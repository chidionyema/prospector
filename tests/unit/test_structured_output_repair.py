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
