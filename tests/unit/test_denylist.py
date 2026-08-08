"""Tests for the exhausted-family denylist (G3) — prospector.denylist.

The denylist reads only the store INDEX rows (so it can run on every generation
call) and clusters kills into families whose gate is one of FAMILY_GATES. A
family with a real PASS survivor is dropped, because a survivor proves the
shape is not categorically dead. Cache is honoured as long as fewer than
`refresh_every_kills` new kills have accumulated.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from prospector.denylist import (
    FAMILY_GATES,
    build_families,
    denial_directive,
    refresh_families,
)
from prospector.models import Decision

# Token phrases designed to give the dedup Jaccard a strong shared signal.
# Stopword-filtered by dedup._content_tokens — only significant (>2 char,
# non-stopword) words survive.
FAMILY_TOKENS_TITLE = "Probate clear-out agent"
FAMILY_TOKENS_ONE_LINER = "Local clearance broker for bereaved families"
FAMILY_NEWEST_TITLE = "Probate clear-out agent 2026 edition"   # newest -> example
PASS_TITLE = "Probate clear-out survival playbook"             # shares tokens -> excludes family
UNRELATED_TITLE = "The Vet's Fee Extractor"
UNRELATED_ONE_LINER = "Surgical invoicing auditor for vet practices"


class FakeStore:
    """Mimics prospector.store.Store's .all(decision=None) just enough for the
    denylist. Real Store.all filters by decision string (e.g. 'kill'/'pass');
    we mirror that contract."""

    def __init__(self, kills: list[dict] | None = None,
                 passes: list[dict] | None = None,
                 raise_on_all: bool = False):
        self._kills = kills or []
        self._passes = passes or []
        self._raise = raise_on_all

    def all(self, decision: str | None = None) -> list[dict]:
        if self._raise:
            raise RuntimeError("simulated store outage")
        if decision == Decision.KILL.value:
            return list(self._kills)
        if decision == Decision.PASS.value:
            return list(self._passes)
        return list(self._kills) + list(self._passes)


def _kill_row(title: str, one_liner: str, gate: str, ts: str) -> dict:
    return {
        "title": title,
        "one_liner": one_liner,
        "gate_fired": gate,
        "created_at": ts,
        "decision": Decision.KILL.value,
    }


def _pass_row(title: str, one_liner: str, ts: str) -> dict:
    return {
        "title": title,
        "one_liner": one_liner,
        "gate_fired": "",
        "created_at": ts,
        "decision": Decision.PASS.value,
    }


def test_family_formed_from_three_similar_kills():
    """Three value_durability kills sharing a token family + 2 unrelated
    single kills -> exactly 1 family; example is the NEWEST member; label
    contains at least one of the family tokens."""
    kills = [
        _kill_row(FAMILY_NEWEST_TITLE, FAMILY_TOKENS_ONE_LINER, "value_durability",
                  "2026-08-03T00:00:00"),
        _kill_row(FAMILY_TOKENS_TITLE, FAMILY_TOKENS_ONE_LINER, "value_durability",
                  "2026-08-02T00:00:00"),
        _kill_row("Probate property clear-out agent", FAMILY_TOKENS_ONE_LINER,
                  "value_durability", "2026-08-01T00:00:00"),
        _kill_row(UNRELATED_TITLE, UNRELATED_ONE_LINER, "value_durability",
                  "2026-07-30T00:00:00"),
        _kill_row("Tradie time-capture agent", "Job-hour reconciliation",
                  "value_durability", "2026-07-29T00:00:00"),
    ]
    families = build_families(kills, pass_rows=[])
    assert len(families) == 1
    fam = families[0]
    assert fam["kills"] == 3
    assert fam["example"] == FAMILY_NEWEST_TITLE
    # The label is the top-4 most-frequent content tokens; at least one of the
    # family tokens ("probate", "clear", "agent", "local", "clearance", "broker",
    # "bereaved", "families") must appear.
    label_tokens = set(fam["label"].split())
    family_token_pool = {"probate", "clear", "agent", "local", "clearance",
                         "broker", "bereaved", "families"}
    assert label_tokens & family_token_pool, (
        f"family label {label_tokens!r} has no tokens from {family_token_pool!r}"
    )


def test_pass_survivor_excludes_family():
    """The same three kills but with a PASS row whose tokens overlap the seed
    -> no families qualify (a family with a survivor is not exhausted)."""
    kills = [
        _kill_row(FAMILY_NEWEST_TITLE, FAMILY_TOKENS_ONE_LINER, "value_durability",
                  "2026-08-03T00:00:00"),
        _kill_row(FAMILY_TOKENS_TITLE, FAMILY_TOKENS_ONE_LINER, "value_durability",
                  "2026-08-02T00:00:00"),
        _kill_row("Probate property clear-out agent", FAMILY_TOKENS_ONE_LINER,
                  "value_durability", "2026-08-01T00:00:00"),
    ]
    passes = [
        _pass_row(PASS_TITLE, FAMILY_TOKENS_ONE_LINER, "2026-08-04T00:00:00"),
    ]
    assert build_families(kills, pass_rows=passes) == []


def test_non_family_gates_ignored():
    """Three similar kills with gate_fired='min_composite' (NOT in FAMILY_GATES)
    -> no families (only structural-dead gates count)."""
    kills = [
        _kill_row(FAMILY_NEWEST_TITLE, FAMILY_TOKENS_ONE_LINER, "min_composite",
                  "2026-08-03T00:00:00"),
        _kill_row(FAMILY_TOKENS_TITLE, FAMILY_TOKENS_ONE_LINER, "min_composite",
                  "2026-08-02T00:00:00"),
        _kill_row("Probate property clear-out agent", FAMILY_TOKENS_ONE_LINER,
                  "min_composite", "2026-08-01T00:00:00"),
    ]
    assert "min_composite" not in FAMILY_GATES
    assert build_families(kills, pass_rows=[]) == []


def test_denial_directive_gated(tmp_path):
    """With the gate ON and qualifying kills, the directive names the family
    and includes the example title. With the gate OFF, returns ""."""
    store = FakeStore(
        kills=[
            _kill_row(FAMILY_NEWEST_TITLE, FAMILY_TOKENS_ONE_LINER,
                      "value_durability", "2026-08-03T00:00:00"),
            _kill_row(FAMILY_TOKENS_TITLE, FAMILY_TOKENS_ONE_LINER,
                      "value_durability", "2026-08-02T00:00:00"),
            _kill_row("Probate property clear-out agent", FAMILY_TOKENS_ONE_LINER,
                      "value_durability", "2026-08-01T00:00:00"),
        ],
        passes=[],
    )
    cfg = SimpleNamespace(
        generation={"denylist": {"enabled": True, "min_family_size": 3,
                                 "refresh_every_kills": 25, "max_families": 12}},
        store_dir=str(tmp_path),
    )
    directive = denial_directive(store, cfg)
    assert "EXHAUSTED FAMILIES" in directive
    assert FAMILY_NEWEST_TITLE in directive
    assert "Do NOT propose any idea" in directive

    # Gate OFF -> empty.
    cfg_off = SimpleNamespace(
        generation={"denylist": {"enabled": False, "min_family_size": 3,
                                 "refresh_every_kills": 25, "max_families": 12}},
        store_dir=str(tmp_path),
    )
    assert denial_directive(store, cfg_off) == ""


def test_cache_watermark(tmp_path, monkeypatch):
    """Cache is honoured until `refresh_every_kills` new kills accumulate, then
    rebuilt. Pin both behaviours against the same on-disk cache file.

    The env override is cleared so the cache resolves through cfg.store_dir, the
    path production actually uses."""
    monkeypatch.delenv("PROSPECTOR_GENERATION_ARTIFACT_DIR", raising=False)
    cache_path = tmp_path / "exhausted_families.json"
    cfg = SimpleNamespace(
        generation={"denylist": {"enabled": True, "min_family_size": 3,
                                 "refresh_every_kills": 25, "max_families": 12}},
        store_dir=str(tmp_path),
    )

    # First call: 3 qualifying kills, family is built and cached.
    store_first = FakeStore(kills=[
        _kill_row(FAMILY_NEWEST_TITLE, FAMILY_TOKENS_ONE_LINER, "value_durability",
                  "2026-08-03T00:00:00"),
        _kill_row(FAMILY_TOKENS_TITLE, FAMILY_TOKENS_ONE_LINER, "value_durability",
                  "2026-08-02T00:00:00"),
        _kill_row("Probate property clear-out agent", FAMILY_TOKENS_ONE_LINER,
                  "value_durability", "2026-08-01T00:00:00"),
    ])
    denial_directive(store_first, cfg)
    assert cache_path.exists()
    cache_after_first = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache_after_first["built_at_kill_count"] == 3
    assert len(cache_after_first["families"]) == 1

    # Second call: 4 kills (< 25 new) — cache is honoured, families unchanged.
    store_second = FakeStore(kills=[
        _kill_row(FAMILY_NEWEST_TITLE, FAMILY_TOKENS_ONE_LINER, "value_durability",
                  "2026-08-03T00:00:00"),
        _kill_row(FAMILY_TOKENS_TITLE, FAMILY_TOKENS_ONE_LINER, "value_durability",
                  "2026-08-02T00:00:00"),
        _kill_row("Probate property clear-out agent", FAMILY_TOKENS_ONE_LINER,
                  "value_durability", "2026-08-01T00:00:00"),
        _kill_row("Probate locker clear-out agent", FAMILY_TOKENS_ONE_LINER,
                  "value_durability", "2026-07-31T00:00:00"),  # +1, but <25
    ])
    denial_directive(store_second, cfg)
    cache_after_second = json.loads(cache_path.read_text(encoding="utf-8"))
    # Watermark not crossed -> same payload as before (built_at_kill_count 3).
    assert cache_after_second["built_at_kill_count"] == 3
    assert len(cache_after_second["families"]) == 1

    # Third call: bump kills by 30 (>= 25 new) -> cache rebuilt, watermark updated.
    many_kills = [
        _kill_row(f"Probate clear-out agent variant {i}",
                  FAMILY_TOKENS_ONE_LINER, "value_durability",
                  f"2026-09-{i + 1:02d}T00:00:00")
        for i in range(30)
    ]
    store_third = FakeStore(kills=many_kills)
    denial_directive(store_third, cfg)
    cache_after_third = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache_after_third["built_at_kill_count"] == 30
    # The 30 similar kills do form a family; the cache now reflects the rebuild.
    assert len(cache_after_third["families"]) >= 1


def test_refresh_never_raises_into_generation(tmp_path):
    """A store whose .all raises must fail open — denial_directive returns ''
    rather than propagating the exception."""
    cfg = SimpleNamespace(
        generation={"denylist": {"enabled": True, "min_family_size": 3,
                                 "refresh_every_kills": 25, "max_families": 12}},
        store_dir=str(tmp_path),
    )
    store = FakeStore(raise_on_all=True)
    # refresh_families swallows; returns []. denial_directive -> "".
    assert refresh_families(store, cfg) == []
    assert denial_directive(store, cfg) == ""


def test_denial_directive_max_families_cap(tmp_path):
    """max_families caps the number of family bullets in the directive so the
    prompt budget is bounded."""
    # Five distinct families, each with exactly 3 kills.
    base_titles = [
        ("Probate", "clearance", "broker", "service"),
        ("Vet", "invoice", "audit", "agent"),
        ("Builder", "warranty", "review", "desk"),
        ("Tradie", "time", "capture", "tracker"),
        ("Notary", "bond", "filing", "service"),
    ]
    kills: list[dict] = []
    for i, (w1, w2, w3, w4) in enumerate(base_titles):
        for j in range(3):
            kills.append(_kill_row(
                f"{w1} {w2} {w3} {w4} v{j}",
                f"{w1} {w2} {w3} {w4} service for local clients",
                "value_durability",
                f"2026-09-{i + 1:02d}T{j:02d}:00:00",
            ))

    cfg = SimpleNamespace(
        generation={"denylist": {"enabled": True, "min_family_size": 3,
                                 "refresh_every_kills": 25, "max_families": 2}},
        store_dir=str(tmp_path),
    )
    directive = denial_directive(FakeStore(kills=kills), cfg)
    # Count bullet lines (start with "- ").
    bullets = [ln for ln in directive.splitlines() if ln.startswith("- ")]
    assert len(bullets) == 2
