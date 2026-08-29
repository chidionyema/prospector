"""The Kubernetes admission gate must refuse a build it cannot grade.

RUNG 4 (incident), per the test ladder in `~/AGENTS.md`. The incident is 2026-08-24: the Kyverno
CLI, handed a file with no gradable resources in it, printed `Applying 0 policy rule(s)` and then
`pass: 0, fail: 0, error: 0` and exited 0. A gate wired to that reports a green check while
grading nothing, and a green check nobody looks behind is worse than no check.

This grades `deploy/k8s/split_workloads.py`, which is the code the workflow actually runs. It was
inline python inside `.github/workflows/k8s-manifests.yml` until a test could not reach it without
re-implementing it — and a test that re-implements its subject agrees with the subject forever,
including on the day the subject changes.

`test_the_workflow_calls_the_splitter` is the one static check here, and it is deliberately narrow:
it asserts the workflow invokes this file, which is the single fact a test of the module cannot
establish about itself. It does not grep the workflow for behaviour.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPLITTER = ROOT / "deploy" / "k8s" / "split_workloads.py"
WORKFLOW = ROOT / ".github" / "workflows" / "k8s-manifests.yml"


def _load():
    """deploy/k8s is not a package, so the module is loaded by path, the way the workflow runs it."""
    spec = importlib.util.spec_from_file_location("split_workloads", SPLITTER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["split_workloads"] = module
    spec.loader.exec_module(module)
    return module


split_workloads = _load()


POLICY = """apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-run-as-nonroot
"""
NAMESPACE = "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: prospector\n"
PVC = "apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: prospector-data\n"
SERVICE = "apiVersion: v1\nkind: Service\nmetadata:\n  name: prospector-engine\n"
DEPLOYMENT = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: prospector-engine\n"
PDB = "apiVersion: policy/v1\nkind: PodDisruptionBudget\nmetadata:\n  name: prospector-store-web\n"
GATEWAY = ("apiVersion: gateway.networking.k8s.io/v1\nkind: Gateway\n"
           "metadata:\n  name: prospector-edge\n")
ROUTE = ("apiVersion: gateway.networking.k8s.io/v1\nkind: HTTPRoute\n"
         "metadata:\n  name: prospector-store-web\n")
ISSUER = ("apiVersion: cert-manager.io/v1\nkind: ClusterIssuer\n"
          "metadata:\n  name: prospector-letsencrypt\n")

# A four-document build. It was what the overlays produced on the day this gate was written, and it
# is now BELOW the floor — which is the point of keeping it: it is the shape a build takes after
# three of the four manifests are silently dropped from base/kustomization.yaml.
SMALL = "\n---\n".join([POLICY, NAMESPACE, PVC, DEPLOYMENT, SERVICE])

# What both overlays actually build, measured 2026-08-24: 15 non-policy documents. The kinds are in
# the order kustomize emits them.
FULL = "\n---\n".join([
    POLICY,
    NAMESPACE,
    SERVICE, SERVICE, SERVICE,
    PVC, PVC,
    DEPLOYMENT, DEPLOYMENT, DEPLOYMENT,
    PDB,
    ISSUER, GATEWAY, ROUTE, ROUTE, ROUTE,
])


def test_a_real_build_is_split_into_workloads_and_graders():
    keep, kinds = split_workloads.split(FULL)
    assert kinds == [
        "Namespace",
        "Service", "Service", "Service",
        "PersistentVolumeClaim", "PersistentVolumeClaim",
        "Deployment", "Deployment", "Deployment",
        "PodDisruptionBudget",
        "ClusterIssuer", "Gateway", "HTTPRoute", "HTTPRoute", "HTTPRoute",
    ]
    assert not any("ClusterPolicy" in d for d in keep), "the policies are the graders, not the graded"
    assert split_workloads.check(keep, kinds, "production") is None


def test_the_floor_rises_with_the_estate():
    """The failure a fixed floor cannot catch, and the reason this test exists at all.

    The floor was 4 when base/ held one workload. Three more landed on 2026-08-24, and a floor left
    at 4 would admit a build that had silently lost the store API, the storefront and the edge — it
    still has a Namespace, a PVC, a Deployment and a Service, so both checks pass. So the yesterday
    build must now be REFUSED, and it is that refusal, not the number, that is asserted here."""
    keep, kinds = split_workloads.split(SMALL)
    reason = split_workloads.check(keep, kinds, "production")
    assert reason and "builds only 4 non-policy document(s)" in reason


def test_a_policy_only_build_is_refused():
    """The exact shape of the vacuous pass: 26 policies and nothing to apply them to."""
    keep, kinds = split_workloads.split("\n---\n".join([POLICY, POLICY]))
    reason = split_workloads.check(keep, kinds, "production")
    assert reason and "builds no Deployment" in reason


def test_a_build_that_lost_its_workload_is_refused():
    """The Namespace alone still looks like output. It is the failure mid-regression looks like."""
    keep, kinds = split_workloads.split("\n---\n".join([POLICY, NAMESPACE]))
    reason = split_workloads.check(keep, kinds, "staging")
    assert reason and "builds no Deployment" in reason


def test_a_build_missing_one_document_is_refused():
    """A Deployment is present, so the kind check passes; the count is what catches this one."""
    keep, kinds = split_workloads.split("\n---\n".join([POLICY, NAMESPACE, DEPLOYMENT]))
    reason = split_workloads.check(keep, kinds, "production")
    assert reason and "builds only 2 non-policy document(s)" in reason


def test_an_empty_build_is_refused():
    keep, kinds = split_workloads.split("")
    assert split_workloads.check(keep, kinds, "production") is not None


@pytest.mark.parametrize("label", ["staging", "production"])
def test_the_reason_names_the_environment(label):
    """Two environments run through the same code. A reason that does not say which is a bug report
    the reader has to reproduce before they can act on it."""
    keep, kinds = split_workloads.split(POLICY)
    reason = split_workloads.check(keep, kinds, label)
    assert reason and reason.startswith(label)


def test_main_writes_nothing_when_it_refuses(tmp_path):
    """A partial output file is what the next step would grade, so refusing must leave no file."""
    build = tmp_path / "build.yaml"
    build.write_text(POLICY)
    out = tmp_path / "workloads.yaml"
    rc = split_workloads.main(["split_workloads.py", str(build), str(out), "production"])
    assert rc == 1
    assert not out.exists()


def test_main_writes_the_workloads_when_it_admits(tmp_path):
    build = tmp_path / "build.yaml"
    build.write_text(FULL)
    out = tmp_path / "workloads.yaml"
    rc = split_workloads.main(["split_workloads.py", str(build), str(out), "production"])
    assert rc == 0
    written = out.read_text()
    assert "kind: Deployment" in written
    assert "kind: ClusterPolicy" not in written


def test_the_real_base_kustomization_still_declares_the_engine():
    """The regression this whole gate exists to catch, asserted against the checked-in file rather
    than a fixture: engine.yaml silently dropped from base/ is how the overlays go back to building
    a Namespace and nothing else."""
    base = (ROOT / "deploy" / "k8s" / "base" / "kustomization.yaml").read_text()
    assert "engine.yaml" in base
    assert (ROOT / "deploy" / "k8s" / "base" / "engine.yaml").exists()


def test_the_workflow_calls_the_splitter():
    """The one fact the module cannot check about itself: that the gate runs it."""
    assert "deploy/k8s/split_workloads.py" in WORKFLOW.read_text()


# The floor was a single number, `MINIMUM_DOCUMENTS = 15`, and on 2026-08-24 deploy/k8s/estate was
# added: 4 documents, refused by a floor that describes Prospector's release. The three tests below
# grade the per-directory floor both ways in one run — it must admit a small directory that is
# complete, and still refuse a large one that has lost documents.
def test_the_same_four_documents_are_admitted_for_estate_and_refused_for_production():
    """One build, two labels, two answers. A floor that is not per-directory cannot do this, and a
    floor that is per-directory but wrong in the permissive direction fails the second half."""
    keep, kinds = split_workloads.split(SMALL)
    assert split_workloads.check(keep, kinds, "estate") is None
    reason = split_workloads.check(keep, kinds, "production")
    assert reason and "builds only 4 non-policy document(s)" in reason


def test_estate_losing_a_document_is_still_refused():
    """The small floor must still be a floor. Three documents is what estate looks like after the
    PVC is dropped from its kustomization."""
    keep, kinds = split_workloads.split("\n---\n".join([POLICY, NAMESPACE, DEPLOYMENT, SERVICE]))
    reason = split_workloads.check(keep, kinds, "estate")
    assert reason and "builds only 3 non-policy document(s)" in reason


def test_a_directory_with_no_declared_floor_is_refused():
    """The silent-miss case. A directory added to deploy/k8s and enumerated by the workflow, but
    never given a floor, must stop the gate rather than be graded against a default."""
    keep, kinds = split_workloads.split(FULL)
    reason = split_workloads.check(keep, kinds, "sandbox")
    assert reason and "has no document floor" in reason
    assert "estate" in reason and "production" in reason, "the reason lists what is known"


def test_every_manifest_directory_the_workflow_grades_has_a_floor():
    """The two halves are edited in different files, so they drift. This is the join: whatever the
    workflow enumerates on disk must have a row in MINIMUM_DOCUMENTS."""
    graded = sorted(
        p.parent.name
        for p in (ROOT / "deploy" / "k8s").glob("*/**/kustomization.yaml")
        if p.parent.name not in ("policies", "base")
    )
    assert graded, "the enumeration found no manifest directories"
    missing = [d for d in graded if d not in split_workloads.MINIMUM_DOCUMENTS]
    assert not missing, f"no document floor declared for: {missing}"
