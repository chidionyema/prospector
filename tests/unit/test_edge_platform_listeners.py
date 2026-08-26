"""Every platform hostname on the edge is a listener other namespaces can attach to.

RUNG 2 (property), per the test ladder in `~/AGENTS.md`: for every Gateway listener whose
hostname is under `${ESTATE_ZONE}` (a platform row: catalogue, auth, llm), the listener
terminates TLS with the shared edge cert and allows routes from any namespace labelled
`idp.estate/edge-attach: "true"`. The rows live in idp, not here, so a listener that only
allowed routes from `prospector` would accept the hostname and serve nothing.

The incident is crew#313 (2026-08-26): the model router ran only on the founder's Mac, so the
platform's `llm` row needs `https-llm` here before idp's HTTPRoute has a parent.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_LISTENERS = {"https-catalogue", "https-auth", "https-llm"}


def _listeners() -> dict[str, dict]:
    for doc in yaml.safe_load_all((ROOT / "deploy/k8s/base/edge.yaml").read_text()):
        if doc and doc.get("kind") == "Gateway" and doc["metadata"]["name"] == "prospector-edge":
            return {l["name"]: l for l in doc["spec"]["listeners"]}
    raise AssertionError("Gateway prospector-edge not found in edge.yaml")


def test_every_estate_zone_listener_accepts_platform_routes() -> None:
    zone = {n: l for n, l in _listeners().items() if "${ESTATE_ZONE}" in str(l.get("hostname"))}
    assert set(zone) == PLATFORM_LISTENERS, set(zone) ^ PLATFORM_LISTENERS
    for name, l in zone.items():
        assert l["port"] == 8443 and l["protocol"] == "HTTPS", name
        assert l["tls"]["certificateRefs"][0]["name"] == "prospector-edge-tls", name
        ns = l["allowedRoutes"]["namespaces"]
        assert ns["from"] == "Selector", name
        assert ns["selector"]["matchLabels"] == {"idp.estate/edge-attach": "true"}, name


def test_llm_listener_names_the_router_hostname() -> None:
    assert _listeners()["https-llm"]["hostname"] == "llm.${ESTATE_ZONE}"
