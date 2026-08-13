"""Per-market retrieval: authority domains, search region, cache isolation (spec D4).

`test_uk_cache_path_is_unchanged` is the one that protects real money: if the UK salt
ever stops being empty, ~8k cached passages are invalidated at once and the next batch
re-fetches all of them.
"""
from __future__ import annotations

from prospector import retrieval
from prospector.config import load_config
from prospector.retrieval import (
    _HIGH_AUTHORITY_TIMEOUT,
    _RESOLVE_TIMEOUT,
    DiskCache,
    DuckDuckGoSearchProvider,
    _get_timeout,
    make_provider,
    market_retrieval,
)


class _Stub(retrieval.SearchProvider):
    def __init__(self):
        self.calls = []

    def search(self, query, k=4, max_chars=1500):
        self.calls.append((query, k, max_chars))
        return [retrieval.Source.make(url="https://example.com/a", text="hit")]


# ---------------------------------------------------------------------------
# Authority domains
# ---------------------------------------------------------------------------

def test_market_authority_domains_get_the_patient_timeout():
    """courtlistener.com is a US authority but not a .gov and not in the global base
    set, so it only qualifies while the US market is active."""
    url = "https://www.courtlistener.com/docket/123/"
    assert _get_timeout(url) == _RESOLVE_TIMEOUT

    with market_retrieval(load_config().for_market("us")):
        assert _get_timeout(url) == _HIGH_AUTHORITY_TIMEOUT

    assert _get_timeout(url) == _RESOLVE_TIMEOUT  # restored on exit


def test_global_authorities_apply_in_every_market():
    for market in ("uk", "us"):
        with market_retrieval(load_config().for_market(market)):
            assert _get_timeout("https://www.reuters.com/x") == _HIGH_AUTHORITY_TIMEOUT


def test_uk_authorities_do_not_leak_into_the_us_context():
    uk_only = "https://www.companieshouse.gov.uk/company/1"
    with market_retrieval(load_config().for_market("uk")):
        assert _get_timeout(uk_only) == _HIGH_AUTHORITY_TIMEOUT
    # .gov.uk is in the global base set, so pick a market domain that is not:
    with market_retrieval(load_config().for_market("us")):
        assert _get_timeout("https://www.fca.org.uk/x") == _RESOLVE_TIMEOUT
    with market_retrieval(load_config().for_market("uk")):
        assert _get_timeout("https://www.fca.org.uk/x") == _HIGH_AUTHORITY_TIMEOUT


def test_an_unrelated_thread_does_not_inherit_the_market():
    """The reason this is a ContextVar and not a module global: a thread that was never
    given a market must not borrow whichever market happened to be active elsewhere."""
    import threading

    seen = {}

    def worker():
        seen["thread"] = _get_timeout("https://www.courtlistener.com/x")

    with market_retrieval(load_config().for_market("us")):
        t = threading.Thread(target=worker)
        t.start()
        t.join()
        seen["main"] = _get_timeout("https://www.courtlistener.com/x")

    assert seen["main"] == _HIGH_AUTHORITY_TIMEOUT
    assert seen["thread"] == _RESOLVE_TIMEOUT


def test_market_context_reaches_the_search_pool():
    """run_check fans its searches out over a ThreadPoolExecutor, and the fetch inside
    each search is what reads the authority list. A ContextVar does not cross a bare
    thread boundary, so without an explicit context copy the market's domains are
    configured but inert — every market would quietly fetch on the base set alone."""
    from prospector import verify
    from prospector.models import Candidate

    seen = {}

    class _Search:
        def search(self, query, k=4, max_chars=1500):
            seen["timeout"] = _get_timeout("https://www.courtlistener.com/x")
            return []

    cand = Candidate(title="T", one_liner="one liner", hypothesis="h",
                     who_pays="payer", why_now="now")
    cfg = load_config().for_market("us")
    with market_retrieval(cfg):
        verify.run_check(object(), _Search(), cfg, cand, "pain_reality",
                         precomputed_queries={"pain_reality": ["query one", "query two"]})

    assert seen["timeout"] == _HIGH_AUTHORITY_TIMEOUT


# ---------------------------------------------------------------------------
# Cache isolation
# ---------------------------------------------------------------------------

def test_cache_salt_isolates_markets(tmp_path):
    a = DiskCache(_Stub(), cache_dir=tmp_path, key_salt="")
    b = DiskCache(_Stub(), cache_dir=tmp_path, key_salt="us")
    assert a._path("same query", 4, 1500) != b._path("same query", 4, 1500)


def test_uk_cache_path_is_unchanged(tmp_path):
    """Pinned against the pre-Epic-D key so the existing store/_cache stays valid.
    A change here silently invalidates thousands of cached passages."""
    import hashlib

    query, k, max_chars = "NHS nurse pension take-up", 4, 1500
    legacy = hashlib.sha1(f"{query}|{k}|{max_chars}".encode()).hexdigest()[:20]
    cache = DiskCache(_Stub(), cache_dir=tmp_path, key_salt="")
    assert cache._path(query, k, max_chars).name == f"{legacy}.json"


def test_shipped_uk_market_uses_the_empty_salt():
    cfg = load_config().for_market("uk")
    assert cfg.market_config().get("cache_salt", "") == ""


def test_make_provider_applies_the_market_salt(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval, "CACHE_DIR", tmp_path)
    cfg = load_config().for_market("us")
    cfg.retrieval.provider = "ddg"
    cfg.retrieval.cache = True
    provider = make_provider(cfg)
    assert isinstance(provider, DiskCache)
    assert provider.key_salt == "us"


# ---------------------------------------------------------------------------
# Search region
# ---------------------------------------------------------------------------

def test_ddg_provider_receives_the_market_region():
    """The region must survive whatever wraps the provider.

    `retrieval.fetch_pages` (on since 2026-08-13) puts a PageTextEnricher between
    make_provider's return value and the DDG provider, so asserting the TOP-LEVEL type
    pins the chain's shape rather than the region this test is named for. Unwrap
    explicitly and assert both: the shape AND the region, so neither can drift silently.
    """
    cfg = load_config().for_market("us")
    cfg.retrieval.provider = "ddg"
    cfg.retrieval.cache = False
    provider = make_provider(cfg)
    assert isinstance(provider, retrieval.PageTextEnricher), (
        "config.yaml retrieval.fetch_pages is on; make_provider must wrap the chain"
    )
    inner = provider._inner
    assert isinstance(inner, DuckDuckGoSearchProvider)
    assert inner.region == "us-en"


def test_ddg_region_is_passed_to_the_library(monkeypatch):
    """ddgs defaults region to 'us-en' when omitted, so 'omitted' is not neutral —
    the argument must actually be sent."""
    captured = {}

    class _FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, **kwargs):
            captured.update(kwargs)
            return []

    import sys
    import types
    fake = types.ModuleType("ddgs")
    fake.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake)

    DuckDuckGoSearchProvider(region="uk-en").search("q", k=3)
    assert captured.get("region") == "uk-en"

    captured.clear()
    DuckDuckGoSearchProvider().search("q", k=3)
    assert "region" not in captured  # unset => library default, today's behaviour
