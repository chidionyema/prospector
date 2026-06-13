"""Provider failover (Part 9): when one LLM is out of quota/credit, the next
takes over for the rest of the run — for grounding AND the verdict brain."""
from __future__ import annotations

import pytest

from prospector.errors import ProviderExhaustedError, looks_exhausted
from prospector.models import Source
from prospector.operator import FallbackOperator, Operator
from prospector.retrieval import FallbackSearchProvider, SearchProvider


# --- error classification ---------------------------------------------------
def test_looks_exhausted_matches_real_markers():
    assert looks_exhausted("TerminalQuotaError ... reason: QUOTA_EXHAUSTED")
    assert looks_exhausted("Error 429 rate limit")
    assert looks_exhausted("Your credit balance is too low")
    assert not looks_exhausted("connection reset by peer")
    assert not looks_exhausted("")


# --- grounding failover -----------------------------------------------------
class _Search(SearchProvider):
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    def search(self, query, k=4, max_chars=1500):
        self.calls += 1
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


def _src():
    return [Source.make(url="https://example.com", text="t", query="q")]


def test_grounding_fails_over_to_next_on_exhaustion():
    dead = _Search(ProviderExhaustedError("out", provider="a"))
    live = _Search(_src())
    fb = FallbackSearchProvider([("a", dead), ("b", live)])
    out = fb.search("q")
    assert out == _src()
    assert dead.calls == 1 and live.calls == 1


def test_grounding_no_failover_on_legit_empty():
    """An empty result from a WORKING provider is real evidence of nothing —
    do NOT fail over (and do not call the next provider)."""
    first = _Search([])           # ran fine, found nothing
    second = _Search(_src())
    fb = FallbackSearchProvider([("a", first), ("b", second)])
    assert fb.search("q") == []
    assert second.calls == 0      # never reached


def test_grounding_all_exhausted_raises():
    fb = FallbackSearchProvider([
        ("a", _Search(ProviderExhaustedError("out"))),
        ("b", _Search(RuntimeError("timeout"))),
    ])
    with pytest.raises(ProviderExhaustedError):
        fb.search("q")


def test_grounding_retires_dead_provider_for_the_run():
    dead = _Search(RuntimeError("boom"))
    live = _Search(_src())
    fb = FallbackSearchProvider([("a", dead), ("b", live)])
    fb.search("q1")
    fb.search("q2")
    # 'a' tried once then retired; 'b' served both calls.
    assert dead.calls == 1 and live.calls == 2


# --- brain failover ---------------------------------------------------------
class _Op(Operator):
    def __init__(self, name, behaviour):
        self.name = name
        self.behaviour = behaviour
        self.calls = 0

    def _raw(self, system, user, temperature):
        self.calls += 1
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


def test_brain_fails_over_and_completes_json():
    dead = _Op("a", ProviderExhaustedError("out"))
    live = _Op("b", '{"ok": true}')
    fb = FallbackOperator([("a", dead), ("b", live)])
    assert fb.complete_json("s", "u") == {"ok": True}
    assert dead.calls == 1 and live.calls == 1


def test_brain_all_exhausted_raises():
    fb = FallbackOperator([
        ("a", _Op("a", ProviderExhaustedError("out"))),
        ("b", _Op("b", RuntimeError("nope"))),
    ])
    with pytest.raises(ProviderExhaustedError):
        fb.complete_json("s", "u")


# --- factory wiring ---------------------------------------------------------
def test_make_provider_builds_chain_from_list():
    from prospector.config import load_config
    from prospector.retrieval import DiskCache, make_provider
    cfg = load_config()
    cfg.retrieval.provider = ["fixture", "fixture"]
    cfg.retrieval.cache = False
    prov = make_provider(cfg, fixtures={})
    assert isinstance(prov, FallbackSearchProvider)


def test_make_operator_single_string_is_not_wrapped():
    from prospector.config import load_config
    from prospector.operator import MockOperator, make_operator
    cfg = load_config()
    cfg.operator = "mock"
    assert isinstance(make_operator(cfg), MockOperator)
