"""The generator must not be handed the engine's own field names.

Measured 2026-08-08: 589 internal schema identifiers reached buyer-facing pack prose
across 51 of 99 packs -- "monthly_price of GBP 12 is assumption", "the opportunity's
who_pays field", "(source: verified claim value_durability)". The origin was
`artifacts.py` serialising `cand.to_dict()` and the raw CheckResult dicts straight into
`prompts/artifacts.md`, so the schema was the only vocabulary the model had.

These tests pin the projection that fixes it. They are deliberately written against
`copy_lint.internal_identifiers()` -- the SAME set the publish gate refuses packs on -- so
the generator and the gate cannot drift apart: if a future field starts leaking, the test
that fails is this one, at generation time, not a listing that silently goes unlisted.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from prospector import models
from prospector.artifacts import (
    _CHECK_PROMPT_KEEP,
    _candidate_prompt_view,
    _claims_prompt_view,
)
from prospector.copy_lint import _IDENT_RE, internal_identifiers


def _identifier_tokens(text: str):
    """Internal identifiers appearing in a string, by the publish gate's own rule."""
    idents = internal_identifiers()
    return sorted({m.group(0) for m in _IDENT_RE.finditer(text) if m.group(0) in idents})


def _real_candidate() -> models.Candidate:
    """A Candidate built from the live dataclass, so a new field is covered the day it lands.

    EVERY field is populated, including those with defaults. Populating only the required
    ones is worthless here: the projection drops empty values, so a defaulted-empty field
    would vanish and the test would pass while proving nothing about it.
    """
    kwargs = {}
    for i, f in enumerate(dataclasses.fields(models.Candidate)):
        if f.name == "tags":
            kwargs[f.name] = {"artifacts": {"gtm_plan": "internal payload"}}
        elif f.name == "refinement_history":
            kwargs[f.name] = ["refined once"]
        elif f.name == "weak_monetisation":
            kwargs[f.name] = True
        else:
            # Deliberately does NOT embed the field name. A value like "value for who_pays"
            # would trip the identifier assertion below on the VALUE, hiding whether the
            # KEYS -- the thing the projection actually controls -- were relabelled. The
            # engine must never rewrite a candidate's own prose, so values pass through.
            kwargs[f.name] = f"sample prose {i}"
    return models.Candidate(**kwargs)


def test_candidate_view_carries_no_internal_field_names():
    view = _candidate_prompt_view(_real_candidate())
    leaked = _identifier_tokens(json.dumps(view))
    assert leaked == [], f"internal identifiers reached the prompt: {leaked}"


def test_candidate_view_keys_are_readable_labels():
    view = _candidate_prompt_view(_real_candidate())
    # The leak was the KEYS above all: the model reads them as the opportunity's vocabulary.
    assert "who_pays" not in view
    assert "who pays" in view
    assert not [k for k in view if "_" in k], f"snake_case keys survived: {list(view)}"


def test_candidate_view_keeps_the_substance():
    """Suppression would be a regression -- the writer still needs every real field."""
    view = _candidate_prompt_view(_real_candidate())
    for label in ("title", "summary", "hypothesis", "who pays", "why now", "market"):
        assert label in view, f"projection dropped {label!r}, which the artifact needs"


def test_candidate_view_drops_engine_bookkeeping():
    view = _candidate_prompt_view(_real_candidate())
    for gone in ("candidate_id", "candidate id", "refinement_history", "refinement history",
                 "tags"):
        assert gone not in view


def test_claims_view_renames_check_name_to_a_citable_phrase():
    claims = [{"check_name": "value_durability", "verdict": "supported",
               "confidence": 0.44, "rationale": "because", "citations": ["u"],
               "sources": ["s"]}]
    out = _claims_prompt_view(claims)
    assert out[0]["claim"] == "value durability"
    assert "check_name" not in out[0]
    assert _identifier_tokens(json.dumps(out)) == []


def test_claims_view_drops_retrieval_bookkeeping():
    """`retrieval_failed` and friends describe HOW we looked, never what is true."""
    claims = [{"check_name": "pain_reality", "verdict": "supported", "confidence": 1.0,
               "rationale": "r", "queries": ["q"], "query_source": "llm",
               "degraded": True, "retrieval_failed": False, "provider": "claude_cli",
               "provisional": True}]
    out = _claims_prompt_view(claims)
    for gone in ("queries", "query_source", "degraded", "retrieval_failed", "provider",
                 "provisional", "query source", "retrieval failed"):
        assert gone not in out[0]
    assert set(out[0]) <= {"claim"} | {k.replace("_", " ") for k in _CHECK_PROMPT_KEEP}


def test_unknown_future_check_still_gets_a_readable_label():
    """An unmapped check must degrade to a phrase, never fall through as snake_case."""
    out = _claims_prompt_view([{"check_name": "brand_new_gate", "verdict": "supported"}])
    assert out[0]["claim"] == "brand new gate"
    assert "_" not in out[0]["claim"]


@pytest.mark.parametrize("view", ["candidate", "claims"])
def test_projection_is_json_serialisable(view):
    """It is injected via json.dumps at the call site; a non-serialisable value crashes generation."""
    if view == "candidate":
        json.dumps(_candidate_prompt_view(_real_candidate()))
    else:
        json.dumps(_claims_prompt_view([{"check_name": "legality", "verdict": "supported"}]))
