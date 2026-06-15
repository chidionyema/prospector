"""_resolve: a grounding URL is REAL iff its HOST answers — not iff a bot can fetch
the exact path.

Authoritative sources (Reuters/Nature/FT) bot-wall a HEAD with 401/403/404 for real
AND fake paths alike, so exact-path validation can only false-drop real evidence. Under
web=True the CLI grounds on live Google Search, so the fabrication signal is a made-up
HOST (no HTTP response), not a bad path. So: any HTTP response (even an error code) =>
KEEP; no response at all (DNS failure / refused / timeout) or a malformed URL => DROP.

Regression guard for the bug that blinded the whole moat: every gate returned
`unverifiable conf 0.00` because real bot-walled sources were dropped as 'fabricated'.
"""
from __future__ import annotations

import urllib.error

import prospector.retrieval as R


class _FakeResp:
    def __init__(self, url: str):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_keeps_bot_walled_host_that_returns_http_error(monkeypatch):
    """A server that answers 403/404 (bot-wall) has PROVEN the host is real -> keep."""
    def _raise_http_error(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(R.urllib.request, "urlopen", _raise_http_error)
    assert R._resolve("https://www.reuters.com/business/some-real-article") == \
        "https://www.reuters.com/business/some-real-article"


def test_keeps_host_that_404s_a_bot(monkeypatch):
    """Reuters/Nature 404 a bot HEAD even for real articles -> keep (host answered)."""
    def _raise_404(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found",
                                     hdrs=None, fp=None)

    monkeypatch.setattr(R.urllib.request, "urlopen", _raise_404)
    assert R._resolve("https://www.nature.com/articles/d41586-024-01582-7") is not None


def test_keeps_2xx(monkeypatch):
    monkeypatch.setattr(R.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp(req.full_url))
    assert R._resolve("https://en.wikipedia.org/wiki/Regulation") == \
        "https://en.wikipedia.org/wiki/Regulation"


def test_drops_dead_host_no_http_response(monkeypatch):
    """DNS failure / connection refused / timeout = no response -> fabricated/dead."""
    def _raise_urlerror(req, timeout=0):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(R.urllib.request, "urlopen", _raise_urlerror)
    assert R._resolve("https://nonexistent-domain-abc123zzz-fake.com/x") is None


def test_drops_malformed_or_non_http_url():
    assert R._resolve("not-a-url") is None
    assert R._resolve("ftp://example.com/file") is None
