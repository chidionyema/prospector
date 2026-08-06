"""The moat must fail SOFT and heal ITSELF — regression guards for the 2026-08-06 outage.

What happened, from the live daemon log and store/provider_health.json:

    08:25, 09:06, 09:07:07 x2, 09:07:11 x2, 09:08, 09:09, 09:36
        Provider 'claude_cli' marked exhausted for ~3600s (persisted)

Nine one-hour blackouts in seventy minutes, on a brain that answered a direct
`env -u ANTHROPIC_API_KEY claude -p` probe with `OK` while the marks were live. Each failure
took ~3s (09:06:21 -> 09:06:24) — backpressure, not a spent quota. Three separate defects
stacked to turn that into a production outage, and each one gets a test here:

  1. `looks_exhausted` matched "429" and "402" as BARE SUBSTRINGS, so any request id or byte
     count containing those digits classified as exhaustion.
  2. Every exhaustion, transient or permanent, got the same DEFAULT_EXHAUSTION_S = 3600s.
  3. A dead mark was never re-probed inside its window — `_raw` skips a dead brain outright —
     so recovery could not be noticed before the hour was up.

The consequence was not a crash. It was 15/15 verdicts ruled by the emergency tail and stamped
`provisional`, each owing a full re-vet, while a `vet --resume` drain competed for the same CLI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from prospector import errors, health


# ---------------------------------------------------------------- classification

@pytest.mark.parametrize("text", [
    "connection reset after 4291 bytes",
    "req_id=a429f0 timeout",
    "Error: 4290 tokens in prompt",
    "billing address invalid",
    "trace 1402938 aborted",
])
def test_digits_in_ids_and_counts_are_not_exhaustion(text):
    """Each of these returned True before the fix and bought an hour of moat blindness."""
    assert errors.classify_exhaustion(text) == errors.NOT_EXHAUSTION
    assert not errors.looks_exhausted(text)


@pytest.mark.parametrize("text,kind", [
    ("HTTP 429 Too Many Requests", errors.TRANSIENT),
    ("Error: rate_limit_error", errors.TRANSIENT),
    ("overloaded_error: server busy", errors.TRANSIENT),
    ("HTTP Error 402: Payment Required", errors.PERMANENT),
    ("Your credit balance is too low", errors.PERMANENT),
    ("ActionRequiredError: You've hit your usage limit", errors.PERMANENT),
    ("billing hard limit reached for this plan", errors.PERMANENT),
])
def test_real_signals_still_classify(text, kind):
    assert errors.classify_exhaustion(text) == kind
    assert errors.looks_exhausted(text), "both shapes must still fail over"


def test_permanent_wins_when_both_shapes_are_present():
    """A spent account being throttled on the way out must get the long window, not the floor."""
    both = "HTTP 429 too many requests; your credit balance is too low"
    assert errors.classify_exhaustion(both) == errors.PERMANENT


def test_401_is_never_exhaustion():
    """A bad credential must fail loudly on every call, not hide behind an hour of failover."""
    assert errors.classify_exhaustion("HTTP 401 Unauthorized") == errors.NOT_EXHAUSTION


# ---------------------------------------------------------------- dead-window length

def _health_at(tmp_path, clock):
    return health.ProviderHealth(path=tmp_path / "h.json", clock=clock)


def test_backpressure_gets_the_floor_and_a_spent_account_gets_the_hour(tmp_path):
    """The distinction that turns a slow-down into a 60s pause instead of a 60m outage."""
    now = [1000.0]
    h = _health_at(tmp_path, lambda: now[0])

    h.mark_exhausted("brainA", health.TRANSIENT_EXHAUSTION_S, error="HTTP 429")
    h.mark_exhausted("brainB", health.DEFAULT_EXHAUSTION_S, error="payment required")

    assert h.dead_until("brainA") == pytest.approx(now[0] + 60.0)
    assert h.dead_until("brainB") == pytest.approx(now[0] + 3600.0)

    now[0] += 61.0
    assert h.dead_until("brainA") is None, "a 429 must not outlive a minute"
    assert h.dead_until("brainB") is not None


def test_mark_persists_the_error_text(tmp_path):
    """The log showed nine marks and not one said why: the text lived only in `extra`, which
    this project's formatter drops. Persisting it is what makes the next incident diagnosable."""
    h = _health_at(tmp_path, lambda: 1000.0)
    h.mark_exhausted("brainA", 60.0, error="ActionRequiredError: You've hit your usage limit")
    entry = json.loads((tmp_path / "h.json").read_text())["brainA"]
    assert "usage limit" in entry["last_error"]


# ---------------------------------------------------------------- half-open probe

def test_dead_brain_is_reprobed_long_before_its_window_expires(tmp_path):
    """The heart of the fix: an hour-long mark must not mean an hour of not looking."""
    now = [1000.0]
    h = _health_at(tmp_path, lambda: now[0])
    h.mark_exhausted("brainA", 3600.0, error="payment required")

    assert h.is_dead("brainA"), "skipped immediately after the mark"

    now[0] += health._PROBE_AFTER_S + 1
    assert not h.is_dead("brainA"), "must be let through to re-probe after ~120s, not 3600s"
    # And the raw mark is untouched — reporting still says 'dead'.
    assert h.dead_until("brainA") is not None


def test_only_one_caller_takes_the_probe(tmp_path):
    """Otherwise every worker stampedes a struggling brain the moment the probe window opens."""
    now = [1000.0]
    h = _health_at(tmp_path, lambda: now[0])
    h.mark_exhausted("brainA", 3600.0, error="payment required")
    now[0] += health._PROBE_AFTER_S + 1

    verdicts = [h.is_dead("brainA") for _ in range(8)]
    assert verdicts.count(False) == 1, f"exactly one probe should be let through, got {verdicts}"


def test_the_probe_claim_is_shared_across_processes(tmp_path):
    """Two ProviderHealth instances on one file stand in for the daemon and a `vet --resume`
    drain — the two processes that were actually competing on 2026-08-06."""
    now = [1000.0]
    daemon = _health_at(tmp_path, lambda: now[0])
    drain = _health_at(tmp_path, lambda: now[0])
    daemon.mark_exhausted("brainA", 3600.0, error="payment required")
    now[0] += health._PROBE_AFTER_S + 1

    assert not daemon.is_dead("brainA"), "daemon takes the probe"
    assert drain.is_dead("brainA"), "drain must NOT also probe — the claim is persisted"


def test_repeat_failures_back_off_geometrically(tmp_path):
    """A genuinely dead brain must not be probed every 120s forever."""
    now = [1000.0]
    h = _health_at(tmp_path, lambda: now[0])
    h.mark_exhausted("brainA", 3600.0, error="payment required")
    assert json.loads((tmp_path / "h.json").read_text())["brainA"]["strikes"] == 1

    # The probe went out and came back dead: a repeat mark inside a live window.
    now[0] += health._PROBE_AFTER_S + 1
    h.is_dead("brainA")                       # claims the probe
    h.mark_exhausted("brainA", 3600.0, error="payment required")
    entry = json.loads((tmp_path / "h.json").read_text())["brainA"]
    assert entry["strikes"] == 2
    assert entry["probe_at"] - now[0] == pytest.approx(health._PROBE_AFTER_S * 2)


def test_success_clears_the_mark_and_the_strikes(tmp_path):
    """`clear()` is what actually ends an outage — one real success beats any window."""
    now = [1000.0]
    h = _health_at(tmp_path, lambda: now[0])
    h.mark_exhausted("brainA", 3600.0, error="payment required")
    now[0] += health._PROBE_AFTER_S + 1
    h.is_dead("brainA")
    h.mark_exhausted("brainA", 3600.0, error="payment required")   # strike 2

    h.clear("brainA")
    assert h.dead_until("brainA") is None
    h.mark_exhausted("brainA", 3600.0, error="payment required")
    assert json.loads((tmp_path / "h.json").read_text())["brainA"]["strikes"] == 1


# ---------------------------------------------------------------- cursor_cli is gone

def test_cursor_cli_is_not_a_moat_brain():
    from prospector.operator import MOAT_PRIMARY, is_provisional_provider
    assert "cursor_cli" not in MOAT_PRIMARY
    assert is_provisional_provider("cursor_cli")


def test_cursor_cli_adapter_is_deleted():
    with pytest.raises(ModuleNotFoundError):
        __import__("prospector.cursor_cli")


def test_building_cursor_cli_fails_loudly_not_silently():
    """A stale config or plist must break at startup, not quietly build a shorter chain."""
    from prospector.config import load_config
    from prospector.operator import _build_operator
    with pytest.raises(ValueError, match="removed"):
        _build_operator("cursor_cli", load_config(), fast=False)


def test_no_live_tooling_still_sets_the_cursor_concurrency_knob():
    """The adapter was deleted, but the ENV KNOB outlived it in three places.

    Found 2026-08-06 while sweeping for the last cursor_cli traces: `PROSPECTOR_CURSOR_CONCURRENCY`
    was still exported by `tools/queue_yield_batch.sh` and conditionally re-exported by
    `tools/backfill_missing_listings.sh`, and was still in the control-center launchd plist's
    EnvironmentVariables — which is why a process started on 31 Jul was STILL carrying it six
    days later. Nothing reads it now, so it is inert; the reason to assert it gone is that a
    dead knob in a live config surface reads as a working control to the next person, and this
    one had already survived one removal pass by hiding in shell and plist rather than Python.

    Comments naming it are fine and deliberately allowed — they carry the reason it went.
    """
    import re
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in list((root / "tools").rglob("*.sh")) + list((root / "deploy").rglob("*.plist")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("<!--"):
                continue
            if re.search(r"\bPROSPECTOR_CURSOR_CONCURRENCY\b", line):
                offenders.append(f"{path.relative_to(root)}:{n}: {stripped}")
    assert not offenders, (
        "the cursor_cli concurrency knob is still set on a live config surface:\n  "
        + "\n  ".join(offenders))


def test_configured_verdict_chain_is_trusted_only():
    """Publish-on-PASS depends on this: no brain outside MOAT_PRIMARY may rule a verdict."""
    from prospector.config import load_config
    from prospector.operator import MOAT_PRIMARY
    ops = load_config().operator
    ops = [ops] if isinstance(ops, str) else list(ops)
    assert ops, "verdict chain must not be empty"
    untrusted = [o for o in ops if o not in MOAT_PRIMARY]
    assert not untrusted, (
        f"{untrusted} would rule verdicts provisionally instead of deferring; "
        "a provisional pass costs a verdict run now AND a re-vet later for the same answer")
