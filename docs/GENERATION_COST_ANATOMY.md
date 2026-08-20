# What one generation tick actually spends

Measured 2026-08-21 by reading the code and the config on `integ-local`. Every number below has
a `file:line`. Nothing here is timed on a running box yet — that is the second angle and it is
named at the bottom as still owed.

Written because the founder asked how generation works today, after a tick was seen burning the
whole box while producing zero candidates.

## The knobs, and where they live

| what | value | where |
|---|---:|---|
| candidates asked for per tick | 50 | `config.yaml schedule.batch_size` |
| tick cadence | 7200s | `config.yaml schedule.interval_s` |
| candidates per signal | 50 | `config.yaml:1278` |
| max candidates per model call | 10 | `config.yaml:1233` |
| max generation waves | 6 | `config.yaml:1292` |
| generation calls in flight at once | 4 | `generate.py::_fan_out` |
| MiniMax requests in flight at once | 8 | `config.yaml:533 minimax_concurrency` |
| claude CLI subprocesses at once | 4 | `config.yaml:570 claude_concurrency` |

## The 429 ladder, exactly

`MiniMaxOperator` in `prospector/operator.py`:

- `_RETRY_429_MAX = 4` — `:685`
- `_RETRY_429_BASE_S = 5.0` — `:686`
- `for attempt in range(self._RETRY_429_MAX + 1)` — `:843`, so **5 attempts**
- `delay = self._RETRY_429_BASE_S * (2 ** attempt)` — `:868`, so **5s, 10s, 20s, 40s**

One model call that is rate-limited the whole way therefore costs **5 HTTP requests and 75
seconds of sleep** before it raises. The fifth attempt gets no sleep; it raises.

## The finding: the rest is shorter than the ladder

`prospector/health.py`:

- `_MIN_DEAD_S = 60.0` — `:46`
- `TRANSIENT_EXHAUSTION_S = _MIN_DEAD_S` — `:57`

A 429 is classified TRANSIENT (`errors.classify_exhaustion`), so the brain is benched for **60
seconds**. The ladder that produced the bench takes **75 seconds**. The bench expires 15 seconds
before the thing it is resting from would have finished on its own.

The effect: a rate-limited MiniMax is never actually rested. Each wave re-enters the full ladder,
so the tick pays 75 seconds per call for as long as the rate limit lasts, and the requests that
keep the rate limit alive are our own retries.

## What a fully rate-limited tick costs

Arithmetic from the numbers above, not from a stopwatch:

    ~5 waves (ceil(50 / 10), under max_rounds 6)
    ~5 generation calls per wave + 1 refine call   -> ~30 model calls
    x 5 HTTP requests per call                     -> ~150 doomed requests
    x 75s of sleep per call                        -> ~2,250 thread-seconds
    / 4 in flight (_fan_out cap)                   -> ~9-10 minutes of pure backoff
    candidates produced                            -> 0

## The four claude processes are the config, not a leak

`claude_cli.py:63` defaults `_MAX_CLI` to 2; `claude_cli.py:72 configure_concurrency` resizes it
from config, called at `run.py:392` and `operator.py:2075`. Config says
`claude_concurrency: 4` (`config.yaml:570`).

Four claude processes on the container is exactly the declared ceiling. HYPOTHESIS, not yet
proven: that `_sync_cli_concurrency` (`run.py:1608`) actually runs on the drain path in the
container. Until that is confirmed, "4 is the config" is one angle, not two.

## Still owed

1. **A stopwatch angle.** Every number above comes from reading source. Time a real tick under
   429 and compare. Two angles or it is not proven.
2. **Is the retry storm self-sustaining?** Our own 150 requests plausibly keep the rate limit
   alive. Plausible is not measured. Not filed as answered.
3. **Whether the ladder should be shorter than the bench, or the bench longer than the ladder.**
   One of the two numbers is wrong; which one is a decision, not a reading.

## Claude concurrency is pinned at 1, in code, and the console says so

Founder directive 2026-08-21, said twice and then a third time with the reason:
"i dont want consurreny onclaude code", "for the last fuckinng tine", "its too expencice".

It had to be said three times because the number lived in a DEFAULT, and a default drifts. It
went 2 -> 4 by 2026-08-15 through ordinary edits, each of which looked reasonable on its own.

**It is now a clamp, not a default.** `prospector/claude_cli.py:68` sets
`_CLAUDE_MAX_EVER = 1`, and `configure_concurrency` clamps DOWN to it
(`claude_cli.py:87`), so config.yaml, the plist and `PROSPECTOR_CLAUDE_CONCURRENCY` all get 1.
Raising the config key changes nothing. Pinned by
`tests/unit/test_claude_cli_is_never_concurrent.py` (5 tests, 3 mutations, all three kill).

**The Ops Console reads that ceiling rather than restating it.**
`prospector/ops/console_api.py::_claude_ceiling` imports `_CLAUDE_MAX_EVER`, so the knob's `max`
IS the code's ceiling and the two cannot drift. The knob carries a `pinned_reason`, which does
three things:

| where | what the operator sees |
|---|---|
| the config page | the knob is listed, shows its live value, and draws the existing "read only" pill |
| the top-of-page card | it is counted in "N knob(s) cannot be edited here", with the reason |
| a write attempt | refused before the value is even parsed, and the refusal quotes the reason |

The alternative — leave `"max": 16` — is worse than having no knob. The operator turns it down,
gets a receipt, and the engine ignores them. A control that does nothing is a lie the dashboard
tells on the engine's behalf.

`minimax_concurrency` is deliberately untouched (1..32). MiniMax leads the chain, so that is the
real throughput knob, and the pin is one key rather than a blanket. Pinned by
`tests/ops/test_the_console_cannot_offer_a_dead_concurrency_knob.py` (7 tests, 4 mutations, all
four kill).
