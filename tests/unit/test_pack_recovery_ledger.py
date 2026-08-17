"""The recovery ledger must stop a second run paying for a failure it already bought.

That is the whole reason the ledger exists, so it is the thing pinned here: the skip rules,
the route each lint record maps to, and the failure signature that makes two runs
comparable. A signature that changes between identical runs can never reach MAX_ATTEMPTS,
so the tool would retry a dead pack forever while looking like it was learning.
"""
from __future__ import annotations

import importlib

recover = importlib.import_module("tools.recover_stranded_passes")


def _row(**kw):
    row = {"ts": "2026-08-17T00:00:00+00:00", "pack": "p", "route": "copy",
           "signature": "shelf_copy", "outcome": "blocked"}
    row.update(kw)
    return row


class TestVerdict:
    def test_a_pack_with_no_history_runs(self):
        assert recover.verdict([], "copy", "shelf_copy")[0] == "run"

    def test_an_unrecoverable_mark_skips_and_says_why(self):
        action, why = recover.verdict(
            [_row(outcome="unrecoverable", why="dead citations")], "copy", "shelf_copy")
        assert action == "skip"
        assert "dead citations" in why

    def test_an_already_published_pack_is_not_republished(self):
        assert recover.verdict([_row(outcome="published")], "publish", "clean")[0] == "skip"

    def test_the_same_failure_MAX_ATTEMPTS_times_stops_being_retried(self):
        history = [_row() for _ in range(recover.MAX_ATTEMPTS)]
        action, why = recover.verdict(history, "copy", "shelf_copy")
        assert action == "skip"
        assert "nothing new to try" in why

    def test_fewer_than_MAX_ATTEMPTS_still_runs(self):
        history = [_row() for _ in range(recover.MAX_ATTEMPTS - 1)]
        assert recover.verdict(history, "copy", "shelf_copy")[0] == "run"

    def test_failures_on_a_DIFFERENT_signature_do_not_count(self):
        """A pack that fails a new way each time is still moving; only identical
        failures prove the route is spent."""
        history = [_row(signature=f"check_{i}") for i in range(recover.MAX_ATTEMPTS + 2)]
        assert recover.verdict(history, "copy", "shelf_copy")[0] == "run"

    def test_a_reset_row_clears_the_unrecoverable_mark(self):
        history = [_row(outcome="unrecoverable"), _row(outcome="reset", route="-")]
        assert recover.verdict(history, "copy", "shelf_copy")[0] == "run"


class TestAnUnmeasuredAttemptIsNotAFailure:
    """A re-gate that never finished proves nothing, and must not count as a failure.

    The tool repairs a pack, then re-runs the gate so the lint record on disk describes the
    REPAIR and not the state before it. When that re-gate is cut short the old lint record
    survives, the signature is unchanged, and the attempt is indistinguishable from "the
    repair did nothing". Measured 2026-08-17: 19 of the first 44 attempts in
    store/ops/pack_recovery.jsonl carry `regate: "timed out"`, and
    store/dossiers/7be1cb35e01902d7.pass.json had fully repaired copy written at 14:47 while
    its .lint.json still read `checked_at: 2026-08-16T06:40:33`. Counting those towards
    MAX_ATTEMPTS retires packs whose repair was never actually measured.
    """

    def test_the_regate_gets_a_bigger_budget_than_the_repair(self):
        """Measured 2026-08-17: one pack gated end to end took 945s, just over the 900s
        default --timeout. A floor at or under the measurement is not a floor."""
        assert recover.REGATE_MIN_S > 945

    def test_unmeasured_attempts_never_accumulate_to_a_skip(self):
        history = [_row(outcome="unmeasured") for _ in range(recover.MAX_ATTEMPTS + 3)]
        assert recover.verdict(history, "copy", "shelf_copy")[0] == "run"

    def test_unmeasured_does_not_help_real_failures_reach_the_cap(self):
        history = [_row(outcome="unmeasured"), _row(outcome="blocked"),
                   _row(outcome="unmeasured"), _row(outcome="blocked")]
        assert recover.verdict(history, "copy", "shelf_copy")[0] == "run"

    def test_real_failures_still_reach_the_cap_alongside_unmeasured_ones(self):
        history = ([_row(outcome="unmeasured")]
                   + [_row(outcome="blocked") for _ in range(recover.MAX_ATTEMPTS)])
        assert recover.verdict(history, "copy", "shelf_copy")[0] == "skip"


class TestSignature:
    def test_two_identical_lint_records_give_the_same_signature(self):
        lint = {"pack_complete": True, "problems": [
            {"check": "shelf_copy", "severity": "error", "message": "row 4 of 9"}]}
        other = {"pack_complete": True, "problems": [
            {"check": "shelf_copy", "severity": "error", "message": "row 7 of 9"}]}
        assert recover._signature(lint) == recover._signature(other) == "shelf_copy"

    def test_warnings_are_not_part_of_the_signature(self):
        lint = {"pack_complete": True, "problems": [
            {"check": "shelf_copy", "severity": "error"},
            {"check": "arithmetic", "severity": "warning"}]}
        assert recover._signature(lint) == "shelf_copy"

    def test_a_clean_record_says_clean(self):
        assert recover._signature({"pack_complete": True, "problems": []}) == "clean"

    def test_a_missing_record_is_not_a_clean_one(self):
        assert recover._signature(None) == "no-lint-record"


class TestRoute:
    def test_no_lint_record_routes_to_the_free_audit(self):
        assert recover._route(None) == "audit"

    def test_an_incomplete_pack_needs_regeneration(self):
        assert recover._route({"pack_complete": False}) == "regenerate"

    def test_a_missing_bundle_file_rebundles_before_anything_costs_money(self):
        assert recover._route(
            {"pack_complete": True, "bundle_missing": ["Assumptions.csv"]}) == "rebundle"

    def test_copy_checks_route_to_the_copy_sweep(self):
        for check in ("shelf_copy", "title", "title_claim"):
            lint = {"pack_complete": True,
                    "problems": [{"check": check, "severity": "error"}]}
            assert recover._route(lint) == "copy", check

    def test_a_clean_record_only_needs_publishing(self):
        assert recover._route({"pack_complete": True, "problems": []}) == "publish"

    def test_an_unknown_blocker_asks_for_a_human_rather_than_guessing(self):
        lint = {"pack_complete": True,
                "problems": [{"check": "arithmetic", "severity": "error"}]}
        assert recover._route(lint) == "manual"


class TestConfigKeysAreInTheBlockThatReadsThem:
    """A key in the wrong YAML block is silence, not an error.

    These four were written under `consumer:` first. `run_scheduled._sched` reads
    `schedule.*`, so every one of them read back as its default and the rail was off while
    config.yaml said it was on. Nothing failed; it just did not run.
    """

    def test_the_recover_keys_live_under_schedule(self):
        import pathlib

        import yaml

        root = pathlib.Path(__file__).resolve().parents[2]
        cfg = yaml.safe_load((root / "config.yaml").read_text())
        keys = ("recover_stranded_packs", "recover_per_tick", "recover_interval_s",
                "recover_publish")
        missing = [k for k in keys if k not in cfg["schedule"]]
        assert not missing, f"config.yaml schedule: is missing {missing}"
        strays = sorted(
            f"{block}.{k}"
            for block, body in cfg.items()
            if isinstance(body, dict) and block != "schedule"
            for k in keys if k in body)
        assert not strays, f"recover keys in a block nothing reads: {strays}"

    def test_the_scheduler_actually_reads_them(self):
        from prospector.config import load_config
        from prospector.scheduler import run_scheduled as rs

        cfg = load_config()
        sentinel = object()
        for key in ("recover_stranded_packs", "recover_per_tick", "recover_interval_s",
                    "recover_publish"):
            assert rs._sched(cfg, key, sentinel) is not sentinel, key


class TestMoneyRailFence:
    def test_publish_needs_the_explicit_flag(self):
        assert recover._cmd("publish", "abc", publish=False) is None
        assert recover._cmd("publish", "abc", publish=True)[-1].endswith("abc.pass.json")

    def test_regeneration_is_money_rail_work_and_waits_for_the_same_flag(self):
        """publish_passes only generates on the path that also lists: --dry-run implies
        --reuse-artifacts. A regenerate route without --publish would run a gate and
        report a repair it never made."""
        assert recover._cmd("regenerate", "abc", publish=False) is None

    def test_every_repair_route_stays_off_the_money_rail(self):
        for route in ("audit", "rebundle", "copy", "citations", "currency"):
            cmd = recover._cmd(route, "abc", publish=False)
            assert cmd is not None, route
            assert "--dry-run" in cmd or "publish_passes" not in " ".join(cmd), route
