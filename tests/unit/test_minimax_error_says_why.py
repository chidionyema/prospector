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
import urllib.error

import pytest

from prospector.errors import PERMANENT, TRANSIENT, classify_exhaustion, looks_exhausted
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


def test_a_plan_window_now_classifies_permanent_not_transient():
    """The behaviour change this buys, stated as the assertion that proves it.

    Bare status line -> TRANSIENT (60s bench, strikes climbing, flap). With the body -> PERMANENT,
    because "usage limit" is already in `_PERMANENT_MARKERS`. The classifier was never wrong; it
    was being shown a sentence with the evidence removed.
    """
    bare = "HTTP Error 429: Too Many Requests"
    assert classify_exhaustion(bare) == TRANSIENT

    withbody = str(_http_error_with_body(_http_error(429, "Too Many Requests", MINIMAX_2056)))
    assert classify_exhaustion(withbody) == PERMANENT
    assert looks_exhausted(withbody)


def test_an_unreadable_body_still_leaves_a_usable_error():
    """A body we cannot read must not cost us the status line as well."""

    class Unreadable(urllib.error.HTTPError):
        def read(self, *a, **k):  # noqa: D102
            raise OSError("socket already closed")

    err = _http_error_with_body(Unreadable(
        "https://api.minimax.io/v1/chat/completions", 429, "Too Many Requests", {}, io.BytesIO(b"")))
    assert str(err) == "HTTP Error 429: Too Many Requests"


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
