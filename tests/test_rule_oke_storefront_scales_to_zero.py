"""Rule (crew#488 CP7, rung 2): on the OKE overlay the storefront may sit at zero replicas, and the
only way a request reaches it is through the KEDA interceptor. Three things must agree or the
buyer meets a 503: the HTTPScaledObject names the Deployment and its Service port, its hosts are
the HTTPRoute's hostnames, and the HTTPRoute's backend is the interceptor proxy in namespace keda.
The base stays a plain Deployment: k3d and the compose box have no KEDA.

Reads the overlay files, not `kubectl kustomize`: the overlay pulls the pinned Kyverno library
over the network and tests here open no sockets (crew#407)."""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OKE = ROOT / "deploy/k8s/overlays/oke"
BASE = ROOT / "deploy/k8s/base"


def _docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]


def _one(docs, kind, name):
    hits = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert len(hits) == 1, f"{kind}/{name}: {len(hits)} found"
    return hits[0]


def test_storefront_scaled_object_matches_deployment_service_and_route():
    hso = _one(_docs(OKE / "keda.yaml"), "HTTPScaledObject", "prospector-store-web")
    web = _docs(BASE / "web.yaml")
    dep = _one(web, "Deployment", "prospector-store-web")
    svc = _one(web, "Service", "prospector-store-web")
    route = _one(_docs(BASE / "edge.yaml"), "HTTPRoute", "prospector-store-web")

    ref = hso["spec"]["scaleTargetRef"]
    assert (ref["kind"], ref["name"]) == ("Deployment", dep["metadata"]["name"])
    assert ref["service"] == svc["metadata"]["name"]
    assert ref["port"] == svc["spec"]["ports"][0]["port"]
    assert sorted(hso["spec"]["hosts"]) == sorted(route["spec"]["hostnames"])
    assert hso["spec"]["replicas"]["min"] == 0
    assert hso["spec"]["replicas"]["max"] == dep["spec"]["replicas"]
    # A shop cold start is seconds; a buyer never waits on it inside a run of visits.
    assert hso["spec"]["scaledownPeriod"] >= 900


def test_oke_overlay_routes_storefront_through_the_interceptor_and_nothing_else():
    kust = yaml.safe_load((OKE / "kustomization.yaml").read_text())
    assert "keda.yaml" in kust["resources"]
    route_patches = [p for p in kust["patches"] if p.get("target", {}).get("kind") == "HTTPRoute"]
    assert [p["target"]["name"] for p in route_patches] == ["prospector-store-web"]
    ops = yaml.safe_load(route_patches[0]["patch"])
    assert ops == [{
        "op": "replace",
        "path": "/spec/rules/0/backendRefs",
        "value": [{"name": "interceptor-proxy", "namespace": "keda", "port": 8080}],
    }]


def test_base_stays_a_plain_deployment():
    for path in BASE.glob("*.yaml"):
        for d in _docs(path):
            assert d.get("kind") not in {"HTTPScaledObject", "ScaledObject"}, f"{path.name} opts into KEDA in the base"
