"""`market` threads end-to-end: Candidate -> dossier JSON -> SQLite index (spec D2).

The load-bearing test here is `test_market_participates_in_candidate_id_only_when_set`:
without that behaviour, replicating a PASS into another market produces an identical
candidate_id and store.save() silently OVERWRITES the source dossier.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from prospector.config import load_config
from prospector.models import Candidate, Decision, Dossier
from prospector.store import Store

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_DB = REPO_ROOT / "store" / "prospector.db"


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------

def test_market_defaults_empty_and_round_trips():
    c = Candidate(title="T", one_liner="O")
    assert c.market == ""
    assert Candidate.from_dict(c.to_dict()).market == ""

    c2 = Candidate(title="T", one_liner="O", market="us-tx")
    assert Candidate.from_dict(c2.to_dict()).market == "us-tx"


def test_market_participates_in_candidate_id_only_when_set():
    """The collision trap: a cross-market clone must NOT reuse the source's id, while
    every pre-Epic-D / default-market id must stay byte-identical."""
    plain = Candidate(title="Mobile notary bond", one_liner="Bond filing service")
    uk = Candidate(title="Mobile notary bond", one_liner="Bond filing service", market="uk")
    us = Candidate(title="Mobile notary bond", one_liner="Bond filing service", market="us")

    assert uk.candidate_id != plain.candidate_id
    assert us.candidate_id != uk.candidate_id
    assert len({plain.candidate_id, uk.candidate_id, us.candidate_id}) == 3


def test_unmarked_candidate_id_is_unchanged_by_epic_d():
    """Pinned against the pre-Epic-D derivation (sha1 of 'title|one_liner') so a future
    edit to the id scheme cannot silently orphan the 1,000+ stored dossiers."""
    import hashlib
    title, one_liner = "Retiree Garden Harvest Share", "Weekly produce box from retiree gardens"
    expected = hashlib.sha1(f"{title}|{one_liner}".encode()).hexdigest()[:16]
    assert Candidate(title=title, one_liner=one_liner).candidate_id == expected


def test_explicit_candidate_id_always_wins():
    c = Candidate(title="T", one_liner="O", market="us", candidate_id="pinned")
    assert c.candidate_id == "pinned"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _cfg(tmp_path):
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    return cfg


def _dossier(market: str, title: str = "T") -> Dossier:
    return Dossier(candidate=Candidate(title=title, one_liner="O", market=market),
                   decision=Decision.PASS, created_at="2026-07-30T12:00:00Z")


def test_market_persists_to_json_and_index(tmp_path):
    store = Store(_cfg(tmp_path))
    d = _dossier("us-tx")
    path = store.save(d)

    assert '"market": "us-tx"' in path.read_text()
    row = sqlite3.connect(str(store.db)).execute(
        "SELECT market FROM dossiers WHERE candidate_id = ?",
        (d.candidate.candidate_id,)).fetchone()
    assert row[0] == "us-tx"


def test_catalogue_titles_returns_market_pairs(tmp_path):
    store = Store(_cfg(tmp_path))
    store.save(_dossier("uk", title="UK idea"))
    store.save(_dossier("us", title="US idea"))

    pairs = store.catalogue_titles()
    assert sorted(pairs) == [("uk", "UK idea O"), ("us", "US idea O")]


def test_markets_present_counts(tmp_path):
    store = Store(_cfg(tmp_path))
    store.save(_dossier("uk", title="A"))
    store.save(_dossier("uk", title="B"))
    store.save(_dossier("us", title="C"))
    assert store.markets_present() == {"uk": 2, "us": 1}


def test_cross_market_clone_does_not_overwrite_source(tmp_path):
    """End-to-end proof of the trap: same title+one_liner, two markets, two dossiers."""
    store = Store(_cfg(tmp_path))
    store.save(_dossier("uk", title="Same idea"))
    store.save(_dossier("us", title="Same idea"))

    n = sqlite3.connect(str(store.db)).execute("SELECT COUNT(*) FROM dossiers").fetchone()[0]
    assert n == 2
    assert len(list((tmp_path / "dossiers").glob("*.json"))) == 2


@pytest.mark.skipif(not LIVE_DB.exists(), reason="no live catalogue on this machine")
def test_additive_migration_applies_to_the_live_catalogue(tmp_path):
    """The migration must work on the REAL database, not just a fresh one — that is
    where the 1,000+ existing dossiers live."""
    shutil.copy(LIVE_DB, tmp_path / "prospector.db")
    before = sqlite3.connect(str(tmp_path / "prospector.db"))
    n_before = before.execute("SELECT COUNT(*) FROM dossiers").fetchone()[0]
    # How many rows already carry a market BEFORE the migration runs. If the live DB
    # predates the column entirely this is 0, which restores the original assertion.
    cols_before = {r[1] for r in before.execute("PRAGMA table_info(dossiers)")}
    marked_before = 0 if "market" not in cols_before else before.execute(
        "SELECT COUNT(*) FROM dossiers WHERE market IS NOT NULL AND market != ''"
    ).fetchone()[0]
    before.close()

    store = Store(_cfg(tmp_path))  # _init_db runs the additive migration

    conn = sqlite3.connect(str(store.db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dossiers)")}
    assert "market" in cols
    assert conn.execute("SELECT COUNT(*) FROM dossiers").fetchone()[0] == n_before
    marked_after = conn.execute(
        "SELECT COUNT(*) FROM dossiers WHERE market IS NOT NULL AND market != ''"
    ).fetchone()[0]
    # Pre-existing rows read as unknown, never as a fabricated 'uk'.
    #
    # This used to assert the count was 0 outright. That premise expired once the engine
    # started writing market-tagged dossiers into the live DB: it now holds 1289 unmarked
    # rows plus 29 legitimately tagged 'uk', so a bare `== 0` fails on real data while the
    # migration is behaving perfectly. The invariant that actually matters is that the
    # migration INVENTS nothing — whatever was tagged before is tagged after, and nothing
    # else acquires a market. Snapshot it rather than hardcoding a number that drifts.
    assert marked_after == marked_before, (
        f"additive migration fabricated a market on {marked_after - marked_before} row(s); "
        f"pre-existing rows must stay unknown")

    # And the store still writes correctly afterwards.
    store.save(_dossier("us"))
    assert conn.execute("SELECT COUNT(*) FROM dossiers").fetchone()[0] == n_before + 1
