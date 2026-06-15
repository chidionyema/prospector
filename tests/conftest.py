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
