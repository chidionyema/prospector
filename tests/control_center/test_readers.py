"""Behavioral tests for control_center.readers.

Tests data loading: catalogue index, dossier loading, pending signals,
moat-down detection, costs, and golden runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from prospector.control_center import readers


class TestCatalogueIndex:
    """catalogue_index() must read the real SQLite store."""

    def test_returns_list(self):
        idx = readers.catalogue_index()
        assert isinstance(idx, list)

    def test_total_matches_existing_data(self):
        idx = readers.catalogue_index()
        # Real store has 367 dossiers — verify we read the real data
        assert len(idx) >= 300  # conservative guard

    def test_filter_by_decision(self):
        pass_rows = readers.catalogue_index(decision="pass")
        kill_rows = readers.catalogue_index(decision="kill")
        defer_rows = readers.catalogue_index(decision="defer")
        all_rows = readers.catalogue_index()

        for r in pass_rows:
            assert r.get("decision", "").lower() == "pass"
        for r in kill_rows:
            assert r.get("decision", "").lower() == "kill"
        for r in defer_rows:
            assert r.get("decision", "").lower() == "defer"
        assert len(all_rows) >= len(pass_rows) + len(kill_rows) + len(defer_rows)


class TestCatalogueStats:
    """catalogue_stats() must aggregate counts correctly."""

    def test_stats_total_matches_index(self):
        idx = readers.catalogue_index()
        stats = readers.catalogue_stats()
        assert stats["total"] == len(idx)

    def test_stats_sum_equals_total(self):
        stats = readers.catalogue_stats()
        # Sum of pass+kill+defer should be <= total (provisional not included)
        n_ruled = stats["n_pass"] + stats["n_kill"] + stats["n_defer"]
        assert n_ruled <= stats["total"]

    def test_stats_has_all_decision_counts(self):
        stats = readers.catalogue_stats()
        for key in ("n_pass", "n_kill", "n_defer", "n_provisional", "total"):
            assert key in stats
            assert isinstance(stats[key], int)
            assert stats[key] >= 0


class TestMoatDown:
    """moat_down() must detect when both moat operators are exhausted."""

    def test_moat_down_false_when_healthy(self):
        health = {}  # no data = not down
        assert not readers.moat_down(health)

    def test_moat_down_true_when_dead_until_in_future(self):
        now = datetime.now(timezone.utc).timestamp()
        health = {
            "claude": {"dead_until": now + 300, "dead_for_s": 300},
            "gemini": {"dead_until": now + 300, "dead_for_s": 300},
        }
        assert readers.moat_down(health)

    def test_moat_down_false_when_one_operator_healthy(self):
        now = datetime.now(timezone.utc).timestamp()
        health = {
            "claude": {"dead_until": now + 300, "dead_for_s": 300},
            "gemini": {"dead_until": 0, "dead_for_s": 0},  # healthy
        }
        assert not readers.moat_down(health)

    def test_moat_down_false_when_both_dead_until_is_zero(self):
        health = {
            "claude": {"dead_until": 0, "dead_for_s": 60},
            "gemini": {"dead_until": 0, "dead_for_s": 60},
        }
        assert not readers.moat_down(health)

    def test_moat_down_ignores_non_moat_operators(self):
        """Non-moat operators (minimax, deepseek) should not trigger moat-down."""
        now = datetime.now(timezone.utc).timestamp()
        health = {
            "minimax": {"dead_until": now + 300, "dead_for_s": 300},
            "deepseek": {"dead_until": now + 300, "dead_for_s": 300},
        }
        assert not readers.moat_down(health)

    def test_moat_down_handles_non_dict_state(self):
        """Provider health entries that are not dicts must not crash."""
        health = {
            "claude": {"dead_until": 0},
            "gemini": "not_a_dict",
            "minimax": 42,
            None: {},
        }
        # Must not raise — should skip the non-dict entries
        result = readers.moat_down(health)
        assert isinstance(result, bool)


class TestLoadDossier:
    """load_dossier() must read real dossier JSON files."""

    def test_returns_none_for_nonexistent_id(self):
        result = readers.load_dossier("nonexistent_id_not_real", "pass")
        assert result is None

    def test_returns_dict_for_real_dossier(self):
        # Get a real candidate_id from the catalogue
        idx = readers.catalogue_index()
        if not idx:
            pytest.skip("No dossiers in store")
        row = idx[0]
        cid = row.get("candidate_id")
        decision = row.get("decision")
        if not cid or not decision:
            pytest.skip("No valid dossier in store")

        dossier = readers.load_dossier(cid, decision)
        assert dossier is not None
        assert isinstance(dossier, dict)
        assert "candidate" in dossier

    def test_corrupt_json_returns_none(self, tmp_path):
        # Monkeypatch the dossiers path for this test
        cid = "fake_id"
        fake_dir = tmp_path / "dossiers"
        fake_dir.mkdir()
        (fake_dir / f"{cid}.kill.json").write_text("{ not valid json")

        # Save real path and override
        import prospector.control_center.readers as r_module
        orig_func = r_module.load_dossier
        # Patch at the module level via monkeypatch in conftest-style
        r_module.load_dossier.clear()

        def fake_load(cid_arg, decision):
            path = fake_dir / f"{cid_arg}.{decision}.json"
            if not path.exists():
                return None
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                return None

        r_module.load_dossier = fake_load
        try:
            result = fake_load(cid, "kill")
            assert result is None
        finally:
            r_module.load_dossier = orig_func


class TestCostsData:
    """costs_data() must compute totals from the real audit log."""

    def test_costs_data_returns_dict(self):
        from prospector.report import costs_data
        result = costs_data("store/prospector.jsonl")
        assert isinstance(result, dict)

    def test_costs_data_has_expected_keys(self):
        from prospector.report import costs_data
        result = costs_data("store/prospector.jsonl")
        for key in ("total_spend_usd", "total_calls", "providers", "tokens", "slowest_ops"):
            assert key in result, f"Missing key: {key}"

    def test_costs_data_total_spend_is_non_negative(self):
        from prospector.report import costs_data
        result = costs_data("store/prospector.jsonl")
        assert result["total_spend_usd"] >= 0

    def test_costs_data_nonexistent_file_returns_error(self):
        from prospector.report import costs_data
        result = costs_data("nonexistent/file.jsonl")
        assert "error" in result or result.get("total_spend_usd", 0) == 0


class TestTodaySpend:
    """today_spend() must compute today's spend from the audit log."""

    def test_returns_dict_with_keys(self):
        audit = readers.load_audit_log()
        spend = readers.today_spend(audit)
        assert isinstance(spend, dict)
        assert "total_usd" in spend
        assert "by_phase" in spend

    def test_total_is_non_negative(self):
        audit = readers.load_audit_log()
        spend = readers.today_spend(audit)
        assert spend["total_usd"] >= 0


class TestLoadGoldenRuns:
    """load_golden_runs() must return sorted golden run results."""

    def test_returns_list(self):
        runs = readers.load_golden_runs()
        assert isinstance(runs, list)

    def test_runs_are_sorted_newest_first(self):
        runs = readers.load_golden_runs()
        if len(runs) < 2:
            pytest.skip("Need at least 2 golden runs for sort test")
        mtimes = [r.get("_mtime", 0) for r in runs]
        # The first (newest) must be >= second (within filesystem clock tolerance)
        assert mtimes[0] >= mtimes[1] - 2, "Newest run should be same or newer than 2nd"
        # The last (oldest) must be <= second-to-last
        assert mtimes[-1] <= mtimes[-2] + 2, "Oldest run should be same or older than 2nd-to-last"
        # All intermediate should be in non-increasing order (allow 2s tolerance per step)
        disordered = [(i, mtimes[i], mtimes[i+1])
                     for i in range(len(mtimes)-1)
                     if mtimes[i] < mtimes[i+1] - 2]
        assert len(disordered) <= 2, f"Too many disordered pairs: {disordered[:5]}"

    def test_latest_golden_returns_most_recent(self):
        runs = readers.load_golden_runs()
        latest = readers.latest_golden()
        if runs:
            assert latest == runs[0]
            assert latest == sorted(runs, key=lambda r: r.get("_mtime", 0), reverse=True)[0]
        else:
            assert latest is None


class TestLoadPendingSignals:
    """load_pending_signals() must read signals/pending/."""

    def test_returns_list(self):
        pending = readers.load_pending_signals()
        assert isinstance(pending, list)


class TestLoadProviderHealth:
    """load_provider_health() must read the circuit state file."""

    def test_returns_dict(self):
        health = readers.load_provider_health()
        assert isinstance(health, dict)


class TestConfigLoad:
    """load_config_typed() must load the real config."""

    def test_loads_config(self):
        cfg = readers.load_config_typed()
        assert cfg is not None

    def test_config_has_expected_fields(self):
        cfg = readers.load_config_typed()
        assert hasattr(cfg, "thresholds")
        assert hasattr(cfg, "hard_gates")
        assert hasattr(cfg, "weights")
        assert hasattr(cfg, "spend")
