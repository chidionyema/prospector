"""Tests for dead-loop prevention (decay.py)."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from prospector.kill_decay import (
    check_diversity_floor,
    get_active_steers,
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
    """Create a mock dossier file.

    `candidate` and `checks` are here because every real dossier carries both (measured over
    the live store, 2026-08-20) and `kill_decay._is_dossier` tests for them. Without them this
    fixture wrote a shape production never writes, which is why no test could see a lint
    receipt being counted as a dossier — see `test_a_lint_receipt_is_not_a_dossier`.
    """
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    dossier = {
        "verdict": verdict,
        "domain": domain,
        "timestamp": ts.isoformat(),
        "idea": {"domain": domain},
        "candidate": {"title": f"a {domain} idea", "market": domain},
        "checks": [{"name": "pain_reality", "verdict": "supported"}],
    }
    (dossiers_dir / filename).write_text(json.dumps(dossier))


def _make_lint_receipt(dossiers_dir: Path, filename: str, market: str):
    """Write the OTHER kind of file that lives in `store/dossiers/`.

    The pack gate writes `<id>.lint.json` beside the dossiers (bridge.py:1256). It carries a
    `market` field holding a jurisdiction code, and every domain fallback in kill_decay reads
    `market`. It has no `checks` and no `candidate`.
    """
    receipt = {
        "market": market,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "problems": [],
        "bundle_missing": [],
    }
    (dossiers_dir / filename).write_text(json.dumps(receipt))


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


def test_a_lint_receipt_is_not_a_dossier():
    """The diversity brake must not read jurisdiction codes off pack lint receipts.

    Measured on the live store 2026-08-20: 31 of the 50 newest `*.json` files under
    `store/dossiers/` were `<id>.lint.json` receipts, not dossiers. The brake read entropy
    1.9334 ("ok") where the dossiers-only entropy was 0.0 ("force_reseed"), and all five
    non-"unknown" domains it reported ("uk", "us", "us-ga", "us-tx", "us-il") came from
    receipts. It did not drift; it returned the opposite verdict.

    This test reproduces that shape: one real domain, plus receipts carrying distinct
    markets. Deleting the `_is_dossier` guard in kill_decay makes it fail.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        for i in range(6):
            _make_dossier(dossiers, f"d_{i}.json", "saas", verdict="PASS", days_ago=i * 0.1)
        for i, market in enumerate(["uk", "us", "us-ga", "us-tx", "us-il"]):
            _make_lint_receipt(dossiers, f"lint_{i}.lint.json", market)

        result = check_diversity_floor(store, window=50, floor=0.5)

        assert result["domains"] == ["saas"], (
            f"a lint receipt's market reached the domain list: {result['domains']}"
        )
        assert result["total_dossiers"] == 6, (
            f"lint receipts counted in the denominator: {result['total_dossiers']} != 6"
        )
        assert result["entropy"] == 0.0
        assert result["triggered"] is True
        assert result["action"] == "force_reseed"


def test_a_lint_receipt_is_never_a_stale_domain():
    """`get_stale_domains` ranks a domain with no timestamp first, at infinite staleness.

    A lint receipt supplies a `market` and carries `checked_at` rather than `timestamp`, so
    before the guard it entered `all_domains` with no last-seen date and sorted ahead of every
    genuinely stale domain — the whole top-k could be jurisdiction codes.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        dossiers = store / "dossiers"
        dossiers.mkdir(parents=True)

        _make_dossier(dossiers, "old.json", "food_delivery", days_ago=30)
        _make_dossier(dossiers, "recent.json", "ai_saas", days_ago=1)
        for i, market in enumerate(["uk", "us", "us-ga"]):
            _make_lint_receipt(dossiers, f"lint_{i}.lint.json", market)

        stale = get_stale_domains(store, top_k=5, min_days_stale=14)

        assert stale == ["food_delivery"], f"lint markets reached the stale list: {stale}"
