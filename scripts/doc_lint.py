#!/usr/bin/env python3
"""Fail a doc that points at something which is not there any more.

ENG-6 was a doc that told an operator to run a provider no config had selected for weeks.
Nothing caught it, because prose has no compiler. This is the compiler.

Three checks, and each one exists because that exact shape of rot has happened here:

1. **A referenced path that does not exist.** `RUN.md` sent readers to a module that had moved.
2. **A referenced path that exists and is empty.** `prospector/publish.py` is a 0-byte stub; a
   doc naming it reads as correct to grep and to a human skimming, and is useless to run.
3. **A provider named as if it were current, that `config.yaml` does not select.** `RUN.md:95`
   said the moat was "Claude+Gemini". There has been no `gemini` key in `config.yaml` for weeks.

Check 3 must not ban discussing a retired provider — the incidents ARE the reasoning behind
the current rules, and `CLAUDE.md` is mostly that. So a line carrying `doc-lint-ok` is exempt,
and whole files can be exempted in HISTORICAL_FILES. The point is to catch instructions, not
to erase history.

Usage
-----
    python3 scripts/doc_lint.py            # report; exit 1 if anything is wrong
    python3 scripts/doc_lint.py --json     # same, machine-readable
    python3 scripts/doc_lint.py --list     # what it scanned and what it knows, then exit 0

Report-only by design. It never edits a doc.
"""
from __future__ import annotations

import argparse
import functools
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Docs that are instructions. A change here changes what CI enforces, so it is a list, not a
#: glob over everything that happens to end in .md.
SCAN_GLOBS = ("RUN.md", "README.md", "docs/*.md")

#: Docs whose job is to record what USED to be true. They still get the path checks; they are
#: exempt from the provider check only.
HISTORICAL_FILES = frozenset({"CLAUDE.md", "docs/COST_PROGRAM.md", "docs/attic"})

#: Roots a path claim may be relative to. Docs cite from the root of the project they are about
#: — `lib/config.ts` in the site spec means the Store.Web source root, and
#: `Store.Api/Endpoints/DeliveryEndpoints.cs` in the subscription spec means `store_platform/src`.
#: Resolving only against the repo root reported 174 live files as missing.
SEARCH_ROOTS = ("", "prospector", "scripts", "tools",
                "store_platform/src",
                "store_platform/src/Store.Web", "store_platform/src/Store.Web/src",
                "store_platform/src/Ops.Console", "store_platform/src/Ops.Console/src")

#: Docs whose paths are rooted in ANOTHER repo. The Telegram programme cites the Hermes
#: checkout; testing those paths against this root reports every one of them missing, which is
#: a linter that is wrong 100% of the time on that file. They still get the provider check.
CROSS_REPO_FILES = frozenset({"docs/TELEGRAM_OPERATOR_PROGRAM.md"})

#: A line saying this is asserting the mention is historical, not an instruction.
WAIVER = "doc-lint-ok"

#: Every provider name that has ever appeared in this repo's config or adapters. The check is
#: "named but not selected", so the vocabulary has to include the dead ones — that is the whole
#: point. Adding a new provider means adding it here as well as to config.yaml.
KNOWN_PROVIDERS = frozenset({
    "gemini", "cursor_cli", "standardcompute", "deepseek", "minimax", "claude_cli",
    "ddg", "exa", "searxng", "ollama", "mock", "brave", "serper",
})

#: Extensions that make a backticked token a path claim rather than a word in code font.
PATH_SUFFIXES = (".py", ".md", ".yaml", ".yml", ".json", ".sh", ".ts", ".tsx", ".cs",
                 ".jsonl", ".txt", ".toml", ".ini", ".plist")

#: `path`, `path:123`, `path:12-30`. The line/range suffix is how this repo cites code, so it
#: has to be stripped before the path is tested — otherwise every citation reads as missing.
_LINE_REF = re.compile(r":\d+(?:-\d+)?$")

#: Backticked spans only. Bare words in prose are not path claims, and treating them as such
#: produces a linter nobody can keep green.
_CODE_SPAN = re.compile(r"`([^`\n]+)`")


def _is_path_claim(token: str) -> bool:
    """Whether a backticked token is claiming a file exists.

    Placeholders (`<candidate_id>.json`, `store/dossiers/*.pass.json`) are claims about a
    SHAPE, not about a file, so they are not checked. Neither is a shell command that merely
    contains a path — the command is checked when it is a bare path, which is how docs cite.
    """
    if not token or " " in token or token.startswith("-"):
        return False
    if any(ch in token for ch in "<>*{}$|"):
        return False
    if token.startswith(("http://", "https://", "/", "~")):
        return False
    # A bare filename is NOT a path claim. `cockpit.py` in the Telegram programme means a file in
    # the Hermes repo; requiring a directory separator was the difference between 815 findings
    # and the handful that are actually about this repo. A doc that wants to be checked cites
    # the way this repo cites: `prospector/ops/console_api.py:147`.
    if "/" not in token:
        return False
    return token.endswith(PATH_SUFFIXES) or _LINE_REF.search(token) is not None


def selected_providers(config_path: Path) -> set[str]:
    """Every provider name `config.yaml` actually selects, read as text.

    Deliberately NOT a YAML parse of specific keys: a provider can be selected under
    `operator:`, `noncritical_operator:`, `moat_primary:`, `retrieval.provider:` or `pricing:`,
    and a reader that knows only some of those reports a live provider as dead. Any appearance
    of the name in the config counts as selected.
    """
    if not config_path.exists():
        return set()
    text = config_path.read_text(errors="replace")
    return {name for name in KNOWN_PROVIDERS if re.search(rf"\b{re.escape(name)}\b", text)}


def _scan_files() -> list[Path]:
    seen: list[Path] = []
    for pattern in SCAN_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.append(path)
    return seen


def _is_historical(rel: str) -> bool:
    return any(rel == h or rel.startswith(f"{h}/") for h in HISTORICAL_FILES)


@functools.lru_cache(maxsize=1)
def _tracked() -> frozenset[str]:
    """Every path git tracks, and every directory holding one.

    A doc's paths must be graded against the REPOSITORY, never against this machine's disk.
    Judging by `Path.exists()` made the count depend on whatever untracked output happened to
    be lying around: the same tree scored 88 findings in the shared checkout and 91 in a fresh
    worktree, because `scratchpad/results.jsonl`, `.popdd/last_verify.json` and
    `graphify-out/graph.json` exist in one and not the other. A per-file baseline is worthless
    if the number moves with the machine — the ratchet then fails for a reviewer, in CI and in
    any clean clone, on docs nobody touched. Git's index is the same everywhere, so this is.

    A path git does not track is one a reviewer cloning the repo will not have. Saying so is
    the honest finding, not a false positive.
    """
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError):
        return frozenset()  # not a git tree; _resolve falls back to disk

    paths: set[str] = set()
    for rel in out.stdout.split("\0"):
        if not rel:
            continue
        paths.add(rel)
        parent = PurePosixPath(rel).parent
        while str(parent) not in (".", "/"):
            paths.add(str(parent))
            parent = parent.parent
    return frozenset(paths)


def _resolve(bare: str) -> Path | None:
    """The repo path this claim names, or None if the repo does not have it."""
    tracked = _tracked()
    for root in SEARCH_ROOTS:
        rel = f"{root}/{bare}" if root else bare
        rel = PurePosixPath(rel).as_posix()
        if tracked:
            if rel in tracked:
                return REPO_ROOT / rel
        elif (REPO_ROOT / rel).exists():  # no git index available
            return REPO_ROOT / rel
    return None


def lint(config_path: Path | None = None) -> list[dict]:
    """Return one finding per problem. An empty list is the green state."""
    live = selected_providers(config_path or (REPO_ROOT / "config.yaml"))
    dead = KNOWN_PROVIDERS - live
    findings: list[dict] = []

    for path in _scan_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        historical = _is_historical(rel)
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if WAIVER in line:
                continue

            for token in ([] if rel in CROSS_REPO_FILES else _CODE_SPAN.findall(line)):
                if not _is_path_claim(token):
                    continue
                bare = _LINE_REF.sub("", token)
                target = _resolve(bare)
                if target is None:
                    findings.append({"file": rel, "line": lineno, "kind": "missing_path",
                                     "detail": token,
                                     "why": "the doc points at a path that is not there"})
                elif target.is_file() and target.stat().st_size == 0:
                    findings.append({"file": rel, "line": lineno, "kind": "empty_path",
                                     "detail": token,
                                     "why": "the path exists but is 0 bytes, so running it "
                                            "does nothing"})

            if historical:
                continue
            for name in sorted(dead):
                if re.search(rf"\b{re.escape(name)}\b", line):
                    findings.append({"file": rel, "line": lineno, "kind": "retired_provider",
                                     "detail": name,
                                     "why": f"config.yaml does not select {name}; add "
                                            f"`{WAIVER}` to the line if the mention is history"})
    return findings


#: Per-file counts as they stood when the linter was written. 89 findings across 24 docs is a
#: real backlog, and turning it into a red build on day one gets the check switched off. The
#: ratchet is the same mechanism `test_swallowed_failures_can_only_go_down.py` already uses:
#: a number may fall, never rise, and a doc not listed here must be clean.
BASELINE_PATH = REPO_ROOT / "docs" / "doc_lint_baseline.json"


def counts_by_file(findings: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f["file"]] = out.get(f["file"], 0) + 1
    return dict(sorted(out.items()))


def check_ratchet(findings: list[dict]) -> tuple[bool, list[str]]:
    """True when no doc got worse. Also reports docs that improved, so the baseline can drop."""
    if not BASELINE_PATH.exists():
        return False, [f"no baseline at {BASELINE_PATH.relative_to(REPO_ROOT)} — "
                       f"run `python3 scripts/doc_lint.py --write-baseline`"]
    baseline = json.loads(BASELINE_PATH.read_text())
    now = counts_by_file(findings)
    problems: list[str] = []
    for rel, count in now.items():
        was = baseline.get(rel, 0)
        if count > was:
            problems.append(f"{rel}: {was} -> {count} — a doc may only get more accurate")
    improved = [f"{rel}: {was} -> {now.get(rel, 0)}"
                for rel, was in baseline.items() if now.get(rel, 0) < was]
    if improved and not problems:
        problems = []  # improving is never a failure; the message below tells you to re-baseline
    return not problems, problems + [f"IMPROVED (re-baseline to lock it in) {i}" for i in improved]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="machine-readable findings")
    parser.add_argument("--list", action="store_true",
                        help="print what would be scanned and which providers are live, then stop")
    parser.add_argument("--check", action="store_true",
                        help="ratchet mode: fail only when a doc got WORSE than the baseline")
    parser.add_argument("--write-baseline", action="store_true",
                        help="record today's per-file counts as the new ceiling")
    args = parser.parse_args(argv)

    if args.list:
        live = selected_providers(REPO_ROOT / "config.yaml")
        print("scanning:")
        for path in _scan_files():
            print(f"  {path.relative_to(REPO_ROOT).as_posix()}")
        print(f"live providers:    {', '.join(sorted(live)) or '(none)'}")
        print(f"retired providers: {', '.join(sorted(KNOWN_PROVIDERS - live))}")
        return 0

    findings = lint()

    if args.write_baseline:
        counts = counts_by_file(findings)
        BASELINE_PATH.write_text(json.dumps(counts, indent=2) + "\n")
        print(f"wrote {BASELINE_PATH.relative_to(REPO_ROOT)}: "
              f"{len(findings)} finding(s) across {len(counts)} doc(s)")
        return 0

    if args.check:
        ok, messages = check_ratchet(findings)
        for message in messages:
            print(message)
        print(f"doc_lint --check: {'PASS' if ok else 'FAIL'} "
              f"({len(findings)} finding(s) total)")
        return 0 if ok else 1

    if args.json:
        print(json.dumps({"ok": not findings, "count": len(findings),
                          "findings": findings}, indent=2))
        return 1 if findings else 0

    if not findings:
        print("doc_lint: clean")
        return 0

    for f in findings:
        print(f"{f['file']}:{f['line']}: {f['kind']}: {f['detail']} — {f['why']}")
    print(f"\ndoc_lint: {len(findings)} problem(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
