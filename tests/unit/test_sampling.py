"""Tests for the G4 Verbalized Sampling directive (prospector.sampling).

`typicality_directive` is the prompt-side generator: gate, count formatting, and
failure isolation. `typicality_score` is the parse side: it must mirror the
automatability coercion in generate.py:66 — same numeric rule, same percentage rule,
same clamp — so the two self-reported fields behave identically in the diversity meter."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from prospector.sampling import typicality_directive, typicality_score

# ----- typicality_directive --------------------------------------------------


def test_directive_gated_off():
    """No verbalized_sampling block => no directive."""
    cfg = SimpleNamespace(generation={})
    assert typicality_directive(cfg, k=10) == ""

    # Present but empty / unenabled => no directive.
    cfg = SimpleNamespace(generation={"verbalized_sampling": {}})
    assert typicality_directive(cfg, k=10) == ""


def test_directive_states_a_concrete_count():
    """The minimum atypical count is computed and rendered in plain English."""
    cfg = SimpleNamespace(generation={
        "verbalized_sampling": {
            "enabled": True,
            "min_atypical_fraction": 0.4,
            "atypical_threshold": 0.3,
        },
    })
    out = typicality_directive(cfg, k=10)
    assert "At least 4 of the 10 ideas" in out
    assert "typicality <= 0.3" in out


def test_directive_count_never_zero():
    """k=1 with a tiny fraction must still ask for at least 1 atypical idea."""
    cfg = SimpleNamespace(generation={
        "verbalized_sampling": {
            "enabled": True,
            "min_atypical_fraction": 0.1,
        },
    })
    out = typicality_directive(cfg, k=1)
    assert "At least 1 of the 1 ideas" in out


def test_directive_never_raises():
    """A non-numeric config degrades to "" — never raises into the generation path."""
    cfg = SimpleNamespace(generation={
        "verbalized_sampling": {
            "enabled": True,
            "min_atypical_fraction": "not a number",
        },
    })
    assert typicality_directive(cfg, k=5) == ""


# ----- typicality_score ------------------------------------------------------


@pytest.mark.parametrize("val,expected", [
    (0.3, 0.3),
    ("0.25", 0.25),
    (40, 0.4),
    ("85%", 0.85),
    (1.0, 1.0),
    (0, 0.0),
    (None, None),
    ("", None),
    ("banana", None),
    (True, None),
    (False, None),
])
def test_typicality_score_coercions(val, expected):
    """The parse-side numeric rule mirrors `_automatability_score` for symmetry."""
    assert typicality_score(val) == expected


def test_typicality_score_clamps_out_of_range():
    """Values outside [0, 1] are clamped, not echoed raw."""
    assert typicality_score(150) == 1.0
    assert typicality_score(-0.5) == 0.0
