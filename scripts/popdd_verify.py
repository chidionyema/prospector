#!/usr/bin/env python3
"""
Prospector POPDD proof runner — lane-aware.

Runs the proof that actually covers the code being committed, and signs the result
into the POPDD chain.

WHY LANES (the defect this replaces, 2026-08-05):
    The pre-commit gate matched `\\.(py|ts|js|cs)$` and, on a hit, ran ONE proof:
    the python pytest suite. Two holes followed from that:

      1. `.tsx` was not in the list at all, so every Next.js page under
         store_platform/src/Store.Web committed with the gate printing
         "no source changes staged — nothing to prove".
      2. Adding `.tsx` alone would have been green theatre: pytest cannot see a
         `.tsx` diff. Zero python tests read a .ts/.tsx file — verified with
         `grep -rn "\\.tsx\\?[\"']" tests/ --include='*.py'` (no output). A green
         pytest run is not evidence about storefront code.

    So the runner classifies the staged delta into lanes and runs each lane's own
    proof. Each lane signs its own receipt, so the chain records WHAT was proven,
    not just that something was.

Lane map — each mapping is a proof, not a preference:
    *.py                                  -> python
    Store.Web/**.{ts,tsx,js,jsx,mjs,cjs,json} -> web
    *.cs, *.csproj                        -> dotnet AND python
        (python too: tests/unit/test_facets.py:141 reads
         store_platform/src/Store.Catalog/Domain/PackFacets.cs and asserts the
         facet vocabulary matches prospector/facets.py — a .cs edit really can
         break the python suite.)

Anything with a source extension that matches no lane BLOCKS with a message naming
the file. Fail-closed: an unproven file is not a passing file.

Usage:
    python scripts/popdd_verify.py              # python lane (back-compat default)
    python scripts/popdd_verify.py --staged     # lanes implied by the staged delta
    python scripts/popdd_verify.py --lanes web  # one lane explicitly
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

# Imported lazily inside main(), NOT at module scope. requirements.txt states the rule
# this obeys: the LUX packages are absent from CI and from every deploy host ("Nothing in
# prospector/ or tests/ imports them; only run_v2.py and scripts/popdd_verify.py do").
# tests/unit/test_popdd_gate_lanes.py imports THIS module to read the lane map, so a
# module-scope import made `import popdd_verify` unsatisfiable wherever LUX is not
# installed — 12 collection errors in CI, none of which touch the agent. The lane map is
# pure data and must stay readable without it; only the chain-signing path needs the agent.
if TYPE_CHECKING:
    from popdd_agent import PopddAgent

ROOT = Path(__file__).parent.parent
WEB_DIR = ROOT / "store_platform" / "src" / "Store.Web"
CONSOLE_DIR = ROOT / "store_platform" / "src" / "Ops.Console"
DOTNET_TEST_PROJ = "store_platform/src/Store.Tests/Store.Tests.csproj"
LOOKENGINE_DIR = ROOT / "docs" / "storefront" / "look-engine"

# Wall-clock ceiling per lane. This is a HANG detector, not a performance budget — set it
# well above the real runtime so a merely-slow suite never reads as a failure. Measured
# 2026-07-30: python 679 tests, 168.81s pytest-internal / 174.65s process. The previous
# 180s ceiling left 3% headroom, so commits failed non-deterministically under load once
# the control-center detach tests (+58 tests) landed. Override with POPDD_TEST_TIMEOUT.
#
# Raised 600 -> 2400 on 2026-08-13. The 600s ceiling had stopped being a hang detector and
# become a blanket commit block: the python lane measured 2968 passed, 3 skipped, 1279.27s
# (21m19s), i.e. 2.1x the limit, so EVERY commit in this repo failed with verdict TIMEOUT
# regardless of its diff. Sessions were working around it with a per-invocation
# POPDD_TEST_TIMEOUT=1800, which is not a fix — an unset variable put the block straight
# back. Note the suite time itself is the real anomaly (567s from the signed receipts of
# 2026-08-10 for 2910 tests -> 1279s for 2968), tracked separately; this constant must not
# be the thing that hides it, so the ceiling stays finite and a genuine hang still dies.
TEST_TIMEOUT_SECONDS = int(os.environ.get("POPDD_TEST_TIMEOUT", "2400"))

# How long the gate will wait to collect output AFTER it has killed a timed-out step's whole
# process group. Deliberately short and deliberately finite: an orphan holding the inherited
# pipe write end is precisely the condition that wedged this hook (see `_run_step`), so the
# drain must be allowed to give up. Losing the tail of a hung run's log costs a diagnosis;
# waiting for it forever costs every commit in the checkout.
DRAIN_TIMEOUT_SECONDS = 30

# Extensions that must be covered by SOME lane. A file with one of these that matches no
# lane blocks the commit rather than sailing through unproven.
SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".cs", ".csproj", ".css", ".rs"}

# Extensions the storefront's own proof (tsc + vitest) can speak to. `.json` is here for
# package.json / tsconfig.json, which change what typecheck and vitest actually run.
#
# `.css` is here because the claim "no cheap local proof exists for CSS short of a full
# `next build`" is false, and was checked: five suites read src/styles/globals.css as
# source text and assert design-contract invariants over it —
#   brandV2.test.ts:44, storefrontDesignContract.test.ts:21, uiPolishContract.test.ts:21,
#   monoIsTheDataVoice.test.ts:48, twoRadiiTwoShadows.test.ts:42.
# What that buys is narrow and worth naming: it proves the declared tokens, the one-colour
# rule and the radius/shadow set survive an edit. It does NOT prove anything renders — the
# two CSS bugs this repo has actually shipped (a var() resolved at its declaration site, an
# @theme token no consumer reached) were both green in every suite, and a `next build`
# would have been green on both too. So this is a real net, not the whole net.
WEB_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".css"}

WEB_REL = "store_platform/src/Store.Web/"
OPS_REL = "store_platform/src/Ops.Console/"

# The Ops Console is the admin surface. It was untracked until 2026-08-16, so no lane covered
# it and every one of its files read as unproven. It has the same proof shape as the
# storefront — tsc plus vitest — so it gets its own lane rather than being folded into `web`:
# the two apps have separate node_modules and separate npm scripts, and one lane cannot cd to
# two directories.
CONSOLE_REL = "store_platform/src/Ops.Console/"

# The look engine is the storefront redesign prototype: .mjs tools plus .js/.css parts that
# build one self-contained page. Its extensions are all in SOURCE_EXTS, so before this lane
# existed every one of its files read as unproven and the directory could not be committed.
LOOKENGINE_REL = "docs/storefront/look-engine/"

# The Rust engine. Its own tree, its own toolchain, no Python in it. Before this lane existed
# a commit of nothing but .rs files reported "no source changes staged — nothing to prove" and
# was allowed, because `.rs` was in neither SOURCE_EXTS nor any lane — so it was not even
# recorded as unclassified. That is the same shape as the `.yaml` hole above: a gate that says
# green while grading nothing. Measured 2026-08-21 before the fix:
#   lanes_for(["engine-rs/crates/prospector-core/src/decision.rs"]) -> ([], [])
RUST_REL = "engine-rs/"
RUST_DIR = ROOT / "engine-rs"

# rustup installs to ~/.cargo/bin, which a git hook's environment does not have on PATH.
CARGO = Path.home() / ".cargo" / "bin" / "cargo"

# Not source, but a change to any of them changes what every Rust build and lint does, so they
# belong in the lane's catchment as much as a .rs file. rust-toolchain.toml is the sharpest:
# it pins the compiler version, so editing it can turn a green tree red with no code change.
RUST_CONFIG_FILES = frozenset({
    "Cargo.toml", "Cargo.lock", "clippy.toml", "rustfmt.toml", "deny.toml", "rust-toolchain.toml",
})

# ── the engine lane's catchment ───────────────────────────────────────────────
# The daemon is steered by two kinds of file, and until 2026-08-14 one of them was proven by
# NOTHING. `.yaml` is not in SOURCE_EXTS and matched no lane, so commit 9089ebc — which raised
# `generation.candidates_per_signal` 5 → 50 in config.yaml — printed "nothing to prove" and
# sailed through. Every tick after it force-exited at the 3h deadline mid-generation
# (store/scheduler/alerts.jsonl 2026-08-14T20:48:25Z `tick_error`), and the engine produced
# nothing for 21 consecutive ticks (18 `barren_streak` criticals, 11:23–15:57Z) until the
# founder asked why.
#
# Deliberately NOT solved by adding `.yaml` to SOURCE_EXTS: that set means "block the commit if
# no lane claims this", which would make every .github/workflows and docs yaml edit unprovable
# and therefore uncommittable, and a gate that blocks unrelated work is a gate people disable
# with --no-verify. Named catchment instead: the config the daemon actually reads, and the
# daemon's own package.
ENGINE_CONFIGS = ("config.yaml",)
ENGINE_DIRS = ("prospector/scheduler/",)


def _is_engine_path(path: str) -> bool:
    return path in ENGINE_CONFIGS or path.startswith(ENGINE_DIRS)


# ── parsers ──────────────────────────────────────────────────────────────────
# Each returns (passed, failed, failed_test_ids). A parser that cannot find counts
# returns zeros; the verdict still comes from the exit code, never from the counts.

def _parse_pytest(stdout: str) -> tuple[int, int, list[str]]:
    passed = failed = 0
    failed_tests: list[str] = []
    for line in stdout.splitlines():
        m = re.search(r"(\d+)\s+passed", line)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+)\s+failed", line)
        if m:
            failed = int(m.group(1))
        # e.g. "FAILED tests/scheduler/test_alerts.py::test_x - AssertionError: ..."
        m = re.match(r"(?:FAILED|ERROR)\s+(\S+)", line)
        if m:
            failed_tests.append(m.group(1))
    return passed, failed, failed_tests


def _parse_vitest(stdout: str) -> tuple[int, int, list[str]]:
    """vitest summary line: '      Tests  523 passed (523)' / '... 2 failed | 521 passed'."""
    passed = failed = 0
    failed_tests: list[str] = []
    for line in stdout.splitlines():
        if re.match(r"\s*Tests\s+", line):
            m = re.search(r"(\d+)\s+passed", line)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+)\s+failed", line)
            if m:
                failed = int(m.group(1))
        # e.g. " FAIL  src/__tests__/foo.test.ts > renders the price"
        # Only the FAIL lines: vitest also prints a `×  <name> 55ms` line per failure, which
        # duplicates the same test without the file that would let you find it.
        m = re.match(r"\s*FAIL\s+(\S+.*)$", line)
        if m:
            failed_tests.append(m.group(1).strip())
    return passed, failed, failed_tests[:50]


def _parse_dotnet(stdout: str) -> tuple[int, int, list[str]]:
    """dotnet summary: 'Passed!  - Failed:     0, Passed:   265, Skipped: 0, Total: 265'."""
    passed = failed = 0
    failed_tests: list[str] = []
    m = re.search(r"Failed:\s+(\d+),\s+Passed:\s+(\d+)", stdout)
    if m:
        failed, passed = int(m.group(1)), int(m.group(2))
    for line in stdout.splitlines():
        m = re.match(r"\s*(?:Failed|error)\s+(\S+)", line)
        if m:
            failed_tests.append(m.group(1))
    return passed, failed, failed_tests[:50]


def _parse_engine(stdout: str) -> tuple[int, int, list[str]]:
    """Count the engine script's own verdict lines ('   PASS  x' / '   FAIL  x').

    The verdict still comes from the exit code — these counts only make the receipt legible.
    """
    passed = failed = 0
    failed_checks: list[str] = []
    for line in stdout.splitlines():
        m = re.match(r"\s+(PASS|FAIL)\s+(.*)$", line)
        if not m:
            continue
        if m.group(1) == "PASS":
            passed += 1
        else:
            failed += 1
            failed_checks.append(m.group(2).strip())
    return passed, failed, failed_checks


def _parse_cargo(stdout: str) -> tuple[int, int, list[str]]:
    """Read cargo's own summary lines.

    `cargo test` prints one `test result:` line PER TARGET (lib, each integration test, the
    doctests), so the counts are summed rather than taken from the last line — reading only
    the last one reports the doctest target's 0 passed and calls a whole workspace proven.

    fmt and clippy print no counts at all. That is fine and deliberate: the step loop breaks
    on a non-zero exit, so their own status blocks the commit before this parser is reached,
    and a `-D warnings` clippy failure is an exit code, not a number to parse.
    """
    passed = failed = 0
    failures: list[str] = []
    for line in stdout.splitlines():
        t = line.strip()
        if t.startswith("test result:"):
            # The first field is "ok. 5 passed", not "5 passed" — cargo puts the verdict
            # word in front of the count. Read the token ADJACENT to the keyword rather
            # than the first token of the field.
            for count, word in re.findall(r"(\d+)\s+(passed|failed)", t):
                if word == "passed":
                    passed += int(count)
                else:
                    failed += int(count)
        elif t.startswith("test ") and t.endswith("... FAILED"):
            failures.append(t[:120])
    return passed, failed, failures[:50]


def _parse_lookengine(stdout: str) -> tuple[int, int, list[str]]:
    """Count the look-engine tools' own verdict lines ('A43 PASS — ...', 'FAIL ...').

    Same shape as _parse_engine: the verdict is the exit code, and these counts exist only
    to make the receipt legible.
    """
    passed = failed = 0
    failed_checks: list[str] = []
    for line in stdout.splitlines():
        m = re.search(r"\b(PASS|FAIL)\b", line)
        if not m:
            continue
        if m.group(1) == "PASS":
            passed += 1
        else:
            failed += 1
            failed_checks.append(line.strip()[:120])
    return passed, failed, failed_checks[:50]


# ── lanes ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Lane:
    key: str
    label: str
    target: str                      # POPDD receipt target
    steps: tuple[tuple[str, list[str]], ...]   # (step name, argv)
    parser: object
    cwd: Path = ROOT
    preflight: tuple[Path, ...] = field(default=())   # paths that must exist to run


LANES: dict[str, Lane] = {
    # ruff runs FIRST because it is seconds against pytest's ~175s, so a lint failure comes
    # back fast. It is declared here with NO path arguments, which means the whole repository.
    # That is the fallback, not the normal case: `scope_ruff` narrows it to the .py files in
    # the commit whenever the caller knows what they are (`--staged`, which is what the hook
    # uses). Read the note on `scope_ruff` for why both halves are needed. The step loop
    # breaks on a non-zero exit, so ruff's own status blocks the commit; _parse_pytest then
    # reads 0/0 off the ruff output and the verdict is FAIL on `returncode != 0`, with ruff's
    # findings already printed by the non-zero branch.
    "python": Lane(
        key="python",
        label="python — ruff + pytest suite",
        target="prospector:test-suite",
        steps=(
            ("ruff", [sys.executable, "-m", "ruff", "check", "--output-format", "concise"]),
            ("pytest", [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rf"]),
        ),
        parser=_parse_pytest,
    ),
    # The Rust engine. Three steps, cheapest first, so a formatting slip comes back in a
    # second instead of after a full compile.
    #
    # cargo-audit and cargo-deny are deliberately NOT here, and they are in ci.yml's `rust`
    # job instead. Both need the network — audit clones the RustSec advisory database, deny
    # reads the crates.io index — and a commit hook that fails when the wifi drops is a gate
    # that teaches people to pass --no-verify. The questions they answer ("is a dependency
    # known-vulnerable", "may we legally ship it") also cannot be changed by an edit to a .rs
    # file; they change when Cargo.lock changes or when the world changes, and CI sees both.
    #
    # CARGO is an absolute path because the hook does not inherit an interactive shell, so
    # ~/.cargo/bin is not on PATH and `cargo` would be "command not found" — which the step
    # loop would report as a failed proof rather than as a missing toolchain.
    "rust": Lane(
        key="rust",
        label="rust — fmt + clippy -D warnings + cargo test",
        target="prospector:rust-engine",
        steps=(
            ("fmt", [str(CARGO), "fmt", "--all", "--", "--check"]),
            ("clippy", [str(CARGO), "clippy", "--workspace", "--all-targets",
                        "--all-features", "--", "-D", "warnings"]),
            ("test", [str(CARGO), "test", "--workspace", "--all-features"]),
        ),
        parser=_parse_cargo,
        cwd=RUST_DIR,
        # Fail closed. Without CARGO in preflight a machine with no Rust toolchain would skip
        # the lane, and skipping is how an unproven commit reads as green.
        preflight=(RUST_DIR / "Cargo.toml", CARGO),
    ),
    # The storefront proof CI itself does NOT fully run: ci.yml's `nextjs` job runs
    # typecheck + build but never `npm test`, so these 523 vitest tests have no other
    # enforcement point. tsc catches the type errors; vitest catches the copy/DOM
    # regressions (e.g. the hardcoded-price assertions in __tests__/noHardcodedPrice.test.ts).
    "web": Lane(
        key="web",
        label="web — tsc --noEmit + vitest (Store.Web)",
        target="storefront:web-suite",
        steps=(
            ("typecheck", ["npm", "run", "--silent", "typecheck"]),
            ("vitest", ["npm", "test", "--silent"]),
        ),
        parser=_parse_vitest,
        cwd=WEB_DIR,
        preflight=(WEB_DIR / "node_modules",),
    ),
    # The engine is the crown jewel and it runs unattended, so its proof is not "the tests
    # passed" but "a tick still completes with this change". scripts/verify_engine_change.sh
    # imports the daemon module, lints it, runs a --dry-run tick to completion, and checks the
    # generation budget ratio that 9089ebc violated. It is ~15s, so it runs FIRST.
    #
    # --dry-run is what makes this safe to run from a commit hook against production state: it
    # evaluates the guards and the generation plan and stops, spending no provider budget and
    # writing no candidates. What it CANNOT prove is yield — only a live paid tick shows the
    # engine is producing — and the script says so in its own output rather than letting a
    # green lane imply it.
    "engine": Lane(
        key="engine",
        label="engine — import + dry-run tick + budget ratio",
        target="prospector:engine-tick",
        steps=(("engine verify", [str(ROOT / "scripts" / "verify_engine_change.sh")]),),
        parser=_parse_engine,
        preflight=(ROOT / "scripts" / "verify_engine_change.sh",),
    ),
    # The Ops Console runs every admin action, including the money-rail tools, so a type error
    # in its act handler is an operator pressing a button that 404s. That happened: on
    # 2026-08-16 `daemon.restart` was live in the Python gateway and missing from the browser
    # allowlist, and nothing caught it. tests/act.test.ts now checks the two lists agree.
    "console": Lane(
        key="console",
        label="console — tsc --noEmit + vitest (Ops.Console)",
        target="ops-console:console-suite",
        steps=(
            ("typecheck", ["npm", "run", "--silent", "typecheck"]),
            ("vitest", ["npm", "test", "--silent"]),
        ),
        parser=_parse_vitest,
        cwd=CONSOLE_DIR,
        preflight=(CONSOLE_DIR / "node_modules",),
    ),
    # Two node-only proofs, and both were mutation-proved BEFORE they were put in a lane. A
    # step that logs a fault and exits 0 makes a lane green while grading nothing, which is the
    # same class as `cmd | tail` reporting tail's status.
    #   check.mjs exits 1 on each of: a hex value written into a look (A43); a `[data-look=...]`
    #   selector appended to the stylesheet (A42); a tool claiming a gate number the programme
    #   doc does not define (the gate audit).
    #   palette-test.mjs exits 1 when one `min:` in the palette module's own pair table is
    #   raised — 4,000 failing pairs out of 80,000 assertions over 2,000 random seeds.
    # Together ~3s, and neither writes a tracked file.
    #
    # tools.mjs WAS in this lane and was removed for failing exactly that test: given a tool
    # whose @ledger line names a script that does not exist, it regenerated the ledger page
    # with the lie in it and exited 0. It is a generator, not a gate.
    #
    # What this lane does NOT prove, said out loud rather than implied by a green tick: the
    # five browser gates (verify.mjs — 104 cells, coldopen.mjs, overflow.mjs, persist.mjs and
    # probe.mjs) all drive Playwright and take minutes, and a commit hook that launches a
    # browser is the wedge this gate already has a memory file about. They are run by hand
    # through runlog.sh, and logs/ carries their last verdict. So this is a real net over the
    # static contracts, not the whole net. seed.mjs is excluded for a different reason: it is a
    # one-off migration from the hand-picked palettes to seeds, so it is a tool, not a gate.
    "lookengine": Lane(
        key="lookengine",
        label="look-engine — source contracts + palette contrast",
        target="storefront:look-engine",
        steps=(
            ("check", ["node", "check.mjs"]),
            ("palette", ["node", "palette-test.mjs"]),
        ),
        parser=_parse_lookengine,
        cwd=LOOKENGINE_DIR,
        preflight=(LOOKENGINE_DIR / "check.mjs",),
    ),
    "dotnet": Lane(
        key="dotnet",
        label="dotnet — Store.Tests",
        target="store-api:dotnet-suite",
        steps=(("dotnet test", ["dotnet", "test", DOTNET_TEST_PROJ, "--nologo", "-v", "q"]),),
        parser=_parse_dotnet,
    ),
}

# cheapest first, so a fast failure comes back fast. `engine` (~15s) leads: a change that
# stops the daemon completing a tick should be reported before anything spends 175s.
# `lookengine` (~3s) is cheaper still and would lead on that rule alone, but
# test_popdd_gate_lanes.py:289 pins the engine at position 0 on purpose, and 15 seconds is
# not worth loosening a guard another session wrote.
LANE_ORDER = ("engine", "lookengine", "rust", "console", "web", "dotnet", "python")


def lanes_for(paths: list[str]) -> tuple[list[str], list[str]]:
    """Classify a staged delta.

    Returns (lane keys in run order, unclassified source paths). Pure — no I/O — so the
    gate's own tests can assert the map without running a suite.
    """
    lanes: set[str] = set()
    unclassified: list[str] = []
    for raw in paths:
        path = raw.strip()
        if not path:
            continue
        ext = Path(path).suffix
        # Checked first and NOT part of the elif chain: prospector/scheduler/*.py must select
        # BOTH lanes. The suite proves the code is correct; the dry-run tick proves the daemon
        # can still complete one. Neither substitutes for the other.
        if _is_engine_path(path):
            lanes.add("engine")
        if path.startswith(CONSOLE_REL) and ext in WEB_EXTS:
            lanes.add("console")
        elif path.startswith(WEB_REL) and ext in WEB_EXTS:
            lanes.add("web")
        elif path.startswith(OPS_REL) and ext in WEB_EXTS:
            lanes.add("ops")
        elif path.startswith(LOOKENGINE_REL) and ext in SOURCE_EXTS:
            lanes.add("lookengine")
        elif path.startswith(RUST_REL) and (
            ext == ".rs" or Path(path).name in RUST_CONFIG_FILES
        ):
            lanes.add("rust")
        elif ext == ".py":
            lanes.add("python")
        elif ext in (".cs", ".csproj"):
            # dotnet proves the C# itself; python because test_facets.py:141 reads PackFacets.cs.
            lanes.add("dotnet")
            lanes.add("python")
        elif ext in SOURCE_EXTS:
            unclassified.append(path)
    return [k for k in LANE_ORDER if k in lanes], unclassified


def scope_ruff(lane: Lane, paths: list[str]) -> Lane:
    """Point ruff at the .py files in THIS commit instead of the whole repository.

    A gate must grade the diff in front of it. Repo-wide ruff did not: one unformatted file
    anywhere walled every commit in every worktree, for a file the committer had never opened.
    `main` itself carried 12 such errors until 2b38ca3 cleared them for exactly this reason,
    and a worktree on an older base failed the gate until it rebased. The person who has to
    fix it is never the person the gate stopped.

    Scoping to the STAGED PATHS, not to a directory list, is what keeps the guarantee the old
    comment here was protecting. `lanes_for` routes any `.py` to this lane, including
    `run_v2.py` and `publish/publish.py` at the repo root; scoping to
    prospector/tools/scripts/tests would have reported green over files it never opened. A
    staged file is in the diff wherever it lives, so it is still linted.

    `--force-exclude` keeps parity with the repo-wide run: without it, ruff lints a path given
    explicitly even when the config excludes it, so scoping would have found NEW errors in
    generated files that the repo-wide run never reported.

    When the caller does not know the paths — `--lanes`, or a bare invocation — the lane is
    returned untouched and ruff runs repo-wide. Failing safe means grading MORE, never less.
    """
    if lane.key != "python":
        return lane
    py = sorted({p for p in paths if p.endswith(".py")})
    if not py:
        return lane
    steps = tuple(
        (name, [*argv, "--force-exclude", *py] if name == "ruff" else argv)
        for name, argv in lane.steps
    )
    return replace(lane, steps=steps)


def staged_paths() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


# ── execution ────────────────────────────────────────────────────────────────

def _gate_lock_path() -> Path:
    """The single-flight lock, in THIS working tree's own git dir.

    `git rev-parse --absolute-git-dir` is used rather than `ROOT / ".git"` because in a linked
    worktree `.git` is a FILE containing `gitdir:`, not a directory — the exact bug
    tests/unit/test_popdd_gate_lanes.py once had. It also gives the property this rail needs
    for free: the primary checkout resolves to `<repo>/.git` and each linked worktree to
    `<repo>/.git/worktrees/<name>`, so two SESSIONS IN THE SAME TREE collide (which is the
    thing we are stopping) while two sessions in separate worktrees never do (which is the
    thing we want people to do instead).
    """
    out = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=ROOT,
        capture_output=True, text=True,
    )
    git_dir = Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() \
        else ROOT / ".git"
    return git_dir / "popdd-gate.lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True      # exists, owned by someone else
    return True


@contextlib.contextmanager
def single_flight():
    """Refuse a second gate run in the SAME working tree, immediately and loudly.

    This is a rail, not advice, because the failure it prevents has bitten this repo
    repeatedly and costs everyone at once. The gate runs the whole suite inside
    .git/hooks/pre-commit, so for its entire runtime `git commit` holds `.git/index.lock`.
    Two sessions sharing one checkout therefore serialise into ~100-minute commit cycles, and
    if either run wedges, EVERY commit in the checkout is blocked until a human kills a PID.
    On 2026-08-14 that happened: a gate sat at 0.0% CPU for 49 minutes holding the lock while
    two other sessions could not commit at all.

    Waiting politely is the wrong behaviour — it produces exactly the queue. Failing in under
    a second with the fix printed is right, and the fix is a worktree of your own:
    `./scripts/setup_worktree.sh` gives you a separate index and a separate lock, after which
    both sessions commit concurrently and neither can wedge the other.

    A holder whose PID is gone is stale (a crash, a SIGKILL) and is taken over silently — a
    lock that bricks the repo after one crash would just be a new way to be stuck.
    """
    path = _gate_lock_path()
    mine = {"pid": os.getpid(), "started": time.time(), "tree": str(ROOT)}

    for attempt in (1, 2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, json.dumps(mine).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                holder = json.loads(path.read_text())
                pid, started = int(holder["pid"]), float(holder["started"])
            except (OSError, ValueError, KeyError, TypeError):
                path.unlink(missing_ok=True)      # unreadable == stale
                continue

            if not _pid_alive(pid):
                path.unlink(missing_ok=True)
                continue

            age = int(time.time() - started)
            print(
                f"\n❌ POPDD gate: another gate run is already in flight IN THIS CHECKOUT "
                f"(pid {pid}, {age // 60}m{age % 60:02d}s old).\n"
                f"   It holds .git/index.lock for its whole run, so this commit cannot even "
                f"start.\n\n"
                f"   Do not wait for it. Get your own working tree — separate index, separate "
                f"lock:\n"
                f"       ./scripts/setup_worktree.sh ../<your-worktree>\n"
            )
            if age > TEST_TIMEOUT_SECONDS + DRAIN_TIMEOUT_SECONDS + 120:
                print(
                    f"   That run is ALSO past its own ceiling ({TEST_TIMEOUT_SECONDS}s) and "
                    f"should have died.\n"
                    f"   It is wedged. Clear it:  kill {pid}\n"
                )
            yield False
            return
        if attempt == 2:
            break

    try:
        yield True
    finally:
        try:
            if json.loads(path.read_text()).get("pid") == os.getpid():
                path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


class StepTimeout(Exception):
    """The step exceeded its wall-clock ceiling and its process group was killed.

    Carries whatever output was drained before the kill, which may be empty when the pipe
    was still held open — see `_run_step`.
    """

    def __init__(self, stdout: str, stderr: str, drained: bool) -> None:
        super().__init__("step timed out")
        self.stdout, self.stderr, self.drained = stdout, stderr, drained


def _run_step(argv: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    """Run one lane step under a wall-clock ceiling that CANNOT itself hang.

    `subprocess.run(capture_output=True, timeout=...)` is not safe here, and on 2026-08-14 it
    wedged this repo for every session at once. On timeout `run()` kills only the DIRECT child
    and then re-enters `communicate()` to drain the pipes. A grandchild that inherited the pipe
    write ends and outlived pytest holds that pipe open, so the second `communicate()` blocks
    forever, `TimeoutExpired` is never raised, and the "exceeded Ns" branch below is never
    reached. This gate runs inside .git/hooks/pre-commit, so a wedged gate holds
    `.git/index.lock` indefinitely — and this checkout is shared by concurrent sessions, so
    ONE hang stops every commit on the machine. Observed: popdd_verify alive at 0.0% CPU for
    37 minutes with no pytest child anywhere, the timeout message never printed.

    pytest is exactly the process that spawns such grandchildren (see the repo's
    multiprocessing-spawn-under-pytest note: the spawned child is unnamed, so it does not even
    show up in `pgrep -f pytest`).

    Two changes make the ceiling real:
      * `start_new_session=True` puts the step in its own process group, so the kill reaches
        every descendant rather than the one process we happen to hold a handle to;
      * the post-kill drain is BOUNDED. If a survivor still holds the pipe we abandon the
        output and fail the lane. A gate that reports "TIMEOUT with no output" is strictly
        better than one that never reports at all.
    """
    proc = subprocess.Popen(
        argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )

    def kill_group() -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()

    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group()
        try:
            # Bounded on purpose. The unbounded retry is the deadlock this function exists
            # to remove; never widen it into a plain communicate().
            out, err = proc.communicate(timeout=DRAIN_TIMEOUT_SECONDS)
            drained = True
        except subprocess.TimeoutExpired:
            for pipe in (proc.stdout, proc.stderr):
                try:
                    pipe.close()
                except OSError:
                    pass
            out, err, drained = "", "", False
        raise StepTimeout(out or "", err or "", drained) from None
    except KeyboardInterrupt:
        # start_new_session detaches the child from the terminal's process group, so a Ctrl-C
        # at the commit prompt no longer reaches pytest by itself. Forward it, or an
        # interrupted commit leaves a full suite running unattended.
        kill_group()
        raise

    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def run_lane(agent: PopddAgent, lane: Lane) -> bool:
    for required in lane.preflight:
        if not required.exists():
            print(f"\n❌ {lane.label}: missing {required.relative_to(ROOT)} — cannot prove this lane.")
            print(f"   Fix it (e.g. `cd {lane.cwd.relative_to(ROOT)} && npm ci`) and commit again.")
            return False

    command = " && ".join(" ".join(argv) for _, argv in lane.steps)
    agent.sign_generic(
        action="test-run:start", target=lane.target,
        **{"verdict": "STARTED", "command": command, "lane": lane.key},
    )

    print(f"\n▶ {lane.label}")
    combined, returncode = "", 0
    # Which steps actually EXECUTED, not which were configured. The loop below breaks on the
    # first non-zero exit, so a lane can report a verdict having run only its cheapest step --
    # and the counts it prints come from parsing that step's output, which yields 0 passed and
    # 0 failed. "0 passed, 0 failed" then reads as a completed clean suite. Measured 2026-08-20:
    # a peer timed this gate at 1.0s and reported it as the gate's cost. It was ruff failing
    # fast; pytest never started, and the real passing cost is 175-290s. The receipt said the
    # same thing, so the misreading survived into a second session.
    ran: list[str] = []
    for step_name, argv in lane.steps:
        print(f"   … {step_name}")
        ran.append(step_name)
        try:
            result = _run_step(argv, lane.cwd, TEST_TIMEOUT_SECONDS)
        except StepTimeout as timed_out:
            # A timeout used to propagate as an uncaught traceback, which killed the process
            # before "test-run:complete" was ever signed. The chain was then left with a
            # dangling STARTED entry (receipts seq 24 and 25 of 2026-07-30) that looked like
            # a crashed run rather than a timeout. Sign the verdict, then fail closed.
            agent.sign_generic(
                action="test-run:complete", target=lane.target,
                **{
                    "verdict": "TIMEOUT", "lane": lane.key, "step": step_name,
                    "passed": 0, "failed": 0, "failedTests": [], "exitCode": None,
                    "stepsRun": ran,
                    "stepsSkipped": [n for n, _ in lane.steps if n not in ran],
                    "timeoutSeconds": TEST_TIMEOUT_SECONDS,
                    "outputDrained": timed_out.drained,
                },
            )
            print(
                f"\n❌ {lane.label}: step '{step_name}' exceeded {TEST_TIMEOUT_SECONDS}s; its "
                "whole process group was killed.\n"
                "   This is a hang, not a slow suite. If the suite is legitimately this slow,\n"
                "   raise POPDD_TEST_TIMEOUT.\n"
            )
            if not timed_out.drained:
                print(
                    "   Output was abandoned: a surviving process still held the pipe after "
                    f"{DRAIN_TIMEOUT_SECONDS}s.\n"
                    "   Failing the lane anyway — the gate never waits on a pipe it cannot "
                    "close.\n"
                )
            print(timed_out.stdout[-4000:])
            print(timed_out.stderr[-2000:])
            return False

        combined += result.stdout + result.stderr
        returncode = result.returncode
        if returncode != 0:
            print(result.stdout[-4000:])
            print(result.stderr[-2000:])
            break

    passed, failed, failed_tests = lane.parser(combined)
    skipped = [name for name, _ in lane.steps if name not in ran]
    verdict = "PASS" if returncode == 0 and failed == 0 else "FAIL"
    agent.sign_generic(
        action="test-run:complete", target=lane.target,
        **{
            "verdict": verdict, "lane": lane.key, "passed": passed, "failed": failed,
            "failedTests": failed_tests, "exitCode": returncode,
            "stepsRun": ran, "stepsSkipped": skipped,
        },
    )
    print(f"   {'✅' if verdict == 'PASS' else '❌'} {lane.key}: {verdict} ({passed} passed, {failed} failed)")
    if skipped:
        print(f"      ⚠ NEVER RAN: {', '.join(skipped)} — '{ran[-1]}' failed first and stopped "
              "the lane.\n"
              f"      So ({passed} passed, {failed} failed) is what {ran[-1]}'s output parsed to, "
              "NOT a suite result,\n"
              "      and this lane's elapsed time is the cost of failing early, not the cost of "
              "passing.")
    for nodeid in failed_tests:
        print(f"      FAILED  {nodeid}")
    if failed and not failed_tests:
        print("      (failure count reported but no ids parsed — check the runner's output format)")
    return verdict == "PASS"


def print_summary(ran: list[str], selected: list[str], ok: bool, chain_valid: bool) -> None:
    """Print the run summary, naming the lanes that ACTUALLY executed.

    It used to print `selected`. The lane loop breaks on the first failing lane, so on a FAIL the
    tail of `selected` never runs -- measured 2026-08-20, a merge blocked by the console lane
    printed "Lanes run: engine, console, web, dotnet, python" and gave a verdict line for engine
    and console only. Three lanes were reported as run and were never started.

    That is the same defect as the step-level `stepsRun` receipt in `run_lane`, one level up, and
    it is worse here because this is the block a human reads. A reader who takes that line at face
    value concludes the dotnet and python lanes graded this diff green. They did not run at all.
    """
    print(f"\n{'=' * 60}")
    print("  Prospector POPDD Run Complete")
    print(f"{'=' * 60}")
    print(f"  Lanes run:     {', '.join(ran) if ran else '(none)'}")
    skipped = [k for k in selected if k not in ran]
    if skipped:
        print(f"  Lanes SKIPPED: {', '.join(skipped)} — kill-fast stopped at the first failing")
        print("                 lane, so these were never graded. Not evidence that they pass.")
    print(f"  Verdict:       {'PASS' if ok else 'FAIL'}")
    print(f"  Chain valid:   {chain_valid}")
    print(f"{'=' * 60}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="POPDD proof runner (lane-aware)")
    ap.add_argument("--staged", action="store_true",
                    help="derive lanes from the staged delta (what the pre-commit gate uses)")
    ap.add_argument("--lanes", default="",
                    help=f"comma-separated lanes to force: {','.join(LANES)}")
    args = ap.parse_args(argv)

    unclassified: list[str] = []
    paths: list[str] = []
    if args.lanes:
        selected = [k.strip() for k in args.lanes.split(",") if k.strip()]
        unknown = [k for k in selected if k not in LANES]
        if unknown:
            print(f"❌ unknown lane(s): {', '.join(unknown)}. Known: {', '.join(LANES)}")
            return 2
        selected = [k for k in LANE_ORDER if k in selected]
    elif args.staged:
        paths = staged_paths()
        selected, unclassified = lanes_for(paths)
        if selected:
            print("🔍 POPDD gate: staged source changes → lanes " + ", ".join(selected))
            for p in paths:
                print(f"     staged: {p}")
    else:
        selected = ["python"]   # back-compat: a bare invocation still means "run the suite"

    if unclassified:
        print("❌ POPDD gate: staged source files that no proof lane covers:")
        for p in unclassified:
            print(f"     unproven: {p}")
        print("   Register a lane for them in scripts/popdd_verify.py (LANES + lanes_for),")
        print("   or commit with --no-verify to record the gap as a deliberate choice.")
        return 1

    if not selected:
        print("✅ POPDD gate: no source changes staged — nothing to prove. Allowing commit.")
        return 0

    # Deferred to here on purpose: both early returns above (unproven paths, nothing to
    # prove) are decisions the lane map makes on its own, and they are what the tests
    # exercise. Only signing the chain needs the agent, so only that path requires LUX.
    #
    # ROOT goes on sys.path first. `popdd_agent.py` sits at the REPO ROOT, and running this
    # file as a script puts `scripts/` on sys.path, not the root -- so the import died with
    # ModuleNotFoundError. Measured 2026-08-18 in the `wt-polish` worktree: the gate reached
    # this line and crashed, which reads as "the gate is broken" rather than "the gate cannot
    # find its own agent". Using THIS file's ROOT also keeps a worktree grading itself: the
    # shared `.venv` resolves an editable path back to the MAIN checkout, so an ambient
    # install would have loaded another tree's copy of the agent.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from popdd_agent import PopddAgent

    agent = PopddAgent.at_path(ROOT)
    ok = True
    # Which lanes actually EXECUTED. The loop below breaks on the first failing lane, so on a FAIL
    # the tail of `selected` never runs. Printing `selected` there claimed five lanes had run when
    # two had -- measured 2026-08-20, a merge blocked by the console lane printed
    # "Lanes run: engine, console, web, dotnet, python" with a verdict line for engine and console
    # only. Same class as the step-level `stepsRun` above: a receipt that reports what was
    # CONFIGURED reads as coverage that never happened.
    ran: list[str] = []
    with single_flight() as acquired:
        if not acquired:
            return 1
        for key in selected:
            ran.append(key)
            if not run_lane(agent, scope_ruff(LANES[key], paths)):
                ok = False
                break   # kill-fast: a failed lane already blocks the commit

    verify = agent.verify_chain()   # (auto-saved by PopddAgent)

    print_summary(ran, selected, ok, verify["valid"])
    return 0 if verify["valid"] and ok else 1


if __name__ == "__main__":
    sys.exit(main())
