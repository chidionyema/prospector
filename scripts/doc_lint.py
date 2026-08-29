#!/usr/bin/env python3
"""Fail a doc that points at something which is not there any more.

ENG-6 was a doc that told an operator to run a provider no config had selected for weeks.
Nothing caught it, because prose has no compiler. This is the compiler.

Four checks, and each one exists because that exact shape of rot has happened here:

1. **A referenced path that does not exist.** `RUN.md` sent readers to a module that had moved.
2. **A referenced path that exists and is empty.** `prospector/publish.py` is a 0-byte stub; a
   doc naming it reads as correct to grep and to a human skimming, and is useless to run.
3. **A provider named as if it were current, that `config.yaml` does not select.** `RUN.md:95`
   said the moat was "Claude+Gemini". There has been no `gemini` key in `config.yaml` for weeks.
4. **A deep link that does not resolve.** A `[text](docs/X.md#anchor)` whose file moved or
   whose heading was reworded still looks like a citation and takes the reader nowhere.
   This one runs only under `--links` and stays out of the ratchet baseline; see the block
   above `main` for why.

Check 3 must not ban discussing a retired provider — the incidents ARE the reasoning behind
the current rules, and `CLAUDE.md` is mostly that. So a line carrying `doc-lint-ok` is exempt,
and whole files can be exempted in HISTORICAL_FILES. The point is to catch instructions, not
to erase history.

Usage
-----
    python3 scripts/doc_lint.py            # report; exit 1 if anything is wrong
    python3 scripts/doc_lint.py --json     # same, machine-readable
    python3 scripts/doc_lint.py --list     # what it scanned and what it knows, then exit 0
    python3 scripts/doc_lint.py --links    # every relative link and #anchor in every tracked
                                           # .md; exit 1 if any does not resolve
    python3 scripts/doc_lint.py --check    # ratchet: a doc may not get worse, and a suppression
                                           # may not outlive the deadline written beside it

Report-only by design. It never edits a doc.
"""
from __future__ import annotations

import argparse
import functools
import json
import posixpath
import re
import subprocess
import sys
from datetime import date, timedelta
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
                "store_platform/src/Store.Api", "store_platform/src/Store.Tests",
                "store_platform/src/Store.Web", "store_platform/src/Store.Web/src",
                "store_platform/src/Store.Web/src/pages",
                "store_platform/src/Ops.Console", "store_platform/src/Ops.Console/src",
                "store_platform/src/Ops.Console/src/pages")

#: Directories the ENGINE writes at run time. Git will never track `store/prospector.jsonl` — it
#: is 211 MB of ledger (`docs/RUNBOOKS.md:190`) — so `_tracked()` called every mention of it a
#: broken reference, and a doc telling an operator where the ledger lives was punished for being
#: right. These are paths the running system CREATES; a clone is not supposed to ship them. A doc
#: naming one is claiming where output goes, and the code that writes it is what checks that
#: claim. Measured 2026-08-17: this class was 11 of the 25 findings failing the ratchet on `main`.
RUNTIME_ROOTS = ("store/", "storage/", "corpora/", "graphify-out/", "scratchpad/",
                 ".popdd/", ".lux/receipts/", ".backfill-logs/")

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
    # An elided path is a shape too. `store_platform/.../lib/copyConfig.ts` and
    # `142717e797740247/…:14-16` name a real file by pointing at it, not by spelling it; testing
    # the literal text can only ever report missing, so it is a linter that is wrong every time.
    if "..." in token or "…" in token:
        return False
    if token.startswith(("http://", "https://", "/", "~")):
        return False
    # A token that OPENS with a colon is a line reference continuing a citation already made --
    # "set at `verify.py:481-493`, persisted at `:527/:534/:553/:561`". There is no path in it to
    # resolve. Reading one as a path reports a file missing that the doc never claimed exists,
    # and the slashes between the line numbers are what makes it look like one.
    if token.startswith(":"):
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


def _resolve(bare: str, doc_dir: str = "") -> Path | None:
    """The repo path this claim names, or None if the repo does not have it.

    `doc_dir` is the directory of the doc making the claim, and it is tried FIRST, because
    that is how a markdown link actually resolves: `docs/A.md` writing `[x](incidents/x.json)`
    means `docs/incidents/x.json`, not `incidents/x.json` at the repo root. Without it every
    doc that links a sibling file was reported as pointing at a missing path — a false finding
    the baseline then froze, which is the whole doc-rot-ratchet failure in miniature.
    """
    if bare.startswith(RUNTIME_ROOTS):
        # Runtime output. Not in the index anywhere, by design, so grading it against the index
        # only measures that fact over and over. Return the path so the empty-file check can
        # still run when the file happens to be here.
        return REPO_ROOT / bare
    tracked = _tracked()
    for root in ((doc_dir,) + SEARCH_ROOTS if doc_dir else SEARCH_ROOTS):
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
                target = _resolve(bare, PurePosixPath(rel).parent.as_posix().strip("."))
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

#: How long a NEW suppression gets before it has to be gone. A ratchet with no burn-down date is
#: a warning fence, and a warning fence is not a fence: on 2026-08-18 this file held all 45 live
#: findings, so `--check` was green while every finding was real
#: (docs/incidents/INC-2026-08-18-doc-rot-ratchet.json).
BASELINE_FIRST_DUE_DAYS = 30

#: Deadlines are staggered a week apart, cheapest doc first, so the burn-down is a queue rather
#: than one day on which fourteen docs come due at once and everybody re-baselines instead.
BASELINE_STAGGER_DAYS = 7


def _baseline_entries(raw: dict) -> dict[str, tuple[int, str | None]]:
    """Read either baseline shape as (ceiling, deadline).

    A bare int is the OLD shape: a ceiling that never expires. It is still read, so an old
    baseline does not crash, but `check_ratchet` refuses it -- see there for why.
    """
    out: dict[str, tuple[int, str | None]] = {}
    for rel, value in raw.items():
        if isinstance(value, dict):
            out[rel] = (int(value.get("count", 0)), value.get("expires"))
        else:
            out[rel] = (int(value), None)
    return out


def due_dates(counts: dict[str, int],
              previous: dict[str, tuple[int, str | None]],
              today: date) -> dict[str, str]:
    """Assign a deadline to every baselined doc, keeping the old one unless the count came DOWN.

    This is the whole mechanism. Without the "unless it came down" rule, `--write-baseline` is a
    snooze button: run it again on the deadline and buy another month, which is exactly how the
    findings this file suppresses became permanent in the first place. A doc only earns a fresh
    deadline by getting more accurate.
    """
    out: dict[str, str] = {}
    fresh = 0
    for rel in sorted(counts, key=lambda r: (counts[r], r)):
        was, when = previous.get(rel, (None, None))
        if when is not None and was is not None and counts[rel] >= was:
            out[rel] = when
            continue
        out[rel] = (today + timedelta(days=BASELINE_FIRST_DUE_DAYS
                                      + BASELINE_STAGGER_DAYS * fresh)).isoformat()
        fresh += 1
    return out


def counts_by_file(findings: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f["file"]] = out.get(f["file"], 0) + 1
    return dict(sorted(out.items()))


def changed_docs(base_ref: str) -> set[str] | None:
    """Docs this branch actually changed, relative to `base_ref`. None if git cannot answer.

    A gate must fail a pull request for what that pull request did, and for nothing else.
    Returning None means "could not tell", and the caller then grades everything -- a shallow
    clone must not silently turn the ratchet off.
    """
    try:
        out = subprocess.run(["git", "diff", "--name-only", f"{base_ref}...HEAD"],
                             cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def check_ratchet(findings: list[dict], scope: set[str] | None = None) -> tuple[bool, list[str]]:
    """True when no doc got worse. Also reports docs that improved, so the baseline can drop.

    `scope` limits which docs may FAIL the run. A doc outside it is still counted and still
    reported, but it cannot turn this pull request red.

    WHY THIS EXISTS. The ratchet graded every doc in the repository against one shared baseline
    file. Any branch that edited a doc without re-baselining turned every OTHER open pull
    request red, for a file none of them had touched. Measured 2026-08-18: main carried 184
    findings across 14 docs, and #319 and #320 both failed `guard` on
    docs/ENGINE_MIGRATION_PROGRAM.md, which neither of them contains a single line of. The
    author of the regression sees green; three strangers see red. That is the defect.
    """
    if not BASELINE_PATH.exists():
        return False, [f"no baseline at {BASELINE_PATH.relative_to(REPO_ROOT)} — "
                       f"run `python3 scripts/doc_lint.py --write-baseline`"]
    entries = _baseline_entries(json.loads(BASELINE_PATH.read_text()))
    now = counts_by_file(findings)
    today = date.today().isoformat()
    problems: list[str] = []
    inherited: list[str] = []
    for rel, count in now.items():
        was, expires = entries.get(rel, (0, None))
        if was and expires is None:
            problems.append(
                f"{rel}: baseline entry has no burn-down date — "
                f"run `python3 scripts/doc_lint.py --write-baseline`")
            continue
        if expires is not None and expires < today and count:
            # Deliberately fatal whether or not this branch touched the doc. `scope` exists so a
            # pull request is not failed by someone else's NEW regression; a deadline is neither
            # new nor a surprise -- it was written into the baseline weeks ago and the file names
            # the day. If this were reported and not fatal, a doc nobody happens to edit would rot
            # forever, which is the exact failure the deadline exists to end.
            problems.append(
                f"{rel}: {count} finding(s) still suppressed, and the suppression expired on "
                f"{expires} — fix the doc. `--write-baseline` only moves the date once the "
                f"count comes DOWN.")
            continue
        if count <= was:
            continue
        message = f"{rel}: {was} -> {count} — a doc may only get more accurate"
        if scope is not None and rel not in scope:
            inherited.append(message)
        else:
            problems.append(message)
    improved = [f"{rel}: {was} -> {now.get(rel, 0)}"
                for rel, (was, _) in entries.items() if now.get(rel, 0) < was]
    if improved and not problems:
        problems = []  # improving is never a failure; the message below tells you to re-baseline
    notes = [f"IMPROVED (re-baseline to lock it in) {i}" for i in improved]
    if inherited:
        notes.append(f"INHERITED from the base branch, not this change ({len(inherited)} doc(s)) "
                     f"-- reported, not fatal:")
        notes.extend(f"    {m}" for m in inherited)
    return not problems, problems + notes


# ---------------------------------------------------------------------------
# Check 4: a deep link that does not resolve.
#
# Deliberately NOT part of `lint()` and NOT in the ratchet baseline. The three checks above
# grade a doc's PROSE against the repo; this one grades its NAVIGATION, over every tracked
# `.md` rather than SCAN_GLOBS. Folding it into `lint()` would move every per-file count in
# `docs/doc_lint_baseline.json` at once, which turns one burn-down queue into two and makes
# `test_doc_lint_never_increases.py` fail for a reason that has nothing to do with doc rot.
#
# It exists because `docs/RESEARCH_INDEX.md` consolidates the estate's research by deep link:
# a link that resolves today and rots next week takes the reader to the wrong claim, and the
# index is the one doc whose entire value is that its pointers land.
# ---------------------------------------------------------------------------

#: A markdown link, excluding images (`![alt](src)`), with an optional `"title"`.
_MD_LINK = re.compile(r'(?<!!)\[([^\]\n]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')

#: An inline code span. A `[text](url)` INSIDE one is prose ABOUT markdown, not a link.
_INLINE_CODE = re.compile(r"`[^`\n]*`")

#: A fenced code block delimiter. Links inside a fence are samples, not navigation.
_FENCE = re.compile(r"^\s*(```|~~~)")

#: An ATX heading, with any trailing closing hashes stripped.
_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def anchor_slug(text: str) -> str:
    """The `#fragment` GitHub generates for this heading text.

    Three rules here were each learned by this instrument reporting a WORKING link as broken,
    so none of them are cosmetic:

    1. **An underscore between word characters is literal, not emphasis.** GitHub keeps it:
       a heading `B. Dead: cta_text has no consumer` anchors at `#b-dead-cta_text-has-no-consumer`.
       Stripping every underscore alongside `*` and `~` reported that link broken when it
       resolves. Only DELIMITER underscores come out.
    2. **GitHub converts each whitespace character to a hyphen and does NOT collapse runs.**
       A spaced em dash `" \u2014 "` loses the dash to the punctuation rule and leaves two
       spaces, so the slug carries a DOUBLE hyphen. Collapsing with a `\\s+` run reported 8
       anchors in `README.md` as broken.
    3. Backticks and inline links in a heading contribute their TEXT, not their markup.
    """
    t = re.sub(r"`([^`]*)`", r"\1", text)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[*~]", "", t)
    t = re.sub(r"(?<!\w)_|_(?!\w)", "", t)
    t = t.strip().lower()
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    return re.sub(r"\s", "-", t)


@functools.lru_cache(maxsize=None)
def heading_anchors(path: Path) -> frozenset[str]:
    """Every `#fragment` this file answers to.

    A repeated heading text gets `-1`, `-2` and so on from GitHub; the bare slug still points
    at the first one, so both forms are accepted.
    """
    found: set[str] = set()
    seen: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return frozenset()
    fenced = False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _ATX.match(line)
        if not m:
            continue
        s = anchor_slug(m.group(2))
        if not s:
            continue
        n = seen.get(s, 0)
        seen[s] = n + 1
        found.add(s if n == 0 else f"{s}-{n}")
        found.add(s)
    return frozenset(found)


def _markdown_files() -> list[str]:
    """Every tracked `.md` path, repo-relative.

    Same doctrine as `_tracked()`: grade against the repository, never against whatever this
    machine happens to have lying around, so the number is the same in a clean clone.
    """
    try:
        out = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError):
        return sorted(p.relative_to(REPO_ROOT).as_posix()
                      for p in REPO_ROOT.rglob("*.md") if p.is_file())
    return [rel for rel in out.stdout.split("\0") if rel]


def check_links() -> tuple[list[dict], dict[str, int]]:
    """Return (findings, tally) for every relative markdown link in every tracked doc.

    `http(s)` and `mailto:` links are counted and not fetched — a network call would make the
    result depend on the weather, and a linter that is red for a reason nobody can fix gets
    switched off.
    """
    tracked = _tracked()
    findings: list[dict] = []
    tally: dict[str, int] = {"ok": 0, "missing_link_target": 0,
                             "missing_anchor": 0, "external": 0}

    for rel in _markdown_files():
        src = REPO_ROOT / rel
        try:
            lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        fenced = False
        for lineno, line in enumerate(lines, 1):
            if _FENCE.match(line):
                fenced = not fenced
                continue
            if fenced:
                continue
            # Blank inline code spans, keeping the line length so column maths still works.
            scan = _INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line)
            for _text, href in _MD_LINK.findall(scan):
                if href.startswith(("http://", "https://", "mailto:")):
                    tally["external"] += 1
                    continue
                path_part, _, frag = href.partition("#")
                if not path_part:
                    target_rel, target = rel, src
                else:
                    target_rel = posixpath.normpath(
                        posixpath.join(posixpath.dirname(rel), path_part))
                    target = REPO_ROOT / target_rel
                known = target_rel in tracked if tracked else target.exists()
                if not known and not target.exists():
                    tally["missing_link_target"] += 1
                    findings.append({"file": rel, "line": lineno,
                                     "kind": "missing_link_target", "detail": href,
                                     "why": "the link points at a path the repo does not have"})
                    continue
                if frag and target.suffix == ".md" and target.is_file():
                    if frag.lower() not in heading_anchors(target):
                        tally["missing_anchor"] += 1
                        findings.append({"file": rel, "line": lineno,
                                         "kind": "missing_anchor", "detail": href,
                                         "why": "the file is there; no heading in it makes "
                                                "that anchor"})
                        continue
                tally["ok"] += 1
    return findings, tally


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="machine-readable findings")
    parser.add_argument("--list", action="store_true",
                        help="print what would be scanned and which providers are live, then stop")
    parser.add_argument("--links", action="store_true",
                        help="check every relative markdown link and #anchor in every tracked "
                             ".md file. Separate from the ratchet: never enters the baseline")
    parser.add_argument("--check", action="store_true",
                        help="ratchet mode: fail only when a doc got WORSE than the baseline")
    parser.add_argument("--write-baseline", action="store_true",
                        help="record today's per-file counts as the new ceiling")
    parser.add_argument("--against", metavar="REF", default=None,
                        help="with --check: only docs changed since REF may fail the run. "
                             "Docs that were already worse on REF are reported, not fatal.")
    args = parser.parse_args(argv)

    if args.list:
        live = selected_providers(REPO_ROOT / "config.yaml")
        print("scanning:")
        for path in _scan_files():
            print(f"  {path.relative_to(REPO_ROOT).as_posix()}")
        print(f"live providers:    {', '.join(sorted(live)) or '(none)'}")
        print(f"retired providers: {', '.join(sorted(KNOWN_PROVIDERS - live))}")
        return 0

    if args.links:
        link_findings, tally = check_links()
        if args.json:
            print(json.dumps({"ok": not link_findings, "count": len(link_findings),
                              "tally": tally, "findings": link_findings}, indent=2))
            return 1 if link_findings else 0
        for f in link_findings:
            print(f"{f['file']}:{f['line']}: {f['kind']}: {f['detail']} — {f['why']}")
        print(f"doc_lint --links: {tally['ok']} ok, "
              f"{tally['missing_link_target']} missing-file, "
              f"{tally['missing_anchor']} missing-anchor, "
              f"{tally['external']} external (not fetched)")
        return 1 if link_findings else 0

    findings = lint()

    if args.write_baseline:
        counts = counts_by_file(findings)
        previous = (_baseline_entries(json.loads(BASELINE_PATH.read_text()))
                    if BASELINE_PATH.exists() else {})
        due = due_dates(counts, previous, date.today())
        payload = {rel: {"count": counts[rel], "expires": due[rel]} for rel in sorted(counts)}
        BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n")
        held = sum(1 for rel in counts
                   if rel in previous and due[rel] == previous[rel][1])
        print(f"wrote {BASELINE_PATH.relative_to(REPO_ROOT)}: "
              f"{len(findings)} finding(s) across {len(counts)} doc(s)")
        if not due:
            # The day the burn-down finishes. There is no next deadline because there is nothing
            # left to be due, and crashing here would make an empty baseline look like a broken
            # tool rather than a finished one.
            print("no deadlines: every doc lints clean, so nothing is suppressed")
        else:
            print(f"next deadline {min(due.values())}; {held} doc(s) kept an existing deadline "
                  f"because their count did not come down")
        return 0

    if args.check:
        scope = changed_docs(args.against) if args.against else None
        if args.against and scope is None:
            print(f"could not diff against {args.against} -- grading every doc")
        elif scope is not None:
            print(f"grading {len(scope)} file(s) changed since {args.against}")
        ok, messages = check_ratchet(findings, scope)
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
