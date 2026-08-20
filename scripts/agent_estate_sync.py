#!/usr/bin/env python3
"""Mirror the agent estate -- ~/.claude -- into this repo, and fail when the two drift.

WHY THIS EXISTS
---------------
Founder, 2026-08-20: "~/.claude/ is not a git repo, easy fix is to copy into prospector".

`~/.claude` holds the laws every session reads and the hook scripts that refuse the mistakes this
estate has already paid for. Measured 2026-08-20: `settings.json` wires 19 hook commands, 14 of
them naming a script under `~/.claude/scripts/`, and 31 of those 33 scripts were in no version
control anywhere. They had one copy, on one disk, with no diff, no history and no review.

`docs/STACK_FLAKINESS_AUDIT.md` section on M2 records the second- and third-order costs: a fresh
laptop gets zero guards and nothing announces it, so the estate silently reverts to the behaviour
each guard was written to stop; and the thirty-minute migration bar cannot be met by a way of
working that does not move at all.

WHY IT IS NOT A NEW MECHANISM
-----------------------------
`scripts/claude_guards/` already held `idle-guard.py` and `wire-idle-guard.sh`, and
`~/.claude/scripts/` reaches both through a symlink into it (`docs/ESTATE_MAP.md` section 11 warns
against "fixing" that symlink during a recovery). This extends that directory from 2 files to the
whole vetted set rather than opening a second home for the same thing.

The two symlinked files need no special case: a symlink reads as its target's bytes, so `--capture`
sees them as already identical and writes nothing.

WHY IT IS AN ALLOW-LIST
-----------------------
`~/.claude` is 7.5 GB and almost none of it may enter a git repo: `projects/` is 5.9 GB of session
transcripts and memory, `telemetry/` is 1.2 GB, `directives/` is the founder-message archive, and
`.credentials.json` holds a live OAuth token. A deny-list fails OPEN -- whatever the CLI grows next
is committed by default. An allow-list only ever fails by leaving something out, which is the safe
direction, and PAIRS below is the whole of it.

WHY IT SCANS
------------
`scripts/backup_agent_estate.py` found real key material inside the same estate: a private key in a
checkpoints directory and a GitHub token archived in the directive log. Neither is inside this
allow-list, but the allow-list is a claim about paths, not about contents. So `--capture` reads the
bytes of every file it is about to write and refuses the whole run if any of them carries a
credential shape. Scanned 2026-08-20 over all 43 files: none.

THREE VERBS, DELIBERATELY SEPARATE
----------------------------------
    scripts/agent_estate_sync.py --capture   ~/.claude -> repo   take this machine's copy in
    scripts/agent_estate_sync.py --check     compare, exit 1     the gate; says which way it drifted
    scripts/agent_estate_sync.py --install   repo -> ~/.claude   bootstrap a bare machine

`--check` is the one that runs unattended. It exits 0 and says so when `~/.claude` is absent, so it
is harmless on CI and inside a container, where there is no agent estate to compare against.
"""
from __future__ import annotations

import argparse
import filecmp
import os
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIRROR = REPO_ROOT / "scripts" / "claude_guards"


def home_claude() -> Path:
    """The live estate. `CLAUDE_HOME` exists so the tests can point this at a temp directory."""
    return Path(os.environ.get("CLAUDE_HOME") or (Path.home() / ".claude"))


#: (path under ~/.claude, path under the mirror). "." maps a directory's files flat into the
#: mirror root, which is the layout the two existing symlinks already assume.
#:
#: CLAUDE.md is renamed on the way in. A file named `CLAUDE.md` anywhere in this tree is read by
#: Claude Code as instructions scoped to its directory, so a verbatim copy of the GLOBAL laws
#: would start governing the repo that is merely storing them.
PAIRS: tuple[tuple[str, str], ...] = (
    ("CLAUDE.md", "CLAUDE.global.md"),
    ("settings.json", "settings.json"),
    ("scripts", "."),
    ("skills", "skills"),
)

KEEP_SUFFIXES = frozenset({".py", ".sh", ".json", ".md", ".yaml", ".yml", ".toml"})

#: Tool droppings: no information, and they change on every run.
SKIP_PARTS = frozenset({"__pycache__", ".pytest_cache", ".DS_Store", "node_modules", ".git"})

#: A backup file is a snapshot of a moment, not the current rule. Tracking them doubles the file
#: count and makes every diff ambiguous about which copy is the one that runs.
SKIP_RE = re.compile(r"\.bak(-[\w.-]+)?$|~$|\.orig$|\.rej$|\.tmp$")

#: Written by this repo, about the mirror. Not part of the estate, so not drift when absent there.
NOT_MIRRORED = frozenset({"README.md"})

#: Shapes, never values. A match names the class and the file; the bytes are never printed.
SECRET_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI-style key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("GitHub token", re.compile(r"(?:ghp_|gho_|ghs_|ghu_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Fly token", re.compile(r"FlyV1 [A-Za-z0-9]")),
    ("PEM private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Slack token", re.compile(r"xox[abposr]-[A-Za-z0-9-]{10,}")),
)


def wanted(rel: Path) -> bool:
    """Whether a file found under an allow-listed directory is one the mirror carries."""
    if any(part in SKIP_PARTS for part in rel.parts):
        return False
    if SKIP_RE.search(rel.name):
        return False
    return rel.suffix.lower() in KEEP_SUFFIXES


def secret_shape(path: Path) -> str | None:
    """The NAME of the credential shape this file carries, or None. Never returns the value."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for name, pattern in SECRET_SHAPES:
        if pattern.search(text):
            return name
    return None


def plan(estate: Path | None = None) -> list[tuple[Path, Path]]:
    """Every (live path under ~/.claude, mirrored path) pair, files only, sorted.

    Raises on two sources mapping to one destination. Without that, adding a PAIRS row whose
    destination overlaps an existing one would silently make one file overwrite the other on
    every capture, and `--check` would report a clean estate while a file was being lost.
    """
    root = estate or home_claude()
    out: list[tuple[Path, Path]] = []
    for src_rel, dst_rel in PAIRS:
        src = root / src_rel
        dst = MIRROR if dst_rel == "." else MIRROR / dst_rel
        if src.is_file():
            out.append((src, MIRROR / dst_rel))
        elif src.is_dir():
            for f in sorted(src.rglob("*")):
                rel = f.relative_to(src)
                if f.is_file() and wanted(rel):
                    out.append((f, dst / rel))
    seen: dict[Path, Path] = {}
    for src, dst in out:
        if dst in seen and seen[dst] != src:
            raise ValueError(f"two sources map to {dst}: {seen[dst]} and {src}")
        seen[dst] = src
    return sorted(out)


def mirrored_files() -> list[Path]:
    """Every file the mirror currently carries, excluding this repo's own notes about it."""
    return sorted(
        f for f in MIRROR.rglob("*")
        if f.is_file()
        and f.name not in NOT_MIRRORED
        and not any(part in SKIP_PARTS for part in f.relative_to(MIRROR).parts)
    )


def capture() -> int:
    pairs = plan()
    if not pairs:
        print(f"nothing to capture: {home_claude()} carries none of {[p[0] for p in PAIRS]}")
        return 1
    refused = [(src, shape) for src, _ in pairs if (shape := secret_shape(src))]
    if refused:
        for src, shape in refused:
            print(f"REFUSED {src}: carries a {shape}", file=sys.stderr)
        print("\nNothing was written. A credential does not go into a git repo, private or not.",
              file=sys.stderr)
        return 2
    written = 0
    for src, dst in pairs:
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written += 1
    print(f"captured {len(pairs)} files from {home_claude()}, {written} changed")
    return 0


def differences() -> list[str]:
    """One line per file that differs, saying WHICH SIDE has it. Direction decides the fix."""
    out: list[str] = []
    pairs = plan()
    for src, dst in pairs:
        rel = dst.relative_to(MIRROR)
        if not dst.exists():
            out.append(f"UNTRACKED  {rel}  (live on this machine, absent from the repo)")
        elif not filecmp.cmp(src, dst, shallow=False):
            out.append(f"DRIFTED    {rel}  (the live copy and the tracked copy differ)")
    live = {dst for _, dst in pairs}
    for f in mirrored_files():
        if f not in live:
            out.append(f"ORPHANED   {f.relative_to(MIRROR)}  (in the repo, not on this machine)")
    return out


def check() -> int:
    estate = home_claude()
    if not estate.is_dir():
        print(f"no agent estate at {estate}; nothing to compare, so nothing to report")
        return 0
    diffs = differences()
    if not diffs:
        print(f"agent estate matches the repo: {len(plan())} files")
        return 0
    print("\n".join(diffs))
    print(f"\n{len(diffs)} difference(s). `--capture` takes this machine's copy into the repo; "
          "`--install` takes the repo's copy onto this machine.")
    return 1


def install(force: bool) -> int:
    """Write the tracked estate onto this machine. The bare-laptop bootstrap.

    It refuses to clobber by default. On a machine that already has an estate, a file that
    differs is KEPT and named, because the local copy may be the newer rule and overwriting it
    silently is the failure this whole mirror exists to stop.
    """
    estate = home_claude()
    pairs: list[tuple[Path, Path]] = []
    for src_rel, dst_rel in PAIRS:
        tracked = MIRROR if dst_rel == "." else MIRROR / dst_rel
        target = estate / src_rel
        if dst_rel != "." and tracked.is_file():
            pairs.append((tracked, target))
        elif tracked.is_dir():
            for f in sorted(tracked.rglob("*") if dst_rel != "." else tracked.glob("*")):
                rel = f.relative_to(tracked)
                if f.is_file() and f.name not in NOT_MIRRORED and wanted(rel):
                    pairs.append((f, target / rel))
    written, kept = 0, 0
    for tracked, target in pairs:
        if target.exists() and not force and not filecmp.cmp(tracked, target, shallow=False):
            print(f"KEPT   {target}  (differs from the repo; --force overwrites)")
            kept += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tracked, target)
        if target.suffix in {".sh", ".py"}:
            target.chmod(target.stat().st_mode | 0o111)
        written += 1
    print(f"installed {written} files into {estate}, kept {kept}")
    return 1 if kept else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--capture", action="store_true", help="~/.claude -> the repo mirror")
    g.add_argument("--check", action="store_true", help="compare the two, exit 1 on drift")
    g.add_argument("--install", action="store_true", help="the repo mirror -> ~/.claude")
    ap.add_argument("--force", action="store_true", help="with --install, overwrite differences")
    args = ap.parse_args(argv)
    if args.capture:
        return capture()
    if args.check:
        return check()
    return install(args.force)


if __name__ == "__main__":
    raise SystemExit(main())
