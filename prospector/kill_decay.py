"""Dead-loop prevention for Prospector's recursive self-improvement.

Prevents generation from spiraling into ever-narrower output by:
1. Decaying old kill reasons exponentially (allows domains to re-enter)
2. Monitoring domain diversity (Shannon entropy) and triggering re-seeding
3. Identifying stale domains for periodic forced re-exploration

Part of the production-grade self-improvement infrastructure (Priority 7).
"""

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


#: `store/dossiers/` is NOT a dossier population. The pack gate writes a
#: `<id>.lint.json` receipt into the same directory (bridge.py:1256), and 116 of the 123
#: non-dossier files measured there on 2026-08-20 carry a `market` field — a jurisdiction
#: code like "uk" or "us-ga", not a business domain. Every domain fallback below reads
#: `market`, so without this test a lint receipt is counted as a real domain.
#:
#: Measured on the live store the same day, over the newest-50 window this module uses:
#: 31 of the 50 files were lint receipts, entropy read 1.9334 ("ok") against a true
#: dossiers-only entropy of 0.0 ("force_reseed"), and ALL five non-"unknown" domains came
#: from lint receipts. The brake did not merely drift; it read the opposite verdict.
#:
#: The test is on CONTENT, not on the filename suffix, because the next artifact somebody
#: writes into this directory will have a different suffix and the same effect.
def _is_dossier(obj: object) -> bool:
    """True if this parsed JSON is a dossier rather than another artifact in the same directory."""
    return isinstance(obj, dict) and ("checks" in obj or "candidate" in obj)



def get_active_steers(
    store_path: Path,
    half_life_days: int = 30,
    min_strength: float = 0.01,
) -> dict[str, float]:
    """Compute decayed kill-reason steer strengths.

    Reads kill dossiers from the store, extracts the domain/category that
    triggered the kill, and applies exponential decay based on how long ago
    the kill happened.

    Args:
        store_path: Path to the Prospector store directory.
        half_life_days: Number of days after which a kill reason's strength
                        is halved. Default 30 days.
        min_strength: Minimum strength threshold; steers below this are
                      dropped. Default 0.01.

    Returns:
        Dict of {domain: decayed_strength} sorted by strength descending.
    """
    dossiers_dir = store_path / "dossiers"
    if not dossiers_dir.is_dir():
        return {}

    now = datetime.now(timezone.utc)
    decay_lambda = math.log(2) / half_life_days
    domain_strengths: dict[str, float] = {}

    for f in dossiers_dir.glob("*.json"):
        try:
            dossier = json.loads(f.read_text())
            if not _is_dossier(dossier):
                continue
            verdict = dossier.get("verdict", "")
            if verdict.upper() != "KILL":
                continue

            domain = (
                dossier.get("domain")
                or dossier.get("category")
                or dossier.get("sector")
                or dossier.get("market")
            )
            if not domain:
                tags = dossier.get("tags", [])
                if tags:
                    domain = tags[0] if isinstance(tags, list) else str(tags)
            if not domain:
                idea = dossier.get("idea", {})
                if isinstance(idea, dict):
                    domain = idea.get("domain") or idea.get("sector") or ""
                elif isinstance(idea, str):
                    domain = idea[:50]
            if not domain:
                continue

            domain = str(domain).strip().lower()

            ts_str = (
                dossier.get("killed_at")
                or dossier.get("timestamp")
                or dossier.get("ts")
                or ""
            )
            if not ts_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            days_ago = (now - ts).total_seconds() / 86400
            if days_ago < 0:
                days_ago = 0

            strength = math.exp(-decay_lambda * days_ago)
            domain_strengths[domain] = domain_strengths.get(domain, 0.0) + strength

        except (json.JSONDecodeError, OSError):
            continue

    if not domain_strengths:
        return {}

    max_strength = max(domain_strengths.values())
    if max_strength > 0:
        domain_strengths = {
            k: v / max_strength for k, v in domain_strengths.items()
        }

    result = {
        k: round(v, 4)
        for k, v in sorted(
            domain_strengths.items(), key=lambda x: x[1], reverse=True
        )
        if v >= min_strength
    }
    return result


def check_diversity_floor(
    store_path: Path,
    window: int = 50,
    floor: float = 0.5,
) -> dict:
    """Check if domain diversity has dropped below the safety floor.

    Computes Shannon entropy over the domain distribution of recent dossiers.
    If entropy drops below the floor, triggers a force re-seed.

    Returns:
        Dict with entropy, floor, triggered flag, and action recommendation.
    """
    dossiers_dir = store_path / "dossiers"
    if not dossiers_dir.is_dir():
        return {
            "entropy": 0.0,
            "floor": floor,
            "triggered": False,
            "action": "ok",
            "domains": [],
        }

    domains = []
    files = sorted(
        dossiers_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:window]

    for f in files:
        try:
            d = json.loads(f.read_text())
            if not _is_dossier(d):
                continue
            domain = (
                d.get("domain")
                or d.get("category")
                or d.get("sector")
                or d.get("market")
                or "unknown"
            )
            domains.append(str(domain).strip().lower())
        except (json.JSONDecodeError, OSError):
            continue

    if not domains:
        return {
            "entropy": 0.0,
            "floor": floor,
            "triggered": False,
            "action": "ok",
            "domains": [],
        }

    counts = Counter(domains)
    total = len(domains)
    entropy = 0.0
    for count in counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    triggered = entropy < floor
    unique_domains = list(counts.keys())

    return {
        "entropy": round(entropy, 4),
        "floor": floor,
        "triggered": triggered,
        "action": "force_reseed" if triggered else "ok",
        "domains": unique_domains,
        "domain_counts": dict(counts.most_common(10)),
        "total_dossiers": total,
        "unique_domains": len(unique_domains),
    }


def get_stale_domains(
    store_path: Path,
    top_k: int = 5,
    min_days_stale: int = 14,
) -> list[str]:
    """Identify domains that haven't been explored recently.

    Returns list of domain names to re-seed, sorted most-stale first.
    """
    dossiers_dir = store_path / "dossiers"
    if not dossiers_dir.is_dir():
        return []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=min_days_stale)

    domain_last_seen: dict[str, datetime] = {}
    all_domains: set[str] = set()

    for f in dossiers_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            if not _is_dossier(d):
                continue
            domain = (
                d.get("domain")
                or d.get("category")
                or d.get("sector")
                or d.get("market")
            )
            if not domain:
                continue
            domain = str(domain).strip().lower()
            all_domains.add(domain)

            ts_str = d.get("timestamp") or d.get("ts") or ""
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if domain not in domain_last_seen or ts > domain_last_seen[domain]:
                        domain_last_seen[domain] = ts
                except (ValueError, TypeError):
                    pass
        except (json.JSONDecodeError, OSError):
            continue

    stale = []
    for domain in sorted(all_domains):
        last_seen = domain_last_seen.get(domain)
        if last_seen is None or last_seen < cutoff:
            days_stale = (
                (now - last_seen).total_seconds() / 86400
                if last_seen
                else float("inf")
            )
            stale.append((domain, days_stale))

    stale.sort(key=lambda x: x[1], reverse=True)
    return [domain for domain, _ in stale[:top_k]]


#: Purpose string for the re-vet claim (see prospector/claim_lock.py). The drain
#: (`run.py::_cmd_resume`) and this walker MUST use the same one, or the lock protects nothing.
REVET_PURPOSE = "revet"


def decayed_kill_ids(
    store_path: Path,
    half_life_days: int = 30,
    revisit_below: float = 0.5,
    limit: int | None = None,
) -> list[str]:
    """Candidate ids whose KILL has decayed below `revisit_below` — eligible for a re-vet.

    Same exponential decay as `get_active_steers`, applied per CANDIDATE rather than per
    domain: a kill loses half its weight every `half_life_days`, and once it is weak enough
    the idea is allowed back in front of the moat. Weakest (oldest) first, so a bounded walk
    re-vets the most-decayed kills rather than an arbitrary glob order.
    """
    dossiers_dir = store_path / "dossiers"
    if not dossiers_dir.is_dir():
        return []

    now = datetime.now(timezone.utc)
    decay_lambda = math.log(2) / max(1, half_life_days)
    scored: list[tuple[float, str]] = []

    for f in sorted(dossiers_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        # No `_is_dossier` test here on purpose: `verdict == "KILL"` is already a stronger
        # discriminator. Measured 2026-08-20, 0 of the 123 pack lint receipts in
        # `store/dossiers/` carry a top-level `verdict` key, so they cannot reach this
        # branch. The guard belongs on the three functions above, which fall back to
        # `market` for a domain and would otherwise read a jurisdiction code as one.
        if not isinstance(d, dict) or str(d.get("verdict", "")).upper() != "KILL":
            continue
        cid = str(d.get("candidate_id") or d.get("id") or f.name.split(".")[0]).strip()
        if not cid:
            continue
        ts_str = d.get("killed_at") or d.get("timestamp") or d.get("ts") or ""
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        days_ago = max(0.0, (now - ts).total_seconds() / 86400)
        strength = math.exp(-decay_lambda * days_ago)
        if strength < revisit_below:
            scored.append((strength, cid))

    scored.sort(key=lambda x: x[0])
    ids: list[str] = []
    for _, cid in scored:
        if cid not in ids:
            ids.append(cid)
    return ids[:limit] if limit else ids


def iter_revet_claims(
    store_path: Path,
    cfg=None,
    *,
    half_life_days: int = 30,
    revisit_below: float = 0.5,
    limit: int | None = None,
):
    """Yield each decayed-KILL candidate id this worker EXCLUSIVELY claimed (register R2).

    The claim is held for the duration of the consumer's loop body and released on the way to
    the next item — including when the body raises, because the claim is taken inside a `with`.
    A candidate another worker already holds (a concurrent backlog drain, or a manual
    `vet --resume`) is SKIPPED, not waited on: without this, the drain and the walker both
    picked up the same id and the same re-vet was paid for twice.

    `cfg=None` (or `claim_lock.enabled: false`) yields every id unclaimed — the pre-rail
    behaviour, so this is a drop-in for a caller that has no config to hand.
    """
    from . import claim_lock

    for cid in decayed_kill_ids(store_path, half_life_days, revisit_below, limit):
        with claim_lock.claiming(cid, REVET_PURPOSE, cfg=cfg) as got:
            if not got:
                continue
            yield cid


def re_seed_suggestions(store_path: Path, count: int = 3) -> list[str]:
    """Generate re-seeding suggestions for stale domains."""
    stale = get_stale_domains(store_path, top_k=count * 2)

    suggestions = []
    for domain in stale:
        suggestions.append(
            f"Explore opportunities in {domain}: what has changed in the "
            f"last 30 days that makes this space viable again?"
        )
        if len(suggestions) >= count:
            break

    if not suggestions:
        suggestions = [
            "Explore an emerging technology sector with recent venture funding",
            "Identify underserved market segments in the creator economy",
            "Find opportunities at the intersection of AI and regulated industries",
        ]

    return suggestions[:count]
