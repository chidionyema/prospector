"""Keyness statistics, plus the shared measurement code re-exported for the corpus tools.

THE MEASURING MOVED. Every tokeniser, lexicon and structural measure now lives in
`prospector/prose_measure.py`, because `register_lint` grades packs against the target these
tools produce and the two must count the same way. A target built with one tokeniser and
enforced with another compares tokenisers, not writing. This module re-exports those names
so the corpus tools and their tests read unchanged, and keeps what is genuinely corpus-only:
Dunning's G2, log ratio and n-grams.

No spaCy, no scipy. Log-likelihood is arithmetic and sentence splitting on this genre is a
regex; adding two heavy dependencies to run `math.log` would be its own kind of defect.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from prospector.prose_measure import (  # noqa: E402,F401  (re-exported on purpose)
    ATTRIB_PHRASES,
    ATTRIB_WORDS,
    FUNCTION_WORDS,
    HEAVY_SENTENCE_COMMAS,
    HEDGES,
    LONG_SENTENCE_WORDS,
    MATTR_WINDOW,
    META_WORDS,
    PUNCT_CLASSES,
    SUBORDINATORS,
    TOKENISER_VERSION,
    Profile,
    classify_item,
    document_measures,
    mattr,
    paragraphs,
    profile,
    sentences,
    tokens,
)


def ngrams(toks: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]


def log_likelihood(a: int, b: int, total_a: int, total_b: int) -> float:
    """Dunning's G2 for one item, SIGNED: positive means over-used in corpus A.

    a/b are the item's frequency in each corpus, total_a/total_b the corpus sizes. This is
    the standard keyness statistic — the same number AntConc reports.
    """
    if total_a <= 0 or total_b <= 0 or (a + b) == 0:
        return 0.0
    e_a = total_a * (a + b) / (total_a + total_b)
    e_b = total_b * (a + b) / (total_a + total_b)
    g2 = 0.0
    if a:
        g2 += a * math.log(a / e_a)
    if b:
        g2 += b * math.log(b / e_b)
    g2 *= 2
    over_in_a = (a / total_a) >= (b / total_b)
    return g2 if over_in_a else -g2


def log_ratio(a: int, b: int, total_a: int, total_b: int) -> float:
    """Effect size to sit beside G2. G2 alone rewards sheer frequency: on a 500k-word
    corpus a trivial difference on a very common word clears any significance threshold.
    Log ratio says how many times more often, which is what a writer can act on.
    """
    fa = (a or 0.5) / total_a
    fb = (b or 0.5) / total_b
    return math.log2(fa / fb)
