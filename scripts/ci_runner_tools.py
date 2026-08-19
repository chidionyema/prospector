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
    args = parser.parse_args()

    declared = declared_packages(DOCKERFILE)
    failures: list[str] = []

    print(f"DECLARED — {DOCKERFILE.relative_to(REPO_ROOT)} installs {len(declared)} packages")
    for binary, (package, why) in sorted(REQUIRED.items()):
        if package in declared:
            continue
        failures.append(
            f"  {binary}: needs apt package `{package}`, which the runner image does not "
            f"install. Why it is needed: {why}."
        )

    grade_path = args.require_present or not hosted_runner()
    if grade_path:
        print("PRESENT — grading PATH on this runner")
        for binary, (package, why) in sorted(REQUIRED.items()):
            if shutil.which(binary) is None:
                failures.append(
                    f"  {binary}: not on PATH (apt package `{package}`). Why it is needed: "
                    f"{why}. A step that calls it will exit 127."
                )
    else:
        print(
            "PRESENT — NOT APPLICABLE: RUNNER_ENVIRONMENT is "
            f"{os.environ.get('RUNNER_ENVIRONMENT', 'unset')}, so PATH here belongs to "
            "GitHub's image, not ours. Passing would prove nothing."
        )

    if failures:
        print("\nRUNNER IMAGE IS MISSING TOOLS OUR WORKFLOWS RUN:", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        print(
            "\nFix: add the package to the apt-get install list in "
            "deploy/runner/Dockerfile, then rebuild and restart the fleet with "
            "`deploy/runners.sh up`.",
            file=sys.stderr,
        )
        return 1

    print(f"\nOK — all {len(REQUIRED)} required tools are accounted for.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
