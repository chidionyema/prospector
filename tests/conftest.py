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
def _isolate_price_rationale(tmp_path, monkeypatch):
    """Write D3 price-rationale records (price_rationale.py) under a per-test temp root.

    The bridge writes one on every publish, and several tests drive that path. Without
    this, a test run files fabricated derivation records into store/pricing/rationale/ —
    the directory `PricePatchRequest.RationaleRef` points at for real, live prices. Same
    class of leak as the audit log above, on the money rail instead of the run log."""
    monkeypatch.setenv("PROSPECTOR_RATIONALE_ROOT", str(tmp_path / "rationale_root"))


@pytest.fixture(autouse=True)
def _no_live_grounding_probe(monkeypatch):
    """Stub the per-tick grounding probe to "healthy" unless a test says otherwise.

    `_generation_suppressed` gained a CAUSAL gate on 2026-08-06 (`_grounding_degraded_reason`),
    and it works by issuing a real search against the live retrieval chain. That is correct in
    the daemon and wrong in a unit test twice over: it puts a network call on the path of every
    test that touches a tick, and — because it fails closed — a test cfg built from
    `SimpleNamespace` makes `make_provider` raise, which would silently flip every pre-existing
    generation assertion from "generated" to "suppressed" for a reason that has nothing to do
    with what the test is pinning.

    Defaulting to healthy keeps those tests testing what they were written to test. The gate's
    own tests (tests/scheduler/test_grounding_gate.py) monkeypatch over this fixture, which
    wins because it is applied after."""
    from prospector.scheduler import run_scheduled as rs
    monkeypatch.setattr(rs, "_probe_grounding_once", lambda cfg, timeout_s: ("", None))


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
