"""S5 — the cross-tick retrieval cache (`docs/COMMERCIAL_READINESS_PROGRAM.md` §2.5).

The cache itself is NOT new: `DiskCache` (`prospector/retrieval.py`) has always been a
persistent, content-addressed, TTL'd store under `store/_cache/`, wired by
`make_provider` and gated by `retrieval.cache` / `retrieval.cache_ttl_s`. S5's premise
that "retrieval.py caching is breaker state, not a persistent result cache" is refuted
by `test_cache_survives_the_process_that_wrote_it` below.

What these tests pin is the hardening S5 requires of it, given a LIVE daemon sharing the
directory:
  - a hit serves without touching the provider, ACROSS instances (the cross-tick property)
  - a miss delegates exactly once and persists the result
  - TTL is honoured on the RECORDED fetch time, not only on a forgeable mtime
  - a torn / malformed entry is a MISS, never an exception on the grounding path
  - `retrieval.cache: false` bypasses the cache entirely (clean A/B)
  - the cache directory is injectable, so a test can never write to production store/

Zero network: every test drives a counting stub provider or the fixture provider.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import prospector.retrieval as R
from prospector.config import load_config
from prospector.models import Source
from prospector.retrieval import DiskCache, SearchProvider


class _CountingProvider(SearchProvider):
    """Inner provider that records how many live searches it actually served."""

    def __init__(self, text: str = "evidence"):
        self.calls = 0
        self.text = text

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        self.calls += 1
        return [Source(source_id="s1", url="http://example.test", text=self.text)]


def _entry_path(cache: DiskCache, query: str = "q") -> Path:
    return cache._path(query, 4, 1500)


def _rewrite(p: Path, obj) -> None:
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj))


# --- hit / miss --------------------------------------------------------------

def test_miss_delegates_once_then_hit_serves_without_the_provider(tmp_path):
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)

    first = cache.search("q")
    assert inner.calls == 1, "a cold key must reach the provider"
    second = cache.search("q")

    assert inner.calls == 1, "a warm key must NOT reach the provider"
    assert [s.to_dict() for s in second] == [s.to_dict() for s in first], (
        "the cache must return what the provider returned, byte for byte")


def test_distinct_queries_do_not_collide(tmp_path):
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    cache.search("query one")
    cache.search("query two")
    assert inner.calls == 2, "two different queries must not share a cache entry"


def test_cache_survives_the_process_that_wrote_it(tmp_path):
    """THE cross-tick property: a second, independent DiskCache over the same dir hits.

    This is what S5 asks for, and it already held — the entry is on disk, not in
    process memory, so a later tick (a different process entirely) is served from it.
    """
    writer = _CountingProvider()
    DiskCache(writer, cache_dir=tmp_path, ttl_s=3600).search("q")
    assert writer.calls == 1

    # A brand-new cache object over the same directory stands in for the next tick.
    reader_inner = _CountingProvider()
    later = DiskCache(reader_inner, cache_dir=tmp_path, ttl_s=3600)
    results = later.search("q")

    assert reader_inner.calls == 0, "a later tick must be served from disk"
    assert [s.url for s in results] == ["http://example.test"]


def test_empty_results_are_not_cached(tmp_path):
    """A transient outage returning [] must not poison the key for the whole TTL."""
    class _Empty(SearchProvider):
        def __init__(self):
            self.calls = 0

        def search(self, query, k=4, max_chars=1500):
            self.calls += 1
            return []

    inner = _Empty()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    cache.search("q")
    cache.search("q")
    assert inner.calls == 2, "an empty result must stay uncached"


# --- TTL ---------------------------------------------------------------------

def test_ttl_expiry_on_the_recorded_fetch_time(tmp_path):
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    cache.search("q")
    p = _entry_path(cache)

    entry = json.loads(p.read_text())
    assert entry["fetched_at"] == pytest.approx(time.time(), abs=60), (
        "the entry must record WHEN it was fetched")

    # Age the recorded fetch time past the TTL while leaving mtime untouched (fresh).
    entry["fetched_at"] = time.time() - 7200
    _rewrite(p, entry)
    cache.search("q")

    assert inner.calls == 2, "an entry past its TTL must be re-fetched, not served"


def test_a_forged_mtime_cannot_revive_a_stale_entry(tmp_path):
    """A restore of store/ (`scripts/backup_store.py`) resets mtime to now.

    If freshness trusted mtime alone, that would silently serve months-old grounding
    as current evidence — a correctness hazard for a source-or-die engine.
    """
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    cache.search("q")
    p = _entry_path(cache)

    entry = json.loads(p.read_text())
    entry["fetched_at"] = time.time() - 90 * 86400      # fetched three months ago
    _rewrite(p, entry)
    now = time.time()
    os.utime(p, (now, now))                             # "restored" a second ago

    cache.search("q")
    assert inner.calls == 2, "the recorded fetch time must outrank a forged mtime"


def test_ttl_expiry_on_mtime_for_a_legacy_entry(tmp_path):
    """v1 entries (a bare JSON list) carry no timestamp — mtime must still expire them."""
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    p = _entry_path(cache)
    _rewrite(p, [Source(source_id="s1", url="http://old.test", text="stale").to_dict()])
    old = time.time() - 7200
    os.utime(p, (old, old))

    cache.search("q")
    assert inner.calls == 1, "a stale legacy entry must be re-fetched"


def test_legacy_entry_is_still_served_while_fresh(tmp_path):
    """The 15k+ v1 entries already on disk must not be invalidated by the new format."""
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    p = _entry_path(cache)
    _rewrite(p, [Source(source_id="s1", url="http://legacy.test", text="old format").to_dict()])

    results = cache.search("q")
    assert inner.calls == 0, "a fresh v1 entry must still be a hit"
    assert [s.url for s in results] == ["http://legacy.test"]


def test_ttl_zero_never_expires(tmp_path):
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=0)
    cache.search("q")
    p = _entry_path(cache)
    entry = json.loads(p.read_text())
    entry["fetched_at"] = time.time() - 10_000_000
    _rewrite(p, entry)
    old = time.time() - 10_000_000
    os.utime(p, (old, old))

    cache.search("q")
    assert inner.calls == 1, "ttl_s=0 disables expiry entirely"


# --- torn / malformed entries ------------------------------------------------

@pytest.mark.parametrize("corrupt", [
    pytest.param('[{"source_id": "s1", "url": "http://e.test", "te', id="truncated_json"),
    pytest.param("", id="empty_file"),
    pytest.param('{"v": 2, "fetched_at": 99999999999, "sources": "not-a-list"}', id="bad_envelope"),
    pytest.param('{"v": 2, "fetched_at": 99999999999, "sources": [{"bogus": 1}]}', id="bad_source"),
    pytest.param('{"v": 2, "fetched_at": 99999999999, "sources": ["not-a-dict"]}', id="scalar_source"),
    pytest.param('{"v": 2, "fetched_at": 99999999999}', id="no_sources_key"),
])
def test_a_torn_entry_is_a_miss_never_a_crash(tmp_path, corrupt):
    """A half-written or garbled entry must cost one re-fetch, not a failed verdict.

    The daemon writes this directory while other runs read it, so a reader WILL meet
    a damaged file eventually; raising here would fail grounding for a candidate that
    a single re-fetch answers.
    """
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    p = _entry_path(cache)
    p.write_text(corrupt)

    results = cache.search("q")                    # must not raise

    assert inner.calls == 1, "a corrupt entry must be treated as a miss"
    assert [s.url for s in results] == ["http://example.test"]
    # ...and the miss must have healed the entry.
    healed = json.loads(p.read_text())
    assert healed["sources"][0]["url"] == "http://example.test"
    cache.search("q")
    assert inner.calls == 1, "the re-written entry must serve the next read"


def test_writes_are_atomic_and_leave_no_debris(tmp_path):
    """tmp+rename: a reader sees the old entry or the new one, never a prefix."""
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)
    cache.search("q")

    leftovers = [f.name for f in tmp_path.iterdir() if f.suffix == ".tmp"]
    assert leftovers == [], f"temp files leaked into the cache dir: {leftovers}"
    entries = [f for f in tmp_path.iterdir() if f.suffix == ".json"]
    assert len(entries) == 1
    json.loads(entries[0].read_text())             # a published entry is always parseable


def test_an_unwritable_cache_dir_does_not_break_the_search(tmp_path, monkeypatch):
    """Cache write failure is a performance event, never a grounding failure."""
    inner = _CountingProvider()
    cache = DiskCache(inner, cache_dir=tmp_path, ttl_s=3600)

    def _boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(R.tempfile, "mkstemp", _boom)
    results = cache.search("q")                    # must not raise
    assert [s.url for s in results] == ["http://example.test"]


# --- config: bypass flag + injectable directory ------------------------------

def _fixture_cfg():
    cfg = load_config()
    cfg.retrieval.provider = ["fixture"]
    return cfg


def test_cache_false_bypasses_the_cache_entirely(monkeypatch, tmp_path):
    """The A/B switch: `retrieval.cache: false` must leave NO cache in the chain."""
    monkeypatch.setattr(R, "CACHE_DIR", tmp_path / "must-not-exist")
    cfg = _fixture_cfg()
    cfg.retrieval.cache = False

    prov = R.make_provider(cfg, fixtures={})

    assert not isinstance(prov, DiskCache), "cache: false must not wrap a DiskCache"
    assert not (tmp_path / "must-not-exist").exists(), (
        "a bypassed cache must not even create its directory")


def test_cache_true_wraps_and_takes_ttl_and_dir_from_config(monkeypatch, tmp_path):
    """Also the regression for the import-time path binding.

    `cache_dir` used to default to the module constant IN THE SIGNATURE, so it was
    frozen at import and monkeypatching `CACHE_DIR` could not redirect it — the exact
    shape that has written test data into production store/ before.
    """
    monkeypatch.setattr(R, "CACHE_DIR", tmp_path / "cache")
    cfg = _fixture_cfg()
    cfg.retrieval.cache = True
    cfg.retrieval.cache_ttl_s = 999

    # A LIVE provider, not the fixture one. `_pinned` is `fixtures is not None or "fixture"
    # in names`, and a pinned chain deliberately bypasses DiskCache (see the test below), so
    # asserting the cache wrapping on a fixture config now asserts the opposite of the truth.
    cfg.retrieval.provider = ["ddg"]

    prov = R.make_provider(cfg)

    assert isinstance(prov, DiskCache)
    assert prov.ttl_s == 999, "TTL comes from config, never a hardcoded literal"
    assert prov.cache_dir == tmp_path / "cache", (
        "cache_dir must resolve CACHE_DIR at construction, not at import")


def test_pinned_run_bypasses_the_cache_entirely(monkeypatch, tmp_path):
    """A fixture-pinned run must not read DiskCache, however `cache: true` is configured.

    `store/_cache` is full of entries written by earlier UNPINNED live runs under the SAME
    stable golden query strings — the promotion gate asks the same questions every time. A
    cache hit would serve real web passages to a run whose whole purpose is that the brain
    sees only the fixture, and it would do so invisibly: the passages look fine, they are
    simply not the held-constant evidence the score is attributed to."""
    monkeypatch.setattr(R, "CACHE_DIR", tmp_path / "cache")
    cfg = _fixture_cfg()
    cfg.retrieval.cache = True

    # Pinned BY THE DICT, on a config whose provider is live.
    cfg.retrieval.provider = ["ddg"]
    assert not isinstance(R.make_provider(cfg, fixtures={}), DiskCache)
    # ...while the identical config UNPINNED still caches, so this is the pin's doing and
    # not `cache: true` being ignored.
    assert isinstance(R.make_provider(cfg), DiskCache)
    # Pinned BY THE CONFIG NAME, with no dict passed at all — the second half of `_pinned`.
    cfg.retrieval.provider = ["fixture"]
    assert not isinstance(R.make_provider(cfg), DiskCache)


def test_config_declares_the_ttl_and_the_bypass_flag():
    """Params live in config: both S5 knobs must exist with real defaults."""
    cfg = load_config()
    assert isinstance(cfg.retrieval.cache, bool)
    assert isinstance(cfg.retrieval.cache_ttl_s, int) and cfg.retrieval.cache_ttl_s > 0
    text = (Path(__file__).resolve().parents[2] / "config.yaml").read_text()
    assert "cache_ttl_s:" in text and "cache:" in text
