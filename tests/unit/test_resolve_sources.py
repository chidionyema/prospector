"""resolve_sources: parallel URL validation (latency win, behaviour-neutral).

Resolving result URLs concurrently must produce EXACTLY what serial resolution did —
same kept set, same order, dead/fabricated URLs dropped — only faster."""
from __future__ import annotations

import prospector.retrieval as R


def _patch_resolve(monkeypatch, alive: set[str]):
    """Stub _resolve so no real network is hit: a URL 'resolves' iff it's in `alive`."""
    monkeypatch.setattr(R, "_resolve", lambda url, timeout=5.0: (url if url in alive else None))


def test_keeps_only_resolvable_urls_in_order(monkeypatch):
    items = [
        {"url": "https://a.com", "text": "A", "published_at": "2026-01-01"},
        {"url": "https://dead.com", "text": "B"},      # will not resolve -> dropped
        {"url": "https://c.com", "text": "C"},
    ]
    _patch_resolve(monkeypatch, {"https://a.com", "https://c.com"})
    out = R.resolve_sources(items, query="q", max_chars=1500, k=4)
    assert [s.url for s in out] == ["https://a.com", "https://c.com"]   # dead dropped, order kept


def test_respects_k_limit(monkeypatch):
    items = [{"url": f"https://s{i}.com", "text": "t"} for i in range(6)]
    _patch_resolve(monkeypatch, {f"https://s{i}.com" for i in range(6)})
    out = R.resolve_sources(items, query="q", max_chars=1500, k=2)
    assert len(out) == 2


def test_empty_and_urlless_items(monkeypatch):
    _patch_resolve(monkeypatch, set())
    assert R.resolve_sources([], query="q", max_chars=1500, k=4) == []
    assert R.resolve_sources([{"text": "no url"}], query="q", max_chars=1500, k=4) == []


def test_truncates_passage_to_max_chars(monkeypatch):
    items = [{"url": "https://a.com", "text": "x" * 5000}]
    _patch_resolve(monkeypatch, {"https://a.com"})
    out = R.resolve_sources(items, query="q", max_chars=100, k=4)
    assert len(out) == 1 and len(out[0].text) == 100
