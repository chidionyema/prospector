#!/usr/bin/env python3
"""Does the cluster run main?  One answer per image, from two sources that must agree.

Production runs on OKE. Flux applies deploy/k8s/overlays/oke, and that overlay pins every image
to a commit by hand (`images[].newTag`). Nothing bumps the pin when main moves, so "merged" and
"running" drift apart silently: measured 2026-08-26 the engine pin was 15 commits behind
origin/main and the store pins 50. This probe is the instrument the pipeline failure ledger rows
`main-moves-and-the-cluster-never-rolls-it-out` and `production-runs-code-that-is-not-main` name.

Two readings, graded separately, because each can be wrong on its own:

  pinned   the tag in the overlay, compared with origin/main by `git rev-list --count`
  running  the image the Deployment actually carries, and /app/GIT_SHA inside the engine pod,
           read with kubectl.  Without a reachable cluster this half is BLIND, never a verdict.

    .venv/bin/python scripts/oke_release_probe.py            # git half, cluster half if kubectl works
    .venv/bin/python scripts/oke_release_probe.py --json     # for the console
    .venv/bin/python scripts/oke_release_probe.py --no-cluster

Exit 0 when every pin is origin/main and the cluster (when read) runs the pin; 1 when any image is
BEHIND or the cluster runs something other than the pin; 2 when the git half cannot be read.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "deploy" / "k8s" / "overlays" / "oke" / "kustomization.yaml"
NAMESPACE = "prospector"
STAMP = "/app/GIT_SHA"
MAIN = "origin/main"

Verdict = Literal["CURRENT", "BEHIND", "UNKNOWN_COMMIT", "BLIND", "MISMATCH"]


@dataclass(frozen=True)
class Pin:
    image: str
    tag: str


@dataclass(frozen=True)
class Reading:
    image: str
    pinned: str
    main: str
    behind: int | None  # commits between the pin and main; None when the pin is not a commit
    pin_verdict: Verdict
    running: str | None  # image tag the Deployment carries, None when BLIND
    stamp: str | None  # /app/GIT_SHA from the pod, engine only
    cluster_verdict: Verdict


def pins(text: str) -> list[Pin]:
    """The `images:` list of a kustomization, as (name, newTag). Missing list means no pins."""
    doc = yaml.safe_load(text) or {}
    out: list[Pin] = []
    for row in doc.get("images") or []:
        tag = row.get("newTag")
        if tag is not None:
            out.append(Pin(image=str(row["name"]).rsplit("/", 1)[-1], tag=str(tag)))
    return out


def grade_pin(behind: int | None) -> Verdict:
    if behind is None:
        return "UNKNOWN_COMMIT"
    return "CURRENT" if behind == 0 else "BEHIND"


def grade_cluster(pinned: str, running: str | None, stamp: str | None) -> Verdict:
    """The cluster agrees when what it runs is the pin. A stamp, when present, must also agree."""
    if running is None:
        return "BLIND"
    if running != pinned:
        return "MISMATCH"
    if stamp is not None and stamp != pinned:
        return "MISMATCH"
    return "CURRENT"


def _git(*args: str) -> str | None:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def commits_behind(tag: str, main: str = MAIN) -> int | None:
    if _git("cat-file", "-e", f"{tag}^{{commit}}") is None:
        return None
    n = _git("rev-list", "--count", f"{tag}..{main}")
    return int(n) if n is not None and n.isdigit() else None


def _kubectl(*args: str) -> str | None:
    try:
        p = subprocess.run(["kubectl", "-n", NAMESPACE, *args], capture_output=True, text=True,
                           timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def running_tags() -> dict[str, str] | None:
    """{deployment name: image tag} from the cluster, or None when it cannot be read."""
    raw = _kubectl("get", "deployments", "-o", "json")
    if raw is None:
        return None
    out: dict[str, str] = {}
    for item in json.loads(raw).get("items", []):
        for c in item["spec"]["template"]["spec"]["containers"]:
            image = c["image"]
            name = image.rsplit("/", 1)[-1].split(":", 1)[0]
            out[name] = image.rsplit(":", 1)[-1] if ":" in image else ""
    return out


def running_stamp(deployment: str) -> str | None:
    return _kubectl("exec", f"deploy/{deployment}", "--", "cat", STAMP)


def probe(*, cluster: bool) -> list[Reading]:
    main = _git("rev-parse", MAIN)
    if main is None:
        raise SystemExit(f"cannot read {MAIN}; run `git fetch origin` first")
    live = running_tags() if cluster else None
    out: list[Reading] = []
    for pin in pins(OVERLAY.read_text(encoding="utf-8")):
        behind = commits_behind(pin.tag, main)
        running = live.get(pin.image) if live is not None else None
        stamp = running_stamp(pin.image) if running is not None and "engine" in pin.image else None
        out.append(Reading(pin.image, pin.tag, main, behind, grade_pin(behind), running, stamp,
                           grade_cluster(pin.tag, running, stamp)))
    return out


def exit_code(rows: list[Reading]) -> int:
    if not rows:
        return 2
    bad = {"BEHIND", "MISMATCH", "UNKNOWN_COMMIT"}
    return 1 if any(r.pin_verdict in bad or r.cluster_verdict in bad for r in rows) else 0


def main_() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-cluster", action="store_true", help="git half only; cluster reads BLIND")
    a = ap.parse_args()
    rows = probe(cluster=not a.no_cluster)
    if a.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        for r in rows:
            behind = "not a commit here" if r.behind is None else f"{r.behind} behind"
            print(f"{r.image:<24} pin {r.pinned[:8]} {r.pin_verdict:<14} ({behind} {MAIN} "
                  f"{r.main[:8]})  cluster {r.cluster_verdict}"
                  + (f" runs {r.running[:8]}" if r.running else "")
                  + (f" stamp {r.stamp[:8]}" if r.stamp else ""))
    return exit_code(rows)


if __name__ == "__main__":
    sys.exit(main_())
