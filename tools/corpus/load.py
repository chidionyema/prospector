"""Loading a corpus from a directory of .txt files, with boilerplate removed.

WHY BOILERPLATE REMOVAL IS PART OF LOADING, not of fetching. Both corpora repeat lines.
Every FOS decision closes with the same statutory paragraph; every dossier of ours repeats
the same scaffolding. Left in, those lines dominate a 4-gram keyness table and the result
reads as "our generator over-uses the phrase it is required to print" — a fact about
templates, not about voice.

The rule is symmetric and measured, never a list of strings someone typed: a line is
boilerplate if it appears in more than `threshold` of the corpus's documents. Both corpora
go through the identical filter, so neither is advantaged.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

DEFAULT_THRESHOLD = 0.30
_MIN_BOILERPLATE_CHARS = 12  # "Yes" and "The complaint" are headings, not prose to strip


def load_corpus(directory: str | Path, threshold: float = DEFAULT_THRESHOLD,
                strip: bool = True) -> tuple[list[str], list[str]]:
    """Return (documents, dropped_lines). Documents keep their paragraph breaks."""
    files = sorted(Path(directory).expanduser().glob("*.txt"))
    raw = [f.read_text(errors="replace") for f in files]
    if not strip or len(raw) < 5:
        return raw, []

    df: Counter[str] = Counter()
    for doc in raw:
        seen = {ln.strip() for ln in doc.splitlines() if len(ln.strip()) >= _MIN_BOILERPLATE_CHARS}
        df.update(seen)
    cutoff = threshold * len(raw)
    dropped = {line for line, n in df.items() if n > cutoff}

    cleaned: list[str] = []
    for doc in raw:
        keep = [ln for ln in doc.splitlines() if ln.strip() not in dropped]
        cleaned.append("\n".join(keep))
    return cleaned, sorted(dropped)
