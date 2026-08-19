#!/usr/bin/env python3
"""Audit the operator's real store/ — the checks that are about DATA, not about code.

Why this is not a pytest file
-----------------------------
These checks used to live in tests/. That conflated two questions that fail for different
reasons and need different responses:

    "is the code correct?"          a defect. Fix the code. True on every machine.
    "is this machine's data sane?"  an operational fact. Run the engine, or investigate.
                                    Meaningless on a fresh clone, where there is no data.

store/dossiers/ and store/prospector.jsonl are gitignored (.gitignore:43), so CI clones with
zero dossiers while the operator's machine has 1153. Asserting on data volume inside pytest
therefore made CI report `assert 0 >= 300` — which reads as a broken reader and is actually
"this checkout has no catalogue". On 2026-07-31 that cost four CI round-trips to untangle.

The split is the fix: pytest asserts behaviour with fixtures it constructs, and passes
anywhere. This probe asserts facts about the real store, and is run by the operator (and by
the daily backup's neighbour LaunchAgent) where the real store exists.

Per the operating rule "state is a probe, not a paragraph": the output is verdict lines, and
the exit code is the answer. 0 = every check passed, 1 = at least one FAIL, 2 = no store here.

    python3 scripts/store_audit.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector.config import store_root  # noqa: E402

DOSSIER_DIR = store_root() / "dossiers"
LEDGER = store_root() / "prospector.jsonl"
BACKFILL = REPO_ROOT / "store_platform" / "data" / "facets-backfill.json"
LISTINGS_DIR = store_root() / "listings"

# Was `assert len(idx) >= 300` in tests/ops/cc/test_readers.py. The number is a floor
# on a catalogue that only grows, not a measurement — it catches a reader silently returning
# a truncated view, which is the failure that would otherwise look like a quiet afternoon.
MIN_CATALOGUE = 300

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))


def main() -> int:
    if not DOSSIER_DIR.is_dir() or not any(DOSSIER_DIR.glob("*.json")):
        print("STORE_AUDIT SKIP no local catalogue — store/dossiers/ is gitignored and empty here.")
        print("  This is the expected state on a fresh clone or in CI. Nothing to audit.")
        return 2

    # readers is a Streamlit module, so importing it outside a Streamlit runtime emits ~20
    # lines of "No runtime found" per @st.cache_data decorator. A probe whose verdict is
    # buried under known-irrelevant warnings stops being read.
    import logging
    logging.getLogger("streamlit").setLevel(logging.ERROR)

    from prospector.ops import readers
    from prospector.report import costs_data

    # ── catalogue ────────────────────────────────────────────────────────────
    idx = readers.catalogue_index()
    check("CATALOGUE", len(idx) >= MIN_CATALOGUE,
          f"{len(idx)} entries (floor {MIN_CATALOGUE})")

    stats = readers.catalogue_stats()
    check("CATALOGUE_STATS", stats["total"] == len(idx),
          f"stats.total={stats['total']} index={len(idx)}")

    on_disk = len(list(DOSSIER_DIR.glob("*.json")))
    check("DOSSIERS_ON_DISK", on_disk > 0, f"{on_disk} files")

    # ── the packs already sold can still be re-rendered ──────────────────────
    # A stored dossier is written once and read for years, so the reader has to tolerate a row
    # older than the schema. It did not: `dossier_from_dict` built a namespace from the keys a
    # record happens to have, and `render_markdown` reads `dossier.persona` unguarded
    # (dossier.py:776) — a field every stored PASS predates. 84 records, 84 AttributeErrors,
    # which is what put the packs on the shelf out of reach of the re-render that corrects
    # their QA report. `pack_manifest._fill_defaults` fixed the class.
    #
    # This belongs here rather than in pytest for the reason at the top of this file, and the
    # reason is not bookkeeping: the fixture tests round-trip a dossier built by TODAY's
    # dataclass, so they were green the whole time every real record failed. A row written
    # before a field existed only exists where the real store is.
    from prospector import dossier as dossier_mod
    from prospector import pack_manifest
    unrenderable: list[str] = []
    pass_files = sorted(DOSSIER_DIR.glob("*.pass.json"))
    for p in pass_files:
        try:
            dossier_mod.render_markdown(
                pack_manifest.dossier_from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except Exception as exc:
            unrenderable.append(f"{p.name}: {type(exc).__name__}: {exc}")
    check("PASS_DOSSIERS_RENDER", not unrenderable,
          f"{len(pass_files)} stored PASS dossiers, all render"
          if not unrenderable
          else f"{len(unrenderable)}/{len(pass_files)} raise: {unrenderable[:3]}")

    # ── ledger / spend ───────────────────────────────────────────────────────
    if LEDGER.is_file():
        costs = costs_data(str(LEDGER))
        expected = ("total_spend_usd", "total_calls", "providers", "tokens", "slowest_ops")
        absent = [k for k in expected if k not in costs]
        check("LEDGER_SHAPE", not absent,
              "all keys present" if not absent else f"missing {absent}")
        spend = costs.get("total_spend_usd", -1)
        check("LEDGER_SPEND", spend >= 0, f"lifetime ${spend:,.2f}")
    else:
        check("LEDGER", False, f"{LEDGER} is missing — the audit trail is the liability record")

    # ── backfill integrity ───────────────────────────────────────────────────
    # Was tests/unit/test_facets.py::test_every_entry_is_a_pack_that_was_actually_published.
    # A phantom entry is a mistyped or stale pack id, which fails as a silent 404 halfway
    # through `backfill_facets.py --apply` — an operational fault, found only against real data.
    if BACKFILL.is_file():
        data = json.loads(BACKFILL.read_text(encoding="utf-8"))
        known = {p.name.split(".")[0] for p in DOSSIER_DIR.glob("*.json")}
        phantom = sorted(set(data) - known)
        check("BACKFILL_ENTRIES", not phantom,
              f"{len(data)} entries, all backed by a dossier" if not phantom
              else f"no dossier justifies: {phantom[:5]}")

    # ── listing receipts are receipts ────────────────────────────────────────
    # Was tests/unit/test_listing_schema_fence.py::test_the_shipped_listings_dir_all_passes
    # _the_fence. store/listings/ is read as authority by three consumers that never
    # re-derive what they find there (the Control Center Pub badge, backfill_missing_
    # listings.sh, decay._queue_unlist), and two mock fixtures once landed in it and were
    # counted as published packs by all three. publish.validate_listing now rejects that
    # shape on the write path; this proves nothing already on disk predates the fence.
    if LISTINGS_DIR.is_dir():
        from publish.publish import validate_listing
        bad: list[str] = []
        files = sorted(LISTINGS_DIR.glob("*.json"))
        for p in files:
            try:
                validate_listing(p.stem, json.loads(p.read_text(encoding="utf-8")))
            except Exception as exc:  # a receipt is off-schema, or is not JSON at all
                bad.append(f"{p.name}: {exc}")
        check("LISTINGS", not bad,
              f"{len(files)} receipts, all on-schema" if not bad
              else f"{len(bad)} off-schema: {bad[:3]}")

    # ── the backup actually happened ─────────────────────────────────────────
    # The point of an audit that runs where the data is: prove the offsite copy matches, not
    # that a script exists. --verify-only uploads nothing.
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "backup_store.py"), "--verify-only"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    line = (proc.stdout.strip().splitlines() or ["no output"])[-1]
    check("OFFSITE_BACKUP", proc.returncode == 0, line)

    # ── verdict ──────────────────────────────────────────────────────────────
    failed = [n for n, ok, _ in results if not ok]
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<18} {detail}")
    print(f"STORE_AUDIT {'PASS' if not failed else 'FAIL'} "
          f"checks={len(results)} failed={len(failed)}"
          + (f" [{', '.join(failed)}]" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
