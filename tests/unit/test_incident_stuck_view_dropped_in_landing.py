"""Incident: the Now page's stuck-work view vanished from the API and nothing failed.

PR #265 added `_stuck` and `_awaiting_recovery` to `_read_status` and the `StuckWork` panel to
the Now page. PR #312, a bulk landing, hand-resolved a conflict in `console_api.py` and silently
dropped the two functions; its body accounts for the resolution as "kept both the shop views and
the receipt-staleness gate" and never mentions them. The frontend kept rendering
`data?.stuck ? <StuckWork/> : null`, so the panel simply never appeared again — no error, no red
test, a dead batch invisible exactly the way `_stuck`'s own docstring warns about.

The class, not the instance: any key the Now page reads off the status payload can be dropped
this way, because `data?.key` renders nothing when the key is gone. So the guard walks the page
for every `data?.<key>` it reads and requires `_read_status` to answer each one.
"""

from __future__ import annotations

import re
import types
from pathlib import Path

from prospector.ops import console_api

REPO = Path(__file__).resolve().parents[2]
INDEX_TSX = REPO / "store_platform/src/Ops.Console/src/pages/index.tsx"


def test_incident_0312_every_key_the_now_page_reads_is_in_the_status_answer(tmp_path):
    assert INDEX_TSX.exists(), f"index.tsx moved; this test is now grading nothing: {INDEX_TSX}"
    keys_read = sorted(set(re.findall(r"data\?\.([a-z_]+)", INDEX_TSX.read_text())))
    assert keys_read, "parsed no data?.<key> reads out of index.tsx — the pattern drifted"

    cfg = types.SimpleNamespace(store_dir=tmp_path)
    out = console_api._read_status(cfg, {})

    missing = [k for k in keys_read if k not in out]
    assert not missing, (
        f"the Now page reads {missing} off the status payload and the API does not send "
        "them; `data?.key` renders nothing when the key is gone, so this fails silently "
        "in the browser — which is how #312 hid the stuck view"
    )


def test_incident_0312_stuck_view_answers_on_an_empty_store(tmp_path):
    """The restored view itself: an empty store is a healthy answer, not an error."""
    cfg = types.SimpleNamespace(store_dir=tmp_path)
    stuck = console_api._stuck(cfg, {})
    assert stuck["needs_attention"] == 0
    assert stuck["awaiting_recovery"]["count"] == 0
