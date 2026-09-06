#!/usr/bin/env python3
"""lint:copy — the storefront lane of the Voice Gate (spec §3/§7, phase 3).

Walks every prose leaf of Store.Web's data blobs and grades it. Kill-log `reason` fields
are graded POST-`clean_reason` — the serve seam: the page renders the reason only after
the estate's sanitizer, so the graded string is the string a buyer reads (the 2026-09-06
boundary decision). Enum fields are never graded.

Exit 1 with one line per finding; Store.Web wires this as `npm run lint:copy` inside
`npm run verify`. Pre-flip this grades with the Python oracle; post-flip the same leaf
set is POSTed to the Rust gate — the leaf walk and the seam do not change.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector.plain_text import clean_reason  # noqa: E402
from prospector.voice_gate.deny import findings_for, walk_prose  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "store_platform", "src", "Store.Web", "src", "data")


def main() -> int:
    findings = []
    leaves = 0
    for name in sorted(os.listdir(DATA)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(DATA, name), encoding="utf-8") as handle:
            doc = json.load(handle)
        for _parent, _key, path, text in walk_prose(doc):
            leaves += 1
            graded = (
                clean_reason(text) if name == "kill-log.json" and path.endswith(".reason") else text
            )
            for hit in findings_for(graded):
                findings.append(f"{name}{path}: {hit.rule_id} {hit.message}")
    if findings:
        for line in findings[:40]:
            print(f"FAIL {line}", file=sys.stderr)
        print(f"lint:copy: {len(findings)} finding(s) over {leaves} leaves", file=sys.stderr)
        return 1
    print(f"lint:copy: PASS ({leaves} prose leaves graded clean)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
