"""E4: per-stage token attribution via the telemetry.stage() context manager.

Mirrors the PHASE contextvar pattern (prospector/telemetry.py) at finer
granularity — every call to ``with telemetry.stage("<step>"):`` around an
``Operator.complete_json(...)`` attaches the active step to the resulting usage
record, so the cost report can break spend down per pipeline step instead of
only per phase.

The context manager is the API on purpose: it keeps the STAGE tag out of
``Operator.complete_json``'s signature so test doubles with strict signatures
never have to learn about it.
"""
from __future__ import annotations

import json

import pytest

from prospector import telemetry
from prospector.operator import MockOperator
from prospector.report import costs_report


# --- fixtures ----------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_state():
    """Reset telemetry and STAGE between tests so cross-test leakage can't
    mask a missing reset on the happy path."""
    telemetry.reset_usage()
    prev_stage = telemetry.STAGE.get()
    yield
    telemetry.reset_usage()
    # Restore prior stage so test order never leaks into another suite.
    telemetry.STAGE.set(prev_stage)


def _stage_capture_op():
    """MockOperator whose _raw records STAGE.get() at the moment record_usage
    is called. Wrapping the call in ``with telemetry.stage(...):`` makes the
    captured value exactly what telemetry.record_usage would have read."""
    captured: list[str] = []

    class _CaptureOp(MockOperator):
        def _raw(self, system, user, temperature):
            captured.append(telemetry.STAGE.get())
            return super()._raw(system, user, temperature)

    return _CaptureOp(), captured


# --- 1: stage("...") sets STAGE during the block -----------------------------
def test_stage_context_manager_sets_stage_on_usage_record():
    """A ``with telemetry.stage("verdict"):`` block makes STAGE == "verdict"
    observable to record_usage at the moment it runs — the value that ends up
    on the usage record's stage field."""
    op, captured = _stage_capture_op()
    with telemetry.stage("verdict"):
        op.complete_json("sys", "user")

    assert captured == ["verdict"], (
        "STAGE contextvar was not set to the supplied value during the call; "
        "either the context manager is missing or record_usage reads STAGE "
        "before the with-block sets it"
    )


# --- 2: STAGE is RESET after the block, INCLUDING when the body raises -------
def test_stage_contextvar_is_reset_after_block():
    """A following call inside an UNTAGGED context manager sees STAGE == "" —
    not "verdict" — so the contextvar never leaks across blocks."""
    op, _ = _stage_capture_op()
    with telemetry.stage("verdict"):
        op.complete_json("sys", "user")

    # Following call is OUTSIDE any stage block — STAGE must be back to its default.
    op.complete_json("sys2", "user2")

    # If the reset were missing, telemetry.STAGE.get() here would still be "verdict"
    # and the next record_usage would attribute this call to verdict. The reset
    # inside the context manager's finally block is what flips it back.
    assert telemetry.STAGE.get() == "", (
        f"STAGE leaked across blocks; got {telemetry.STAGE.get()!r} after an "
        "untagged call that should have seen an empty contextvar"
    )


def test_stage_contextvar_is_restored_when_body_raises():
    """An exception inside the ``with`` body MUST still reset STAGE on the way
    out — a leaked "verdict" would mis-attribute every later spend row."""
    with telemetry.stage("verdict"):
        with pytest.raises(RuntimeError, match="boom"):
            raise RuntimeError("boom")

    assert telemetry.STAGE.get() == "", (
        f"STAGE leaked from a raising block; got {telemetry.STAGE.get()!r} "
        "after the exception unwound — the context manager's finally block "
        "did not run or did not call STAGE.reset"
    )


# --- 3: nested stages — outer value survives inner block exit ----------------
def test_outer_stage_survives_nested_inner_block_exit():
    """Entering an inner ``with telemetry.stage("inner"):`` inside an outer
    ``with telemetry.stage("outer"):`` must leave STAGE == "outer" again on
    exit from the inner block, exactly as a balanced try/finally would."""
    with telemetry.stage("outer"):
        assert telemetry.STAGE.get() == "outer"
        with telemetry.stage("inner"):
            assert telemetry.STAGE.get() == "inner"
        # Inner exited — outer must still be visible.
        assert telemetry.STAGE.get() == "outer", (
            f"outer STAGE was not restored after inner block exit; got "
            f"{telemetry.STAGE.get()!r}"
        )
    # And after the outer block ends the contextvar is back to the suite default.
    assert telemetry.STAGE.get() == "", (
        "outer STAGE was not cleared after the outermost block exited"
    )


# --- 4: costs_report groups legacy records under "untagged" -------------------
def test_costs_report_groups_legacy_records_under_untagged(tmp_path):
    """A usage log row without a stage field must group under "untagged" in
    the by-stage section — pre-E4 history must stay visible, not be silently
    dropped."""
    log = tmp_path / "prospector.jsonl"
    # Same shape as test_costs_parses_audit_log, but with explicit stage=None
    # on the legacy row to simulate a pre-E4 audit log entry.
    lines = [
        {"event": "spend", "amount_usd": 0.05, "phase": "signal_pipeline"},
        {"message": "Claude CLI usage", "web": True, "input": 100, "output": 50,
         "total": 200},  # no `stage` key — legacy row
        {"event": "latency", "operation": "claude_cli_search", "latency_ms": 5000.0},
    ]
    log.write_text("\n".join(json.dumps(x) for x in lines))

    out = costs_report(log)
    assert "SPEND BY STAGE" in out, "by-stage section missing from cost report"
    assert "untagged" in out, "legacy row was not grouped under 'untagged'"
    # Pre-existing sections still present — the E4 change must not regress them.
    assert "SPEND BY AGENT / PROVIDER" in out
