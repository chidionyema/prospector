"""Every hostname the edge serves is a link in the product's catalogue entity.

RUNG 2 (property), per the test ladder in `~/AGENTS.md`: for every HTTPRoute hostname in
deploy/k8s/base/edge.yaml there is a Component in catalog-info.yaml whose links carry
https://<hostname>. The incident is crew#282 (2026-08-26): the estate catalogue named the store
and the API but neither carried a URL, so the founder's pinned URL card listed two links out of
four. The catalogue is what the card is generated from, so the file that names the hostnames
is the file the card reads.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _edge_hostnames() -> set[str]:
    hosts: set[str] = set()
    for doc in yaml.safe_load_all((ROOT / "deploy/k8s/base/edge.yaml").read_text()):
        if doc and doc.get("kind") == "HTTPRoute":
            hosts.update(doc["spec"].get("hostnames") or [])
    return hosts


def _catalog_urls() -> set[str]:
    urls: set[str] = set()
    for doc in yaml.safe_load_all((ROOT / "catalog-info.yaml").read_text()):
        if doc and doc.get("kind") == "Component":
            urls.update(link["url"] for link in doc["metadata"].get("links") or [])
    return urls


def test_every_edge_hostname_is_a_catalogue_link() -> None:
    hosts = _edge_hostnames()
    assert hosts, "edge.yaml has no HTTPRoute hostnames; the property would grade nothing"
    missing = {h for h in hosts if f"https://{h}" not in _catalog_urls()}
    assert not missing, f"edge serves {sorted(missing)} but catalog-info.yaml has no link for them"


def test_every_catalogue_link_is_served_by_the_edge() -> None:
    hosts = _edge_hostnames()
    dead = {u for u in _catalog_urls() if u.removeprefix("https://") not in hosts}
    assert not dead, f"catalog-info.yaml links {sorted(dead)} that no HTTPRoute serves"
