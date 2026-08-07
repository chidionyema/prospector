"""E6 — local-embedding prescreen prefilter, SHADOW MODE ONLY (programme doc §3, §2.4).

The bet (`docs/COMMERCIAL_READINESS_PROGRAM.md` §3, row E6): a local embedding
prefilter can drop >=20% of LLM prescreen calls at no PASS loss. The register
mandates **shadow-mode first (log, don't act)**, and this module implements only
that half. It computes what it WOULD have dropped and writes it next to what the
LLM prescreen actually decided; it returns nothing that any caller consumes for a
decision. `prescreen.prescreen()` calls `record()` AFTER its result tuple is
built, and discards the return value — so the prefilter is structurally incapable
of changing a decision, not merely disciplined about it
(`tests/unit/test_prescreen_prefilter.py::test_prescreen_result_identical_with_shadow_on_and_off`).

Why shadow first is not ceremony: an unproven prefilter that acts silently kills
good candidates, and the pipeline's own rule is that nothing is killed at
generation time (project CLAUDE.md, "Creativity lives in generation").

EMBEDDING BACKEND — measured 2026-08-07, no network:
  `sentence_transformers`, `torch`, `transformers`, `onnxruntime`, `model2vec`
  and `fastembed` are all ABSENT from `.venv`, and the local `ollama` install
  carries no embedding model (qwen2.5-coder / gemma3 / gemma2 / llama3.2 are
  chat models). Pulling nomic-embed-text (~274MB) or Qwen3-Embedding-0.6B
  (~1.5GB) is a download, which this task forbids. So the DEFAULT backend is
  `lexical`: a sparse bag-of-content-words + character-trigram vector built from
  the SAME tokeniser dedup already uses (`dedup._content_tokens`), scored with
  the SAME cosine the DPP selector already uses (`novelty.cosine_similarity`).
  There is exactly one similarity implementation in this repo and this reuses it
  rather than adding a second one.
  `backend: sentence_transformers` is accepted and will use a real dense model
  IF one is ever installed; when the import fails it logs and degrades to
  `lexical`, and every shadow row records `backend_used` so a mixed log is never
  ambiguous about which encoder produced a score.

HOW THE SCORE IS FORMED (prequential kNN, zero LLM, zero network):
  There is no labelled corpus of "obvious near-misses" on disk, so the prefilter
  learns from the LLM decisions it is shadowing. For each candidate it scores
  against the exemplars accumulated SO FAR (never itself), then appends this
  candidate's own LLM outcome as a new exemplar. That ordering is what makes the
  logged agreement an honest out-of-sample number rather than a memorised one.
  score = similarity-weighted keep-rate of the k nearest exemplars above
  `min_similarity`. Below `min_exemplars` neighbours the prefilter ABSTAINS
  (`would_drop=False`, `abstain_reason` recorded) — cold start never drops.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .dedup import _content_tokens
from .models import Candidate
from .novelty import cosine_similarity
from .telemetry import logger

# Agreement labels written to every shadow row. "false_drop" is the metric that
# matters for "no PASS loss": a candidate the LLM kept that the prefilter would
# have thrown away before the LLM ever saw it.
AGREE_DROP = "agree_drop"
AGREE_KEEP = "agree_keep"
DISAGREE_FALSE_DROP = "disagree_false_drop"
DISAGREE_MISSED_DROP = "disagree_missed_drop"

_DEFAULT_LOG_SUBDIR = "prescreen_shadow"


# --------------------------------------------------------------------------- #
# Vectorisation
# --------------------------------------------------------------------------- #

def _char_trigrams(text: str) -> list[str]:
    """Whitespace-normalised character trigrams (same shape as `novelty._text_similarity`)."""
    clean = " ".join(str(text).lower().split())
    return [clean[i:i + 3] for i in range(len(clean) - 2)]


def lexical_vector(text: str) -> dict[str, float]:
    """L2-normalised sparse vector: dedup's content words + character trigrams.

    Content words carry the idea's identity (dedup calibrated that stopword list
    against the live catalogue); trigrams carry morphology so "planner" and
    "planning" are not orthogonal. Weight 2.0 on words keeps the word signal
    dominant over the much denser trigram signal.
    """
    feats: dict[str, float] = {}
    for tok in _content_tokens(text):
        feats["w:" + tok] = feats.get("w:" + tok, 0.0) + 2.0
    for tri in _char_trigrams(text):
        feats["c:" + tri] = feats.get("c:" + tri, 0.0) + 1.0
    norm = sum(v * v for v in feats.values()) ** 0.5
    if norm == 0.0:
        return {}
    return {k: v / norm for k, v in feats.items()}


def _sparse_cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine over sparse vectors, delegated to `novelty.cosine_similarity`.

    Aligning both vectors onto the union of their keys and handing the dense
    lists to the existing helper keeps ONE cosine implementation in the repo.
    """
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    return cosine_similarity([a.get(k, 0.0) for k in keys],
                             [b.get(k, 0.0) for k in keys])


class LexicalEmbedder:
    """Offline, deterministic, dependency-free encoder (see module docstring)."""

    name = "lexical"

    def encode(self, text: str) -> dict[str, float]:
        return lexical_vector(text)


def load_embedder(backend: str) -> Any:
    """Return an encoder for `backend`, degrading to lexical with a logged reason.

    A missing dense model must never break prescreen — this whole module runs
    inside a keep-biased gate. Degradation is visible in `backend_used` on every
    row, so the experiment can never silently attribute lexical numbers to a
    dense model.
    """
    backend = (backend or "lexical").strip()
    if backend in ("", "lexical"):
        return LexicalEmbedder()
    if backend.startswith("sentence_transformers"):
        model_name = backend.partition(":")[2] or "nomic-ai/nomic-embed-text-v2-moe"
        try:  # pragma: no cover - no such package is installed in this venv
            from sentence_transformers import SentenceTransformer  # type: ignore

            model = SentenceTransformer(model_name)

            class _STEmbedder:
                name = f"sentence_transformers:{model_name}"

                def encode(self, text: str) -> dict[str, float]:
                    vec = list(model.encode(text))
                    return {str(i): float(v) for i, v in enumerate(vec)}

            return _STEmbedder()
        except Exception as e:
            logger.warning(
                f"prescreen prefilter: backend {backend!r} unavailable ({e}); "
                f"falling back to lexical")
            return LexicalEmbedder()
    logger.warning(f"prescreen prefilter: unknown backend {backend!r}; using lexical")
    return LexicalEmbedder()


# --------------------------------------------------------------------------- #
# Settings + shadow recorder
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PrefilterSettings:
    """Resolved `config.yaml prescreen_prefilter` block. Defaults = OFF, inert."""
    shadow_mode: bool = False
    backend: str = "lexical"
    threshold: float = 0.35
    neighbours: int = 5
    min_similarity: float = 0.15
    min_exemplars: int = 20
    max_exemplars: int = 500
    log_dir: str = ""


def settings_from_config(cfg: Any) -> PrefilterSettings:
    """Read the block off a Config (or any object/dict carrying it). Never raises."""
    raw = getattr(cfg, "prescreen_prefilter", None)
    if isinstance(raw, PrefilterSettings):
        return raw
    if not isinstance(raw, dict):
        return PrefilterSettings()
    d = PrefilterSettings()
    return PrefilterSettings(
        shadow_mode=bool(raw.get("shadow_mode", d.shadow_mode)),
        backend=str(raw.get("backend", d.backend)),
        threshold=float(raw.get("threshold", d.threshold)),
        neighbours=int(raw.get("neighbours", d.neighbours)),
        min_similarity=float(raw.get("min_similarity", d.min_similarity)),
        min_exemplars=int(raw.get("min_exemplars", d.min_exemplars)),
        max_exemplars=int(raw.get("max_exemplars", d.max_exemplars)),
        log_dir=str(raw.get("log_dir", d.log_dir) or ""),
    )


def resolve_log_path(cfg: Any, settings: PrefilterSettings) -> Path:
    """Where the shadow log is written.

    `prescreen_prefilter.log_dir` wins; otherwise `<cfg.store_dir>/prescreen_shadow`,
    which already honours `PROSPECTOR_STORE_DIR`. Nothing here is bound at import
    time — module-level path constants are exactly how tests have polluted
    production state in this repo before (memory: tests-polluted-the-durable-ledger).
    """
    if settings.log_dir:
        base = Path(settings.log_dir)
    else:
        store_dir = getattr(cfg, "store_dir", None)
        base = Path(store_dir) if store_dir else Path("store")
        base = base / _DEFAULT_LOG_SUBDIR
    return base / f"shadow-{time.strftime('%Y-%m')}.jsonl"


def _text_of(cand: Candidate) -> str:
    return f"{getattr(cand, 'title', '')} {getattr(cand, 'one_liner', '')}".strip()


class PrescreenShadow:
    """Accumulates exemplars from real LLM prescreen outcomes and logs would-drops.

    Instances are per-log-path and thread-safe: `prescreen()` runs under a
    ThreadPoolExecutor in `run.py:766`, so both the exemplar list and the append
    to the JSONL are guarded by one lock. Every write is a single line built in
    memory then written in one `write()` call, so a torn row is not possible
    from this side.
    """

    def __init__(
        self,
        log_path: Path,
        settings: PrefilterSettings | None = None,
        embedder: Any | None = None,
    ) -> None:
        self.log_path = Path(log_path)
        self.settings = settings or PrefilterSettings()
        self.embedder = embedder or load_embedder(self.settings.backend)
        self._lock = threading.Lock()
        self._exemplars: list[tuple[dict[str, float], bool]] = []
        self._seeded = False

    # -- exemplar corpus ---------------------------------------------------- #

    def _seed_from_log(self) -> None:
        """Load prior rows so agreement accumulates across runs, not just within one."""
        self._seeded = True
        try:
            if not self.log_path.exists():
                return
            with self.log_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue  # a partial line from another writer is not fatal
                    text = str(row.get("text") or "")
                    keep = row.get("llm_keep")
                    if not text or not isinstance(keep, bool):
                        continue
                    self._exemplars.append((self.embedder.encode(text), keep))
            if len(self._exemplars) > self.settings.max_exemplars:
                self._exemplars = self._exemplars[-self.settings.max_exemplars:]
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"prescreen prefilter: could not seed exemplars: {e}")

    # -- scoring ------------------------------------------------------------ #

    def score(self, text: str) -> tuple[Optional[float], int, str]:
        """(score, neighbours_used, abstain_reason). score None => abstained.

        Similarity-weighted keep-rate over the k nearest exemplars above
        `min_similarity`. Abstains — never drops — on an empty vector, a cold
        corpus, or no neighbour near enough to say anything.
        """
        vec = self.embedder.encode(text)
        if not vec:
            return None, 0, "empty_vector"
        if len(self._exemplars) < self.settings.min_exemplars:
            return None, 0, "cold_start"
        sims = [(_sparse_cosine(vec, ev), keep) for ev, keep in self._exemplars]
        sims = [s for s in sims if s[0] >= self.settings.min_similarity]
        if not sims:
            return None, 0, "no_neighbours"
        sims.sort(key=lambda s: s[0], reverse=True)
        top = sims[: max(1, self.settings.neighbours)]
        total = sum(s for s, _ in top)
        if total <= 0.0:
            return None, len(top), "zero_weight"
        keep_mass = sum(s for s, keep in top if keep)
        return keep_mass / total, len(top), ""

    # -- the shadow record -------------------------------------------------- #

    def record(
        self,
        cand: Candidate,
        *,
        llm_keep: bool,
        llm_score: float,
        llm_reason: str,
        llm_called: bool,
    ) -> dict[str, Any]:
        """Score, log, then learn. Returns the row purely for tests/analysis.

        NOTHING in the pipeline consumes the return value — `prescreen()` throws
        it away. Adding this candidate to the corpus AFTER scoring is what keeps
        the logged agreement out-of-sample.
        """
        with self._lock:
            if not self._seeded:
                self._seed_from_log()
            score, n_used, abstain = self.score(_text_of(cand))
            would_drop = bool(score is not None and score < self.settings.threshold)
            if would_drop:
                agreement = AGREE_DROP if not llm_keep else DISAGREE_FALSE_DROP
            else:
                agreement = AGREE_KEEP if llm_keep else DISAGREE_MISSED_DROP
            row = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "candidate_id": getattr(cand, "candidate_id", ""),
                "title": getattr(cand, "title", ""),
                "market": getattr(cand, "market", "") or "",
                "text": _text_of(cand),
                "backend_used": getattr(self.embedder, "name", "unknown"),
                "threshold": self.settings.threshold,
                "prefilter_score": score,
                "neighbours_used": n_used,
                "abstained": score is None,
                "abstain_reason": abstain,
                "would_drop": would_drop,
                "llm_called": bool(llm_called),
                "llm_keep": bool(llm_keep),
                "llm_score": float(llm_score),
                "llm_reason": str(llm_reason)[:300],
                "agreement": agreement,
                "shadow_only": True,
            }
            self._write(row)
            # Learn from the decision we just shadowed (prequential).
            vec = self.embedder.encode(_text_of(cand))
            if vec:
                self._exemplars.append((vec, bool(llm_keep)))
                if len(self._exemplars) > self.settings.max_exemplars:
                    del self._exemplars[0]
            return row

    def _write(self, row: dict[str, Any]) -> None:
        line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)


# --------------------------------------------------------------------------- #
# Process-wide accessor + the ONE entry point prescreen() calls
# --------------------------------------------------------------------------- #

_INSTANCES: dict[str, PrescreenShadow] = {}
_INSTANCES_LOCK = threading.Lock()


def get_shadow(cfg: Any) -> Optional[PrescreenShadow]:
    """Cached recorder for this config's log path, or None when shadow mode is off."""
    settings = settings_from_config(cfg)
    if not settings.shadow_mode:
        return None
    path = resolve_log_path(cfg, settings)
    key = str(path)
    with _INSTANCES_LOCK:
        inst = _INSTANCES.get(key)
        if inst is None or inst.settings != settings:
            inst = PrescreenShadow(path, settings)
            _INSTANCES[key] = inst
        return inst


def reset_cache() -> None:
    """Drop cached recorders (tests, and any process that swaps store dirs)."""
    with _INSTANCES_LOCK:
        _INSTANCES.clear()


def record_shadow(
    cfg: Any,
    cand: Candidate,
    *,
    llm_keep: bool,
    llm_score: float,
    llm_reason: str,
    llm_called: bool,
) -> Optional[dict[str, Any]]:
    """Fire-and-forget shadow record. Returns None when off or on ANY failure.

    Every exception is swallowed on purpose: this observer sits inside a
    keep-biased gate, and an observability feature that can fail a prescreen is
    a decision change by another name.
    """
    try:
        shadow = get_shadow(cfg)
        if shadow is None:
            return None
        return shadow.record(
            cand,
            llm_keep=llm_keep,
            llm_score=llm_score,
            llm_reason=llm_reason,
            llm_called=llm_called,
        )
    except Exception as e:
        logger.warning(f"prescreen prefilter shadow record failed: {e}")
        return None


# --------------------------------------------------------------------------- #
# Read side — the E6 metric
# --------------------------------------------------------------------------- #

def summarise_shadow_log(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Agreement counters for E6's acceptance metric.

    `llm_calls_saved_pct` is measured over rows where the LLM was ACTUALLY
    called (structural rejects never reach stage 3, so counting them would
    inflate the saving). `false_drop_rate` is the "no PASS loss" side: the share
    of LLM-kept candidates the prefilter would have discarded.
    """
    p = Path(path)
    counts = {AGREE_DROP: 0, AGREE_KEEP: 0, DISAGREE_FALSE_DROP: 0, DISAGREE_MISSED_DROP: 0}
    rows = llm_called = would_drop_llm_called = abstained = llm_kept = false_drops = 0
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                rows += 1
                counts[row.get("agreement", "")] = counts.get(row.get("agreement", ""), 0) + 1
                if row.get("abstained"):
                    abstained += 1
                if row.get("llm_called"):
                    llm_called += 1
                    if row.get("would_drop"):
                        would_drop_llm_called += 1
                if row.get("llm_keep"):
                    llm_kept += 1
                    if row.get("would_drop"):
                        false_drops += 1
    return {
        "rows": rows,
        "abstained": abstained,
        "llm_called": llm_called,
        "would_drop_llm_called": would_drop_llm_called,
        "llm_calls_saved_pct": (100.0 * would_drop_llm_called / llm_called) if llm_called else 0.0,
        "llm_kept": llm_kept,
        "false_drops": false_drops,
        "false_drop_rate": (100.0 * false_drops / llm_kept) if llm_kept else 0.0,
        "agreement_counts": counts,
    }
