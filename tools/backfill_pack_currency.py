#!/usr/bin/env python3
"""Repair the money symbol on packs rendered before the renderer knew its market.

`_render_financial_model` hardcoded `£` until `091e806` (2026-08-08). Packs generated
before that carry a headline row like `- **£295**` in a `us` pack, while the model's own
justification prose two sections down says `$295`. The number was always right — the
artifacts prompt has been handed `currency_hint` since `5fa2388` (2026-07-30), so the
model supplied local figures — only the symbol Python stamped in front of it was wrong.
`lint_pack` refuses to list such a pack, correctly.

WHAT THIS MAY AND MAY NOT TOUCH
-------------------------------
A foreign symbol in a pack is one of two completely different things, and treating them
alike is how a source-or-die storefront starts lying:

  * A **rendered row** — Python formatting a number it computed. A wrong symbol here is
    this bug, and swapping it is the whole repair.
  * A **quoted comparable** — "PACER charges $0.10 per page (source: pacer.uscourts.gov)"
    inside a `uk` pack. The figure is foreign because the SOURCE is foreign. Rewriting it
    to `£0.10` would falsify a citation. `check_currency` already tolerates these: it
    grades a foreign amount as a warning when the market's own symbol appears alongside,
    and errors only when the buyer never sees their own currency.

The boundary is not a judgement call and not a curated list of pack ids. It is stated in
the renderer itself (`prospector/artifacts.py`, above the `assumptions_list` block): the
"Key Assumptions" and "Model Weaknesses" lists "are the only FREE TEXT in this artifact —
everything above is Python formatting a number." So this tool rewrites symbols ONLY above
the first of those two headers, and only where the symbol is immediately followed by a
digit. Free text is reported and never edited. Every other artifact, and the marketing
copy, are reported and never edited.

The target symbol comes from `pack_linter.expected_currency` — the same function the gate
rules with — so a repair and the verdict on it cannot disagree by construction.

Usage:
    python -m tools.backfill_pack_currency                 # report, write nothing
    python -m tools.backfill_pack_currency --apply         # repair rendered rows
    python -m tools.backfill_pack_currency <id> [<id>...]  # restrict to these packs
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector.pack_linter import (  # noqa: E402
    expected_currency,
    split_rendered_free_text,
)

STORE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "store", "dossiers")

# A money amount is a symbol bound to a digit. `$` loose in a sentence ("$ per seat") is
# not an amount and is not this bug, so it is left alone rather than guessed at.
_AMOUNT = re.compile(r"([£$€])(?=\d)")


def _rendered_region_end(text: str) -> int:
    """Index where Python-rendered output stops and model free text begins.

    Delegates to the linter so the repair and the gate cannot drift apart: a tool that
    edited a region the gate grades differently would fix packs into a new failure.
    """
    return len(split_rendered_free_text(text)[0])


def _repair_rendered(text: str, want: str) -> Tuple[str, List[str]]:
    """Rewrite foreign money symbols in the rendered region only. Digits untouched."""
    end = _rendered_region_end(text)
    head, tail = text[:end], text[end:]
    changed: List[str] = []

    def sub(m: re.Match) -> str:
        if m.group(1) == want:
            return m.group(1)
        return want

    for line in head.split("\n"):
        if _AMOUNT.search(line) and any(
            s != want for s in _AMOUNT.findall(line)
        ):
            changed.append(line.strip())

    return _AMOUNT.sub(sub, head) + tail, changed


def _foreign_elsewhere(text: str, want: str) -> List[str]:
    """Amounts in a foreign symbol OUTSIDE the rendered region — reported, never edited."""
    out: List[str] = []
    for line in text[_rendered_region_end(text):].split("\n"):
        if any(s != want for s in _AMOUNT.findall(line)):
            out.append(line.strip())
    return out


def _iter_dossiers(ids: List[str]) -> List[str]:
    if ids:
        return [os.path.join(STORE_DIR, f"{i}.pass.json") for i in ids]
    return sorted(glob.glob(os.path.join(STORE_DIR, "*.pass.json")))


def _detect_indent(raw: str) -> Optional[int]:
    for line in raw.split("\n")[1:3]:
        stripped = line.lstrip(" ")
        if stripped and stripped != line:
            return len(line) - len(stripped)
    return None


def main(argv: List[str]) -> int:
    apply = "--apply" in argv
    ids = [a for a in argv if not a.startswith("--")]

    repaired = skipped = 0
    reports: List[str] = []

    for path in _iter_dossiers(ids):
        if not os.path.exists(path):
            print(f"  MISSING {path}")
            continue
        raw = open(path, encoding="utf-8").read()
        doc: Dict[str, Any] = json.loads(raw)
        cand = doc.get("candidate") or {}
        cid = cand.get("id") or os.path.basename(path).split(".")[0]
        market = str(cand.get("market") or doc.get("market") or "")
        want = expected_currency(market)
        if not want:
            continue  # unmapped market lints currency-free; nothing to align to

        tags = cand.get("tags") or {}
        artifacts = tags.get("artifacts") or {}
        fm = artifacts.get("financial_model")
        if not isinstance(fm, str) or not fm.strip():
            continue

        new_fm, changed = _repair_rendered(fm, want)
        quoted = _foreign_elsewhere(fm, want)

        # Foreign amounts in the OTHER artifacts and in the marketing copy are outside
        # this tool's remit entirely: none of them is Python-rendered.
        other: List[str] = []
        for name, body in artifacts.items():
            if name == "financial_model" or not isinstance(body, str):
                continue
            for line in body.split("\n"):
                if any(s != want for s in _AMOUNT.findall(line)):
                    other.append(f"{name}: {line.strip()[:90]}")

        if not changed and not quoted and not other:
            continue

        reports.append(f"\n--- {cid}  market={market}  expects {want} ---")
        for line in changed:
            reports.append(f"    REPAIR  {line[:96]}")
        for line in quoted:
            reports.append(f"    quoted (left alone, free text) {line[:70]}")
        for line in other:
            reports.append(f"    quoted (left alone, {line[:70]})")

        if changed and apply:
            artifacts["financial_model"] = new_fm
            indent = _detect_indent(raw)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=indent, ensure_ascii=False)
            os.replace(tmp, path)
            repaired += 1
        elif changed:
            skipped += 1

    print("\n".join(reports) if reports else "No packs carry a foreign rendered symbol.")
    print(f"\n{'REPAIRED' if apply else 'WOULD REPAIR'}: "
          f"{repaired if apply else skipped} pack(s). "
          f"{'' if apply else 'Re-run with --apply to write.'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
