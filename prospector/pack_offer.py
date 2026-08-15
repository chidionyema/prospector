"""What you would be selling — the thing itself, before any plan about it.

WHY THIS FILE EXISTS
--------------------
A buyer who has read the opening knows why this is a business. They do not yet know what the
business IS, in the concrete sense of what changes hands for money. Until 2026-08-15 the pack
never told them directly: the product had to be inferred from a build spec that opens with
architecture, a go-to-market plan that opens with a channel, and an operations plan that opens
with a rota. Three documents about how to run a thing, none of which says what the thing is.

That is the section a newspaper puts immediately after the nut graf, and it is short by
design. Everything here is a field already on the candidate — no evidence is restated, no
claim about the market is made, and nothing is inferred. A field that is empty on the dossier
is absent here rather than filled with a plausible line, because a plausible line about what
the product is would be the single most damaging invention in the pack.
"""
from __future__ import annotations

from typing import Any, List

FILENAME = "The_Offer.md"
TITLE = "What you would be selling"

# `structural_form` is the engine's word for how the business makes money. The buyer never
# reads a snake_case identifier (`prompts/artifacts.md` HARD RULE), so each one is given its
# plain-English form here. An unmapped value is printed with underscores swapped for spaces
# rather than dropped: a form we have not written a phrase for is still true.
_FORMS = {
    "productized_service": "a service sold as a fixed package rather than by the hour",
    "vertical_tool": "a software tool built for one trade rather than for everyone",
    "transaction_broker": "a business that takes a cut of a transaction it arranges",
    "risk_financing": "a business that carries a risk its customers would rather not",
    "physical_ops": "a business whose work happens in the physical world",
    "audience_media": "an audience built first, sold to second",
    "picks_and_shovels": "a business selling to the people doing the work, not doing it",
    "data_intelligence": "a business selling what it knows rather than what it does",
}


#: Market slugs as a reader would say them. The dossier stores routing keys — `uk`, `us`, `us-fl`
#: — and the offer page was printing them raw: "The market it was checked against is uk." A lower
#: -case country code mid-sentence is the single clearest tell that prose came out of a database
#: rather than being written, which is the register the founder rejected on 2026-08-15 ("our tone
#: and language is hurried and cryptic"). Measured across the 66 PASS dossiers on disk, the whole
#: live vocabulary is five values: uk (50), us (12), us-fl (2), us-il (1) and one null.
_MARKETS = {
    "uk": "the UK",
    "us": "the US",
    "us-fl": "the US, Florida",
    "us-il": "the US, Illinois",
}


def _market_phrase(slug: str) -> str:
    """A market slug in English, or the slug upper-cased when we have no phrasing for it.

    The fallback upper-cases rather than guessing at expansion. "US-TX" is plainly a code and
    reads as one; inventing "the US, Texas" from a table that does not contain it would be the
    same class of error as inventing any other unretrieved fact — and this file's contract
    (module docstring) is that nothing is inferred.
    """
    key = slug.strip().lower()
    return _MARKETS.get(key, slug.strip().upper())


def _article(phrase: str) -> str:
    """"a" or "an" for a phrase we did not write.

    `_FORMS` covers the eight structural forms the generator is supposed to emit, and each of its
    values is a complete noun phrase carrying its own article. Anything else falls through to the
    raw slug, and that path shipped: `structural_form: "prosumer_tool"` is not in the map, so the
    sentence rendered "This is prosumer tool." — a missing article in the fourth heading of the
    second section of a paid document (observed in pack 13d41ccee9e96e2d, 2026-08-15).

    Vowel-letter matching is not a general solution to English articles ("a university", "an
    hour"), and is not claimed to be. It is right for the shape of value that actually reaches
    here — a snake_case classifier label like `prosumer_tool` or `marketplace` — and a wrong
    article is a smaller defect than no article at all.
    """
    return "an" if phrase[:1].lower() in "aeiou" else "a"


def _field(obj: Any, name: str) -> str:
    return str(getattr(obj, name, "") or "").strip()


def render(dossier: Any) -> str:
    """The offer section as markdown, or "" when the candidate carries nothing to describe.

    "" when none of the three fields this section actually prints is set: a section titled
    "what you would be selling" that then declines to say is worse for the reader than no
    section at all.
    """
    cand = getattr(dossier, "candidate", None)
    if cand is None:
        return ""

    hypothesis = _field(cand, "hypothesis")
    who = _field(cand, "who_pays")
    form = _field(cand, "structural_form").lower()
    market = _field(cand, "market")

    # THE GUARD ASKS ABOUT THE FIELDS THIS SECTION PRINTS (2026-08-15).
    #
    # It was `if not one and not hypothesis`, written when this section opened on the
    # one-liner. The one-liner moved to section 1 on 2026-08-15 (see the ownership note
    # below) and the guard did not move with it, so it went on admitting a candidate on the
    # strength of a field the body no longer touches. A candidate with a one-liner and an
    # empty hypothesis, payer and structural form therefore shipped `The_Offer.md` as a
    # heading over nothing at all — the exact failure the guard was written to prevent,
    # reached through the one field that no longer proves anything about the body.
    #
    # These two ARE the body: `hypothesis` is the bet and `form` is the shape. `who_pays` is
    # not in the guard because it cannot carry the section on its own — it renders a rider
    # that points at what comes AFTER it, so it is gated on there being something after it
    # (below). A guard naming any field this section does not print can go stale the next time
    # a field moves house, which is exactly how the one-liner version of it went stale.
    if not (hypothesis or form):
        return ""

    # ONE OWNER PER CANDIDATE FIELD (2026-08-15).
    #
    # This section used to open on the one-liner and then reprint `who_pays` and `why_now`
    # under headings of their own. All three now belong to section 1: "Where this starts" leads
    # on the one-liner as its standfirst, names the payer and says what changed. Printing them
    # again two pages later is the pack repeating itself inside the buyer's first five minutes,
    # and `pack_linter.check_repetition` blocks the listing on it.
    #
    # Each field now has exactly one home. Section 1 owns the one-liner, the payer and the
    # timing; this section owns the BET and the shape it takes. The framing sentence that sat
    # under the payer was the only part worth keeping, so it survives as a pointer instead of
    # as a second copy of the paragraph it framed.
    out: List[str] = [f"# {TITLE}", ""]

    if hypothesis:
        out += ["## The bet", "",
                "Stated plainly, so you can disagree with it:", "",
                hypothesis, ""]

    # "Everything BELOW" — so this only renders when there is something below it, which here
    # means the shape block. Printed on a candidate with a payer and no `structural_form`, the
    # sentence promised a passage that the same render had already decided to omit, and the
    # reader is left looking for it. Same failure as the guard above, one paragraph smaller.
    if who and form:
        out += ["Everything below is written on the assumption that the person named at the "
                "start of this pack is who you are selling to. If you cannot picture reaching "
                "them, that is the objection to raise now, not after the build.", ""]

    if form:
        known = _FORMS.get(form)
        phrase = known if known else f"{_article(form)} {form.replace('_', ' ')}"
        line = f"This is {phrase}."
        if market:
            line += f" The market it was checked against is {_market_phrase(market)}."
        out += ["## The shape of it", "", line, "",
                "That shape decides more than it looks like it does. It sets who you have to "
                "convince, how long you wait to be paid, and what you are still doing in year "
                "two.", ""]

    return "\n".join(out).rstrip() + "\n"
