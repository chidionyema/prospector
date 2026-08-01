"""Shared fixtures for the prospector test suite."""
from __future__ import annotations

import pytest
from prospector.config import load_config, Config


@pytest.fixture(autouse=True)
def _isolate_provider_health(tmp_path, monkeypatch):
    """Point the shared provider-health singleton at a per-test temp file.

    The persisted health layer (health.py) is process-wide state read/written by the
    failover chains. Without isolation, one test marking a provider exhausted would
    leak into later tests AND pollute the real store/provider_health.json. Each test
    gets a fresh, empty, throwaway health file."""
    import prospector.health as H
    monkeypatch.setattr(H, "_DEFAULT",
                        H.ProviderHealth(tmp_path / "provider_health.json"))


@pytest.fixture(autouse=True)
def _isolate_audit_log(tmp_path, monkeypatch):
    """Redirect the append-only audit log at a per-test temp dir.

    Without this, any test that exercises a search provider or the brain chain appends
    real-looking rows to store/scheduler/audit/<today>.jsonl — the file we read to decide
    what the daemon actually did. That is not a cosmetic leak: on 2026-07-31 six
    `brain_fallthrough` rows carrying fixture values ("served": "b",
    "last_err": "gemini cli exhausted...") sat in the production log at test-run pids and
    read exactly like a live moat failure.

    Patched on the module attribute, not the env var: audit.py binds _AUDIT_DIR at import
    (audit.py:66), so setenv alone is a no-op for an already-imported module."""
    import prospector.audit as A
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PROSPECTOR_AUDIT_DIR", str(audit_dir))
    monkeypatch.setattr(A, "_AUDIT_DIR", audit_dir)


@pytest.fixture(autouse=True)
def _isolate_durable_ledger(tmp_path, monkeypatch):
    """Redirect the v2 durable ledger at a per-test temp file.

    Without this, every TribunalMiddleware() built with no explicit ledger_path appends
    real-looking "LAW:" bullets to storage/durable_ledger.md. That is not cosmetic: the
    generator injects the LAST 15 bullets into every batch prompt (moat_prompts._load_ledger),
    so test laws about spec ids "abc"/"abc123"/"test-2"/"test-3" become the entire law context
    the real generator reasons from. As of 2026-08-01 the committed ledger held 826 bullets of
    which only 5 were real — all 15 in the generator's window were test noise.

    Patched on the module attributes, not the env var: both modules bind their ledger path at
    import (middleware.py:24, moat_prompts.py:18), so setenv alone is a no-op in-process."""
    import prospector.pipeline.middleware as MW
    import prospector.pipeline.moat_prompts as MP
    ledger = tmp_path / "durable_ledger.md"
    monkeypatch.setenv("PROSPECTOR_LEDGER_PATH", str(ledger))
    monkeypatch.setattr(MW, "_DEFAULT_LEDGER", ledger)
    monkeypatch.setattr(MP, "_LEDGER_PATH", ledger)


@pytest.fixture(autouse=True)
def _isolate_control_center_state(tmp_path, monkeypatch):
    """Redirect the Control Center's on-disk state at a per-test temp dir.

    config_editor.write_config() appends an audit row to store/control_center/config_history.jsonl
    and rewrites certification.json. The existing tests rebind _CC_DIR and _BACKUP_DIR but NOT
    _CONFIG_HISTORY, which was derived from _CC_DIR once at import (config_editor.py:30) — so the
    history row landed in the production file while its "backup" field pointed at a pytest tmpdir.
    All 138 rows committed as of 2026-08-01 were test rows of exactly that shape.

    Rebinds all four; tests that redirect a subset still override this on top."""
    import prospector.control_center.config_editor as CE
    cc = tmp_path / "control_center"
    cc.mkdir(parents=True, exist_ok=True)
    # Deliberately NOT setting PROSPECTOR_STORE_DIR here: that env var redirects every store
    # read as well, and many tests legitimately read the real catalogue.
    monkeypatch.setattr(CE, "_CC_DIR", cc)
    monkeypatch.setattr(CE, "_BACKUP_DIR", cc / "backups")
    monkeypatch.setattr(CE, "_CERT_PATH", cc / "certification.json")
    monkeypatch.setattr(CE, "_CONFIG_HISTORY", cc / "config_history.jsonl")


@pytest.fixture
def cfg() -> Config:
    """Load real config from config.yaml (fixture mode wired by individual tests)."""
    c = load_config()
    # Tests that need fixture retrieval set c.retrieval.provider themselves;
    # this fixture just provides a clean config base.
    return c


@pytest.fixture
def fixture_cfg(cfg: Config) -> Config:
    """Config with retrieval provider set to 'fixture' and cache disabled."""
    cfg.retrieval.provider = "fixture"
    cfg.retrieval.cache = False
    return cfg
