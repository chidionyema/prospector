"""Unit tests for Control Center job command/outcome helpers."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from prospector.control_center.readers import (
    glance_status,
    job_outcome_summary,
    launch_archetype_choices,
    launch_lane_choices,
    launch_market_choices,
    launch_operator_choices,
    launch_profile_choices,
    parse_job_outcome_counts,
    parse_job_progress,
    summarize_job_command,
    today_spend,
)


class TestSummarizeJobCommand:
    def test_generate_k(self):
        argv = [
            "/usr/bin/python3.14", "-u", "-m", "prospector.run",
            "generate", "--candidates", "20",
        ]
        assert summarize_job_command(argv) == "generate k=20"

    def test_signal_k(self):
        argv = ["python", "-m", "prospector.run", "signal", "--count", "5", "--text", "x"]
        assert summarize_job_command(argv) == "signal k=5"

    def test_vet_resume(self):
        argv = ["python", "-m", "prospector.run", "vet", "--resume"]
        assert summarize_job_command(argv) == "vet --resume"

    def test_empty(self):
        assert summarize_job_command([]) == "—"

    def test_dash_c_is_marked_ephemeral(self):
        argv = ["/usr/bin/python3", "-c", "import time; time.sleep(60)"]
        assert "ephemeral" in summarize_job_command(argv)


class TestParseJobOutcomeCounts:
    def test_summary_line(self):
        text = "  PASS 2 / KILL 3 / DEFER 1   survival 40% (of ruled)\n"
        assert parse_job_outcome_counts(text) == {
            "n_pass": 2, "n_kill": 3, "n_defer": 1,
        }

    def test_summary_line_ansi(self):
        text = "  \x1b[1mPASS 1 / KILL 4\x1b[0m   survival 20% (of ruled)\n"
        assert parse_job_outcome_counts(text) == {
            "n_pass": 1, "n_kill": 4, "n_defer": 0,
        }

    def test_per_candidate_fallback(self):
        text = (
            "  [1/3] ✓ PASS  Idea one\n"
            "  [2/3] ✗ KILL  Idea two\n"
            "  [3/3] ⏸ DEFER Idea three\n"
        )
        assert parse_job_outcome_counts(text) == {
            "n_pass": 1, "n_kill": 1, "n_defer": 1,
        }

    def test_empty_log(self):
        assert parse_job_outcome_counts("") is None
        assert parse_job_outcome_counts("still starting…\n") is None


class TestJobOutcomeSummary:
    def test_running(self):
        assert job_outcome_summary({"status": "running"}) == "still running — see log"

    def test_finished_from_log(self, tmp_path):
        log = tmp_path / "job.log"
        log.write_text("  PASS 1 / KILL 2 / DEFER 0   survival 33% (of ruled)\n")
        out = job_outcome_summary({
            "status": "succeeded",
            "log_file": str(log),
        })
        assert out == "PASS 1 / KILL 2 / DEFER 0"

    def test_failed_no_counts(self, tmp_path):
        log = tmp_path / "job.log"
        log.write_text("boom\n")
        assert job_outcome_summary({
            "status": "failed",
            "log_file": str(log),
        }) == "failed — see log"


class TestGlanceStatus:
    def test_idle_last_failed(self):
        latest = {
            "status": "failed",
            "argv": ["python", "-m", "prospector.run", "generate", "--candidates", "20"],
            "elapsed_s": 987,
            "start_ts": 1,
        }
        out = glance_status(None, latest)
        # This sentence is built from the last MANUAL launcher job and knows nothing about the
        # daemon, so "Engine idle" was the defect, not the wording: on 2026-08-16 the console
        # printed it over a job dated 2026-07-31 while the consumer was live and ruling. The
        # contract is now (a) it never claims the engine's state, and (b) it dates itself, so a
        # stale job cannot read as current.
        assert out.startswith("No manual job running · last generate k=20 failed (987s,")
        assert "Engine idle" not in out
        assert out.endswith("ago)")

    def test_running_with_progress(self, tmp_path):
        log = tmp_path / "run.log"
        # Still in generation (no vetting markers) — glance stays "Generating".
        log.write_text("  ▸ generated 20 candidates\n")
        active = {
            "status": "running",
            "argv": [
                "python", "-m", "prospector.run", "generate",
                "--candidates", "20", "--lane", "smb",
            ],
            "log_file": str(log),
            "start_ts": 1_000_000,
        }
        out = glance_status(active, None, now=1_000_340)
        assert out.startswith("Generating")
        assert "lane smb" in out
        assert "340s" in out

    def test_running_generate_shows_vetting_once_vet_starts(self, tmp_path):
        log = tmp_path / "run.log"
        log.write_text(
            "  ▸ vetting 20 candidate(s) diverse subset live (max 2 in parallel)…\n"
            "  [12/20] ✓ PASS  Idea\n"
        )
        active = {
            "status": "running",
            "argv": [
                "python", "-m", "prospector.run", "generate",
                "--candidates", "20", "--lane", "smb",
            ],
            "log_file": str(log),
            "start_ts": 1_000_000,
        }
        out = glance_status(active, None, now=1_000_340)
        assert out.startswith("Vetting 12/20")
        assert "lane smb" in out

    def test_parse_progress(self):
        assert parse_job_progress("[1/5] x\n[3/5] y\n") == (3, 5)


class TestLaunchOperatorChoices:
    def test_config_first(self):
        choices = launch_operator_choices()
        assert choices[0] == "(config)"
        assert "claude_cli" in choices
        assert "mock" in choices
        # Offering a deleted adapter in the launcher would build a job that dies at startup
        # on `_build_operator`'s explicit ValueError. Removed 2026-08-06.
        assert "cursor_cli" not in choices


class TestLaunchScopeChoices:
    def test_lanes_are_ambition_tiers_not_stale_labels(self):
        choices = launch_lane_choices()
        # Catalogue default first; MIX (empty) last — not the yield default.
        assert choices[0] == "side_hustle"
        assert choices[-1] == ""
        for lane in ("side_hustle", "smb", "growth", "venture"):
            assert lane in choices
        for stale in ("operator", "founder", "scout"):
            assert stale not in choices

    def test_markets_only_open(self):
        choices = launch_market_choices()
        assert choices[0] == ""
        assert "uk" in choices
        assert "us" in choices  # opened 2026-07-30 on a passing readiness probe
        # Still-closed stubs must never reach the launcher.
        for closed in ("africa", "nigeria", "europe", "asia"):
            assert closed not in choices

    def test_archetypes(self):
        choices = launch_archetype_choices()
        assert choices[0] == ""
        for name in ("solo_agent", "small_team", "startup"):
            assert name in choices

    def test_profiles_include_statutory_pack(self):
        choices = launch_profile_choices()
        # Catalogue preset first; empty (research / unsteered) last.
        assert choices[0] == "statutory_compliance_pack"
        assert choices[-1] == ""
        assert "statutory_compliance_pack" in choices


class TestTodaySpendFromEvents:
    def test_sums_only_today(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        audit = [
            {"event": "spend", "ts": f"{today}T10:00:00Z", "amount_usd": 1.25, "phase": "main"},
            {"event": "spend", "ts": "2000-01-01T10:00:00Z", "amount_usd": 9.0, "phase": "main"},
            {"event": "other", "ts": f"{today}T11:00:00Z", "amount_usd": 3.0},
        ]
        out = today_spend(audit)
        assert out["total_usd"] == 1.25
        assert out["by_phase"]["main"] == 1.25
