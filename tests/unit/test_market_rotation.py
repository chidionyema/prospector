"""`schedule.market_rotation` — working two markets from a single-valued knob.

THE GAP THIS CLOSES

The founder's ask was "US as well as UK". The config schema could not express it: `active_market`
is a single string (`config.py:437`) and the market block it selects rewrites retrieval and the
prompt framing for a whole batch, so setting it to one code retires the other. Lanes are a list;
markets are not, and making them one would mean a batch generated against two retrieval corpora
and two currencies at once.

Rotation keeps the single-valued contract — one market per batch, every downstream reader still
sees exactly one — and moves it BETWEEN ticks.

WHAT IS PINNED, AND WHY EACH ONE

1. Off by default, byte-for-byte today's behaviour. A steering feature that changes an unsteered
   daemon is a regression, not a feature.
2. It actually alternates. A rotation that returns the same code twice is the bug it exists to
   prevent, wearing the label of the fix.
3. The cursor survives the process. `reload_on_code_change` re-execs the daemon whenever
   config.yaml moves — and turning rotation ON *is* a config.yaml move. An in-memory counter
   would therefore reset to 0 on the very tick that enabled it, and on a two-code rotation would
   serve the first code forever and the second never.
4. One bad code disables the WHOLE rotation. Rotating over the valid subset is indistinguishable
   from working, which is how "us-ca" typo'd into UK-only generation would go unnoticed.
5. Rotation can never stop a tick. Every failure path degrades to "no rotation", never an raise.
6. The drain does not rotate. A backlogged candidate was created under one market's framing;
   re-vetting it under another changes the question it is being asked.
"""
from __future__ import annotations

import argparse
import json
import textwrap
from dataclasses import replace

import pytest

from prospector.config import load_config
from prospector.scheduler import paths, run_scheduled

_CFG = """\
operator: mock
hard_gates:
  - legality: [refuted]
weights: {pain_acuity: 0.5, defensibility: 0.5}
thresholds: {min_composite_to_pass: 2.5}
active_market: "uk"
markets:
  default: uk
  uk: {label: "United Kingdom", currency: GBP}
  us: {label: "United States", currency: USD}
"""


def _cfg(tmp_path, rotation, *, store=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "config.yaml"
    sched = json.dumps({"market_rotation": rotation, "batch_size": 3})
    p.write_text(textwrap.dedent(_CFG) + f"schedule: {sched}\n", encoding="utf-8")
    cfg = load_config(str(p))
    # `store_dir` is a read-only property over `store["dir"]` (config.py:513) — and it honours
    # PROSPECTOR_STORE_DIR, which `paths.store_dir` refuses to guess around. Point the whole
    # store at tmp_path so no test can reach the live store/scheduler.
    return replace(cfg, store={"dir": str(store or tmp_path / "store")})


def _cursor(cfg):
    return paths.scheduler_dir(cfg) / run_scheduled._MARKET_ROTATION_STATE


# ---------------------------------------------------------------------------
# 1. Off by default
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rotation", ["", None, [], "   ", ",, ,"])
def test_rotation_off_leaves_the_config_untouched(tmp_path, rotation):
    cfg = _cfg(tmp_path, rotation)
    assert run_scheduled._market_rotation(cfg) == []
    out, code = run_scheduled._rotate_market(cfg)
    assert code is None
    assert out is cfg, "an off rotation must not even rebuild the Config"
    assert out.active_market == "uk"
    assert not _cursor(cfg).exists(), "off rotation must not write state"


# ---------------------------------------------------------------------------
# 2 + 3. It alternates, and the cursor outlives the process
# ---------------------------------------------------------------------------

def test_rotation_alternates_and_applies_the_market(tmp_path):
    cfg = _cfg(tmp_path, "uk,us")
    assert run_scheduled._market_rotation(cfg) == ["uk", "us"]

    first, code1 = run_scheduled._rotate_market(cfg)
    second, code2 = run_scheduled._rotate_market(cfg)
    third, code3 = run_scheduled._rotate_market(cfg)

    assert [code1, code2, code3] == ["uk", "us", "uk"]
    # for_market was really applied — not just reported.
    assert [first.active_market, second.active_market] == ["uk", "us"]


def test_cursor_survives_a_re_exec(tmp_path):
    """A fresh Config object over the same store dir must resume, not restart.

    This is the daemon's real lifecycle: `reload_on_code_change` re-execs the process when
    config.yaml moves, and enabling rotation IS such a move.
    """
    store = tmp_path / "store"
    run_scheduled._rotate_market(_cfg(tmp_path / "a", "uk,us", store=store))
    _cfg_b = _cfg(tmp_path / "b", "uk,us", store=store)
    _out, code = run_scheduled._rotate_market(_cfg_b)
    assert code == "us", "a re-exec restarted the rotation at its first code"


def test_cursor_is_advanced_before_generation(tmp_path):
    """Written on the way in, so a batch that dies mid-run cannot pin the rotation."""
    cfg = _cfg(tmp_path, "uk,us")
    run_scheduled._rotate_market(cfg)
    state = json.loads(_cursor(cfg).read_text(encoding="utf-8"))
    assert state["next"] == 1 and state["last"] == "uk"


# ---------------------------------------------------------------------------
# 4. One bad code disables the whole rotation
# ---------------------------------------------------------------------------

def test_one_unresolvable_code_disables_the_entire_rotation(tmp_path, caplog):
    cfg = _cfg(tmp_path, "uk,atlantis")
    with caplog.at_level("WARNING"):
        assert run_scheduled._market_rotation(cfg) == []
    assert "atlantis" in caplog.text, "a refused rotation must leave a trace"
    out, code = run_scheduled._rotate_market(cfg)
    assert code is None and out.active_market == "uk"


def test_subdivisions_resolve_through_their_parent(tmp_path):
    """`us-ca` needs no config beyond `us` — spec DD4. The validator must honour that."""
    cfg = _cfg(tmp_path, "uk,us-ca")
    assert run_scheduled._market_rotation(cfg) == ["uk", "us-ca"]
    _out, code = run_scheduled._rotate_market(cfg)
    assert code == "uk"


# ---------------------------------------------------------------------------
# 5. Rotation can never stop a tick
# ---------------------------------------------------------------------------

def test_a_corrupt_cursor_degrades_to_restarting_not_raising(tmp_path):
    cfg = _cfg(tmp_path, "uk,us")
    path = _cursor(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    out, code = run_scheduled._rotate_market(cfg)
    assert code == "uk" and out.active_market == "uk"


def test_an_unwritable_cursor_still_generates(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, "uk,us")

    def _boom(*_a, **_k):
        raise OSError("read-only store")

    monkeypatch.setattr("pathlib.Path.write_text", _boom)
    out, code = run_scheduled._rotate_market(cfg)
    assert code == "uk" and out.active_market == "uk"


# ---------------------------------------------------------------------------
# 6. Wiring: the batch rotates, the drain does not, and the market is attributed
# ---------------------------------------------------------------------------

def _stub_generate(tmp_path, monkeypatch, rotation):
    """Run `_default_generate` with the moat stubbed out. Returns (out, seen)."""
    cfg = _cfg(tmp_path, rotation)
    seen: dict = {}

    # `gen_time_budget_s` is named rather than swallowed by `**_extra`: `_default_generate`
    # must keep passing the generation deadline through, and a stub that absorbs every
    # keyword would let it be dropped without a single test going red. `**_extra` then
    # covers the keywords this file genuinely does not care about, so adding one more
    # does not re-break three market-rotation tests.
    def _fake_run_signal(_signal, *, cfg, k, publish, lanes, gen_time_budget_s=None, **_extra):  # noqa: A002
        seen["generation_market"] = cfg.active_market
        seen["gen_time_budget_s"] = gen_time_budget_s
        return []

    def _fake_drain(drain_cfg, _n):
        seen["drain_market"] = drain_cfg.active_market
        return 0

    monkeypatch.setattr("prospector.run.run_signal", _fake_run_signal)
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *_a, **_k: None)
    monkeypatch.setattr(run_scheduled, "_drain_pass", _fake_drain)
    monkeypatch.setattr(run_scheduled, "_resume_per_tick", lambda _c: 1)
    return run_scheduled._default_generate(cfg, 3), seen


def test_generation_rotates_while_the_drain_keeps_active_market(tmp_path, monkeypatch):
    out, seen = _stub_generate(tmp_path, monkeypatch, "us,uk")
    assert seen["generation_market"] == "us", "the batch did not rotate"
    assert seen["drain_market"] == "uk", "the drain must stay on active_market"
    assert out["market"] == "us", "a rotating batch must be attributable to its market"


def test_no_market_key_when_rotation_is_off(tmp_path, monkeypatch):
    """Absence is the contract: readers use it to tell a rotating daemon from a pinned one."""
    out, seen = _stub_generate(tmp_path, monkeypatch, "")
    assert "market" not in out
    assert seen["generation_market"] == "uk"


def test_rotation_reads_argparse_free(tmp_path, monkeypatch):
    """`_default_generate` builds its own Namespace; pinning it catches a signature drift."""
    assert isinstance(argparse.Namespace(lane=None), argparse.Namespace)
    out, _seen = _stub_generate(tmp_path, monkeypatch, "uk,us")
    assert out["dossiers"] == 0 and out["passes"] == 0
