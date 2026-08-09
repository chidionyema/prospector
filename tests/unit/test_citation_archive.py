"""Citation archiving: the second pointer, and the rules that keep it from costing a publish.

A pack is generated once and sold indefinitely, so its citations rot after the sale (measured
2026-08-09: 12 of 14 dead citations blocking packs were genuinely 404 on GET). The passage
text was already durable; what was missing was a durable POINTER. These tests pin the three
properties that decide whether that is an asset or a liability: it is rendered to the buyer,
it never blocks a publish, and it does not hammer Save Page Now.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from prospector import archive
from prospector.models import Source


class _Resp:
    def __init__(self, status=200, payload=None, headers=None, url=""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.url = url

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _avail(available=True, status="200", url="http://web.archive.org/web/20240101/https://x.test/a"):
    return _Resp(payload={"archived_snapshots": {"closest": {
        "available": available, "status": status, "url": url}}})


# ---------------------------------------------------------------------------
# Availability lookup
# ---------------------------------------------------------------------------

def test_existing_snapshot_returns_https_memento():
    """The API answers in http:// for historical reasons and the storefront is https-only;
    a mixed-content link is one the buyer's browser may simply refuse to open."""
    with patch.object(archive.requests, "get", return_value=_avail()):
        assert archive.existing_snapshot("https://x.test/a") == \
            "https://web.archive.org/web/20240101/https://x.test/a"


def test_snapshot_of_an_error_page_is_not_evidence():
    """A capture whose own status was 404 is worse than no memento: it puts a snapshot of an
    error page next to the quote it is supposed to corroborate."""
    with patch.object(archive.requests, "get", return_value=_avail(status="404")):
        assert archive.existing_snapshot("https://x.test/a") is None


def test_unavailable_snapshot_is_none():
    with patch.object(archive.requests, "get", return_value=_avail(available=False)):
        assert archive.existing_snapshot("https://x.test/a") is None


def test_the_trailing_slash_form_is_tried_too():
    """Measured live 2026-08-09: the availability API returns a capture for
    `https://example.com` and nothing for `https://example.com/`, on a site archived thousands
    of times. Asking one way only turns "not asked correctly" into "no snapshot"."""
    asked = []

    def fake_get(url, params=None, **kw):
        asked.append(params["url"])
        if params["url"].endswith("/"):
            return _Resp(payload={"archived_snapshots": {}})       # the API's blind spot
        return _avail()

    with patch.object(archive.requests, "get", side_effect=fake_get):
        assert archive.existing_snapshot("https://x.test/a/") is not None
    assert asked == ["https://x.test/a/", "https://x.test/a"]


def test_the_retry_never_degrades_to_a_bare_host():
    """`https://x.test/` minus its slash is `https://x.test`, a different page on plenty of
    sites and a scheme fragment on none — but stripping further would be nonsense."""
    asked = []

    def fake_get(url, params=None, **kw):
        asked.append(params["url"])
        return _Resp(payload={"archived_snapshots": {}})

    with patch.object(archive.requests, "get", side_effect=fake_get):
        assert archive.existing_snapshot("https://x.test/") is None
    assert asked == ["https://x.test/"], f"asked for a degraded form: {asked}"


def test_lookup_failure_is_none_never_raises():
    with patch.object(archive.requests, "get",
                      side_effect=archive.requests.RequestException("boom")):
        assert archive.existing_snapshot("https://x.test/a") is None
    with patch.object(archive.requests, "get", return_value=_Resp(payload=None)):
        assert archive.existing_snapshot("https://x.test/a") is None


# ---------------------------------------------------------------------------
# A 429 from the availability API is not an answer (2026-08-09)
# ---------------------------------------------------------------------------
# The module used to exempt lookups from the rate-limit rule, on the premise that they hit "a
# different, unmetered endpoint". Live `curl` returned HTTP 429 from that endpoint during a
# backfill sweep, and because every non-200 collapsed to None, the throttling was recorded as
# a property of the URL: 0 of 18 dead citations reported unrecoverable, with bbc.co.uk and
# gov.uk among the supposedly-unarchived.

def test_a_429_is_reported_as_rate_limited_not_as_no_snapshot():
    with patch.object(archive.requests, "get", return_value=_Resp(status=429)):
        memento, limited = archive._snapshot("https://x.test/a", 5.0)
    assert memento is None
    assert limited is True, "a 429 must be distinguishable from 'never archived'"


def test_a_rate_limited_lookup_does_not_retry_the_alt_form():
    """Asking a second time while being told to stop is what earns a longer block."""
    asked = []

    def fake_get(url, params=None, **kw):
        asked.append(params["url"])
        return _Resp(status=429)

    with patch.object(archive.requests, "get", side_effect=fake_get):
        archive._snapshot("https://x.test/a", 5.0)
    assert asked == ["https://x.test/a"], f"retried while rate-limited: {asked}"


def test_a_rate_limited_url_is_never_cached_as_missing(tmp_path):
    """The bug this pins: caching `{"memento": None}` for a URL the archive never answered
    about pins our own throttling onto it for _FAILURE_TTL_S, and every later run reads it
    back as 'already checked, not archived' without ever asking again."""
    cache = tmp_path / "c.json"
    with patch.object(archive, "_snapshot", return_value=(None, True)), \
         patch.object(archive, "save_snapshot") as save:
        out = archive.archive_urls(["https://x.test/a"], cache_path=cache, save_new=True)
    assert out == {}
    assert save.call_count == 0, "must not spend the expensive save while rate-limited"
    assert not cache.exists() or json.loads(cache.read_text()) == {}, \
        "a URL the archive declined to answer about was cached as unarchived"


def test_one_429_stops_lookups_for_the_whole_batch():
    calls = []

    def fake_snapshot(url, timeout_s):
        calls.append(url)
        return None, True

    with patch.object(archive, "_snapshot", side_effect=fake_snapshot), \
         patch.object(archive, "save_snapshot", return_value=(None, False)):
        archive.archive_urls([f"https://x.test/{i}" for i in range(5)], save_new=False)
    assert calls == ["https://x.test/0"], f"kept asking after a 429: {calls}"


def test_a_genuine_miss_is_still_cached(tmp_path):
    """The control for the test above: when the archive DOES answer and has nothing, that is
    a fact about the URL and must still be remembered, or every run re-spends the request."""
    cache = tmp_path / "c.json"
    with patch.object(archive, "_snapshot", return_value=(None, False)), \
         patch.object(archive, "save_snapshot", return_value=(None, False)):
        archive.archive_urls(["https://x.test/a"], cache_path=cache)
    assert json.loads(cache.read_text())["https://x.test/a"]["memento"] is None


# ---------------------------------------------------------------------------
# Save Page Now
# ---------------------------------------------------------------------------

def test_save_reads_content_location():
    resp = _Resp(headers={"Content-Location": "/web/20260809/https://x.test/a"})
    with patch.object(archive.requests, "get", return_value=resp):
        memento, limited = archive.save_snapshot("https://x.test/a")
    assert memento == "https://web.archive.org/web/20260809/https://x.test/a"
    assert limited is False


def test_save_falls_back_to_the_final_url():
    resp = _Resp(url="https://web.archive.org/web/20260809/https://x.test/a")
    with patch.object(archive.requests, "get", return_value=resp):
        memento, _ = archive.save_snapshot("https://x.test/a")
    assert memento == "https://web.archive.org/web/20260809/https://x.test/a"


def test_429_reports_rate_limited():
    with patch.object(archive.requests, "get", return_value=_Resp(status=429)):
        memento, limited = archive.save_snapshot("https://x.test/a")
    assert memento is None and limited is True


# ---------------------------------------------------------------------------
# Batch behaviour
# ---------------------------------------------------------------------------

def test_one_429_stops_saving_for_the_whole_batch(tmp_path):
    """Continuing to hammer SPN after it asked us to stop earns a longer block, which the
    NEXT publish inherits."""
    saves = []

    def fake_save(url, timeout_s):
        saves.append(url)
        return None, True  # rate-limited on the very first save

    with patch.object(archive, "_snapshot", return_value=(None, False)), \
         patch.object(archive, "save_snapshot", side_effect=fake_save):
        out = archive.archive_urls([f"https://x.test/{i}" for i in range(5)],
                                   cache_path=tmp_path / "c.json")
    assert out == {}
    assert len(saves) == 1, f"kept saving after a 429: {saves}"


def test_existing_snapshot_avoids_the_expensive_save():
    with patch.object(archive, "_snapshot", return_value=("https://web.archive.org/w/1", False)), \
         patch.object(archive, "save_snapshot") as spn:
        out = archive.archive_urls(["https://x.test/a"])
    assert out == {"https://x.test/a": "https://web.archive.org/w/1"}
    assert not spn.called, "saved a page that was already archived"


def test_cached_memento_costs_no_network(tmp_path):
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({
        "https://x.test/a": {"memento": "https://web.archive.org/w/1", "ts": 1}}))
    with patch.object(archive, "_snapshot") as look, \
         patch.object(archive, "save_snapshot") as spn:
        out = archive.archive_urls(["https://x.test/a"], cache_path=cache)
    assert out == {"https://x.test/a": "https://web.archive.org/w/1"}
    assert not look.called and not spn.called


def test_a_failure_is_retried_later_not_remembered_for_a_week(tmp_path):
    """The inverse of pack_linter's 7-day cache of a WRONG dead verdict: a miss is a
    statement about today's network, so it must expire quickly."""
    assert archive._FAILURE_TTL_S <= 24 * 3600
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({
        "https://x.test/a": {"memento": None, "ts": 0}}))  # ancient failure
    with patch.object(archive, "_snapshot", return_value=("https://web.archive.org/w/2", False)), \
         patch.object(archive, "save_snapshot", return_value=(None, False)):
        out = archive.archive_urls(["https://x.test/a"], cache_path=cache)
    assert out == {"https://x.test/a": "https://web.archive.org/w/2"}


def test_max_urls_is_bounded_and_deduped():
    with patch.object(archive, "_snapshot", return_value=("https://web.archive.org/w/1", False)), \
         patch.object(archive, "save_snapshot", return_value=(None, False)):
        out = archive.archive_urls(["https://x.test/a"] * 4 + [f"https://x.test/{i}" for i in range(10)],
                                   max_urls=3)
    assert len(out) == 3


# ---------------------------------------------------------------------------
# The publish-path contract
# ---------------------------------------------------------------------------

def test_archive_sources_never_raises():
    """This runs inside publish_pass, upstream of the money rail. A requests edge case here
    must never be the reason a paid-for pack fails to ship."""
    src = Source.make("https://x.test/a", "the passage")
    with patch.object(archive, "archive_urls", side_effect=RuntimeError("kaboom")):
        assert archive.archive_sources([src]) == 0
    assert src.archived_url is None


def test_archive_sources_populates_the_field():
    src = Source.make("https://x.test/a", "the passage")
    with patch.object(archive, "archive_urls",
                      return_value={"https://x.test/a": "https://web.archive.org/w/1"}):
        assert archive.archive_sources([src]) == 1
    assert src.archived_url == "https://web.archive.org/w/1"


def test_old_dossiers_still_deserialise():
    """`retrieval.py:1337` does Source(**d) over stored payloads; every dossier written
    before 2026-08-09 lacks this key."""
    old = {"source_id": "s1", "url": "https://x.test/a", "text": "t"}
    assert Source(**old).archived_url is None


# ---------------------------------------------------------------------------
# The reader -- a memento nobody renders is a write-only field
# ---------------------------------------------------------------------------

def _dossier_with(src: Source):
    from prospector.models import Candidate, CheckResult, Decision, Dossier, Verdict
    cand = Candidate(candidate_id="a" * 16, title="T", one_liner="o", market="uk",
                     who_pays="operators", why_now="new rules")
    check = CheckResult(check_name="pain_reality", verdict=Verdict.SUPPORTED, confidence=0.8,
                        rationale="r", citations=[src.source_id], sources=[src])
    return Dossier(candidate=cand, decision=Decision.PASS, checks=[check],
                   created_at="2026-08-09T00:00:00Z")


def test_the_buyer_sees_the_archived_copy():
    """Rendered for real through the function that writes the pack's QA report -- asserting
    on the renderer's SOURCE instead would pass just as happily if it never ran."""
    from prospector.dossier import render_markdown

    src = Source.make("https://x.test/a", "the quoted passage",
                      fetched_at="2026-08-09T01:00:00+00:00")
    src.archived_url = "https://web.archive.org/web/20260809/https://x.test/a"
    md = render_markdown(_dossier_with(src))

    assert "https://web.archive.org/web/20260809/https://x.test/a" in md
    assert "Archived copy:" in md
    assert "as retrieved 2026-08-09" in md   # the date is half of what makes it evidence
    assert "the quoted passage" in md        # the passage is still the primary evidence
    assert "https://x.test/a" in md          # and the live URL is still offered


def test_an_unarchived_source_renders_exactly_as_before():
    """No memento must mean no change: every pack published before today has none."""
    from prospector.dossier import render_markdown

    src = Source.make("https://x.test/a", "the quoted passage")
    md = render_markdown(_dossier_with(src))
    assert "Archived copy:" not in md
    assert "the archived copy is the same text" not in md
    assert "https://x.test/a" in md
