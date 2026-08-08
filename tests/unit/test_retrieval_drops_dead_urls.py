"""`_resolve` must tell "this page is GONE" apart from "you are being walled".

THE DEFECT THIS CLOSES. `_resolve` kept any URL that produced an HTTP response at all,
because authoritative sites bot-wall a HEAD with 401/403 for real and fake paths alike, and
dropping those would discard real evidence. That reasoning is correct for a wall and wrong for
a grave: nothing answers a bot challenge with `410 Gone`, and a 404 that survives a real
browser UA is a page that is genuinely missing.

The cost of conflating them was measured on 2026-08-08. Three of the four packs that passed
every gate that day carried exactly ONE dead citation each, out of twenty URLs — a removed
law-firm bio (404), a deleted WordPress page (404) and a retired gov.uk asset (410). The dead
URL rode from retrieval all the way to publish, where `pack_linter._DEAD_STATUSES` — the same
two statuses — failed the entire pack after the money rail had already been minted. The shelf
could not grow while a single dead link anywhere in a pack was fatal at the last step.

Dropping it at retrieval costs one source out of many, and the check either stands on its
remaining sources or honestly goes unverifiable and lets the kill gates rule.
"""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from prospector.retrieval import _resolve

URL = "https://example.test/some/page"


class _Resp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, url: str):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, _n=None):
        return b""


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, f"HTTP {code}", {}, None)


def _urlopen_stub(head: int | None, get: int | None):
    """Stub urlopen: `head`/`get` are status codes, or None meaning 'served fine'."""

    def _stub(req, timeout=None):
        code = head if req.get_method() == "HEAD" else get
        if code is None:
            return _Resp(URL)
        raise _http_error(code)

    return _stub


@pytest.mark.parametrize("status", [404, 410])
def test_a_dead_page_confirmed_by_a_get_is_dropped(status):
    """404 and 410 are the two statuses that mean gone. Kept identical to
    pack_linter._DEAD_STATUSES so the retrieval drop and the publish lint cannot disagree."""
    with patch("urllib.request.urlopen", _urlopen_stub(head=status, get=status)):
        assert _resolve(URL) is None


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_a_bot_wall_or_outage_is_kept(status):
    """The original rule, still load-bearing: en.wikipedia.org answers a bare HEAD with 403
    and a browser GET with 200. Dropping these would discard real evidence."""
    with patch("urllib.request.urlopen", _urlopen_stub(head=status, get=status)):
        assert _resolve(URL) == URL


def test_a_head_only_404_is_kept_when_a_get_would_have_served_it():
    """Some origins 404 a HEAD they would serve for a GET. The confirming GET is what makes
    dropping safe; without it this fix would trade a stranded shelf for lost evidence."""
    with patch("urllib.request.urlopen", _urlopen_stub(head=404, get=None)):
        assert _resolve(URL) == URL


def test_a_get_that_cannot_reach_the_host_is_not_a_death_certificate():
    """An exception is never evidence — the engine-wide rule. If the confirming GET fails to
    produce a verdict, keep the source rather than inventing one."""

    def _stub(req, timeout=None):
        if req.get_method() == "HEAD":
            raise _http_error(404)
        raise OSError("connection reset")

    with patch("urllib.request.urlopen", _stub):
        assert _resolve(URL) == URL


def test_a_host_that_never_responds_is_still_dropped():
    """The pre-existing behaviour, unchanged: no HTTP response at all means the host is
    fabricated or dead."""

    def _stub(req, timeout=None):
        raise OSError("nxdomain")

    with patch("urllib.request.urlopen", _stub):
        assert _resolve(URL) is None


def test_a_live_page_resolves_to_its_canonical_url():
    with patch("urllib.request.urlopen", _urlopen_stub(head=None, get=None)):
        assert _resolve(URL) == URL
