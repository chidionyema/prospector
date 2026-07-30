"""Near-duplicate detection and deduplication (Part 3).

Pure stdlib — no model required. Compares candidates against each other
(intra-batch) and against an existing catalogue to keep results fresh.

Two complementary signals, because neither alone is enough:
  * char ratio  (difflib.SequenceMatcher) — catches small edits of the same
    wording, but is blind to the SAME idea reworded ("Retiree's Garden Legacy"
    vs "Retiree Garden Harvest Share" score only ~0.43).
  * token overlap (Jaccard on content words) — catches reworded same-idea
    titles that char ratio misses, while genuinely distinct ideas share no
    content words and score ~0.0.
A pair is a near-duplicate if EITHER signal fires. The token signal is opt-in
(token_threshold=None disables it) so the kill fast-path can stay char-only.
"""
from __future__ import annotations

import difflib
import re

from .models import Candidate
from .telemetry import logger, track_latency

# Articles/prepositions plus generic business-pitch boilerplate that pollutes
# one-liners ("service", "revenue", "per month", "customers", "fee"...). Stripping
# these leaves the words that actually name the idea, so Jaccard separates the
# same-idea-reworded clusters from genuinely distinct ideas. (Calibrated against
# the live catalogue: dupe pairs >=0.38, distinct pairs ~0.00 — see test_dedup.)
_STOPWORDS = frozenset("""the a an of for to and your you my our with on in is are be that this it
from each into them their as at by or who not no get got make made help helps using use used per
via more most then than so we i they he she but if can will would should out up down over under
about across service services solo operator local business idea customers customer revenue money
cash income month monthly week day daily year clients client market niche people small owner owners
run running build building start starting offer offering provide providing turn turning without
need needs want high low new first one two free paid fee fees price pricing cost costs sell selling
buy buying time agent app tool platform system""".split())

_WORD = re.compile(r"[a-z]+")


def _content_tokens(text: str) -> frozenset[str]:
    """Significant (non-stopword, length>2) lowercase words in `text`."""
    return frozenset(w for w in _WORD.findall(text.lower())
                     if w not in _STOPWORDS and len(w) > 2)


def _token_overlap(a: str, b: str) -> float:
    """Jaccard similarity of the content-word sets of a and b (0.0..1.0)."""
    ta, tb = _content_tokens(a), _content_tokens(b)
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def is_near_duplicate(
    a: str,
    b: str,
    threshold: float = 0.85,
    token_threshold: float | None = None,
) -> bool:
    """Return True when a and b are near-duplicates.

    A pair is a duplicate if the char-ratio (difflib.SequenceMatcher, symmetric,
    0.0..1.0) is at or above `threshold`, OR — when `token_threshold` is set —
    the content-word Jaccard overlap is at or above `token_threshold`. The token
    signal is opt-in so callers that need strict char-only matching (the kill
    fast-path) keep their behaviour by leaving `token_threshold` None.
    """
    ratio = difflib.SequenceMatcher(None, a.lower(), b.lower(), autojunk=False).ratio()
    if ratio >= threshold:
        return True
    if token_threshold is not None and _token_overlap(a, b) >= token_threshold:
        return True
    return False


def _fingerprint(cand: Candidate) -> str:
    """Combine title and one_liner into a single comparison string."""
    return f"{cand.title} {cand.one_liner}".strip()


def _normalise_catalogue(
    catalogue_titles: "list[str] | list[tuple[str, str]]",
    default_market: str,
) -> list[tuple[str, str]]:
    """Accept either the legacy list[str] or list[(market, fingerprint)].

    Keeping both shapes is deliberate: the legacy form is used across the existing
    tests and by any caller that has no market context, and rewriting them would be
    churn with no benefit. A legacy entry is attributed to the default market.
    """
    out: list[tuple[str, str]] = []
    for entry in catalogue_titles or []:
        if isinstance(entry, (tuple, list)) and len(entry) == 2:
            market, text = entry
        else:
            market, text = default_market, entry
        out.append(((market or default_market or "").lower(), str(text).lower()))
    return out


@track_latency(name="dedup")
def dedup(
    candidates: list[Candidate],
    catalogue_titles: "list[str] | list[tuple[str, str]]",
    threshold: float = 0.85,
    token_threshold: float | None = 0.34,
    default_market: str = "",
) -> tuple[list[Candidate], list[tuple[Candidate, str]]]:
    """Remove near-duplicates from candidates, WITHIN each market.

    Each candidate is compared against:
      1. Every catalogue entry in the SAME market (cross-batch dedup).
      2. Every candidate already accepted in this batch, in the same market.

    Catalogue dedup runs BOTH signals (char ratio + content-word overlap): char
    ratio alone is blind to the same idea reworded, which is exactly how the live
    catalogue accumulated 4 "retiree garden harvest" variants + 2 "probate
    clear-out" variants that all scored well under the char threshold.

    MARKET SCOPING: the same idea in a different jurisdiction is NOT a duplicate —
    "mobile notary bond, Texas" and the UK equivalent are different opportunities
    resting on different evidence. Without this, opening a market would be silently
    throttled by the dedup gate: the second market's candidates would collide with the
    first's and vanish, with nothing in the logs to say why.

    Args:
        candidates: Incoming candidates in priority order (order is preserved).
        catalogue_titles: Either (market, fingerprint) pairs, or bare fingerprint
            strings (legacy), which are attributed to `default_market`.
        threshold: Char-ratio at or above which two entries are duplicates.
        token_threshold: Content-word Jaccard at or above which two entries are
            duplicates (None disables the token signal). Calibrated to 0.34 so
            same-idea-reworded clusters collapse but distinct ideas survive.
        default_market: Market assigned to entries/candidates carrying no market.

    Returns:
        (unique_candidates, dropped_pairs) where dropped_pairs is a list of
        (dropped_candidate, matched_existing_title) tuples.
    """
    logger.info(f"Dedup started for {len(candidates)} candidates", extra={"batch_size": len(candidates)})

    unique: list[Candidate] = []
    dropped: list[tuple[Candidate, str]] = []

    default_market = (default_market or "").lower()
    catalogue_fps = _normalise_catalogue(catalogue_titles, default_market)

    for cand in candidates:
        fp = _fingerprint(cand)
        cand_market = (getattr(cand, "market", "") or default_market).lower()

        matched: str | None = None

        # 1. Compare against existing catalogue entries in the SAME market.
        for cat_market, cat_fp in catalogue_fps:
            if cat_market != cand_market:
                continue
            if is_near_duplicate(fp, cat_fp, threshold, token_threshold):
                matched = cat_fp
                break

        # 2. Compare against already-accepted candidates in this batch, same market.
        if matched is None:
            for kept in unique:
                if (getattr(kept, "market", "") or default_market).lower() != cand_market:
                    continue
                kept_fp = _fingerprint(kept)
                if is_near_duplicate(fp, kept_fp, threshold, token_threshold):
                    matched = kept_fp
                    break

        if matched is not None:
            dropped.append((cand, matched))
        else:
            unique.append(cand)

    logger.info(f"Dedup complete: {len(unique)} unique, {len(dropped)} dropped", 
                extra={"unique": len(unique), "dropped": len(dropped),
                       "dropped_by_market": drops_by_market(dropped)})
    return unique, dropped


def drops_by_market(dropped: list[tuple[Candidate, str]]) -> dict[str, int]:
    """Dedup drops keyed by market — the diagnostic that makes a market being
    throttled by dedup visible instead of silent."""
    out: dict[str, int] = {}
    for cand, _ in dropped:
        key = getattr(cand, "market", "") or ""
        out[key] = out.get(key, 0) + 1
    return out
