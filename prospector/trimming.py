"""Bound the length of model-written prose without cutting a word in half.

WHY THIS EXISTS
---------------
Three call sites capped a model-written `rationale` with a bare character slice::

    rationale=str(data.get("rationale", ""))[:600]

A slice does not know what a word is. Measured on 2026-08-06 across every dossier in
``store/dossiers``: of 7,265 stored rationales, **726 were exactly 600 characters long** and
**720 of those ended without terminal punctuation**. The length histogram makes the mechanism
plain -- the 550-599 bucket holds 259 rationales and the 600 bucket holds 726, a pile-up that no
natural distribution of sentence lengths produces. Every one of those was a verdict argument
stopped mid-word, and they were shipped to the storefront and read by buyers that way.

That matters more here than on an ordinary site. A kill dossier's whole job is to show the
argument that killed an idea; an argument that stops mid-word reads as though the engine ran out
of something, and a reader cannot tell whether the missing half contained the part that undoes
the conclusion. The fix is not to raise the cap -- any cap has this failure at its boundary -- it
is to make the boundary land somewhere a human would have stopped.

WHAT THIS DOES
--------------
Prefer the last sentence that fits. If the text has no sentence boundary in the back portion of
the budget (one very long sentence, a list, a fragment), fall back to the last whole WORD and
append an explicit ellipsis, so a truncated passage announces itself instead of impersonating a
finished one.

LAYERING
--------
This bounds text at the point it is WRITTEN, so it only helps dossiers produced from now on. The
726 already on disk stay damaged, which is why `tools/make_kill_log.py::_whole_sentences` also
repairs at publish time. Two layers, deliberately: one stops new damage, one keeps the existing
damage off the storefront. Neither makes the other redundant.
"""

from __future__ import annotations

import re

__all__ = ["clip_to_sentence", "RATIONALE_MAX"]

#: The budget every verdict rationale is held to. The prompt asks for <=2 sentences, so this is a
#: backstop against a model that ignores the instruction, not the normal path.
RATIONALE_MAX = 600

# A sentence end, plus any closing quote or bracket that belongs to it, followed by whitespace or
# the end of the string. The trailing-bracket clause matters: `... (Ofgem, 2024).` must cut after
# the period, not before the parenthesis, or the citation is orphaned.
_SENTENCE_END = re.compile(r"[.!?][\"'’\)\]]*(?=\s|$)")

# How much of the budget a sentence-boundary cut must retain to be worth taking. Below this we
# would be throwing away most of the allowance to honour an early full stop -- a rationale opening
# with "No. The incumbent ..." would otherwise be cut to one word.
_KEEP_RATIO = 0.6

_TRAILING_JUNK = " \t\r\n,;:-–—("


def clip_to_sentence(text: str, limit: int = RATIONALE_MAX) -> str:
    """Return `text` bounded to roughly `limit` characters, ending where a human would.

    Never returns a string cut mid-word. Text that already fits is returned untouched, so this is
    a no-op for the overwhelming majority of rationales (6,539 of 7,265 measured).
    """
    if not text:
        return text
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped

    window = stripped[:limit]

    # Best case: end on the last complete sentence inside the budget.
    ends = list(_SENTENCE_END.finditer(window))
    if ends:
        cut = ends[-1].end()
        if cut >= limit * _KEEP_RATIO:
            return window[:cut].strip()

    # Otherwise cut at the last whole word and SAY that it was cut. Marking is the point: an
    # unmarked truncation is indistinguishable from a complete thought, which is the failure this
    # module exists to end.
    space = window.rfind(" ")
    body = window[:space] if space > 0 else window
    return body.rstrip(_TRAILING_JUNK) + "…"
