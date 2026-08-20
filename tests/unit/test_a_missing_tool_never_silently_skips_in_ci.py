"""A test that needs an external binary must never disappear from CI when the binary is absent.

WHAT PAID FOR THIS FILE. `tests/unit/test_main_admission_guard.py` and `tests/unit/test_pr_keeper.py`
prove their workflows by EXECUTING them: they lift the `github-script` body out of the YAML and run
it in node against a stubbed Octokit. Between them that is 67 tests, and they are the only
executable proof that main's admission guard decides correctly — every other assertion about those
two workflows is a string in a YAML file.

Both modules opened with `pytest.mark.skipif(shutil.which("node") is None)`. `deploy/runner/Dockerfile`
installs no language runtimes on purpose ("every toolchain arrives through an action that fetches its
own copy"), and `ci.yml`'s python job never called setup-node. So `node` was not on PATH on the
runner, and all 67 tests skipped on every run since the fleet moved onto our own image. The job was
green throughout. Measured on this tree with node off PATH: `67 skipped in 10.92s`.

THE CLASS is a test that answers "the tool is missing" with the same colour as "the code is correct".
A missing binary normally fails at exit 127, which is loud. Wrapped in a skip it fails as nothing at
all: `-q` prints an `s`, no annotation is written, and nobody counts them. Same shape as pytest
exiting 0 on a run that collected nothing, and as an empty log read as a clean negative.

THE CLOSE, in the order the laws ask for it:

  refuse  `tests/conftest.py::_require_tools` turns a missing tool into an ERROR under CI and
          leaves it a skip on a laptop, where "I do not have node installed" is a fact about the
          box rather than a hole in a gate.
  test    this file, so a new module cannot reintroduce the skipif spelling, and so deleting the
          setup step from ci.yml fails here rather than quietly stopping 67 tests.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
CI = ROOT / ".github" / "workflows" / "ci.yml"

# A tool a test may declare with `needs_tool`, and the thing in ci.yml's python job that puts it
# on PATH there. Adding a row is how you say "CI installs this"; a marker naming a tool with no
# row fails below, because the alternative is a test that silently stops running in CI.
INSTALLED_BY: dict[str, str] = {
    "node": "actions/setup-node",
    # git is on every runner image, but the row is not a formality: the checkout step is
    # what makes the repo a git repo at all, and a test that reads the index needs both.
    "git": "actions/checkout",
}

# This file's own assertions quote both the banned spelling and the marker, and `conftest.py`
# defines them. Neither is a declaration, so both are read past rather than graded.
_NOT_A_DECLARATION = {
    "test_a_missing_tool_never_silently_skips_in_ci.py",
    "conftest.py",
    "tool_gate.py",
}


def _test_sources() -> list[Path]:
    return [p for p in TESTS.rglob("*.py") if "__pycache__" not in p.parts]


def _code_lines(path: Path) -> list[str]:
    """Source with whole-line comments dropped.

    The two modules this file exists for now carry a comment SAYING not to use the skipif
    spelling, so a whole-file text scan finds the words it is looking for in the very warning
    against them and fails the files that were fixed. Grade code, not prose.
    """
    return [ln for ln in path.read_text().splitlines() if not ln.lstrip().startswith("#")]


def _python_job() -> dict:
    return yaml.safe_load(CI.read_text())["jobs"]["python"]


def test_no_test_gates_itself_on_a_missing_binary():
    """Both spellings, because the first sweep found only one of them.

    `pytestmark = pytest.mark.skipif(shutil.which("node") is None)` deleted 67 tests. Searching
    for that shape finds exactly the two files that use it and reports the class closed, which is
    what happened here. A peer session then ran the suite with node genuinely off PATH and
    measured `12 passed, 26 skipped` across three MORE files, against `38 passed` with node
    present. Those three called `shutil.which` inside their own harness function (`_run`,
    `_decide`) and skipped from there, at run time, where no marker and no search for a marker
    can see it.

    So the rule is about the PAIR, wherever in a file it appears: deciding from `shutil.which`
    that a test should not run is the thing that goes silent in CI. `tests/tool_gate.py` is the
    one place that pair may live.
    """
    offenders = []
    for path in _test_sources():
        if path.name in _NOT_A_DECLARATION:
            continue
        code = "\n".join(_code_lines(path))
        if "shutil.which(" not in code:
            continue
        if "skipif" in code or "pytest.skip(" in code:
            offenders.append(path.relative_to(ROOT))
    assert not offenders, (
        "these files decide from `shutil.which(...)` that a test should not run, which is "
        "invisible in CI: "
        + ", ".join(str(p) for p in offenders)
        + '. Use `pytestmark = pytest.mark.needs_tool("<binary>")`, or call '
        + '`require_tool("<binary>")` from the helper that needs the binary. Both skip on a '
        + "laptop and ERROR on a CI runner, where a missing tool is a hole in the gate."
    )


def test_every_tool_a_test_needs_is_installed_by_the_job_that_runs_it():
    """A `needs_tool` marker naming something CI does not install is a test that only ever errors."""
    named = set()
    for path in _test_sources():
        if path.name in _NOT_A_DECLARATION:
            continue
        for line in _code_lines(path):
            # Two legal spellings, and the ci.yml linkage below has to cover both. The marker
            # gates a whole module; `require_tool` gates the helper that actually shells out,
            # which is what a file needs when only some of its tests touch the binary.
            for opener in ("pytest.mark.needs_tool(", "require_tool("):
                if opener not in line:
                    continue
                inside = line.split(opener, 1)[1].split(")")[0]
                named.update(
                    part.strip().strip("\"'") for part in inside.split(",") if part.strip()
                )
    assert named, (
        "no test declares `pytest.mark.needs_tool(...)` any more. If the node-executed proofs of "
        "main-admission-guard.yml and pr-keeper.yml were deleted, this whole file is measuring "
        "nothing; if they were merely renamed, point it at them."
    )

    unmapped = sorted(t for t in named if t not in INSTALLED_BY)
    assert not unmapped, (
        f"no row in INSTALLED_BY for {unmapped}. Add the step to ci.yml's python job that puts it "
        "on PATH, then add the row here, or the test errors on every CI run."
    )

    steps = yaml.safe_dump(_python_job()["steps"])
    for tool in sorted(named):
        assert INSTALLED_BY[tool] in steps, (
            f"tests declare `needs_tool(\"{tool}\")` but ci.yml's python job no longer runs "
            f"{INSTALLED_BY[tool]}. Without it those tests error on every CI run. Put the step "
            "back, or stop needing the tool."
        )


def _path_without(tool: str) -> str:
    keep = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not (Path(d) / tool).exists()]
    return os.pathsep.join(keep)


def _run_without_node(module: str, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in {"CI", "GITHUB_ACTIONS"}}
    env["PATH"] = _path_without("node")
    env["PYTHONPATH"] = str(ROOT)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "pytest", module, "-q", "-n", "0", "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )


# One module per spelling. The marker is read during setup, so a missing tool is reported as an
# ERROR; `require_tool` runs inside the test body, so it is reported as a FAILURE. Different
# words, same consequence, which is the only part that matters: the job cannot be green while
# the test did not run.
_MARKED = "tests/unit/test_pr_keeper.py"
_HELPER_GATED = "tests/unit/test_the_green_guard_reverts_the_cause_not_the_head.py"


@pytest.mark.parametrize(
    "module, env_extra, expect",
    [
        (_MARKED, {}, "skipped"),
        (_MARKED, {"CI": "true"}, "error"),
        (_HELPER_GATED, {}, "skipped"),
        (_HELPER_GATED, {"CI": "true"}, "failed"),
    ],
    ids=[
        "a marked module on a laptop skips",
        "a marked module on a CI runner errors",
        "a helper-gated module on a laptop skips",
        "a helper-gated module on a CI runner fails",
    ],
)
def test_the_gate_behaves_differently_on_a_laptop_and_on_a_runner(module, env_extra, expect):
    """The whole point, executed rather than asserted about.

    Run a real gated module with node taken off PATH. Off CI it must skip, so nobody is walled
    for not having a runtime they do not need. On CI it must fail, because a green job that
    measured nothing is the failure this file exists to stop.
    """
    proc = _run_without_node(module, env_extra)
    tail = (proc.stdout or "")[-2000:]
    assert expect in tail, f"expected {expect!r} in the summary, got:\n{tail}\n{proc.stderr[-800:]}"
    if expect != "skipped":
        assert proc.returncode != 0, "a CI runner missing a tool must fail the job, not pass it"
    else:
        assert proc.returncode == 0, f"a laptop without node must not be walled:\n{tail}"
