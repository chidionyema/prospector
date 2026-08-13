"""Post-verdict figure tracing — does every number a rationale asserts come from a passage?

Why this module exists (programme doc §33, 2026-08-13). `price_comparables._appears_in` requires a
cited PRICE to appear literally in its passage, and `rg -n "_appears_in" prospector/` returns hits
only in that file. So the seventh check — the one that can never kill — was the only check verifying
its own arithmetic, while the six that CAN kill simply trusted the model. Measured consequence:
**15 of the 50 packs on sale (30%)** asserted at least one figure appearing in NO passage the run
retrieved, against storefront copy promising "Every figure in every pack links to a retrievable
source."

**This module only ever OBSERVES.** It returns buckets; it does not demote a verdict and it does not
kill. That is deliberate doctrine, not timidity: an absent number is OUR extraction failure, and
`kill_filter` can hard-fail on an `unverifiable` hard gate, so demoting here would let our own bug
kill a sound idea — the exact failure class as `store/dossiers/2102bacc6dd75cf9.kill.json`. What the
flag is FOR is the listing fence (`bridge.py:437` already refuses to list what we cannot deliver):
a pack may be barred from the shelf on this signal, which is a revenue decision, not a verdict one.

**Why the matcher is duplicated in `tools/experiments/q4c_claim_level_tracing.py` on purpose.** That
probe is the independent instrument that measures whether this module works. If it imported this
module, a bug here would make the probe agree with the bug — the measurement would be circular.
`tests/unit/test_figure_check.py` pins the two implementations to identical output on a fixture
corpus, so they cannot silently diverge while staying independent at measurement time.

**Matching is deliberately LENIENT, so `untraceable` is a LOWER BOUND.** A figure counts as found if
its bare digits appear in the passage with digit boundaries: "92" matches "92%", "92 percent" and
"92 of them". Units, currency and wording are not required. Anything called untraceable here is
untraceable under any stricter test, which is the only defensible direction for an accusation this
serious.

**`contains` here and `price_comparables._appears_in` disagree BY DESIGN, and must not be unified.**
`_appears_in` is strict (it rejects "49" against a passage reading "49.99") because it decides
whether to ACCEPT an anchor as evidence, and a near-miss would launder a fabricated number into a
cited one. `contains` is lenient in exactly that case because it decides whether to ACCUSE our own
output of invention, where every count must be a lower bound. Same rail, opposite directions, both
conservative. Pinned by `test_leniency_runs_OPPOSITE_to_appears_in_and_that_is_correct`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: Mirrors `verify.VERDICT_PASSAGE_TRUNCATE`. The verdict prompt is built as
#: `s.text[:VERDICT_PASSAGE_TRUNCATE]` (`verify.py:439`), so the truncated passage — not the full
#: stored text — is the model's entire grounding input. Tracing against untruncated text would
#: credit the model with evidence it never saw.
DEFAULT_TRUNCATE = 600

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"

#: A figure is a number that carries a CLAIM. Bare small integers ("three of the passages",
#: "2 sources") are prose, not evidence, so a number qualifies only if it wears a unit or is large
#: enough that nobody writes it casually.
FIGURE_RE = re.compile(
    rf"(?:[£$€]\s?({_NUM})"                                   # currency
    rf"|({_NUM})\s?%"                                          # percent sign
    rf"|({_NUM})\s?(?:percent|per cent|pc\b)"                  # spelled percent
    rf"|({_NUM})\s?(?:million|billion|trillion|bn\b|m\b|k\b)"  # magnitude words
    rf"|({_NUM})\s?(?:x|fold|times)\b"                         # multiples
    rf"|\b({_NUM})\b)",                                        # bare — filtered below
    re.IGNORECASE,
)

_BARE_GROUP = 6
_BARE_MIN = 1000.0
YEAR_RE = re.compile(r"^(?:19|20)\d\d$")


def figures(text: str) -> list[str]:
    """Normalised digit-strings of every claim-bearing number in `text`, in order, deduped."""
    out: list[str] = []
    seen: set[str] = set()
    for m in FIGURE_RE.finditer(text or ""):
        raw = next(g for g in m.groups() if g)
        bare = m.lastindex == _BARE_GROUP
        norm = raw.replace(",", "")
        if YEAR_RE.match(norm):
            continue                       # a year is a date, not a measurement
        if bare:
            # No unit attached. Keep only numbers too big to be prose counting.
            try:
                if float(norm) < _BARE_MIN:
                    continue
            except ValueError:
                continue
        if "." in norm:
            norm = norm.rstrip("0").rstrip(".")
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def contains(haystack: str, num: str) -> bool:
    """Does `num` occur in `haystack` with digit boundaries? Commas in the haystack ignored.

    Digit boundaries are what stop a near-miss laundering a fabricated number into a "cited" one:
    49 must not match inside 149 or 4.9. Trailing zeros are the same number, so 92 matches "92.0"
    and 4.5 matches "4.50".
    """
    h = re.sub(r"(?<=\d),(?=\d\d\d)", "", haystack or "")
    esc = re.escape(num)
    if re.search(rf"(?<![\d.]){esc}(?!\d)", h):
        return True
    tail = r"0*" if "." in num else r"\.0+"
    return bool(re.search(rf"(?<![\d.]){esc}{tail}(?!\d)", h))


@dataclass
class FigureTrace:
    """Where every claim-bearing number in a rationale came from.

    `untraceable` is the only field the listing fence should read; the rest exist so a human
    reading a receipt can tell a grounding defect from a citation-hygiene defect from our own
    pricing showing up in our own prose.
    """
    traceable: list[str] = field(default_factory=list)
    """In a passage this check CITED, within the prompt's truncation budget."""
    other_passage: list[str] = field(default_factory=list)
    """Retrieved for this candidate but cited by a different check. Grounded; citation is wrong."""
    self_ref: list[str] = field(default_factory=list)
    """Our own price rung or the candidate's own pitch — not a claim about the world."""
    untraceable: list[str] = field(default_factory=list)
    """In NO text the run retrieved. The model supplied it."""

    @property
    def clean(self) -> bool:
        return not self.untraceable

    def to_dict(self) -> dict[str, list[str]]:
        return {"traceable": list(self.traceable), "other_passage": list(self.other_passage),
                "self_ref": list(self.self_ref), "untraceable": list(self.untraceable)}


def price_rung_forms(rungs: Iterable[Any]) -> set[str]:
    """Declared price points in BOTH pence and pounds — config says 4999, a rationale writes £49.99.

    Note what this does NOT do: it does not accept a number merely because it looks like a price.
    `payer_solvency` was measured asserting "£49" on four live packs while the ladder is
    `[1999, 2999, 4999, ...]` — £49 is not a rung (£49.99 is) and £39 is off-ladder entirely. Those
    stay UNTRACEABLE on purpose, because a check reasoning about a price we do not charge is a real
    defect and must not be laundered into `self_ref`.
    """
    out: set[str] = set()
    for r in rungs or []:
        try:
            pence = int(r)
        except (TypeError, ValueError):
            continue
        out.add(str(pence))
        pounds = pence / 100.0
        out.add(f"{pounds:g}")
        if pounds.is_integer():
            out.add(str(int(pounds)))
    return out


def trace_figures(rationale: str,
                  sources: Sequence[Any],
                  citations: Sequence[str],
                  *,
                  self_text: str = "",
                  price_rungs: Iterable[str] = (),
                  truncate: int = DEFAULT_TRUNCATE) -> FigureTrace:
    """Bucket every claim-bearing figure in `rationale` by where it can be found.

    `sources` are Source-likes carrying `.source_id` and `.text`; `citations` are the source_ids
    this check actually cited. Passages are truncated to `truncate` because that is what the model
    was shown — see DEFAULT_TRUNCATE.
    """
    figs = figures(rationale)
    trace = FigureTrace()
    if not figs:
        return trace

    cited_ids = set(citations or ())
    cited_text, other_text = [], []
    for s in sources or ():
        text = str(getattr(s, "text", "") or "")[:truncate]
        if getattr(s, "source_id", None) in cited_ids:
            cited_text.append(text)
        else:
            other_text.append(text)
    cited_hay = "\n".join(cited_text)
    other_hay = "\n".join(other_text)
    rung_forms = set(price_rungs or ())

    for f in figs:
        if contains(cited_hay, f):
            trace.traceable.append(f)
        elif contains(other_hay, f):
            trace.other_passage.append(f)
        elif f in rung_forms or (self_text and contains(self_text, f)):
            trace.self_ref.append(f)
        else:
            trace.untraceable.append(f)
    return trace
