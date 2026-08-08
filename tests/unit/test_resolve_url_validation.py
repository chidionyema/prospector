"""_resolve: a grounding URL is REAL iff its HOST answers — not iff a bot can fetch
the exact path.

Authoritative sources (Reuters/Nature/FT) bot-wall a HEAD for real AND fake paths alike, so
exact-path validation can only false-drop real evidence. Under web=True the CLI grounds on
live Google Search, so the fabrication signal is a made-up HOST (no HTTP response), not a bad
path. So: an HTTP response => KEEP; no response at all (DNS failure / refused / timeout) or a
malformed URL => DROP.

Regression guard for the bug that blinded the whole moat: every gate returned
`unverifiable conf 0.00` because real bot-walled sources were dropped as 'fabricated'.

AMENDED 2026-08-08 — the wall and the grave are not the same status. This file used to assert
that a 404 is kept too, on the stated premise that "Reuters/Nature 404 a bot HEAD even for
real articles". Measured with the browser UA `_resolve` actually sends, that premise does not
hold: nature.com answers 303 for a real article AND for a fabricated one, reuters.com answers
401, and the only 404 came from a deliberately fabricated FT path. Meanwhile keeping 404/410
cost the shelf directly — a dead citation rode to publish, where `pack_linter._DEAD_STATUSES`
failed the whole pack after the money rail had been minted (see
tests/unit/test_retrieval_drops_dead_urls.py for the full incident).

So 404/410 now DROP, confirmed by a second GET, and every bot-wall status still KEEPS. The
guard this file exists for is unchanged and is asserted below on the statuses the walls
actually use. Measured blast radius over the 68 distinct cited URLs in
`store/lint_url_cache.json`: 3 dropped (4%), all three confirmed dead; the 17 bot-walled 403s
(25%) are untouched.
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

    def read(self, _n=None):
        # `_confirm_dead` reads a byte to prove the GET really served. Without this the
        # HEAD-404/GET-200 test would pass through _confirm_dead's broad `except` instead
        # of through the served-GET branch — green for the wrong reason.
        return b""


def test_keeps_bot_walled_host_that_returns_http_error(monkeypatch):
    """A server that answers 403/404 (bot-wall) has PROVEN the host is real -> keep."""
    def _raise_http_error(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(R.urllib.request, "urlopen", _raise_http_error)
    assert R._resolve("https://www.reuters.com/business/some-real-article") == \
        "https://www.reuters.com/business/some-real-article"


def test_keeps_a_host_that_404s_a_HEAD_but_serves_a_GET(monkeypatch):
    """The false-drop protection that makes dropping 404s safe at all.

    Some origins 404 a HEAD they would have served. `_resolve` confirms with a GET before
    dropping, so a real article behind a HEAD-hostile origin is still kept — which is the
    property the old `test_keeps_host_that_404s_a_bot` was reaching for.
    """
    def _head_404_get_200(req, timeout=0):
        if req.get_method() == "HEAD":
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", hdrs=None, fp=None)
        return _FakeResp(req.full_url)

    monkeypatch.setattr(R.urllib.request, "urlopen", _head_404_get_200)
    assert R._resolve("https://www.nature.com/articles/d41586-024-01582-7") is not None


def test_drops_a_page_that_is_gone_to_a_HEAD_and_to_a_GET(monkeypatch):
    """404/410 confirmed twice is a grave, not a wall. Keeping these stranded the shelf."""
    def _gone(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 410, "Gone", hdrs=None, fp=None)

    monkeypatch.setattr(R.urllib.request, "urlopen", _gone)
    assert R._resolve("https://assets.publishing.service.gov.uk/media/deleted.pdf") is None


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
