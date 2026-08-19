"""A console view that nothing imports is a screen that does not exist.

The incident, 2026-08-19. `prospector/ops/automations_view.py` was written, documented and
tested. It discovered every automation, ran each one for real, and returned a sorted list with
`needs_attention` on the front. It was reachable from nothing: not `console_api.READS`, not the
browser's `VIEWS` allow-list, not a page. So log rotation could be scheduled, running every six
hours and freeing a gigabyte, while the console showed no sign that any automation existed. The
same class already has a memory file (`built-and-unreachable-is-the-cockpit-defect-class.md`);
this is the first mechanical guard for it in this repo.

Why the guard is a naming rule and not a call graph. Every registered read imports its module
INSIDE the function body, so a static import graph sees nothing. What is stable is the name:
`prospector/ops/<x>_view.py` is a console view by construction, and `console_api.py` is the only
door. Naming a file `*_view.py` is therefore a claim that the console serves it, and this test
makes the claim falsifiable. A helper that is genuinely not a console view should not carry the
suffix.

The existing parity test (`tests/unit/test_console_tools_run.py`) covers the next link:
everything in `READS` is in the browser allow-list and back. Together the two mean a view module
cannot stop short of the browser.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "prospector" / "ops"
CONSOLE_API = OPS / "console_api.py"


def _view_modules() -> list[str]:
    return sorted(p.stem for p in OPS.glob("*_view.py"))


def test_the_repo_actually_has_view_modules_to_check():
    """A guard that iterates an empty list passes and proves nothing."""
    assert len(_view_modules()) >= 3, _view_modules()


def test_every_view_module_is_reachable_from_the_console_api():
    source = CONSOLE_API.read_text(encoding="utf-8")
    orphans = [name for name in _view_modules() if name not in source]
    assert orphans == [], (
        f"{orphans} live in prospector/ops/ and nothing in console_api.py mentions them. "
        f"A view module with no caller is a screen the operator cannot open. Register it in "
        f"READS (and in the browser VIEWS allow-list, which the parity test then checks), or "
        f"rename it if it is not a console view.")


def test_the_automations_view_in_particular_is_registered():
    """The instance that produced the rule. Named, so a regression says which screen went dark."""
    from prospector.ops.console_api import READS

    assert "automations" in READS


def test_the_automations_view_is_in_the_browser_allow_list():
    """`READS` alone is the CLI. The browser has its own allow-list and they must agree."""
    allow = (ROOT / "store_platform" / "src" / "Ops.Console" / "src" / "pages" / "api" / "ops"
             / "read" / "[view].ts")
    text = allow.read_text(encoding="utf-8")
    listed = set(re.findall(r"^\s*'([a-z_]+)',\s*$", text, flags=re.MULTILINE))
    assert "automations" in listed, sorted(listed)


def test_a_page_renders_the_automations_view():
    """Served is not shown. `content_rules` was registered on both sides and on no page for weeks."""
    page = (ROOT / "store_platform" / "src" / "Ops.Console" / "src" / "pages" / "processes.tsx")
    assert "useOps<AutomationsView>('automations'" in page.read_text(encoding="utf-8")
