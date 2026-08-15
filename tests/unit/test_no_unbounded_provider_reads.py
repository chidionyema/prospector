"""No provider adapter may read a response body without a HARD total deadline.

`urllib.request.urlopen(req, timeout=N)` bounds each individual socket recv. It does NOT bound
`resp.read()`: a server that trickles the body resets the timer on every chunk, so the read can
block forever while every timeout in the stack looks satisfied.

WHAT THIS COST, MEASURED
------------------------
`store/scheduler/launchd.err.log`, parsed 2026-08-13:

    2026-08-11T08:05:25Z  INFO  LLM completion started: fallback(claude_cli+standardcompute+minimax)
      ... 165,997 seconds — 46.1 hours — with not one log line ...
    2026-08-13T06:12:02Z  ERROR Failed minimax_raw_call

Two days of a live storefront's supply spent inside one `read()`. The tick's 3-hour hard
deadline did not save it and neither did any provider timeout, because there was nothing to
fire — the socket was healthy, the body simply never ended.

`_urlopen_read_bounded` (`prospector/operator.py:277`) was written for exactly this in July 2026,
after a 34-minute MiniMax wedge. It was then applied to MiniMax **only**. Every other metered
adapter kept the bare call, so the chain still hung — on whichever member was left bare. A bound
that protects one provider in a fallback chain protects nothing.

That is why this test scans for the SHAPE rather than testing one adapter: the defect was never
that a particular provider was wrong, it was that the fix was applied per-provider instead of
per-call-site.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OPERATOR = REPO / "prospector" / "operator.py"

#: A bare urlopen used as a context manager or assigned — i.e. one whose body will be `.read()`
#: without a total deadline. The single legitimate use is INSIDE a bounded helper itself.
_BARE_URLOPEN = re.compile(r"urllib\.request\.urlopen\(")

#: The helpers are allowed to call urlopen — they are the things that add the deadline. There are
#: two because there are two transports: whole-body reads and the SSE stream MiniMax moved to on
#: 2026-08-14. The rule under test is "no urlopen outside a bounded helper", NOT "one blessed
#: function name" — a second transport is exactly how the original per-provider fix leaked.
_HELPERS = ("_urlopen_read_bounded", "_read_sse_bounded")


def _helper_body_lines(text: str, helper: str) -> set[int]:
    """Line numbers belonging to `helper`'s own definition."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(f"def {helper}(")), None)
    assert start is not None, f"{helper} has been renamed or removed — re-derive this test"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i] and not lines[i][0].isspace()), len(lines))
    return set(range(start + 1, end + 1))  # 1-indexed


def test_every_provider_read_is_bounded_by_a_total_deadline():
    text = OPERATOR.read_text()
    exempt = set().union(*(_helper_body_lines(text, h) for h in _HELPERS))

    offenders = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if lineno in exempt or line.lstrip().startswith("#"):
            continue
        if _BARE_URLOPEN.search(line):
            offenders.append(f"operator.py:{lineno}  {line.strip()}")

    assert not offenders, (
        f"bare urlopen in a provider adapter — `timeout=` is PER-RECV and cannot stop a trickled "
        f"body; a wedged read here hung the daemon for 46 hours on 2026-08-11. Use one of "
        f"{_HELPERS} (req, ..., total_deadline=...).\n  " + "\n  ".join(offenders))


@pytest.mark.parametrize("helper", _HELPERS)
def test_the_bounded_helper_still_enforces_a_deadline(helper):
    """Guard the guard: the scan above is worthless if a helper stopped bounding anything. Every
    exempt helper must earn its exemption, or exempting it is just a hole with a name."""
    text = OPERATOR.read_text()
    body_lines = _helper_body_lines(text, helper)
    body = "\n".join(line for n, line in enumerate(text.splitlines(), start=1) if n in body_lines)

    assert "total_deadline" in body, f"{helper} no longer takes a total deadline"
    assert "join(total_deadline)" in body, (
        f"{helper} no longer joins the reader thread on the deadline — it cannot time out")
    assert "resp.close()" in body, (
        f"{helper} no longer closes the socket on timeout — the wedged read leaks a thread + fd")


def test_the_adapters_that_hung_are_specifically_covered():
    """Name the call sites from the incident, so a future refactor cannot quietly drop them.

    StandardCompute is the one that was live in the chain during the 46-hour wedge
    (`config.yaml:53` operator, `:76` noncritical_operator). Its adapter was DELETED on
    2026-08-15 by founder directive, so it is off the list below: a name assertion against a
    class that no longer exists fails for the one reason this test does not care about. The
    invariant is unweakened -- the bounded-read count still covers every adapter that
    survives, and `_build_operator` raises on `kind == "standardcompute"`
    (`prospector/operator.py:1383`), so a stale config cannot resurrect an unbounded read.
    """
    text = OPERATOR.read_text()
    for adapter in ("DeepSeekOperator", "OllamaOperator", "OpenRouterOperator"):
        assert f"class {adapter}" in text, f"{adapter} vanished — re-derive this test"

    # Every adapter class must reach a bounded helper at least once. MiniMax moved to the SSE
    # helper on 2026-08-14, so count both — the invariant is "bounded", not "which helper".
    calls = sum(text.count(f"{h}(") for h in _HELPERS)
    assert calls >= 6, (
        f"expected every metered adapter to call one of {_HELPERS}; found "
        f"{calls} call(s) including the definitions")
