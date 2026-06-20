#!/usr/bin/env python3
"""
Guard against SILENT deletion of protected files.

Background: the account/social-login system (TIE-inherited AuthContext, SocialSignIn,
useProtectedRoute) was deleted bundled inside an unrelated "brand: replace logo" commit
(d98c38b) with no mention in the message. A whole capability vanished without a decision.
This guard makes that un-mergeable: removing a protected path requires an explicit, documented
acknowledgement.

Rule:
  - `.protected-paths` lists Python regexes (one per non-comment line) of critical paths.
  - Compute files DELETED in the range `<base>...HEAD`.
  - If any deleted file matches a protected pattern, FAIL — unless some commit message in
    `<base>..HEAD` carries a `Removes:` trailer (a line starting with `Removes:`). That trailer
    is the author consciously saying "yes, I am removing this, here's why."

Usage:
  python3 scripts/guard_protected_deletions.py [base_ref]      # default base: origin/main
Exit codes: 0 = ok, 1 = protected deletion without acknowledgement, 2 = usage/git error.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROTECTED_FILE = REPO / ".protected-paths"


def git(*args: str) -> str:
    res = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"git {' '.join(args)} failed:\n{res.stderr}", file=sys.stderr)
        raise SystemExit(2)
    return res.stdout


def load_patterns() -> list[re.Pattern]:
    if not PROTECTED_FILE.exists():
        print("No .protected-paths file; nothing to guard.")
        raise SystemExit(0)
    pats = []
    for line in PROTECTED_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pats.append(re.compile(line))
    return pats


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    patterns = load_patterns()

    # Files deleted between the merge-base of `base` and HEAD.
    deleted = [f for f in git("diff", "--diff-filter=D", "--name-only", f"{base}...HEAD").splitlines() if f]
    hits = [f for f in deleted if any(p.search(f) for p in patterns)]

    if not hits:
        print(f"✓ guard: no protected files deleted vs {base}.")
        return 0

    # An explicit `Removes:` trailer anywhere in the range acknowledges the removal.
    bodies = git("log", f"{base}..HEAD", "--format=%B")
    acknowledged = any(line.strip().startswith("Removes:") for line in bodies.splitlines())

    print("Protected files deleted in this change:")
    for f in hits:
        print(f"  - {f}")

    if acknowledged:
        print("\n✓ guard: deletion is acknowledged via a `Removes:` trailer. Allowing.")
        return 0

    print(
        "\n✗ guard FAILED: the above protected file(s) were deleted with no acknowledgement.\n"
        "Protected paths (money rail, engine moat, identity, critical storefront surfaces) must not\n"
        "vanish silently — this is exactly how account/social-login was lost in commit d98c38b.\n\n"
        "If the removal is intentional, say so explicitly: add a trailer to the commit message, e.g.\n\n"
        "    Removes: store_platform/.../AuthContext.tsx — superseded by X, accounts moved to Y\n\n"
        "(amend the commit or add a follow-up commit in this branch carrying the trailer).\n"
        "If it was an accident, restore the file(s).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
