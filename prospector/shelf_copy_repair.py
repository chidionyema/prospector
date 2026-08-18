"""Rewrite one line of shelf copy so it grades clean, and refuse a rewrite that invents a fact.

MOVED HERE FROM `tools/sweep_shelf_copy.py` ON 2026-08-17, because the engine needed it before
the pack exists and a tool under `tools/` cannot be imported by the package.

The sweep repairs the LIVE shelf: it walks rows that were published before a rule landed and
rewrites the ones that fail. That is a cure. The same defect is still being MADE — measured
2026-08-17 against the live catalogue, `oneLine` blocked 21 stranded PASS packs and 9 of them
were created in the previous two days. `bridge.py:843` takes the shelf's one-liner off the
Candidate (`_card_field(candidate.one_liner)`), so no marketing retry can reach it: the pack is
generated, vetted and paid for, and the publish gate then refuses a line nothing downstream can
change. `run.py::_repair_shelf_lines` calls this before the pack is built, which is the same
repair moved upstream of the spend.

One definition, two callers, so the sweep and the engine can never disagree about what a clean
line is or what a rewrite is allowed to say.

THE MACHINE COUNTS THE CHARACTERS, NOT THE MODEL.

This prompt used to ask for "under 200 characters" while `field_write.ONE_LINER_CUT_AT` — the
only length the catalogue enforces — is 280. On 2026-08-18 pack 83f2e75faa80bb60 sent a
318-character, fact-dense line into that ask. MiniMax M3 reasoned to its 65536-token ceiling and
returned nothing, three times: 23 minutes, $0.059, no answer.

The obvious fix was to render 280 instead of 200. It was measured and it does not work. Same
model, same line, same prompt, only the number changed:

    limit=200   601s   no answer at all (streamed response hit the 600s deadline)
    limit=280   254s   a 320-character line — over the gate anyway

A number in the prompt does not control the length of the answer, because the model cannot count
its own characters. So the number is no longer the model's problem. The machine measures what
came back, and when it is too long it says by exactly how much — `rewrite_one` does that on its
own retry, and `field_write.repair` does it across attempts through `feedback`. Both loops carry
a figure only a machine can compute.
"""
from __future__ import annotations

import re

from .field_write import ONE_LINER_CUT_AT
from .pack_linter import check_shelf_copy, expands_on_first_use, unexplained_initialisms

SYSTEM = (
    "You rewrite one line of shelf copy for a storefront that sells research packs about "
    "businesses. The reader is a person deciding whether to BUILD this business, never the "
    "business's own customer."
)
USER = """Rewrite this one-line description.

TITLE: {title}
LINE:  {line}

RULES
- Third person throughout. Never the words you, your, yours, yourself.
- Describe the business to someone considering running it, not to its end customer.
- Do not open on it, we, our, they, this, that, these, those — open on the thing itself:
  "A tool for UK freelance designers ... that turns every out-of-scope client request into
  a priced, dated change note the client has to answer" is the shape.
- Keep every fact: every figure, price, place, institution and named market must survive
  unchanged. Add nothing that is not already in the line.
- Do NOT name a customer group the line does not already name. If the line does not say who
  the customers are, describe what the business does and stop; inventing an audience is
  inventing a fact.
- One sentence, plain words a stranger to the trade reads once. Keep it as short as the facts
  allow. Do not count characters; if it comes back too long you will be told by how much.

Return JSON: {{"one_liner": "<the rewritten line>"}}"""


def breaches(title: str, one_liner: str) -> list[tuple[str, str]]:
    """The errors the publish gate would raise on this row today, each tagged with the
    FIELD it came from.

    Tagged because the row has two shelf strings and they fail independently: the first run
    of this sweep printed "second person on the shelf" twice against
    `Printed, weatherproof bin store signs made for one specific block of flats` — a line
    with no second person in it at all. Both findings were about its TITLE. An untagged
    report reads as a defect in the line the operator is looking at, and sends the rewrite
    at the wrong string."""
    fields = {"title": title or "", "oneLine": one_liner or ""}
    seen, out = set(), []
    for p in check_shelf_copy(fields, block=True):
        if p.get("severity") != "error":
            continue
        key = (p.get("where") or "?", p["detail"])
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def voice_breaches(one_liner: str) -> list[str]:
    """The subset a REWRITE of the one-liner can actually clear: the founder's two, second
    person and a bare opener.

    An initialism is deliberately not here. `PA RTY-100` and `British Standard BS 4142`
    both trip the initialism rule, and neither is a voice defect — spelling those out is a
    judgement about the term, not about who the sentence is addressed to, and asking a
    cheap brain to fix it while it rewords is how a rewrite invents an expansion. They are
    reported and left."""
    return [d for f, d in breaches("", one_liner)
            if "second person" in d or "opens on" in d]


class RewriteUnavailable(RuntimeError):
    """The rewrite was never ATTEMPTED — the brain call itself failed.

    This exists so a caller can tell two different things apart. `rewrite_one` returning
    None means the rewrite ran and was refused on its merits: the line stays as it is, and
    that is a finished, correct answer. This exception means we never got an answer at all.

    They used to be the same value. The `except Exception: return None` this replaces
    printed the error and handed back None, so `run.py`'s own error branch — which logs at
    ERROR and records `one_liner_repair_failed` — could never fire, and an outage read as
    "the copy could not be improved". That is the swallowed-failure class the ratchet in
    `tests/unit/test_swallowed_failures_can_only_go_down.py` exists to stop, and it walled
    main red on 2026-08-17.
    """


def rewrite_one(op, title: str, line: str, attempts: int = 2,
                feedback: str = "") -> str | None:
    """Rewrite until it grades clean, or keep the original.

    The second attempt is told WHY the first was refused. Four of the founder's twenty rows
    came back unfixed on the first parallel run — including the two lines he opened with,
    the stolen-tool claim and the Cal/OSHA citation — and a refusal we could name in one
    clause was thrown away instead of being handed back. A retry that repeats the same
    prompt is a coin flip; a retry that quotes the rejection is the cheapest correction
    available, at one extra call on failures only.

    An outage raises `RewriteUnavailable` out of here. It used to be caught and turned into
    `None`, which is the same
    answer this function gives when the brain refuses the line — so a quota failure read as "no
    rewrite is possible", and that is what parks a candidate for good. The engine's choke point
    (`field_write.repair`) records a raise as an outage and an empty answer as a refusal, and it
    can only do that if the two arrive differently. The sweep catches it per row, so one dead
    call still does not abort the other twenty-two.
    """
    note = f"\n\n{feedback.strip()}" if feedback and feedback.strip() else ""
    for attempt in range(max(1, attempts)):
        try:
            prompt = USER.format(title=title, line=line)
            got = op.complete_json(SYSTEM, prompt + note)
        except Exception as exc:  # an outage is not a verdict on the copy
            raise RewriteUnavailable(f"rewrite call failed: {exc}") from exc
        new = (got or {}).get("one_liner", "") if isinstance(got, dict) else ""
        new = re.sub(r"\s+", " ", str(new)).strip().strip('"')
        if not new:
            return None

        why = ""
        if voice_breaches(new):
            why = ("it still addresses the reader as 'you' or opens on a pronoun "
                   "(it, we, this, they)")
        elif (invented := _new_facts(f"{title} {line}", new)):
            why = (f"it introduced {', '.join(invented)}, which appear nowhere in the "
                   f"original — use only the words and facts already there")
        elif len(new) > ONE_LINER_CUT_AT:
            # The one figure only the machine can supply. Asking for a length up front does not
            # work (measured: at 280 this model returned 320), so the ask is made after the fact
            # and states the exact overage instead of a budget the model has to hold.
            why = (f"it is {len(new)} characters and the shelf cuts at {ONE_LINER_CUT_AT}, so it "
                   f"needs to lose {len(new) - ONE_LINER_CUT_AT} characters without losing a fact")
        if not why:
            return new

        print(f"    attempt {attempt + 1} refused ({why.split(',')[0]}): {new!r}")
        note = (f"\n\nYour previous answer was REJECTED because {why}. It was:\n{new}\n"
                f"Rewrite it again, fixing exactly that and changing nothing else.")
    return None


#: Words a rewrite may introduce without inventing anything: they carry no fact.
_FREE_WORDS = frozenset("""
a an and the of for to in on at by with from that which who whose so it its their
one each every per turns builds gives makes into out up as is are be
service tool report pack app system engine kit dashboard business
""".split())


def _new_facts(source: str, new: str) -> list[str]:
    """Proper nouns and figures in the rewrite that are nowhere in the source.

    The first run produced "A data intelligence report for UK retirees that turns HMRC's
    real settlement data into evidence for negotiating inheritance tax bills" from a line
    that never mentioned retirees — and inheritance tax is not, as a rule, paid by them. A
    reworded line is allowed to be shorter, clearer and differently ordered; it is not
    allowed to know something the original did not, on a storefront whose whole claim is
    that every fact came from a source.

    Only names and numbers are checked. An ordinary word the rewrite reaches for is style;
    a capitalised term or a figure is a fact, and a fact that appeared from nowhere is the
    class worth blocking."""
    # Compared on a five-character stem, because a faithful rewrite reworks the grammar:
    # `HMRC.` becomes `HMRC's` and `negotiate` becomes `negotiating`, and an exact-token
    # guard calls both of those inventions and blocks a clean line.
    # A compound term is indexed whole AND in pieces. `Cal/OSHA` reaches this function as
    # one whitespace token, normalises to `calosha`, and the rewrite's `Cal/OSHA` arrives
    # as two matches, `Cal` and `OSHA` — so a source that plainly contains the term was
    # read as containing neither half, and two good rewrites of `d6f72b9dc9a45c45` were
    # refused for inventing a fact quoted in their own input.
    def _norm(s):
        out = set()
        for w in s.lower().split():
            out.add(re.sub(r"[^a-z0-9£$%]", "", w))
            out.update(re.split(r"[^a-z0-9£$%]+", w))
        return out - {""}

    have = _norm(source)

    def known(w):
        if w in have or w.rstrip("s") in have or w in _FREE_WORDS:
            return True
        return len(w) >= 5 and any(h.startswith(w[:5]) or w.startswith(h[:5])
                                   for h in have if len(h) >= 4)

    out = []
    for tok in re.findall(r"[A-Z][\w'’-]+|[£$]?\d[\d,.]*%?", new):
        low = re.sub(r"[^a-z0-9£$%]", "", tok.lower())
        if low and not known(low):
            out.append(tok)

    # And the audience, which is the half `retirees` fell through: a lowercase noun, so no
    # capital marks it as a name, but "for X" is a claim about who buys — the one fact this
    # storefront is least able to source after the fact.
    for phrase in re.findall(r"\bfor ((?:[a-z][\w'’-]*[ ]?){1,4})", new.lower()):
        for word in phrase.split():
            w = re.sub(r"[^a-z0-9]", "", word)
            if len(w) > 3 and not known(w):
                out.append(w)
    return sorted(set(out))


# --------------------------------------------------------------------------------------------- #
# The glossary expander. MOVED HERE FROM `tools/sweep_shelf_copy.py` ON 2026-08-19, for the same
# reason the prompt moved on 2026-08-17: the engine needs it before the pack exists, and a module
# under `tools/` cannot be imported by the package.
#
# Measured 2026-08-18 across the 123 lint receipts in the canonical store: 65 packs cannot list,
# and `shelf_copy` holds 41 of them. Twenty of those 41 are held by an unexplained initialism
# alone, and fifteen of the terms already had an operator-declared expansion sitting in
# `config.yaml listing.initialism_glossary`. Nothing on the publish path ran the expander, so a
# pack stayed off the shelf for want of words that were on disk.
#
# This is not a model call and it cannot invent a fact — that is the whole point. `voice_breaches`
# still refuses to send an initialism to a brain, and it still should.
# --------------------------------------------------------------------------------------------- #

def glossary() -> dict[str, str]:
    """The operator's declared expansions, `config.yaml listing.initialism_glossary`.

    Empty is a valid answer and means "expand nothing" — the sweep then reports every
    unexplained term and changes no copy, which is the honest outcome when nobody has said
    what the letters stand for."""
    from prospector.config import load_config
    return dict(load_config().listing.get("initialism_glossary") or {})


def _plural(words: str) -> str | None:
    """`independent software vendor` -> `independent software vendors`.

    Only regular plurals. A last word already ending in `s` gets None, and the caller then
    reports the term instead of writing `Resourcess` onto the shelf — the operator rewords
    it, which is the same answer we give for a term with no entry at all."""
    head, _, last = words.rpartition(" ")
    if not last or last.endswith("s"):
        return None
    if last.endswith("y") and last[-2:-1].lower() not in "aeiou":
        last = last[:-1] + "ies"
    elif last.endswith(("x", "ch", "sh", "z")):
        last += "es"
    else:
        last += "s"
    return f"{head} {last}".strip()


#: `a` before a consonant, `an` before a vowel. The article sits OUTSIDE the run, so
#: expanding in place leaves it agreeing with the letters and not with the words: the live
#: line `an HSE improvement notice` became `an Health and Safety Executive (HSE) notice`.
#: Letter-based, not sound-based, which is right for every term in the glossary today.
_ARTICLE_RE = re.compile(r"\b(a|an|A|An)\s+$")


def expand_initialisms(text: str, gloss: dict[str, str]):
    """Spell out the initialisms the operator has declared. No model call, no judgement.

    Returns `(new_text, unresolved, rejected, embedded)`.

    This exists because `voice_breaches` deliberately refuses to send an initialism to a
    brain: an expansion is a FACT, and a rewrite that invents one ships an unsourced claim on
    a source-or-die storefront. A declared glossary is the safe half of the same job — the
    words come from the operator, and this only pastes them in.

    Three things it will not do, each reported rather than guessed at:

    * `unresolved` — no glossary entry, or a plural this cannot form regularly.
    * `rejected` — an entry whose initials do not spell the run, judged by
      `expands_on_first_use`, the same function the publish gate uses. A typo in
      `config.yaml` cannot put a wrong gloss on the shelf.
    * `embedded` — the run only ever appears inside a longer word, as `STRS` does in
      `CalSTRS`. Pasting an expansion into the middle of a word is worse than leaving it,
      so the copy needs a human, not a substitution.
    """
    out, unresolved, rejected, embedded = text, [], [], []
    for run in unexplained_initialisms(text):
        words = gloss.get(run)
        if not words:
            unresolved.append(run)
            continue
        # A trailing `s` is the plural of the term (`IFAs`, `PACs`), and a following hyphen
        # is a compound (`FOI-sourced`, `RMF-ready`) — both are the term in use. A LEADING
        # letter or digit is not: `STRS` in `CalSTRS` is part of another word.
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(run)}(s?)(?![A-Za-z0-9])")
        match = pattern.search(out)
        if match is None:
            embedded.append(run)
            continue
        if match.group(1):
            words = _plural(words)
            if words is None:
                unresolved.append(run)
                continue
        replacement = f"{words} ({run}{match.group(1)})"
        # Sentence start: the glossary holds common nouns in lower case (`independent
        # software vendor`), and the line it replaces began the sentence.
        head = out[:match.start()]
        if not head.strip() or head.rstrip().endswith((".", "!", "?")):
            replacement = replacement[:1].upper() + replacement[1:]
        else:
            article = _ARTICLE_RE.search(head)
            if article:
                want = "an" if replacement[0].lower() in "aeiou" else "a"
                if article.group(1)[0].isupper():
                    want = want.capitalize()
                head = head[:article.start()] + want + " "
        candidate = head + replacement + out[match.end():]
        if not expands_on_first_use(candidate, run):
            rejected.append(run)
            continue
        out = candidate
    return out, unresolved, rejected, embedded


def expand_row(title: str, one: str, gloss: dict[str, str]):
    """Apply the glossary to both shelf strings, keeping only a change that helps.

    Returns `(new_title|None, new_line|None, needs_operator, rejected)`; None means "leave
    it". An expansion makes a line longer and the gate has a length limit, so it can trade
    one error for another. The test is the gate's own count: a field is only rewritten when
    the errors it would raise strictly go down."""
    new_t, unres_t, rej_t, emb_t = expand_initialisms(title, gloss)
    if new_t != title and len(breaches(new_t, one)) >= len(breaches(title, one)):
        new_t = title
    new_o, unres_o, rej_o, emb_o = expand_initialisms(one, gloss)
    if new_o != one and len(breaches(new_t, new_o)) >= len(breaches(new_t, one)):
        new_o = one
    return (new_t if new_t != title else None,
            new_o if new_o != one else None,
            sorted(set(unres_t) | set(unres_o) | set(emb_t) | set(emb_o)),
            sorted(set(rej_t) | set(rej_o)))
