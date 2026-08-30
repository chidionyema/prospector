"""Merged, built and green is not shipped, and something has to say so out loud.

WHAT HAPPENED. 2026-08-30. Four storefront changes -- #785, #788, #789, #790 -- were merged to
main between 2026-08-25 and 2026-08-30. `container images` built and pushed every one of them to
ghcr. Every check on every one of them was green. https://mumchimp.com went on serving the markup
#790 deleted, because the only thing that moves the shop is the `newTag` line for
`ghcr.io/chidionyema/prospector-store-web` in `deploy/k8s/overlays/oke/kustomization.yaml`, no
automation rewrites it (idp#925, still open), and nobody rewrote it by hand.

THE CLASS is `silent-green` from the friction ledger, in its purest form: not one check was wrong.
CI grades the code, the live smoke grades the site, and neither of them was ever asked whether the
site is the code. The founder asked, by looking at his own shop, which is the instrument this
estate is not supposed to be using.

So there are two properties here and they are different. The first is that the pin names a commit
that exists -- a typo in a 40-character sha leaves the cluster pulling a tag ghcr never built, and
that is an outage rather than a lag. The second is that the daily live smoke still holds the job
that asks the question, reporting on its OWN issue label: `live-red` means the shop is failing its
checks right now, and conflating "old but working" with that would make an open issue mean two
things.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "deploy" / "k8s" / "overlays" / "oke" / "kustomization.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "e2e-live-smoke.yml"
WEB_IMAGE = "ghcr.io/chidionyema/prospector-store-web"
WEB_SOURCE = "store_platform/src/Store.Web"


def _pins() -> dict[str, str]:
    cfg = yaml.safe_load(OVERLAY.read_text())
    return {i["name"]: i["newTag"] for i in cfg["images"]}


def test_the_production_overlay_pins_store_web_at_a_commit_this_repository_holds():
    """A pin ghcr never built is not a stale shop, it is an ImagePullBackOff."""
    pin = _pins()[WEB_IMAGE]
    assert re.fullmatch(r"[0-9a-f]{40}", pin), f"not a commit sha: {pin!r}"
    found = subprocess.run(
        ["git", "cat-file", "-e", f"{pin}^{{commit}}"], cwd=ROOT, capture_output=True
    )
    assert found.returncode == 0, f"{OVERLAY.name} pins store-web at {pin}, not a commit here"


def test_the_daily_live_smoke_asks_whether_the_shop_is_the_code():
    """The instrument itself. Delete the job and this is how anyone finds out."""
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    assert "release-lag" in jobs, "nothing grades whether merged storefront code is released"
    job = jobs["release-lag"]

    # Schedule only, on purpose: merging a web change and releasing it minutes later is ordinary
    # work, so a per-push version would sit red for hours of every normal day, and a guard that
    # refuses correct work is an outage.
    assert "schedule" in job["if"], job["if"]

    body = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert WEB_SOURCE in body, "the check does not look at the storefront's source"
    assert WEB_IMAGE in body, "the check does not read the pin it is grading"
    # It must compare the pin against main, not merely read it.
    assert "origin/main" in body, "the check never compares the pin to main"


def test_a_stale_shop_and_a_broken_shop_are_two_different_issues():
    """`live-red` means failing its checks NOW. A working shop running old code is not that."""
    alarm = yaml.safe_load(WORKFLOW.read_text())["jobs"]["alarm"]
    steps = {s["name"]: s for s in alarm["steps"] if "name" in s}

    lag = [s for n, s in steps.items() if "release-lag alarm" in n]
    assert len(lag) == 2, "the lag needs a raise step and a stand-down step of its own"
    for step in lag:
        script = str(step["with"]["script"])
        assert "'release-lag'" in script
        assert "'live-red'" not in script, "a lag must not file or clear the live-outage issue"

    # And the reverse: the live-smoke steps must name their three jobs rather than read
    # `needs.*`, or `release-lag` would open and close the outage issue for them.
    for name in (
        "Raise the alarm (live smoke is red)",
        "Stand the alarm down (live smoke is green again)",
    ):
        assert "needs.*" not in steps[name]["if"], (
            f"{name!r} reads every need, so a release lag would report as a broken shop"
        )
