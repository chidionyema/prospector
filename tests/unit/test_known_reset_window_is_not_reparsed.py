"""A bench window the raiser KNOWS must never be re-derived from its own prose.

THE DEFECT THIS CLOSES, measured 2026-08-08. The usage-wall preflight in `claude_cli.py`
refuses to spawn the CLI into a wall another process already observed, and it renders the reset
for a human: "claude usage wall: capacity returns 2026-08-08 22:37:45 (14.0 min), observed by
otto-coordinator". `FallbackOperator._raw` then asked `limit_window_seconds` to read the window
back out of that sentence. It returns None on that shape, so the mark fell through to the
`DEFAULT_EXHAUSTION_S` hour — whose own docstring says it is for errors that "carry no
parseable reset time".

The cost was not the extra minutes in the abstract. `claude_cli` is the head of MOAT_PRIMARY,
so a 14-minute wall benched the only trusted brain for 60: `store/provider_health.json` held
`dead_for_s: 3600.0, dead_until 23:23:44` for a wall that lifted at 22:37:45. Every verdict in
that window fell to the emergency tail and came back `provisional`, and a provisional PASS is
held back from publication by `run.py:543` — so the shelf could not grow for 46 minutes it did
not owe. Worse, `probe_at` sits at +120s, so the half-open probe re-hit the still-live wall and
re-marked with a DOUBLED window.

The fix is structural, not a better regex: `ProviderExhaustedError.retry_after_s` carries the
number the preflight already holds, and both marking sites prefer it over any text parsing.
`test_the_rendered_wall_prose_is_still_unparseable` is the load-bearing one — it pins the exact
premise that makes the structural field necessary, so if someone later teaches the parser this
prose, the coupling is re-examined rather than silently duplicated.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from prospector.errors import ProviderExhaustedError, limit_window_seconds
from prospector.health import DEFAULT_EXHAUSTION_S, ProviderHealth
from prospector.operator import FallbackOperator, Operator

#: The message the preflight actually produced, verbatim from `store/provider_health.json`.
WALL_MESSAGE = ("claude cli not called: usage limit reached — claude usage wall: capacity "
                "returns 2026-08-08 22:37:45 (14.0 min), observed by otto-coordinator")

WALL_WINDOW_S = 840.0   # the 14 minutes the wall itself stated


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class _Op(Operator):
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    def _raw(self, system, user, temperature):
        self.calls += 1
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


def _bench_seconds(err: Exception, tmp_path: Path) -> float:
    """Drive the REAL marking path and return the window it chose.

    Deliberately not a re-implementation of the precedence expression: a test that recomputes
    `retry_after_s or limit_window_seconds(...) or default` would agree with the code by
    construction and could not fail if the code stopped consulting the field.
    """
    h = ProviderHealth(tmp_path / "h.json", clock=_Clock())
    fb = FallbackOperator([("a", _Op(err)), ("b", _Op('{"ok": true}'))], health=h)
    fb.complete_json("s", "u")
    assert h.dead_until("a") is not None, "the exhausted brain was never marked at all"
    return h.dead_until("a") - 1000.0


def test_the_rendered_wall_prose_is_still_unparseable(tmp_path):
    """The premise. If this ever starts returning a number, the structural field below is no
    longer load-bearing and the two mechanisms must be reconciled rather than both kept."""
    assert limit_window_seconds(WALL_MESSAGE) is None


def test_a_known_window_benches_for_exactly_that_window(tmp_path):
    """14 minutes stated, 14 minutes benched — not the hour the prose fell through to."""
    err = ProviderExhaustedError(WALL_MESSAGE, provider="a", retry_after_s=WALL_WINDOW_S)
    assert abs(_bench_seconds(err, tmp_path) - WALL_WINDOW_S) < 1.0


def test_without_the_known_window_the_same_message_costs_the_full_hour(tmp_path):
    """The regression itself, pinned. Same message, no `retry_after_s` — and the mark is the
    1h default. This is what the moat was actually served on 2026-08-08."""
    err = ProviderExhaustedError(WALL_MESSAGE, provider="a")
    assert abs(_bench_seconds(err, tmp_path) - DEFAULT_EXHAUSTION_S) < 1.0


def test_text_parsing_still_wins_when_the_raiser_knows_nothing(tmp_path):
    """No regression for adapters that only ever see a provider's own words: a parseable
    stated reset must still beat the class default."""
    err = ProviderExhaustedError("gemini cli exhausted: reset after 2h0m0s", provider="a")
    assert abs(_bench_seconds(err, tmp_path) - 7200.0) < 1.0


def test_a_known_window_beats_a_parseable_one_in_the_same_message(tmp_path):
    """Precedence, stated explicitly. The raiser's number outranks the text even when the text
    parses — the raiser holds the reset epoch, the text is a rendering of it."""
    err = ProviderExhaustedError("exhausted: reset after 2h0m0s", provider="a",
                                 retry_after_s=WALL_WINDOW_S)
    assert abs(_bench_seconds(err, tmp_path) - WALL_WINDOW_S) < 1.0
