"""The automations console view must fire on the broken state, not only pass on the clean one.

R4: a guard that has never been seen to fail is not known to work. So every test here builds a
fake checkout with fake automations and asserts the line the operator would actually read.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from prospector.ops.automations_view import discover, read_automations, run_one


def _checkout(tmp_path: Path) -> Path:
    (tmp_path / "ops" / "automations").mkdir(parents=True)
    (tmp_path / "ops" / "config").mkdir(parents=True)
    (tmp_path / "ops" / "automations" / "__init__.py").write_text("")
    return tmp_path


def _automation(root: Path, name: str, body: str, *, declare: bool = True) -> None:
    (root / "ops" / "automations" / f"{name}.py").write_text(textwrap.dedent(body))
    if declare:
        (root / "ops" / "config" / f"{name}.yaml").write_text("targets: []\n")


CLEAN = """
    import json, sys
    print(json.dumps({"automation": "greenish", "status": "ok", "checked": 3,
                      "findings": [], "ran_at": "2026-08-16T00:00:00Z",
                      "probe": "python -m ops.automations.greenish"}))
    sys.exit(0)
"""

BROKEN = """
    import json, sys
    print(json.dumps({"automation": "reddish", "status": "findings", "checked": 2,
                      "findings": [{"where": "somewhere", "what": "a thing is wrong"}],
                      "ran_at": "2026-08-16T00:00:00Z", "probe": "x"}))
    sys.exit(1)
"""

CANNOT_TELL = """
    import sys
    print("", end="")
    sys.exit(2)
"""

CRASHES = """
    raise RuntimeError("the engine blew up before it could print anything")
"""


def test_a_findings_exit_shows_as_findings_with_its_findings(tmp_path):
    root = _checkout(tmp_path)
    _automation(root, "reddish", BROKEN)
    line = run_one("reddish", root)
    assert line["status"] == "findings"
    assert line["findings"] == [{"where": "somewhere", "what": "a thing is wrong"}]


def test_a_clean_exit_shows_as_ok(tmp_path):
    root = _checkout(tmp_path)
    _automation(root, "greenish", CLEAN)
    assert run_one("greenish", root)["status"] == "ok"


def test_exit_two_is_unknown_and_never_ok(tmp_path):
    """P6: an empty result and a failed check must not share a code path."""
    root = _checkout(tmp_path)
    _automation(root, "murky", CANNOT_TELL)
    line = run_one("murky", root)
    assert line["status"] == "unknown"
    assert line["status"] != "ok"


def test_a_crashing_automation_is_unknown_and_says_why(tmp_path):
    """A traceback is not a clean run. The line must carry the last line of stderr."""
    root = _checkout(tmp_path)
    _automation(root, "explodes", CRASHES)
    line = run_one("explodes", root)
    assert line["status"] == "unknown"
    assert "the engine blew up" in (line["error"] or "")


def test_a_slow_automation_times_out_as_unknown(tmp_path):
    root = _checkout(tmp_path)
    _automation(root, "slow", "import time\ntime.sleep(30)\n")
    line = run_one("slow", root, timeout_s=1.0)
    assert line["status"] == "unknown"
    assert "did not answer" in (line["error"] or "")


def test_discovery_needs_both_an_engine_and_a_declaration(tmp_path):
    root = _checkout(tmp_path)
    _automation(root, "complete", CLEAN)
    _automation(root, "engine_only", CLEAN, declare=False)
    (root / "ops" / "config" / "orphan_yaml.yaml").write_text("targets: []\n")
    assert discover(root) == ["complete"]


def test_the_screen_sorts_trouble_above_green(tmp_path):
    root = _checkout(tmp_path)
    _automation(root, "aaa_green", CLEAN)
    _automation(root, "zzz_red", BROKEN)
    doc = read_automations(None, {"root": str(root)})
    # The payload's own `automation` name wins over the file name, which is why these read
    # "reddish"/"greenish" rather than the module names.
    assert [row["automation"] for row in doc["automations"]] == ["reddish", "greenish"]
    assert doc["needs_attention"] == 1
    assert doc["count"] == 2


def test_a_checkout_with_no_automations_is_empty_not_broken(tmp_path):
    """A merge that has not landed the engines yet is a valid state, not a red line."""
    root = _checkout(tmp_path)
    doc = read_automations(None, {"root": str(root)})
    assert doc["count"] == 0
    assert doc["automations"] == []
    assert "note" in doc
