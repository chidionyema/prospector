"""Undated evidence cannot support a "why now" claim.

A "why now" is a claim about TIME: the window opened, the rule changed, the incumbent moved.
A passage with no publication date cannot carry that claim — and to a buyer reading the
dossier, a citation with no date reads as weak evidence whatever it says, because nothing on
the page tells them whether it describes this year or 2011. The date is already sitting in the
HTML we fetch anyway (`article:published_time`, JSON-LD `datePublished`, `<time datetime>`), so
reading it costs one xpath pass and no LLM call.

The properties pinned below are the ones that make this safe rather than merely useful. The
ordering ones (3, 4) matter most: `fetch_page` strips `<script>`, `<footer>` and `<header>` as
page furniture BEFORE reading any text, so extracting the date after that strip finds nothing
on most real pages while every unit test built on a `<meta>` tag keeps passing.
"""
from __future__ import annotations

import pytest

from prospector.models import Source
from prospector.retrieval import (
    _MIN_PAGE_TEXT,
    PageTextEnricher,
    SearchProvider,
    _normalise_date,
    fetch_page,
)


# Copied, not imported, from test_grounding_fetches_the_page_not_the_snippet.py: a shared
# fixture helper across test modules turns two independent proofs into one.
class _Resp:
    def __init__(self, body: bytes, status: int = 200, ctype: str = "text/html"):
        self._body, self.status_code = body, status
        self.headers = {"Content-Type": ctype}
        self.encoding = "utf-8"
        self.closed = False

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def close(self):
        self.closed = True


def _patch_get(monkeypatch, resp):
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp)
    return resp


# One body, reused by every fixture below, deliberately over `_MIN_PAGE_TEXT` (200): under that
# floor `fetch_page` returns no passage whatever it extracted, so a short fixture could report
# a date-extraction pass or failure for a reason that has nothing to do with dates.
_PROSE = (b"<p>The tenancy deposit must be protected within 30 calendar days of receipt, and "
          b"the prescribed information must then be served on the tenant by the landlord.</p>") * 3
assert len(_PROSE) > 400, "fixture body is too short to clear the passage floor"


def _page(head: bytes = b"", body_extra: bytes = b"") -> bytes:
    return (b"<html><head>" + head + b"</head><body><main>" + _PROSE + body_extra
            + b"</main></body></html>")


def test_the_article_published_time_meta_is_read(monkeypatch):
    """The commonest shape on the open web: Open Graph article metadata."""
    _patch_get(monkeypatch, _Resp(
        _page(head=b'<meta property="article:published_time" content="2024-03-11T09:00:00Z">')))

    assert fetch_page("https://example.invalid/x")[1] == "2024-03-11", (
        "the page declared its publication date in article:published_time and we dropped it, "
        "so this citation reaches the buyer undated")


def test_the_plain_date_meta_is_read(monkeypatch):
    """gov.uk-style pages use the bare `date` meta name rather than Open Graph."""
    _patch_get(monkeypatch, _Resp(_page(head=b'<meta name="date" content="2023-05-04">')))

    assert fetch_page("https://example.invalid/x")[1] == "2023-05-04", (
        "a <meta name=date> page came back undated, so the whole gov.uk shape is unread")


def test_jsonld_is_read_BEFORE_the_script_tag_is_stripped(monkeypatch):
    """Extraction must happen before `strip_elements` deletes the <script>.

    THIS IS THE WAY THIS CHANGE BREAKS. `fetch_page` strips `script` as page furniture (it is
    not prose, and it inflates the question/passage overlap `verify.py` scores confidence on).
    JSON-LD — the only date a lot of news sites publish — lives inside exactly that tag, so
    extracting the date after the strip silently finds nothing on those pages while every
    `<meta>`-based test above keeps passing. The date is nested here on purpose: real blobs
    put `datePublished` inside `mainEntity`/`@graph`, not at the top level.
    """
    _patch_get(monkeypatch, _Resp(_page(
        head=b'<script type="application/ld+json">'
             b'{"@type":"NewsArticle","mainEntity":{"datePublished":"2022-09-30T12:00:00+01:00"}}'
             b'</script>')))

    assert fetch_page("https://example.invalid/x")[1] == "2022-09-30", (
        "the JSON-LD date was lost — extraction is running after strip_elements deleted the "
        "<script>, which silently undates every news site that publishes only JSON-LD")


def test_a_time_tag_in_the_footer_is_read_BEFORE_the_footer_is_stripped(monkeypatch):
    """Same ordering reason as the JSON-LD case, different tag.

    `<time datetime>` overwhelmingly sits in the page's `<footer>` or `<header>` byline, and
    `fetch_page` strips both as chrome. Extract after the strip and this date is gone too.
    """
    _patch_get(monkeypatch, _Resp(
        _page(body_extra=b'<footer>Published <time datetime="2021-07-02">2 July 2021</time>'
                         b'</footer>')))

    assert fetch_page("https://example.invalid/x")[1] == "2021-07-02", (
        "the <time> date was lost — extraction is running after strip_elements deleted the "
        "<footer>, where bylines actually live")


def test_the_meta_date_wins_over_a_time_tag(monkeypatch):
    """Priority is not cosmetic: a `<time>` tag is as likely to be a comment timestamp or a
    'related articles' byline as the article's own date, while the meta tag is the page
    declaring its own publication date. The declaration must win."""
    _patch_get(monkeypatch, _Resp(_page(
        head=b'<meta property="article:published_time" content="2024-03-11T09:00:00Z">',
        body_extra=b'<footer><time datetime="2019-01-01">1 Jan 2019</time></footer>')))

    assert fetch_page("https://example.invalid/x")[1] == "2024-03-11", (
        "a stray <time> tag outranked the page's own declared date, so we would date "
        "citations by whatever timestamp happened to appear in the sidebar")


@pytest.mark.parametrize("raw", ["", "not a date", "0001-01-01", "2999-12-31", "1985-06-06",
                                 "2024-13-45", "id-2024-03-11", None])
def test_junk_is_rejected(raw):
    """A wrong date is worse than no date: it is a false claim about time in a dossier.

    `id-2024-03-11` is the one that motivates the anchored regex — an unanchored search would
    pull a date out of an id or a query string and present it as the publication date.
    """
    assert _normalise_date(raw) is None, (
        f"{raw!r} was accepted as a publication date, so a dossier can now carry a date the "
        f"page never published")


@pytest.mark.parametrize("raw", ["2024-03-11", "2024-03-11T09:00:00Z", "2024/03/11"])
def test_real_dates_are_normalised_to_a_plain_day(raw):
    assert _normalise_date(raw) == "2024-03-11", (
        f"{raw!r} is a real date the web serves and we refused it")


def test_a_page_with_no_date_still_yields_its_passage(monkeypatch):
    """A missing date must never cost us the page. Most of the web declares no date at all,
    and the passage is the evidence — the date is only ever a bonus on top of it."""
    _patch_get(monkeypatch, _Resp(_page()))
    text, published = fetch_page("https://example.invalid/x")

    assert published is None, "a date was invented for a page that declares none"
    assert text is not None and len(text) >= _MIN_PAGE_TEXT, (
        "an undated page lost its passage — date extraction must never cost us evidence")
    assert "tenancy deposit" in text


# --------------------------------------------------------------------------------------
# the enricher, which is what actually writes the date onto the Source
# --------------------------------------------------------------------------------------

class _Inner(SearchProvider):
    """A provider that returns exactly what a snippet-only provider returns today."""

    def __init__(self, texts: list[str], published_at: str | None = None) -> None:
        self.texts = texts
        self.published_at = published_at

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        return [Source.make(url=f"https://example.invalid/{i}", text=t, query=query,
                            published_at=self.published_at)
                for i, t in enumerate(self.texts)]


SNIPPET = "A" * 220          # the real measured median is 217 chars
PAGE = "B" * 1400            # what the page itself yields


def test_the_enricher_records_the_date_on_the_source(monkeypatch):
    """The end-to-end property: a date read out of the HTML reaches the stored Source."""
    monkeypatch.setattr("prospector.retrieval.fetch_page",
                        lambda url, **k: (PAGE, "2024-03-11"))
    out = PageTextEnricher(_Inner([SNIPPET])).search("q")

    assert out[0].published_at == "2024-03-11", (
        "the page's date was extracted and then thrown away instead of being stored")


def test_the_enricher_never_overwrites_a_date_the_provider_supplied(monkeypatch):
    """A search provider that returns a date got it from the search index, which knows things
    the page body does not (a redirect target, a syndicated original). This layer can only
    ever ADD, exactly as it can only ever add text."""
    monkeypatch.setattr("prospector.retrieval.fetch_page",
                        lambda url, **k: (PAGE, "2024-03-11"))
    out = PageTextEnricher(_Inner([SNIPPET], published_at="2001-01-01")).search("q")

    assert out[0].published_at == "2001-01-01", (
        "page enrichment overwrote a date the provider had already supplied")


def test_the_date_is_recorded_even_when_the_text_is_not_an_upgrade(monkeypatch):
    """A page whose snippet already beat the gain floor still told us when it was published.

    THIS IS THE ONE THAT FAILS if the date is only recorded inside the upgrade branch. The
    gain floor rejects most real pages (10 of 12 measured passages were already at the
    1500-char cap, so there was no headroom to win), so recording the date only on an upgrade
    would leave the great majority of sources undated for a reason unrelated to dates.
    """
    short_page = "C" * (len(SNIPPET) + 399)          # one char under the 400 gain floor
    monkeypatch.setattr("prospector.retrieval.fetch_page",
                        lambda url, **k: (short_page, "2024-03-11"))
    out = PageTextEnricher(_Inner([SNIPPET]), min_gain_chars=400).search("q")

    assert out[0].text == SNIPPET, "a page under the gain floor replaced a real snippet"
    assert out[0].published_at == "2024-03-11", (
        "the date was only recorded when the text was an upgrade, so every source whose "
        "snippet already cleared the gain floor stays undated")
