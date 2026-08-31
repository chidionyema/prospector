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
PLATFORM_LISTENERS = {"https-catalogue", "https-auth", "https-llm", "https-langfuse", "https-hc", "https-mcp", "https-otto", "https-signoz", "https-alertmanager", "https-prometheus"}


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


def test_incident_crew325_langfuse_listener_names_the_trace_store_hostname() -> None:
    """crew#325 showcase: langfuse.<zone> attaches from the idp `observability` namespace like the
    catalogue and the router do; a listener missing here leaves the idp HTTPRoute with no parent."""
    assert _listeners()["https-langfuse"]["hostname"] == "langfuse.${ESTATE_ZONE}"


def test_incident_crew177_hc_listener_names_the_job_monitor_hostname() -> None:
    """crew#177: hc.<zone> attaches from the idp `healthchecks` namespace; without this listener the
    idp HTTPRoutes (screen behind the login, /ping/ for the jobs) have no parent."""
    assert _listeners()["https-hc"]["hostname"] == "hc.${ESTATE_ZONE}"


def test_incident_crew458_mcp_listener_names_the_mcp_gateway_hostname() -> None:
    """crew#458: mcp.<zone> attaches from the idp `mcp` namespace; the MCP servers left the colima VM
    on the founder Mac for the cluster and need a parent here before idp's HTTPRoute has one."""
    assert _listeners()["https-mcp"]["hostname"] == "mcp.${ESTATE_ZONE}"


def test_incident_crew495_signoz_listener_names_the_telemetry_backend_hostname() -> None:
    """crew#495 CP8: SigNoz had no listener, so no person and no Terraform run could reach it."""
    assert _listeners()["https-signoz"]["hostname"] == "signoz.${ESTATE_ZONE}"


def test_incident_crew684_alertmanager_and_prometheus_listeners_name_the_monitoring_hostnames() -> None:
    """crew#684 (founder 2026-08-30, "i need all cluster monitoring tools now"): the alert console and
    the metrics store ran 43 hours with no hostname; idp's HTTPRoutes in `monitoring` need a parent."""
    assert _listeners()["https-alertmanager"]["hostname"] == "alertmanager.${ESTATE_ZONE}"
    assert _listeners()["https-prometheus"]["hostname"] == "prometheus.${ESTATE_ZONE}"


def test_incident_crew736_otto_listener_names_the_webhook_hostname() -> None:
    """crew#736: otto.<zone> attaches from the idp `hermes-agent` namespace; Telegram's webhook
    calls this hostname, so a listener missing here leaves the idp HTTPRoute with no parent."""
    assert _listeners()["https-otto"]["hostname"] == "otto.${ESTATE_ZONE}"
