"""Tests for dead-loop prevention (decay.py)."""

import json
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from prospector.kill_decay import (
    get_active_steers,
    check_diversity_floor,
    get_stale_domains,
    re_seed_suggestions,
)


def _make_dossier(
    dossiers_dir: Path,
    filename: str,
    domain: str,
    verdict: str = "KILL",
    days_ago: float = 0.0,
):
    """Create a mock dossier file."""
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    dossier = {
        "verdict": verdict,
        "domain": domain,
        "timestamp": ts.isoformat(),
        "idea": {"domain": domain},
    }
    (dossiers_dir / filename).write_text(json.dumps(dossier))


def test_kill_reasons_decay():
    """Old kill reasons should have lower strength than recent ones."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        # Old kill (45 days ago)
        _make_dossier(dossiers, "old_kill.json", "food_delivery", days_ago=45)
        # Recent kill (1 day ago)
        _make_dossier(dossiers, "recent_kill.json", "fintech", days_ago=1)

        steers = get_active_steers(store, half_life_days=30)

        # fintech should have higher strength than food_delivery
        assert "fintech" in steers, f"Expected fintech in steers, got {steers}"
        if "food_delivery" in steers:
            assert steers["fintech"] > steers["food_delivery"], (
                f"Recent kill should be stronger: fintech={steers['fintech']}, "
                f"food_delivery={steers['food_delivery']}"
            )


def test_very_old_kills_dropped():
    """Kills older than several half-lives should drop below threshold."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        # Very old kill (120 days, 4 half-lives at 30-day HL)
        _make_dossier(dossiers, "ancient.json", "ancient_domain", days_ago=120)
        # Recent kill
        _make_dossier(dossiers, "recent.json", "recent_domain", days_ago=1)

        steers = get_active_steers(store, half_life_days=30, min_strength=0.1)

        # Ancient should be gone (decayed below threshold)
        assert "recent_domain" in steers
        # ancient at 120 days: exp(-ln(2)*120/30) = exp(-2.77) = 0.0625
        # Normalized: 0.0625 / 1.0 = 0.0625 < 0.1 threshold → dropped
        assert "ancient_domain" not in steers, (
            f"Ancient domain should be below threshold, got {steers}"
        )


def test_multiple_kills_accumulate():
    """Multiple kills in same domain should accumulate strength."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        # Three recent kills in same domain
        for i in range(3):
            _make_dossier(dossiers, f"kill_{i}.json", "saas", days_ago=0.5)

        # One kill in different domain
        _make_dossier(dossiers, "other.json", "fintech", days_ago=0.5)

        steers = get_active_steers(store, half_life_days=30)

        # saas should have higher strength (3 kills vs 1)
        assert steers.get("saas", 0) > steers.get("fintech", 1.0), (
            f"3 kills should accumulate: saas={steers.get('saas')}, fintech={steers.get('fintech')}"
        )


def test_pass_candidates_not_counted():
    """Only KILL verdicts should generate steers."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        _make_dossier(dossiers, "pass.json", "good_domain", verdict="PASS", days_ago=1)
        _make_dossier(dossiers, "kill.json", "bad_domain", verdict="KILL", days_ago=1)

        steers = get_active_steers(store, half_life_days=30)

        assert "bad_domain" in steers
        assert "good_domain" not in steers


def test_empty_store():
    """Empty store should return empty steers."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        steers = get_active_steers(store)
        assert steers == {}


def test_diversity_entropy_uniform():
    """Uniform distribution should have maximum entropy."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        domains = ["saas", "fintech", "health", "food", "climate", "gaming", "ai", "web3"]
        for i, domain in enumerate(domains):
            _make_dossier(dossiers, f"d_{i}.json", domain, verdict="PASS", days_ago=i * 0.5)

        result = check_diversity_floor(store, window=20, floor=0.5)
        # 8 domains uniformly distributed → entropy ≈ 3.0 (log2(8) = 3.0)
        assert result["entropy"] > 2.0, f"Uniform 8 domains should have entropy ~3.0, got {result['entropy']}"
        assert result["triggered"] is False


def test_diversity_collapse_triggers():
    """All candidates in one domain should trigger floor."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        # All in one domain
        for i in range(20):
            _make_dossier(dossiers, f"d_{i}.json", "saas", verdict="PASS", days_ago=i * 0.5)

        result = check_diversity_floor(store, window=20, floor=0.5)
        # One domain → entropy = 0.0
        assert result["entropy"] == 0.0, f"Single domain should have entropy 0, got {result['entropy']}"
        assert result["triggered"] is True
        assert result["action"] == "force_reseed"


def test_stale_domains_detection():
    """Domains not seen recently should be identified as stale."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        # Old entries
        _make_dossier(dossiers, "old_1.json", "food_delivery", days_ago=30)
        _make_dossier(dossiers, "old_2.json", "marketplace", days_ago=25)
        # Recent entry
        _make_dossier(dossiers, "recent.json", "ai_saas", days_ago=2)

        stale = get_stale_domains(store, top_k=5, min_days_stale=14)

        assert "food_delivery" in stale
        assert "marketplace" in stale
        assert "ai_saas" not in stale


def test_reseed_suggestions():
    """Should generate suggestions for stale domains."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        _make_dossier(dossiers, "old.json", "food_delivery", days_ago=30)

        suggestions = re_seed_suggestions(store, count=2)
        assert len(suggestions) <= 2
        assert len(suggestions) > 0
        # Should mention the stale domain
        assert any("food_delivery" in s.lower() for s in suggestions)


def test_reseed_suggestions_empty_store():
    """Empty store should still give broad suggestions."""
    with tempfile.TemporaryDirectory() as tmp:
        suggestions = re_seed_suggestions(Path(tmp), count=3)
        assert len(suggestions) == 3
        assert all(isinstance(s, str) for s in suggestions)
