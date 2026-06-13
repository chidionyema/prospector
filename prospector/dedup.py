"""Near-duplicate detection and deduplication (Part 3).

Pure stdlib — no model required. Compares candidates against each other
(intra-batch) and against an existing catalogue to keep results fresh.
"""
from __future__ import annotations

import difflib

from .models import Candidate
from .telemetry import logger, track_latency


def is_near_duplicate(a: str, b: str, threshold: float = 0.85) -> bool:
    """Return True when a and b are near-duplicates.

    Uses difflib.SequenceMatcher ratio, which is fast and stdlib-only.
    The ratio is symmetric and ranges 0.0 (nothing in common) to 1.0 (identical).
    """
    ratio = difflib.SequenceMatcher(None, a.lower(), b.lower(), autojunk=False).ratio()
    return ratio >= threshold


def _fingerprint(cand: Candidate) -> str:
    """Combine title and one_liner into a single comparison string."""
    return f"{cand.title} {cand.one_liner}".strip()


@track_latency(name="dedup")
def dedup(
    candidates: list[Candidate],
    catalogue_titles: list[str],
    threshold: float = 0.85,
) -> tuple[list[Candidate], list[tuple[Candidate, str]]]:
    """Remove near-duplicates from candidates.

    Each candidate is compared against:
      1. Every entry in catalogue_titles (existing catalogue, cross-batch dedup).
      2. Every candidate already accepted in this batch (intra-batch dedup).

    Args:
        candidates: Incoming candidates in priority order (order is preserved).
        catalogue_titles: Titles (or title+one_liner strings) of already-stored
            opportunities.
        threshold: Similarity ratio at or above which two entries are duplicates.

    Returns:
        (unique_candidates, dropped_pairs) where dropped_pairs is a list of
        (dropped_candidate, matched_existing_title) tuples.
    """
    logger.info(f"Dedup started for {len(candidates)} candidates", extra={"batch_size": len(candidates)})
    
    unique: list[Candidate] = []
    dropped: list[tuple[Candidate, str]] = []

    # Pre-compute fingerprints for the catalogue to avoid repeated concatenation.
    catalogue_fps: list[str] = [t.lower() for t in catalogue_titles]

    for cand in candidates:
        fp = _fingerprint(cand)

        matched: str | None = None

        # 1. Compare against existing catalogue.
        for cat_fp in catalogue_fps:
            if is_near_duplicate(fp, cat_fp, threshold):
                matched = cat_fp
                break

        # 2. Compare against already-accepted candidates in this batch.
        if matched is None:
            for kept in unique:
                kept_fp = _fingerprint(kept)
                if is_near_duplicate(fp, kept_fp, threshold):
                    matched = kept_fp
                    break

        if matched is not None:
            dropped.append((cand, matched))
        else:
            unique.append(cand)

    logger.info(f"Dedup complete: {len(unique)} unique, {len(dropped)} dropped", 
                extra={"unique": len(unique), "dropped": len(dropped)})
    return unique, dropped
