"""How to know in 30 days — the kicker.

WHY THIS FILE EXISTS
--------------------
Bruce DeSilva's test for a kicker: it must resolve the piece, not summarise it. A summary at
the end of a document the reader has just finished is the definition of a wasted paragraph.

Until 2026-08-15 the last thing in a pack was the QA report — a table of checks and confidence
scores. The reader closed a £30 product on the engine's internal bookkeeping, which is both the
least interesting page and the one that tells them nothing about what to do on Monday. This is
what ends it now.

It resolves by naming ONE test. Not a plan, not a checklist — the pack already has both. One
thing that can come back false in thirty days, chosen from what the dossier could not settle,
because the thing that would kill the venture soonest is the thing worth knowing first.

Deterministic and claim-free: it asserts nothing about the market, only about what this pack
did and did not establish.
"""
from __future__ import annotations

from typing import Any, List, Optional

from .dossier import check_label

FILENAME = "How_To_Know_In_30_Days.md"
TITLE = "How to know in 30 days"

# What settling each check looks like in the field, in the imperative. Ordered by how early a
# false answer kills the venture: nobody has the problem beats nobody has the budget beats
# everything else, and there is no point testing distribution for a thing nobody wants.
_TESTS = {
    "pain_reality": (
        "whether the problem is real enough that people describe it unprompted",
        "Ten conversations. Count how many raise this problem before you mention it. If the "
        "number is under three, the problem is yours and not theirs."),
    "payer_solvency": (
        "whether the person with the problem is the person with a budget",
        "In those same conversations, ask who signs off and which budget line it comes from. A "
        "room full of enthusiasm and no budget holder is the most expensive false positive in "
        "small business."),
    "incumbency": (
        "who is already being paid for this",
        "Ask every person you speak to what they looked at before. Two names you had not heard "
        "of changes the plan; zero names means you are either early or wrong, and thirty days "
        "of asking tells you which."),
    "value_durability": (
        "whether anyone would still be paying in a year",
        "Find one person already paying somebody for this and ask how long they have been "
        "paying. A year of somebody else's renewals is worth more than any forecast."),
    "distribution": (
        "whether you can reach these people at all",
        "Send fifty first messages through one channel and count replies. Not sales — replies. "
        "Under five means the channel is wrong, and that is a cheap thing to learn in week two."),
    "legality": (
        "whether anything stops them buying even when they want to",
        "Ask two people in the trade what their procurement or compliance would say. One "
        "sentence from someone inside beats a week of reading regulations."),
    "price_comparables": (
        "what they already pay for the nearest thing",
        "Ask for the invoice figure of the closest thing they currently buy. It is the only "
        "price anchor that is not a guess."),
}

_ORDER = ("pain_reality", "payer_solvency", "incumbency", "value_durability",
          "distribution", "legality", "price_comparables")


def _verdict(chk: Any) -> str:
    return str(getattr(getattr(chk, "verdict", None), "value", getattr(chk, "verdict", "")) or
               "").strip().lower()


def _pick(checks: List[Any]) -> Optional[tuple]:
    """``(check_name, verdict)`` for the check to test first, or None if none is open.

    Refuted before unverifiable, and earliest-killing within each. A refuted check outranks an
    unverifiable one because the evidence already argues against it: the reader is being asked
    to overturn a finding rather than to fill a gap, which is the harder and more urgent job.
    The verdict travels with the name because the two need different sentences — "we could not
    establish it" and "the evidence argued against it" are not the same instruction.
    """
    by_name = {str(getattr(c, "check_name", "") or "").strip().lower(): c for c in checks}
    for wanted in ("refuted", "unverifiable"):
        for name in _ORDER:
            chk = by_name.get(name)
            if chk is not None and _verdict(chk) == wanted and name in _TESTS:
                return (name, wanted)
    return None


def render(dossier: Any) -> str:
    """The kicker as markdown. Renders even when every check came back supported.

    The all-supported case is not the empty case, it is the most dangerous one: a pack where
    nothing failed reads as permission, and the correct kicker for it says so.

    Four states, not two: a check we can derive a field test from, an open check we cannot,
    everything supported, and no checks at all. The middle one used to be indistinguishable
    from the third and printed its paragraph — see the comment on `open_checks` below.
    """
    checks = list(getattr(dossier, "checks", None) or [])
    cand = getattr(dossier, "candidate", None)
    who = str(getattr(cand, "who_pays", "") or "").strip()

    out: List[str] = [f"# {TITLE}", ""]
    picked = _pick(checks)
    # `_pick` returning None was read as "everything came back supported" until 2026-08-15,
    # and it is not the same question. It also returns None when an open check's name is not
    # in `_TESTS` — `hybrid_entity` is the live example, and `buyer_intent`, `currency` and
    # `route_to_market` are all checks the engine runs and this map does not carry. On such a
    # dossier the pack's CLOSING PARAGRAPH, the last thing a buyer reads, asserted "Every
    # check in this pack came back supported" over a dossier holding a check that was not.
    # This repo's first rule is source-or-die; a false claim in the final paragraph of the
    # product is the worst place in the pack to break it.
    #
    # So the two questions are asked separately now. `picked` decides whether we can derive a
    # thirty-day test from a named check; `all_supported` decides what is TRUE about the
    # dossier, and it is the ONLY thing that may unlock the sentence claiming so.
    #
    # It is written as "every verdict reads supported" rather than "nothing reads refuted or
    # unverifiable" deliberately. `pack_manifest.dossier_from_dict` hands this renderer a
    # `SimpleNamespace` tree whose verdicts are plain strings, so a check carrying a verdict
    # this file does not recognise is possible; under the negative form it would count as
    # supported, which is the same false claim reached by a different door.
    open_checks = [c for c in checks if _verdict(c) in ("refuted", "unverifiable")]
    all_supported = bool(checks) and all(_verdict(c) == "supported" for c in checks)

    if picked:
        name, verdict = picked
        subject, instruction = _TESTS[name]
        if verdict == "refuted":
            finding = (f"The evidence we found argues AGAINST {subject}. That is the strongest "
                       "thing standing between this and a business, so it is what thirty days "
                       "goes on: you are looking for the specific case where the finding does "
                       "not hold, not for reasons to discount it.")
        else:
            finding = (f"The pack could not establish {subject}. Of everything left open, this "
                       "is the one that decides the fastest, so it is the one to spend thirty "
                       "days on.")
        out += [
            "This pack is a desk job. Everything in it was retrieved, read and checked without "
            "anybody leaving a chair, and there is a limit to what that can establish. Here is "
            "the limit, and here is the one thing to do about it.", "",
            "---", "",
            f"## The open question: {check_label(name)}", "",
            finding, "",
            "**What to do.** " + instruction, "",
        ]
        # NOT `as_phrase(who)`. Reprinting the payer description here made it the fourth copy in
        # the pack (section 1, the offer, the marketing copy, this), which is the repetition the
        # founder read back to us on 2026-08-15. The instruction survives without the restatement
        # — a reader ten sections in knows who the buyer is, and if they do not, the pointer is
        # more use to them than a paragraph they have already skipped three times.
        if who:
            out += ["**Who with.** The buyer named at the start of this pack, and nobody else. "
                    "The whole argument rests on that being the payer, so the test is worth "
                    "nothing run against anyone adjacent to them.", ""]
        out += [
            "**What counts as a no.** Decide the number before you start and write it down. A "
            "test with no failing condition is not a test, it is a way of spending thirty days "
            "and feeling productive.", "",
        ]
    else:
        # The general test, used by every branch that has no single check to derive one from.
        # It is the same ten conversations either way; what differs is the sentence above it,
        # which has to be true about THIS dossier.
        general_test = (
            "**The thirty-day test.** Ten conversations with the people who would pay. Count "
            "how many describe the problem before you mention it, and how many name the budget "
            "it would come out of. Under three of either, and the evidence in this pack is "
            "about a problem that exists in public but not in anybody's week.")

        if all_supported:
            out += [
                "Every check in this pack came back supported. That is the least common outcome "
                "and it is not permission to build.", "",
                "What it means precisely: nothing we searched for argued against this. What it "
                "does not mean: that anyone will pay you. No amount of desk research "
                "establishes that, and a pack that let you believe otherwise would be worth "
                "less than what you paid for it.", "",
                general_test, "",
            ]
        elif checks:
            questions = sorted({check_label(str(getattr(c, "check_name", "") or "").strip())
                                for c in open_checks
                                if str(getattr(c, "check_name", "") or "").strip()})
            out += [
                "Not every check in this pack came back supported, and none of the ones that "
                "did not is a question this pack could turn into a single field test.", "",
            ]
            if questions:
                out += ["Still open:", ""]
                out += [f"- {q}" for q in questions]
                out += ["",
                        "Each is argued at full strength earlier in this pack. What follows is "
                        "the general test rather than one cut to fit a named check, because "
                        "none of these narrows to one thing you can go and measure.", ""]
            out += [general_test, ""]
        else:
            # No check record at all. Saying every check came back supported would be a claim
            # about seven checks that were never run, which is the same false sentence as the
            # one above wearing a different cause.
            out += [
                "This pack carries no check record, so there is nothing here that came back "
                "either way. Treat everything in it as an argument to be tested rather than as "
                "a finding, and start with the cheapest test there is.", "",
                general_test, "",
            ]

        if who:
            out += ["**Who with.** The buyer named at the start of this pack, and nobody else.",
                    ""]

    out += [
        "---", "",
        "Thirty days from now you will either have a specific reason to keep going or a "
        "specific reason to stop. Both are worth what this pack cost. The outcome to avoid is "
        "the third one, where six months have gone and the question is still open.", "",
    ]
    return "\n".join(out).rstrip() + "\n"
