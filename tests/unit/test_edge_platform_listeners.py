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
PLATFORM_LISTENERS = {"https-catalogue", "https-auth", "https-llm", "https-langfuse", "https-hc", "https-mcp", "https-otto", "https-signoz", "https-superset", "https-cyrus"}

# A listener whose hostname is brand new has no DNS record until external-dns publishes its route,
# and cert-manager orders ONE certificate per Secret: on 2026-08-31 two such names failed the order
# for all thirteen listeners sharing prospector-edge-tls and otto.<zone> served Traefik's
# placeholder. A new name therefore gets its own Secret, so a failed order costs only that name.
# The entry leaves this map when the certificate has issued and the name resolves.
ISOLATED_CERTS = {"https-cyrus": "prospector-edge-cyrus-tls"}


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
        assert l["tls"]["certificateRefs"][0]["name"] == ISOLATED_CERTS.get(name, "prospector-edge-tls"), name
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


def test_incident_decision_0018_superset_listener_names_the_dashboard_hostname() -> None:
    """idp decision 0018 (2026-09-02): Superset replaces Metabase because its free tier takes the
    gateway's word (header trust), so the dashboard keeps the one login. Main went red when the
    metabase listener landed with no route and no row here; the rename to https-superset and this
    row are that fix, landing in the same wave as idp's HTTPRoute."""
    assert _listeners()["https-superset"]["hostname"] == "superset.${ESTATE_ZONE}"


def test_incident_otto_outage_2026_09_01_no_listener_without_a_route() -> None:
    """Otto outage 2026-08-31T23:18Z to 2026-09-01: the alertmanager and prometheus listeners
    (crew#684) landed before their idp HTTPRoutes merged, so external-dns published no record for
    either name; cert-manager orders one certificate for every listener sharing prospector-edge-tls,
    the two unreachable names failed the order, and otto.<zone> kept the Traefik placeholder
    certificate that Telegram refuses. A listener lands in the same wave as its route, never before."""
    listeners = _listeners()
    assert "https-alertmanager" not in listeners
    assert "https-prometheus" not in listeners
    assert not {n for n, l in listeners.items() if "${ESTATE_ZONE}" in str(l.get("hostname"))} - PLATFORM_LISTENERS


def test_incident_crew736_otto_listener_names_the_webhook_hostname() -> None:
    """crew#736: otto.<zone> attaches from the idp `hermes-agent` namespace; Telegram's webhook
    calls this hostname, so a listener missing here leaves the idp HTTPRoute with no parent."""
    assert _listeners()["https-otto"]["hostname"] == "otto.${ESTATE_ZONE}"
def test_an_isolated_certificate_is_named_by_exactly_one_listener() -> None:
    """What makes ISOLATED_CERTS isolation rather than a second shared certificate: cert-manager
    groups listeners by the Secret in their certificateRefs, so a Secret named by two listeners is
    one order for two names again, and a name HTTP-01 cannot reach takes the other one down with
    it -- the 2026-08-31 shape, in miniature. One Secret, one listener, one name, one order."""
    listeners = _listeners()
    for name, secret in ISOLATED_CERTS.items():
        assert name in listeners, name
        users = [n for n, l in listeners.items() if (l.get("tls") or {}).get("certificateRefs", [{}])[0].get("name") == secret]
        assert users == [name], (secret, users)


def test_incident_crew834_cyrus_listener_names_the_webhook_hostname() -> None:
    """crew#834: cyrus.<zone> attaches from the idp `cyrus` namespace, whose HTTPRoute
    (idp platform/cyrus/httproute.yaml) names this listener by sectionName and whose namespace
    carries idp.estate/edge-attach. Linear and GitHub POST their deliveries here; without the
    listener the route attached to nothing and no webhook could arrive."""
    assert _listeners()["https-cyrus"]["hostname"] == "cyrus.${ESTATE_ZONE}"
