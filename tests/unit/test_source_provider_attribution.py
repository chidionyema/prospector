"""Every retrieved passage records WHICH provider supplied it (`Source.retrieved_by`).

THE DEFECT. Until 2026-08-14 a stored source was
`{source_id, url, text, published_at, query, fetched_at}` — no provider. So the question
that decides the whole retrieval programme, "which engine is giving us this evidence?",
could not be answered from `store/dossiers/*.json` at all.

What was at stake, measured the same day over 13,479 citations written 8-14 Aug:

    en.wikipedia.org        970          gov.uk                  455
    youtube.com             318          linkedin.com            262
    merriam-webster.com     128          tiktok.com               72
    dictionary.cambridge.org 42          facebook.com             66

    primary-source share of ALL citations: 1,204 / 13,479 = 8.9%

Two dictionaries supplied 170 citations of evidence about whether business problems are
real. Attributing that to a provider required replaying queries against the live web,
because our own audit trail did not record it. `docs/RETRIEVAL_PROGRAM.md` §D8.

THE FENCE THESE TESTS PIN. Attribution is structural — a provider is stamped because of how
`make_provider` COMPOSES it, not because a provider class remembered to pass a kwarg at one
of ~11 `Source.make` call sites. That is what makes it survive the next provider added.
"""
from __future__ import annotations

import pytest

from prospector.config import Retrieval
from prospector.models import Source
from prospector.retrieval import (
    FallbackSearchProvider,
    ProviderStamped,
    SearchProvider,
    make_provider,
)

QUERY = "Illinois BIPA reform legislation per person violation"


class _Fake(SearchProvider):
    """A provider that returns fresh, unstamped sources — as every real one does."""

    def __init__(self, urls: list[str], text: str = "some retrieved passage text") -> None:
        self.urls = urls
        self.text = text
        self.calls = 0

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        self.calls += 1
        return [Source.make(url=u, text=self.text, query=query) for u in self.urls]


class _Cfg:
    """The narrowest config `make_provider` needs. `cache=False` deliberately: it returns
    before `DiskCache`, so these tests never touch `_market_block` or the filesystem."""

    def __init__(self, retrieval: Retrieval) -> None:
        self.retrieval = retrieval


def _cfg(provider, **kw) -> _Cfg:
    return _Cfg(Retrieval(provider=provider, cache=False, fetch_pages=False,
                          relevance_overfetch=1, **kw))


def _stub_builds(monkeypatch, mapping: dict[str, SearchProvider]) -> None:
    monkeypatch.setattr("prospector.retrieval._build_search",
                        lambda name, cfg, fixtures=None: mapping[name])


# --------------------------------------------------------------------------------------
# The stamp itself
# --------------------------------------------------------------------------------------

def test_stamps_every_source_with_the_provider_name():
    inner = _Fake(["https://ilga.gov/bipa", "https://en.wikipedia.org/wiki/Privacy"])
    out = ProviderStamped("ddg", inner).search(QUERY)
    assert [s.retrieved_by for s in out] == ["ddg", "ddg"]


def test_never_overwrites_an_existing_stamp():
    """A cached passage really was retrieved by whoever first returned it. Re-stamping it
    with today's chain head would invent an attribution that never happened."""
    class _Replay(SearchProvider):
        def search(self, query, k=4, max_chars=1500):
            return [Source.make(url="https://ilga.gov/bipa", text="cached passage",
                                query=query, retrieved_by="exa")]

    out = ProviderStamped("ddg", _Replay()).search(QUERY)
    assert out[0].retrieved_by == "exa"


def test_empty_result_set_is_passed_through_untouched():
    class _Empty(SearchProvider):
        def search(self, query, k=4, max_chars=1500):
            return []

    assert ProviderStamped("ddg", _Empty()).search(QUERY) == []


def test_is_transparent_to_the_wrapped_providers_surface():
    """Anything reaching past `.search` (breaker bookkeeping, probes, `close()`) must still
    find the real provider, or it fails far from here and reads as a provider outage."""
    inner = _Fake(["https://ilga.gov/bipa"])
    inner.some_probe_attr = "live"                     # type: ignore[attr-defined]
    stamped = ProviderStamped("ddg", inner)
    assert stamped.some_probe_attr == "live"
    assert stamped.urls == ["https://ilga.gov/bipa"]


def test_a_source_that_cannot_be_stamped_never_breaks_grounding():
    """Attribution is an audit field. Losing it costs a measurement; raising costs a verdict."""
    class _Frozen:
        __slots__ = ("url", "text")

        def __init__(self):
            self.url, self.text = "https://ilga.gov/bipa", "passage"

    class _Odd(SearchProvider):
        def search(self, query, k=4, max_chars=1500):
            return [_Frozen()]

    out = ProviderStamped("ddg", _Odd()).search(QUERY)
    assert len(out) == 1                                # returned, not dropped, not raised


# --------------------------------------------------------------------------------------
# The structural fence: attribution comes from COMPOSITION, not from provider authors
# --------------------------------------------------------------------------------------

def test_make_provider_stamps_a_multi_provider_chain(monkeypatch):
    a, b = _Fake(["https://en.wikipedia.org/wiki/Privacy"]), _Fake(["https://ilga.gov/bipa"])
    _stub_builds(monkeypatch, {"ddg": a, "exa": b})
    out = make_provider(_cfg(["ddg", "exa"])).search(QUERY)
    assert [s.retrieved_by for s in out] == ["ddg"]      # first to answer, correctly named


def test_make_provider_stamps_a_SINGLE_provider_config(monkeypatch):
    """The single-provider path skips `FallbackSearchProvider` entirely (`make_provider`
    returns `built[0][1]`), so a stamp that lived inside the chain would miss it."""
    _stub_builds(monkeypatch, {"ddg": _Fake(["https://ilga.gov/bipa"])})
    out = make_provider(_cfg("ddg")).search(QUERY)
    assert [s.retrieved_by for s in out] == ["ddg"]


def test_every_provider_in_the_chain_is_wrapped(monkeypatch):
    """The fence proper: a provider is attributable because of how it is composed. A new
    provider class added to `_build_search` inherits this without touching its own code."""
    _stub_builds(monkeypatch, {n: _Fake([f"https://{n}.example"]) for n in
                               ("ddg", "exa", "claude_cli")})
    chain = make_provider(_cfg(["ddg", "exa", "claude_cli"]))
    assert isinstance(chain, FallbackSearchProvider)
    assert [n for n, _ in chain.providers] == ["ddg", "exa", "claude_cli"]
    for name, prov in chain.providers:
        assert isinstance(prov, ProviderStamped), f"{name} is not attributable"
        assert prov.name == name


def test_the_escalated_provider_is_the_one_credited(monkeypatch):
    """Relevance failover returns the BEST set, not the first. The credit must follow the
    passages, or the attribution blames the provider that was rejected."""
    off = _Fake(["https://en.wikipedia.org/wiki/Privacy"], text="Privacy is the ability")
    on = _Fake(["https://ilga.gov/bipa"],
               text="Illinois BIPA reform legislation caps per person violation damages")
    _stub_builds(monkeypatch, {"ddg": off, "exa": on})
    out = make_provider(_cfg(["ddg", "exa"], min_relevance=0.35)).search(QUERY)
    assert out, "escalation must never return an empty set"
    assert [s.retrieved_by for s in out] == ["exa"]


# --------------------------------------------------------------------------------------
# Serialisation: the field is only useful if it reaches disk and comes back
# --------------------------------------------------------------------------------------

def test_round_trips_through_the_disk_cache_shape():
    """`DiskCache` stores `to_dict()` and rebuilds with `Source(**d)`."""
    s = Source.make(url="https://ilga.gov/bipa", text="passage", query=QUERY,
                    retrieved_by="exa")
    assert s.to_dict()["retrieved_by"] == "exa"
    assert Source(**s.to_dict()).retrieved_by == "exa"


def test_a_pre_2026_08_14_source_still_deserialises():
    """Absent means "written before attribution existed", never "unknown provider". Every
    dossier on disk today lacks the key and must still load."""
    old = {"source_id": "abc", "url": "https://ilga.gov/bipa", "text": "passage",
           "published_at": None, "query": QUERY, "fetched_at": None}
    assert Source(**old).retrieved_by is None


@pytest.mark.parametrize("field", ["retrieved_by"])
def test_the_field_is_not_called_provider(field):
    """A dossier check already has `provider`, meaning the VERDICT brain that ruled it.
    "Who found the page" and "who judged it" must not share a word in the same document."""
    assert field in Source.__dataclass_fields__
    assert "provider" not in Source.__dataclass_fields__
