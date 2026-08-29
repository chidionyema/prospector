"""crew#307 follow-up, founder 2026-08-29: the raw Traefik "no available server" reached a user.
The store front and the store API are the public doors; both must answer errors with the
platform status page and carry the edge headers, and no door may name its web server."""
import pathlib

import yaml

BASE = pathlib.Path(__file__).resolve().parents[2] / "deploy/k8s/base"


def _docs(name):
    return [d for d in yaml.safe_load_all((BASE / name).read_text()) if d]


def test_both_store_routes_run_friendly_errors_and_edge_headers():
    routes = [d for d in _docs("edge.yaml") if d.get("kind") == "HTTPRoute" and "store" in d["metadata"]["name"]]
    assert {r["metadata"]["name"] for r in routes} == {"prospector-store-web", "prospector-store-api"}
    for r in routes:
        for rule in r["spec"]["rules"]:
            names = {f["extensionRef"]["name"] for f in rule.get("filters", []) if f.get("type") == "ExtensionRef"}
            assert {"friendly-errors", "edge-headers"} <= names, r["metadata"]["name"]


def test_the_middlewares_exist_in_the_store_namespace_and_are_wired():
    mws = {d["metadata"]["name"]: d for d in _docs("edge-manners.yaml") if d.get("kind") == "Middleware"}
    assert set(mws) == {"friendly-errors", "edge-headers"}
    assert all(d["metadata"]["namespace"] == "prospector" for d in mws.values())
    assert mws["friendly-errors"]["spec"]["errors"]["service"]["name"] == "status-page"
    h = mws["edge-headers"]["spec"]["headers"]
    assert h["customResponseHeaders"]["Server"] == "" and h["frameDeny"] is True and h["stsSeconds"] >= 31536000
    assert "edge-manners.yaml" in (BASE / "kustomization.yaml").read_text()
