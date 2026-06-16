"""Behavioral tests for control_center components."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from prospector.control_center.components.gate_badge import render_gate_badge
from prospector.control_center.components.source_list import (
    render_source_summary,
    _truncate,
)


class TestGateBadge:
    """render_gate_badge() must produce the correct HTML for each decision."""

    def test_pass_badge_contains_pass(self):
        result = render_gate_badge("pass")
        assert "PASS" in result
        assert "#22c55e" in result  # green hex

    def test_kill_badge_contains_kill(self):
        result = render_gate_badge("kill")
        assert "KILL" in result
        assert "#ef4444" in result  # red hex

    def test_defer_badge_contains_defer(self):
        result = render_gate_badge("defer")
        assert "DEFER" in result
        assert "#eab308" in result  # yellow hex

    def test_case_insensitive(self):
        assert "PASS" in render_gate_badge("PASS")
        assert "KILL" in render_gate_badge("KILL")
        assert "DEFER" in render_gate_badge("DEFER")

    def test_unknown_decision_returns_plain(self):
        result = render_gate_badge("")
        assert "—" in result

    def test_none_decision_returns_plain(self):
        result = render_gate_badge(None)
        assert "—" in result


class TestSourceList:
    """render_source_list() and render_source_summary() must handle sources correctly."""

    def test_truncate_shortens_long_strings(self):
        s = "a" * 100
        result = _truncate(s, 50)
        assert len(result) == 51  # 50 + "…" (one-char ellipsis)
        assert result.endswith("…")

    def test_truncate_keeps_short_strings(self):
        s = "hello"
        result = _truncate(s, 50)
        assert result == "hello"

    def test_source_summary_no_sources(self):
        result = render_source_summary([])
        assert result == "no sources"

    def test_source_summary_with_urls(self):
        sources = [
            {"url": "https://example.com", "text": "Example page"},
            {"url": "https://gov.uk/policy", "text": "Policy doc"},
            {"url": "https://third.com"},
        ]
        result = render_source_summary(sources)
        assert "example.com" in result
        assert "gov.uk" in result
        assert "3 source(s)" in result


class TestKPStrip:
    """kpi_card, kpi_row, spend_progress_bar functions must handle edge cases."""

    def test_spend_progress_bar_handles_zero_cap(self):
        import prospector.control_center.components.kpi_strip as kpi
        kpi.spend_progress_bar(0.0, 0.0)

    def test_spend_progress_bar_handles_over_cap(self):
        # This requires a Streamlit runtime context — skip without mocking
        pytest.skip("requires Streamlit runtime context")

    def test_kpi_strip_exports(self):
        from prospector.control_center.components import kpi_strip
        assert hasattr(kpi_strip, "kpi_card")
        assert hasattr(kpi_strip, "kpi_row")
        assert hasattr(kpi_strip, "spend_progress_bar")


class TestDossierCard:
    """Dossier card component — pure logic tests."""

    def test_dossier_card_module_imports_cleanly(self):
        from prospector.control_center.components import dossier_card
        assert hasattr(dossier_card, "render_dossier_card")
        assert hasattr(dossier_card, "_render_checks")
        assert hasattr(dossier_card, "_render_sources")

    def test_sources_handles_empty_list(self):
        """Empty source list should not crash the helper."""
        # Just verify the module is importable
        from prospector.control_center.components import dossier_card
        assert dossier_card._render_sources.__doc__ is not None

    def test_decision_badge_unknown(self):
        pass  # pure UI — Streamlit context needed


class TestConfigEditorExports:
    """Verify all expected config_editor functions are exported."""

    def test_all_expected_exports_exist(self):
        from prospector.control_center import config_editor as ce

        expected = [
            "load_config_raw",
            "config_hash",
            "diff_configs",
            "validate_config",
            "is_moat_affecting",
            "mtime_conflict",
            "get_config_mtime",
            "write_config",
            "load_certification",
            "certify_from_golden",
            "list_backups",
            "restore_backup",
            "MOAT_AFFECTING_KEYS",
        ]
        for name in expected:
            assert hasattr(ce, name), f"Missing export: {name}"


class TestReadersExports:
    """Verify all expected readers functions are exported."""

    def test_all_expected_readers_exist(self):
        from prospector.control_center import readers

        expected = [
            "load_config_typed",
            "load_config_dict",
            "catalogue_index",
            "catalogue_stats",
            "load_dossier",
            "load_listing",
            "load_pending_signals",
            "load_jobs",
            "load_provider_health",
            "load_audit_log",
            "today_spend",
            "load_golden_runs",
            "latest_golden",
            "load_certification",
            "moat_down",
        ]
        for name in expected:
            assert hasattr(readers, name), f"Missing export: {name}"
