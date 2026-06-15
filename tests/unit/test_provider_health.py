"""Persisted, time-aware provider health (L3): a brain/grounding provider learned to
be out of quota stays skipped — within the run AND across process restarts — until its
parsed reset window elapses, then is retried. This is what stops every fresh run (and
every parallel call) from re-paying a dead provider's full timeout to rediscover it."""
from __future__ import annotations

from prospector.errors import ProviderExhaustedError, parse_reset_seconds
from prospector.health import DEFAULT_EXHAUSTION_S, ProviderHealth
from prospector.operator import FallbackOperator, Operator
from prospector.retrieval import FallbackSearchProvider, SearchProvider
from prospector.models import Source


# --- reset-time parsing -----------------------------------------------------
def test_parse_retry_delay_ms():
    s = "reason: 'QUOTA_EXHAUSTED' }, retryDelayMs: 24846193.66814 }"
    secs = parse_reset_seconds(s)
    assert secs is not None and abs(secs - 24846.19) < 1.0     # ms -> ~6.9h


def test_parse_human_hms():
    secs = parse_reset_seconds("You have exhausted your capacity. Your quota will reset after 6h54m27s.")
    assert secs == 6 * 3600 + 54 * 60 + 27


def test_parse_returns_none_when_absent():
    assert parse_reset_seconds("connection reset by peer") is None
    assert parse_reset_seconds("") is None


# --- ProviderHealth store ---------------------------------------------------
class _Clock:
    def __init__(self, t=1000.0): self.t = t
    def __call__(self): return self.t


def test_mark_then_dead_until_expiry(tmp_path):
    clk = _Clock()
    h = ProviderHealth(tmp_path / "h.json", clock=clk)
    assert not h.is_dead("gemini_cli")
    h.mark_exhausted("gemini_cli", 600.0)
    assert h.is_dead("gemini_cli")
    clk.t += 599.0
    assert h.is_dead("gemini_cli")     # still within window
    clk.t += 2.0
    assert not h.is_dead("gemini_cli")  # window elapsed -> retried


def test_persists_across_instances(tmp_path):
    """A NEW process (new instance, same file) sees the dead mark — the cross-run win."""
    clk = _Clock()
    p = tmp_path / "h.json"
    ProviderHealth(p, clock=clk).mark_exhausted("gemini_cli", 3600.0)
    fresh = ProviderHealth(p, clock=_Clock(clk.t + 10))   # "next run", 10s later
    assert fresh.is_dead("gemini_cli")


def test_clear_drops_mark(tmp_path):
    h = ProviderHealth(tmp_path / "h.json", clock=_Clock())
    h.mark_exhausted("gemini_cli", 3600.0)
    h.clear("gemini_cli")
    assert not h.is_dead("gemini_cli")


def test_window_is_clamped(tmp_path):
    clk = _Clock()
    h = ProviderHealth(tmp_path / "h.json", clock=clk)
    h.mark_exhausted("x", 9_999_999.0)        # absurd -> clamped to <= 24h
    assert h.dead_until("x") - clk.t <= 24 * 3600 + 1


def test_corrupt_file_is_ignored(tmp_path):
    p = tmp_path / "h.json"
    p.write_text("{ not json")
    h = ProviderHealth(p, clock=_Clock())
    assert not h.is_dead("anything")          # never crashes -> no knowledge


# --- failover chains consult & record persisted health ----------------------
class _Op(Operator):
    def __init__(self, name, behaviour):
        self.name = name; self.behaviour = behaviour; self.calls = 0

    def _raw(self, system, user, temperature):
        self.calls += 1
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


def test_brain_skips_provider_marked_dead_by_health(tmp_path):
    """A brain known-exhausted from a PRIOR run (persisted) is never called this run."""
    h = ProviderHealth(tmp_path / "h.json", clock=_Clock())
    h.mark_exhausted("a", 3600.0)
    dead = _Op("a", '{"unreached": true}')   # would succeed, but must be skipped
    live = _Op("b", '{"ok": true}')
    fb = FallbackOperator([("a", dead), ("b", live)], health=h)
    assert fb.complete_json("s", "u") == {"ok": True}
    assert dead.calls == 0 and live.calls == 1   # 'a' skipped from call #1, no probe


def test_brain_exhaustion_is_recorded_to_health(tmp_path):
    """On a fresh exhaustion the brain's reset window is parsed and persisted, so the
    NEXT chain built on the same file skips it without re-probing."""
    h = ProviderHealth(tmp_path / "h.json", clock=_Clock())
    err = ProviderExhaustedError("gemini cli exhausted: reset after 2h0m0s", provider="a")
    fb = FallbackOperator([("a", _Op("a", err)), ("b", _Op("b", '{"ok": true}'))], health=h)
    fb.complete_json("s", "u")
    assert h.is_dead("a") and abs(h.dead_until("a") - (1000.0 + 7200.0)) < 1.0


class _Search(SearchProvider):
    def __init__(self, behaviour):
        self.behaviour = behaviour; self.calls = 0

    def search(self, query, k=4, max_chars=1500):
        self.calls += 1
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


def test_grounding_skips_provider_marked_dead_by_health(tmp_path):
    h = ProviderHealth(tmp_path / "h.json", clock=_Clock())
    h.mark_exhausted("a", 3600.0)
    dead = _Search([Source.make(url="https://x.com", text="t", query="q")])
    live = _Search([Source.make(url="https://y.com", text="t", query="q")])
    fb = FallbackSearchProvider([("a", dead), ("b", live)], health=h)
    out = fb.search("q")
    assert dead.calls == 0 and live.calls == 1 and out[0].url == "https://y.com"


def test_grounding_success_clears_stale_mark(tmp_path):
    """A provider that recovers (its window passed, now serves) gets its mark cleared."""
    clk = _Clock()
    h = ProviderHealth(tmp_path / "h.json", clock=clk)
    h.mark_exhausted("a", 100.0)
    clk.t += 101.0                                  # window elapsed -> a is retriable
    live = _Search([Source.make(url="https://x.com", text="t", query="q")])
    fb = FallbackSearchProvider([("a", live)], health=h)
    fb.search("q")
    assert not h.is_dead("a")                        # stale mark cleared on success
