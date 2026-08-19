"""One cutter caps every shelf field, and it is not a bare slice.

`bridge._cap_words` existed because a hard `text[:cap]` shipped a subhead ending "to a true
hourly wag" on 2026-08-08. `check_truncation` catches exactly that shape — `len(final) == cap`
with a word character either side of the cut — so a hard slice does not merely read badly, it
unlists the pack.

Three other writers of the same fields did not use it, because it was private and lived in the
money rail's own module: `pack_floors.claim_safe_marketing` (two fields) and
`tools/backfill_listing_copy.catalog_payload` (two more), whose docstring claims it "mirrors
bridge.py exactly" while doing the opposite.

`pack_floors` is the worse of the two. It writes `headline` and `subhead` FROM the title and
one-liner, so a hard cut there also destroys the untruncated source `check_truncation` compares
against — the linter cannot flag a cut it can no longer see.

The cutter now lives in `trimming.py`, which every one of them can import.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from prospector.pack_floors import claim_safe_marketing
from prospector.pack_linter import check_truncation
from prospector.trimming import cap_words

# 320 chars, and the two leading X's are load-bearing: they place index 280 in the middle of
# "out", so the old bare slice cut mid-word. Without them the cap landed on a space and the
# defect was invisible — which is how a first attempt at this test passed against BOTH the
# broken and the fixed code.
LONG_LINE = "XX" + (
    "A grounded one-line description of an opportunity for operators who want a clear, "
    "evidenced starting point without wading through vendor marketing or guesswork, and "
    "who need the numbers stated plainly enough to argue with before committing capital "
    "to anything at all, written out here at some considerable length indeed."
)


def _candidate(one_liner: str) -> SimpleNamespace:
    return SimpleNamespace(title="A pack title", one_liner=one_liner, why_now="", who_pays="")


def test_the_old_bare_slice_really_would_have_unlisted_the_pack():
    """Non-vacuity. If this stops flagging, the fixture stopped exercising the defect and every
    other test in this file is measuring nothing."""
    bare = LONG_LINE[:280]
    flags = check_truncation({"subhead": (bare, LONG_LINE)}, {"subhead": 280})
    assert flags, "the fixture no longer cuts mid-word — fix the fixture, not the assert"
    assert flags[0]["severity"] == "error"
    assert "hard-sliced mid-word" in flags[0]["detail"]


def test_the_marketing_floor_caps_the_subhead_on_a_word_boundary():
    piece = claim_safe_marketing(_candidate(LONG_LINE))[0]
    assert piece["type"] == "listing_page"
    sub = piece["subhead"]
    assert len(sub) <= 280
    assert not sub.endswith(" ")
    assert check_truncation({"subhead": (sub, LONG_LINE)}, {"subhead": 280}) == []


def test_the_marketing_floor_caps_the_headline_on_a_word_boundary():
    long_title = "Word " * 40  # 200 chars, over the 140 headline cap
    piece = claim_safe_marketing(_candidate(""))[0]
    assert piece["headline"]  # sanity: the floor writes one at all
    piece = claim_safe_marketing(
        SimpleNamespace(title=long_title, one_liner="", why_now="", who_pays=""))[0]
    head = piece["headline"]
    assert len(head) <= 140
    assert check_truncation({"headline": (head, long_title.strip())}, {"headline": 140}) == []


def test_a_short_line_is_left_exactly_alone():
    """The cap must not become a tax on the normal path — this is the case that always runs."""
    piece = claim_safe_marketing(_candidate("A short, complete one-liner."))[0]
    assert piece["subhead"] == "A short, complete one-liner."


def test_the_backfill_uses_the_same_cutter_its_docstring_promises():
    from tools.backfill_listing_copy import catalog_payload

    payload = catalog_payload({"headline": "Head " * 40, "subhead": LONG_LINE})
    assert check_truncation({"subhead": (payload["subhead"], LONG_LINE)},
                            {"subhead": 280}) == []
    assert len(payload["headline"]) <= 140
    assert not payload["headline"].endswith(" ")


def test_the_bridge_re_export_is_the_same_function_not_a_second_copy():
    """Two copies of a cutter drift. `bridge._cap_words` is still imported by `run.py` and by
    `tests/unit/test_bridge_card_field_caps.py`, so the name stays — pointing at the one
    implementation."""
    from prospector.bridge import _cap_words

    assert _cap_words is cap_words


def test_no_shelf_field_is_capped_by_a_bare_slice_anywhere():
    """A ratchet. Every one of these four sites was written by someone who did not know a
    word-boundary cutter existed, which is what a private name in the money rail's module
    causes. A new one must fail here rather than on the shelf."""
    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(
        r'"(headline|subhead|cardLine|card_line)"\s*:.*\[\s*:\s*\d+\s*\]')
    offenders, scanned = [], 0
    for base in ("prospector", "tools"):
        for path in sorted((root / base).rglob("*.py")):
            for i, line in enumerate(path.read_text().splitlines()):
                if '"headline"' in line or '"subhead"' in line or '"cardLine"' in line:
                    scanned += 1
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(root)}:{i + 1}: {line.strip()}")
    assert not offenders, (
        "shelf fields capped by a bare slice — use `trimming.cap_words`:\n"
        + "\n".join(offenders))
    assert scanned >= 6, f"the scan matched only {scanned} shelf-field writes — has it gone blind?"
