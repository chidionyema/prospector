"""One literal newline in a rationale destroyed the verdict — and blamed the brain for it.

MEASURED 2026-08-15, during the golden promotion gate that is supposed to decide whether
MiniMax can be trusted to rule alongside Claude.  MiniMax returned a complete, well-reasoned
verdict.  Three of OUR layers, in sequence, turned it into evidence against MiniMax:

  1. `_extract_json` called `json.loads` in STRICT mode, which rejects a literal newline
     inside a string with `Invalid control character`.  The model had written a two-sentence
     rationale with a real line break between the sentences.

  2. Strategy 2 then scanned for `[`…`]` BEFORE `{`…`}`.  The verdict object contains a
     citations array, so it found `["a1b2c3d4e5f6a7b8"]`, parsed that perfectly, and
     returned it.  A LIST, where every caller expects the verdict dict.  No error.

  3. `verdict_for` coerced the unreadable shape to `{}` — below the `except`, so nothing
     deferred — and the check came out `unverifiable, conf 0.0, rationale ""`, presented as
     a real finding.

The golden gate then recorded: the brain answered without a reason.  It had not.  It
answered in full and we threw the answer away, twice, and then wrote down that it was
silent.  A promotion decision on the engine's second brain — the whole point of which is
that the engine must run without Claude Code — was being taken on a number our own parser
manufactured.

This file pins each of the three fixes separately, because any one of them alone still
leaves the failure reachable.
"""
from __future__ import annotations

import json

import pytest

from prospector.models import Candidate, Source, Verdict
from prospector.operator import ParseError, _extract_json

# The exact reply measured on 2026-08-15. The newline between the two sentences is REAL,
# not an escape: that is the entire defect, so the test must contain a real one.
LIVE_REPLY = (
    '{"verdict":"supported","confidence":0.8,'
    '"rationale":"The passage says adjudication is statutory.\n'
    'It also names the 28-day timetable.",'
    '"citations":["a1b2c3d4e5f6a7b8"]}'
)


# ---------------------------------------------------------------------------
# Layer 1 — the parser must not lose an answer to a control character
# ---------------------------------------------------------------------------
def test_the_live_reply_that_was_lost_now_parses_whole():
    """Asserted end-to-end on the real string, not on a reconstruction of it."""
    with pytest.raises(json.JSONDecodeError):
        json.loads(LIVE_REPLY)  # strict: this is what used to happen, and still would

    data = _extract_json(LIVE_REPLY)

    assert isinstance(data, dict), (
        f"the citations array came back instead of the verdict: {data!r}")
    assert data["verdict"] == "supported"
    assert data["confidence"] == 0.8
    assert data["rationale"].startswith("The passage says adjudication is statutory.")
    assert "28-day timetable" in data["rationale"], (
        "the second sentence — the half after the newline — must survive intact; a "
        "truncating parse is the same lost evidence wearing a different shape")
    assert data["citations"] == ["a1b2c3d4e5f6a7b8"]


def test_a_tab_inside_a_rationale_is_not_a_failed_call_either():
    """Not just newlines. `strict=True` rejects every control char below 0x20, and a model
    that indents a list inside its rationale emits tabs."""
    raw = '{"verdict":"refuted","rationale":"Two reasons:\t(a) cost\t(b) churn","citations":[]}'
    assert _extract_json(raw)["rationale"] == "Two reasons:\t(a) cost\t(b) churn"


def test_an_object_holding_an_array_is_read_as_the_object():
    """The ordering fix, isolated from the strict-mode fix.

    This string is VALID strict JSON, so fix 1 alone never runs — Strategy 1 catches it.
    It exists to pin the ordering directly: force Strategy 2 by putting prose in front, and
    the outer object must still win over the array nested inside it.
    """
    raw = 'Here is my answer.\n' + json.dumps(
        {"verdict": "unverifiable", "rationale": "nothing on point",
         "citations": ["deadbeefdeadbeef", "cafebabecafebabe"]})
    data = _extract_json(raw)
    assert isinstance(data, dict), f"picked the nested array over the object: {data!r}"
    assert data["citations"] == ["deadbeefdeadbeef", "cafebabecafebabe"]


def test_a_genuine_top_level_array_still_parses_as_an_array():
    """The ordering fix is 'outermost first', NOT 'always prefer objects'. Query-gen and
    claim-extraction replies are legitimately bare arrays of objects, and breaking those to
    fix verdicts would just move the outage."""
    raw = 'Sure:\n[{"query": "adjudication statutory timetable"}, {"query": "28 day"}]'
    data = _extract_json(raw)
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["query"] == "adjudication statutory timetable"


# ---------------------------------------------------------------------------
# Layer 3 — an unreadable shape is a FAILED CALL, never an empty finding
# ---------------------------------------------------------------------------
class _ShapeOperator:
    """Returns a shape `verdict_for` cannot read — exactly what the old parser handed it."""

    name = "shapeshifter"
    model_version = "shapeshifter"

    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, system, user, **kw):
        return self.payload


def _cand() -> Candidate:
    return Candidate(title="Adjudication timetable service",
                     one_liner="statutory adjudication, 28-day timetable")


def _sources() -> list[Source]:
    return [Source(source_id="a1b2c3d4e5f6a7b8", url="https://example.gov/adjudication",
                   text="Adjudication is statutory and runs to a 28-day timetable.",
                   retrieved_by="fixture")]


@pytest.mark.parametrize("payload", [
    ["a1b2c3d4e5f6a7b8"],   # the measured case: the citations array came back
    [],                     # an empty list — the old code's `if data else {}` branch
    "supported",            # a bare string
    None,
])
def test_an_unreadable_verdict_shape_defers_and_does_not_become_a_finding(payload):
    """The compensating control for the whole class.

    Before this, EVERY one of these produced `unverifiable, conf 0.0, rationale ""` with
    `degraded=False, retrieval_failed=False` — a check that reads as evaluated and
    inconclusive, feeding the kill gates and the score, when in truth we never read the
    reply at all. `retrieval_failed` is the flag that makes run_check DEFER; without it the
    project rule 'an exception is never evidence' is enforced for exceptions only, and a
    silent coercion walks straight past it.
    """
    from prospector.verify import verdict_for

    res = verdict_for(_ShapeOperator(payload), _cand(), "legality", _sources())

    assert res.verdict == Verdict.UNVERIFIABLE
    assert res.retrieval_failed is True, (
        f"{payload!r} was read as a finding instead of a failed call — this is the flag "
        "that makes it DEFER rather than count toward a KILL")
    assert res.degraded is True
    assert res.confidence == 0.0


def test_a_one_element_list_wrapping_the_object_is_still_unwrapped():
    """The coercion that was RIGHT stays. Cheap-tail models really do reply `[{...}]`, and
    that is a readable answer, not a failed call — it must not be swept into the DEFER
    above just because its neighbour was broken."""
    from prospector.verify import verdict_for

    op = _ShapeOperator([{"verdict": "supported", "confidence": 0.7,
                          "rationale": "The passage states the statutory timetable.",
                          "citations": ["a1b2c3d4e5f6a7b8"]}])
    res = verdict_for(op, _cand(), "legality", _sources())

    assert res.verdict == Verdict.SUPPORTED
    assert res.retrieval_failed is False
    assert "statutory timetable" in res.rationale


def test_parse_error_is_still_raised_when_there_is_no_json_at_all():
    """`strict=False` must not turn the parser into something that accepts anything."""
    with pytest.raises(ParseError):
        _extract_json("I could not complete this request.")
