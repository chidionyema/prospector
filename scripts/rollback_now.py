#!/usr/bin/env python3
"""Put one service back on its previous image, from the ops console, without a terminal.

WHY THIS EXISTS. `scripts/deploy_now.py` gave every service a Deploy button. A deploy button with
no rollback button is half a control: the operator can now break production from a web page and
still needs a shell to fix it. Founder, 2026-08-20: "this is deploying to prod, needs to be
absolutely rock solid and bulletproof, rollback also, verified with automated tests and a drill
function in ops".

WHAT A ROLLBACK IS HERE. Every deployable service on this estate is a Fly app, and Fly keeps every
release with the exact image it shipped (`flyctl releases --json` carries `ImageRef`). So a
rollback is a deploy of an image that already exists - no build, no source tree, no CI - which is
why it lands in seconds and cannot be poisoned by whatever is in the working tree.

    flyctl deploy --image <the previous release's ImageRef> --config <the same fly.toml> --app <app>

`--strategy` is deliberately NOT passed. The strategy lives in each app's fly.toml (the engine's
says `immediate`, because it is one machine on one volume with a single-writer store), and a
rollback that used a different strategy from the deploy would be a second, untested code path
through production.

THE ONE THING A ROLLBACK DOES NOT DO. It does not change main. The next merge that touches a
watched path redeploys the code you just rolled away from, because deploy-engine.yml, deploy-api.yml
and deploy-web.yml all trigger on push to main. A rollback buys time to revert the commit; it is
not the revert. Every refusal, preview and success line below says so, because the button hides it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from deploy_status import DEPLOYABLES  # noqa: E402

#: How each Fly-hosted service is rolled back, and how we prove afterwards that it came back.
#:
#: `cwd` and `config` are copied from the workflow that deploys the same app, because flyctl
#: resolves --config RELATIVE TO THE WORKING DIRECTORY. deploy-api.yml carries the scar: running
#: from the repo root with `--config store_platform/deploy/fly/api.fly.toml` logs
#: `Validating --config path unset--` and silently loads no config at all.
#:
#: `probe` is the same request the deploy workflow makes after shipping, so a rollback is held to
#: the same bar as a deploy. curl rather than urllib on purpose: mumchimp.com sits behind
#: Cloudflare, which answers urllib's default user agent with 1010 (memory
#: `cloudflare-blocks-urllib-user-agent.md`).
SERVICES: dict[str, dict] = {
    "engine": {
        "app": "prospector-engine",
        "cwd": ".",
        "config": "deploy/engine/fly.toml",
        "probe": [
            {"url": "https://prospector-engine.fly.dev/login", "expect": "200",
             "means": "the console booted"},
            {"url": "https://prospector-engine.fly.dev/api/ops/read/status", "expect": "401",
             "means": "it still fails closed to an unauthenticated caller"},
        ],
        "restarts": "the scheduler, consumer, watchdog and ops console all restart together "
                    "(one machine, strategy immediate)",
    },
    "store-api": {
        "app": "prospector-store-api",
        "cwd": "store_platform",
        "config": "deploy/fly/api.fly.toml",
        "probe": [
            {"url": "https://api.mumchimp.com/catalog", "expect": "200",
             "means": "the catalogue serves"},
            {"url": "https://api.mumchimp.com/healthz/money-rail", "expect_body": '"mode":"live"',
             "means": "the money rail is still on a LIVE key, not a test one"},
        ],
        "restarts": "checkout and fulfilment restart; a buyer mid-checkout retries",
    },
    "store-web": {
        "app": "prospector-store-web",
        "cwd": "store_platform",
        "config": "deploy/fly/web.fly.toml",
        "probe": [
            {"url": "https://mumchimp.com/", "expect": "200", "means": "the shop serves"},
        ],
        "restarts": "the storefront restarts; buyers see a few seconds of the old page",
    },
    "searxng": {
        "app": "prospector-searxng",
        "cwd": ".",
        "config": "deploy/searxng/fly.toml",
        # Deliberately empty. searxng answers on the private Fly network only
        # (http://prospector-searxng.internal:8080, deploy/searxng/deploy.sh), so there is no
        # request this host can make that proves it. An empty probe list is reported as UNPROVEN,
        # never as a pass - see `_probe_all`.
        "probe": [],
        "restarts": "retrieval loses its self-hosted search for a few seconds and falls back "
                    "down the grounding chain",
    },
}

#: Services with no rollback route, and why. A DEPLOYABLE that is in neither map fails
#: tests/unit/test_rollback_is_wired_to_the_console.py.
NO_ROLLBACK: dict[str, str] = {
    "ci-runner": "the CI fleet is not a deployed image. Machines are created and destroyed with "
                 "`deploy/runners.sh`, so 'the previous release' does not exist for it",
    "engine-standby": "a git checkout, not an image. It is rolled back by pointing it at another "
                      "ref: scripts/live_checkout.py",
}


# --------------------------------------------------------------------------- #
# Pure helpers. Everything here is tested against fixtures; everything below the next
# line shells out to flyctl or curl.
# --------------------------------------------------------------------------- #
def routes() -> dict[str, dict]:
    """Every deployable, and the single way it is rolled back."""
    out: dict[str, dict] = {}
    for d in DEPLOYABLES:
        name = d["name"]
        if name in SERVICES:
            out[name] = dict(SERVICES[name], kind="image", what=d.get("what", ""))
        elif name in NO_ROLLBACK:
            out[name] = {"kind": "none", "why": NO_ROLLBACK[name], "what": d.get("what", "")}
        else:
            out[name] = {"kind": "unrouted", "what": d.get("what", "")}
    return out


def parse_releases(text: str) -> list[dict]:
    """`flyctl releases --json` into a list newest-first, or [] when it is not JSON."""
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return sorted((r for r in data if isinstance(r, dict)),
                  key=lambda r: int(r.get("Version") or 0), reverse=True)


def choose_target(releases: list[dict]) -> tuple[dict | None, str]:
    """The release to roll back TO, or None and the reason it is refused.

    Four refusals, each one an edge case that would otherwise be discovered in production:

      no releases      flyctl could not read the app, or it has never deployed
      one release      there is nothing behind the current one
      in flight        a deploy is running right now; two deploys racing one machine is how an
                       app ends up serving neither image
      already rolled   the CURRENT release ships an image an OLDER release also shipped, which
                       only happens after a rollback. Rolling back again would re-ship the exact
                       image that was rolled away from, which reads like a rollback and is a
                       roll FORWARD onto the broken build.
    """
    if not releases:
        return None, ("flyctl returned no releases for this app. Either it has never been "
                      "deployed or the token cannot read it")

    running = [r for r in releases if r.get("InProgress")]
    if running:
        return None, (f"release v{running[0].get('Version')} is still in progress. Wait for it: "
                      "two deploys racing one app can leave it serving neither image")

    current = releases[0]
    older = releases[1:]
    if not older:
        return None, (f"v{current.get('Version')} is the only release this app has. There is no "
                      "previous image to go back to")

    current_image = (current.get("ImageRef") or "").strip()
    if current_image and any((r.get("ImageRef") or "").strip() == current_image for r in older):
        prior = next(r for r in older if (r.get("ImageRef") or "").strip() == current_image)
        return None, (f"v{current.get('Version')} already ships the image from "
                      f"v{prior.get('Version')}, so the last deploy WAS a rollback. Rolling back "
                      "again would re-ship the build you rolled away from. Revert the commit on "
                      "main and deploy forward instead")

    for r in older:
        if r.get("Status") == "complete" and (r.get("ImageRef") or "").strip():
            return r, ""
    return None, ("no earlier release completed with an image reference, so there is no known-good "
                  "image to go back to")


def rollback_command(fly: str, app: str, config: str, image: str) -> list[str]:
    """The one command a rollback runs. No build context: --image ships an existing image."""
    return [fly, "deploy", "--image", image, "--config", config, "--app", app,
            "--remote-only", "--yes"]


def find_fly() -> str | None:
    """flyctl on PATH, or where it installs.

    The console runs under launchd, whose PATH omits /usr/local/bin, so a bare shutil.which finds
    nothing and the button would fail with `flyctl: not found` (memory
    `launchd-path-hides-local-bin-clis.md`).
    """
    found = shutil.which("flyctl") or shutil.which("fly")
    if found:
        return found
    for candidate in ("/usr/local/bin/flyctl", "/opt/homebrew/bin/flyctl",
                      str(Path.home() / ".fly" / "bin" / "flyctl")):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


# --------------------------------------------------------------------------- #
def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd or ROOT), timeout=timeout)


def _releases(fly: str, app: str) -> tuple[list[dict], str]:
    p = _run([fly, "releases", "-a", app, "--json"], timeout=120)
    if p.returncode != 0:
        return [], (p.stderr or p.stdout).strip().splitlines()[0] if (p.stderr or p.stdout) else \
            f"flyctl releases exited {p.returncode}"
    return parse_releases(p.stdout), ""


def _probe_one(check: dict) -> tuple[bool, str]:
    """One curl, with the deploy workflow's own retry budget."""
    url = check["url"]
    if "expect_body" in check:
        p = _run(["curl", "-s", "--max-time", "30", "--retry", "5", "--retry-delay", "5",
                  "--retry-all-errors", url], timeout=120)
        body = (p.stdout or "")[:400]
        ok = check["expect_body"] in body
        return ok, f"GET {url} -> {body.strip()[:120] or '(empty)'}"
    p = _run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "30",
              "--retry", "5", "--retry-delay", "5", "--retry-all-errors", url], timeout=120)
    code = (p.stdout or "").strip()
    return code == check["expect"], f"GET {url} -> {code} (want {check['expect']})"


def _probe_all(name: str, svc: dict) -> tuple[bool, list[str]]:
    """True only when every check passed. A service with no checks is UNPROVEN, not passing."""
    checks = svc.get("probe") or []
    if not checks:
        return False, [f"{name}: no request this host can make proves it (private network); "
                       f"UNPROVEN, check it by hand"]
    lines, ok = [], True
    for check in checks:
        passed, line = _probe_one(check)
        lines.append(("  ok   " if passed else "  FAIL ") + line + f"   [{check['means']}]")
        ok = ok and passed
    return ok, lines


def print_routes() -> int:
    print("service          rollback")
    print("-" * 78)
    bad = 0
    for name, r in routes().items():
        if r["kind"] == "image":
            how = f"flyctl deploy --image <previous> --config {r['config']}  (cwd {r['cwd']})"
        elif r["kind"] == "none":
            how = "no image rollback - " + r["why"]
        else:
            how = "NO ROUTE - nobody can put this service back"
            bad += 1
        print(f"{name:<16} {how}")
    return 2 if bad else 0


def drill(name: str | None = None) -> int:
    """Prove the rollback path works, WITHOUT rolling anything back.

    The restore drill (`scripts/restore_drill.py`) exists because a backup nobody has restored is
    not a backup. The same holds here: a rollback button nobody has ever resolved a target for is
    not a rollback. This reads releases, resolves the exact image each service would go back to,
    prints the command, and makes the live health request now - so the checks that would grade a
    rollback are known to work BEFORE one is needed. It writes nothing and deploys nothing.
    """
    fly = find_fly()
    if fly is None:
        print("DRILL FAILED: no flyctl on PATH or at /usr/local/bin/flyctl", file=sys.stderr)
        return 2

    targets = {n: r for n, r in routes().items() if r["kind"] == "image"}
    if name:
        if name not in targets:
            print(f"{name} has no image rollback. Known: {', '.join(targets)}", file=sys.stderr)
            return 2
        targets = {name: targets[name]}

    failures: list[str] = []
    warnings: list[str] = []
    for svc_name, svc in targets.items():
        print(f"\n=== {svc_name} ({svc['app']}) ===")
        releases, err = _releases(fly, svc["app"])
        if err:
            print(f"  FAIL cannot read releases: {err}")
            failures.append(f"{svc_name}: releases unreadable")
            continue
        target, why = choose_target(releases)
        current = releases[0] if releases else {}
        print(f"  live now: v{current.get('Version')} {current.get('ImageRef', '')[-24:]}")
        if target is None:
            # Three different states end up here and they are NOT the same finding.
            #
            #   already rolled   healthy. The last action was a rollback and the guard is working.
            #   only release     a gap, but nothing is broken and it clears itself the next time
            #                    the service deploys. Measured 2026-08-20: searxng is on v1, so it
            #                    has no previous image. Grading that RED every run would make this
            #                    drill permanently red, and a check that is always red is a check
            #                    nobody reads.
            #   anything else    a real failure: a deploy is stuck, or no release ever completed.
            healthy = "already ships the image from" in why
            gap = "is the only release" in why
            print(f"  {'note' if healthy else 'WARN' if gap else 'FAIL'} no rollback target: {why}")
            if gap:
                warnings.append(f"{svc_name}: {why}")
            elif not healthy:
                failures.append(f"{svc_name}: {why}")
        else:
            cmd = rollback_command(fly, svc["app"], svc["config"], target["ImageRef"])
            print(f"  would go back to v{target.get('Version')} "
                  f"({target.get('CreatedAt')}), image {target['ImageRef'][-24:]}")
            print(f"  $ (cd {svc['cwd']} && {' '.join(cmd)})")
        ok, lines = _probe_all(svc_name, svc)
        for line in lines:
            print(line)
        if not ok and svc.get("probe"):
            failures.append(f"{svc_name}: health check failing NOW, before any rollback")

    print()
    for w in warnings:
        print(f"  warning - {w}")
    if failures:
        print("DRILL FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"DRILL PASSED: {len(targets) - len(warnings)} of {len(targets)} service(s) have a "
          f"resolvable previous image and answer their health checks"
          + (f"; {len(warnings)} cannot be rolled back yet (see warnings)" if warnings else "")
          + ". Nothing was deployed.")
    return 0


def rollback(name: str, check_only: bool) -> int:
    r = routes().get(name)
    if r is None:
        print(f"unknown service {name!r}. Known: {', '.join(routes())}", file=sys.stderr)
        return 2
    if r["kind"] == "none":
        print(f"{name} has no image rollback.\n  {r['why']}", file=sys.stderr)
        return 2
    if r["kind"] == "unrouted":
        print(f"{name} has no rollback route. Add one to SERVICES in {__file__}.", file=sys.stderr)
        return 2

    fly = find_fly()
    if fly is None:
        print("REFUSED: no flyctl on PATH, and none at /usr/local/bin/flyctl, "
              "/opt/homebrew/bin/flyctl or ~/.fly/bin/flyctl.", file=sys.stderr)
        return 2

    releases, err = _releases(fly, r["app"])
    if err:
        print(f"REFUSED: cannot read releases for {r['app']}: {err}", file=sys.stderr)
        return 2

    target, why = choose_target(releases)
    if target is None:
        print(f"REFUSED: {why}.", file=sys.stderr)
        return 2

    current = releases[0]
    cmd = rollback_command(fly, r["app"], r["config"], target["ImageRef"])
    cwd = ROOT / r["cwd"]
    print(f"{name}: v{current.get('Version')} -> v{target.get('Version')} "
          f"(released {target.get('CreatedAt')})")
    print(f"  {r['restarts']}")
    print("  this does NOT change main: the next merge touching this service's paths ships the "
          "current code again. Revert the commit as well.")
    print(f"$ (cd {r['cwd']} && {' '.join(cmd)})")
    if check_only:
        print("--check: nothing was rolled back. A target resolves and flyctl is present.")
        return 0

    p = subprocess.run(cmd, cwd=str(cwd), timeout=900)
    if p.returncode != 0:
        print(f"flyctl exited {p.returncode}. The app may be part-way through a deploy; "
              f"run --check to see what it is serving now.", file=sys.stderr)
        return p.returncode

    ok, lines = _probe_all(name, r)
    for line in lines:
        print(line)
    if not ok:
        # The rollback ran and the service still does not answer. Saying "rolled back" here would
        # be the worst possible lie, because the operator stops looking.
        print("ROLLED BACK, BUT NOT HEALTHY: the previous image is deployed and the health check "
              "above did not pass. This needs a human.", file=sys.stderr)
        return 1
    print(f"rolled {name} back to v{target.get('Version')} and it answers its health checks.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("service", nargs="?", help="what to roll back; omit to list every route")
    ap.add_argument("--list", action="store_true", help="show every service and its rollback")
    ap.add_argument("--drill", action="store_true",
                    help="prove every rollback resolves and every health check works; deploy nothing")
    ap.add_argument("--check", action="store_true",
                    help="run the preflight and print the command, roll nothing back")
    args = ap.parse_args(argv)

    if args.drill:
        return drill(args.service)
    if args.list or not args.service:
        return print_routes()
    return rollback(args.service, args.check)


if __name__ == "__main__":
    raise SystemExit(main())
