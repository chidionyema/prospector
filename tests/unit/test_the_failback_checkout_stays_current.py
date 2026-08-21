"""The failover target must be current, and its currency must be visible.

Measured 2026-08-21: `/Users/chidionyema/Documents/code/prospector-live` was 81 commits
behind origin/main while it WAS the failover target, and every screen in the estate read
green. Three independent causes, one test each here:

  1. `fly_update` returned on "already deployed" BEFORE the checkout move. Once deploys
     started coming from the Deploy Engine workflow on a runner, Fly advanced on its own and
     that early return became the only branch that ever ran, so the checkout stopped moving.
  2. `t_stop` disabled every com.prospector.* job including the one whose whole purpose is to
     roll the failback checkout forward. `launchctl disable` is persistent and only `t_start`
     lifts it, so a migration that SUCCEEDS never re-enables it -- the follower dies at the
     exact moment the cutover works.
  3. `probe_standby()` measured money-file age only and its docstring called that number "the
     exposure". No code-drift figure existed anywhere in the estate, so nothing could report
     the 81.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(cwd),
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


def _estate(tmp_path: Path) -> tuple[Path, str, str]:
    """A bare origin, a clone one commit behind it. Returns (clone, old_sha, new_sha)."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git("init", "--bare", "-b", "main", ".", cwd=origin)

    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", "-b", "main", ".", cwd=seed)
    (seed / "a.txt").write_text("one\n")
    _git("add", "a.txt", cwd=seed)
    _git("commit", "-m", "one", cwd=seed)
    _git("remote", "add", "origin", str(origin), cwd=seed)
    _git("push", "-u", "origin", "main", cwd=seed)
    old = _git("rev-parse", "HEAD", cwd=seed).stdout.strip()

    clone = tmp_path / "live"
    _git("clone", str(origin), str(clone), cwd=tmp_path)

    (seed / "a.txt").write_text("two\n")
    _git("commit", "-am", "two", cwd=seed)
    _git("push", "origin", "main", cwd=seed)
    new = _git("rev-parse", "HEAD", cwd=seed).stdout.strip()

    assert old != new
    return clone, old, new


# ---------------------------------------------------------------- cause 1: the early return

def test_already_deployed_still_advances_the_failback_checkout(tmp_path, monkeypatch, capsys):
    """Fly already serving `target` is exactly when the checkout is silently left behind.

    The old code printed "already deployed" and returned. Everything it said was true, and
    the checkout it would fail back to stayed where it was, forever.
    """
    lc = _load("live_checkout")
    clone, old, new = _estate(tmp_path)

    monkeypatch.setattr(lc, "DEPLOY_SOURCE", clone)
    monkeypatch.setattr(lc, "NO_AUTO_UPDATE", tmp_path / "never-exists")
    monkeypatch.setattr(lc, "deployed_commit", lambda: (new, "probe"))
    monkeypatch.setattr(lc, "fly_report", lambda: 0)

    assert _git("rev-parse", "HEAD", cwd=clone).stdout.strip() == old

    rc = lc.fly_update()

    assert rc == 0
    assert "already deployed" in capsys.readouterr().out
    assert _git("rev-parse", "HEAD", cwd=clone).stdout.strip() == new, (
        "Fly is on `new` and the failback checkout is still on `old`, so a failover would "
        "roll production back. This is the 81-commit defect."
    )


def test_a_failed_checkout_move_does_not_fail_the_deploy_report(tmp_path, monkeypatch, capsys):
    """The move is best-effort. Fly is already serving the right commit either way.

    Two ways it can fail and neither may raise: the checkout is gone (run() only catches
    TimeoutExpired, so a missing cwd comes out of the subprocess layer), or git refuses the
    target.
    """
    lc = _load("live_checkout")

    monkeypatch.setattr(lc, "DEPLOY_SOURCE", tmp_path / "not-a-repo")
    lc._sync_failback_checkout("0" * 40)
    assert "WARNING" in capsys.readouterr().out

    clone, _, _ = _estate(tmp_path)
    monkeypatch.setattr(lc, "DEPLOY_SOURCE", clone)
    lc._sync_failback_checkout("0" * 40)
    out = capsys.readouterr().out
    assert "WARNING" in out and "still at" in out


# ------------------------------------------------------- cause 2: the persistent disable

def _disable_list(tmp_path: Path, labels: list[str]) -> list[str]:
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    for label in labels:
        (agents / f"{label}.plist").write_text("<plist/>\n")
    out = subprocess.run(
        ["bash", "-c",
         f'source "{ROOT}/deploy/targets/laptop.sh"; AGENTS="{agents}"; _labels_to_disable'],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.split()


def test_the_disable_sweep_spares_the_job_that_rolls_the_checkout_forward(tmp_path):
    labels = ["com.prospector.scheduler", "com.prospector.live-update",
              "com.prospector.watchdog"]
    got = _disable_list(tmp_path, labels)
    assert "com.prospector.live-update" not in got, (
        "`launchctl disable` is persistent and only t_start lifts it. A migration that "
        "SUCCEEDS never calls t_start, so disabling live-update here stops the failback "
        "checkout being rolled forward from the moment the cutover works."
    )


def test_the_disable_sweep_still_disables_every_writer(tmp_path):
    """The exemption must be one label, not a hole. Both halves or neither."""
    labels = ["com.prospector.scheduler", "com.prospector.live-update",
              "com.prospector.watchdog", "com.prospector.consumer"]
    got = _disable_list(tmp_path, labels)
    assert set(got) == {"com.prospector.scheduler", "com.prospector.watchdog",
                        "com.prospector.consumer"}


# ------------------------------------------------------------- cause 3: the blind instrument

def test_probe_standby_code_reports_the_commits_behind(tmp_path, monkeypatch):
    ef = _load("engine_failover")
    clone, old, new = _estate(tmp_path)
    monkeypatch.setattr(ef, "STANDBY_CHECKOUT", clone)

    code = ef.probe_standby_code()
    assert code.get("error") is None, code
    assert code["behind"] == 0, "clone is at origin/main as fetched; nothing to catch up on"

    _git("fetch", "origin", "main:refs/remotes/origin/main", cwd=clone)
    code = ef.probe_standby_code()
    assert code["behind"] == 1
    assert code["head"] == old[: len(code["head"])]


def test_ref_age_is_none_rather_than_a_number_when_nothing_ever_fetched(tmp_path, monkeypatch):
    """behind=0 against an unfetched ref is the trap. It must be reported, not smoothed."""
    ef = _load("engine_failover")
    clone, _, _ = _estate(tmp_path)
    (clone / ".git" / "FETCH_HEAD").unlink(missing_ok=True)
    monkeypatch.setattr(ef, "STANDBY_CHECKOUT", clone)
    assert ef.probe_standby_code()["ref_age_min"] is None


def test_a_missing_checkout_is_an_error_not_a_zero(tmp_path, monkeypatch):
    ef = _load("engine_failover")
    monkeypatch.setattr(ef, "STANDBY_CHECKOUT", tmp_path / "gone")
    code = ef.probe_standby_code()
    assert "error" in code and "behind" not in code


def test_probe_standby_carries_the_code_axis(tmp_path, monkeypatch):
    ef = _load("engine_failover")
    monkeypatch.setattr(ef, "STANDBY", tmp_path / "standby")
    monkeypatch.setattr(ef, "STANDBY_CHECKOUT", tmp_path / "gone")
    assert "code" in ef.probe_standby()


def test_code_drift_never_makes_the_standby_unusable(tmp_path, monkeypatch):
    """Failing over 81 commits behind beats staying down. That call is the operator's."""
    ef = _load("engine_failover")
    standby = tmp_path / "standby"
    standby.mkdir()
    for name in ef.MONEY_FILES:
        (standby / name).write_text("x")
    monkeypatch.setattr(ef, "STANDBY", standby)
    monkeypatch.setattr(ef, "STANDBY_CHECKOUT", tmp_path / "gone")
    out = ef.probe_standby()
    assert out["usable"] is True
    assert "error" in out["code"]


@pytest.mark.parametrize(
    "code,expect_ok",
    [
        ({"behind": 0, "head": "abc1234", "ref_age_min": 3.0}, True),
        ({"behind": 0, "head": "abc1234", "ref_age_min": 4300.0}, False),
        ({"behind": 0, "head": "abc1234", "ref_age_min": None}, False),
        ({"behind": 81, "head": "abc1234", "ref_age_min": 1.0}, False),
    ],
)
def test_zero_behind_only_reads_ok_when_the_ref_is_fresh(code, expect_ok):
    ef = _load("engine_failover")
    line = ef.standby_code_line(code)
    assert (" OK " in line) is expect_ok, line


def test_an_unreadable_code_axis_says_so_out_loud():
    ef = _load("engine_failover")
    assert "UNKNOWN" in ef.standby_code_line({"error": "no checkout at /nope"})


# --- cause 3, one level down: the drift figure existed for the CHECKOUT, not for the code that
# --- actually runs. Measured 2026-08-21: ~/.prospector/bin/engine_failover.frozen.py was the
# --- 2026-08-18 copy, 594 lines behind scripts/engine_failover.py, so commit 3f7550e5 (refuse a
# --- standby pull that did not reach the end of the source) was merged and never reached the job
# --- doing the pulling. Three short pulls were promoted and the standby spend ledger fell to
# --- 1,572,864 bytes against a source of 454,701,248. `standby CODE:` read OK the whole time.


@pytest.mark.parametrize(
    "run,expect_ok",
    [
        ({"same_file": True, "running": "/repo/scripts/engine_failover.py"}, True),
        ({"same_file": False, "digest": "aaaaaaaaaaaa", "checkout_digest": "aaaaaaaaaaaa"}, True),
        ({"same_file": False, "digest": "aaaaaaaaaaaa", "checkout_digest": "bbbbbbbbbbbb"}, False),
        ({"error": "no such file"}, False),
    ],
)
def test_a_frozen_copy_that_differs_from_the_checkout_never_reads_ok(run, expect_ok):
    ef = _load("engine_failover")
    line = ef.running_code_line(run)
    assert (" OK " in line) is expect_ok, line


def test_the_drifted_copy_names_the_command_that_fixes_it():
    """A red line an operator cannot act on gets muted. This one carries its own remedy."""
    ef = _load("engine_failover")
    line = ef.running_code_line(
        {"same_file": False, "digest": "aaaaaaaaaaaa", "checkout_digest": "bbbbbbbbbbbb"})
    assert "install_failover_watch.sh" in line, line


def test_the_running_copy_is_compared_by_content_not_by_mtime(tmp_path, monkeypatch):
    """Two bytes-identical files with different timestamps are the SAME code.

    Grading a copy by its mtime is the proxy this estate keeps paying for: it goes red on a
    harmless `cp` and green on a file edited in place. The probe hashes the bytes.

    Built entirely in tmp_path, deliberately. The first version of this test asserted on the
    real STANDBY_CHECKOUT, which is a laptop path (`engine_failover.py:76`); CI runs the repo at
    /home/runner/_work and the test went red for the host it ran on rather than for the code.
    """
    ef = _load("engine_failover")
    mirror_dir = tmp_path / "checkout" / "scripts"
    mirror_dir.mkdir(parents=True)
    mirror = mirror_dir / "engine_failover.py"
    running = Path(ef.__file__)
    mirror.write_bytes(running.read_bytes())
    # Same bytes, an hour apart. mtime is the proxy; content is the answer.
    os.utime(mirror, (0, 0))
    monkeypatch.setattr(ef, "STANDBY_CHECKOUT", tmp_path / "checkout")

    probe = ef.probe_running_code()
    assert probe.get("error") is None, probe
    assert probe.get("same_file") is False, probe
    assert probe["digest"] == probe["checkout_digest"], probe
    assert " OK " in ef.running_code_line(probe), probe

    # And a real difference still reads as drift, so the test above is not passing by accident.
    mirror.write_bytes(running.read_bytes() + b"\n# drift\n")
    drifted = ef.probe_running_code()
    assert drifted["digest"] != drifted["checkout_digest"], drifted
    assert "!!" in ef.running_code_line(drifted), drifted


def test_status_actually_prints_the_running_code_line():
    """Wiring, not behaviour. A correct helper nothing calls is the exact shape of cause 3:
    the number was computable and never printed for the whole of the period it was wrong."""
    body = (ROOT / "scripts" / "engine_failover.py").read_text()
    assert "running_code_line(" in body.split("def cmd_status", 1)[-1] or \
        body.count("running_code_line(") >= 2, "status never renders the line it computes"


def test_t_stop_actually_uses_the_sparing_list():
    """Wiring, not behaviour: t_stop cannot be run in a test without stopping the estate.

    The behaviour of `_labels_to_disable` is graded above. This asserts the caller reaches it,
    because a correct helper that nothing calls is exactly the shape the original defect had.
    """
    body = (ROOT / "deploy" / "targets" / "laptop.sh").read_text()
    t_stop = body.split("t_stop()", 1)[1].split("\nt_", 1)[0]
    assert "_labels_to_disable" in t_stop
    assert "in $(_plist_labels)" not in t_stop, (
        "t_stop is disabling every plist again, including live-update"
    )
