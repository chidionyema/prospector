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

import ast
import os
import re
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
    # kubectl carries kustomize; the crew#248 scheduler test renders the oke overlay with it.
    "kubectl": "azure/setup-kubectl",
    # git is on every runner image, but the row is not a formality: the checkout step is
    # what makes the repo a git repo at all, and a test that reads the index needs both.
    "git": "actions/checkout",
    # The apt package `age` ships both binaries. The recipients tests decrypt real
    # ciphertext, which a fake age cannot prove.
    "age": "Install age",
    "age-keygen": "Install age",
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
        "no test declares `pytest.mark.needs_tool(...)` any more. The node-executed proofs of "
        "main-admission-guard.yml went with that workflow on 2026-08-21; if pr-keeper.yml's "
        "were deleted too this whole file is measuring nothing, and if they were merely "
        "renamed, point it at them."
    )

    unmapped = sorted(t for t in named if t not in INSTALLED_BY)
    assert not unmapped, (
        f"no row in INSTALLED_BY for {unmapped}. Add the step to ci.yml's python job that puts it "
        "on PATH, then add the row here, or the test errors on every CI run."
    )

    steps = yaml.safe_dump(_python_job()["steps"])
    for tool in sorted(named):
        assert INSTALLED_BY[tool] in steps, (
            f'tests declare `needs_tool("{tool}")` but ci.yml\'s python job no longer runs '
            f"{INSTALLED_BY[tool]}. Without it those tests error on every CI run. Put the step "
            "back, or stop needing the tool."
        )


def _path_without(tool: str) -> str:
    keep = [
        d
        for d in os.environ.get("PATH", "").split(os.pathsep)
        if d and not (Path(d) / tool).exists()
    ]
    return os.pathsep.join(keep)


def _run_without_node(module: str, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in {"CI", "GITHUB_ACTIONS"}}
    env["PATH"] = _path_without("node")
    env["PYTHONPATH"] = str(ROOT)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "pytest", module, "-q", "-n", "0", "-p", "no:cacheprovider"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


# One module per spelling. The marker is read during setup, so a missing tool is reported as an
# ERROR; `require_tool` runs inside the test body, so it is reported as a FAILURE. Different
# words, same consequence, which is the only part that matters: the job cannot be green while
# the test did not run.
_MARKED = "tests/unit/test_pr_keeper.py"
_HELPER_GATED = "tests/unit/test_only_our_own_parked_runs_are_approved.py"


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


# --------------------------------------------------------------------------------------------
# The hole the marker did not cover: a test that never declares the tool at all
# --------------------------------------------------------------------------------------------
#
# WHAT PAID FOR THIS SECTION. 2026-08-21, PR #544: `tests/ops/test_every_console_knob_is_live.py`
# shelled out to `rg` once per knob. ripgrep is on the founder's laptop and is not in
# `deploy/runner/Dockerfile`, so the local POPDD gate said `Verdict: PASS` with 7437 passed and
# the same commit produced 61 failures on the runner -- `FileNotFoundError: [Errno 2] No such
# file or directory: 'rg'` (run 32444675763, job 96665192946).
#
# Everything above this line grades tests that DECLARE a tool and then skip. This one had no
# marker and no skipif; it simply ran a binary and assumed it was there. The marker cannot help
# a test that never says the tool's name, and the local gate structurally cannot catch it,
# because the laptop is the box that has the tool.

#: Present on every runner image, so a test may use them without declaring anything. The basis
#: for each is a fact rather than a habit: `git` is `INSTALLED_BY` above via actions/checkout,
#: and `deploy/runner/Dockerfile` runs its own build steps through `bash`/`sh`, which is proof
#: those exist in the image it produces. `true` is coreutils, present in any Linux base.
_ON_EVERY_RUNNER_IMAGE = {"git", "bash", "sh", "true"}

#: (test file, binary) pairs that run an external name the runner does not have, WITH the reason
#: it is safe. This is a debt list, not a waiver: every row has to say why the CI runner is not
#: about to fail on it. Adding a row without a real reason is how `rg` would come back.
_FAKED_ON_PATH_BY_THE_TEST = {
    (
        "tests/unit/test_secrets_set_reads_stdin.py",
        "age",
    ): "the fixture puts a FAKE `age` and `age-keygen` on PATH, so the file needs no binary "
    "installed and runs identically on a laptop and a runner. The fake also records the "
    "argv it was called with, which is the only way to prove the secret value never "
    "reaches a command line -- real encryption could not prove that.",
}


def _external_binaries(path: Path) -> set[str]:
    """Every bare binary name this test file hands to subprocess, from its AST.

    Only `subprocess.<call>([...])` with a literal string first element counts. A local helper
    named `run` is not subprocess, `sys.executable` is not a literal, and anything with a `/` in
    it is a path the test built and therefore already knows the location of.
    """
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except (OSError, SyntaxError):
        return set()
    found = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        fn = node.func
        if not (
            isinstance(fn, ast.Attribute)
            and fn.attr in {"run", "Popen", "check_output", "check_call", "call"}
            and isinstance(fn.value, ast.Name)
            and fn.value.id in {"subprocess", "sp"}
        ):
            continue
        argv = node.args[0]
        if isinstance(argv, ast.List) and argv.elts and isinstance(argv.elts[0], ast.Constant):
            first = argv.elts[0].value
            if isinstance(first, str) and first and "/" not in first:
                found.add(first)
    return found


@pytest.mark.parametrize("path", _test_sources(), ids=lambda p: p.name)
def test_no_test_runs_a_binary_it_never_declared(path):
    """A test may only shell out to a name CI is known to have, or one it declares.

    THE PROXY IS STATED RATHER THAN HIDDEN: the `needs_tool` names are matched anywhere in the
    file, not resolved per test item. A file that declares a tool for one test and uses it in
    another passes here. That is deliberate -- the failure this closes is a binary NAMED NOWHERE
    in the file, and per-item marker resolution through the AST would be a second, more fragile
    thing to be wrong about.
    """
    rel = path.relative_to(ROOT).as_posix()
    if path.name in _NOT_A_DECLARATION:
        pytest.skip("this file quotes the spellings it grades")
    declared = set(re.findall(r"needs_tool\(\s*['\"]([A-Za-z0-9_.-]+)['\"]", path.read_text()))
    for tool in sorted(_external_binaries(path)):
        if tool in _ON_EVERY_RUNNER_IMAGE or tool in INSTALLED_BY or tool in declared:
            continue
        if (rel, tool) in _FAKED_ON_PATH_BY_THE_TEST:
            continue
        pytest.fail(
            f"{rel} runs `{tool}` and never says so. It is not in INSTALLED_BY, not in "
            f"_ON_EVERY_RUNNER_IMAGE, and the file carries no needs_tool({tool!r}). On the "
            f"founder's laptop that passes; on the runner it is FileNotFoundError. Either mark "
            f"the test `@pytest.mark.needs_tool({tool!r})` and add a row to INSTALLED_BY saying "
            f"what installs it, or stop shelling out -- `rg` was replaced by "
            f"tests/unit/repo_files.py plus a re.compile, which is faster anyway."
        )
