#!/usr/bin/env python3
"""Probe every live pack for the retired PASS banner — the claim the renderer stopped making.

`prospector/dossier.py:_pass_gloss` was rewritten on 2026-08-14 so the PASS banner counts the
verdicts instead of asserting them ("Two of eight checks came back against this idea"). That fix
reaches packs generated AFTER it. It does not reach the shelf: `tools/backfill_bundle_html.py`
copies every `.md` deliverable byte-identical by design (see its docstring, "The .md deliverables
of record are copied byte-identical with exactly ONE exception"), so `QA_Report.md` inside a pack
that is on sale today still carries the retired sentence.

This script is the measurement, not the fix. It is the corpus census
`docs/PACK_QUALITY_PROGRAM.md` asks for ("A defect on 1 of 62 is a repair; a defect on 62 of 62
is a generator change") applied to the one defect that is a factual falsehood in the product.

    python3 scripts/pack_banner_probe.py             # counts + exit 1 while any pack is stale
    python3 scripts/pack_banner_probe.py --verbose   # one row per offending pack

Two sources, and the difference matters (same distinction `tools/preview_packs.py` draws):
`--from disk` reads `publish/bundles/<id>/*.zip`, what was BUILT on this machine. The bytes a
buyer actually receives come from R2. Disk is the floor: a defect present on disk is a defect
worth fixing, but only an R2 read can prove what is SERVED.

Exit codes:  0 = no live pack claims to have cleared checks it did not.  1 = at least one does.

Deliberately dependency-free and read-only.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector.config import store_root  # noqa: E402

#: The exact sentence `_DECISION_GLOSS[Decision.PASS]` used to emit unconditionally on every PASS.
RETIRED_BANNER = "cleared every check we hold it to"

#: How a check that went the other way is rendered — `dossier.py` writes the glyph into the
#: per-check heading, and the gloss underneath. Either one alone is enough to contradict the
#: banner above it.
CONTRADICTION_MARKERS = ("❌", "the sources contradict this")

QA_MEMBER = "QA_Report.md"


def _bundle_zip(pack_id: str) -> Path | None:
    d = REPO / "publish" / "bundles" / pack_id
    if not d.is_dir():
        return None
    zips = sorted(d.glob("*.zip"))
    return zips[0] if zips else None


def _qa_text(zip_path: Path) -> str | None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [n for n in zf.namelist() if n.endswith(QA_MEMBER)]
            if not names:
                return None
            return zf.read(names[0]).decode("utf-8", "replace")
    except (zipfile.BadZipFile, OSError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="one row per offending pack")
    args = ap.parse_args()

    live = sorted(p.stem for p in (store_root() / "listings").glob("*.json"))
    if not live:
        print("no live listings under store/listings — nothing to probe", file=sys.stderr)
        return 1

    missing: list[str] = []
    unreadable: list[str] = []
    stale: list[str] = []
    contradicted: list[str] = []

    for pack_id in live:
        zp = _bundle_zip(pack_id)
        if zp is None:
            missing.append(pack_id)
            continue
        text = _qa_text(zp)
        if text is None:
            unreadable.append(pack_id)
            continue
        if RETIRED_BANNER not in text:
            continue
        stale.append(pack_id)
        if any(m in text for m in CONTRADICTION_MARKERS):
            contradicted.append(pack_id)

    print("── PACK BANNER PROBE ── source: publish/bundles (BUILT, not necessarily SERVED)")
    print(f"live listings                         : {len(live)}")
    print(f"  no bundle on this disk              : {len(missing)}")
    print(f"  bundle unreadable                   : {len(unreadable)}")
    print(f"  QA_Report carries retired banner    : {len(stale)}")
    print(f"  …and contradicts it in the same doc : {len(contradicted)}")

    if args.verbose:
        for pack_id in contradicted:
            print(f"  CONTRADICTED  {pack_id}")
        for pack_id in sorted(set(stale) - set(contradicted)):
            print(f"  STALE         {pack_id}")

    if stale or unreadable:
        print("\nFAIL — a pack on sale states it cleared checks that its own report says it did "
              "not.\nFix: re-render QA_Report.md from the stored record "
              "(store/dossiers/<id>.pass.json, else the zip's manifest.jsonld) and re-upload.")
        return 1

    print("\nPASS — no live pack carries the retired banner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
