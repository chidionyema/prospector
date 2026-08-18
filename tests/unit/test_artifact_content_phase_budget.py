"""The ARTIFACT + MARKETING-CONTENT phase had no time budget at all, and it is what ate
the tick: on the 2026-08-15 10:17->13:17 breach, artifact/content markers in
store/scheduler/launchd.err.log span 10:40 -> 13:12 — 152 of the tick's 180 minutes
(84%) — while `schedule.gen_budget_frac` (run_scheduled.py) bounded generation alone.
Three of the five `_TICK_HARD_DEADLINE_S` breaches recorded in store/scheduler/
ticks.jsonl landed in the 48h before this fix.

This file proves three things, none of them hypothetical:
  (a) a ThreadPoolExecutor batch that overruns its `deadline_mono` returns whatever
      completed instead of hanging or raising (mirrors generate.py:771's fix exactly);
  (b) `schedule.artifact_budget_frac` is read from config, with 0 disabling the rail —
      the same convention as `schedule.gen_budget_frac`;
  (c) listing_page — required for publish — survives a partial marketing-content batch
      even when it is the piece still running at the shared deadline;
  (d) a force-exited tick (`_force_exit_hung_tick`) now records elapsed wall-clock time
      and a heartbeat snapshot, not just the constant deadline and the configured batch
      size — the founder directive that "the one event we most need evidence about
      leaves the least evidence" (2026-08-15).

No real operator or network call anywhere below: `_gen_one_artifact` / `_gen_one_content`
are monkeypatched to sleeping stand-ins so these tests are fast and deterministic.
"""
from __future__ import annotations

import json
import threading
import time

from prospector import artifacts as art_mod
from prospector.scheduler import run_scheduled as rs_mod


class _Cand:
    candidate_id = "c" * 16
    # The real Candidate always carries both (`models.py:172`), and `_generate_pack_content`
    # now repairs them before it builds anything. Clean values on purpose: a breach here
    # would call the operator and make a budget/retry test grade the repair instead.
    title = "Weatherproof bin store signs for a single block of flats"
    one_liner = ("A printing business that makes weatherproof bin store signs for one "
                 "specific block of flats.")
    market = "us"

    def to_dict(self):
        return {"name": "Test Candidate", "market": self.market}


# ---------------------------------------------------------------------------
# (a) generate_artifacts: overrun returns completed pieces, never hangs or raises
# ---------------------------------------------------------------------------

class TestGenerateArtifactsBudget:
    def test_overrun_returns_partial_result_not_a_hang_or_raise(self, monkeypatch, caplog):
        """gtm_plan never finishes inside the budget; the other three must still ship."""
        SLOW = "gtm_plan"
        # The slow piece BLOCKS ON AN EVENT rather than sleeping a fixed span, for two
        # reasons that a bare `time.sleep` got wrong (it flaked at 4.04s against a 2.0s
        # ceiling under `-n auto` on 2026-08-15, and its 5.0s sleep was close enough to
        # the ceiling that noise and the real defect were no longer distinguishable):
        # the block is long enough (60s) that a rail which actually awaits the abandoned
        # future cannot be confused with scheduler contention, and the release in
        # `finally` means the worker thread never outlives the test — an unreleased
        # 60s sleep would be joined by concurrent.futures at interpreter exit and add
        # its whole span to the end of the suite.
        released = threading.Event()

        def _fake(op, cand_json, claims_json, t, market_vars=None, length_rule="",
                  check_op=None, claims=None, prose_repair=True):
            if t == SLOW:
                released.wait(60.0)  # far past any budget below; must never be awaited
            if t == "financial_model":
                return t, f"content-{t}", {"revenue": 1}, []
            return t, f"content-{t}", None, []

        monkeypatch.setattr(art_mod, "_gen_one_artifact", _fake)
        deadline = time.monotonic() + 0.15

        try:
            t0 = time.monotonic()
            with caplog.at_level("WARNING"):
                results = art_mod.generate_artifacts(
                    object(), _Cand(), [], cfg=None, deadline_mono=deadline)
            elapsed = time.monotonic() - t0
        finally:
            released.set()

        assert elapsed < 10.0, (
            f"blocked {elapsed:.2f}s waiting on an abandoned future that blocks for 60s "
            f"— the exact defect this rail exists to close (generate.py's 'BOUNDED WAIT')")
        assert results["build_spec"] == "content-build_spec"
        assert results["ops_plan"] == "content-ops_plan"
        assert results["financial_model"] == "content-financial_model"
        assert results[SLOW] == "", (
            "a piece that misses the deadline must read as a failed piece "
            '(results[t] = ""), not a new failure mode')
        assert any(
            "artifact_budget_exhausted" in str(getattr(r, "artifact_budget_exhausted", ""))
            or r.levelname == "WARNING" and "phase time budget" in r.message
            for r in caplog.records), "the miss must be logged loudly, naming the piece"
        warn = next(r for r in caplog.records
                    if r.levelname == "WARNING" and "phase time budget" in r.message)
        assert SLOW in str(warn.__dict__.get("missing", [])) or SLOW in warn.message

    def test_no_deadline_is_unbounded_exactly_as_before(self, monkeypatch):
        """`deadline_mono=None` (every caller today) must not change behaviour at all."""
        def _fake(op, cand_json, claims_json, t, market_vars=None, length_rule="",
                  check_op=None, claims=None, prose_repair=True):
            if t == "financial_model":
                return t, f"content-{t}", {"revenue": 1}, []
            return t, f"content-{t}", None, []

        monkeypatch.setattr(art_mod, "_gen_one_artifact", _fake)
        results = art_mod.generate_artifacts(object(), _Cand(), [], cfg=None)
        for t in ("build_spec", "gtm_plan", "ops_plan", "financial_model"):
            assert results[t] == f"content-{t}"

    def test_budget_left_floors_positive_and_passes_through_none(self):
        assert art_mod._budget_left(None) is None
        # A deadline already in the past must not return <= 0 — a 0 timeout to
        # `as_completed` means "check once and give up", which is right AT the deadline
        # and wrong once it has passed (it would refuse to collect an already-done
        # future). See `_budget_left`'s own docstring.
        past = time.monotonic() - 10
        assert art_mod._budget_left(past) > 0


# ---------------------------------------------------------------------------
# (c) generate_marketing_content: listing_page is preferred on a partial result
# ---------------------------------------------------------------------------

class TestGenerateMarketingContentBudget:
    def _fake_content(self, listing_delay: float, ancillary_delay: float):
        # `candidate` is the Candidate OBJECT, submitted alongside `cand_json` since
        # `_normalize_listing` began deriving `facets.mechanism` from
        # `candidate.structural_form`. This fake ignores it; the parameter is here so the
        # signature matches what `generate_marketing_content` actually submits.
        def _fake(gen_op, check_op, cand_json, claims_json, claims, t, currency_rule="",
                  candidate=None):
            time.sleep(listing_delay if t == "listing_page" else ancillary_delay)
            if t == "listing_page":
                return {"type": t, "headline": "h", "card_line": "c", "copy": "x" * 40}
            return {"type": t, "copy": f"copy-{t}"}
        return _fake

    def test_overrun_omits_unfinished_pieces_not_a_hang_or_raise(self, monkeypatch, caplog):
        # All four pieces exceed the batch's shared budget; none should ever be waited on.
        monkeypatch.setattr(
            art_mod, "_gen_one_content", self._fake_content(5.0, 5.0))
        deadline = time.monotonic() + 0.15

        t0 = time.monotonic()
        with caplog.at_level("WARNING"):
            results = art_mod.generate_marketing_content(
                object(), _Cand(), [], cfg=None, deadline_mono=deadline)
        elapsed = time.monotonic() - t0

        assert elapsed < 2.0, f"blocked {elapsed:.2f}s past the deadline"
        assert results == [], "nothing finished in time — an unfinished piece is OMITTED"
        assert any(r.levelname == "WARNING" and "phase time budget" in r.message
                  for r in caplog.records)

    def test_listing_page_survives_when_it_is_the_slow_one(self, monkeypatch, caplog):
        """listing_page structurally does more work (3 attempts + salvage) than any
        ancillary piece (1 attempt), so it is the piece MOST likely to still be running
        at a shared deadline. It must get the LAST slice of the budget alone rather than
        being dropped alongside whichever ancillary pieces are also still running.
        """
        # Total budget ~0.3s. _MARKETING_BATCH_SHARE=0.9 -> the shared wait is ~0.27s.
        # listing_page finishes at ~0.29s (after the shared cutoff, before the true
        # deadline) so it can ONLY survive via the dedicated grace wait. The ancillary
        # pieces sleep far longer than the whole budget and must be dropped.
        monkeypatch.setattr(
            art_mod, "_gen_one_content", self._fake_content(0.29, 5.0))
        deadline = time.monotonic() + 0.3

        t0 = time.monotonic()
        with caplog.at_level("INFO"):
            results = art_mod.generate_marketing_content(
                object(), _Cand(), [], cfg=None, deadline_mono=deadline)
        elapsed = time.monotonic() - t0

        assert elapsed < 2.0, f"blocked {elapsed:.2f}s — an ancillary piece was awaited"
        types = [r.get("type") for r in results]
        assert types == ["listing_page"], (
            f"listing_page must survive a partial result; got {types}")
        assert any("listing_page still" in r.message for r in caplog.records), (
            "the priority grace wait must be visible in the log, not silent")

    def test_no_deadline_is_unbounded_exactly_as_before(self, monkeypatch):
        monkeypatch.setattr(art_mod, "_gen_one_content", self._fake_content(0.0, 0.0))
        results = art_mod.generate_marketing_content(object(), _Cand(), [], cfg=None)
        types = {r.get("type") for r in results}
        assert types == {"listing_page", "teaser_social", "seo_preview", "launch_email"}


# ---------------------------------------------------------------------------
# (b) schedule.artifact_budget_frac: config-declared, 0 disables the rail
# ---------------------------------------------------------------------------

class TestArtifactBudgetFracReader:
    def test_default_matches_config_yaml(self):
        # config.yaml:schedule.artifact_budget_frac must agree with the reader's own
        # fallback — the fallback is what every caller gets if the key is ever removed
        # from config.yaml, so a drift between the two is silent until that day.
        assert rs_mod._artifact_budget_frac(None) == 0.40

    def test_reads_schedule_dict(self):
        class _Cfg:
            schedule = {"artifact_budget_frac": 0.55}
        assert rs_mod._artifact_budget_frac(_Cfg()) == 0.55

    def test_reads_schedule_namespace(self):
        class _Schedule:
            artifact_budget_frac = 0.2
        class _Cfg:
            schedule = _Schedule()
        assert rs_mod._artifact_budget_frac(_Cfg()) == 0.2

    def test_zero_disables_the_rail(self):
        class _Cfg:
            schedule = {"artifact_budget_frac": 0}
        assert rs_mod._artifact_budget_frac(_Cfg()) == 0.0

    def test_negative_floors_at_zero(self):
        class _Cfg:
            schedule = {"artifact_budget_frac": -1}
        assert rs_mod._artifact_budget_frac(_Cfg()) == 0.0

    def test_garbage_value_falls_back_to_default(self):
        class _Cfg:
            schedule = {"artifact_budget_frac": "not-a-number"}
        assert rs_mod._artifact_budget_frac(_Cfg()) == 0.40

    def test_gen_and_artifact_fracs_together_never_exceed_the_tick_deadline(self):
        """The config comment's own arithmetic, pinned so a future edit to either
        default cannot silently break the "generation + artifacts <= tick deadline"
        invariant `config.yaml` documents."""
        assert rs_mod._gen_budget_frac(None) + rs_mod._artifact_budget_frac(None) <= 1.0


# ---------------------------------------------------------------------------
# (d) a force-exited tick records elapsed time + a heartbeat snapshot, not just the
#     constant deadline
# ---------------------------------------------------------------------------

class TestForceExitRecordsEvidence:
    def test_breach_records_elapsed_and_heartbeat_before_exiting(self, tmp_path, monkeypatch):
        exited = {}
        monkeypatch.setattr(rs_mod.os, "_exit", lambda code: exited.setdefault("code", code))

        store_dir = tmp_path / "store" / "scheduler"
        store_dir.mkdir(parents=True)
        hb_path = store_dir / "heartbeat.json"
        hb_path.write_text(json.dumps({"phase": "generating", "batch_size": 15,
                                       "mono": 123.0}))

        class _Cfg:
            pass

        monkeypatch.setattr(rs_mod, "_heartbeat_path", lambda cfg: hb_path)
        monkeypatch.setattr(rs_mod, "_append_tick", lambda cfg, tick: None)
        monkeypatch.setattr(rs_mod, "_emit_tick_alerts", lambda cfg, tick: None)
        monkeypatch.setattr(rs_mod, "_emit_tick_digest", lambda cfg, tick: None)

        started = rs_mod.datetime.now(rs_mod.timezone.utc)
        tick = {"ts": started.isoformat()}
        time.sleep(0.05)

        rs_mod._force_exit_hung_tick(15, _Cfg(), tick, phase="generation")

        assert exited.get("code") == 2, "must still force-exit — this is a hard wall"
        assert tick["breach_phase"] == "generation"
        assert tick["elapsed_s"] is not None and tick["elapsed_s"] >= 0.05
        assert tick["breach_heartbeat"] == {"phase": "generating", "batch_size": 15,
                                            "mono": 123.0}
        assert "tick_hard_deadline" in tick["error"]

    def test_a_missing_heartbeat_file_degrades_not_crashes(self, tmp_path, monkeypatch):
        exited = {}
        monkeypatch.setattr(rs_mod.os, "_exit", lambda code: exited.setdefault("code", code))
        monkeypatch.setattr(rs_mod, "_heartbeat_path", lambda cfg: tmp_path / "missing.json")
        monkeypatch.setattr(rs_mod, "_append_tick", lambda cfg, tick: None)
        monkeypatch.setattr(rs_mod, "_emit_tick_alerts", lambda cfg, tick: None)
        monkeypatch.setattr(rs_mod, "_emit_tick_digest", lambda cfg, tick: None)

        class _Cfg:
            pass

        tick = {"ts": rs_mod.datetime.now(rs_mod.timezone.utc).isoformat()}
        rs_mod._force_exit_hung_tick(15, _Cfg(), tick, phase="generation")

        assert exited.get("code") == 2
        assert tick["breach_heartbeat"] == {}
