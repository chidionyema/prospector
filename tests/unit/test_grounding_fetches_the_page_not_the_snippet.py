"""The verdict brain must rule on the PAGE, not on the search engine's result snippet.

WHAT THIS COST, MEASURED
------------------------
`retrieval._resolve()` sends a HEAD request: by design it proves the host is real and never
reads the body. Every provider then stored the search engine's result blurb as the passage —
`DuckDuckGoSearchProvider` does this literally, `text = item.get("body", "")[:max_chars]`, and
DDG's `body` IS the snippet. There was no page-fetch step anywhere in `retrieval.py`.

Measured 2026-08-13 over every grounding passage recorded since 2026-08-08 (n=11,857):

    mean 222 chars | median 217 | p90 281 | max 1500
    94.7% under 300 chars      <- `max_passage_chars: 1500` had never once bound
    `verify.VERDICT_PASSAGE_TRUNCATE` = 600, so we filled 37% of a budget already there

Consequence, from the dossiers themselves:

    unverifiable checks since 2026-08-08 : 1,701
      with ZERO sources fetched          :     0  (0.0%)   <- retrieval was NOT failing
      WITH sources fetched               : 1,701  (100.0%) <- fetched, nothing supported it
    67.5% of all checks ruled `unverifiable`
    grounding kills (moat_ungrounded + source_or_die): 43.9% -> 54.6% of all kills
    PASS rate: ~19% (2026-08-01) -> ~1% (2026-08-13)

The engine had never read a web page. It also explains the dead citations: a URL we never
opened is only discovered to be gone when the linter probes it months later.

The properties pinned below are the ones that make this safe rather than merely effective.
The enricher can only ADD: every failure mode leaves the original snippet in place, because a
grounding fetch that fails is our convenience failing, and this repo has already paid once for
an outage that presented as a fully-reasoned kill.
"""
from __future__ import annotations

import sys

import pytest

from prospector.models import Source
from prospector.retrieval import _MIN_PAGE_TEXT, PageTextEnricher, SearchProvider, fetch_page_text


class _Inner(SearchProvider):
    """A provider that returns exactly what a snippet-only provider returns today."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls: list[tuple[str, int, int]] = []

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        self.calls.append((query, k, max_chars))
        return [Source.make(url=f"https://example.invalid/{i}", text=t, query=query)
                for i, t in enumerate(self.texts)]


SNIPPET = "A" * 220          # the real measured median is 217 chars
PAGE = "B" * 1400            # what the page itself yields


def _enricher(inner, monkeypatch, page_result, **kw):
    import prospector.retrieval as R
    monkeypatch.setattr(R, "fetch_page_text",
                        lambda url, **k: page_result(url) if callable(page_result) else page_result)
    return PageTextEnricher(inner, **kw)


def test_a_fetched_page_replaces_the_snippet(monkeypatch):
    """The whole point: the verdict brain sees the page, not the blurb."""
    inner = _Inner([SNIPPET])
    enr = _enricher(inner, monkeypatch, PAGE)
    out = enr.search("q", k=3, max_chars=1500)

    assert len(out) == 1
    assert out[0].text == PAGE, "the snippet was still handed to the verdict brain"
    assert len(out[0].text) > 6 * len(SNIPPET)


def test_a_failed_fetch_KEEPS_the_snippet(monkeypatch):
    """A grounding fetch failing must never cost a source.

    Losing the snippet here would convert an ordinary network failure into a check with less
    evidence than before — i.e. into a false `unverifiable`, which is the exact failure mode
    the DEFER rule exists to prevent.
    """
    inner = _Inner([SNIPPET])
    enr = _enricher(inner, monkeypatch, None)
    out = enr.search("q")

    assert out[0].text == SNIPPET, "a failed page fetch destroyed the snippet we already had"


def test_a_shorter_page_never_overwrites_a_longer_snippet(monkeypatch):
    """Bot-walls answer 200 with 'please enable JavaScript'. That is not an upgrade."""
    inner = _Inner([SNIPPET])
    enr = _enricher(inner, monkeypatch, "Please enable JavaScript to continue.",
                    min_gain_chars=400)
    out = enr.search("q")

    assert out[0].text == SNIPPET, "a bot-wall shim replaced a real snippet with less text"


def test_the_gain_floor_is_honoured_exactly(monkeypatch):
    """Guard-the-guard: a page must beat the snippet by min_gain_chars, not merely match it."""
    just_under = "C" * (len(SNIPPET) + 399)
    assert _enricher(_Inner([SNIPPET]), monkeypatch, just_under,
                     min_gain_chars=400).search("q")[0].text == SNIPPET

    just_over = "C" * (len(SNIPPET) + 400)
    inner2 = _Inner([SNIPPET])
    assert _enricher(inner2, monkeypatch, just_over, min_gain_chars=400).search("q")[0].text == just_over


def test_one_dead_page_does_not_poison_its_siblings(monkeypatch):
    """Fetches are independent. One failure must not cost the other sources their upgrade."""
    inner = _Inner([SNIPPET, SNIPPET, SNIPPET])
    pages = {"https://example.invalid/0": PAGE,
             "https://example.invalid/1": None,
             "https://example.invalid/2": PAGE}
    enr = _enricher(inner, monkeypatch, lambda url: pages[url])
    out = enr.search("q")

    assert [len(s.text) for s in out] == [len(PAGE), len(SNIPPET), len(PAGE)]


def test_an_exploding_fetch_never_loses_the_results(monkeypatch):
    """`fetch_page_text` is contracted never to raise. This pins the belt-and-braces catch."""
    def boom(url, **kw):
        raise RuntimeError("connection reset")

    inner = _Inner([SNIPPET, SNIPPET])
    enr = _enricher(inner, monkeypatch, None)
    import prospector.retrieval as R
    monkeypatch.setattr(R, "fetch_page_text", boom)
    out = enr.search("q")

    assert len(out) == 2 and all(s.text == SNIPPET for s in out), (
        "an exception during enrichment destroyed the grounding results")


def test_empty_results_short_circuit(monkeypatch):
    """No sources means no fetches — a legitimate empty result is evidence, not work."""
    calls = []
    inner = _Inner([])
    import prospector.retrieval as R
    monkeypatch.setattr(R, "fetch_page_text", lambda url, **k: calls.append(url))
    assert PageTextEnricher(inner).search("q") == []
    assert calls == []


def test_the_inner_provider_is_called_through_unchanged(monkeypatch):
    """k and max_chars must reach the real provider untouched — this is a decorator."""
    inner = _Inner([SNIPPET])
    _enricher(inner, monkeypatch, PAGE).search("the query", k=7, max_chars=900)
    assert inner.calls == [("the query", 7, 900)]


# --------------------------------------------------------------------------------------
# fetch_page_text itself
# --------------------------------------------------------------------------------------

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


def test_script_and_style_are_stripped(monkeypatch):
    """Minified JS is not prose, and it would inflate the question/passage word overlap that
    `verify.py:138` scores confidence on — making grounding look better while making it worse.

    The prose is deliberately longer than `_MIN_PAGE_TEXT` (`retrieval.py:489`): under that
    floor the function returns None whatever it stripped, so a short fixture would pass this
    test for a reason that has nothing to do with stripping. Staying over the floor also makes
    the test deterministic about trafilatura — the fallback (`retrieval.py:597`) runs only
    UNDER the floor, so this case never reaches it, installed or not.
    """
    prose = (b"<p>The tenancy deposit must be protected within 30 days of receipt, and the "
             b"prescribed information must then be served on the tenant by the landlord.</p>")
    html = (b"<html><head><style>.a{color:red}</style>"
            b"<script>var trackingPixel=1;function q(){}</script></head>"
            b"<body>" + prose * 2 + b"</body></html>")
    _patch_get(monkeypatch, _Resp(html))
    text = fetch_page_text("https://example.invalid/x")

    assert text is not None and len(text) >= _MIN_PAGE_TEXT, "fixture is under the passage floor"
    assert "tenancy deposit" in text
    assert "trackingPixel" not in text and "color:red" not in text


def test_navigation_chrome_is_not_mistaken_for_evidence(monkeypatch):
    """Boilerplate is worse than the snippet it replaces.

    It inflates the question/passage word overlap `verify.py:138` scores confidence on, so it
    would make grounding LOOK better while making it worse. Proven necessary on the first live
    run, where the longest "upgraded" passage of the batch was
    "Skip Navigation Personal Business Find a store Ver en español Shop Deals ...".

    The body deliberately sits in a plain <div> and NOT in <main>: with a landmark present the
    ladder would exclude the chrome by selecting <main>, and this test would then pass with
    `strip_elements` deleted — i.e. it would stop measuring stripping at all. The document
    fallback is the path where stripping is load-bearing, so that is the path pinned here.
    It also carries more than `_MIN_PAGE_TEXT` (`retrieval.py:489`), so the assertions measure
    stripping and not the passage floor, and the trafilatura fallback (which only fires under
    that floor) is out of the picture whether or not it is installed.
    """
    body = (b"<p>Deposits must be protected within 30 calendar days of receipt, and the "
            b"prescribed information must be given to the tenant in that same window.</p>")
    html = (b"<html><body>"
            b"<nav>Skip Navigation Personal Business Find a store Ver en espanol Shop Deals</nav>"
            b"<header>Search site Your cart is empty</header>"
            b"<div>" + body * 2 + b"</div>"
            b"<footer>Copyright 2026 All rights reserved Privacy Terms</footer>"
            b"</body></html>")
    _patch_get(monkeypatch, _Resp(html))
    text = fetch_page_text("https://example.invalid/x")

    assert text is not None and len(text) >= _MIN_PAGE_TEXT, "fixture is under the passage floor"
    assert "30 calendar days" in text
    for junk in ("Skip Navigation", "cart is empty", "All rights reserved", "Shop Deals"):
        assert junk not in text, f"page furniture {junk!r} was handed to the verdict brain"


def test_an_extraction_under_the_floor_is_no_passage_at_all(monkeypatch):
    """A title, a 404 body or a cookie wall is not a short passage — it is no passage.

    Added 2026-08-15 with `_MIN_PAGE_TEXT` (`retrieval.py:489`, 597-608). The snippet this
    function replaces averages 222 chars, so handing back 25 chars of "Page not found –
    GeekWire" would be a DOWNGRADE that the enricher's gain floor cannot see as one. None is
    the contract for "keep what you had".
    """
    html = b"<html><body><main><p>SOPPA Contracts</p></main></body></html>"
    _patch_get(monkeypatch, _Resp(html))

    assert fetch_page_text("https://example.invalid/x") is None
    # And the caller does keep the snippet, which is the whole point of returning None.
    monkeypatch.setattr("prospector.retrieval.fetch_page_text", lambda url, **k: None)
    assert PageTextEnricher(_Inner([SNIPPET])).search("q")[0].text == SNIPPET


# The .aspx shape that motivated the fallback: the whole body sits inside <form>, which the
# lxml ladder strips as page furniture, so it extracts nothing at all. Measured on
# isbe.net/Pages/SOPPA-Contracts.aspx, which the ladder reduced to 15 chars.
_SENTENCES = [
    "Deposits must be protected within 30 calendar days of receipt by the landlord.",
    "The prescribed information must be served on the tenant within the same period.",
    "A landlord who fails to comply may be ordered to pay up to three times the sum.",
    "The scheme administrator publishes the statutory guidance on its own website.",
    "Tenants may apply to the county court where the deposit was never protected.",
    "The rules apply to assured shorthold tenancies granted on or after 6 April 2007.",
]
_FORM_WRAPPED_PAGE = (
    "<html><head><title>SOPPA Contracts</title>"
    "<script>var trackingPixel=1;function q(){}</script><style>.a{color:red}</style></head>"
    "<body><nav>" + ("Skip Navigation Personal Business Find a store Shop Deals Sign in " * 6)
    + "</nav><form id='form1'><div class='content'>"
    + "".join(f"<p>{s}</p>" for s in _SENTENCES * 3)
    + "</div></form><footer>Copyright 2026 All rights reserved Privacy Terms</footer>"
      "</body></html>"
).encode()


def test_the_fallback_rescues_a_total_extraction_failure_without_readmitting_chrome(monkeypatch):
    """The fallback's justification is rescuing a TOTAL extraction failure, not stripping
    better — on boilerplate the two extractors tied. So it is only allowed to run where the
    ladder returned nothing usable, and it must not hand back the nav bar that the ladder was
    strict about: that would be the "looks better, is worse" outcome, arriving by the back door.
    """
    pytest.importorskip("trafilatura")
    _patch_get(monkeypatch, _Resp(_FORM_WRAPPED_PAGE))
    text = fetch_page_text("https://example.invalid/x")

    assert text and "30 calendar days" in text, "the fallback did not rescue the page"
    for junk in ("Skip Navigation", "Shop Deals", "All rights reserved", "trackingPixel",
                 "color:red"):
        assert junk not in text, f"the fallback readmitted page furniture {junk!r}"


def test_the_fallback_being_absent_is_never_worse_than_not_having_it(monkeypatch):
    """Determinism about the machine: trafilatura is an optional import, so the suite must say
    what happens with AND without it. Without it the same page is simply no passage — the
    caller keeps its snippet — and nothing raises.
    """
    monkeypatch.setitem(sys.modules, "trafilatura", None)   # `import trafilatura` -> ImportError
    _patch_get(monkeypatch, _Resp(_FORM_WRAPPED_PAGE))

    assert fetch_page_text("https://example.invalid/x") is None


def test_a_page_with_no_landmarks_still_yields_its_text(monkeypatch):
    """gov.uk-style pages declare no <main>/<article>. Refusing those would re-create exactly
    the false-drop the HEAD-based `_resolve` docstring spent so long removing."""
    html = (b"<html><body><div><p>" + (b"The rule applies to all landlords. " * 12)
            + b"</p></div></body></html>")
    _patch_get(monkeypatch, _Resp(html))
    text = fetch_page_text("https://example.invalid/x")

    assert text and "all landlords" in text


def test_a_thin_main_falls_back_to_the_document(monkeypatch):
    """A near-empty <main> must not shadow the real content sitting outside it."""
    html = (b"<html><body><main> </main><div>" + (b"Substantive guidance text. " * 20)
            + b"</div></body></html>")
    _patch_get(monkeypatch, _Resp(html))
    text = fetch_page_text("https://example.invalid/x")

    assert text and "Substantive guidance" in text


def test_a_non_html_content_type_is_skipped(monkeypatch):
    _patch_get(monkeypatch, _Resp(b"%PDF-1.4 ...", ctype="application/pdf"))
    assert fetch_page_text("https://example.invalid/x.pdf") is None


def test_an_error_status_is_skipped(monkeypatch):
    _patch_get(monkeypatch, _Resp(b"<html><body>gone</body></html>", status=404))
    assert fetch_page_text("https://example.invalid/x") is None


def test_the_byte_cap_is_enforced(monkeypatch):
    """Some pages are tens of MB. The reader stops; it does not stream the whole thing."""
    huge = b"<html><body>" + (b"z" * 5_000_000) + b"</body></html>"
    _patch_get(monkeypatch, _Resp(huge))
    text = fetch_page_text("https://example.invalid/x", max_chars=1500, max_bytes=50_000)
    assert text is not None and len(text) <= 1500


def test_max_chars_is_respected(monkeypatch):
    body = b"<html><body>" + (b"word " * 5000) + b"</body></html>"
    _patch_get(monkeypatch, _Resp(body))
    assert len(fetch_page_text("https://example.invalid/x", max_chars=600)) == 600


def test_a_network_error_returns_none_and_never_raises(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.RequestException("connection reset by peer")

    monkeypatch.setattr(requests, "get", boom)
    assert fetch_page_text("https://example.invalid/x") is None


def test_binary_junk_can_never_reach_the_verdict_brain(monkeypatch):
    """lxml is permissive: it happily parses `\\x00\\x01\\x02` into a 3-char text node rather
    than raising, so the extractor cannot be relied on to reject junk by itself. What actually
    protects the passage is the gain floor — anything this thin is rejected downstream. Pinned
    here so a future change to either half cannot quietly let binary through.
    """
    _patch_get(monkeypatch, _Resp(b"\x00\x01\x02"))
    got = fetch_page_text("https://example.invalid/x")

    assert got is None or len(got) < 400, "binary junk was returned as a usable passage"
    inner = _Inner([SNIPPET])
    monkeypatch.setattr("prospector.retrieval.fetch_page_text", lambda url, **k: got)
    assert PageTextEnricher(inner, min_gain_chars=400).search("q")[0].text == SNIPPET


def test_concurrent_fetches_do_not_share_one_context(monkeypatch):
    """A single `copy_context()` shared across the pool raises RuntimeError the moment two
    fetches overlap, and the pool-level catch then degrades enrichment to plain snippets while
    still logging success. Measured live 2026-08-13: 0 of 3 passages upgraded.

    Real threads, real overlap — a mocked pool would not reproduce it.
    """
    import threading

    barrier = threading.Barrier(3, timeout=10)

    def slow(url, **kw):
        barrier.wait()          # force all three to be inside `ctx.run` simultaneously
        return PAGE

    monkeypatch.setattr("prospector.retrieval.fetch_page_text", slow)
    out = PageTextEnricher(_Inner([SNIPPET] * 3), max_workers=3).search("q")

    assert [s.text for s in out] == [PAGE] * 3, (
        "concurrent fetches collided on a shared Context and fell back to snippets")


# --------------------------------------------------------------------------------------
# wiring
# --------------------------------------------------------------------------------------

def test_fixtures_are_never_wrapped():
    """The golden-set harness attributes results to the BRAIN, not to search variance.

    Reaching the live web from it would destroy that property and make the suite depend on
    the network.
    """
    from prospector.config import Config, Retrieval
    from prospector.retrieval import make_provider

    cfg = Config(retrieval=Retrieval(provider="fixture", fetch_pages=True, cache=False))
    prov = make_provider(cfg, fixtures={"k": [{"url": "https://x.invalid", "text": "t"}]})

    assert not isinstance(prov, PageTextEnricher), (
        "a fixture-pinned run would reach the live web")


def test_a_single_provider_config_is_still_wrapped():
    """`make_provider` skips FallbackSearchProvider when only one provider is configured.

    Wiring the enricher into the fallback would therefore have silently done nothing on a
    one-provider config — the reason it is a layer of its own.
    """
    from prospector.config import Config, Retrieval
    from prospector.retrieval import make_provider

    cfg = Config(retrieval=Retrieval(provider="ddg", fetch_pages=True, cache=False))
    assert isinstance(make_provider(cfg), PageTextEnricher)


def test_off_by_default_so_nothing_else_changes_behaviour():
    """A directly-constructed Retrieval() must keep its byte-for-byte current behaviour."""
    from prospector.config import Retrieval
    assert Retrieval().fetch_pages is False


def test_the_live_config_actually_switches_this_on():
    """Pins the deployed value, so turning it off is a deliberate, visible act."""
    from prospector.config import load_config

    r = load_config().retrieval
    assert r.fetch_pages is True, (
        "page fetching is off in config.yaml — the engine is back to ruling verdicts on "
        "~220-char search snippets, which measured a 67.5% unverifiable rate")
    assert r.fetch_min_gain_chars > 0
