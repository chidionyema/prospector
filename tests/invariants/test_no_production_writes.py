"""Invariant: the test suite must never write into production data files.

Three separate leaks were live until 2026-08-01, all with the same shape — a path bound at
import time, so redirecting the env var (or even the directory it was derived from) was a
no-op. The damage was not hygiene: the durable ledger feeds the generator's prompt, and 821
of its 826 bullets were laws about test spec ids.

These tests fail if any of those paths resolves back to the repo's real files during a run.
"""
from __future__ import annotations

import json
from pathlib import Path

import prospector.audit as A
import prospector.control_center.config_editor as CE
import prospector.pipeline.middleware as MW
import prospector.pipeline.moat_prompts as MP

REPO = Path(__file__).resolve().parents[2]

PROD_PATHS = {
    "durable ledger (middleware writer)": (
        lambda: MW._DEFAULT_LEDGER, REPO / "storage" / "durable_ledger.md"),
    "durable ledger (moat_prompts reader)": (
        lambda: MP._LEDGER_PATH, REPO / "storage" / "durable_ledger.md"),
    "control center history": (
        lambda: CE._CONFIG_HISTORY, REPO / "store" / "control_center" / "config_history.jsonl"),
    "control center certification": (
        lambda: CE._CERT_PATH, REPO / "store" / "control_center" / "certification.json"),
    "control center backups": (
        lambda: CE._BACKUP_DIR, REPO / "store" / "control_center" / "backups"),
    "scheduler audit log": (
        lambda: A._AUDIT_DIR, REPO / "store" / "scheduler" / "audit"),
}


def test_no_module_points_at_a_production_data_file():
    """Every autouse-isolated path must be redirected away from the repo."""
    leaks = []
    for name, (resolve, prod) in PROD_PATHS.items():
        live = Path(resolve()).resolve()
        if live == prod.resolve():
            leaks.append(f"{name}: still points at {prod}")
    assert not leaks, "Test run would write production data:\n  " + "\n  ".join(leaks)


def test_tribunal_default_ledger_write_lands_outside_the_repo(tmp_path):
    """A TribunalMiddleware built with NO explicit ledger_path must not touch the repo.

    This is the exact construction used by tests/unit/test_v2_pipeline.py, which was the
    largest contributor of test laws to the real ledger."""
    before = _ledger_snapshot()
    MW.TribunalMiddleware()._commit_law(
        "LAW: invariant probe, must never reach the production ledger.", "invariant-probe")
    assert _ledger_snapshot() == before, (
        "TribunalMiddleware() with no ledger_path wrote into storage/durable_ledger.md")


def test_commit_law_does_not_append_exact_duplicates(tmp_path):
    """The generator reads only the last 15 bullets; a repeated law must not evict the rest."""
    ledger = tmp_path / "ledger.md"
    t = MW.TribunalMiddleware(ledger_path=ledger)
    for _ in range(5):
        t._commit_law("LAW: Do not build wrappers on transparent markets.", "spec-1")
    bullets = [ln for ln in ledger.read_text().splitlines() if ln.strip().startswith("*")]
    assert len(bullets) == 1, f"expected 1 bullet after 5 identical commits, got {bullets}"


def _ledger_snapshot() -> str:
    p = REPO / "storage" / "durable_ledger.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""
