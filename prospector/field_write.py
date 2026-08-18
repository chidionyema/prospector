"""One choke point every buyer-facing field write passes through: grade, repair, re-grade, record.

P2 of `docs/CONTENT_CONTRACT_PROGRAM.md`.

The problem this closes is not that the engine failed to repair its shelf lines. It repaired them.
The problem is that "what a clean line is" was written down more than once, by hand, in each place
that needed it — and the copies drift silently, because a drifted copy does not raise. It grades
a pack clean that the publish gate then refuses, and the pack is already paid for.

Measured in this repo on 2026-08-17, before this module existed:

  * `run.py:827` and `run.py:882` both carried the one-liner length bar, as the same sentence
    typed twice. Two copies of one rule, in one file, twelve lines apart.
  * `_repair_title` and `_repair_one_liner` were two hand-written copies of the same four-step
    loop, differing only in which checker and which rewriter they called.

So the loop lives here once, and each field is a DECLARATION of what it reads, what grades it and
what rewrites it. Adding the next buyer-facing field is a `Field(...)`, not another loop.

Three properties, unchanged from the code this replaces and all three load-bearing on the money
path:

  * **It costs nothing when the field is clean.** No breach, no operator call.
  * **It can only improve.** A proposal is written only when the grader passes it, so a bad
    rewrite leaves the candidate what it had. A dead operator does the same.
  * **It never raises.** A repair that loses a PASS is worse than a PASS that reaches the gate
    and gets refused there.

The grader is the SAME function on the way in and on the way out, and the same one the park check
(`run._unrepaired_shelf_breaches`) asks. That identity is the whole point; it is pinned by
`tests/unit/test_one_choke_point_grades_every_buyer_facing_field.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as _dc_field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: A one-liner longer than this is CUT by `bridge.py:878` when the catalogue row is written, and
#: a cut line ends in `…`, which `check_shelf_copy` then refuses as "trails off on the shelf".
#: The engine was manufacturing the defect it goes on to reject: 9 of the 21 stranded `oneLine`
#: packs failed on exactly that. This mirrors the catalogue's cut, so it is not a knob — moving it
#: without moving `bridge.py` would re-open the gap it exists to close.
ONE_LINER_CUT_AT = 280

#: Two shots at a title. The first is warm, the second is given the refusal verbatim.
MAX_TITLE_REPAIR_ATTEMPTS = 2

#: Two shots at a one-liner, for the same reason. It was 1 until 2026-08-18, which meant the
#: refusal — the only place the character count is ever stated — was assembled and then dropped.
MAX_ONE_LINER_REPAIR_ATTEMPTS = 2


# --------------------------------------------------------------------------------------------- #
# graders — one definition of clean per field, asked on the way in AND on the way out
# --------------------------------------------------------------------------------------------- #
def grade_title(value: str, cand: Any = None) -> list[str]:
    """What the publish gate will refuse about this title. `check_title` is the gate's own."""
    from .pack_linter import TITLE_MAX_CHARS, check_title

    return [p["detail"] for p in check_title(value, max_chars=TITLE_MAX_CHARS)
            if p.get("severity") == "error"]


#: Prefix of the breach `grade_one_liner` raises for an initialism the reader has never met.
#: `_propose_one_liner` matches on it to decide whether a model may touch the line at all, so it
#: is a constant rather than a string typed twice.
INITIALISM_BREACH = "unexplained initialism"


def grade_one_liner(value: str, cand: Any = None) -> list[str]:
    """Voice, the catalogue's cut, then the initialism the reader has never met.

    Voice is `shelf_copy_repair.voice_breaches`, the live sweep's own checker — deliberately the
    founder's two only (second person, an opener on a bare pronoun).

    The initialism used to be left ungraded here, on the reasoning that asking a cheap brain to
    expand `BS 4142` while it rewords is how a rewrite invents a fact on a source-or-die
    storefront. That reasoning is right about a MODEL and wrong about the outcome. The publish
    gate grades it either way, so leaving it out of this grader did not spare anyone the breach:
    it only meant the writer never saw what the gate was going to refuse. Measured 2026-08-18,
    twenty packs sat unlisted on an initialism alone, fifteen of them on terms the operator had
    already declared in `config.yaml listing.initialism_glossary`.

    So it is graded, and it is repaired WITHOUT a model — `Field.prepare` pastes in the declared
    expansion and `_propose_one_liner` refuses to hand a bare initialism to a brain. A term with
    no declared expansion stays a breach and the pack stays off the shelf, which is the honest
    answer: the operator declares the words, or the copy gets reworded.

    Context is the title AND this line, because that is what the buyer reads together and what
    the publish gate grades (`pack_linter.py:1376` builds its context from every graded field).
    Note the argument widens where an expansion may APPEAR, so it has to include the line itself:
    passing the title alone made a line that spelled the term out perfectly well read as
    unexplained, because the expansion was in the text and not in the context.
    """
    from .pack_linter import unexplained_initialisms
    from .shelf_copy_repair import voice_breaches

    why = list(voice_breaches(value))
    if len(value) > ONE_LINER_CUT_AT:
        why.append(f"{len(value)} chars — over the {ONE_LINER_CUT_AT} the catalogue cuts at, "
                   f"and a cut line trails off on the shelf")
    context = f"{getattr(cand, 'title', '') or ''}\n{value}"
    unknown = unexplained_initialisms(value, context=context)
    if unknown:
        why.append(f"{INITIALISM_BREACH}(s) {', '.join(unknown)} — spell it out on first use, "
                   f"declare it in config.yaml listing.initialism_glossary, or reword the line")
    return why


def _is_initialism_breach(detail: str) -> bool:
    return detail.startswith(INITIALISM_BREACH)


def _expand_one_liner(value: str, cand: Any = None) -> Optional[str]:
    """Paste in the expansions the operator has declared. No model call, no judgement.

    This is `Field.prepare` for the one-liner: it runs once, before any provider call, and costs
    nothing. `expand_initialisms` reports rather than guesses — a term with no entry, a plural it
    cannot form regularly, an entry whose initials do not spell the run, and a run that only ever
    appears inside a longer word are all left alone. So the worst case is that it changes nothing.
    """
    from .shelf_copy_repair import expand_initialisms, glossary

    # No handler here on purpose. `glossary()` returns {} when the operator has declared
    # nothing, so the only way it raises is a broken config load, which is our bug. `repair()`
    # already catches it, keeps the candidate, and writes the reason into the trail — visible,
    # rather than a second silent `return None` that reads exactly like an empty glossary.
    gloss = glossary()
    expanded, _unresolved, _rejected, _embedded = expand_initialisms(value, gloss)
    return expanded if expanded != value else None


# --------------------------------------------------------------------------------------------- #
# proposers — how a breached field is rewritten. Same prompts the live repair tools use.
# --------------------------------------------------------------------------------------------- #
def _propose_title(cand: Any, current: str, feedback: str, attempt: int, op: Any) -> Optional[str]:
    from .pack_linter import TITLE_MAX_CHARS
    from .prompts import render

    system, user = render(
        "retitle",
        current_title=current,
        one_line=cand.one_liner or "",
        # Neither line exists yet — that is the whole point of running here. The prompt reads
        # them as context for the trade, so "(none)" is honest input rather than a placeholder
        # it might echo.
        headline="(none)",
        card_line="(none)",
        who_pays=cand.who_pays or "",
        sector=str((cand.tags or {}).get("sector") or ""),
        market=cand.market or "",
        max_chars=TITLE_MAX_CHARS,
        feedback=feedback,
    )
    data = op.complete_json(system, user, temperature=0.6 if attempt == 1 else 0.2)
    return " ".join(str((data or {}).get("title") or "").split()).rstrip(".").strip() or None


def _propose_one_liner(cand: Any, current: str, feedback: str, attempt: int,
                       op: Any) -> Optional[str]:
    # Imported as a MODULE, not a name: `rewrite_one` is resolved at call time so the sweep and
    # the engine can never end up bound to different versions of it.
    from . import shelf_copy_repair

    # An expansion is a FACT. If everything still wrong with this line is an initialism nobody
    # has declared, there is no rewrite a model can honestly produce: it would have to invent
    # what the letters stand for, on a source-or-die storefront. Refuse, spend nothing, and let
    # the line stay off the shelf until the operator declares the words or rewords the copy.
    # `Field.prepare` has already pasted in every expansion that WAS declared.
    still = grade_one_liner(current, cand)
    if still and all(_is_initialism_breach(b) for b in still):
        return None

    # `feedback` is `_reject_feedback`, which quotes the breach VERBATIM — including the
    # character count. It used to be dropped on the floor here, so the loop computed the one
    # number the model cannot work out for itself and then threw it away, and every attempt
    # sent the identical prompt. The title has always passed it through; this is that.
    return shelf_copy_repair.rewrite_one(op, cand.title or "", current, feedback=feedback)


def _reject_feedback(still: list[str]) -> str:
    # Verbatim, counts included: a vague "too long" gets a draft one character shorter.
    return ("Your previous answer was REJECTED for these reasons:\n"
            + "\n".join(f"  - {b}" for b in still)
            + "\nRewrite it. Do not truncate; say a shorter true thing.")


# --------------------------------------------------------------------------------------------- #
# the declaration
# --------------------------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Field:
    """One buyer-facing field: where it lives, what grades it, what rewrites it."""

    name: str
    #: How it reads in a log line. "title", "one-liner".
    noun: str
    read: Callable[[Any], str]
    write: Callable[[Any, str], None]
    #: `(value, cand) -> breach details`. The only definition of clean for this field.
    grade: Callable[[str, Any], list[str]]
    #: `(cand, current, feedback, attempt, op) -> proposal or None`. None means "no repair".
    propose: Optional[Callable[[Any, str, str, int, Any], Optional[str]]] = None
    #: `(value, cand) -> better value or None`. A deterministic repair, run once BEFORE any
    #: provider call and outside the attempt budget, because it cannot fail in the way an
    #: attempt can: no brain, no prompt, no spend. It is kept only when it strictly reduces the
    #: breach count, so it can never trade one error for another.
    prepare: Optional[Callable[[str, Any], Optional[str]]] = None
    attempts: int = 1
    #: An absent field is not a wrong field. A one-liner nobody has written yet must not park a
    #: candidate; a title is graded even when empty, because a pack with no title is a defect.
    skip_when_empty: bool = False
    strip_value: bool = True
    empty_feedback: str = ""


FIELDS: dict[str, Field] = {
    "title": Field(
        name="title",
        noun="title",
        read=lambda c: c.title or "",
        write=lambda c, v: setattr(c, "title", v),
        grade=grade_title,
        propose=_propose_title,
        attempts=MAX_TITLE_REPAIR_ATTEMPTS,
        strip_value=False,
        empty_feedback="Your output was not a JSON object with a 'title'. Output only that.",
    ),
    "one_liner": Field(
        name="one_liner",
        noun="one-liner",
        read=lambda c: c.one_liner or "",
        write=lambda c, v: setattr(c, "one_liner", v),
        grade=grade_one_liner,
        propose=_propose_one_liner,
        prepare=_expand_one_liner,
        # Two, like the title, and for the same reason: the second attempt is the one that gets
        # told what was wrong. At one attempt `_reject_feedback` was computed on the way out of
        # the loop and never sent, so the retry that names the character overage could not fire.
        attempts=MAX_ONE_LINER_REPAIR_ATTEMPTS,
        skip_when_empty=True,
    ),
}


@dataclass
class Outcome:
    """What the choke point did. The `record` half of grade-repair-re-grade-record."""

    field: str
    #: Breaches on the value as it arrived. Empty means the repair was free.
    before: list[str] = _dc_field(default_factory=list)
    #: Breaches still standing on the value that was kept.
    after: list[str] = _dc_field(default_factory=list)
    repaired: bool = False
    attempts_used: int = 0
    #: Set when the operator call raised. Distinct from "tried and could not" — one is an outage,
    #: the other is a rule the brain cannot satisfy, and they need different answers.
    failed: Optional[str] = None
    trail: list[str] = _dc_field(default_factory=list)


def _value(f: Field, cand: Any) -> str:
    v = f.read(cand) or ""
    return v.strip() if f.strip_value else v


def breaches(cand: Any, *names: str) -> list[str]:
    """What the publish gate will refuse about this candidate, as `field: detail`.

    The same graders the repair uses, so a value this returns nothing for is a value the repair
    would have left alone. No second copy of any bar.
    """
    out: list[str] = []
    for name in (names or tuple(FIELDS)):
        f = FIELDS[name]
        value = _value(f, cand)
        if f.skip_when_empty and not value:
            continue
        out += [f"{name}: {detail}" for detail in f.grade(value, cand)]
    return out


def repair(cand: Any, name: str, *, op: Any, log: Any = None) -> Outcome:
    """Grade, repair, re-grade, record — for one field, once.

    Never raises. Never writes a value the grader has not passed.
    """
    f = FIELDS[name]
    lg = log or logger
    cid = getattr(cand, "candidate_id", "?")
    value = _value(f, cand)

    if f.skip_when_empty and not value:
        return Outcome(field=name)

    before = f.grade(value, cand)
    if not before:
        return Outcome(field=name)

    trail = [f"{f.noun} breaches: {'; '.join(before)}"]

    # The deterministic pass, before any provider call. It is outside the attempt budget on
    # purpose: an attempt is a request to a brain that can fail, refuse or invent, and this is a
    # substitution from a table the operator wrote. Spending an attempt on it would leave the
    # model one fewer try at the breaches it is the only thing that can fix.
    if f.prepare is not None:
        try:
            prepared = f.prepare(value, cand)
        except Exception as e:  # noqa: BLE001 — a field repair must never lose a PASS
            # swallow-ok: best effort by contract, same as the proposer below.
            prepared = None
            trail.append(f"deterministic pass failed — {e}")
        if prepared and prepared != value:
            after_prep = f.grade(prepared, cand)
            # Strictly fewer, never equal. An expansion makes a line longer and the cut is a
            # breach too, so a pass that trades an initialism for an overage has helped nobody.
            if len(after_prep) < len(before):
                trail.append(f"deterministic pass: {len(before)} -> {len(after_prep)} breach(es)")
                value = prepared
                if not after_prep:
                    lg.warning("Repaired the %s of %s from the operator's own glossary, with no "
                               "model call: %r -> %r (%s)",
                               f.noun, cid, _value(f, cand), value, "; ".join(before),
                               extra={"candidate_id": cid, "field": name,
                                      "old_value": _value(f, cand), "new_value": value,
                                      "field_breaches": before, "field_repaired": True,
                                      "field_repaired_without_a_model": True,
                                      f"{name}_repaired": True})
                    f.write(cand, value)
                    return Outcome(field=name, before=before, repaired=True, attempts_used=0,
                                   trail=trail)
            else:
                trail.append("deterministic pass: no improvement, discarded")

    if f.propose is None:
        trail.append("no repair declared")
        return Outcome(field=name, before=before, after=before, trail=trail)

    feedback = ""
    still: list[str] = list(before)

    for attempt in range(1, f.attempts + 1):
        try:
            proposed = f.propose(cand, value, feedback, attempt, op)
        except Exception as e:  # noqa: BLE001 — a field repair must never lose a PASS
            # swallow-ok: best effort by contract. The candidate keeps its own value and the pack
            # is still built; the publish gate remains the backstop it has always been.
            lg.error("%s repair for %s failed on attempt %d: %s",
                     f.noun.capitalize(), cid, attempt, e,
                     extra={"candidate_id": cid, "field": name, "attempt": attempt,
                            "error": str(e), "field_repair_failed": True,
                            f"{name}_repair_failed": True})
            trail.append(f"attempt {attempt}: call failed — {e}")
            return Outcome(field=name, before=before, after=before, attempts_used=attempt,
                           failed=str(e), trail=trail)

        if not proposed:
            trail.append(f"attempt {attempt}: no {f.noun} returned")
            feedback = f.empty_feedback
            continue

        still = f.grade(proposed, cand)
        if not still:
            trail.append(f"attempt {attempt}: accepted ({len(proposed)} chars)")
            lg.warning("Repaired the %s of %s before building its pack: %r -> %r (%s)",
                       f.noun, cid, value, proposed, "; ".join(before),
                       extra={"candidate_id": cid, "field": name, "old_value": value,
                              "new_value": proposed, "field_breaches": before,
                              "field_repaired": True, f"{name}_repaired": True})
            f.write(cand, proposed)
            return Outcome(field=name, before=before, repaired=True, attempts_used=attempt,
                           trail=trail)

        trail.append(f"attempt {attempt}: rejected — {'; '.join(still)}")
        feedback = _reject_feedback(still)

    # Said once, at the end, whatever the attempts did: a run that only ever got empty answers
    # and a run whose every proposal was refused end in the same place — the candidate keeps
    # what it had. A trail that records the first as "no title returned" and nothing else reads
    # as an unfinished attempt rather than a refusal.
    trail.append(f"rejected — kept the candidate's own {f.noun}")
    lg.warning("Could not repair the %s of %s in %d attempt(s) — building the pack on its own "
               "%s, which the publish gate will refuse: %s",
               f.noun, cid, f.attempts, f.noun, "; ".join(before),
               extra={"candidate_id": cid, "field": name, "field_breaches": before,
                      "field_repair_exhausted": True, f"{name}_repair_exhausted": True})
    return Outcome(field=name, before=before, after=before, attempts_used=f.attempts, trail=trail)


def repair_all(cand: Any, *names: str, op: Any, log: Any = None) -> list[Outcome]:
    """Every declared field, in the order given.

    The title goes first where both are repaired: `rewrite_one` is handed the title as context
    for the trade, and a breached title is poor context.
    """
    return [repair(cand, name, op=op, log=log) for name in (names or tuple(FIELDS))]
