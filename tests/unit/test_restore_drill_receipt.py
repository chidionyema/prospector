"""The restore drill leaves proof it ran.

DAT-2 asks "when did a restore last work". Before this receipt the only answer was whatever was
in a terminal at the time, which is not an answer a console can read, and not one that survives
the session it was printed in.

The load-bearing case is the failing drill. A receipt written only on success turns a broken
restore into a screen that says "never run" — which reads as nothing happened, not as something
broke. So both outcomes write, and the receipt carries `ok`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_NAME = "restore_drill_under_test"


def _module():
    """Load `scripts/restore_drill.py` by path. It is a script, not a package module.

    The module MUST be in `sys.modules` before `exec_module` runs. `@dataclass` resolves an
    `InitVar` annotation through `sys.modules[cls.__module__]`, and on a module that is not
    registered yet that lookup returns None and the import dies inside dataclasses.py.
    """
    if _NAME in sys.modules:
        return sys.modules[_NAME]
    spec = importlib.util.spec_from_file_location(_NAME, REPO / "scripts" / "restore_drill.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[_NAME]
        raise
    return mod


def test_receipt_lands_where_the_data_screen_reads_it(tmp_path):
    drill = _module()
    path = drill.write_receipt(tmp_path, ok=True, took_s=3.14, report="RESTORE_DRILL PASS\nmore")

    # The Data view reads exactly this path under the store root. If one of the two moves, the
    # screen silently reports "never run" forever, so the two are pinned to each other.
    from prospector.ops.data import DRILL_RECEIPT

    assert path == tmp_path / "ops" / "restore_drill.json"
    assert DRILL_RECEIPT == Path("store") / "ops" / "restore_drill.json"

    rec = json.loads(path.read_text())
    assert rec["ok"] is True
    assert rec["took_s"] == 3.1
    assert rec["what"] == "RESTORE_DRILL PASS"
    assert rec["ran_at"].endswith("Z")


def test_a_failed_drill_still_writes_its_receipt(tmp_path):
    drill = _module()
    path = drill.write_receipt(tmp_path, ok=False, took_s=1.0, report="RESTORE_DRILL FAIL\nwhy")
    rec = json.loads(path.read_text())
    assert rec["ok"] is False
    assert rec["what"] == "RESTORE_DRILL FAIL"


def test_the_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    drill = _module()
    drill.write_receipt(tmp_path, ok=True, took_s=1.0, report="RESTORE_DRILL PASS")
    drill.write_receipt(tmp_path, ok=True, took_s=2.0, report="RESTORE_DRILL PASS")
    assert sorted(p.name for p in (tmp_path / "ops").iterdir()) == ["restore_drill.json"]
