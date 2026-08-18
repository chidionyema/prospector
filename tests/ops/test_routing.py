"""R20 — the verdict roster is editable, and the fence is in the WRITER.

The requirement's probe, verbatim from `docs/OPS_CONSOLE_PROGRAM.md:916`:
*"writer refuses an untrusted head; test asserts cold-import never answers"*.

Both halves are here, and both are about the same failure: **a roster change breaks nothing
visible.** No rail goes red, the daemon keeps ticking, spend keeps accruing — the only symptom is
that PASSes stop reaching the shelf, days later, because everything is being stamped provisional
(`operator.py:1509` → `run.py:1157`). So the fence cannot live in a UI, and the panel cannot
answer from a cold import.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest
import yaml

from prospector import operator as _op
from prospector.ops import config_editor as _ce
from prospector.ops import routing as R

_CONFIG = """\
# The roster's rationale, which a save must not eat.
operator: [minimax, claude_cli]      # the verdict chain, failover order
noncritical_operator: [minimax]
moat_primary: [minimax, claude_cli]  # who may rule FINALLY

thresholds:
  confidence_floor: 0.4
  min_composite_to_pass: 3.0

hard_gates:
  - value_durability: [refuted]
  - legality: [refuted]

spend:
  daily_cap_usd: 100.0
"""


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(_CONFIG, encoding="utf-8")
    monkeypatch.setattr(_ce, "CONFIG_PATH", path)
    monkeypatch.setattr(_ce, "_CC_DIR", tmp_path / "cc")
    monkeypatch.delenv(_op.MOAT_PRIMARY_ENV, raising=False)
    return path


@pytest.fixture
def cfg(tmp_path):
    """Only the store dir is read from cfg by the writer — the receipt log lives under it."""
    return types.SimpleNamespace(store_dir=tmp_path, store={"dir": str(tmp_path)},
                                 operator=["minimax", "claude_cli"],
                                 noncritical_operator=["minimax"],
                                 moat_primary=["minimax", "claude_cli"])


def _on_disk(path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _receipts(tmp_path) -> list[dict]:
    log = tmp_path / "ops" / "intents.jsonl"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


# --------------------------------------------------------------------------- #
# The fence, as a pure function (both surfaces call exactly this)
# --------------------------------------------------------------------------- #
def test_an_untrusted_head_is_a_problem():
    problems = R.routing_problems(["minimax", "claude_cli"], ["claude_cli"])
    assert problems and "provisional" in problems[0]
    assert "publish" in problems[0]


def test_a_trusted_head_with_a_provisional_tail_is_allowed():
    """The tail is SUPPOSED to be able to be provisional — that is the 2026-08-08 directive
    (exhaustion means provisional first, DEFER only when the tail is down too). A fence that
    demanded a fully-trusted chain would forbid the design."""
    assert R.routing_problems(["minimax", "deepseek"], ["minimax"]) == []
    assert any("provisional fallbacks" in a
               for a in R.routing_advisories(["minimax", "deepseek"], ["minimax"]))


def test_an_empty_roster_is_a_problem():
    assert any("fall back" in p for p in R.routing_problems(["minimax"], []))


def test_a_tier_no_adapter_can_build_is_a_problem():
    for dead in ("claude", "cursor_cli", "standardcompute"):
        assert any("no adapter can build" in p
                   for p in R.routing_problems([dead], [dead])), dead


# --------------------------------------------------------------------------- #
# The writer refuses — and the refusal is a receipt
# --------------------------------------------------------------------------- #
def test_the_writer_refuses_an_untrusted_head_and_leaves_the_file_alone(cfg_file, cfg, tmp_path):
    before = cfg_file.read_text(encoding="utf-8")
    receipt = R.set_moat_primary(cfg, ["claude_cli"], actor="test", reason="drop minimax")

    assert receipt["applied"] is False
    assert any("stop selling" in p for p in receipt["problems"]), receipt
    assert cfg_file.read_text(encoding="utf-8") == before, "a refused write must be a no-op"
    assert _receipts(tmp_path)[-1]["applied"] is False, "a refusal is logged too"


def test_the_writer_refuses_an_empty_roster(cfg_file, cfg):
    assert R.set_moat_primary(cfg, [])["applied"] is False
    assert _on_disk(cfg_file)["moat_primary"] == ["minimax", "claude_cli"]


def test_the_writer_refuses_a_tier_that_cannot_be_built(cfg_file, cfg):
    r = R.set_moat_primary(cfg, ["minimax", "claude"])
    assert r["applied"] is False
    assert _on_disk(cfg_file)["moat_primary"] == ["minimax", "claude_cli"]


# --------------------------------------------------------------------------- #
# The writer writes — surgically
# --------------------------------------------------------------------------- #
def test_a_legal_roster_is_written_and_keeps_every_comment(cfg_file, cfg, tmp_path):
    before = cfg_file.read_text(encoding="utf-8").splitlines()
    n_comments = sum(1 for ln in before if "#" in ln)

    receipt = R.set_moat_primary(cfg, ["minimax"], actor="chidi", reason="minimax only")
    after = cfg_file.read_text(encoding="utf-8").splitlines()

    assert receipt["applied"] and receipt["changed"], receipt
    assert _on_disk(cfg_file)["moat_primary"] == ["minimax"]
    assert sum(1 for ln in after if "#" in ln) == n_comments
    assert len(after) == len(before)
    assert [i for i, (a, b) in enumerate(zip(before, after)) if a != b] == [3]
    last = _receipts(tmp_path)[-1]
    assert last["actor"] == "chidi" and last["before"] == ["minimax", "claude_cli"]


def test_a_moat_primary_change_uncertifies(cfg_file, cfg):
    """It is moat-affecting by definition — it is the definition."""
    assert R.set_moat_primary(cfg, ["minimax"])["applied"]
    assert _ce.load_certification().get("certified") is False


def test_writing_the_roster_it_already_has_changes_nothing(cfg_file, cfg):
    mtime = cfg_file.stat().st_mtime
    receipt = R.set_moat_primary(cfg, ["minimax", "claude_cli"])
    assert receipt["applied"] and receipt["changed"] is False
    assert cfg_file.stat().st_mtime == mtime


def test_a_replayed_nonce_does_not_write_twice(cfg_file, cfg, tmp_path):
    """A Telegram tap that arrives twice must not re-apply a roster a human has since edited
    (`idempotency-keys-expire-they-are-not-dedup`)."""
    first = R.set_moat_primary(cfg, ["minimax"], actor="phone", nonce="abc123")
    assert first["applied"]

    # Someone widens it again by hand between the two deliveries.
    R.set_moat_primary(cfg, ["minimax", "claude_cli"], actor="desk")
    replay = R.set_moat_primary(cfg, ["minimax"], actor="phone", nonce="abc123")

    assert replay.get("replayed") is True
    assert _on_disk(cfg_file)["moat_primary"] == ["minimax", "claude_cli"], \
        "the replay must not re-narrow the roster"


# --------------------------------------------------------------------------- #
# One fence, three surfaces
# --------------------------------------------------------------------------- #
def test_the_streamlit_save_path_refuses_the_same_roster(cfg_file):
    bad = yaml.safe_load(_CONFIG)
    bad["moat_primary"] = ["claude_cli"]          # head `minimax` is now untrusted

    ok, errors = _ce.validate_config(bad)
    assert not ok and any("stop selling" in e for e in errors), errors

    wrote, msg = _ce.write_config(bad, moat_affecting=True, orig_mtime=_ce.get_config_mtime())
    assert wrote is False, msg
    assert _on_disk(cfg_file)["moat_primary"] == ["minimax", "claude_cli"]


# --------------------------------------------------------------------------- #
# The reader — §14.5.1, the trap this requirement names
# --------------------------------------------------------------------------- #
def test_a_cold_import_answers_the_default_not_the_config():
    """THE PROBE. A fresh process that imports `operator` without `load_config` answers
    `{claude_cli}` — while config.yaml on disk says otherwise. Nothing raises; the number is
    simply wrong, which is the kind of wrong nobody re-checks."""
    declared = yaml.safe_load(open("config.yaml", encoding="utf-8"))["moat_primary"]
    out = subprocess.run(
        [sys.executable, "-c",
         "import prospector.operator as o; import json; print(json.dumps(sorted(o.moat_primary())))"],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
    )
    cold = json.loads(out.stdout.strip().splitlines()[-1])

    assert cold == sorted(_op.MOAT_PRIMARY_DEFAULT)
    assert set(cold) != set(declared), (
        "config.yaml no longer differs from the cold-import default, so this trap is currently "
        "invisible — the fence below still matters and must not be removed")


def test_routing_view_refuses_to_answer_from_a_cold_process_global(monkeypatch):
    monkeypatch.delenv(_op.MOAT_PRIMARY_ENV, raising=False)
    monkeypatch.setattr(_op, "_MOAT_PRIMARY", None)      # exactly the cold-import state
    cold_cfg = types.SimpleNamespace(operator=["minimax", "claude_cli"],
                                     noncritical_operator=["minimax"],
                                     moat_primary=["minimax", "claude_cli"])

    with pytest.raises(R.StaleProcessGlobal):
        R.routing_view(cold_cfg)


def test_routing_view_answers_once_config_was_loaded_the_way_the_engine_loads_it(monkeypatch):
    monkeypatch.delenv(_op.MOAT_PRIMARY_ENV, raising=False)
    monkeypatch.setattr(_op, "_MOAT_PRIMARY", None)
    from prospector.ops.readmodel import load_cfg

    live = load_cfg()                       # installs the process globals, as config.py:1142 does
    view = R.routing_view(live)

    assert view["trusted"] == sorted(view["moat_primary_declared"])
    assert view["head"] == view["operator"][0]
    assert view["head_trusted"] is (view["head"] in view["trusted"])
    assert view["publishes"] is (view["head_trusted"] and not view["problems"])
    assert view["trusted_source"] == "config.yaml moat_primary"


def test_an_env_override_is_reported_as_the_source_and_does_not_raise(monkeypatch):
    """`PROSPECTOR_MOAT_PRIMARY` outranks the file (`operator.py:1446`). The view must say so
    rather than flag the disagreement it creates by design."""
    monkeypatch.setenv(_op.MOAT_PRIMARY_ENV, "mock")
    cfg = types.SimpleNamespace(operator=["mock"], moat_primary=["minimax"],
                                noncritical_operator=["minimax"])

    view = R.routing_view(cfg)
    assert view["trusted"] == ["mock"]
    assert view["trusted_source"] == f"${_op.MOAT_PRIMARY_ENV}"
