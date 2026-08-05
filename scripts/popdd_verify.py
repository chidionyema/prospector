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
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from popdd_agent import PopddAgent

ROOT = Path(__file__).parent.parent
WEB_DIR = ROOT / "store_platform" / "src" / "Store.Web"
DOTNET_TEST_PROJ = "store_platform/src/Store.Tests/Store.Tests.csproj"

# Wall-clock ceiling per lane. This is a HANG detector, not a performance budget — set it
# well above the real runtime so a merely-slow suite never reads as a failure. Measured
# 2026-07-30: python 679 tests, 168.81s pytest-internal / 174.65s process. The previous
# 180s ceiling left 3% headroom, so commits failed non-deterministically under load once
# the control-center detach tests (+58 tests) landed. Override with POPDD_TEST_TIMEOUT.
TEST_TIMEOUT_SECONDS = int(os.environ.get("POPDD_TEST_TIMEOUT", "600"))

# Extensions that must be covered by SOME lane. A file with one of these that matches no
# lane blocks the commit rather than sailing through unproven.
SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".cs", ".csproj"}

# Extensions the storefront's own proof (tsc + vitest) can speak to. `.json` is here for
# package.json / tsconfig.json, which change what typecheck and vitest actually run.
WEB_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json"}

WEB_REL = "store_platform/src/Store.Web/"


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
    "python": Lane(
        key="python",
        label="python — pytest suite",
        target="prospector:test-suite",
        steps=(("pytest", [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rf"]),),
        parser=_parse_pytest,
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
    "dotnet": Lane(
        key="dotnet",
        label="dotnet — Store.Tests",
        target="store-api:dotnet-suite",
        steps=(("dotnet test", ["dotnet", "test", DOTNET_TEST_PROJ, "--nologo", "-v", "q"]),),
        parser=_parse_dotnet,
    ),
}

LANE_ORDER = ("web", "dotnet", "python")   # cheapest first, so a fast failure comes back fast


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
        if path.startswith(WEB_REL) and ext in WEB_EXTS:
            lanes.add("web")
        elif ext == ".py":
            lanes.add("python")
        elif ext in (".cs", ".csproj"):
            # dotnet proves the C# itself; python because test_facets.py:141 reads PackFacets.cs.
            lanes.add("dotnet")
            lanes.add("python")
        elif ext in SOURCE_EXTS:
            unclassified.append(path)
    return [k for k in LANE_ORDER if k in lanes], unclassified


def staged_paths() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


# ── execution ────────────────────────────────────────────────────────────────

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
    for step_name, argv in lane.steps:
        print(f"   … {step_name}")
        try:
            result = subprocess.run(
                argv, cwd=lane.cwd, capture_output=True, text=True,
                timeout=TEST_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            # A timeout used to propagate as an uncaught traceback, which killed the process
            # before "test-run:complete" was ever signed. The chain was then left with a
            # dangling STARTED entry (receipts seq 24 and 25 of 2026-07-30) that looked like
            # a crashed run rather than a timeout. Sign the verdict, then fail closed.
            agent.sign_generic(
                action="test-run:complete", target=lane.target,
                **{
                    "verdict": "TIMEOUT", "lane": lane.key, "step": step_name,
                    "passed": 0, "failed": 0, "failedTests": [], "exitCode": None,
                    "timeoutSeconds": TEST_TIMEOUT_SECONDS,
                },
            )
            print(
                f"\n❌ {lane.label}: step '{step_name}' exceeded {TEST_TIMEOUT_SECONDS}s and was killed.\n"
                "   This is a hang, not a slow suite. If the suite is legitimately this slow,\n"
                "   raise POPDD_TEST_TIMEOUT.\n"
            )
            return False

        combined += result.stdout + result.stderr
        returncode = result.returncode
        if returncode != 0:
            print(result.stdout[-4000:])
            print(result.stderr[-2000:])
            break

    passed, failed, failed_tests = lane.parser(combined)
    verdict = "PASS" if returncode == 0 and failed == 0 else "FAIL"
    agent.sign_generic(
        action="test-run:complete", target=lane.target,
        **{
            "verdict": verdict, "lane": lane.key, "passed": passed, "failed": failed,
            "failedTests": failed_tests, "exitCode": returncode,
        },
    )
    print(f"   {'✅' if verdict == 'PASS' else '❌'} {lane.key}: {verdict} ({passed} passed, {failed} failed)")
    for nodeid in failed_tests:
        print(f"      FAILED  {nodeid}")
    if failed and not failed_tests:
        print("      (failure count reported but no ids parsed — check the runner's output format)")
    return verdict == "PASS"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="POPDD proof runner (lane-aware)")
    ap.add_argument("--staged", action="store_true",
                    help="derive lanes from the staged delta (what the pre-commit gate uses)")
    ap.add_argument("--lanes", default="",
                    help=f"comma-separated lanes to force: {','.join(LANES)}")
    args = ap.parse_args(argv)

    unclassified: list[str] = []
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

    agent = PopddAgent.at_path(ROOT)
    ok = True
    for key in selected:
        if not run_lane(agent, LANES[key]):
            ok = False
            break   # kill-fast: a failed lane already blocks the commit

    verify = agent.verify_chain()   # (auto-saved by PopddAgent)

    print(f"\n{'=' * 60}")
    print("  Prospector POPDD Run Complete")
    print(f"{'=' * 60}")
    print(f"  Lanes run:     {', '.join(selected)}")
    print(f"  Verdict:       {'PASS' if ok else 'FAIL'}")
    print(f"  Chain valid:   {verify['valid']}")
    print(f"{'=' * 60}\n")
    return 0 if verify["valid"] and ok else 1


if __name__ == "__main__":
    sys.exit(main())
