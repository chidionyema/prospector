"""The output ceiling is per stage, and the two repair calls now declare one.

One global `max_tokens` gave a one-sentence shelf-copy rewrite the same 65536-token budget as a
full dossier. `docs/CONTENT_CONTRACT_PROGRAM.md:489` records what that costs when the model runs
away on the small ask: 23 minutes and $0.059 for no answer. The ceiling could not just be lowered,
because generation genuinely uses it (measured over 33,553 `event: spend` records in
`store/prospector.jsonl`: `generate` p50 32,094 / p95 65,536 against `verdict` p50 390 / max
6,591).

The mechanism that tells the two apart already existed — `telemetry.stage()` — but the shelf-copy
rewrite and the title repair were the only two model calls in the engine running outside it, so
the one call that ran away was the one call the ledger could not see. Both halves are pinned here:
the resolver, and the fact that those two sites declare a stage at all.
"""
from __future__ import annotations

import json

import pytest

from prospector import operator as O
from prospector.telemetry import stage as telemetry_stage


@pytest.fixture(autouse=True)
def clean_table(monkeypatch):
    """Every test starts from an empty table and no env override."""
    monkeypatch.delenv(O.MINIMAX_MAX_TOKENS_ENV, raising=False)
    monkeypatch.setattr(O, "_MINIMAX_MAX_TOKENS_BY_STAGE", {})
    yield


# ------------------------------------------------------------------ the resolver

def test_an_undeclared_stage_keeps_the_old_ceiling():
    """The safe direction. A stage nobody has measured must not be narrowed blind — clipping a
    long honest answer produces `_MiniMaxTruncated` and two MORE full-budget retries, which is
    more expensive than the ceiling it was meant to save."""
    O.set_minimax_max_tokens({"verdict": 16384})
    assert O.minimax_max_tokens_for_stage("generate") == O.MINIMAX_MAX_TOKENS_DEFAULT == 65536
    assert O.minimax_max_tokens_for_stage("") == 65536


def test_a_declared_stage_gets_its_own_ceiling():
    O.set_minimax_max_tokens({"verdict": 16384, "prescreen": 8192})
    assert O.minimax_max_tokens_for_stage("verdict") == 16384
    assert O.minimax_max_tokens_for_stage("prescreen") == 8192


def test_the_stage_is_read_from_the_telemetry_context_when_not_passed():
    """`_raw_once` holds no Config and no stage argument. The contextvar is the only channel."""
    O.set_minimax_max_tokens({"verdict": 16384})
    assert O.minimax_max_tokens_for_stage() == 65536
    with telemetry_stage("verdict"):
        assert O.minimax_max_tokens_for_stage() == 16384
    assert O.minimax_max_tokens_for_stage() == 65536, "the stage must not leak past its block"


def test_env_overrides_config_so_an_incident_is_capped_without_a_deploy(monkeypatch):
    """Same precedence as `set_minimax_concurrency` and `moat_primary()`."""
    O.set_minimax_max_tokens({"verdict": 16384})
    monkeypatch.setenv(O.MINIMAX_MAX_TOKENS_ENV, "2048")
    assert O.minimax_max_tokens_for_stage("verdict") == 2048
    assert O.minimax_max_tokens_for_stage("generate") == 2048


@pytest.mark.parametrize("junk", ["", "nonsense", "0", "-1"])
def test_an_unusable_env_value_falls_through_rather_than_zeroing_the_budget(monkeypatch, junk):
    """A typo in a plist must not send `max_tokens: 0` to the endpoint."""
    O.set_minimax_max_tokens({"verdict": 16384})
    monkeypatch.setenv(O.MINIMAX_MAX_TOKENS_ENV, junk)
    assert O.minimax_max_tokens_for_stage("verdict") == 16384


def test_a_load_with_no_table_resets_it_so_a_fixture_config_cannot_poison_the_next_load():
    O.set_minimax_max_tokens({"verdict": 16384})
    O.set_minimax_max_tokens(None)
    assert O.minimax_max_tokens_for_stage("verdict") == 65536


@pytest.mark.parametrize("bad", [
    {"verdict": "lots"},
    {"verdict": 0},
    {"verdict": -8},
    {"verdict": None},
    ["verdict", 16384],
])
def test_a_ceiling_that_cannot_mean_what_it_says_stops_the_process(bad):
    """Deliberately louder than `set_minimax_concurrency`, which falls back to a working default.

    A bad width still leaves a running engine. A bad entry here would read as a configured
    ceiling while silently leaving that stage at 65536 — the same configured-but-inert failure
    `_validate_retrieval` and `_validate_admissibility` already stop at startup.
    """
    with pytest.raises(ValueError, match="minimax_max_tokens"):
        O.set_minimax_max_tokens(bad)


# ------------------------------------------------------------------ the wire

def test_the_resolved_ceiling_reaches_the_request_body(monkeypatch):
    """The resolver is worthless if the payload still carries a constant. Assert the bytes."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    op = O.MiniMaxOperator()
    O.set_minimax_max_tokens({"verdict": 16384})
    seen: list[dict] = []

    def fake_read(req, *, stall_timeout, total_deadline):
        seen.append(json.loads(req.data.decode("utf-8")))
        return '{"ok": 1}', {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "stop"

    monkeypatch.setattr(O, "_read_sse_bounded", fake_read)

    with telemetry_stage("verdict"):
        op._raw_once("sys", "user", 0.0)
    with telemetry_stage("generate"):
        op._raw_once("sys", "user", 0.0)

    assert [p["max_tokens"] for p in seen] == [16384, 65536]


# ------------------------------------------------------------------ the two undeclared sites

class _StageSpy:
    """An operator that records the telemetry stage in force when it is called."""

    def __init__(self, answer: dict):
        self.answer = answer
        self.stages: list[str] = []

    def complete_json(self, system, user, **kw):
        from prospector.telemetry import STAGE
        self.stages.append(STAGE.get(""))
        return self.answer


def test_the_title_repair_call_declares_its_stage():
    from types import SimpleNamespace

    from prospector.field_write import _propose_title

    spy = _StageSpy({"title": "A shorter title"})
    cand = SimpleNamespace(one_liner="", who_pays="", tags={}, market="")
    assert _propose_title(cand, "old title", "too long", 1, spy) == "A shorter title"
    assert spy.stages == ["title_repair"]


def test_the_shelf_copy_rewrite_call_declares_its_stage():
    from prospector.shelf_copy_repair import rewrite_one

    spy = _StageSpy({"one_liner": ""})
    rewrite_one(spy, "A title", "A line that needs work.", attempts=1)
    assert spy.stages == ["shelf_copy_repair"], (
        "this is the call that spent 23 minutes unattributed; it must name itself"
    )


def test_every_model_call_on_the_publish_path_is_inside_a_stage():
    """A ratchet, not a spot check. `complete_json` outside a stage is a call the spend ledger
    cannot attribute and `minimax_max_tokens_for_stage` cannot bound, which is exactly how the
    runaway rewrite hid. Kept to the publish path — the modules a pack's title and one-liner
    actually travel through — so it fails on a regression here rather than on unrelated work."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "prospector"
    offenders, scanned = [], 0
    for name in ("field_write.py", "shelf_copy_repair.py", "artifacts.py", "verify.py",
                 "prescreen.py", "score.py", "generate.py", "critique.py",
                 "price_comparables.py"):
        lines = (root / name).read_text().splitlines()
        for i, line in enumerate(lines):
            if not re.search(r"\.complete_json\(", line):
                continue
            scanned += 1
            # The stage opens within the enclosing block, so look back a short window.
            window = "\n".join(lines[max(0, i - 12):i])
            if "telemetry_stage(" not in window and "telemetry.stage(" not in window:
                offenders.append(f"{name}:{i + 1}: {line.strip()}")
    assert not offenders, "model calls outside any telemetry stage:\n" + "\n".join(offenders)
    # Non-vacuity. A rename of `complete_json` would otherwise leave this test scanning nothing
    # and reporting green, which is the guard-that-iterates-an-empty-list failure.
    assert scanned >= 14, f"the scan matched only {scanned} model calls — has it stopped seeing them?"
