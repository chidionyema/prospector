#!/usr/bin/env python3
"""Split a kustomize build into the policies and the workloads they must judge, and refuse a
build that has nothing to judge.

WHY THIS IS A FILE AND NOT SIX LINES INSIDE THE WORKFLOW. It was inline python in
`.github/workflows/k8s-manifests.yml` first. Nothing could test it there without re-implementing
it, and a test that re-implements the thing it grades passes on the day the original changes —
which is the "grade a proxy" mistake this estate has made four times in one day. Here it is
importable, so `tests/unit/test_the_k8s_gate_cannot_pass_on_nothing.py` calls THIS code, and the
workflow calls it too.

WHAT IT PREVENTS. `kyverno apply` reports `pass: 0, fail: 0, warn: 0, error: 0` when handed no
resources, and exits 0. That is indistinguishable from success in a log, in a check mark and in a
summary line. An admission gate that grades nothing is worse than no gate: it is a green light
nobody will look behind. So this refuses, loudly, rather than emitting an empty file.

Usage:
    kubectl kustomize deploy/k8s/overlays/production > build.yaml
    python3 deploy/k8s/split_workloads.py build.yaml workloads.yaml production

Exit 0 and write the workload documents. Exit 1 with the reason on stderr otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The floor is the count the build actually produces, and it is RAISED whenever a manifest lands.
# A floor left at the day-one number stops catching anything the day two arrives: it was 4 when
# base/engine.yaml was the only workload, and a build that had silently dropped the store API, the
# storefront and the edge would still have cleared it. Measured 2026-08-24 on both overlays: 15
# non-policy documents — the Namespace, a PVC/Deployment/Service each for the engine and the store
# API, a Deployment/Service/PodDisruptionBudget for the storefront, and a ClusterIssuer, a Gateway
# and three HTTPRoutes for the edge.
#
# The Deployment is named separately because it is the only kind most of the 26 policies have any
# opinion about — a build that kept the Namespace and lost the workload would still clear a bare
# count. That asymmetry is worth stating for the edge documents too: Gateway, HTTPRoute and
# ClusterIssuer contributed 0 of the 91 passes, because no policy in the set matches them. They are
# in the count so a dropped file is caught, not because they were checked.
MINIMUM_DOCUMENTS = 15
REQUIRED_KIND = "Deployment"


def split(build: str) -> tuple[list[str], list[str]]:
    """Return (workload documents, their kinds), dropping every ClusterPolicy.

    The policies are dropped because they are the graders, not the graded. Feeding them back in
    would have the policy set judge itself, which is both meaningless and noisy.
    """
    docs = [d for d in build.split("\n---\n") if d.strip()]
    keep = [d for d in docs if "kind: ClusterPolicy" not in d]
    kinds = [line.split(": ", 1)[1].strip()
             for d in keep for line in d.splitlines() if line.startswith("kind: ")]
    return keep, kinds


def check(keep: list[str], kinds: list[str], label: str) -> str | None:
    """The reason this build cannot be graded, or None when it can."""
    if REQUIRED_KIND not in kinds:
        return (f"{label} builds no {REQUIRED_KIND}. There is nothing for an admission policy to "
                f"have an opinion about, so the gate would report success while grading nothing. "
                f"Kinds found: {kinds or 'none'}.")
    if len(keep) < MINIMUM_DOCUMENTS:
        return (f"{label} builds only {len(keep)} non-policy document(s): {kinds}. It has had "
                f"{MINIMUM_DOCUMENTS} since 2026-08-24, so something was dropped from "
                f"deploy/k8s/base/kustomization.yaml or from the overlay.")
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    build_path, out_path, label = argv[1], argv[2], argv[3]
    keep, kinds = split(Path(build_path).read_text())
    reason = check(keep, kinds, label)
    if reason:
        print(f"FAIL: {reason}", file=sys.stderr)
        return 1
    Path(out_path).write_text("\n---\n".join(keep))
    print(f"{label}: grading {len(keep)} workload document(s): {', '.join(kinds)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
