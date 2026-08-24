#!/usr/bin/env python3
"""Was this commit the cause of the red main, or did it inherit one?

WHY THIS EXISTS. 2026-08-20, 00:30Z. `.github/workflows/main-green-guard.yml` reverted PR #466
-- the whole central logging build, 48 files -- because main's CI failed twice on the commit
that landed it. Five tests failed. One of them was #466's. The other four,
`test_console_tool_registry_has_no_drift` and four in `test_prune_branches_absorbed.py`, came
from #460 and #467 and were already failing before #466 merged.

The proof is not an argument about the tests. It is the guard's own next CI run: run
32317556934, on the revert commit `739b6d42`, failed on the SAME five tests. Reverting #466 did
not make main green, and could not have. The build was deleted for four failures it did not
cause, and the issue the guard opened named it as the breaking commit.

THE CLASS is attributing a red main to the newest commit without asking whether its parent was
already red. The guard's risk list covers flakes, races, storms, ping-pong and conflicts. It
does not cover the case where main was broken before this commit arrived, and that case is not
rare here: PRs merge without being rebased (issue #404), so main is red from someone else's
merge most of the time it is red at all.

WHAT THIS ANSWERS. Given a sha, look up the CI runs for its FIRST PARENT and report one of:

  already-red  the parent's own CI concluded failure, so main was broken before this commit and
               reverting it cannot be the fix. The guard stands down.
  newly-red    the parent's CI concluded success. This commit is the newest thing that changed,
               so it is the guard's suspect and the revert proceeds as before.
  unknown      the parent has no completed CI run -- nothing was measured, so nothing is claimed
               and the revert proceeds. A guard that stands down on missing evidence would be
               disabled by any change that stops CI running.

`unknown` proceeding is deliberate and is the only one of the three that can still revert good
work. It keeps this check strictly additive: it can stop a wrong revert, never cause one.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ALREADY_RED = "already-red"
NEWLY_RED = "newly-red"
UNKNOWN = "unknown"


def gh_api(path: str) -> object:
    """One seam for every GitHub read, so the tests can replace all of them at once."""
    p = subprocess.run(("gh", "api", path), capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("gh api %s failed: %s" % (path, p.stderr.strip()[:300]))
    return json.loads(p.stdout)


def first_parent(repo: str, sha: str) -> str | None:
    commit = gh_api("repos/%s/commits/%s" % (repo, sha))
    parents = commit.get("parents") or []
    return parents[0]["sha"] if parents else None


def parent_verdict(repo: str, sha: str, workflow: str = "ci.yml") -> tuple[str, str]:
    """(verdict, one line of evidence). Never raises on a missing parent or a missing run."""
    parent = first_parent(repo, sha)
    if not parent:
        return UNKNOWN, "%s has no parent commit" % sha[:8]

    runs = gh_api("repos/%s/actions/workflows/%s/runs?head_sha=%s&per_page=20"
                  % (repo, workflow, parent)).get("workflow_runs") or []
    # A re-run keeps the run id and rewrites its conclusion, so the answer is the run touched
    # LAST, not the one created last. Taking the first row would read a superseded failure as
    # the parent's verdict and stand the guard down on a run that has since gone green.
    done = [r for r in runs if r.get("status") == "completed"]
    if not done:
        return UNKNOWN, "parent %s has no completed %s run" % (parent[:8], workflow)
    newest = max(done, key=lambda r: r.get("updated_at") or "")

    if newest.get("conclusion") == "failure":
        return ALREADY_RED, ("parent %s already failed CI: %s"
                             % (parent[:8], newest.get("html_url") or newest.get("id")))
    return NEWLY_RED, ("parent %s concluded %s: %s"
                       % (parent[:8], newest.get("conclusion"), newest.get("html_url") or ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", required=True, help="the commit the failing run tested")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""),
                    help="owner/name; defaults to $GITHUB_REPOSITORY")
    ap.add_argument("--workflow", default="ci.yml")
    args = ap.parse_args(argv)
    if not args.repo:
        print("--repo or $GITHUB_REPOSITORY is required", file=sys.stderr)
        return 2

    try:
        verdict, why = parent_verdict(args.repo, args.sha, args.workflow)
    except Exception as exc:                     # noqa: BLE001 - see UNKNOWN above
        # An API failure must not stand the guard down: that would turn any GitHub outage into
        # a red main nobody recovers from. It is unknown evidence, and unknown proceeds.
        verdict, why = UNKNOWN, "could not read the parent's CI: %s" % exc

    print("%s: %s" % (verdict, why))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write("verdict=%s\n" % verdict)
            fh.write("why=%s\n" % why.replace("\n", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
