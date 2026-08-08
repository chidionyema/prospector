"""Tests for the G2 incumbent-landscape directive (prospector.landscape).

`_format_brief` is a pure function — exercised directly. `incumbent_brief` is exercised
through its real gate, topic derivation, cache logic and failure-isolation behaviour,
with the network-bound `_fetch_brief` stubbed at the module boundary. Every test that
goes through the production path pins `cfg.store_dir` rather than the conftest fence
so a real cache write is observable in tmp_path."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from prospector import landscape
from prospector.landscape import (
    _DEFAULT_PROVIDERS,
    _format_brief,
    _providers,
    _topic,
    incumbent_brief,
)


def _src(url: str, text: str):
    return SimpleNamespace(url=url, text=text)


# ----- _topic ----------------------------------------------------------------


def test_sector_beats_signal_for_topic():
    """When sector is a clean noun phrase it wins over a long signal."""
    assert _topic("some long signal text here", "veterinary") == "veterinary"


def test_signal_only_caps_at_twelve_words():
    """A 30-word signal collapses to the first 12 words, stripped of run-on whitespace."""
    assert len(_topic("word " * 30, "").split()) == 12


def test_empty_inputs_return_empty():
    """No signal, no sector, no audience => empty topic => caller skips the retrieval."""
    assert _topic("", "") == ""
    assert _topic("   ", "  ") == ""
    assert _topic("", "", "") == ""


def test_audience_is_the_blue_sky_fallback():
    """Rung 3: with no signal and no sector, the audience persona slug becomes the topic.

    This is the daemon's path and the reason the rung exists —
    `scheduler/run_scheduled.py:724` calls `run_signal("", ...)`, so without this the
    brief would be inert on the majority of all generation."""
    assert _topic("", "", "ecommerce_seller") == "ecommerce seller"
    assert _topic("", "", "manual_tradesperson") == "manual tradesperson"


def test_audience_never_outranks_a_real_signal():
    """The audience is the LAST rung: a sector or a signal always wins, so an on-demand
    vet run never degrades to a buyer-level topic when it has an idea-level one."""
    assert _topic("", "veterinary", "ecommerce_seller") == "veterinary"
    assert _topic("vet invoicing pain", "", "ecommerce_seller") == "vet invoicing pain"


# ----- _format_brief ----------------------------------------------------------


def test_format_brief_dedupes_and_caps():
    """Five sources, two share a URL, max_entries=3 => exactly 3 lines, no 'www.',
    and the directive strings the unit test is asked to pin are present."""
    sources = [
        _src("https://www.acme.com/a", "Acme does the thing"),
        _src("https://acme.com/b", "Acme again, deduped by host"),  # dedup on url, not host
        _src("https://bravo.io/x", "Bravo is different"),
        _src("https://charlie.com/y", "Charlie is also different"),
        _src("https://delta.com/z", "Delta is here too"),
    ]
    out = _format_brief(sources, max_entries=3, max_chars=220)
    lines = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(lines) == 3
    assert "www." not in out
    assert "CONTEXT, not evidence" in out
    assert "incumbency gate's next kill" in out


def test_format_brief_dedupes_by_url_not_host():
    """Two URLs sharing a host are TWO sources, not one — dedup is on url, not host."""
    sources = [
        _src("https://www.acme.com/a", "Acme does the thing"),
        _src("https://acme.com/b", "Acme also does this other thing"),
    ]
    out = _format_brief(sources, max_entries=8)
    lines = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(lines) == 2


def test_format_brief_empty_sources_returns_empty():
    """No sources => no directive. A source with empty text is also skipped."""
    assert _format_brief([]) == ""
    assert _format_brief([_src("https://acme.com/x", "")]) == ""
    assert _format_brief([_src("", "some text")]) == ""


def test_format_brief_truncates_long_text():
    """Snippet longer than max_chars is truncated, not echoed in full."""
    long = "x" * 1000
    out = _format_brief([_src("https://acme.com/x", long)], max_chars=50)
    # The truncated line is exactly 50 chars of 'x' followed by "rstrip".
    assert any(ln.startswith("- acme.com: ") and len(ln) < 50 + len("- acme.com: ") + 50
               for ln in out.splitlines())


# ----- _providers -------------------------------------------------------------


def test_providers_never_includes_claude_cli():
    """claude_cli is always dropped (with a warning) so it cannot leak into the moat chain."""
    # Mixed list — claude_cli dropped, others survive.
    assert _providers({"providers": ["ddg", "claude_cli"]}) == ["ddg"]
    # Pure claude_cli falls back to the default chain.
    assert _providers({"providers": ["claude_cli"]}) == list(_DEFAULT_PROVIDERS)
    # Missing key falls back to the default chain.
    assert _providers({}) == list(_DEFAULT_PROVIDERS)


def test_providers_strips_whitespace_and_empties():
    """Whitespace-only and empty entries are dropped silently."""
    assert _providers({"providers": ["", "  ", "ddg"]}) == ["ddg"]


# ----- incumbent_brief gate / topic ------------------------------------------


def test_gate_off_returns_empty(monkeypatch):
    """When generation.incumbent_seed is absent the function never fetches."""
    calls = {"n": 0}

    def _spy(cfg, icfg, topic):
        calls["n"] += 1
        return "BRIEF"

    monkeypatch.setattr(landscape, "_fetch_brief", _spy)
    cfg = SimpleNamespace(generation={}, store_dir="/tmp/never")
    assert incumbent_brief(cfg, signal_text="x", sector="") == ""
    assert calls["n"] == 0


def test_no_topic_no_call(monkeypatch):
    """Empty signal AND empty sector => no brief and zero fetches."""
    calls = {"n": 0}
    monkeypatch.setattr(landscape, "_fetch_brief",
                        lambda cfg, icfg, topic: (calls.__setitem__("n", calls["n"] + 1) or ""))
    cfg = SimpleNamespace(
        generation={"incumbent_seed": {"enabled": True}},
        store_dir="/tmp/never",
    )
    assert incumbent_brief(cfg, signal_text="", sector="") == ""
    assert calls["n"] == 0


# ----- incumbent_brief cache --------------------------------------------------


def test_cache_hit_avoids_second_fetch(tmp_path, monkeypatch):
    """Two calls with the same topic share one fetch and write one cache file."""
    monkeypatch.delenv("PROSPECTOR_GENERATION_ARTIFACT_DIR", raising=False)
    calls = {"n": 0}

    def _stub(cfg, icfg, topic):
        calls["n"] += 1
        return "BRIEF"

    monkeypatch.setattr(landscape, "_fetch_brief", _stub)
    cfg = SimpleNamespace(
        generation={"incumbent_seed": {"enabled": True}},
        store_dir=str(tmp_path),
    )
    a = incumbent_brief(cfg, sector="veterinary")
    b = incumbent_brief(cfg, sector="veterinary")
    assert a == b == "BRIEF"
    assert calls["n"] == 1
    assert (tmp_path / "incumbent_cache.json").exists()


def test_expired_cache_refetches(tmp_path, monkeypatch):
    """A cache entry older than cache_ttl_s must be re-fetched."""
    monkeypatch.delenv("PROSPECTOR_GENERATION_ARTIFACT_DIR", raising=False)
    calls = {"n": 0}
    monkeypatch.setattr(landscape, "_fetch_brief",
                        lambda cfg, icfg, topic: (calls.__setitem__("n", calls["n"] + 1) or ""))

    # Hand-write a stale cache entry: fetched_at is 10_000s ago, ttl is 1s.
    stale = {
        landscape._cache_key("veterinary", ""): {
            "fetched_at": time.time() - 10_000,
            "topic": "veterinary",
            "brief": "STALE",
        }
    }
    cache_path = tmp_path / "incumbent_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(stale), encoding="utf-8")

    cfg = SimpleNamespace(
        generation={"incumbent_seed": {"enabled": True, "cache_ttl_s": 1}},
        store_dir=str(tmp_path),
    )
    # Force the path resolution to come from cfg.store_dir, not the env override.
    out = incumbent_brief(cfg, sector="veterinary")
    assert calls["n"] == 1   # ran the fetch (the stale entry was expired)
    assert out == ""         # the stub returns ""


def test_never_raises(monkeypatch, tmp_path):
    """A raising fetch must be swallowed by the outer try/except — no propagation."""
    monkeypatch.delenv("PROSPECTOR_GENERATION_ARTIFACT_DIR", raising=False)
    monkeypatch.setattr(landscape, "_fetch_brief",
                        lambda cfg, icfg, topic: (_ for _ in ()).throw(RuntimeError("boom")))
    cfg = SimpleNamespace(
        generation={"incumbent_seed": {"enabled": True}},
        store_dir=str(tmp_path),
    )
    assert incumbent_brief(cfg, sector="veterinary") == ""


def test_corrupt_cache_is_a_cold_cache(tmp_path, monkeypatch):
    """An unparseable cache file is treated as empty — fetch runs, valid file is written."""
    monkeypatch.delenv("PROSPECTOR_GENERATION_ARTIFACT_DIR", raising=False)
    cache_path = tmp_path / "incumbent_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("not json", encoding="utf-8")

    monkeypatch.setattr(landscape, "_fetch_brief", lambda cfg, icfg, topic: "FRESH")
    cfg = SimpleNamespace(
        generation={"incumbent_seed": {"enabled": True}},
        store_dir=str(tmp_path),
    )
    out = incumbent_brief(cfg, sector="veterinary")
    assert out == "FRESH"
    # The cold-cache path rewrote the file as valid JSON.
    parsed = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "veterinary" in str(parsed)  # the key uses (topic, "") tuple
