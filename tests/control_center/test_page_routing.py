"""Page routing invariants — each nav target must be a distinct module."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from prospector.control_center import app as cc_app
from prospector.control_center import pages as pages_mod
from prospector.control_center.components import chrome

# Unique markers that must appear in each page's render() source (hero titles).
_PAGE_MARKERS = {
    "overview": "Overview",
    "catalogue": "Catalogue",
    "launcher": "Launch",
    "diagnostics": "Diagnostics",
    "engine": "Engine",
    "runs": "Runs",
    "metrics": "Outcomes",
    "spend": "Spend",
    "parameters": "Parameters",
    "reports": "Reports",
    "resume": "Resume & Queue",
}


def test_page_modules_map_covers_nav_list():
    nav_keys = {k for _, k in cc_app._PAGES_LIST}
    assert nav_keys == set(cc_app._PAGE_MODULES)
    assert nav_keys == set(_PAGE_MARKERS)


def test_each_page_render_is_distinct_function():
    renders = [mod.render for mod in cc_app._PAGE_MODULES.values()]
    assert len(renders) == len(set(renders))
    for mod in cc_app._PAGE_MODULES.values():
        assert callable(mod.render)


def test_each_page_source_has_unique_hero_marker():
    """Guard against copy-paste homogenization of page modules."""
    for key, marker in _PAGE_MARKERS.items():
        mod = cc_app._PAGE_MODULES[key]
        src = inspect.getsource(mod.render)
        assert f'page_hero("{marker}"' in src or f"page_hero('{marker}'" in src, (
            f"{key}.render() must call page_hero({marker!r})"
        )


def test_go_page_flags_sync_without_touching_nav_radio(monkeypatch):
    """go_page must not assign nav_radio after the radio widget exists."""
    state: dict = {}

    class _SS(dict):
        def __setitem__(self, k, v):
            super().__setitem__(k, v)
            state[k] = v

    ss = _SS()
    monkeypatch.setattr(chrome.st, "session_state", ss)

    reran = {"n": 0}

    def _rerun():
        reran["n"] += 1
        raise SystemExit("rerun")

    monkeypatch.setattr(chrome.st, "rerun", _rerun)

    with pytest.raises(SystemExit, match="rerun"):
        chrome.go_page("launcher")

    assert ss["active_page"] == "launcher"
    assert ss["_sync_nav_radio"] is True
    assert "nav_radio" not in ss
    assert reran["n"] == 1


def test_nav_sync_only_on_flag_not_stale_active_page():
    """Regression: stale active_page must not overwrite a fresh radio click.

    Simulate the pure decision used in app.main (extracted as logic check).
    """
    labels = [p[0] for p in cc_app._PAGES_LIST]
    # User clicked Launch; widget already wrote nav_radio. active_page still overview.
    session = {
        "active_page": "overview",
        "nav_radio": "🚀 Launch",
        # no _sync_nav_radio
    }
    sync = session.pop("_sync_nav_radio", False) or "nav_radio" not in session
    assert sync is False  # must NOT clobber the radio
    selected = session["nav_radio"]
    key = next(p[1] for p in cc_app._PAGES_LIST if p[0] == selected)
    assert key == "launcher"

    # Programmatic go_page path: flag set, radio must follow active_page.
    session2 = {
        "active_page": "diagnostics",
        "nav_radio": "🛰 Overview",
        "_sync_nav_radio": True,
    }
    sync2 = session2.pop("_sync_nav_radio", False) or "nav_radio" not in session2
    assert sync2 is True
    want = next(p[0] for p in cc_app._PAGES_LIST if p[1] == session2["active_page"])
    session2["nav_radio"] = want
    assert session2["nav_radio"] == "🔬 Diagnostics"
    assert labels  # sanity: nav list non-empty


def test_page_package_exports_match_app_modules():
    for key, mod in cc_app._PAGE_MODULES.items():
        assert getattr(pages_mod, f"_{key}") is mod


def test_page_files_are_not_identical_copies():
    root = Path(pages_mod.__file__).parent
    digests = {}
    for key in _PAGE_MARKERS:
        path = root / f"_{key}.py"
        digests[key] = path.read_bytes()
    # Pairwise distinct file bodies
    bodies = list(digests.values())
    assert len(bodies) == len(set(bodies))
