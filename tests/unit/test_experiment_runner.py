"""Cover tools/experiments/runner.py with fake experiment modules written into tmp_path.

Everything here runs against modules this test writes itself. Nothing touches store/, nothing
imports a real experiment, and nothing writes into tools/experiments/ — a harness test that
scribbles receipts next to the real ones is how a receipt stops being evidence.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

RUNNER_PATH = Path(__file__).resolve().parents[2] / "tools" / "experiments" / "runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("_test_experiment_runner", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


GOOD = '''
"""A fake experiment that exists only for the harness test."""
NAME = "X1"
DOC_REF = "docs/FAKE.md §0"


def describe():
    return "a fake experiment"


def run(args):
    return {
        "title": "fake result",
        "verdict": "BUILD" if "--build" in args else "DO NOT BUILD",
        "population": "3 fabricated rows",
        "headline": {"rows": 3, "share": 0.25},
        "limitations": ["it is fake"],
        "args_seen": list(args),
    }
'''

NO_DESCRIBE = '''
"""First docstring line is the fallback description.

More prose that must not appear in the one-liner.
"""
NAME = "X2"


def run(args):
    return {"headline": {"n": 1}}
'''

LEGACY = '''
"""An old-style script with only main() — discoverable but not registered."""


def main():
    return 0
'''

NAME_NO_RUN = '''
NAME = "X3"
'''

BAD_RETURN = '''
NAME = "X4"


def run(args):
    return "not a dict"
'''

IMPORT_BOOM = '''
NAME = "X5"
raise RuntimeError("import-time explosion")
'''

SUFFIXED = '''
NAME = "X6"


def run(args):
    return {"headline": {"n": 2}, "_receipt_suffix": "_scoped"}
'''

CUSTOM_DOC = '''
NAME = "X7"


def run(args):
    return {"headline": {"n": 1}}


def doc_block(receipts):
    return "CUSTOM BLOCK for " + receipts["_meta"]["experiment"]
'''


@pytest.fixture()
def expdir(tmp_path: Path) -> Path:
    d = tmp_path / "experiments"
    d.mkdir()
    (d / "x1_good.py").write_text(GOOD)
    (d / "x2_nodescribe.py").write_text(NO_DESCRIBE)
    (d / "legacy_main_only.py").write_text(LEGACY)
    (d / "_helper.py").write_text("raise RuntimeError('helpers must never be imported')\n")
    return d


# --- discovery ---------------------------------------------------------------------------------

def test_discover_registers_by_name_and_skips_helpers_and_legacy(expdir: Path):
    reg = runner.discover(expdir)
    assert set(reg) == {"X1", "X2"}, "legacy main()-only and _helper.py must not register"
    assert reg["X1"].registered
    assert reg["X1"].stem == "x1_good"


def test_describe_falls_back_to_first_docstring_line(expdir: Path):
    reg = runner.discover(expdir)
    assert reg["X1"].describe() == "a fake experiment"
    assert reg["X2"].describe() == "First docstring line is the fallback description."


def test_discover_reports_import_failure_instead_of_hiding_it(expdir: Path):
    (expdir / "x5_boom.py").write_text(IMPORT_BOOM)
    reg = runner.discover(expdir)
    assert "X5_BOOM" in reg, "a module that fails to import must still be listed"
    assert not reg["X5_BOOM"].registered
    assert "import-time explosion" in reg["X5_BOOM"].error


def test_name_without_run_is_flagged_not_dropped(expdir: Path):
    (expdir / "x3_norun.py").write_text(NAME_NO_RUN)
    reg = runner.discover(expdir)
    assert not reg["X3"].registered
    assert "no callable run" in reg["X3"].error


def test_discover_defaults_to_the_real_experiments_directory():
    reg = runner.discover()
    assert {"E12", "E15", "E17", "L1"} <= set(reg), sorted(reg)
    assert all(reg[k].registered for k in ("E12", "E15", "E17", "L1"))


# --- resolution --------------------------------------------------------------------------------

def test_resolve_accepts_name_case_insensitively_and_by_file_stem(expdir: Path):
    reg = runner.discover(expdir)
    assert runner.resolve("x1", reg).name == "X1"
    assert runner.resolve("X1", reg).name == "X1"
    assert runner.resolve("x1_good", reg).name == "X1"


def test_resolve_unknown_name_lists_what_it_knows(expdir: Path):
    reg = runner.discover(expdir)
    with pytest.raises(runner.ExperimentError) as exc:
        runner.resolve("nope", reg)
    assert "X1" in str(exc.value) and "X2" in str(exc.value)


# --- running -----------------------------------------------------------------------------------

def test_run_one_writes_receipts_and_doc_append(expdir: Path, tmp_path: Path):
    out = tmp_path / "out"
    result = runner.run_one("X1", ["--build"], expdir, out)

    receipts_path = result["receipts_path"]
    doc_path = result["doc_append_path"]
    assert receipts_path.name == "x1_good_receipts.json"
    assert doc_path.name == "x1_good_doc_append.md"

    payload = json.loads(receipts_path.read_text())
    assert payload["verdict"] == "BUILD"
    assert payload["args_seen"] == ["--build"], "args must reach run() verbatim"
    assert payload["_meta"]["experiment"] == "X1"
    assert payload["_meta"]["argv"] == ["--build"]
    assert payload["_meta"]["run_at_utc"].endswith("+00:00")
    assert "_receipt_suffix" not in payload

    md = doc_path.read_text()
    assert md.startswith("### X1 — fake result")
    assert "- **rows**: 3" in md
    assert "**Verdict:** BUILD" in md
    assert "docs/FAKE.md §0" in md
    assert "it is fake" in md
    assert md.endswith("\n")


def test_run_one_honours_receipt_suffix(expdir: Path, tmp_path: Path):
    (expdir / "x6_suffix.py").write_text(SUFFIXED)
    result = runner.run_one("X6", [], expdir, tmp_path / "out")
    assert result["receipts_path"].name == "x6_suffix_scoped_receipts.json"
    assert result["doc_append_path"].name == "x6_suffix_scoped_doc_append.md"


def test_run_one_uses_a_module_supplied_doc_block(expdir: Path, tmp_path: Path):
    (expdir / "x7_custom.py").write_text(CUSTOM_DOC)
    result = runner.run_one("X7", [], expdir, tmp_path / "out")
    assert result["doc_append_path"].read_text().strip() == "CUSTOM BLOCK for X7"


def test_run_one_rejects_a_non_dict_return(expdir: Path, tmp_path: Path):
    (expdir / "x4_bad.py").write_text(BAD_RETURN)
    with pytest.raises(runner.ExperimentError, match="must return a dict"):
        runner.run_one("X4", [], expdir, tmp_path / "out")


def test_run_one_refuses_an_unrunnable_experiment(expdir: Path, tmp_path: Path):
    (expdir / "x5_boom.py").write_text(IMPORT_BOOM)
    with pytest.raises(runner.ExperimentError, match="not runnable"):
        runner.run_one("X5_BOOM", [], expdir, tmp_path / "out")


def test_run_one_defaults_receipts_next_to_the_module(expdir: Path):
    result = runner.run_one("X2", [], expdir)
    assert result["receipts_path"].parent == expdir


def test_runner_never_writes_to_the_programme_doc(expdir: Path, tmp_path: Path):
    """The doc has an owner. The runner emits a paste-ready block and nothing else."""
    doc = tmp_path / "COMMERCIAL_READINESS_PROGRAM.md"
    doc.write_text("# untouched\n")
    before = doc.read_text()
    runner.run_one("X1", [], expdir, tmp_path / "out")
    assert doc.read_text() == before
    assert "COMMERCIAL_READINESS_PROGRAM" not in RUNNER_PATH.read_text().replace(
        "docs/COMMERCIAL_READINESS_PROGRAM.md", ""), \
        "runner.py may name the doc in prose but must never open it"


# --- cli ---------------------------------------------------------------------------------------

def test_cli_list_shows_registered_broken_and_legacy(expdir: Path, capsys):
    (expdir / "x5_boom.py").write_text(IMPORT_BOOM)
    assert runner.main(["--dir", str(expdir), "list"]) == 0
    out = capsys.readouterr().out
    assert "X1" in out and "a fake experiment" in out
    assert "broken / half-registered" in out and "import-time explosion" in out
    assert "legacy_main_only.py" in out


def test_cli_describe(expdir: Path, capsys):
    assert runner.main(["--dir", str(expdir), "describe", "x1"]) == 0
    out = capsys.readouterr().out
    assert "a fake experiment" in out and "docs/FAKE.md §0" in out


def test_cli_run_prints_both_paths(expdir: Path, tmp_path: Path, capsys):
    rc = runner.main(["--dir", str(expdir), "--out-dir", str(tmp_path / "o"), "run", "X1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "x1_good_receipts.json" in out
    assert "x1_good_doc_append.md" in out
    assert "does NOT edit docs/COMMERCIAL_READINESS_PROGRAM.md" in out


def test_cli_forwards_trailing_args_to_the_experiment(expdir: Path, tmp_path: Path):
    out = tmp_path / "o"
    assert runner.main(["--dir", str(expdir), "--out-dir", str(out), "run", "X1", "--build"]) == 0
    payload = json.loads((out / "x1_good_receipts.json").read_text())
    assert payload["args_seen"] == ["--build"]
    assert payload["verdict"] == "BUILD"


def test_cli_unknown_experiment_exits_2(expdir: Path, capsys):
    assert runner.main(["--dir", str(expdir), "run", "nope"]) == 2
    assert "unknown experiment" in capsys.readouterr().err
