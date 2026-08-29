"""When a subprocess fails, the text explaining WHY must survive into what we log.

WHY THIS EXISTS. Measured 2026-08-19. `scripts/worktree_snapshot.py::git` returned
`(p.stdout or p.stderr)`, which drops stderr whenever stdout is non-empty. A `git push` of 17
snapshot refs was REJECTED; the pre-push hook had already written one line to stdout; so the
rejection printed nothing and the run ended on a tick that read as success. The backups had not
happened, and the next step in that session was to discard the 60 files those snapshots existed to
protect. The green tick was the only evidence, and it was wrong.

The SAME one-line shape sat on both diagnostic tails in the scheduler
(`prospector/scheduler/run_scheduled.py`), including the one logged next to the words "killed
pack(s) may still be selling" -- so a drain that printed progress and then raised would log the
progress and swallow the traceback.

The class is A HELPER THAT DISCARDS THE STDERR EXPLAINING ITS OWN DEATH. Two behavioural tests pin
the two helpers, and one AST guard refuses the shape anywhere else, because the next agent to write
it will not have read either helper.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import worktree_snapshot as ws  # noqa: E402

from prospector.scheduler.run_scheduled import _proc_tail  # noqa: E402


def _completed(rc: int, out: str, err: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["git"], returncode=rc, stdout=out, stderr=err)


# --------------------------------------------------------------------------------------
# 1. scripts/worktree_snapshot.py::git
# --------------------------------------------------------------------------------------

def test_a_failed_git_keeps_stderr_even_when_stdout_spoke_first(monkeypatch, tmp_path):
    """The exact 2026-08-19 shape: a hook writes to stdout, then the push is rejected."""
    monkeypatch.setattr(ws.subprocess, "run",
                        lambda *a, **k: _completed(1, "pre-push: checked 17 refs",
                                                   "! [remote rejected] snapshot -> snapshot"))
    rc, out = ws.git(["push"], tmp_path)
    assert rc == 1
    assert "remote rejected" in out, f"the reason was discarded: {out!r}"


def test_a_successful_git_returns_stdout_alone(monkeypatch, tmp_path):
    """Callers parse this as a VALUE -- a tree sha, a commit sha, a date. git writes warnings to
    stderr on commands that succeed, and a warning concatenated onto a sha is not a sha."""
    monkeypatch.setattr(ws.subprocess, "run",
                        lambda *a, **k: _completed(0, "df6f0f4ae574f544544e64a35511123a92aacc75",
                                                   "warning: LF will be replaced by CRLF"))
    rc, out = ws.git(["write-tree"], tmp_path)
    assert rc == 0
    assert out == "df6f0f4ae574f544544e64a35511123a92aacc75"


# --------------------------------------------------------------------------------------
# 2. prospector/scheduler/run_scheduled.py::_proc_tail
# --------------------------------------------------------------------------------------

def test_the_drain_tail_keeps_the_traceback_it_was_logged_to_explain():
    tail = _proc_tail(_completed(1, "unlisting 4 packs...", "RuntimeError: shelf write refused"))
    assert "RuntimeError: shelf write refused" in tail


def test_the_drain_tail_is_cut_from_the_end_so_the_reason_survives_the_cut():
    """300 chars, taken off the END. stderr is joined LAST for exactly this reason."""
    tail = _proc_tail(_completed(1, "x" * 5000, "RuntimeError: shelf write refused"))
    assert len(tail) <= 300
    assert "RuntimeError: shelf write refused" in tail


def test_a_successful_drain_tail_is_its_report_not_its_warnings():
    assert _proc_tail(_completed(0, "unlisted 4", "warning: noisy")) == "unlisted 4"


# --------------------------------------------------------------------------------------
# 3. The class guard: the shape is refused everywhere else.
# --------------------------------------------------------------------------------------

def _discarding_or(tree: ast.AST) -> list[int]:
    """`X.stdout or Y.stderr` used AS A VALUE.

    A truthiness TEST (`... if exc.stdout or exc.stderr else ""`) is not this defect -- it asks
    whether either stream spoke and then reads both. So the tests of `if`/`while`/conditional
    expressions are excluded, and everything else is a value that silently loses a stream.
    """
    tests = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.IfExp)):
            tests.add(id(node.test))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
            continue
        if id(node) in tests:
            continue
        attrs = [v.attr for v in node.values if isinstance(v, ast.Attribute)]
        if "stdout" in attrs and "stderr" in attrs and attrs.index("stdout") < attrs.index("stderr"):
            hits.append(node.lineno)
    return hits


@pytest.mark.parametrize("root", ["prospector", "scripts", "ops", "tools"])
def test_no_helper_discards_the_stderr_explaining_its_own_death(root: str):
    offenders = []
    base = ROOT / root
    if not base.exists():
        pytest.skip(f"{root}/ is not in this checkout")
    for path in sorted(base.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for line in _discarding_or(tree):
            offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert not offenders, (
        "`stdout or stderr` used as a value drops the failure reason whenever stdout is "
        "non-empty. Join both on the failure path instead:\n  " + "\n  ".join(offenders))


def test_the_guard_can_actually_see_the_defect():
    """A guard that never fires is not a guard. This is the literal deleted line."""
    bad = ast.parse("def f(p):\n    return p.returncode, (p.stdout or p.stderr).strip()\n")
    assert _discarding_or(bad) == [2]
    ok = ast.parse('def f(e):\n    return (e.stdout or b"") + (e.stderr or b"") '
                   'if e.stdout or e.stderr else ""\n')
    assert _discarding_or(ok) == []
