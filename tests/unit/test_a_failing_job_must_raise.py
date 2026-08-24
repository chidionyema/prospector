"""A scheduled job that fails must reach a person, and must leave a receipt that it tried.

Step 2 of `docs/LOGGING_AND_RETENTION.md`. The design doc said "nothing alerts when a launchd job
exits non-zero". Measured on 2026-08-20 that was half right, and the half it got wrong is the
interesting half: `scripts/process_audit.py` already grades every scheduled job on this Mac AND
every supervisord program inside `prospector-engine` (`grade_fly`), and it already had an
`--alert` flag. The rail existed. It just could not fire.

`alert()` imported `~/.hermes/scripts/estate_alert.py`, which lives outside this repository. On a
host with no Hermes checkout the import raised, the function returned the string
`could not alert: No module named estate_alert`, and nothing anywhere graded that string. The
audit printed it, exited 1 for the findings, and the estate went on being reported as watched.
That is the same class as a workflow that can never run: the failure looks like ordinary output.

Measured evidence that the class is real, taken the same day:

    launchctl list | grep prospector
      -> com.prospector.backup          last exit 78
      -> com.prospector.process-audit   last exit 2
    tail store/backup.log
      -> FileNotFoundError ... store/dossiers/d0dc386eb8f7934f.defer.json
      -> last STORE_BACKUP PASS is dated 2026-08-17

Three days of a failing nightly backup, and the only place it was written down was a log file
nobody opens.

So these tests do not check that a notification was delivered — no test can promise that, and a
test that mocked a sink into returning True would be testing the mock. They check the one thing
that must survive every sink being absent: a DURABLE RECORD that the estate was failing at this
time, written before any sink is attempted, with the names of what failed in it.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.process_audit as pa
from prospector.scheduler import alerts


@pytest.fixture
def cfg(tmp_path):
    """A config double whose alert path writes to tmp, never to the real store."""
    return SimpleNamespace(store_dir=tmp_path)


@pytest.fixture(autouse=True)
def _no_real_sinks(monkeypatch):
    """No desktop banner, no webhook, no Telegram message out of a test run.

    This is also the condition under test: with every sink neutralised, the durable record is
    the ONLY thing left, which is exactly the state a host without Hermes is permanently in.
    """
    monkeypatch.setattr(alerts, "_desktop_notify", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "_webhook_post", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "_telegram_push", lambda *a, **k: None)


def _payload(*rows, failing=None):
    """An audit payload in the shape `main()` builds for `--json`."""
    return {"failing": failing if failing is not None else sum(1 for g, _, _ in rows if g == pa.BAD),
            "sections": [{"rows": [{"grade": g, "name": n, "detail": d} for g, n, d in rows]}]}


def _records(tmp_path):
    path = tmp_path / "scheduler" / "alerts.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_a_failing_audit_leaves_a_durable_record_with_no_sinks_at_all(cfg, tmp_path):
    """The regression. This is what returned a string and wrote nothing."""
    out = pa.alert(_payload((pa.BAD, "com.prospector.backup", "last exit 78")), cfg=cfg)

    records = _records(tmp_path)
    assert len(records) == 1, f"expected one durable alert record, got {records}; said: {out}"
    assert records[0]["key"] == "process-audit"
    assert records[0]["severity"] == "critical"


def test_the_record_names_what_failed_so_nobody_has_to_open_a_console(cfg, tmp_path):
    """An alert saying "1 failing" sends someone to a dashboard. Name it in the alert."""
    pa.alert(_payload((pa.BAD, "com.prospector.backup", "last exit 78"),
                      (pa.BAD, "prospector-engine/consumer", "FATAL"),
                      (pa.OK, "prospector-engine/scheduler", "RUNNING")), cfg=cfg)

    rec = _records(tmp_path)[0]
    assert rec["failing"] == 2
    assert "com.prospector.backup" in rec["checks"]
    assert "prospector-engine/consumer" in rec["checks"]
    assert "prospector-engine/scheduler" not in rec["checks"], "a passing check is not a failure"
    assert "last exit 78" in rec["message"], "the detail is what tells the operator what to do"


def test_a_clean_audit_raises_nothing(cfg, tmp_path):
    """The empty case. A quiet estate must not page, and must not write a record either."""
    out = pa.alert(_payload((pa.OK, "com.prospector.backup", "ok"),
                            (pa.WARN, "some-workflow", "late")), cfg=cfg)

    assert out == "nothing to alert"
    assert _records(tmp_path) == []


def test_a_warning_is_not_an_alert(cfg, tmp_path):
    """WARN exists so that not everything pages. If WARN paged, nothing would be read."""
    pa.alert(_payload((pa.WARN, "worktree drift", "11 commits behind")), cfg=cfg)
    assert _records(tmp_path) == []


def test_a_broken_alert_path_says_so_in_words_nobody_reads_as_success(cfg, monkeypatch):
    """The defect being closed, stated as a test.

    The old function's failure string was `could not alert: ...` -- lowercase, mild, and printed
    among ordinary audit output. The replacement has to be unmistakable, because this string is
    the ONLY signal left when the alert path itself is down.
    """
    def _explode(*a, **k):
        raise RuntimeError("sink is down")
    monkeypatch.setattr(alerts, "emit_alert", _explode)

    out = pa.alert(_payload((pa.BAD, "com.prospector.backup", "last exit 78")), cfg=cfg)

    assert "ALERT PATH BROKEN" in out
    assert "went unsent" in out
    assert "RuntimeError" in out, "name the failure, so the next reader does not have to guess"


def test_observing_a_job_can_never_fail_it(cfg, monkeypatch):
    """`alert()` runs inside a scheduled job. If it raises, it turns a report into an outage.

    `ImportError` is the specific one to pin: it is what actually happened for months, because
    the old implementation reached for a module in another project's checkout. `OSError` covers
    the other real shape, a store directory that cannot be written.

    Deliberately NOT covered: `KeyboardInterrupt` and friends. They are `BaseException`, they are
    not caught here, and they must not be -- a rail that swallows Ctrl-C is a worse bug than the
    one this test guards.
    """
    for boom in (ImportError("No module named estate_alert"), OSError("read-only file system")):
        def _explode(*a, _boom=boom, **k):
            raise _boom
        monkeypatch.setattr(alerts, "emit_alert", _explode)

        # No pytest.raises: the assertion is that this line returns at all.
        out = pa.alert(_payload((pa.BAD, "x", "y")), cfg=cfg)
        assert "ALERT PATH BROKEN" in out, f"{type(boom).__name__} was not contained"


def test_the_alert_does_not_depend_on_a_checkout_outside_this_repo(cfg, tmp_path, monkeypatch):
    """Production runs on prospector-engine, where ~/.hermes does not exist.

    Simulated by making the Hermes sender unimportable. The old code took its whole alert path
    through that import; the record below has to appear anyway.
    """
    monkeypatch.setattr(alerts, "_load_hermes_sender", lambda: None)
    pa.alert(_payload((pa.BAD, "prospector-engine/backup", "EXITED")), cfg=cfg)

    assert len(_records(tmp_path)) == 1, "an alert must not need a checkout of another project"
