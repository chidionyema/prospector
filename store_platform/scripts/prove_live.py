#!/usr/bin/env python3
"""Measure PRODUCTION. The half of the estate that was missing.

Every gate in this repo fires BEFORE a deploy: `predeploy_guard.sh` refuses a dirty tree,
`deploy_web.sh` validates the five NEXT_PUBLIC_* build args and proves the Stripe key
authenticates. Nothing fired after. `deploy_web.sh` ended in `exec flyctl deploy`, and `exec`
replaces the process image, so by construction no post-deploy check could ever run there.

The consequence is the thing this programme kept paying for: a fix is proven on localhost,
shipped, and never measured again. Drift, a regression from a concurrent session, or a data-side
change on the shelf is invisible until a human opens the site on a phone. Seven probes exist in
this repo (`site_spec_probe.py`, `store_audit.py`, `prove_storefront.py`, `prove_web.sh` and
friends); every one of them reads local files or a locally-booted dev server, and none is wired to
an automatic trigger. This one reads what buyers actually get.

It asserts three families, chosen because each has ALREADY shipped to production undetected:

  LADDER    `config.yaml listing.pricing.rungs` declares the seven prices the catalogue may hold,
            and the comment above it records the decision that every rung ends in 99p. On
            2026-08-14 nine of fifty-nine live packs were serving flat-hundred prices (£49.00,
            £79.00, £29.00, £199.00) that appear nowhere on that ladder. Nothing compared the two.

  TAGS      Three live packs carried no `market`, which drops them into the storefront's
            `grouped.others` bucket and gives them the wrong jurisdiction badge -- the same defect
            family the founder reported as "UK rows tagged US rules".

  COPY      Two one-liners were cut mid-word ("...before…", "...tuned to…"), which is a trimming
            bug that reads to a buyer as an unfinished product.

It REPORTS the ladder breach; it does not repair it. A live price is half of a money rail: the
catalogue row and the provider Price object are minted together by one `PriceDecision`
(`bridge.py`), and rewriting one of them alone charges a buyer an amount the fulfilment fence will
then reject. Repricing is a decision with a before/after table, not a side effect of a probe.

Usage:
    python3 store_platform/scripts/prove_live.py [--api URL] [--site URL] [--no-geometry]

Exit codes: 0 clean, 1 defects found, 2 the probe could not measure (which is NOT clean).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB_DIR = REPO / "store_platform" / "src" / "Store.Web"
# The geometry probe lives inside Store.Web, not beside this file: ESM resolves a bare import
# from the importing file's own directory, so a script in store_platform/scripts/ cannot find
# @playwright/test no matter what cwd it is given.
GEOMETRY = WEB_DIR / "scripts" / "prove_live_geometry.mjs"

DEFAULT_API = os.environ.get("STORE_API_URL") or f"https://api.{os.environ['ESTATE_ZONE']}"
DEFAULT_SITE = os.environ.get("SITE_URL") or f"https://{os.environ['ESTATE_ZONE']}"

GRN, RED, YEL, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def ok(msg: str) -> None:
    print(f"{GRN}PASS  {msg}{OFF}")


def bad(msg: str) -> None:
    print(f"{RED}FAIL  {msg}{OFF}")


def warn(msg: str) -> None:
    print(f"{YEL}WARN  {msg}{OFF}")


def declared_rungs() -> list[int] | None:
    """The ladder, from config, never hardcoded here.

    A copy of the rung list in this file would pass on the day someone edits `config.yaml`, which
    is exactly the drift the probe exists to catch.
    """
    try:
        import yaml  # noqa: PLC0415 -- optional at import time; the probe degrades, not dies

        cfg = yaml.safe_load((REPO / "config.yaml").read_text())
        rungs = cfg["listing"]["pricing"]["rungs"]
        return [int(r) for r in rungs]
    except Exception as exc:  # pragma: no cover -- reported, not swallowed
        warn(f"could not read listing.pricing.rungs from config.yaml ({exc}); ladder check skipped")
        return None


def fetch_catalog(api: str) -> list[dict] | None:
    url = f"{api.rstrip('/')}/catalog"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            body = resp.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        bad(f"{url} unreachable: {exc}")
        return None
    try:
        rows = json.loads(body)
    except json.JSONDecodeError as exc:
        bad(f"{url} returned {len(body)} bytes that are not JSON: {exc}")
        return None
    if not isinstance(rows, list):
        bad(f"{url} returned {type(rows).__name__}, expected a top-level array")
        return None
    return rows


# A one-liner that ends on an ellipsis, or runs long and stops without any terminal punctuation,
# is a trimmer's output rather than a writer's. Deliberately conservative: a short line with no
# full stop is a legitimate style choice, so only lines past 60 characters are judged.
_TERMINAL = re.compile(r"[.!?\"')\]]$")


def looks_truncated(text: str) -> bool:
    s = (text or "").rstrip()
    if not s:
        return False
    if s.endswith(("…", "...")):
        return True
    return len(s) > 60 and not _TERMINAL.search(s)


def check_catalog(rows: list[dict]) -> int:
    """Returns the number of failing families (not the number of bad rows)."""
    failures = 0
    n = len(rows)

    if n == 0:
        bad("catalogue is EMPTY — the shelf is serving nothing to buy")
        return 1
    print(f"      catalogue population: {n} live packs")

    rungs = declared_rungs()
    if rungs is not None:
        off = [r for r in rows if r.get("pricePence") not in rungs]
        if off:
            counts: dict[str, int] = {}
            for r in off:
                counts[str(r.get("price"))] = counts.get(str(r.get("price")), 0) + 1
            bad(
                f"{len(off)}/{n} packs priced OFF the declared ladder {rungs} — "
                + ", ".join(f"{p}x{c}" for p, c in sorted(counts.items()))
            )
            print("        a catalogue price and its Stripe Price object are minted together by")
            print("        one PriceDecision; repair these through bridge.py, never in the DB.")
            failures += 1
        else:
            ok(f"all {n} prices sit on the declared ladder")

    untagged = [r for r in rows if not r.get("market")]
    if untagged:
        bad(
            f"{len(untagged)}/{n} packs carry no market tag — they fall into grouped.others "
            f"and render the wrong jurisdiction badge: {', '.join(r.get('id', '?')[:8] for r in untagged)}"
        )
        failures += 1
    else:
        ok(f"all {n} packs carry a market tag")

    trunc = [r for r in rows if looks_truncated(r.get("oneLine") or "")]
    if trunc:
        bad(f"{len(trunc)}/{n} one-liners look cut mid-word")
        for r in trunc[:5]:
            print(f"        {r.get('id', '?')[:8]}  …{(r.get('oneLine') or '')[-60:]!r}")
        failures += 1
    else:
        ok(f"all {n} one-liners end cleanly")

    unsourced = [r for r in rows if not r.get("sourceCount")]
    if unsourced:
        bad(
            f"{len(unsourced)}/{n} packs claim no sources — the source count IS the product's "
            "claim to be grounded"
        )
        failures += 1
    else:
        ok(f"all {n} packs carry a source count")

    return failures


def check_geometry(site: str) -> int:
    if not GEOMETRY.exists():
        warn(f"{GEOMETRY.name} missing; geometry check skipped")
        return 0
    if not (WEB_DIR / "node_modules" / "@playwright").exists():
        warn("@playwright/test not installed in Store.Web; geometry check skipped")
        return 0
    try:
        # cwd is Store.Web so the script resolves @playwright from the app's own install rather
        # than needing a global one. Bounded: a browser harness fails by running forever, not by
        # exiting non-zero.
        proc = subprocess.run(
            ["node", str(GEOMETRY), site],
            cwd=str(WEB_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        bad("geometry probe exceeded 300s — treat as UNMEASURED, not clean")
        return 1
    out = (proc.stdout or "").splitlines()
    for line in out:
        if line.startswith("PASS"):
            print(f"{GRN}{line}{OFF}")
        elif line.startswith("FAIL"):
            print(f"{RED}{line}{OFF}")
        else:
            print(line)
    # Any non-zero exit gets its stderr surfaced, including 1. An uncaught throw in Node exits 1,
    # which is the SAME code this script uses for "defects found" -- so gating the diagnostic on
    # `not in (0, 1)` printed a silent empty section for a probe that had crashed on its first
    # line, and the crash counted as a defect nobody could read.
    if proc.returncode != 0:
        if not out:
            bad("geometry probe produced no output — it did not measure, it crashed")
        for line in (proc.stderr or "").splitlines()[-8:]:
            print(f"        {line}")
    return 1 if proc.returncode else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--site", default=DEFAULT_SITE)
    ap.add_argument("--no-geometry", action="store_true", help="skip the browser render")
    args = ap.parse_args()

    print(f"==> Measuring live storefront  site={args.site}  api={args.api}")
    failures = 0

    print("\n--- catalogue contract ---")
    rows = fetch_catalog(args.api)
    if rows is None:
        # An outage is the END of the measurement, not a datum in it. Reporting "clean" here
        # would be the exact failure this probe exists to prevent.
        print(f"\n{RED}==> UNMEASURED: the catalogue could not be read{OFF}")
        return 2
    failures += check_catalog(rows)

    if not args.no_geometry:
        print("\n--- rendered geometry ---")
        failures += check_geometry(args.site)

    print()
    if failures:
        print(f"{RED}==> LIVE STOREFRONT HAS {failures} FAILING CHECK(S){OFF}")
        return 1
    print(f"{GRN}==> LIVE STOREFRONT CLEAN{OFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
