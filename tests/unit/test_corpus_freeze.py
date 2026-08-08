"""A matched pair must be guaranteed by construction, not hoped for.

On 2026-08-07 E15 and E17 both reported `n_dossiers: 1597` and were quoted as a
pair. Their corpus fingerprints were `d97829ed7ea0bae0` (20:16:23Z) and
`81d96e5387f7467a` (20:35:10Z) — same count, different content, because the daemon
rewrites dossiers while an experiment runs. Any agreement figure across them
compares two samples, not two methods.

`corpus_fingerprint()` DETECTS that. It cannot prevent it. `_freeze_corpus.py`
prevents it, and these tests pin the three properties that make it worth trusting:

* the corpus location is resolved PER CALL, so an override set after import is
  honoured (a module-level constant was the original shape, and a constant that no
  longer describes what the code reads is this repo's "write-only field" trap);
* freezing from inside an already-frozen shell fingerprints the LIVE store, not the
  snapshot — otherwise it would re-copy the snapshot and report a perfect match that
  proves nothing;
* a snapshot taken while the corpus moves is REJECTED. A torn snapshot is worse than
  no snapshot: it looks frozen and is not.

No test here touches the real `store/`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXPERIMENTS = REPO / "tools" / "experiments"


def _load(name: str, path: Path):
    if str(EXPERIMENTS) not in sys.path:
        sys.path.insert(0, str(EXPERIMENTS))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    mod = _load("_corpus", EXPERIMENTS / "_corpus.py")
    monkeypatch.delenv(mod.ENV_CORPUS_DIR, raising=False)
    monkeypatch.delenv(mod.ENV_CORPUS_DB, raising=False)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    live = tmp_path / "store" / "dossiers"
    live.mkdir(parents=True)
    for i in range(5):
        (live / f"{i:04x}.pass.json").write_text('{"decision": "pass"}')
    return mod


# --------------------------------------------------------------------------- #
# per-call resolution
# --------------------------------------------------------------------------- #

def test_corpus_dir_defaults_to_the_live_store(corpus, tmp_path):
    assert corpus.corpus_dir() == tmp_path / "store" / "dossiers"
    assert corpus.db_path() == tmp_path / "store" / "prospector.db"
    assert corpus.is_frozen() is False
    assert len(corpus.dossier_paths()) == 5


def test_an_override_set_after_import_is_honoured(corpus, tmp_path, monkeypatch):
    """The whole point of resolving per call. A module-level constant captured at
    import would silently keep reading the live store."""
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "aaaa.pass.json").write_text("{}")
    monkeypatch.setenv(corpus.ENV_CORPUS_DIR, str(snap))
    assert corpus.corpus_dir() == snap
    assert corpus.dossier_paths() == [str(snap / "aaaa.pass.json")]
    assert corpus.is_frozen() is True


def test_a_blank_override_is_not_an_override(corpus, tmp_path, monkeypatch):
    """An empty env var is how a shell exports "unset"; treating it as a path would
    point the corpus at the process cwd."""
    monkeypatch.setenv(corpus.ENV_CORPUS_DIR, "   ")
    assert corpus.corpus_dir() == tmp_path / "store" / "dossiers"
    assert corpus.is_frozen() is False


def test_fingerprint_records_whether_it_was_frozen(corpus, tmp_path, monkeypatch):
    """A number that cannot say whether it read a snapshot or the live store can be
    mistaken for a live reading."""
    live = corpus.corpus_fingerprint()
    assert live["frozen"] is False and live["n_dossiers"] == 5
    snap = tmp_path / "snap"
    snap.mkdir()
    monkeypatch.setenv(corpus.ENV_CORPUS_DIR, str(snap))
    frozen = corpus.corpus_fingerprint()
    assert frozen["frozen"] is True
    assert frozen["corpus_dir"] == str(snap)
    assert frozen["sha256"] != live["sha256"]


def test_fingerprint_changes_when_content_changes_but_count_does_not(corpus, tmp_path):
    """The exact 2026-08-07 failure: same n_dossiers, different corpus."""
    before = corpus.corpus_fingerprint()
    target = sorted(corpus.dossier_paths())[0]
    Path(target).write_text('{"decision": "pass", "rewritten": true}')
    after = corpus.corpus_fingerprint()
    assert before["n_dossiers"] == after["n_dossiers"] == 5
    assert before["sha256"] != after["sha256"]


# --------------------------------------------------------------------------- #
# freezing
# --------------------------------------------------------------------------- #

@pytest.fixture
def freezer(corpus, monkeypatch):
    mod = _load("_freeze_corpus", EXPERIMENTS / "_freeze_corpus.py")
    monkeypatch.setattr(mod, "corpus", corpus)
    return mod


def test_freeze_produces_a_verified_matching_snapshot(freezer, corpus, tmp_path):
    dest = tmp_path / "frozen"
    target, fp = freezer.freeze(dest)
    assert target == dest
    assert fp["n_dossiers"] == 5
    assert len(list((dest / "dossiers").glob("*.json"))) == 5
    # the snapshot reproduces the live hash exactly -- copy2 preserves mtime+size,
    # which is what the fingerprint hashes
    assert fp["sha256"] == freezer._live_fingerprint()["sha256"]


def test_freeze_leaves_the_environment_as_it_found_it(freezer, corpus):
    """freeze() sets the override to verify the snapshot. If it leaked, the calling
    process would silently start reading the snapshot."""
    import os
    freezer.freeze()
    assert corpus.ENV_CORPUS_DIR not in os.environ


def test_live_fingerprint_ignores_an_existing_override(freezer, corpus, tmp_path, monkeypatch):
    """Freezing from inside a frozen shell must still measure the LIVE store,
    otherwise it re-copies the snapshot and reports a match that proves nothing."""
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "zzzz.pass.json").write_text("{}")
    monkeypatch.setenv(corpus.ENV_CORPUS_DIR, str(snap))
    assert corpus.corpus_fingerprint()["n_dossiers"] == 1     # the frozen view
    assert freezer._live_fingerprint()["n_dossiers"] == 5     # the live one
    assert freezer._live_fingerprint()["frozen"] is False


def test_a_moving_corpus_is_rejected_not_returned(freezer, corpus, monkeypatch):
    """A torn snapshot looks frozen and is not. The caller must get an exception, not
    a plausible-looking pair of receipts."""
    calls = {"n": 0}

    def never_settles():
        calls["n"] += 1
        return {"n_dossiers": 5, "newest_mtime_utc": None,
                "sha256": f"{calls['n']:016x}", "frozen": False, "corpus_dir": "x"}

    monkeypatch.setattr(corpus, "corpus_fingerprint", never_settles)
    with pytest.raises(RuntimeError, match="did not hold still"):
        freezer.freeze()
    assert calls["n"] >= freezer.MAX_ATTEMPTS * 2   # before+after on every attempt


def test_freeze_retries_and_succeeds_once_the_corpus_settles(freezer, corpus, monkeypatch):
    """The retry must be a real retry, not a single attempt with a loop around it."""
    seq = iter(["aaaa", "bbbb", "cccc", "cccc"])   # attempt 1 tears, attempt 2 holds

    def fingerprint():
        return {"n_dossiers": 5, "newest_mtime_utc": None,
                "sha256": next(seq), "frozen": False, "corpus_dir": "x"}

    monkeypatch.setattr(corpus, "corpus_fingerprint", fingerprint)
    _, fp = freezer.freeze()
    assert fp["sha256"] == "cccc"
