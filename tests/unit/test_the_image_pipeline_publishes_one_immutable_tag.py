"""The image pipeline may only publish a tag that never moves.

WHY THIS EXISTS. `deploy/k8s/overlays/*/kustomization.yaml` names an image by tag. If the tag
that CI pushes is a moving one -- `latest`, `main`, `edge` -- then the overlay names a moving
target, and the cluster runs whatever was pushed last rather than the commit that was graded.
That defect is invisible in every green check: the manifests apply, the pods start, and the
running code is not the reviewed code. Kyverno's `disallow-latest-tag` does not catch it either;
upstream it refuses `:latest` and an untagged image, and a moving `:main` sails straight past.

WHAT THIS CANNOT SEE. It reads the workflow file, not the registry. It cannot tell you what tags
ghcr.io actually holds, whether a human pushed a `:latest` by hand, or whether a build succeeded.
`gh api /users/<owner>/packages/container/<name>/versions` is the command for that, and it needs
a token with `read:packages`, which is why it is not run here.

Rung 4 of the ladder in ~/AGENTS.md: one incident test per failure mode, asserting the rule and
not the code. The checker below is exercised in both directions in the same run -- a spec it must
refuse and a spec it must permit -- because a guard only ever seen refusing has never been shown
to permit, and a guard that refuses correct work is an outage.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "container-images.yml"

# Every `type=` docker/metadata-action understands that yields a tag which can later point at a
# different image. `sha` and `semver` are the two that cannot, and `sha` is only immutable when
# its prefix is pinned -- the action's default prefix is `sha-`, so an unpinned spec silently
# produces `sha-<40hex>` and no overlay written against the bare SHA will ever match it.
_MOVING_TYPES = ("raw", "ref", "edge", "schedule", "pep440", "match")


def mutable_tag_specs(tags_block: str) -> list[str]:
    """Return the lines of a metadata-action `tags:` block that can name two different images.

    Pure, so the test below can feed it a spec that must be refused without editing the
    workflow to create one.
    """
    offending = []
    for raw in tags_block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("type="):
            # A literal tag. `ghcr.io/x/y:latest` and friends are exactly the failure.
            offending.append(line)
            continue
        kind = line.split("=", 1)[1].split(",", 1)[0]
        if kind in _MOVING_TYPES:
            offending.append(line)
        elif kind == "sha" and not re.search(r"\bprefix=(,|$)", line):
            offending.append(line)
    return offending


def _meta_step() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["build"]["steps"]
    for step in steps:
        if str(step.get("uses", "")).startswith("docker/metadata-action"):
            return step
    raise AssertionError("container-images.yml has no docker/metadata-action step to read")


def _build_step() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in doc["jobs"]["build"]["steps"]:
        if str(step.get("uses", "")).startswith("docker/build-push-action"):
            return step
    raise AssertionError("container-images.yml has no docker/build-push-action step to read")


def test_the_pipeline_emits_only_an_immutable_tag():
    offending = mutable_tag_specs(_meta_step()["with"]["tags"])
    assert not offending, (
        "container-images.yml would publish a tag that can later point at a different image: "
        f"{offending}. The overlays name images by tag, so a moving tag means the cluster runs "
        "whatever was pushed last, not the commit that was graded."
    )


@pytest.mark.parametrize(
    "spec",
    [
        "type=raw,value=latest",
        "type=ref,event=branch",
        "type=edge",
        "type=sha,format=long",  # the default prefix `sha-` is still a pin, but not the one the
        # overlays are written against; an unpinned prefix is a silent mismatch, not a moving tag
        "latest",
        "ghcr.io/chidionyema/prospector-engine:main",
    ],
)
def test_the_checker_refuses_a_tag_that_can_move(spec: str):
    """The must-fail half. Without it, a checker that returns [] unconditionally passes above."""
    assert mutable_tag_specs(spec) == [spec]


@pytest.mark.parametrize("spec", ["type=sha,format=long,prefix=", "type=semver,pattern={{version}}"])
def test_the_checker_permits_a_tag_that_cannot_move(spec: str):
    """The must-permit half. A guard that refuses correct work is an outage (LAW 38)."""
    assert mutable_tag_specs(spec) == []


def test_a_pull_request_publishes_nothing():
    """A PR build proves the Dockerfile still works. It must not put bytes in the registry:
    a fork's PR would otherwise write to the estate's namespace, and an unreviewed SHA would
    become pullable."""
    push = str(_build_step()["with"]["push"])
    assert "github.event_name != 'pull_request'" in push, (
        f"the build step's push: is {push!r}. It must be conditional on the event not being a "
        "pull request, or an unreviewed commit lands in ghcr.io."
    )


def test_the_storefront_build_time_variables_are_checked_before_the_build():
    """NEXT_PUBLIC_* are inlined into the bundle at build time. Empty ones do not fail the
    build; they ship a storefront that calls `undefined` and looks fine until a buyer clicks.
    deploy-web.yml already learned this. The image path has to check the same thing or the k8s
    route reintroduces the bug the Fly route fixed.
    """
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["build"]["steps"]
    names = [str(s.get("name", "")) for s in steps]
    guard = next((i for i, s in enumerate(steps)
                  if "NEXT_PUBLIC_" in str(s.get("run", ""))), None)
    assert guard is not None, (
        "no step checks NEXT_PUBLIC_* before the build; an empty one ships a broken storefront"
    )
    build = next(i for i, s in enumerate(steps)
                 if str(s.get("uses", "")).startswith("docker/build-push-action"))
    assert guard < build, (
        f"the NEXT_PUBLIC_ check is step {guard} ({names[guard]!r}) and the build is step "
        f"{build}; a check after the build cannot stop the broken image being built"
    )
    assert "exit " in str(steps[guard]["run"]), (
        "the check prints but never exits non-zero, so it reports the problem and builds anyway"
    )
