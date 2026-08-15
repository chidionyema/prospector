"""The toolkit — the things a buyer uses rather than reads.

WHY THIS FILE EXISTS
--------------------
The founder's brief, 2026-08-15: "our product needs to be worth much more than the selling
price". A pack that is entirely prose is worth exactly one read. The comparable products at
this price point ship something the buyer OPERATES: a call script, an outreach template, a
question list. That material costs nothing to produce here because the hard part — knowing
which questions actually decide this venture — is already on the dossier. Each check the
engine could not settle is, by definition, a question that has to be answered by a human
talking to a real buyer.

So the interview script is not written; it is DERIVED. An unproven `payer_solvency` check
becomes "who signs off on spend like this". That is why this file can be deterministic and
still be the most useful page in the pack.

WHAT IT DOES NOT DO
-------------------
It states no fact about the market, so it needs no citation and cannot fail the claim-check.
The templates carry square brackets wherever a real detail belongs, and the brackets are the
honest form: a template that filled them in with something plausible would be putting words
into a buyer's mouth about a business we have never seen operate.

That licence is for BLANKS THE BUYER FILLS and for nothing else. A bracket holding an
instruction to us, or a pointer telling the reader to go and copy something out of another
section, is a piece of the template that escaped rather than a hole left on purpose — and one
of them shipped, pointing at a section `bridge` omits on an all-supported dossier
(`_biggest_risk`, 2026-08-15). Anything this file wants to say about the dossier it reads off
the dossier, or does not say.
"""
from __future__ import annotations

from typing import Any, List

from .dossier import check_label

FILENAME = "The_Toolkit.md"
TITLE = "The toolkit"

# One question per check, phrased for a real conversation rather than for a research log.
# These are OUR judgement about what settles each check in the field, stated plainly and
# without hedge (`prompts/style/voice.md`, 2026-08-15): there is no external source that could
# confirm an interview question, so a hedge on one would point at nothing.
_QUESTIONS = {
    "pain_reality":
        "How do you handle this today? Walk me through the last time it went wrong.",
    "value_durability":
        "If someone took this problem away entirely, how long before you would stop paying "
        "them for it?",
    "incumbency":
        "Who else have you looked at for this, and what stopped you buying?",
    "payer_solvency":
        "Who signs this off, and which budget does it come out of?",
    "distribution":
        "Where would you have gone looking for something like this? Who would you have asked?",
    "legality":
        "Is there anything in your procurement or compliance that would stop you using this?",
    "price_comparables":
        "What do you currently pay for the nearest thing you already buy?",
}

_ORDER = ("pain_reality", "payer_solvency", "incumbency", "value_durability",
          "distribution", "price_comparables", "legality")


def _verdict(chk: Any) -> str:
    return str(getattr(getattr(chk, "verdict", None), "value", getattr(chk, "verdict", "")) or
               "").strip().lower()


def _field(obj: Any, name: str) -> str:
    return str(getattr(obj, name, "") or "").strip()


def _biggest_risk(checks: List[Any]) -> str:
    """The memo's risk line, taken from the dossier — or "" when the dossier names no risk.

    WHAT THIS REPLACED, AND WHY (2026-08-15)
    ----------------------------------------
    The memo printed one line unconditionally::

        BIGGEST RISK:      [from 'What would sink this']

    Two defects in one line. The first is that it is a bracketed CROSS-REFERENCE, not
    a blank: every other bracket in this file is a hole the buyer fills with their own detail,
    which is the honest form and stays. This one told the buyer to go and copy something out
    of another part of the pack, so it is a template instruction that reached the reader.

    The second is worse. `pack_bear_case.render` returns "" — and `bridge` then omits the
    section entirely — when nothing was refuted, nothing was left unverifiable, and the
    financial model named no weakness of its own. On an all-supported dossier the paid
    document therefore pointed at a section that is not in the bundle, in the one artefact the
    buyer is meant to fill in and act on.

    The dossier already holds the answer, so it is read from there instead. Refuted outranks
    unverifiable for the same reason it does in `pack_kicker._pick`: evidence that argues
    against a check is a live finding, not a gap. Ranking is `_ORDER` first (earliest-killing),
    then any remaining open check, so a name we have written no interview question for still
    reaches the memo. When every check came back supported there is no risk to name and the
    line is absent rather than invented — this file states no fact about the market, and
    "your biggest risk is X" would be the first one it ever asserted.
    """
    # A nameless check is dropped here rather than ranked and rejected afterwards: rejecting
    # the winner would silently suppress a risk line that a later, named check could have
    # filled, which is the omission this function exists to stop.
    open_checks = [c for c in checks
                   if _verdict(c) in ("refuted", "unverifiable")
                   and str(getattr(c, "check_name", "") or "").strip()]
    if not open_checks:
        return ""

    def rank(chk: Any) -> tuple:
        name = str(getattr(chk, "check_name", "") or "").strip().lower()
        order = _ORDER.index(name) if name in _ORDER else len(_ORDER)
        return (0 if _verdict(chk) == "refuted" else 1, order, name)

    best = sorted(open_checks, key=rank)[0]
    name = str(getattr(best, "check_name", "") or "").strip().lower()
    verdict = _verdict(best)
    tail = ("the evidence argued against this"
            if verdict == "refuted" else "we could not settle this from the desk")
    return f"{check_label(name)} ({tail})"


def render(dossier: Any) -> str:
    """The toolkit as markdown. Always renders when a candidate exists.

    Unlike the evidence sections, this one has no empty case worth guarding: the templates are
    built from the candidate's own title and payer, and a pack without those has already failed
    earlier gates.
    """
    cand = getattr(dossier, "candidate", None)
    if cand is None:
        return ""
    title = _field(cand, "title") or "this"
    one = _field(cand, "one_liner")
    who = _field(cand, "who_pays")
    checks = list(getattr(dossier, "checks", None) or [])

    # Unproven checks first — those are the live questions. Then the rest, because a supported
    # check is still worth hearing a real person confirm in their own words.
    unproven = {str(getattr(c, "check_name", "") or "").strip().lower()
                for c in checks if _verdict(c) in ("unverifiable", "refuted")}
    present = {str(getattr(c, "check_name", "") or "").strip().lower() for c in checks}
    ranked = ([n for n in _ORDER if n in unproven] +
              [n for n in _ORDER if n in present and n not in unproven])

    out: List[str] = [
        f"# {TITLE}", "",
        "Four things to use rather than read. None of them asserts anything about your market: "
        "they are scaffolding, and the square brackets are where your own detail goes.", "",
        "---", "",
    ]

    # 1. The interview script.
    out += ["## 1. The conversations that settle this", "",
            "Ten conversations decide whether this is real, and these are the questions that "
            "make them count. The order is deliberate: the ones we could not settle from the "
            "desk are first, because they are the ones that can still kill it.", ""]
    if who:
        out += [f"Who to have them with: **{who}**.", ""]
    n = 0
    for name in ranked:
        question = _QUESTIONS.get(name)
        if not question:
            continue
        n += 1
        flag = "  _(open — we could not settle this from the desk)_" if name in unproven else ""
        out.append(f"{n}. {question}{flag}")
    if n == 0:
        out.append("_No checks are attached to this pack, so there is no derived question set._")
    out += ["",
            "Do not pitch in these calls. The moment you describe what you are building, the "
            "answers stop being about their problem and start being about your idea, and the "
            "conversation is worth nothing. Ask, write down their words verbatim, stop.", ""]

    # 2. The first message.
    out += ["---", "", "## 2. A first message", "",
            "Short on purpose. The only job of this message is a reply, not a sale.", "",
            "```",
            f"Subject: quick question about [the specific thing {who or 'they'} deals with]",
            "",
            "Hi [name],",
            "",
            "I'm looking into how [organisations like theirs] handle "
            "[the problem, in their words, not yours].",
            "",
            "Not selling anything. I'm trying to understand whether it's actually a "
            "problem worth solving, and you'd know better than anyone.",
            "",
            "Fifteen minutes this week or next?",
            "",
            "[your name]",
            "```", "",
            "Say \"not selling anything\" only while it is true. It is true for the first ten "
            "calls, and those ten calls are worth more than the eleventh sale.", ""]

    # 3. The decision memo.
    #
    # Every bracket below is a BLANK the buyer fills from their own calls, which is this
    # file's whole contract (see the module docstring). A bracket that instead told them to
    # copy something out of another section of the pack is a different thing wearing the same
    # punctuation, and the one that existed pointed at a section the bundle may not contain —
    # see `_biggest_risk`.
    risk = _biggest_risk(checks)
    out += ["---", "", "## 3. The one-page decision memo", "",
            "Fill this in after the tenth conversation. If you cannot fill a line, that is the "
            "answer for that line.", "",
            "```",
            f"WHAT I'M BUILDING: {one or '[one sentence]'}",
            f"WHO PAYS:          {who or '[named role, named organisation type]'}",
            "WHAT THEY DO NOW:  [in their words, from the calls]",
            "WHAT IT COSTS THEM:[hours, money, or risk — a number they gave me]",
            "WHO SAID YES:      [names, not counts]",
            "WHAT I'D CHARGE:   [figure] because [what they compared it to]"]
    if risk:
        out.append(f"BIGGEST RISK:      {risk}")
    out += ["KILL LINE:         if [specific thing] by [date], I stop.",
            "```", "",
            "The kill line is the part people leave out. Write it before you start, when it "
            "costs you nothing to be honest.", ""]

    # 4. Re-check schedule.
    #
    # The pointer at the evidence section is conditional for the same reason the risk line is:
    # `pack_reference.render` returns "" for a dossier with no checks and `bridge` then omits
    # that section, so a sentence saying "the sources are listed with their links" would be
    # sending the reader to a page that is not in their download — and there would be no
    # sources to list either. Directing a paying reader at something absent is the defect, not
    # the wording.
    out += ["---", "", "## 4. When to re-check us", ""]
    if checks:
        out += [f"Everything in this pack about {title} was retrieved on a date, and the web "
                "moved on afterwards. The sources are listed with their links alongside the "
                "checks they back. Re-run the two or three that matter most before you commit "
                "money, and again at ninety days if you are still going.", "",
                "A source that has changed since we read it is not a fault in this pack. It is "
                "the single most useful signal you will get for free, and it is why the links "
                "are there rather than a summary of what they said.", ""]
    else:
        out += [f"Everything in this pack about {title} was written on a date, and the web "
                "moved on afterwards. Re-check the two or three claims you are about to spend "
                "money on before you spend it, and again at ninety days if you are still "
                "going.", ""]

    return "\n".join(out).rstrip() + "\n"
