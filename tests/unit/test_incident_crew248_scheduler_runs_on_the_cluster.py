"""Incident test (rung 4), named for crew#248: no scheduler workload ran anywhere, so
run_decay_sweep never ran and the catalog's verifiedAt froze on 2026-08-16.

The rule: the OKE overlay renders exactly one scheduler Deployment, it runs the scheduler
module as PID 1 from a commit-pinned engine image with no supervisord in front of it, it owns
its dossier store, and its liveness is the scheduler's own --watchdog verdict. Read from
`kubectl kustomize`, because the file on disk is not what reaches the cluster.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "deploy" / "k8s" / "overlays" / "oke"

pytestmark = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl carries kustomize")


def _rendered() -> list[dict]:
    # The overlay pulls kyverno's remote base through git. A laptop's global core.hooksPath
    # (the estate guard router) refuses inside kustomize's temp clone; CI has none.
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
    out = subprocess.run(
        ["kubectl", "kustomize", str(OVERLAY)], check=True, capture_output=True, text=True, env=env
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _scheduler(docs: list[dict]) -> dict:
    found = [
        d
        for d in docs
        if d["kind"] == "Deployment" and d["metadata"]["name"] == "prospector-scheduler"
    ]
    assert len(found) == 1, "exactly one scheduler on the cluster"
    return found[0]


def test_scheduler_is_pid_one_from_a_pinned_engine_image() -> None:
    dep = _scheduler(_rendered())
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert re.fullmatch(r"ghcr\.io/chidionyema/prospector-engine:[0-9a-f]{40}", c["image"]), c[
        "image"
    ]
    assert c["command"] == ["python", "-m", "prospector.scheduler.run_scheduled"]
    assert "--daemon" in c["args"]
    assert "supervisord" not in " ".join(c.get("command", []) + c.get("args", []))


def test_scheduler_owns_its_store_and_reports_its_own_liveness() -> None:
    docs = _rendered()
    dep = _scheduler(docs)
    spec = dep["spec"]["template"]["spec"]
    claim = next(
        v["persistentVolumeClaim"]["claimName"]
        for v in spec["volumes"]
        if "persistentVolumeClaim" in v
    )
    pvcs = {d["metadata"]["name"] for d in docs if d["kind"] == "PersistentVolumeClaim"}
    assert claim in pvcs and claim != "prospector-store-api-data", claim
    c = spec["containers"][0]
    assert "--watchdog" in c["livenessProbe"]["exec"]["command"]
    assert (
        next(e["value"] for e in c["env"] if e["name"] == "PROSPECTOR_STORE_DIR") == "/data/store"
    )
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert c["securityContext"]["readOnlyRootFilesystem"] is True
    assert {"name": "ghcr-pull"} in spec["imagePullSecrets"]
