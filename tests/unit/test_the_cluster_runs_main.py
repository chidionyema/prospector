"""The OKE probe is the instrument for two pipeline-ledger rows (crew#203).

`main-moves-and-the-cluster-never-rolls-it-out`: the overlay pins images by hand, so main moving
does not roll anything out. `production-runs-code-that-is-not-main`: the cluster can carry an
image other than the pin. Measured 2026-08-26 19:5xZ: engine pin 15 commits behind origin/main,
store pins 50. scripts/oke_release_probe.py reads both halves and grades each; without a cluster
the second half reports BLIND, never a verdict.

Rungs: two properties over the graders' whole input classes, one incident test (the overlay is
pinned to commits the probe can compare), one structure test (the ledger rows name this file).
"""

from __future__ import annotations

import importlib.util
import itertools
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "oke_release_probe.py"
OVERLAY = ROOT / "deploy" / "k8s" / "overlays" / "oke" / "kustomization.yaml"


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("oke_release_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # dataclasses on 3.14 look the module up by name
    spec.loader.exec_module(mod)
    return mod


PIN = "a" * 40
OTHER = "b" * 40


@pytest.mark.parametrize("running,stamp", list(itertools.product((None, PIN, OTHER), repeat=2)))
def test_the_cluster_half_is_blind_without_a_reading_and_never_current_on_a_disagreement(
        probe, running, stamp):
    """Every class of (running, stamp): no reading is BLIND, any disagreement is MISMATCH."""
    v = probe.grade_cluster(PIN, running, stamp)
    if running is None:
        assert v == "BLIND"
    elif running != PIN or (stamp is not None and stamp != PIN):
        assert v == "MISMATCH"
    else:
        assert v == "CURRENT"


@pytest.mark.parametrize("behind", [None, 0, 1, 15, 50, 10_000])
def test_a_pin_is_current_only_at_zero_commits_behind(probe, behind):
    assert probe.grade_pin(behind) == {None: "UNKNOWN_COMMIT", 0: "CURRENT"}.get(behind, "BEHIND")


def test_incident_crew203_the_oke_overlay_pins_every_image_to_a_commit(probe):
    """A pin the probe cannot compare with origin/main is a pin nobody can grade."""
    rows = probe.pins(OVERLAY.read_text(encoding="utf-8"))
    assert rows, f"{OVERLAY} pins no images; the probe would grade nothing"
    for pin in rows:
        assert re.fullmatch(r"[0-9a-f]{40}", pin.tag), (
            f"{pin.image} is pinned to {pin.tag!r}, not a commit; the probe cannot say how far "
            f"behind origin/main it is")


def test_the_ledger_rows_name_this_probe():
    ledger = (ROOT / "tests" / "unit" / "test_the_pipeline_failure_ledger.py").read_text()
    for row in ("main-moves-and-the-cluster-never-rolls-it-out",
                "production-runs-code-that-is-not-main"):
        block = ledger.split(f'"{row}"', 1)[1].split("Mode(", 1)[0]
        assert Path(__file__).name in block, f"ledger row {row} does not name this proof"
