"""Every verifier arm that has ever produced a number names the exact commit that produced it.

WHY THIS TEST EXISTS. On 2026-08-20, building the sources table for `docs/ENGINE_100X_PROGRAM.md`
found that nine of the thirteen E-101 arms had been scored with no revision at all:
`_verifier_sidecar.py` called `from_pretrained(model_id)` bare, so each arm loaded whatever
`refs/main` happened to be. The commits were recoverable after the fact from the caches that did
the scoring, but only because those caches still existed. The failure this guards is silent: a
re-run against a moved checkpoint returns a different number with no error and no warning, and a
number that moved for an unrecorded reason reads exactly like a finding.

A memory file would not have stopped it — the previous run had a docstring about reproducibility
and still shipped nine unpinned arms. Only a failing test does.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools" / "experiments"))

from _verifiers import ARMS, unpinned_arms  # noqa: E402

SHA = re.compile(r"^[0-9a-f]{40}$")

# An arm that has never been run has no commit it "was measured at", and inventing one would be a
# fabricated receipt. The exemption is paid for by the second test below, which fails the moment
# such an arm produces a score file — so the exemption cannot outlive the fact that justifies it.
NEVER_SCORED = {"lynx-8b": "designed in the registry, never downloaded and never scored"}

SCORE_LOCATIONS = [HERE / "tools" / "experiments" / "_verifier_cache",
                   HERE / "tools" / "experiments" / "fly_scores"]


def _score_files(arm: str) -> list[Path]:
    return [p for d in SCORE_LOCATIONS if d.is_dir() for p in d.glob(f"{arm}.json")]


def test_every_scored_arm_names_its_commit():
    missing = [a for a in unpinned_arms() if a not in NEVER_SCORED]
    assert not missing, (
        f"these arms name a model but no commit: {missing}. A model id is a repository and a "
        f"repository moves; without a revision the next run can load different weights and report "
        f"a different number with no error. Recover the commit from the HF cache that scored it "
        f"(`refs/main`, or `cached_file()` when a repo has more than one snapshot on disk) and put "
        f"it in tools/experiments/_verifiers.py.")


def test_pins_are_commits_not_branches():
    bad = {n: a.revision for n, a in ARMS.items()
           if a.revision and not SHA.match(a.revision)}
    assert not bad, (f"these pins are not 40-character commit shas: {bad}. 'main' is not a pin — "
                     f"it is the absence of one, spelled differently.")


@pytest.mark.parametrize("arm", sorted(NEVER_SCORED))
def test_an_exempt_arm_really_has_no_scores(arm):
    found = _score_files(arm)
    assert not found, (
        f"{arm} is exempt from pinning on the grounds that it has never been scored "
        f"({NEVER_SCORED[arm]}), but score files exist: {[str(p) for p in found]}. It has a "
        f"number now, so it needs the commit that produced it. Remove it from NEVER_SCORED and "
        f"pin it.")


def test_the_sidecar_actually_uses_the_pin():
    """A pin the loader ignores is decoration. Every from_pretrained must forward the revision."""
    src = (HERE / "tools" / "experiments" / "_verifier_sidecar.py").read_text()
    bare = re.findall(r"from_pretrained\(model_id\s*[,)](?![^)]*_rev)", src)
    assert not bare, (
        f"{len(bare)} from_pretrained call(s) in _verifier_sidecar.py load model_id without "
        f"forwarding **_rev, so the registry's pin does not reach the loader.")
