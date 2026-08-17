"""A lint receipt may not outlive the rules that produced it.

`tools/publish_passes.py::_fresh_lint` trusts a stored verdict when the receipt is newer than
the pack. That answers "has the PACK changed". It cannot answer "have the RULES changed",
because editing `pack_linter.py` touches no dossier: every receipt stays byte-identical and
newer than its pack.

Measured 2026-08-17. Five rules stopped blocking that day and seven stranded packs became
sellable. Not one receipt on disk knew it, so `--dry-run` would have gone on reporting all
seven as blocked, from a file, with no gate run able to correct it — the tool would have been
reporting yesterday's rules as today's answer, with no way for anyone to tell.

`pack_linter.RULESET_VERSION` is stamped into every receipt and a mismatch is treated exactly
like a missing record: re-gate and find out. Same mechanism as `_PROBE_LOGIC_VERSION`, which
exists because a cached 404 outlived the probe fix that would have cleared it.
"""
from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from prospector.pack_linter import RULESET_VERSION
from tools.publish_passes import _fresh_lint


class _Pack:
    """A `.pass.json` with a `.lint.json` beside it, the receipt written second."""

    def __init__(self, tmp: str, receipt: dict | None):
        self.pass_path = os.path.join(tmp, "abc123.pass.json")
        Path(self.pass_path).write_text("{}")
        if receipt is not None:
            time.sleep(0.01)   # the receipt must be the newer file
            Path(os.path.join(tmp, "abc123.lint.json")).write_text(json.dumps(receipt))


class TestTheStampDecidesFreshness(unittest.TestCase):
    def test_the_current_ruleset_is_served_from_the_receipt(self):
        with TemporaryDirectory() as tmp:
            p = _Pack(tmp, {"ok": True, "ruleset": RULESET_VERSION, "problems": []})
            self.assertIsNotNone(_fresh_lint(p.pass_path))

    def test_an_older_ruleset_is_refused(self):
        with TemporaryDirectory() as tmp:
            p = _Pack(tmp, {"ok": False, "ruleset": "a-retired-ruleset", "problems": []})
            self.assertIsNone(_fresh_lint(p.pass_path),
                              "a verdict from retired rules was served as current")

    def test_a_receipt_from_before_the_stamp_is_refused(self):
        """Every receipt on disk on 2026-08-17 is this shape."""
        with TemporaryDirectory() as tmp:
            p = _Pack(tmp, {"ok": False, "checked_at": "2026-08-16T00:00:00Z", "problems": []})
            self.assertIsNone(_fresh_lint(p.pass_path))

    def test_a_missing_receipt_is_unchanged(self):
        with TemporaryDirectory() as tmp:
            p = _Pack(tmp, None)
            self.assertIsNone(_fresh_lint(p.pass_path))


class TestTheGateStampsWhatItWrites(unittest.TestCase):
    def test_lint_pack_records_the_ruleset(self):
        """The two halves have to meet: a stamp nothing writes fails every pack forever."""
        from prospector.pack_linter import lint_pack
        report = lint_pack(artifacts={}, listing_copy="", listing_texts={}, market="uk")
        self.assertEqual(report.get("ruleset"), RULESET_VERSION)


if __name__ == "__main__":
    unittest.main()
