"""The provider said why it refused. We used to throw that away.

Measured 2026-08-18 while `prospector-engine` sat moat-blind: `provider_health.json` recorded

    "last_error": "MiniMax quota exhausted: HTTP Error 429: Too Many Requests"

The first half is our guess and the second is a generic status line, so nothing in the estate
could tell a plan window from a busy endpoint. The live endpoint, asked directly at concurrency
1, was saying something far more useful in the response BODY, which `urllib` discards unless the
exception is read as a file:

    {"type":"error","error":{"type":"rate_limit_error","message":"Token Plan usage limit
     reached: Upgrade your Token Plan or purchase Credits for more usage. (2056)",
     "http_code":"429"},"request_id":"06d39d81b21ad83755fc36146cd0e843"}

These tests pin that the body survives to the caller, and that once it does the shared classifier
grades it for what it is.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from prospector.errors import PERMANENT, TRANSIENT, classify_exhaustion, looks_exhausted
from prospector.health import _MAX_PROBE_GAP_S, DEFAULT_EXHAUSTION_S, ProviderHealth
from prospector.operator import _ERROR_BODY_CHARS, _http_error_with_body, _read_sse_bounded

MINIMAX_2056 = (
    '{"type":"error","error":{"type":"rate_limit_error","message":"Token Plan usage limit '
    'reached: Upgrade your Token Plan or purchase Credits for more usage. (2056)",'
    '"http_code":"429"},"request_id":"06d39d81b21ad83755fc36146cd0e843"}'
)


def _http_error(code: int, reason: str, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.minimax.io/v1/chat/completions", code, reason, {},
        io.BytesIO(body.encode("utf-8")))


def test_the_body_reaches_the_message():
    """Without this, every 429 reads identically no matter why it was refused."""
    err = _http_error_with_body(_http_error(429, "Too Many Requests", MINIMAX_2056))
    msg = str(err)
    assert "Token Plan usage limit reached" in msg
    assert "2056" in msg


def test_the_status_line_stays_first_and_verbatim():
    """`\\b429\\b` matching in the retry loop and in `errors` keys off the status line.

    A body that happens to carry another number must not be able to displace it.
    """
    err = _http_error_with_body(_http_error(429, "Too Many Requests", MINIMAX_2056))
    assert str(err).startswith("HTTP Error 429: Too Many Requests")


def test_the_body_turns_a_flapping_60s_bench_into_a_diagnosed_one():
    """The behaviour change this buys, stated as the assertion that proves it.

    Bare status line -> TRANSIENT: a 60s bench, strikes climbing, and a log line that says
    nothing. With the body -> PERMANENT, because "usage limit" is already in
    `_PERMANENT_MARKERS`. The classifier was never wrong; it was being shown a sentence with the
    evidence removed.
    """
    bare = "HTTP Error 429: Too Many Requests"
    assert classify_exhaustion(bare) == TRANSIENT

    withbody = str(_http_error_with_body(_http_error(429, "Too Many Requests", MINIMAX_2056)))
    assert "2056" in withbody, "the body has to reach the classifier at all"
    assert classify_exhaustion(withbody) == PERMANENT
    assert looks_exhausted(withbody)


def test_a_permanent_mark_is_still_re_probed_inside_ten_minutes(tmp_path):
    """PERMANENT must not mean "come back in an hour". That is the other half of the fix.

    Measured 2026-08-18: this MiniMax window reopened 38 minutes after it closed. The geometric
    backoff alone would next look at ~62 minutes (120 + 240 + 480 + 960 + 1920), so the engine
    would sit idle for 24 minutes after the provider was already answering. `_MAX_PROBE_GAP_S`
    caps the gap, and this pins that the cap is actually applied at every strike.
    """
    clock = {"t": 1000.0}
    h = ProviderHealth(path=tmp_path / "h.json", clock=lambda: clock["t"])

    gaps = []
    for _ in range(8):
        h.mark_exhausted("minimax", DEFAULT_EXHAUSTION_S, error=MINIMAX_2056)
        rec = json.loads((tmp_path / "h.json").read_text())["minimax"]
        gaps.append(rec["probe_at"] - rec["marked_at"])
        clock["t"] += 1.0  # the probe went out and came back dead; the mark is still live

    # The number that matters is the WORST WAIT, not the total: whenever the window reopens, the
    # engine looks again within one gap. Ten minutes, not sixty-two.
    assert max(gaps) <= _MAX_PROBE_GAP_S, f"a probe gap ran past the ceiling: {gaps}"
    assert gaps[:3] == [120.0, 240.0, 480.0], f"the early backoff must be untouched: {gaps}"
    # Without the ceiling the first hour holds 4 probes and the fifth lands at 62 minutes.
    within_hour, total = 0, 0.0
    for g in gaps:
        total += g
        if total <= 3600:
            within_hour += 1
    assert within_hour >= 7, f"only {within_hour} probes in the first hour: {gaps}"


def test_an_unreadable_body_still_leaves_a_usable_error():
    """A body we cannot read must not cost us the status line as well."""

    class Unreadable(urllib.error.HTTPError):
        def read(self, *a, **k):  # noqa: D102
            raise OSError("socket already closed")

    err = _http_error_with_body(Unreadable(
        "https://api.minimax.io/v1/chat/completions", 429, "Too Many Requests", {}, io.BytesIO(b"")))
    # NOT the bare status line, and NOT silence: an empty body and an unreadable one are
    # different facts, and this message is the only place either is ever seen.
    assert str(err) == "HTTP Error 429: Too Many Requests — <error body unreadable: OSError>"
    assert classify_exhaustion(str(err)) == TRANSIENT, "the status line still decides"


def test_a_long_body_is_bounded():
    """`provider_health.json` is state, not a log. A chatty upstream must not turn it into one."""
    err = _http_error_with_body(_http_error(500, "Internal Server Error", "x" * 5000))
    assert len(str(err)) < _ERROR_BODY_CHARS + 200


def test_the_stream_reader_raises_with_the_body(monkeypatch):
    """The seam that matters: this is the call the MiniMax adapter actually makes."""
    import urllib.request

    def _boom(req, timeout=None):
        raise _http_error(429, "Too Many Requests", MINIMAX_2056)

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(Exception) as caught:
        _read_sse_bounded(object(), stall_timeout=1.0, total_deadline=2.0)
    assert "Token Plan usage limit reached" in str(caught.value)
    assert str(caught.value).startswith("HTTP Error 429")
