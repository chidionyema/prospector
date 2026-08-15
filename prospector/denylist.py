"""Exhausted-family denial constraints (G3).

The adaptive failure-mode window (20 rows) FORGETS: families killed by the same
market structure stay buried in history and re-surface on every fresh signal.
This module mines the FULL kill corpus into a standing denial list, cached on
disk and refreshed only as kills accumulate. It reads only the store INDEX
rows — never the per-dossier JSON, because it runs on every generation call
and must not pay that cost.

DENIAL PROMPTING (arXiv:2407.09007): constraints drive novelty. A standing
list of proven-dead families, surfaced as a hard directive at generation time,
forces the model away from shapes it would otherwise re-propose.

This module NEVER raises into the generation path and NEVER kills anything
itself — it only steers generation away from proven-dead families. Cache I/O
is wrapped, so a stale or unwritable cache is logged and ignored, not fatal.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .dedup import _content_tokens
from .diversity import generation_artifact_dir
from .models import Decision
from .telemetry import logger

# Gates meaning "the FAMILY is structurally dead" (vs. "evidence was thin for
# THIS idea"). A min_composite failure is per-idea and doesn't generalise; the
# three below indicate a shape that the moat refuses, run after run.
FAMILY_GATES = frozenset({"value_durability", "incumbency", "adversarial"})


def _rows_tokens(row: dict) -> frozenset:
    """Tokenise a store INDEX row for clustering.

    The index row carries title + one_liner as flat strings, so the same
    `dedup._content_tokens` signal (content words, stopwords stripped) applies.
    Empty token sets are filtered by the caller — a row with no signal cannot
    seed a family.
    """
    return _content_tokens(f"{row.get('title', '') or ''} "
                           f"{row.get('one_liner', '') or ''}")


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Local Jaccard — same definition as diversity._jaccard; declared here so
    this module does not import across siblings and pick up an import cycle
    with the diversity meter."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def build_families(
    kill_rows: list[dict],
    pass_rows: list[dict],
    *,
    min_family_size: int = 3,
    token_threshold: float = 0.34,
) -> list[dict]:
    """Cluster recent KILL rows into exhausted families.

    Filter kill_rows to those whose gate_fired is in FAMILY_GATES and which
    have a non-empty token set, sort newest-first, then greedy-cluster by
    content-token Jaccard >= token_threshold. A family is a cluster of size
    >= min_family_size; its label is the four most frequent content tokens
    across its members (ties broken alphabetically), its example is the
    NEWEST member's title, and its kills is the cluster size.

    PASS EXCLUSION: a family with a real survivor (any pass_row's token set
    scoring >= token_threshold against the cluster seed) is dropped. A
    family that produced a survivor is not exhausted — the moat let one
    variant through, so the shape is not categorically dead.

    Returns families sorted by kills desc (most-dead first), so the directive
    lists the strongest constraints at the top.
    """
    eligible = [r for r in kill_rows
                if (r.get("gate_fired") in FAMILY_GATES)
                and bool(_rows_tokens(r))]
    eligible.sort(key=lambda r: r.get("created_at", "") or "", reverse=True)

    clusters: list[list[dict]] = []   # members in insertion order
    seeds: list[frozenset] = []
    for row in eligible:
        toks = _rows_tokens(row)
        joined_idx = -1
        for i, seed in enumerate(seeds):
            if _jaccard(toks, seed) >= token_threshold:
                joined_idx = i
                break
        if joined_idx >= 0:
            clusters[joined_idx].append(row)
        else:
            clusters.append([row])
            seeds.append(toks)

    out: list[dict] = []
    for cluster, seed in zip(clusters, seeds):
        if len(cluster) < min_family_size:
            continue
        # Drop the family if any PASS row overlaps the seed.
        if any(_jaccard(_rows_tokens(p), seed) >= token_threshold for p in pass_rows):
            continue
        # Label: top-4 most-frequent content tokens across members, ties
        # broken alphabetically (Counter.most_count is unstable on ties;
        # re-sort by (-count, token) for determinism).
        token_counts: Counter = Counter()
        for m in cluster:
            token_counts.update(_rows_tokens(m))
        ranked = sorted(token_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        label = " ".join(tok for tok, _ in ranked[:4])
        example = (cluster[0].get("title") or "").strip()   # newest first
        out.append({"label": label, "example": example, "kills": len(cluster)})

    out.sort(key=lambda f: f["kills"], reverse=True)
    return out


def refresh_families(store: Any, cfg: Any) -> list[dict]:
    """Return the cached exhausted-family list, rebuilding it only when enough
    new kills have accumulated to warrant the cost.

    Cache lives at `<store_dir>/exhausted_families.json`. The "watermark" is
    the kill-row count at the time the cache was built; we only rebuild when
    the current kill count exceeds (built_at_kill_count + refresh_every_kills).
    On any error — missing index, unwritable cache, broken JSON — we fail
    open (return an empty list) so generation keeps moving.
    """
    try:
        dcfg = (getattr(cfg, "generation", {}) or {}).get("denylist", {}) or {}
        cache_path = generation_artifact_dir(cfg) / "exhausted_families.json"
        kill_rows = store.all(decision=Decision.KILL.value)
        pass_rows = store.all(decision=Decision.PASS.value)
        refresh_every = int(dcfg.get("refresh_every_kills", 25))

        cache: dict[str, Any] = {}
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                # Corrupted or unreadable cache — treat as cold, but never in silence: this
                # is the only place that would tell us the cache is being rebuilt on EVERY
                # generation call (the cost this cache exists to avoid). Narrow, so a
                # TypeError from a future refactor surfaces instead of reading as corruption.
                logger.error(f"denylist cache unreadable at {cache_path}, rebuilding: {e}",
                             extra={"path": str(cache_path), "error": str(e)})
                cache = {}
            if (len(kill_rows) - int(cache.get("built_at_kill_count", 0))
                    < refresh_every):
                return list(cache.get("families", []) or [])

        families = build_families(
            kill_rows, pass_rows,
            min_family_size=int(dcfg.get("min_family_size", 3)),
        )
        payload = {
            "built_at": datetime.now(timezone.utc).isoformat(),
            "built_at_kill_count": len(kill_rows),
            "families": families,
        }
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as e:
            # Still return the fresh list — but an unwritable cache means every future call
            # re-mines the whole kill corpus, so it is an ERROR, not a `pass`.
            logger.error(f"denylist cache not written to {cache_path}: {e}",
                         extra={"path": str(cache_path), "error": str(e)})
        logger.info(
            f"denylist: {len(families)} exhausted families from {len(kill_rows)} kills"
        )
        return families
    except Exception as e:  # noqa: BLE001
        # Deliberately still broad, and the empty list stays: the module's never-raise-into-
        # generation invariant is a TESTED contract (tests/unit/test_denylist.py:233 passes an
        # arbitrary RuntimeError through a store), and a prompt hint may not take down a run.
        # What changes is the trace — `[]` here is also what "no family qualifies" returns, and
        # at WARNING the two were the same line in a log full of generation chatter. ERROR with
        # a traceback is what tells them apart after the fact.
        logger.exception(f"denylist refresh FAILED, generation loses the denial list: {e}",
                         extra={"error": str(e)})
        return []


def denial_directive(store: Any, cfg: Any) -> str:
    """Return a generation-time directive listing exhausted families, or "".

    Gated by `generation.denylist.enabled` (default off). Capped to
    `max_families` (default 12) so the prompt budget is bounded. Empty when
    the gate is off OR when no family qualifies OR on any error — every
    failure mode returns "" and never breaks generation.
    """
    dcfg = (getattr(cfg, "generation", {}) or {}).get("denylist", {}) or {}
    if not dcfg.get("enabled", False):
        return ""
    try:
        families = refresh_families(store, cfg)
        families = families[: int(dcfg.get("max_families", 12))]
        if not families:
            return ""
        lines = [
            "EXHAUSTED FAMILIES (standing denial list, mined from the full kill "
            "history — these idea families have repeatedly FAILED verification on "
            "structural grounds and have zero survivors; they are DEAD regardless "
            "of sector or wording):"
        ]
        for fam in families:
            lines.append(
                f"- {fam['label']} (e.g. '{fam['example']}'; {fam['kills']} kills)"
            )
        lines.append(
            "Do NOT propose any idea in these families or a near-variant/re-skin "
            "of one. Treat each as a hard constraint and let it force you somewhere "
            "genuinely new."
        )
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001 — same never-raise invariant as `refresh_families`
        # `""` is also what the gate-off and no-family paths return, so a directive that broke
        # was indistinguishable from one that legitimately had nothing to say — at WARNING,
        # next to hundreds of generation lines. ERROR + traceback.
        logger.exception(f"denial_directive FAILED, generation loses the denial list: {e}",
                         extra={"error": str(e)})
        return ""
