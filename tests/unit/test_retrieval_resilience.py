"""Resilience of the free retrieval chain (searxng -> ddg).

Proves the two free fixes that re-open grounding when the self-hosted SearXNG's upstream
engines get blocked under daemon load (the 97.5%-unverifiable failure, 2026-06-25):

1. SearXNG must distinguish a BROKEN-empty response (HTTP 200 but every engine timed out)
   from a WORKING-but-empty one (engines ran, found nothing). The former raises so the
   FallbackSearchProvider consults ddg; the latter returns [] (real evidence of nothing).
2. The ddg provider must retry the transient primp/FakeUserAgent error its first call
   throws, so a flaky first attempt does not blind the only working free fallback.
"""
import json

import pytest

from prospector import retrieval as r
from prospector.errors import SearchProviderError


class _FakeResp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p


def _patch_urlopen(monkeypatch, payload):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeResp(payload))


def test_searxng_raises_when_all_engines_unresponsive(monkeypatch):
    """HTTP 200, zero results, engines all timed out -> infrastructure failure, not empty."""
    _patch_urlopen(monkeypatch, {"results": [],
                                 "unresponsive_engines": [["google", "timeout"],
                                                          ["bing", "timeout"]]})
    with pytest.raises(SearchProviderError):
        r.SearXNGSearcher(base_url="http://x").search("q")


def test_searxng_returns_empty_when_engines_ran_and_found_nothing(monkeypatch):
    """Engines responded (none unresponsive) but found nothing -> legit empty, return []."""
    _patch_urlopen(monkeypatch, {"results": [], "unresponsive_engines": []})
    assert r.SearXNGSearcher(base_url="http://x").search("q") == []


def test_searxng_broken_empty_fails_over_to_next_provider(monkeypatch):
    """End-to-end: a broken-empty SearXNG must let the chain reach the next provider."""
    _patch_urlopen(monkeypatch, {"results": [],
                                 "unresponsive_engines": [["brave", "timeout"]]})
    second_called = {"n": 0}

    class _Second(r.SearchProvider):
        def search(self, query, k=4, max_chars=1500):
            second_called["n"] += 1
            return [r.Source.make(url="https://e.com", text="real passage", query=query)]

    fb = r.FallbackSearchProvider([("searxng", r.SearXNGSearcher(base_url="http://x")),
                                   ("second", _Second())])
    out = fb.search("q")
    assert second_called["n"] == 1          # broken-empty searxng did NOT short-circuit
    assert len(out) == 1 and out[0].url == "https://e.com"


def test_ddg_retries_transient_error_then_succeeds(monkeypatch):
    """First ddgs call throws the transient primp/Client error; the retry succeeds."""
    calls = {"n": 0}

    class _FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, q, max_results=10):
            calls["n"] += 1
            if calls["n"] == 1:
                raise SystemError("<class 'builtins.Client'> returned a result with an "
                                  "exception set")
            return [{"href": "https://e.com", "body": "real ddg passage"}]

    import ddgs
    monkeypatch.setattr(ddgs, "DDGS", _FakeDDGS)
    monkeypatch.setattr(r, "_resolve", lambda u, timeout=None: u)

    out = r.DuckDuckGoSearchProvider().search("q")
    assert calls["n"] == 2                  # retried past the flaky first call
    assert len(out) == 1 and out[0].url == "https://e.com"


def test_ddg_gives_up_after_three_transient_errors(monkeypatch):
    """If every attempt fails, the error propagates so the breaker can count it."""
    class _AlwaysFails:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, q, max_results=10):
            raise SystemError("persistent client failure")

    import ddgs
    monkeypatch.setattr(ddgs, "DDGS", _AlwaysFails)
    with pytest.raises(Exception):
        r.DuckDuckGoSearchProvider().search("q")
