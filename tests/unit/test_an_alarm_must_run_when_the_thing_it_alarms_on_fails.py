"""An alert step is useless in a job that does not run on the failure it reports.

WHAT HAPPENED. `.github/workflows/e2e-live-smoke.yml` opens a `live-red` GitHub issue when the
storefront smoke fails and closes it when the smoke passes. The two steps were written carefully:
they de-duplicate against an already-open issue, they comment rather than re-open, and they close
with a reason. They were attached to the `visual-baselines` job, which runs only on
`workflow_dispatch` with `update_visual_baselines: true`.

So on the daily schedule and on every deploy that job was SKIPPED, and a skipped job runs no
steps. Measured 2026-08-19: five consecutive live-smoke runs failed (32297503069, 32266166158,
32239852032, 32229157920, 32222302816) and not one issue was opened. Memory
`a-check-that-runs-after-deploy-cannot-prevent-a-deploy.md` records the same mechanism costing 30
hours of unreported red.

THE CLASS: a reporting mechanism whose own trigger is narrower than the thing it reports on. It
never fails; it is simply never reached, and every instrument says the workflow ran fine. Nothing
downstream can detect it, which is why the check has to be static and has to be here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / ".github" / "workflows" / "e2e-live-smoke.yml"

# the checks whose failure the alarm exists to report
GRADED = {"smoke", "a11y", "lighthouse"}


def _doc() -> dict:
    return yaml.safe_load(SMOKE.read_text())


def _alarm_jobs(doc: dict) -> dict:
    """Jobs that touch the live-red issue, whatever they are called."""
    return {n: j for n, j in doc["jobs"].items() if "live-red" in json.dumps(j)}


def test_exactly_one_job_owns_the_alarm():
    jobs = _alarm_jobs(_doc())
    assert len(jobs) == 1, (
        f"the live-red issue must have exactly one owner; found {sorted(jobs)}. Two owners race "
        f"and one of them will close an issue the other just opened."
    )


def test_the_alarm_waits_for_every_check_it_reports_on():
    doc = _doc()
    name, job = next(iter(_alarm_jobs(doc).items()))
    needs = set(job.get("needs") or [])

    assert GRADED <= needs, (
        f"job `{name}` reports on the live smoke but does not need {sorted(GRADED - needs)}. A "
        f"check it does not need can fail without the alarm ever seeing it."
    )
    assert needs <= set(doc["jobs"]), f"`{name}` needs a job that does not exist: {needs}"


def test_the_alarm_still_runs_when_a_check_has_failed():
    """This is the whole defect: a job that only runs on success can never report a failure."""
    name, job = next(iter(_alarm_jobs(_doc()).items()))
    cond = str(job.get("if", ""))

    assert "always()" in cond, (
        f"job `{name}` has `if: {cond or '(none)'}`. Without always(), GitHub skips a job whose "
        f"dependencies failed -- so the alarm is silent on exactly the runs it exists for."
    )
    assert "workflow_dispatch" not in cond and "inputs." not in cond, (
        f"job `{name}` is gated on a manual dispatch input (`if: {cond}`). That is the original "
        f"bug: the alarm ran only when a human asked for something else entirely."
    )


def test_the_alarm_reads_its_verdict_from_the_jobs_it_needs():
    """`failure()` in this job reads THIS job's status, which is always success. It must not."""
    name, job = next(iter(_alarm_jobs(_doc()).items()))
    for step in job["steps"]:
        cond = str(step.get("if", ""))
        if not cond:
            continue
        assert not re.fullmatch(r"\$?\{?\{?\s*(failure|success)\(\)\s*\}?\}?", cond.strip()), (
            f"step {step.get('name')!r} in `{name}` is gated on bare `{cond}`, which reads the "
            f"alarm job's own status, not the smoke's. Use `needs.*.result`."
        )
    joined = json.dumps(job["steps"])
    assert "needs.*.result" in joined or "needs.smoke.result" in joined, (
        f"`{name}` never reads a needs result, so its steps cannot tell red from green"
    )


def test_the_alarm_can_actually_write_the_issue():
    """A job block replaces the top-level permissions. This one dropped issues:write for weeks."""
    name, job = next(iter(_alarm_jobs(_doc()).items()))
    perms = job.get("permissions", _doc().get("permissions"))

    assert isinstance(perms, dict) and perms.get("issues") == "write", (
        f"`{name}` has permissions {perms} and calls the Issues API, so every call returns 403 "
        f"'Resource not accessible by integration'. A job-level block REPLACES the top-level one."
    )
