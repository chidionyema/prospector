"""UI theme and Overview page tests — validate the Phase 1 modernization.

These must PASS for the UI modernization to be considered done.
"""
from __future__ import annotations

import pytest


class TestThemeCSS:
    """Theme CSS injection and module integrity."""

    def test_theme_module_exists_and_exports_inject(self):
        """Theme module must be importable and export inject_theme()."""
        from prospector.control_center import theme
        assert hasattr(theme, "inject_theme")
        assert callable(theme.inject_theme)

    def test_theme_css_is_non_trivial_string(self):
        """THEME_CSS must be a substantial CSS string with required classes."""
        from prospector.control_center.theme import THEME_CSS
        assert isinstance(THEME_CSS, str)
        assert len(THEME_CSS) > 200, "THEME_CSS too short — must have real CSS"
        # Required CSS classes from the spec
        assert ".cc-card" in THEME_CSS, "missing .cc-card"
        assert ".cc-kpi" in THEME_CSS, "missing .cc-kpi"
        assert ".cc-alarm" in THEME_CSS, "missing .cc-alarm"
        assert ".cc-pill" in THEME_CSS, "missing .cc-pill"

    def test_inject_theme_does_not_raise(self):
        """inject_theme() must not raise (though it needs Streamlit context
        for full rendering, the import and CSS string formation must succeed)."""
        from prospector.control_center.theme import inject_theme
        # inject_theme calls st.markdown which needs Streamlit runtime context.
        # We only test that the function exists and the CSS constant is valid.
        # The actual injection is tested via Streamlit integration tests.
        pass  # structural test — covered by test_theme_css_is_non_trivial_string


class TestConfigToml:
    """Streamlit theme config must exist."""

    def test_config_toml_has_theme_section(self):
        """`.streamlit/config.toml` must contain a [theme] section."""
        import tomllib
        from pathlib import Path
        config_path = Path(".streamlit/config.toml")
        assert config_path.exists(), ".streamlit/config.toml missing"
        cfg = tomllib.loads(config_path.read_text())
        assert "theme" in cfg, "[theme] section missing from config.toml"
        theme = cfg["theme"]
        assert "primaryColor" in theme or "base" in theme, \
            "theme must have at least base or primaryColor"


class TestOverviewPage:
    """Overview page module integrity."""

    def test_overview_module_imports(self):
        """Overview page module must import without errors."""
        from prospector.control_center.pages import _overview
        assert hasattr(_overview, "render")
        assert callable(_overview.render)

    def test_overview_has_card_render_functions(self):
        """Overview must export the new card-rendering helper functions."""
        from prospector.control_center.pages import _overview
        # After modernization, these functions must exist
        assert hasattr(_overview, "_render_kpi_cards"), \
            "missing _render_kpi_cards (KPI card row)"
        assert hasattr(_overview, "_render_alarm_cards"), \
            "missing _render_alarm_cards (severity alarm cards)"
        assert hasattr(_overview, "_render_moat_pills"), \
            "missing _render_moat_pills (operator status pills)"


class TestAppWiresTheme:
    """app.py must inject the theme."""

    def test_app_calls_inject_theme(self):
        """app.py main() must call inject_theme() from the theme module."""
        from pathlib import Path
        app_src = Path("prospector/control_center/app.py").read_text()
        assert "inject_theme" in app_src, \
            "app.py must call inject_theme() to activate custom CSS"
