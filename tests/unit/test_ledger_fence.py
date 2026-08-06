"""The durable ledger must never be written by the test suite.

Regression guard for the leak found 2026-08-06: `storage/durable_ledger.md` carried 1196
committed `LAW:` lines minted by pytest fixtures ("LAW: Do not generate concepts related to
abc123 after multiple failed wedge pivots."). The ledger is not a log — moat_prompts injects
its last 15 laws into the generator AND verifier prompts as concepts "mathematically proven
to fail", so fixture junk becomes a standing ban on what the engine may propose.

The fence is `middleware.default_ledger_path()` resolving $PROSPECTOR_LEDGER_PATH at CALL
time. Anyone who "simplifies" it back into a module-level constant re-opens the hole, because
a constant binds at import — before conftest can redirect it. These tests set the env after
import specifically so that regression fails here.
"""
from __future__ import annotations

from pathlib import Path

from prospector.pipeline.middleware import (
    TribunalMiddleware,
    _REPO_LEDGER,
    default_ledger_path,
)
from prospector.pipeline.moat_prompts import _load_ledger

PRODUCTION_LEDGER = Path(__file__).resolve().parents[2] / "storage" / "durable_ledger.md"


def test_autouse_fixture_diverts_the_ledger_off_the_repo(tmp_path):
    """The conftest fixture alone must be enough — no per-test opt-in."""
    resolved = default_ledger_path()
    assert resolved != _REPO_LEDGER
    assert PRODUCTION_LEDGER not in (resolved, *resolved.parents)


def test_tribunal_writes_a_law_to_the_temp_ledger_not_the_repo():
    """The end-to-end proof: commit a law, then check the real file is byte-identical."""
    before = PRODUCTION_LEDGER.read_bytes() if PRODUCTION_LEDGER.exists() else None

    tribunal = TribunalMiddleware()
    tribunal._commit_law("LAW: fixture law that must never reach the repo.", "spec-fence")

    after = PRODUCTION_LEDGER.read_bytes() if PRODUCTION_LEDGER.exists() else None
    assert after == before, "the test suite just wrote to the production durable ledger"

    written = tribunal.ledger_path.read_text(encoding="utf-8")
    assert "fixture law that must never reach the repo" in written


def test_reader_and_writer_resolve_to_the_same_redirected_file():
    """A one-sided fence still poisons prompts: the reader must follow the writer.

    If only the writer honoured the override, `_load_ledger` would keep serving the
    production laws into test prompts — and a reader still pinned to a module constant
    would pass a writer-only test while silently reading the repo file.
    """
    TribunalMiddleware()._commit_law("LAW: reader must see this one.", "spec-reader")
    assert "reader must see this one" in _load_ledger()


def test_explicit_ledger_path_argument_still_wins(tmp_path):
    """The constructor override outranks the env var — used by callers with their own store."""
    explicit = tmp_path / "explicit_ledger.md"
    tribunal = TribunalMiddleware(ledger_path=explicit)
    tribunal._commit_law("LAW: explicit path wins.", "spec-explicit")
    assert "explicit path wins" in explicit.read_text(encoding="utf-8")
    assert not default_ledger_path().exists(), "env-default ledger should be untouched"
