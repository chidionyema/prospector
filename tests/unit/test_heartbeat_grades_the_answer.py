"""The heartbeat must grade the ANSWER, cover every model, and never bench a brain.

Founder directive 2026-08-21: "need heatbeat", "for all nodels in platforn", "when enabeld fron
ops, should be able to test fron ops console and cconfirn nodel is active".

Each test here pins a way a monitor can be worse than no monitor:
  * reporting a provider alive because the socket opened, when the body was an upsell;
  * covering the built-in tiers and silently missing every provider added by config;
  * marking a brain dead, or eating the half-open recovery probe a real call is owed;
  * billing the founder every quarter hour on a metered tier to learn nothing.
"""

from __future__ import annotations

import json

import pytest

from prospector.ops import heartbeat as hb


class _Answering:
    _model = "test-model-1"

    def __init__(self, reply):
        self._reply = reply
        self.calls = 0

    def _raw(self, system, user, temperature):
        self.calls += 1
        return self._reply


class _Raising:
    _model = "test-model-1"

    def __init__(self, exc):
        self._exc = exc

    def _raw(self, system, user, temperature):
        raise self._exc


def _fake_build(monkeypatch, op):
    monkeypatch.setattr("prospector.operator._build_operator",
                        lambda kind, cfg, fast, component=None: op)


def test_a_two_hundred_carrying_an_upsell_is_not_alive(monkeypatch, cfg):
    """The exact shape that hid StandardCompute's exhaustion for a day: HTTP 200, a well-formed
    body, and not one word of the answer that was asked for."""
    _fake_build(monkeypatch, _Answering(
        "You've used up your free trial — let's keep going. Set up your plan at /billing."))
    row = hb.probe_one(cfg, "groq")
    assert row["ok"] is False
    assert row["state"] == "answered_wrong"


def test_the_word_it_was_asked_for_is_what_makes_it_alive(monkeypatch, cfg):
    _fake_build(monkeypatch, _Answering("ALIVE"))
    row = hb.probe_one(cfg, "groq")
    assert row["ok"] is True and row["state"] == "alive"


def test_the_model_that_answered_is_reported(monkeypatch, cfg):
    """Founder: "cconfirn nodel is active". A provider that silently substitutes a model still
    answers correctly, so the tier name alone cannot answer the question that was asked."""
    _fake_build(monkeypatch, _Answering("alive"))
    assert hb.probe_one(cfg, "groq")["model"] == "test-model-1"


@pytest.mark.parametrize("detail,want", [
    ("HTTP Error 402: Payment Required — credit balance is too low", "exhausted_permanent"),
    ("HTTP Error 429: Too Many Requests — rate_limit_error", "exhausted_transient"),
    ("HTTP Error 413: Payload Too Large — on tokens per minute (TPM): Limit 8000, Requested 8267",
     "exhausted_transient"),
    ("socket hung up", "error"),
])
def test_a_failure_is_classified_not_merely_recorded(monkeypatch, cfg, detail, want):
    """"down" is not a repair instruction. Money, a wait and a bug need different answers, and
    the 413/TPM row is the one measured against Groq on 2026-08-21."""
    _fake_build(monkeypatch, _Raising(RuntimeError(detail)))
    assert hb.probe_one(cfg, "groq")["state"] == want


def test_the_heartbeat_marks_nothing_dead(monkeypatch, cfg):
    """A monitor that can bench a brain can take the engine down. It must only ever report."""
    marked = []
    monkeypatch.setattr("prospector.health.mark_exhausted",
                        lambda *a, **k: marked.append(a), raising=False)
    _fake_build(monkeypatch, _Raising(RuntimeError("HTTP Error 402: Payment Required")))
    hb.probe_one(cfg, "groq")
    assert marked == []


def test_every_model_the_platform_can_build_is_covered(cfg):
    """Founder: "for all nodels in platforn". Built-ins AND anything declared in config."""
    tiers = hb.platform_tiers(cfg)
    assert "claude_cli" in tiers and "minimax" in tiers
    for name in cfg.providers:
        assert name in tiers, f"declared provider {name} is invisible to the heartbeat"


def test_the_roster_is_not_hand_listed(cfg):
    """A provider declared in config appears without anyone editing this module."""
    from prospector.providers import DeclaredProvider

    cfg.providers = dict(cfg.providers)
    cfg.providers["a_brand_new_one"] = DeclaredProvider(
        name="a_brand_new_one", base_url="https://x.test/v1",
        api_key_env="A_BRAND_NEW_ONE_API_KEY", model="m")
    assert "a_brand_new_one" in hb.platform_tiers(cfg)


def test_fixtures_and_removed_tiers_are_not_probed(cfg):
    """`mock` proves nothing about the world; the removed tiers raise by design."""
    tiers = hb.platform_tiers(cfg)
    for name in ("mock", "claude", "cursor_cli", "standardcompute"):
        assert name not in tiers


def test_a_metered_tier_is_probed_on_the_long_cadence(monkeypatch, cfg, tmp_path):
    """One claude_cli probe measured $0.049. At the free cadence that is $4.70/day for an
    answer nothing was waiting on."""
    monkeypatch.setattr(hb, "heartbeat_path", lambda: tmp_path / "heartbeat.json")
    _fake_build(monkeypatch, _Answering("ALIVE"))
    cfg.heartbeat = {"interval_s": 900, "metered_interval_s": 21600}

    first = hb.run_heartbeat(cfg, tiers=("groq", "claude_cli"), now=1000.0)
    assert first["probed"] == ["claude_cli", "groq"]

    later = hb.run_heartbeat(cfg, tiers=("groq", "claude_cli"), now=1000.0 + 1000.0)
    assert later["probed"] == ["groq"], "a metered tier was re-probed inside its own cadence"
    assert "claude_cli" in later["skipped_not_due"]


def test_the_console_test_button_overrides_the_cadence(monkeypatch, cfg, tmp_path):
    """A person clicking Test is a person choosing to spend, and that choice wins."""
    monkeypatch.setattr(hb, "heartbeat_path", lambda: tmp_path / "heartbeat.json")
    _fake_build(monkeypatch, _Answering("ALIVE"))
    hb.run_heartbeat(cfg, tiers=("claude_cli",), now=1000.0)
    forced = hb.run_heartbeat(cfg, force=True, tiers=("claude_cli",), now=1001.0)
    assert forced["probed"] == ["claude_cli"]


def test_a_skipped_tier_keeps_its_last_answer_and_is_marked_stale(monkeypatch, cfg, tmp_path):
    """Dropping a row that was not due would make the console read "never probed" every round."""
    monkeypatch.setattr(hb, "heartbeat_path", lambda: tmp_path / "heartbeat.json")
    _fake_build(monkeypatch, _Answering("ALIVE"))
    hb.run_heartbeat(cfg, tiers=("claude_cli",), now=1000.0)
    out = hb.run_heartbeat(cfg, tiers=("claude_cli",), now=1500.0)
    row = out["providers"][0]
    assert row["tier"] == "claude_cli" and row["ok"] is True
    assert row["stale"] is True and row["age_s"] == 500.0


def test_the_round_is_readable_json_written_whole(monkeypatch, cfg, tmp_path):
    """Written through a temp file and os.replace, so a reader never sees half a round."""
    path = tmp_path / "heartbeat.json"
    monkeypatch.setattr(hb, "heartbeat_path", lambda: path)
    _fake_build(monkeypatch, _Answering("ALIVE"))
    hb.run_heartbeat(cfg, tiers=("groq",), now=1000.0)
    assert json.loads(path.read_text())["alive"] == ["groq"]
    assert not list(tmp_path.glob("*.tmp")), "the temp file was left behind"


def test_the_console_view_spends_nothing(monkeypatch, cfg, tmp_path):
    """A dashboard that probes on page load bills the founder for every refresh."""
    monkeypatch.setattr(hb, "heartbeat_path", lambda: tmp_path / "heartbeat.json")
    called = []
    monkeypatch.setattr("prospector.operator._build_operator",
                        lambda *a, **k: called.append(a) or _Answering("ALIVE"))
    hb.heartbeat_view(cfg)
    assert called == []


def test_the_console_preview_says_what_it_will_spend(cfg):
    """The preview is the informed half of an informed choice."""
    from prospector.ops.console_api import _act_providers_test

    free = _act_providers_test(cfg, {"tier": "groq"}, True)
    assert free["spends_money"] is False and free["tiers"] == ["groq"]

    metered = _act_providers_test(cfg, {"tier": "claude_cli"}, True)
    assert metered["spends_money"] is True and "claude_cli" in metered["metered"]


def test_the_console_preview_calls_no_provider(monkeypatch, cfg):
    from prospector.ops.console_api import _act_providers_test

    called = []
    monkeypatch.setattr("prospector.operator._build_operator",
                        lambda *a, **k: called.append(a) or _Answering("ALIVE"))
    _act_providers_test(cfg, {}, True)
    assert called == []


def test_an_unknown_tier_is_refused_by_name(cfg):
    from prospector.ops.console_api import _act_providers_test

    with pytest.raises(ValueError, match="unknown tier"):
        _act_providers_test(cfg, {"tier": "not_a_provider"}, True)


def test_a_declared_provider_gets_a_console_model_pin(cfg):
    """Founder: "seanless ability ti add nore", and "configurability via ops dashboad". The pin
    is the one knob a declaration exists to expose; before 2026-08-21 the hand-written chain
    table meant declared providers had none."""
    from prospector.ops.console_api import KNOBS_BY_KEY, refresh_declared_knobs

    refresh_declared_knobs()
    for name in cfg.providers:
        assert f"component_models.noncritical.{name}" in KNOBS_BY_KEY
