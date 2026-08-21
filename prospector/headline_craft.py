"""Is this title WEAK? — the question `check_title` deliberately does not ask.

`pack_linter.check_title` says so in its own docstring: it "catches 'the format was not
followed', never 'this is a weak title'." Nothing else asked either, so nothing in the estate
has ever graded whether a buyer-facing line is worth reading. This module is that grader, and
it is deterministic — no model, no judgement call, so it can run in the writer's repair loop
and in a test without a brain being available.

WHY IT EXISTS, MEASURED. 119 live catalogue titles, 2026-08-21. Two instruments, and they
agree in the worst possible way:

  * The craft devices below: 51 of 119 (42.9%) carry NONE of them — a bare service
    description with no name, no adversary, no stake and no verb. 7 of 119 carry all four.
    That is 7.3x more dead titles than crafted ones.
  * The live publish gate, run over the same 119: it REFUSES all five of the strongest
    titles in the catalogue and passes all four of the deadest as CLEAN.

An inversion, not a weak correlation. `check_title` bans a coined product name and caps the
line at 60 characters, and the crafted form — `<Name> — <plain promise naming the buyer and
what they are up against>` — cannot fit inside either. So the machine was enforcing the
opposite of what it was asked for.

WHAT THIS MODULE DOES AND DOES NOT DO. It grades strength and returns WARNINGS. It does not
block publication and it is not wired into the publish gate, deliberately: 42.9% of the live
catalogue is weak by this measure, and a grader that unlists half a storefront the day it
lands is a decision for the founder, not a side effect of a diff. It is wired into
`field_write.grade_title`, which is the WRITER's mirror — so the repair loop that already
exists (`field_write.repair`, two model attempts against the refusal verbatim) starts
improving titles on the way in, and nothing already on the shelf moves.

The four devices are not a style preference. They are what separates the 7 from the 51 in the
corpus above, and each one is a claim about the reader:

  NAME      a coined product name, then a descriptor. The name is what gets repeated back;
            the descriptor is what stops it being cryptic. The founder's 2026-08-13 complaint
            — "the title tells me nothing, it feels cryptic" — was about a name with NO
            descriptor, and it produced a rule that banned the name instead of requiring the
            descriptor. Both halves, or neither.
  ANTAGONIST who the reader is up against. HMRC, the main contractor, the agency, the insurer.
            13 of 119 titles name one. A pitch with no adversary has no tension.
  STAKE     what is won or lost, in money, a percentage, or a named thing recovered.
  VERB      something HAPPENS. 29 of 119 have an active verb; the rest are noun stacks.
"""
from __future__ import annotations

import re
from typing import List

#: Fewer devices than this and the line is a bare description. Two is the floor rather than
#: three because two is where the corpus separates: at >=2 the set is 41 of 119 and reads as
#: written copy; at >=3 it is 16 and the bar would refuse lines that are working.
MIN_DEVICES = 2

#: A coined product name followed by a descriptor clause. Two things have to be true, and the
#: second one was missing until a test caught it. The separator is the join that turns a
#: cryptic name into a promise — an em-dash, en-dash or colon. And the descriptor has to be a
#: SENTENCE, which on this shelf means it opens lowercase: "GrossStick — the fixed-fee appeal
#: that wins back…" scores, while "PlatformAlpha: The Freelancer's Gig Discovery Letter" does
#: not, because a capitalised opener means another Title Case label follows rather than a
#: clause. A bare `FreelanceCaseLaw` scores nothing at all, which is exactly the founder's
#: 2026-08-13 complaint that the title "tells me nothing, it feels cryptic".
_NAME_THEN_PROMISE = re.compile(
    r"^\s*(?P<name>[A-Z][\w&'’]*(?:\s+[A-Z][\w&'’]*){0,2})\s*[—–:]\s*(?P<promise>[a-z]\S*\s+\S.{8,})$"
)

#: Who the reader is up against. Two shapes: a named institution, and a verb of refusal or
#: pursuit that implies one. The list is drawn from the corpus, not invented — every entry
#: appears in a live title.
_ANTAGONIST = re.compile(
    r"\b(HMRC|IRS|DWP|Ofsted|CQC|Cal/?OSHA|the agency|main contractors?|landlords?|insurers?|"
    r"councils?|tribunals?|regulators?|auditors?|Companies House|"
    r"refus\w+|reject\w+|den(?:y|ies|ied)|withhold\w*|holding back|claw\w*|"
    r"disput\w+|challeng\w+|appeal\w*|chas\w+|forc\w+|wins? back|underpaid|underpayment)\b",
    re.I,
)

#: What is won or lost. Money, a percentage, a fee, or a named recovery.
_STAKE = re.compile(
    r"(£|\$|€|\b\d+(?:\.\d+)?\s*[-–]?\s*\d*\s*%|\bfees?\b|\brecover\w*|\brefund\w*|"
    r"\bpenalt\w+|\brebate\w*|\bcredits?\b|\bclaims?\b|\bpaid\b|\bpays?\b|\bcosts?\b)",
    re.I,
)

#: Something happens. Third-person present is the shelf's register, so that is what is looked
#: for; a gerund ("chasing") is a noun stack wearing a verb's clothes and does not count.
_VERB = re.compile(
    r"\b(wins?|forces?|turns?|stops?|gets?|recovers?|chases?|swaps?|sells?|buys?|remembers?|"
    r"shows?|proves?|challenges?|reverses?|rescues?|releases?|unlocks?|cuts?|blocks?|"
    r"catches?|finds?|fixes?|settles?|answers?)\b",
    re.I,
)

#: Four or more consecutive Capitalised Words is a noun pileup — Title Case standing in for a
#: sentence. 16 of 119 live titles do it. `The Primary Carer's Childcare-Provider
#: Insolvency Fee-Recovery & Placement-Transfer Broker` is the worst of them.
_NOUN_PILEUP = re.compile(r"(?:\b[A-Z][a-z]+[-\s]){3,}[A-Z][a-z]+")


def devices(title: str) -> List[str]:
    """Which craft devices this title actually uses. Order is stable for receipts."""
    t = " ".join((title or "").split())
    if not t:
        return []
    found: List[str] = []
    m = _NAME_THEN_PROMISE.match(t)
    if m and not _looks_like_sentence_fragment(m.group("name")):
        found.append("name")
    if _ANTAGONIST.search(t):
        found.append("antagonist")
    if _STAKE.search(t):
        found.append("stake")
    if _VERB.search(t):
        found.append("verb")
    return found


#: Openers that are grammar, not a product name — `The`, `A`, `An` and the like start a
#: sentence, so `The Subbie Brief — the weekly read…` must not score a NAME it does not have.
_ARTICLES = {"the", "a", "an", "our", "your", "this", "that"}


def _looks_like_sentence_fragment(name: str) -> bool:
    first = name.split()[0].lower() if name.split() else ""
    return first in _ARTICLES


def grade(title: str) -> List[str]:
    """Warnings about how weak this title is. Empty means it is doing the job.

    Returns human-readable reasons, in the same shape `field_write.grade_title` returns, so
    the existing repair loop can hand them straight to a writer.
    """
    t = " ".join((title or "").split())
    if not t:
        return []          # emptiness is `check_title`'s error to raise, not this one's

    why: List[str] = []
    used = devices(t)
    if len(used) < MIN_DEVICES:
        missing = [d for d in ("name", "antagonist", "stake", "verb") if d not in used]
        why.append(
            f"weak title: uses {len(used)} of 4 craft devices ({', '.join(used) or 'none'}) — "
            f"a buyer scanning a shelf needs at least {MIN_DEVICES}. Missing: "
            f"{', '.join(missing)}. NAME is a coined name followed by a plain descriptor "
            f"after an em-dash; ANTAGONIST is who the reader is up against (HMRC, the main "
            f"contractor, the agency); STAKE is the money, the percentage or the thing "
            f"recovered; VERB is something that happens, not a stack of nouns"
        )
    if _NOUN_PILEUP.search(t):
        why.append(
            f"noun pileup: four or more Capitalised Words in a row read as a filing-cabinet "
            f"label, not a sentence — {t!r}"
        )
    return why
