"""Structured output repair tests (Part 9).

Tests _extract_json directly for various input forms, and verifies that
complete_json raises ParseError when all repair attempts are exhausted.
"""
from __future__ import annotations

import pytest

from prospector.operator import MockOperator, ParseError, _extract_json

# ---------------------------------------------------------------------------
# _extract_json — input format handling
# ---------------------------------------------------------------------------

def test_extract_json_fenced_json_block():
    """Code-fenced ```json ... ``` block is unwrapped and parsed."""
    text = '```json\n{"verdict": "supported", "confidence": 0.9}\n```'
    result = _extract_json(text)
    assert result == {"verdict": "supported", "confidence": 0.9}


def test_extract_json_fenced_plain_block():
    """Plain ``` fence (no language tag) is also handled."""
    text = '```\n{"key": "val"}\n```'
    result = _extract_json(text)
    assert result == {"key": "val"}


def test_extract_json_trailing_prose():
    """JSON followed by trailing prose — only the JSON object is returned."""
    text = '{"verdict": "refuted"} Here is some extra prose that should be ignored.'
    result = _extract_json(text)
    assert result == {"verdict": "refuted"}


def test_extract_json_bare_object():
    """A plain JSON object with no fences."""
    text = '{"a": 1, "b": [1, 2, 3]}'
    result = _extract_json(text)
    assert result == {"a": 1, "b": [1, 2, 3]}


def test_extract_json_bare_array():
    """A plain JSON array with no fences."""
    text = '["query one", "query two", "query three"]'
    result = _extract_json(text)
    assert result == ["query one", "query two", "query three"]


def test_extract_json_leading_prose_then_object():
    """Prose before the JSON object — extract finds the first { and parses from there."""
    text = "Here is the result:\n\n{\"score\": 5}"
    result = _extract_json(text)
    assert result == {"score": 5}


def test_extract_json_unparseable_raises_parse_error():
    """Completely unparseable text raises ParseError."""
    with pytest.raises(ParseError):
        _extract_json("not json at all")


def test_extract_json_empty_string_raises_parse_error():
    with pytest.raises(ParseError):
        _extract_json("")


# ---------------------------------------------------------------------------
# complete_json — ParseError raised after all retries exhausted
# ---------------------------------------------------------------------------

class _AlwaysBadOperator(MockOperator):
    """Operator that always returns non-JSON text, forcing all retries to fail."""
    def __init__(self):
        super().__init__()
        self.name = "always_bad"

    def _raw(self, system: str, user: str, temperature: float) -> str:
        return "this is not json at all, ever, no matter what you do"


def test_complete_json_raises_parse_error_after_retries():
    """complete_json must raise ParseError when all repair attempts fail."""
    op = _AlwaysBadOperator()
    with pytest.raises(ParseError):
        op.complete_json("system", "user", retries=1)


# ---------------------------------------------------------------------------
# MockOperator router integration
# ---------------------------------------------------------------------------

def test_mock_operator_router_returns_dict():
    """MockOperator with a dict-returning router produces parseable JSON via complete_json."""
    def router(system, user):
        return {"verdict": "supported", "confidence": 0.9, "rationale": "ok", "citations": []}

    op = MockOperator(router=router)
    result = op.complete_json("system", "user")
    assert result["verdict"] == "supported"
    assert result["confidence"] == pytest.approx(0.9)


def test_mock_operator_router_returns_none_falls_back_to_empty():
    """Router returning None causes MockOperator to fall through to responses dict,
    returning '{}' if no key matches — complete_json returns {}."""
    op = MockOperator(router=lambda s, u: None)
    result = op.complete_json("system", "user")
    assert result == {}


def test_mock_operator_router_returns_list():
    """A list-returning router is valid for query_gen calls."""
    def router(system, user):
        return ["query one", "query two"]

    op = MockOperator(router=router)
    result = op.complete_json("system", "user")
    assert result == ["query one", "query two"]


# ---------------------------------------------------------------------------
# Strategy 4 — the answer a reasoning model leaves at the very END
#
# MiniMax heads the non-critical chain since claude_cli was removed from it
# (config.yaml:70, founder directive 2026-08-14), so every generation, prescreen,
# score and retitle call now goes through a model that thinks out loud first.
# These pin the shapes that thinking produces. Measured on a live retitle run:
# 55,639 chars of reasoning, the answer in the last 200.
# ---------------------------------------------------------------------------

_REASONING = (
    "Let me analyze this carefully.\n"
    'The headline template says "[Customers] [have problem]" and a shape {like: this\n'
) * 40
_ANSWER = '{"name": "Vendor patch alerts", "card_line": "flags suppliers that stopped patching"}'


def test_reasoning_prose_with_an_unclosed_brace_does_not_swallow_the_answer():
    """The measured failure. Prose describing a data shape leaves `{` open, so a
    forward depth scan never returns to zero and the trailing answer is read as
    nested inside the noise. Anchoring on the LAST closer makes the prose irrelevant."""
    assert _extract_json(_REASONING + "\n" + _ANSWER)["name"] == "Vendor patch alerts"


def test_a_bracket_pair_in_the_reasoning_does_not_win_over_the_answer():
    """`[Customers]` is valid-looking and appears first. First-match strategies
    returned it, or a fragment starting at it, and the caller saw a ParseError."""
    text = 'The template is [Customers] [have problem].\n' + _ANSWER
    assert _extract_json(text)["card_line"] == "flags suppliers that stopped patching"


def test_the_answer_is_found_inside_a_closed_think_block_response():
    assert _extract_json("<think>\n" + _REASONING + "\n</think>\n" + _ANSWER)["name"] == \
        "Vendor patch alerts"


def test_chatter_after_the_answer_still_resolves():
    """A closer that is not the last character: the scan walks closers backwards, so
    a sign-off containing brackets costs one failed parse, not the answer."""
    out = _extract_json(_REASONING + "\n" + _ANSWER + "\nI hope this helps! [done]")
    assert out["name"] == "Vendor patch alerts"


def test_a_brace_inside_a_string_value_is_not_treated_as_structure():
    text = _REASONING + '\n{"card_line": "Costs about {X} per seat", "n": 2}'
    assert _extract_json(text) == {"card_line": "Costs about {X} per seat", "n": 2}


def test_an_array_answer_after_reasoning_is_recovered():
    assert _extract_json(_REASONING + '\n[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_prose_with_no_json_at_all_still_raises_rather_than_scanning_forever():
    """The bound matters: `_tail_json_candidates` is capped so a pathological
    response fails fast instead of turning a parse error into a CPU-bound hang on
    the publish path."""
    with pytest.raises(ParseError):
        _extract_json("Here are some braces { { { and brackets [ [ [ and no answer.")
