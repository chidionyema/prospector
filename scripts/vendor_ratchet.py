#!/usr/bin/env python3
"""Count a vendor's call-sites and refuse to let the number grow.

WHY THIS EXISTS. On 2026-08-24 the founder asked to eradicate Fly.io. The measurement was 180
tracked files mentioning it, 96 of them executable rather than documentation. That cannot be
deleted in one commit, because production takes money through Fly today and the deploy path for
the live shop is inside that set. Removing it before the cutover breaks the thing being rescued.

So the removal is a ratchet instead. The baseline is committed. A change that adds a reference
fails. A change that removes one passes and lowers the baseline. The count only ever goes down,
and when it reaches zero the vendor is gone with no single dangerous commit anywhere in the
history.

IT IS NOT ABOUT FLY. `vendors.yaml` lists the patterns per vendor, so the next exit reuses this
instead of writing a second copy of it (LAW 34: the estate is the thing that persists, a vendor is
a supplier it happens to be using this month).

    scripts/vendor_ratchet.py                  # report every vendor against its baseline
    scripts/vendor_ratchet.py --check          # exit 1 if any count grew. This is the gate.
    scripts/vendor_ratchet.py --update         # lower the baseline after a real removal
    scripts/vendor_ratchet.py --vendor fly     # one vendor only
    scripts/vendor_ratchet.py --root /tmp/x    # count some other checkout instead of this one
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: `--root` points the counter at a different checkout. It exists so the REFUSE half of this gate
#: can be proved against a throwaway repository instead of against this one. The first version of
#: that test wrote its probe file into the real working tree and ran `git add -N` on it; under
#: pytest-xdist a second test in another worker read the tree at that moment and failed, blaming a
#: file it had never heard of. A test that mutates the estate to prove a point is a flaky test in
#: waiting, and the fix belongs in the tool, not in the test's cleanup block.
BASELINE_REL = Path("ops") / "config" / "vendor_ratchet.json"

# Per vendor: the regex that finds a call-site, and the paths that do not count.
#
# DOCS ARE EXCLUDED ON PURPOSE. A doc saying "we used to run on Fly and here is why we left" is
# the opposite of a dependency, and a ratchet that counted it would push agents to delete the
# history that explains the migration. What counts is a path that would BREAK if the vendor
# vanished tonight.
VENDORS: dict[str, dict] = {
    "fly": {
        "pattern": r"fly\.io|flyctl|\bfly (?:deploy|apps|secrets|ssh|status|machines?|volumes?|scale)\b|\.fly\.dev|fly\.internal|fly\.toml",
        "exclude": r"\.md$|^docs/|^specs/|/incidents/|vendor_ratchet",
    },
}


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


# A COMMENT IS NOT A CALL-SITE, and counting one is grading a proxy.
#
# Measured on 2026-08-24, the first time this ran: the step added to ci.yml to install the gate
# carried a comment saying the founder had asked to eradicate Fly.io, and the counter read its own
# rationale as a new dependency and refused the commit that installed it. Rewording the comment
# would have made the number go down and taught every later agent to write around the counter
# instead of removing anything.
#
# Stripping is deliberately crude. It removes `#` and `//` line comments and `/* */` blocks, and
# it will occasionally strip a `#` inside a string literal. That direction of error is the safe
# one: it can only UNDER-count, so it can only let a real dependency through, never invent one.
# A gate that invents work is abandoned; a gate that misses one is corrected by the next sweep.
_LINE_COMMENT = re.compile(r"(?m)(?:^|\s)(?:#|//).*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_XML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT.sub(" ", text)
    text = _XML_COMMENT.sub(" ", text)
    return _LINE_COMMENT.sub(" ", text)


def count(vendor: str, root: Path = ROOT) -> tuple[int, dict[str, int]]:
    """Return (total occurrences, {path: occurrences}) for one vendor."""
    spec = VENDORS[vendor]
    pat = re.compile(spec["pattern"], re.IGNORECASE)
    skip = re.compile(spec["exclude"], re.IGNORECASE)
    per_file: dict[str, int] = {}
    for rel in tracked_files(root):
        if skip.search(rel):
            continue
        p = root / rel
        try:
            # A binary file is not a call-site. errors="ignore" would silently scan one, so read
            # bytes and give up on anything that is not text.
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        n = len(pat.findall(strip_comments(text)))
        if n:
            per_file[rel] = n
    return sum(per_file.values()), per_file


def load_baseline(root: Path = ROOT) -> dict:
    path = root / BASELINE_REL
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_baseline(data: dict, root: Path = ROOT) -> None:
    path = root / BASELINE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if any count grew")
    ap.add_argument("--update", action="store_true", help="write the current counts as the baseline")
    ap.add_argument("--vendor", help="one vendor instead of all")
    ap.add_argument("--root", default=str(ROOT), help="the checkout to count (default: this one)")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    names = [args.vendor] if args.vendor else sorted(VENDORS)
    unknown = [n for n in names if n not in VENDORS]
    if unknown:
        print(f"unknown vendor: {', '.join(unknown)}", file=sys.stderr)
        return 2

    baseline = load_baseline(root)
    grew = False
    new_baseline = dict(baseline)

    for name in names:
        total, per_file = count(name, root)
        prev = baseline.get(name, {}).get("occurrences")
        prev_files = baseline.get(name, {}).get("files", {})

        if prev is None:
            verdict = "NEW BASELINE"
        elif total > prev:
            verdict = f"GREW +{total - prev}"
            grew = True
        elif total < prev:
            verdict = f"fell -{prev - total}"
        else:
            verdict = "unchanged"

        print(f"{name}: {total} occurrences in {len(per_file)} files  [{verdict}]")

        if prev is not None and total > prev:
            # Say WHICH file grew. A gate that reports only a number makes the next agent
            # re-derive the diff by hand, which is the cost this is supposed to remove.
            for path, n in sorted(per_file.items()):
                was = prev_files.get(path, 0)
                if n > was:
                    print(f"    +{n - was:<4} {path}" + ("   (new file)" if not was else ""))
            print(
                f"    A new {name} reference is a new dependency on a vendor this estate is\n"
                f"    leaving. Use the portable path, or if this really is unavoidable, say why\n"
                f"    in the commit and run: scripts/vendor_ratchet.py --update --vendor {name}"
            )

        new_baseline[name] = {"occurrences": total, "files": per_file}

    if args.update:
        save_baseline(new_baseline, root)
        print(f"baseline written: {BASELINE_REL}")
        return 0

    if args.check and grew:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
