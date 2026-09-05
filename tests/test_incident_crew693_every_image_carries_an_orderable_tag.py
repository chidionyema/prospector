"""crew#693: the storefront on prod ran a 26 Aug image while main was four days newer. CI built
and pushed every merge, tagged with the bare commit sha, and nothing could order those tags, so no
ImagePolicy could pick the newest build and the overlay tag was bumped by hand or not at all.

The guard: every image build also carries main-<run>-<sha>, the shape the platform's ImagePolicy
orders by, and the bare sha stays for attestation. Both are immutable; a moving tag is still refused.
"""

from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "container-images.yml"
ORDERABLE = re.compile(r"^main-(?P<run>[0-9]+)-[0-9a-f]{40}$")


def _tags_input() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text())
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("docker/metadata-action@"):
                return step["with"]["tags"]
    raise AssertionError("container-images.yml has no docker/metadata-action step")


def test_every_image_carries_the_bare_sha_and_the_orderable_tag():
    tags = _tags_input()
    assert "type=sha,format=long,prefix=" in tags, tags
    assert "type=raw,value=main-${{ github.run_number }}-${{ github.sha }}" in tags, tags


def test_the_orderable_tag_shape_is_what_the_platform_policy_orders_by():
    example = "main-2721-" + "a" * 40
    assert ORDERABLE.match(example)
    assert not ORDERABLE.match("main")
    assert not ORDERABLE.match("latest")
    assert not ORDERABLE.match("a" * 40)


def test_no_moving_tag_is_published():
    tags = _tags_input()
    for line in tags.splitlines():
        assert (
            "value=latest" not in line and "value=main," not in line and "type=ref" not in line
        ), line
