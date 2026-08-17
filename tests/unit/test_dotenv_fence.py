"""The credential fence has to cover the DISK read, not just os.environ.

Background (2026-08-07). `tests/conftest.py::_no_live_payment_credentials` deletes
STRIPE_API_KEY / STRIPE_LIVE_API_KEY so `EngineBridge` cannot build a live provisioner
(`bridge.py:281`). That fence was defeatable: `_load_dotenv` reads `.env` and
`~/.config/llm/secrets.sh` off disk and fills any key *absent* from os.environ — and a key
the fence just deleted is, by construction, absent. Measured by repro: strip both Stripe
keys, call `_load_dotenv()` once, and both are resident again, the live one included.

Two tests here, deliberately different in kind:

  * a BEHAVIOURAL one — under the fence, the real `_load_dotenv` cannot re-arm a stripped
    credential; with the guard cleared it demonstrably does fill gaps, so the assertion is
    not vacuous;
  * a STRUCTURAL one — every `_load_dotenv` implementation in the repo honours the guard.
    Three copies exist (`prospector/run.py`, `scripts/backfill_ladder_prices.py`,
    `scripts/backup_store.py`). Guarding the three that exist today does nothing about the
    fourth someone copies in next month, and this class of leak is invisible when it
    reopens — nothing turns red, the suite just starts talking to Stripe again.
"""
from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

import prospector.run as R

REPO = Path(__file__).resolve().parents[2]

# Money-rail keys the conftest fence deletes. Re-arming ANY of these from disk is the bug.
# The retired second provider's key was dropped from this list on 2026-08-17. The conftest fence
# had already stopped listing it, so the name survived here alone and only the retired-terms guard
# could still see it.
FENCED_KEYS = ("STRIPE_API_KEY", "STRIPE_LIVE_API_KEY", "STORE_INTERNAL_API_KEY")


def _keys_defined_on_disk() -> set[str]:
    """Which fenced keys the env files actually define — read WITHOUT touching os.environ.

    This is the non-vacuity check for the behavioural test below: if `.env` carries no
    Stripe key on this machine, "the key did not come back" proves nothing.
    """
    found: set[str] = set()
    for path in (REPO / ".env", Path(os.path.expanduser("~/.config/llm/secrets.sh"))):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            key, _, _val = line.partition("=")
            if key.strip() in FENCED_KEYS:
                found.add(key.strip())
    return found


def test_load_dotenv_cannot_rearm_a_stripped_credential(monkeypatch):
    """Under the conftest fence, `_load_dotenv()` must not restore a money-rail key.

    The fence (autouse `_no_live_payment_credentials`) is already applied to this test, so
    the preconditions below are assertions about the fence itself, not setup.
    """
    on_disk = _keys_defined_on_disk()
    if not on_disk:
        pytest.skip("no fenced credential is defined in .env or ~/.config/llm/secrets.sh "
                    "on this machine — nothing for _load_dotenv to re-arm, so this "
                    "assertion would be vacuous")

    # Precondition: the fence stripped them, and set the disk guard.
    for key in FENCED_KEYS:
        assert key not in os.environ, f"fence did not strip {key} before the test body ran"
    assert os.environ.get("PROSPECTOR_DISABLE_DOTENV") == "1"

    R._load_dotenv()

    still_absent = [k for k in on_disk if k not in os.environ]
    assert sorted(still_absent) == sorted(on_disk), (
        "_load_dotenv() re-armed a fenced credential from disk: "
        f"{sorted(set(on_disk) - set(still_absent))}. The fence covers os.environ only; "
        "the PROSPECTOR_DISABLE_DOTENV guard at prospector/run.py:2466 is what closes the "
        "file route."
    )


def test_load_dotenv_does_fill_gaps_when_the_guard_is_cleared(tmp_path, monkeypatch):
    """The control that makes the test above non-vacuous.

    Same function, same call, guard cleared — and it fills the gap. Without this, a
    `_load_dotenv` that had been accidentally turned into a no-op would make the fence test
    pass for the wrong reason.

    The env files are redirected at a synthetic key in tmp_path so this control never puts a
    real Stripe key back into the process environment — which is the exact thing being
    fenced. `_load_dotenv` hardcodes both paths, so the redirect is done at the two
    os.path calls it uses to build them, each delegating for every other argument.
    """
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / ".env").write_text(
        "# comment\nexport PROSPECTOR_DOTENV_CANARY=\"loaded-from-disk\"\n", encoding="utf-8")

    real_abspath, real_expanduser = os.path.abspath, os.path.expanduser
    monkeypatch.setattr(
        R.os.path, "abspath",
        lambda p: str(fake_repo / "prospector" / "run.py") if p == R.__file__ else real_abspath(p))
    monkeypatch.setattr(
        R.os.path, "expanduser",
        lambda p: str(tmp_path / "absent-secrets.sh")
        if p == "~/.config/llm/secrets.sh" else real_expanduser(p))

    monkeypatch.delenv("PROSPECTOR_DISABLE_DOTENV", raising=False)
    monkeypatch.delenv("PROSPECTOR_DOTENV_CANARY", raising=False)

    R._load_dotenv()
    assert os.environ.get("PROSPECTOR_DOTENV_CANARY") == "loaded-from-disk", (
        "_load_dotenv() did not fill an absent key from disk even with the guard cleared — "
        "the fence test above is passing for the wrong reason")

    # And with the guard back on, the same call is a no-op.
    monkeypatch.delenv("PROSPECTOR_DOTENV_CANARY", raising=False)
    monkeypatch.setenv("PROSPECTOR_DISABLE_DOTENV", "1")
    R._load_dotenv()
    assert "PROSPECTOR_DOTENV_CANARY" not in os.environ


def _repo_python_files() -> list[Path]:
    """Repo sources only. `.claude/worktrees/` holds other sessions' checkouts of this same
    repo and `.venv/` holds third-party code; neither is ours to gate.

    Ask git, do not walk. `REPO.rglob("*.py")` descends into every skipped directory before
    the filter below can reject it, and in this checkout that is about 169,000 files — 1.7 GB
    of `.claude/worktrees`, 387 MB of `store/`, 120 MB of `graphify-out/`. Filtering the OUTPUT
    does not stop the walk. Measured 2026-08-17: this single test was the slowest in the whole
    suite at 116s, against 542s for all 4180 tests.

    `--cached --others --exclude-standard` is tracked files plus untracked ones git would not
    ignore, so a new source file is still gated the moment it is written, and everything the
    skip list used to remove is already gitignored.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "*.py"],
            cwd=REPO, capture_output=True, text=True, check=True, timeout=60,
        ).stdout
        paths = [REPO / rel for rel in out.split("\0") if rel]
        if paths:
            return paths
    except (OSError, subprocess.SubprocessError):
        pass

    # No git (a tarball, a stripped container). Walk, and accept the cost.
    skip = (".venv", "node_modules", ".claude/worktrees", ".git")
    walked = []
    for p in REPO.rglob("*.py"):
        rel = p.relative_to(REPO).as_posix()
        if any(rel.startswith(s) or f"/{s}/" in f"/{rel}" for s in skip):
            continue
        walked.append(p)
    return walked


def _guards_disable_dotenv(fn: ast.FunctionDef) -> bool:
    """True if the function short-circuits on PROSPECTOR_DISABLE_DOTENV before doing work.

    Checked structurally rather than by substring: the guard has to be an `if` that
    `return`s, and it has to come before anything else executable, or a copy could name the
    variable in a comment and read the file anyway.
    """
    for stmt in fn.body:
        # skip the docstring
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
                and isinstance(stmt.value.value, str):
            continue
        if not isinstance(stmt, ast.If):
            return False
        names = {n.value for n in ast.walk(stmt.test)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        if "PROSPECTOR_DISABLE_DOTENV" not in names:
            return False
        return any(isinstance(s, ast.Return) for s in stmt.body)
    return False


def test_every_load_dotenv_in_the_repo_honours_the_guard():
    """A fourth copy of `_load_dotenv` reopens the hole silently. This is the tripwire.

    If this fails on a file you just added, the fix is four lines at the top of the new
    function, not an exemption here:

        if os.environ.get("PROSPECTOR_DISABLE_DOTENV", "").strip() not in ("", "0", "false", "False"):
            return
    """
    unguarded: list[str] = []
    found = 0
    for path in _repo_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == "_load_dotenv":
                found += 1
                if not _guards_disable_dotenv(node):
                    unguarded.append(f"{path.relative_to(REPO)}:{node.lineno}")

    assert found >= 3, (
        f"expected the three known _load_dotenv implementations, found {found} — this test "
        "has stopped looking where they live and is no longer a tripwire")
    assert not unguarded, (
        "these _load_dotenv implementations fill credentials from disk without honouring "
        f"PROSPECTOR_DISABLE_DOTENV: {unguarded}")
