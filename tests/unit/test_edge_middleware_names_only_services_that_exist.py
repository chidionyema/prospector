"""P1 2026-08-29 03:32Z: prospector#774 merged before idp#695 existed. Its friendly-errors
Middleware named service status-page in ns edge; Traefik drops every route that names a broken
middleware, so mumchimp.com and api.mumchimp.com answered a bare 404 for an hour (crew#307).
This test refuses a Middleware that names a service outside this repo unless the platform repo's
main already ships it -- the order lives in the test, not in someone's memory."""
import pathlib
import subprocess
import urllib.request

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLATFORM_REPO = "chidionyema/idp"
SHIPS = {("edge", "status-page"): "platform/edge/status-page.yaml"}
# A platform door that carries the same edge-headers Middleware idp#695 ships: HSTS on it proves
# the running Traefik accepts cross-namespace middlewares, not just that the file is on main.
PLATFORM_DOOR = "https://catalogue.mumchimp.com/"


def _platform_main_has(path):
    r = subprocess.run(["gh", "api", f"repos/{PLATFORM_REPO}/contents/{path}?ref=main", "-q", ".name"],
                       capture_output=True, text=True, check=False)
    return r.returncode == 0 and r.stdout.strip() == pathlib.Path(path).name


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # the door answers 302 to the login; following it would read the identity provider's HSTS
    # and call the edge live when it is not (caught 2026-08-29 while writing this)
    def redirect_request(self, *a, **k):
        return None


def _platform_edge_is_live():
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        r = opener.open(urllib.request.Request(PLATFORM_DOOR, method="HEAD"), timeout=10)
        return bool(r.headers.get("Strict-Transport-Security"))
    except urllib.error.HTTPError as e:
        return bool(e.headers.get("Strict-Transport-Security"))
    except Exception:
        return False


def test_every_cross_namespace_service_a_middleware_names_is_on_platform_main():
    docs = [d for d in yaml.safe_load_all((ROOT / "deploy/k8s/base/edge-manners.yaml").read_text()) if d]
    seen = 0
    for d in docs:
        if d.get("kind") != "Middleware":
            continue
        svc = ((d.get("spec") or {}).get("errors") or {}).get("service") or {}
        if not svc:
            continue
        key = (svc.get("namespace"), svc.get("name"))
        assert key in SHIPS, f"unknown cross-namespace service {key}: add it to SHIPS with its platform file"
        assert _platform_main_has(SHIPS[key]), f"{key} is not on {PLATFORM_REPO} main yet -- merge the platform PR first"
        seen += 1
    assert seen >= 1
    assert _platform_edge_is_live(), f"{PLATFORM_DOOR} sends no HSTS yet: the platform edge (idp#695) is not live, merging now drops the store routes"
