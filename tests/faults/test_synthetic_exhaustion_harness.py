"""R5 — end-to-end synthetic-failure harness for the exhaustion seam.

`errors.classify_exhaustion` is well unit-tested. THE SEAM IS NOT: nothing drove a classified
error through `FallbackOperator` and asserted that the downstream consequences actually happen.
That gap is not theoretical — every 2026-08-06 incident in this area (a live brain benched for
an hour by a request id containing "429"; a monthly SPEND limit re-probed every 60s because the
classifier read the incidental 429 instead of the words; a moat-blind daemon whose most severe
state was log-only) was a defect in the CONSEQUENCE, not in the classifier.

So each test here forces a real exhaustion shape through the real chain and asserts the four
things that must follow:

  1. the health mark is written, with the window the shape earns
     (TRANSIENT -> health.TRANSIENT_EXHAUSTION_S = 60s; PERMANENT -> DEFAULT_EXHAUSTION_S = 1h;
      a STATED limit class refines it — 5-hour -> 18000s, weekly -> clamped to _MAX_DEAD_S);
  2. failover still happens — a live second brain serves, and is NOT marked;
  3. `_moat_blind_reason` goes blind only when EVERY trusted brain carries a live mark, and
     reads the mark without spending the half-open probe slot;
  4. the alert fires: `alerts_for_tick` emits a CRITICAL `moat_blind` spec and `emit_alert`
     durably records it.

Isolation: the provider-health file is redirected to tmp by the autouse `_isolate_provider_health`
fixture in tests/conftest.py, and every cfg double here carries `store_dir=tmp_path`, so the
alert path writes to tmp and never to store/scheduler/.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

import prospector.health as H
from prospector.errors import PERMANENT, TRANSIENT, ProviderExhaustedError, classify_exhaustion
from prospector.operator import MOAT_PRIMARY, FallbackOperator, Operator
from prospector.scheduler import run_scheduled as rs
from prospector.scheduler.alerts import CRITICAL, alerts_for_tick, emit_alert

#: (label, error text the adapter raises, expected class, expected dead-window seconds).
#:
#: The windows are the real contract, not round numbers: 60s for backpressure comes from
#: `health.TRANSIENT_EXHAUSTION_S` (= `_MIN_DEAD_S`), 3600s for a spent allowance from
#: `health.DEFAULT_EXHAUSTION_S`, and the last two from `errors.DEFAULT_LIMIT_WINDOW_S` —
#: with the weekly case CLAMPED by `health._MAX_DEAD_S` (24h), which is itself a rail worth
#: pinning: a mis-parsed window must never bench a brain for a month.
SHAPES = [
    ("http_429",        "HTTP 429 Too Many Requests",                              TRANSIENT, 60.0),
    ("http_503",        "upstream returned 503 Service Unavailable",               TRANSIENT, 60.0),
    ("http_529",        "api.anthropic.com responded 529",                         TRANSIENT, 60.0),
    ("overloaded_error",
     '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}', TRANSIENT, 60.0),
    ("http_402",        "HTTP 402 Payment Required",                               PERMANENT, 3600.0),
    ("credit_balance",
     "Your credit balance is too low to access the Anthropic API",                 PERMANENT, 3600.0),
    ("spend_limit",
     "You've hit your monthly spend limit · raise it at claude.ai/settings/usage",
     PERMANENT, 3600.0),
    ("usage_limit",     "Claude AI usage limit reached",                           PERMANENT, 3600.0),
    ("session_5h",      "5-hour limit reached; try again later",                   PERMANENT, 18000.0),
    ("weekly_limit",    "weekly limit reached for your plan",                      PERMANENT, 86400.0),
]
SHAPE_IDS = [s[0] for s in SHAPES]


class _Exhausted(Operator):
    """A brain that always reports the given exhaustion text, exactly as an adapter would."""

    def __init__(self, name: str, text: str):
        self.name = name
        self._text = text
        self.calls = 0

    def _raw(self, system: str, user: str, temperature: float) -> str:
        self.calls += 1
        raise ProviderExhaustedError(self._text, provider=self.name)


class _Alive(Operator):
    def __init__(self, name: str, reply: str = "ok"):
        self.name = name
        self.reply = reply
        self.calls = 0

    def _raw(self, system: str, user: str, temperature: float) -> str:
        self.calls += 1
        return self.reply


def _cfg(tmp_path, operators=("claude_cli", "claude")):
    return SimpleNamespace(store_dir=tmp_path, operator=list(operators))


def _health_entry(name: str) -> dict:
    """The raw persisted mark. Read straight off the (tmp) health file rather than through
    `is_dead`, which would CONSUME the half-open probe slot and change what we are measuring."""
    return json.loads(H.get_health()._path.read_text(encoding="utf-8"))[name]


# ---------------------------------------------------------------------------
# 1. Every classified shape writes a health mark with the window it earns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,text,kind,window_s", SHAPES, ids=SHAPE_IDS)
def test_shape_marks_health_with_the_expected_window(label, text, kind, window_s):
    assert classify_exhaustion(text) == kind, f"{label}: classifier drifted from the harness"

    brain = _Exhausted("claude_cli", text)
    chain = FallbackOperator([("claude_cli", brain)])

    t0 = time.time()
    with pytest.raises(ProviderExhaustedError):
        chain._raw("sys", "user", 0.0)

    assert brain.calls == 1
    entry = _health_entry("claude_cli")
    assert entry["dead_for_s"] == pytest.approx(window_s, abs=1.0), (
        f"{label}: expected a ~{window_s}s bench, got {entry['dead_for_s']}s")
    assert entry["dead_until"] == pytest.approx(t0 + window_s, abs=5.0)
    assert text[:40].lower() in entry["last_error"].lower(), (
        "the mark must carry WHY, or nine identical marks in 70 minutes are undiagnosable")


def test_a_shape_the_classifier_does_not_call_exhaustion_is_never_marked():
    """The dangerous half, stated as a test: a failure that is NOT ProviderExhaustedError must
    fail over WITHOUT writing an hour-long dead mark."""
    chain = FallbackOperator([("claude_cli", _RaisesValueError()), ("claude", _Alive("claude"))])
    assert chain._raw("sys", "user", 0.0) == "ok"
    assert H.get_health().dead_until("claude_cli") is None


class _RaisesValueError(Operator):
    name = "claude_cli"

    def _raw(self, system: str, user: str, temperature: float) -> str:
        raise ValueError("malformed JSON from the model")


# ---------------------------------------------------------------------------
# 2. Failover: one dead brain does not take the chain down
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,text,kind,window_s", SHAPES, ids=SHAPE_IDS)
def test_failover_serves_from_the_live_brain_and_marks_only_the_dead_one(label, text, kind,
                                                                        window_s):
    dead = _Exhausted("claude_cli", text)
    alive = _Alive("claude")
    chain = FallbackOperator([("claude_cli", dead), ("claude", alive)])

    assert chain._raw("sys", "user", 0.0) == "ok"
    assert chain.last_served() == "claude"
    assert chain.served_is_provisional() is False, "'claude' is a MOAT_PRIMARY brain"
    assert H.get_health().dead_until("claude_cli") is not None
    assert H.get_health().dead_until("claude") is None, "a live brain must never be benched"


def test_every_brain_exhausted_raises_so_the_caller_defers():
    chain = FallbackOperator([("claude_cli", _Exhausted("claude_cli", "HTTP 402 Payment Required")),
                              ("claude", _Exhausted("claude", "HTTP 429 Too Many Requests"))])
    with pytest.raises(ProviderExhaustedError) as ei:
        chain._raw("sys", "user", 0.0)
    assert "all brains exhausted" in str(ei.value)


# ---------------------------------------------------------------------------
# 3. The moat-blind consequence
# ---------------------------------------------------------------------------

def test_moat_is_not_blind_while_one_trusted_brain_is_alive(tmp_path):
    cfg = _cfg(tmp_path)
    chain = FallbackOperator([("claude_cli", _Exhausted("claude_cli", "HTTP 402 Payment Required")),
                              ("claude", _Alive("claude"))])
    assert chain._raw("sys", "user", 0.0) == "ok"
    assert rs._moat_blind_reason(cfg) == "", (
        "one live brain is a FLOOR, not a fair-weather switch — the tick must still run")


@pytest.mark.parametrize("label,text,kind,window_s", SHAPES, ids=SHAPE_IDS)
def test_moat_goes_blind_when_every_trusted_brain_is_marked(tmp_path, label, text, kind, window_s):
    cfg = _cfg(tmp_path)
    chain = FallbackOperator([("claude_cli", _Exhausted("claude_cli", text)),
                              ("claude", _Exhausted("claude", text))])
    with pytest.raises(ProviderExhaustedError):
        chain._raw("sys", "user", 0.0)

    reason = rs._moat_blind_reason(cfg)
    assert reason.startswith("moat blind:"), f"{label}: expected a blind moat, got {reason!r}"
    assert "claude_cli" in reason and "claude for" in reason


def test_moat_blind_check_does_not_spend_the_half_open_probe(tmp_path):
    """`_moat_blind_reason` must read `dead_until`, never `is_dead`. A bookkeeping check that
    consumed the probe slot would steal the one call whose job is to measure recovery."""
    cfg = _cfg(tmp_path)
    chain = FallbackOperator([("claude_cli", _Exhausted("claude_cli", "HTTP 402 Payment Required")),
                              ("claude", _Exhausted("claude", "HTTP 402 Payment Required"))])
    with pytest.raises(ProviderExhaustedError):
        chain._raw("sys", "user", 0.0)

    before = _health_entry("claude_cli").get("probes", 0)
    for _ in range(5):
        assert rs._moat_blind_reason(cfg).startswith("moat blind:")
    after = _health_entry("claude_cli").get("probes", 0)
    assert after == before, "the blind check consumed half-open probe slots"


def test_a_non_moat_brain_going_dead_never_blinds_the_moat(tmp_path):
    """The founder fence: a non-critical brain (minimax) is outside MOAT_PRIMARY, so its
    exhaustion must not be able to stop a tick."""
    assert "minimax" not in MOAT_PRIMARY
    cfg = _cfg(tmp_path, operators=("claude_cli", "minimax"))
    chain = FallbackOperator([("minimax", _Exhausted("minimax", "HTTP 402 Payment Required")),
                              ("claude_cli", _Alive("claude_cli"))])
    assert chain._raw("sys", "user", 0.0) == "ok"
    assert rs._moat_blind_reason(cfg) == ""


# ---------------------------------------------------------------------------
# 4. The alert consequence (R1's branch, driven from a real synthetic outage)
# ---------------------------------------------------------------------------

def _blind_tick(reason: str) -> dict:
    """The tick dict `run_scheduled.run_tick` writes on the moat-blind path (:812-823)."""
    return {"ts": "2026-08-07T00:00:00+00:00", "allowed": True, "moat_blind": True,
            "reason": reason, "batch_size": None}


def test_a_synthetic_total_outage_produces_a_critical_moat_blind_alert(tmp_path, monkeypatch):
    monkeypatch.setattr("prospector.scheduler.alerts._desktop_notify", lambda *a, **k: None)
    cfg = _cfg(tmp_path)

    chain = FallbackOperator([("claude_cli", _Exhausted("claude_cli", "HTTP 402 Payment Required")),
                              ("claude", _Exhausted("claude", "HTTP 402 Payment Required"))])
    with pytest.raises(ProviderExhaustedError):
        chain._raw("sys", "user", 0.0)

    reason = rs._moat_blind_reason(cfg)
    tick = _blind_tick(reason)

    specs = alerts_for_tick(tick)
    assert [s["key"] for s in specs] == ["moat_blind"]
    assert specs[0]["severity"] == CRITICAL

    record = emit_alert(cfg, **specs[0])
    assert record["key"] == "moat_blind"

    # Durably recorded — under tmp_path, never store/scheduler/.
    written = [json.loads(ln) for ln in
               (tmp_path / "scheduler" / "alerts.jsonl").read_text(encoding="utf-8").splitlines()
               if ln.strip()]
    assert [r["key"] for r in written] == ["moat_blind"]
    assert reason[:40] in written[0]["message"]
    assert (tmp_path / "scheduler" / "ALERT.txt").exists()


def test_a_blind_tick_is_unproductive_so_the_fast_retry_applies():
    """The other consequence of blindness: the 5m/10m/20m escalating retry, not the 2h cadence.
    A moat that heals in ninety seconds must be picked up in minutes."""
    assert rs._tick_unproductive(_blind_tick("moat blind: every trusted brain is marked dead")) \
        is True


def test_a_healthy_tick_raises_no_moat_blind_alert():
    assert alerts_for_tick({"ts": "t", "allowed": True,
                            "result": {"dossiers": 3, "passes": 1}}) == []
