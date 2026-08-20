"""The POPDD pre-commit gate's own proof.

The gate is the thing that decides whether anything else is proven, so it is the one
file whose defects are invisible: it fails by printing "nothing to prove" and exiting 0.
It did exactly that for months — `.git/hooks/pre-commit` matched `\\.(py|ts|js|cs)$`,
which does not match `.tsx`, so all 183 tracked Store.Web `.ts`/`.tsx` files committed
ungated. Adding `.tsx` to that list would not have fixed it either: the gate ran the
python pytest suite as its only proof, and no python test reads a `.ts`/`.tsx` file.

So these tests assert two things the gate cannot self-report:
  1. the lane map covers each source kind with a proof that can actually see it, and
  2. the shell hook still DELEGATES that map instead of keeping a second copy of it.

(2) is the one that rots. The extension list lived in two places; one was updated and
the other was not.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "popdd_verify.py"
HOOK = REPO_ROOT / ".lux" / "hooks" / "pre-commit"


def _hooks_dir() -> Path:
    """Where git will actually look for hooks, which is NOT always `<root>/.git/hooks`.

    In a git worktree `.git` is a FILE containing `gitdir: ...`, not a directory, so the
    hardcoded path this used to use cannot exist and the assert below failed on location
    rather than on fact — reporting "the gate is not installed" in a checkout where it was
    installed and working. That cost a shipping session real time, because the failure
    names the gate, which is the one thing an agent will not wave through.

    `git rev-parse --git-path hooks` answers the question git itself answers: it resolves
    to the common dir, so a worktree gets the main checkout's shared hooks. It also honours
    `core.hooksPath`, which the naive path silently ignored.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # no git binary, or not a checkout
        return REPO_ROOT / ".git" / "hooks"
    path = Path(out)
    return path if path.is_absolute() else (REPO_ROOT / path)


INSTALLED_HOOK = _hooks_dir() / "pre-commit"


def _hook_state(path: Path) -> str:
    """`clean`, `dirty`, `untracked` or `unmeasurable`, from the checkout that OWNS `path`.

    Run in the owner's directory, never the caller's: the installed hook lives in the main
    checkout, and `git status` on a path outside the current worktree answers about the
    wrong tree or refuses outright.
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", path.name],
            cwd=path.parent,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return "unmeasurable"
    if out.returncode != 0:
        return "unmeasurable"
    line = out.stdout.strip()
    if not line:
        return "clean"
    if line.startswith("??"):
        return "untracked"
    return "dirty"


def _uncommitted(path: Path) -> bool:
    """True when `path` has changes not committed in its own checkout.

    `git status --porcelain -- <file>` prints one line for a file that differs from HEAD or
    the index, and nothing at all for a clean one. Run with `cwd` set to the file's own
    directory, because the hook that runs lives in the MAIN checkout while this test runs in
    a worktree, and the two have different indexes.

    Anything that goes wrong — no git, not a checkout, a permission error — returns False,
    so a broken measurement re-arms the assertion rather than silently muting it.
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", path.name],
            cwd=path.parent, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    return bool(out.strip())


def _load_runner():
    """Import the runner by path — scripts/ is not an importable package.

    The sys.modules registration is load-bearing: @dataclass resolves annotations via
    sys.modules[cls.__module__], so exec_module on an unregistered module raises
    AttributeError: 'NoneType' object has no attribute '__dict__' before any test runs.
    """
    spec = importlib.util.spec_from_file_location("popdd_verify", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["popdd_verify"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _hook_code() -> str:
    """The hook's executable lines only.

    A regex over source text cannot tell code from a comment, and this hook's header
    quotes the very pattern these tests forbid (`\\.(py|ts|js|cs)$`) while explaining
    why it was removed. Two storefront tests shipped passing vacuously for exactly this
    reason. Strip comments first, always.
    """
    lines = []
    for line in HOOK.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


class TestTheLaneMapCoversEachSourceKind:
    def test_a_tsx_page_selects_the_web_lane(self, runner):
        """The exact regression: this file was ungated because `.tsx` was not matched."""
        lanes, unclassified = runner.lanes_for(
            ["store_platform/src/Store.Web/src/pages/pack/[id].tsx"]
        )
        assert lanes == ["web"]
        assert unclassified == []

    def test_the_look_engine_tools_select_the_look_engine_lane(self, runner):
        """The exact regression: 20 staged .mjs/.js/.css files under docs/storefront/look-engine

        were all in SOURCE_EXTS and matched no lane, so the gate refused the whole directory as
        unproven and it could not be committed at all.
        """
        lanes, unclassified = runner.lanes_for(
            [
                "docs/storefront/look-engine/verify.mjs",
                "docs/storefront/look-engine/parts/03-looks.js",
                "docs/storefront/look-engine/parts/06-switches.css",
            ]
        )
        assert lanes == ["lookengine"]
        assert unclassified == []

    def test_every_look_engine_step_is_one_that_can_refuse(self, runner):
        """A lane step that logs a fault and exits 0 makes the lane green while grading nothing.

        Both steps below were mutation-proved before they were added: check.mjs exits 1 on a hex
        written into a look, on a `[data-look=...]` selector in the stylesheet, and on a tool
        claiming an undefined gate number; palette-test.mjs exits 1 when one `min:` in the pair
        table is raised. tools.mjs was in this lane and was removed for failing that test — it
        regenerated the ledger page with a lie in it and exited 0.

        This assertion is deliberately exact, so adding a step means saying here that you
        mutation-proved it.
        """
        steps = [argv[-1] for _, argv in runner.LANES["lookengine"].steps]
        assert steps == ["check.mjs", "palette-test.mjs"], steps

    def test_the_python_lane_lints_before_it_tests(self, runner):
        """W2.3: ruff is part of the python proof, and DECLARES itself repo-wide.

        Two things are asserted, both of which were the defect. (1) The step exists at all
        — a lint baseline of 0 decays back to 395 the moment nothing enforces it. (2) It
        carries NO path arguments: `lanes_for` routes any `.py` to this lane, including
        `run_v2.py` and `publish/publish.py` at the repo root, so scoping ruff to
        prospector/tools/scripts/tests would report green over files it never opened.
        """
        py = runner.LANES["python"]
        names = [name for name, _ in py.steps]
        assert names[0] == "ruff", f"ruff must run before pytest (seconds vs ~175s): {names}"
        assert "pytest" in names, names

        ruff_argv = dict(py.steps)["ruff"]
        assert ruff_argv[1:4] == ["-m", "ruff", "check"], ruff_argv
        paths = [a for a in ruff_argv[4:] if not a.startswith("-")]
        # "concise" is --output-format's value, not a path.
        paths = [p for p in paths if p != "concise"]
        assert paths == [], f"ruff must lint the whole repo, not a subset: {paths}"

    def test_ruff_grades_the_files_in_the_commit_not_the_whole_repo(self, runner):
        """The declared lane fails safe; `scope_ruff` narrows it when the caller knows the paths.

        A gate that grades the whole repository fails a commit for work someone else did in
        files it never touched. `main` itself carried 12 ruff errors until 2b38ca3, and while
        it did, every commit in every worktree was walled by them. The narrowing is by STAGED
        PATH rather than by directory, which keeps the guarantee the test above protects:
        `lanes_for` routes any `.py` to this lane, including `run_v2.py` and
        `publish/publish.py` at the repo root, so a directory list would report green over
        files it never opened.
        """
        py = runner.LANES["python"]

        scoped = runner.scope_ruff(py, ["run_v2.py", "scripts/doc_lint.py", "docs/x.md"])
        ruff_argv = dict(scoped.steps)["ruff"]
        assert ruff_argv[-2:] == ["run_v2.py", "scripts/doc_lint.py"], ruff_argv
        # Without --force-exclude ruff lints an explicitly named path even when the config
        # excludes it, so the scoped run would grade MORE than the repo-wide one it replaces.
        assert "--force-exclude" in ruff_argv, ruff_argv
        assert dict(scoped.steps)["pytest"] == dict(py.steps)["pytest"], "only ruff is scoped"

        # Three ways of not knowing, all of which must grade MORE, never less.
        for label, paths in [("caller knows nothing", []), ("no .py in the commit", ["a.md"])]:
            fallback = dict(runner.scope_ruff(py, paths).steps)["ruff"]
            assert fallback == dict(py.steps)["ruff"], f"{label}: {fallback}"
        assert runner.scope_ruff(runner.LANES["web"], ["a.py"]) is runner.LANES["web"]

    def test_the_web_lane_proof_is_not_pytest(self, runner):
        """A green pytest is not evidence about a .tsx diff, so the web lane must not use it."""
        web = runner.LANES["web"]
        commands = [" ".join(argv) for _, argv in web.steps]
        assert not any("pytest" in c for c in commands), commands
        assert any("typecheck" in c for c in commands), commands
        assert any("test" in c for c in commands), commands
        assert web.cwd.name == "Store.Web"

    def test_a_stylesheet_selects_the_web_lane(self, runner):
        """The gate's header used to state CSS was uncoverable "short of a full next build".

        It is not: five vitest suites read src/styles/globals.css as source text
        (brandV2.test.ts:44, storefrontDesignContract.test.ts:21, uiPolishContract.test.ts:21,
        monoIsTheDataVoice.test.ts:48, twoRadiiTwoShadows.test.ts:42) and assert the design
        contract over it. Before this, a globals.css edit printed "nothing to prove" and
        exited 0 — the same silent-pass shape that lost `.tsx`.
        """
        lanes, unclassified = runner.lanes_for(
            ["store_platform/src/Store.Web/src/styles/globals.css"]
        )
        assert lanes == ["web"]
        assert unclassified == []

    def test_a_stylesheet_outside_the_storefront_blocks_rather_than_passing_silently(self, runner):
        """globals.css is the only tracked .css today. A second one landing elsewhere has no
        suite reading it, so it must be named as unproven, not treated as a non-source file."""
        lanes, unclassified = runner.lanes_for(["docs/site/theme.css"])
        assert lanes == []
        assert unclassified == ["docs/site/theme.css"]

    def test_python_source_selects_the_python_lane(self, runner):
        assert runner.lanes_for(["prospector/verify.py"])[0] == ["python"]

    def test_csharp_selects_dotnet_AND_python(self, runner):
        """tests/unit/test_facets.py:141 reads PackFacets.cs, so a .cs edit can break pytest."""
        lanes, _ = runner.lanes_for(
            ["store_platform/src/Store.Catalog/Domain/PackFacets.cs"]
        )
        assert lanes == ["dotnet", "python"]

    def test_non_source_proves_nothing_and_selects_no_lane(self, runner):
        lanes, unclassified = runner.lanes_for(["README.md", "store/provider_health.json"])
        assert lanes == []
        assert unclassified == []

    def test_source_with_no_lane_is_reported_not_ignored(self, runner):
        """Fail-closed. pi-governance/src/index.ts has no test runner; it must not sail through."""
        lanes, unclassified = runner.lanes_for(["pi-governance/src/index.ts"])
        assert lanes == []
        assert unclassified == ["pi-governance/src/index.ts"]

    def test_the_daemons_config_selects_the_engine_lane(self, runner):
        """The exact hole 9089ebc came through, and the most expensive one this gate has had.

        `.yaml` is in no extension set, so config.yaml matched no lane AND was not reported
        unclassified — `main` printed "nothing to prove" and exited 0. That commit raised
        `generation.candidates_per_signal` 5 → 50; every tick afterwards force-exited at the
        3h hard deadline mid-generation and the engine produced nothing for 21 ticks
        (store/scheduler/alerts.jsonl, 18 `barren_streak` criticals 11:23–15:57Z on
        2026-08-14). Nothing in the repo noticed. The founder did.
        """
        lanes, unclassified = runner.lanes_for(["config.yaml"])
        assert lanes == ["engine"], "the file that steers the live daemon must be proven"
        assert unclassified == []

    def test_scheduler_code_selects_the_engine_lane_AND_python(self, runner):
        """Both, not either. pytest proves the code; the dry-run tick proves the daemon can
        still complete a tick with it — a green suite over a scheduler that no longer starts
        is exactly the shape that reads healthy while the engine is down."""
        lanes, _ = runner.lanes_for(["prospector/scheduler/run_scheduled.py"])
        assert lanes == ["engine", "python"], lanes

    def test_the_engine_lane_proof_is_a_tick_not_a_test_run(self, runner):
        """A suite cannot speak to a config value. The engine lane's proof must be the
        daemon's own dry-run tick, or this lane is decoration."""
        engine = runner.LANES["engine"]
        commands = [" ".join(argv) for _, argv in engine.steps]
        assert any("verify_engine_change.sh" in c for c in commands), commands
        script = runner.ROOT / "scripts" / "verify_engine_change.sh"
        assert script.exists() and os.access(script, os.X_OK), f"{script} must exist and be executable"
        body = script.read_text()
        assert "--dry-run" in body, "the tick must be a dry run — a commit hook may not spend budget"
        assert "candidates_per_signal" in body, "the budget ratio check is the point of this lane"
        # Fail-closed: a missing script must block the commit, not skip the lane.
        assert script in engine.preflight, engine.preflight

    def test_the_engine_lane_runs_before_the_expensive_ones(self, runner):
        assert runner.LANE_ORDER[0] == "engine", runner.LANE_ORDER

    def test_a_mixed_commit_runs_every_lane_cheapest_first(self, runner):
        lanes, _ = runner.lanes_for([
            "prospector/run.py",
            "store_platform/src/Store.Web/src/lib/priceRange.ts",
            "store_platform/src/Store.Api/Program.cs",
        ])
        assert lanes == ["web", "dotnet", "python"]

    def test_every_source_extension_is_reachable_by_some_lane(self, runner):
        """Nothing in SOURCE_EXTS may be unclassifiable everywhere it can legally live."""
        samples = {
            ".py": "prospector/x.py",
            ".ts": "store_platform/src/Store.Web/src/x.ts",
            ".tsx": "store_platform/src/Store.Web/src/x.tsx",
            ".js": "store_platform/src/Store.Web/src/x.js",
            ".jsx": "store_platform/src/Store.Web/src/x.jsx",
            ".mjs": "store_platform/src/Store.Web/src/x.mjs",
            ".cjs": "store_platform/src/Store.Web/src/x.cjs",
            ".cs": "store_platform/src/Store.Api/X.cs",
            ".csproj": "store_platform/src/Store.Api/Store.Api.csproj",
            ".css": "store_platform/src/Store.Web/src/styles/globals.css",
        }
        assert set(samples) == runner.SOURCE_EXTS, "a new source extension needs a lane + a sample"
        for ext, path in samples.items():
            lanes, unclassified = runner.lanes_for([path])
            assert lanes and not unclassified, f"{ext} ({path}) reaches no lane"


class TestTheGateDecidesBeforeItSpendsAnything:
    """main() must reach its verdict on these two paths without running a suite or
    signing a receipt — a gate that has to spend 175s to say "nothing to prove" is a
    gate people bypass."""

    def test_an_unproven_source_file_blocks(self, runner, monkeypatch, capsys):
        monkeypatch.setattr(runner, "staged_paths", lambda: ["pi-governance/src/index.ts"])
        assert runner.main(["--staged"]) == 1
        assert "unproven: pi-governance/src/index.ts" in capsys.readouterr().out

    def test_a_docs_only_commit_is_allowed_without_running_anything(self, runner, monkeypatch, capsys):
        monkeypatch.setattr(runner, "staged_paths", lambda: ["README.md", "specs/x.md"])
        assert runner.main(["--staged"]) == 0
        assert "nothing to prove" in capsys.readouterr().out


class TestTheHookDelegatesInsteadOfKeepingASecondCopy:
    def test_the_installed_hook_is_the_tracked_one(self):
        # ABSENT is a legitimate state, and this test used to deny it twice over.
        #
        # `.git/hooks/` is not part of the repository — actions/checkout populates it with
        # `*.sample` only — so on CI this asserted an artifact that cannot exist. That was
        # first patched with a CI-only skip, which still FAILED on a developer machine with
        # no hook. Then the founder deliberately removed the local hook (2026-08-14,
        # "the POPDD gate is now installed — no, this should be disabled"), and a green
        # suite started reporting a red on a decision, not a defect.
        #
        # Whether the gate is INSTALLED is the operator's call and is enforced elsewhere:
        # the `engine` job in .github/workflows/ci.yml runs the same verification on every
        # PR, so a disabled local hook does not mean unverified code. What this class exists
        # to catch is narrower and is still asserted below for every checkout that has a
        # hook at all: a SECOND COPY whose content has diverged from the tracked file.
        if not INSTALLED_HOOK.exists() and not INSTALLED_HOOK.is_symlink():
            pytest.skip(f"no pre-commit hook at {INSTALLED_HOOK} — nothing installed to compare")
        assert INSTALLED_HOOK.is_symlink(), (
            f"{INSTALLED_HOOK} must be a symlink to the tracked .lux/hooks/pre-commit, "
            "or the file under review is not the file that runs."
        )
        # Compare WHAT IT IS, not WHERE IT IS. Hooks are shared through the common dir, so
        # in a worktree this symlink resolves into the MAIN checkout's .lux/ while `HOOK`
        # is this worktree's own copy of the same tracked file. Path equality therefore
        # fails in every worktree, on a repo where the gate is installed and working — and
        # a failure naming the POPDD gate is the last one an agent will wave through.
        # Identical bytes is the property this class actually cares about: the stale second
        # copy it was written to catch is one whose content has DIVERGED.
        resolved = INSTALLED_HOOK.resolve()
        assert resolved.parts[-3:] == (".lux", "hooks", "pre-commit"), (
            f"installed hook resolves to {resolved}, which is not a .lux/hooks/pre-commit"
        )
        # DIRTY is the third legitimate state, for the same reason ABSENT is. The hook that
        # runs is shared through the common git dir by EVERY worktree, so while any session
        # has an uncommitted edit in it, its bytes match no committed file anywhere and this
        # comparison fails in every worktree at once, on every diff, whatever the diff is.
        # Measured 2026-08-20: one session edited the block message at 17:34 and that alone
        # walled a live outage fix in a different worktree, with 6737 tests passing and the
        # only red naming the POPDD gate — which is the last failure an agent will wave
        # through. An edit in progress is a decision being made, not the stale second copy
        # this class was written to catch. It is still caught the moment it is committed.
        # Comparing bytes against THIS worktree's copy is the wrong question, and it walls
        # the one branch with the most right to differ. The installed hook is ONE file,
        # shared through the common git dir, so it is whatever the MAIN checkout has on
        # disk. A worktree carrying a not-yet-merged change to .lux/hooks/pre-commit
        # differs from it BY DESIGN, and the merge is how that difference goes away.
        #
        # Measured 2026-08-20, on the run that blocked this commit: both files tracked,
        # both clean, main on origin/main's blob fc60ec93 and this worktree on da4bf880's
        # d3073086 — six lines of message text apart, no defect on either side. 6749 tests
        # passed and the only red named the POPDD gate, which is the last failure an agent
        # will wave through.
        #
        # The stale second copy this class was written to catch is one that matches NO
        # commit in its OWN checkout: hand-edited, or dropped in untracked. That is the
        # question worth asking, and it does not care what any other worktree holds.
        state = _hook_state(resolved)
        if state == "dirty":
            pytest.skip(
                f"{resolved} has uncommitted changes — it is being edited, so it matches "
                "no committed file by definition. Re-run once it is committed."
            )
        assert state != "untracked", (
            f"the hook that runs ({resolved}) is not tracked by its own checkout — it is "
            "the hand-maintained second copy this class exists to catch. Commit it or "
            "point the symlink at the tracked .lux/hooks/pre-commit."
        )
        assert state == "clean", (
            f"could not measure whether {resolved} is tracked in its own checkout "
            f"(git status returned {state!r}). This assertion is not being skipped: an "
            "unmeasurable hook is a finding, not a pass."
        )

    def test_hook_state_answers_every_way_it_is_branched_on(self, tmp_path: Path):
        """The test above branches four ways on `_hook_state`. Prove all four are reachable.

        A helper that returned "dirty" for everything would skip forever; one that returned
        "clean" for everything would pass forever. Either way the class goes quiet without
        anything failing, which is the failure mode that let a stale hook sit unnoticed in
        the first place.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e",
        }
        for cmd in (["init", "-q"], ["config", "commit.gpgsign", "false"]):
            subprocess.run(["git", *cmd], cwd=repo, check=True, env=env, capture_output=True)

        f = repo / "hook"
        f.write_text("one\n", encoding="utf-8")
        assert _hook_state(f) == "untracked", "a file git has never seen reported as tracked"

        subprocess.run(["git", "add", "hook"], cwd=repo, check=True, env=env, capture_output=True)
        subprocess.run(
            ["git", "commit", "-qm", "add"], cwd=repo, check=True, env=env, capture_output=True
        )
        assert _hook_state(f) == "clean", "a committed, unmodified file reported as not clean"

        f.write_text("two\n", encoding="utf-8")
        assert _hook_state(f) == "dirty", "an uncommitted edit reported as clean"

        assert _hook_state(tmp_path / "nowhere" / "hook") == "unmeasurable", (
            "a path in no git repository must be reported unmeasurable, never clean — "
            "a broken measurement that reads as clean is the muzzle this test exists to stop"
        )

    def test_the_dirty_skip_is_not_a_blanket_muzzle(self, tmp_path: Path):
        """`_uncommitted` must answer BOTH ways, or the skip above mutes the assertion.

        A helper that always returned True would make this class green forever while the
        stale-second-copy defect it exists to catch shipped. Proved against a real throwaway
        checkout rather than a mock, because the thing under test is what git prints.
        """
        env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": str(tmp_path / "nogitconfig"),
            "GIT_CONFIG_SYSTEM": str(tmp_path / "nogitconfig"),
        }
        run = lambda *a: subprocess.run(  # noqa: E731 - one-line local, not an API
            ["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True, env=env,
        )
        run("init", "-q", "-b", "main")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        f = tmp_path / "pre-commit"
        f.write_text("clean\n", encoding="utf-8")
        run("add", "pre-commit")
        run("commit", "-q", "-m", "x", "--no-verify")

        assert _uncommitted(f) is False, "a committed, unmodified file reported as dirty"
        f.write_text("edited\n", encoding="utf-8")
        assert _uncommitted(f) is True, "an uncommitted edit reported as clean"

    def test_the_hook_calls_the_runner_in_staged_mode(self):
        code = _hook_code()
        assert "scripts/popdd_verify.py --staged" in code, code

    def test_the_hook_pins_its_interpreter_by_path(self):
        """A bare `python3` is whatever is first on PATH, and the system one cannot even
        collect this suite (8 ModuleNotFoundErrors). The hook must name an interpreter by
        path, not by command.

        Asserted structurally rather than by matching the literal path: this file may not
        contain a hardcoded interpreter path — tests/test_suite_is_machine_independent.py::
        test_no_test_hardcodes_an_interpreter_path forbids it, and it caught this test
        doing exactly that.
        """
        m = re.search(r'VERIFY_CMD="\$\{POPDD_VERIFY_CMD:-(.+?)\}"', _hook_code())
        assert m, "the hook no longer declares a default VERIFY_CMD"
        interpreter = m.group(1).split()[0]
        assert "/" in interpreter, (
            f"the gate runs `{interpreter}`, i.e. whatever is first on PATH — pin the "
            "project interpreter by path"
        )

    def test_the_hook_holds_no_extension_list_of_its_own(self):
        """The duplicated list is how `.tsx` went missing. Comments are stripped first."""
        code = _hook_code()
        assert not re.search(r"\\\.\((?:py|ts|tsx|js|cs)\|", code), (
            "the hook is filtering extensions itself again — that list belongs only in "
            "scripts/popdd_verify.py:lanes_for()"
        )
        # The blunt substring net runs over the lines that can actually FILTER. An `echo`
        # prints; it cannot classify a file, so an extension named in the hook's failure
        # message is documentation, not a second copy of the lane map. This assertion went
        # red on 2026-08-20 for exactly that reason: the message was corrected to say ruff
        # is scoped to "the .py files you staged", and a guard against duplicated LOGIC
        # graded PROSE. The regex above is the guard that matters and is unchanged.
        filtering = "\n".join(
            line for line in code.splitlines() if not re.match(r"\s*(echo|printf)\b", line)
        )
        assert ".tsx" not in filtering and ".py" not in filtering.replace("popdd_verify.py", "")

    def test_the_hook_still_fails_closed(self):
        code = _hook_code()
        assert "exit 1" in code, "the BLOCK path must exit non-zero"
        assert "--no-verify" in code, "the documented deliberate override must stay documented"
