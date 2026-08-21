"""The gate must not re-run to learn what it already wrote down.

Every gate run persists its full problem list to `store/dossiers/<id>.lint.json`
(`bridge.py:1102`). Measured 2026-08-17, one pack gated end to end took **945 seconds**,
almost all of it live network. Running it again on an unchanged pack pays that twice and the
second payment buys nothing — and worse, one-pack-at-a-time never reveals that most of the
backlog shares a single cause.

That lesson was first written down as a rule. Rules get forgotten, so it lives here as a
default instead: `tools.publish_passes --dry-run` reports from the stored record whenever the
record is newer than the pack, and only runs the gate when it is not.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from prospector.pack_linter import RULESET_VERSION
from tools import publish_passes


def _write(path: Path, payload: dict, *, mtime: float) -> None:
    path.write_text(json.dumps(payload))
    os.utime(path, (mtime, mtime))


class TestFreshLint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.pack = self.dir / "abc123.pass.json"
        self.lint = self.dir / "abc123.lint.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_record_written_after_the_pack_is_used(self):
        """Newer than the pack AND written by today's rules. Both, since 2026-08-17.

        mtime answers "has the pack changed" and cannot answer "have the rules changed", so
        the receipt also carries `pack_linter.RULESET_VERSION` — a fingerprint of the linter
        source — and a receipt from any other ruleset is refused like a missing one.
        """
        now = time.time()
        _write(self.pack, {"candidate": {}}, mtime=now - 100)
        _write(self.lint, {"ok": False, "problems": [], "ruleset": RULESET_VERSION}, mtime=now)

        rec = publish_passes._fresh_lint(str(self.pack))

        self.assertIsNotNone(rec, "a receipt newer than the pack it describes was ignored")
        self.assertIs(rec["ok"], False)

    def test_a_record_written_before_the_pack_is_not_used(self):
        """The repair case. `tools/recover_stranded_passes.py` rewrites the .pass.json and
        then re-gates; grading the repair against the previous day's record is exactly the
        defect that wrote 19 false `blocked` rows into store/ops/pack_recovery.jsonl."""
        now = time.time()
        _write(self.lint, {"ok": False, "problems": []}, mtime=now - 100)
        _write(self.pack, {"candidate": {}}, mtime=now)

        self.assertIsNone(publish_passes._fresh_lint(str(self.pack)),
                          "a stale receipt was served for a pack repaired after it")

    def test_no_record_at_all_means_run_the_gate(self):
        _write(self.pack, {"candidate": {}}, mtime=time.time())
        self.assertIsNone(publish_passes._fresh_lint(str(self.pack)))

    def test_a_corrupt_record_means_run_the_gate(self):
        """The guard may cost a run it did not need. It may never return a wrong verdict."""
        now = time.time()
        _write(self.pack, {"candidate": {}}, mtime=now - 100)
        self.lint.write_text("{not json")
        os.utime(self.lint, (now, now))

        self.assertIsNone(publish_passes._fresh_lint(str(self.pack)))

    def test_a_record_that_is_not_an_object_means_run_the_gate(self):
        now = time.time()
        _write(self.pack, {"candidate": {}}, mtime=now - 100)
        _write(self.lint, ["problems"], mtime=now)  # type: ignore[arg-type]

        self.assertIsNone(publish_passes._fresh_lint(str(self.pack)))

    def test_a_path_that_is_not_a_pass_file_is_never_matched_to_a_receipt(self):
        """`re.sub` returns the input unchanged when it does not match. Without the guard
        that returns, a non-pass path would compare a file against itself and always look
        fresh."""
        other = self.dir / "abc123.kill.json"
        _write(other, {"ok": True}, mtime=time.time())

        self.assertIsNone(publish_passes._fresh_lint(str(other)))


class TestReportCached(unittest.TestCase):
    def test_a_clean_record_counts_as_would_list(self):
        rec = {"ok": True, "checked_at": "2026-08-17T14:35:04Z",
               "problems": [{"check": "currency", "severity": "warning",
                             "where": "financial_model_notes", "detail": "mixed symbols"}]}
        self.assertIs(publish_passes._report_cached("abc123", rec), True)

    def test_a_blocked_record_counts_as_held_back(self):
        rec = {"ok": False, "checked_at": "2026-08-17T15:07:50Z",
               "problems": [{"check": "shelf_copy", "severity": "error",
                             "where": "cardLine", "detail": "unexplained initialism AWS"}]}
        self.assertIs(publish_passes._report_cached("abc123", rec), False)

    def test_a_record_with_no_problems_list_does_not_raise(self):
        self.assertIs(publish_passes._report_cached("abc123", {"ok": True}), True)


class TestTheFlagExists(unittest.TestCase):
    def test_force_regate_is_documented_where_the_operator_will_look(self):
        """A guard nobody can turn off is a trap when a lint RULE changes: every stored
        record was written by the old rule and is worth nothing."""
        src = Path(publish_passes.__file__).read_text()
        self.assertIn("--force-regate", src)
        self.assertIn("--force-regate", publish_passes.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
