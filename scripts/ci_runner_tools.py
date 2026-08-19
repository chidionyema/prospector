#!/usr/bin/env python3
"""The self-hosted runner image carries the tools our workflows actually run.

WHY THIS EXISTS. Our runners are a container we build (``deploy/runner/Dockerfile``), not
GitHub's ``ubuntu-latest``. GitHub's image ships hundreds of packages; ours ships fourteen,
deliberately. So a workflow step written against GitHub's image can run for weeks on hosted
runners and then fail the moment ``vars.CI_RUNS_ON`` is set to ``self-hosted`` — and it fails
as a MISSING COMMAND, which is the worst shape of failure there is:

  * ``python3`` was missing once. It failed as ``python3: command not found``, exit 127,
    AFTER a successful web deploy. The Dockerfile comment still records it.
  * ``openssh-client`` was missing on 2026-08-19. The hermes-config gate fetches a private
    submodule with a read-only deploy key, which speaks SSH and nothing else. The step wrote
    ``ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null``, and the shell
    writes its own "command not found" to that SAME redirected stderr. The job therefore
    produced exit code 127, seventeen milliseconds, and not one character of output.
    (run 32267152679, job 96114329207.)

The class is not "ssh was missing". The class is **a runner image that differs from the one a
workflow was written against, with nothing that reports the difference**. A comment in the
Dockerfile listing why each package is there does not stop a fifteenth being needed and never
added. This does.

TWO CHECKS, because either alone has a hole:

1. DECLARED — every required package appears in the Dockerfile's ``apt-get install`` list.
   This runs anywhere, including on ``ubuntu-latest``, and is what catches someone deleting a
   package from the image.
2. PRESENT — every required binary is on ``PATH``. This is only meaningful when the job is
   running on our own image, so on a GitHub-hosted runner it is reported as NOT APPLICABLE
   rather than quietly passing: ubuntu-latest has all of these, so a pass there proves
   nothing about the image we ship.

TWO KINDS OF FAILURE, AND ONLY ONE OF THEM MAY BLOCK A PULL REQUEST. This distinction was
not in the first version of this script, and the first thing that version did was fail the
very pull request that added the missing package:

  * UNDECLARED — the Dockerfile does not install the package. A pull request can fix that by
    editing one line, so this is FATAL. Exit 1, every time, on every runner.
  * ABSENT — the Dockerfile declares it but the binary is not on PATH. That means the fleet is
    running an image built before the change. NO pull request can fix it; only an operator
    running ``deploy/runners.sh up`` can. Failing here walls every pull request in the
    repository INCLUDING the deploy that would clear it, so by default it is reported as a
    GitHub warning annotation and the step passes. ``--strict`` makes it fatal, which is for
    the fleet probe the operator reads, not for the pull-request gate.

That is not "a warning fence is not a fence". The gate's job is to stop the CODE defect, and
the code defect is UNDECLARED. ABSENT is an operator action, so its fence belongs where the
operator looks: ``scripts/ci_fleet_probe.py`` calls this script with ``--strict`` and the ops
console surfaces the result. That probe arrives with pull request #417; until it merges, the
warning annotation on the job summary is the only signal, which is why the annotation names
the exact command rather than describing the problem.

Standard library only, no virtualenv, no network — it runs in the ``guard`` job beside
``ci_capacity.py``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "deploy" / "runner" / "Dockerfile"

# binary on PATH -> the apt package that provides it, and the caller that needs it.
# Add a row here the moment a workflow step starts depending on a new command. A row costs
# nothing; a missing one costs a bare exit 127 in a job that prints no reason.
REQUIRED: dict[str, tuple[str, str]] = {
    "git": ("git", "actions/checkout"),
    "curl": ("curl", "every setup-* action downloads over https"),
    "jq": ("jq", "deploy/runner/entrypoint.sh parses the registration-token response"),
    "tar": ("tar", "actions/cache"),
    "unzip": ("unzip", "actions/cache and several setup-* actions"),
    "zstd": ("zstd", "actions/cache writes .tzst"),
    "sudo": ("sudo", "third-party actions call it"),
    "python3": ("python3", "the repo's own shell scripts shell out to it"),
    "ssh": ("openssh-client", "a deploy key fetches a private submodule over SSH"),
    "ssh-keyscan": ("openssh-client", "the same step pins github.com's host key"),
    "gpg": ("gnupg", "apt key handling in setup-* actions"),
    "xz": ("xz-utils", "several release tarballs are .tar.xz"),
}


FIX_DECLARE = "add the package to the apt-get install list in deploy/runner/Dockerfile."
FIX_REBUILD = (
    "rebuild and restart the fleet with `deploy/runners.sh up`. Check for in-flight CI runs "
    "first — that deploy uses `--strategy immediate` and will kill them."
)


def declared_packages(dockerfile: Path) -> set[str]:
    """The package names inside the Dockerfile's ``apt-get install`` invocation.

    Parses the RUN line rather than trusting the comment block above it: the comment is prose
    and has been right while the list was wrong.
    """
    text = dockerfile.read_text()
    match = re.search(r"apt-get install[^\n]*\n((?:[^\n]*\\\n)*[^\n]*)", text)
    if not match:
        raise SystemExit(f"{dockerfile}: no `apt-get install` line found — has the image moved?")
    body = match.group(0)
    # Stop at the first `&&`: anything after it is a later command (locale-gen, rm -rf), not
    # a package. Without this the word `locale-gen` reads as a package name.
    body = body.split("&&")[0]
    words = re.split(r"[\s\\]+", body)
    skip = {"apt-get", "install", "-y", ""}
    return {w for w in words if w and w not in skip and not w.startswith("-")}


def hosted_runner() -> bool:
    """True when this is one of GitHub's images rather than ours.

    ``RUNNER_ENVIRONMENT`` is set by the runner agent itself: ``github-hosted`` or
    ``self-hosted``. Falling back to "assume hosted" is the safe default for a laptop, where
    the PRESENT check would grade the developer's Mac and not the image at all.
    """
    return os.environ.get("RUNNER_ENVIRONMENT", "github-hosted") != "self-hosted"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-present",
        action="store_true",
        help="grade PATH even on a GitHub-hosted runner (for testing this script)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "treat a declared-but-absent binary as fatal. For the fleet probe an operator "
            "reads, NOT for the pull-request gate: a stale image is not a code defect and no "
            "pull request can fix it."
        ),
    )
    args = parser.parse_args()

    declared = declared_packages(DOCKERFILE)
    undeclared: list[str] = []
    absent: list[str] = []

    print(f"DECLARED — {DOCKERFILE.relative_to(REPO_ROOT)} installs {len(declared)} packages")
    for binary, (package, why) in sorted(REQUIRED.items()):
        if package in declared:
            continue
        undeclared.append(
            f"  {binary}: needs apt package `{package}`, which the runner image does not "
            f"install. Why it is needed: {why}."
        )

    grade_path = args.require_present or not hosted_runner()
    if grade_path:
        print("PRESENT — grading PATH on this runner")
        for binary, (package, why) in sorted(REQUIRED.items()):
            if shutil.which(binary) is None:
                absent.append(
                    f"  {binary}: not on PATH (apt package `{package}`). Why it is needed: "
                    f"{why}. A step that calls it will exit 127."
                )
    else:
        print(
            "PRESENT — NOT APPLICABLE: RUNNER_ENVIRONMENT is "
            f"{os.environ.get('RUNNER_ENVIRONMENT', 'unset')}, so PATH here belongs to "
            "GitHub's image, not ours. Passing would prove nothing."
        )

    if undeclared:
        print("\nRUNNER IMAGE DOES NOT DECLARE TOOLS OUR WORKFLOWS RUN:", file=sys.stderr)
        for line in undeclared:
            print(line, file=sys.stderr)
        print(f"\nFix: {FIX_DECLARE}", file=sys.stderr)

    if absent:
        # Only the packages the Dockerfile DOES declare reach here — an undeclared one is
        # already fatal above. So this is always the same diagnosis: the fleet predates the
        # Dockerfile. Say that, name the one command that clears it, and do not block.
        stream = sys.stderr if args.strict else sys.stdout
        headline = (
            "THE RUNNING FLEET IS OLDER THAN THE RUNNER DOCKERFILE. These tools are declared "
            "in the image we build but are not on PATH on the machine this job ran on:"
        )
        if not args.strict:
            # A GitHub warning annotation surfaces on the job summary and in the PR's file
            # view, so it is visible without reading the log.
            print(f"::warning title=Runner fleet is stale::{headline}", file=stream)
        else:
            print(f"\n{headline}", file=stream)
        for line in absent:
            print(line, file=stream)
        print(f"\nFix (operator, not a pull request): {FIX_REBUILD}", file=stream)

    if undeclared or (absent and args.strict):
        return 1
    if absent:
        print(
            "\nPASSING ANYWAY — a stale fleet is an operator action, not a code defect. "
            "Blocking here would wall every pull request including the one that rebuilds it. "
            "Run with --strict where an operator reads the result."
        )
        return 0

    print(f"\nOK — all {len(REQUIRED)} required tools are accounted for.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
