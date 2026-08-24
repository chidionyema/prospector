"""The named case the opening document says it cannot write.

`pack_floors.exec_summary_md` states its own ceiling in its docstring, verbatim:

    "The WSJ formula wants a person: one named case, then the widening. This renderer cannot
    write one. It makes no model call ... and every sentence it emits must come from a dossier
    field. An invented protagonist would be the single worst thing this pack could contain."

Both halves of that are right and neither is challenged here. What it missed is that a real
named case is already sitting in the dossier: the retrieved passages. A sentence lifted
verbatim out of a page we fetched, printed with the URL it came from, is not an invented
protagonist. It is a quotation, which is the one form of specificity this repo's source-or-die
rule has always permitted.

MEASURED, 2026-08-21, 108 pass dossiers in the live store
---------------------------------------------------------
Only passages cited by a check that came back `supported` were considered. Each row is a
filter added because the row above it shipped something a buyer must never read, and each
number was measured on the same 108 dossiers rather than estimated.

  actor + number only                       89 of 108 (82.4%), 405 lines
  + finite verb, + capitalisation cap       40 of 108 (37.0%),  57 lines
  + no scraped blocks, + topic overlap      19 of 108 (17.6%)   <-- what ships

**82.4% was my own instrument grading a proxy.** Three of its first four examples were page
furniture: "Temperature Log Book 6 Month Food Hygiene." scored because "Month Food Hygiene"
is capitalised and "6" is a number.

**37.0% still shipped two things a buyer must not see**, and this module's own output on the
live store is what caught them:

  A SCRAPED TABLE. "EVER MACH Oakland / Elevated / ERD drift expectation +1 to +7 days CY Cut
  behavior repeated movement ..." arrived as one "sentence" because the cells carry no full
  stop, so nothing split them.

  AN OFF-SUBJECT CITATION. An AI training-data provenance pack drew the lede "penalties run
  to EUR 1,500 for unauthorized detection and EUR 7,500 if digging occurs", which is French
  metal-detecting law. The check that cited it was about penalties and was correctly ruled
  `supported`. A supported citation is not automatically a relevant one.

**17.6% is the honest number and it is what this module is built against.** The other 89
dossiers get nothing: `select_lede` returns None and the opening document is unchanged,
which is the contract every other floor in this pack keeps --- where the specific is absent
from the dossier, the line is absent too rather than padded with a generic one. A filter that
cuts the yield by more than half and raises every surviving example from "technically cited"
to "worth opening with" is the right trade for the first thing a buyer reads.

Two of the nineteen, verbatim:

  "For projects certified by DECD on or after January 1, 2021, that exceed $2.5 million in
   credit, the production company must apply and receive an audit"
      --- in the Georgia film production compliance pack

  "Manufacturing is the UK's largest claimant sector by value, with an average claim of
   GBP 72,000 (HMRC, 2024), and the 20% above-the-line credit rises to 27% under ERIS"
      --- in the R&D tax credit pack

WHY EACH FILTER IS THERE
------------------------
Each one removed a class of false positive the measurement above actually produced. None of
them is a style preference.

  CITED BY A SUPPORTED CHECK   a passage we retrieved but did not rule on is not evidence.
  ACTOR                        a proper noun that is not the first word of the sentence and is
                               not a bare place. "UK" was the top scoring "actor" in the first
                               pass and names nobody.
  NUMBER                       money, a percentage, or a duration. A stake the reader can hold.
  FINITE VERB                  something HAPPENS. Without it the match is a heading.
  CAPITALISATION CAP           over 40% of words capitalised is Title Case, which is navigation
                               furniture and product names, not prose.
  NO INTERNAL BLANK LINE       prose does not contain one mid-sentence; a scraped table does.
  TOPIC OVERLAP >= 2           the passage must share two content words with the candidate.
  LENGTH 60-300                under 60 characters is a fragment; over 300 is a scraped table.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
No model call, so it can be backfilled onto packs already sold and re-rendered offline --- the
same constraint `exec_summary_md` works under, kept for the same reason. It never paraphrases:
the sentence is printed exactly as retrieved, so a buyer who follows the link finds the words
they read. And it never invents an attribution --- the URL is the one we fetched, and if the
passage carries no URL the candidate is dropped rather than published bare.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set

#: Money, a percentage, or a duration. One of these must be present: a situation with no stake
#: in it is a statement, and the reader has no reason to carry it into the next paragraph.
_MONEY = re.compile(r"[£$€]\s?\d[\d,]*(?:\.\d+)?\s*(?:k|m|bn|billion|million|thousand)?", re.I)
_PCT = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
_DURATION = re.compile(r"\b\d+\s?(?:days?|weeks?|months?|hours?)\b", re.I)

#: A named actor: two to four capitalised words, or an acronym of three to six letters.
_ACTOR = re.compile(r"\b(?:[A-Z][a-z]{2,}\s){1,3}[A-Z][a-z]{2,}\b|\b[A-Z]{3,6}\b")

#: Words that start a sentence in English and are not names.
_SENTENCE_OPENERS = frozenset(
    "The This That These Those In On For And But If It We You They Our Your His Her Their "
    "There Here When While After Before Since Because However".split()
)

#: A place is not an actor. "In the UK, spending rose 4%" names no one who did anything, and
#: in the first measurement a bare country code was the single most common match.
#: HMRC, DECD and the FSA are deliberately NOT here. They are the antagonists in the two best
#: lines the measurement found; a body that acts on the reader is an actor, not a place.
_PLACES = frozenset("UK USA EU US GB EEA UAE".split())

#: A finite verb. The sentence has to DO something or it is a heading with a number in it.
_VERB = re.compile(
    r"\b(?:said|says|found|finds|reported|reports|paid|pays|lost|loses|owed|owes|spent|spends|"
    r"faces|faced|took|takes|waited|waits|refused|refuses|ruled|rules|fined|fines|cut|cuts|"
    r"rose|rises|fell|falls|must|cannot|failed|fails|charged|charges|claimed|claims|"
    r"received|receives|identified|identifies|exceed|exceeds|apply|applies|"
    # Grant and obligation verbs. Measured 2026-08-21: adding these moved the yield over
    # the 108 pass dossiers by 0 -- 19 before, 19 after. They are here for recall on
    # future dossiers, and they earned none of the number below.
    r"awarded|awards|granted|grants|banned|bans|required|requires|"
    r"had to|have to|has to|is entitled|are entitled)\b",
    re.I,
)

MIN_CHARS = 60
MAX_CHARS = 300
#: Over this share of capitalised words the line is Title Case: a product name, a nav item, a
#: table header. Measured at 0.40 because that is where the corpus separates prose from
#: furniture; "Temperature Log Book 6 Month Food Hygiene" sits at 1.00.
MAX_CAPITALISED_SHARE = 0.40
#: Below this many alphabetic words there is not enough sentence to judge.
MIN_WORDS = 10


#: Words too common to prove a passage is about this candidate. Anything else of four
#: characters or more counts.
_TOPIC_STOPWORDS = frozenset(
    "with from that this they them their there where when what which will would should could "
    "have been were also into over under about more most than then some such only other "
    "these those your ours here need needs make makes made take takes used using".split()
)


def _content_words(text: str) -> Set[str]:
    return {
        w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _TOPIC_STOPWORDS
    }


@dataclass(frozen=True)
class Lede:
    """One cited situation line, ready to print with its attribution."""

    text: str
    url: str
    source_id: str
    actor: str

    def as_markdown(self) -> str:
        """The block the opening document prints.

        The attribution is on its own line and carries the bare URL rather than a link with
        invented anchor text: naming the page in words we chose would be us characterising a
        source, which is the one thing a quotation exists to avoid.
        """
        return f"> {self.text}\n>\n> — {self.url}"


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "")]


def _is_furniture(sentence: str) -> bool:
    """True for Title Case navigation, product names and scraped blocks rather than prose.

    The newline check is not cosmetic and it was added after this module's own output caught
    it. `_sentences` splits on `[.!?]` followed by whitespace, so a scraped table whose cells
    are separated by blank lines and carry no terminator arrives here as ONE "sentence". The
    first live run produced exactly that: "EVER MACH Oakland / Elevated / ERD drift
    expectation +1 to +7 days ..." scored as a situation because it holds a capitalised token
    and a duration. Prose does not contain a blank line mid-sentence.
    """
    if "\n" in sentence.strip():
        return True
    words = [w for w in sentence.split() if w.isalpha()]
    if len(words) < MIN_WORDS:
        return True
    capitalised = sum(1 for w in words if w[0].isupper())
    return capitalised / len(words) > MAX_CAPITALISED_SHARE


def _actor(sentence: str) -> Optional[str]:
    """The first named actor that is not the sentence's opening word and not a bare place."""
    for match in _ACTOR.finditer(sentence):
        token = match.group(0)
        if token.split()[0] in _SENTENCE_OPENERS:
            continue
        if token in _PLACES:
            continue
        if sentence.startswith(token):
            continue
        return token
    return None


def _has_stake(sentence: str) -> bool:
    return bool(_MONEY.search(sentence) or _PCT.search(sentence) or _DURATION.search(sentence))


def _cited_source_ids(checks: Sequence[Any]) -> Set[str]:
    """Source ids cited by a check that came back `supported`.

    A passage we retrieved but did not rule on is not evidence, and a passage cited by a
    REFUTED check is evidence for the opposite of what the pack is about to say.
    """
    cited: Set[str] = set()
    for check in checks or []:
        verdict = getattr(getattr(check, "verdict", None), "value", None)
        if verdict is None:
            verdict = getattr(check, "verdict", "")
            if isinstance(check, dict):
                verdict = check.get("verdict", "")
        if str(verdict).lower() != "supported":
            continue
        raw = check.get("sources") if isinstance(check, dict) else getattr(check, "sources", None)
        for entry in raw or []:
            if isinstance(entry, str):
                cited.add(entry)
            elif isinstance(entry, dict) and entry.get("source_id"):
                cited.add(entry["source_id"])
            elif getattr(entry, "source_id", None):
                cited.add(entry.source_id)
    return cited


def _source_fields(source: Any) -> Dict[str, str]:
    if isinstance(source, dict):
        return {
            "source_id": str(source.get("source_id") or ""),
            "url": str(source.get("url") or ""),
            "text": str(source.get("text") or ""),
        }
    return {
        "source_id": str(getattr(source, "source_id", "") or ""),
        "url": str(getattr(source, "url", "") or ""),
        "text": str(getattr(source, "text", "") or ""),
    }


#: A cited passage must share at least this many content words with the candidate itself.
#: Two rather than one because one is met by accident: "service", "cost" and "business" appear
#: in almost every retrieved page.
MIN_TOPIC_OVERLAP = 2


def candidates(sources: Sequence[Any], checks: Sequence[Any],
               topic: str = "") -> List[Lede]:
    """Every cited sentence that passes all filters, in the order they were retrieved.

    `topic` is the candidate's own words --- title, one-liner and payer. It exists because a
    `supported` check can cite a passage that is off-subject, and the first live run over 108
    dossiers proved it: an AI training-data provenance pack drew the lede "penalties run to
    EUR 1,500 for unauthorized detection and EUR 7,500 if digging occurs", which is French
    metal-detecting law. The check that cited it was about penalties and was correctly ruled
    supported. The passage was still the wrong thing to open a pack with.

    Passing no topic disables the relevance filter, which is what the unit tests do when they
    are grading one filter at a time.
    """
    cited = _cited_source_ids(checks)
    topic_words = _content_words(topic)
    found: List[Lede] = []
    for source in sources or []:
        fields = _source_fields(source)
        if fields["source_id"] not in cited:
            continue
        # No URL, no attribution, no publication. A quotation a reader cannot follow back is
        # exactly the unsourced claim this repo refuses everywhere else.
        if not fields["url"]:
            continue
        for sentence in _sentences(fields["text"]):
            if not (MIN_CHARS <= len(sentence) <= MAX_CHARS):
                continue
            if _is_furniture(sentence):
                continue
            if not _VERB.search(sentence):
                continue
            if not _has_stake(sentence):
                continue
            actor = _actor(sentence)
            if not actor:
                continue
            if topic_words and len(_content_words(sentence) & topic_words) < MIN_TOPIC_OVERLAP:
                continue
            found.append(
                Lede(text=sentence, url=fields["url"], source_id=fields["source_id"], actor=actor)
            )
    return found


def _score(lede: Lede) -> tuple:
    """Rank the survivors. Money outranks a percentage outranks a duration.

    A pound figure is the stake a reader feels; a duration is the weakest of the three because
    "within 30 days" is often a procedural deadline rather than a cost. Ties break on the
    shorter sentence, because the lede is read before the reader has decided to care.
    """
    has_money = bool(_MONEY.search(lede.text))
    has_pct = bool(_PCT.search(lede.text))
    return (not has_money, not has_pct, len(lede.text))


def select_lede(sources: Sequence[Any], checks: Sequence[Any],
                topic: str = "") -> Optional[Lede]:
    """The best cited situation line, or None when the dossier does not hold one.

    None is the expected answer for roughly two dossiers in three (63% measured 2026-08-21).
    The caller prints nothing in that case. It must never substitute a generic opening.
    """
    found = candidates(sources, checks, topic)
    if not found:
        return None
    return sorted(found, key=_score)[0]
