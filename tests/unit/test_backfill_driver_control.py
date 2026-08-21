"""The backfill must stop when it is told to, and only one may run at a time.

Both behaviours are regressions from 2026-07-31, when stopping the backfill took three
rounds of kills: TERMing a batch made the driver launch the NEXT batch (the `exit=-15` /
`exit=-9` rows in backfill_all_listings.log), and a second, orphaned backfill from an earlier
run had been grinding for 5h23m into the same log, invisible to a `ps` for the shell.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _fake_repo(tmp_path: Path, n_dossiers: int) -> Path:
    """A store/ skeleton with n PASS dossiers and no listings."""
    (tmp_path / "store" / "dossiers").mkdir(parents=True)
    (tmp_path / "store" / "listings").mkdir(parents=True)
    for i in range(n_dossiers):
        cid = f"{i:016x}"
        (tmp_path / "store" / "dossiers" / f"{cid}.pass.json").write_text(
            json.dumps({"decision": "pass", "candidate": {"candidate_id": cid}})
        )
    return tmp_path


def _install_fake_publisher(tmp_path: Path, body: str) -> None:
    """Stand in for tools.publish_passes so no model or network is touched."""
    pkg = tmp_path / "tools"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "publish_passes.py").write_text(body)


class TestStopsOnSignal:
    def test_sigterm_stops_the_run_instead_of_advancing(self, tmp_path):
        """REGRESSION: the loop used to print `exit=-15` and start the next batch."""
        repo = _fake_repo(tmp_path, 15)  # 3 batches of 5
        _install_fake_publisher(repo, (
            "import sys, time\n"
            "from pathlib import Path\n"
            "Path('batches.log').open('a').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "time.sleep(30)\n"  # long enough that we kill it mid-batch
        ))
        env = {**os.environ, "PYTHONPATH": str(repo), "PROSPECTOR_REPO_ROOT": str(repo)}
        proc = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "tools" / "_backfill_driver.py")],
            cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True,
        )
        # wait until batch 1 is actually running
        deadline = time.time() + 20
        while time.time() < deadline and not (repo / "batches.log").exists():
            time.sleep(0.1)
        assert (repo / "batches.log").exists(), "first batch never started"

        proc.send_signal(signal.SIGTERM)
        out = proc.communicate(timeout=30)[0]

        assert proc.returncode == 130, out
        assert "stopping" in out
        batches = (repo / "batches.log").read_text().strip().splitlines()
        assert len(batches) == 1, f"driver started another batch after SIGTERM: {batches}"

    def test_children_do_not_outlive_the_driver(self, tmp_path):
        repo = _fake_repo(tmp_path, 5)
        _install_fake_publisher(repo, (
            "import os, time\n"
            "from pathlib import Path\n"
            "Path('child.pid').write_text(str(os.getpid()))\n"
            "time.sleep(30)\n"
        ))
        env = {**os.environ, "PYTHONPATH": str(repo), "PROSPECTOR_REPO_ROOT": str(repo)}
        proc = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "tools" / "_backfill_driver.py")],
            cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True,
        )
        # Wait for CONTENT, not for the path -- the same race, and the same fix, as the
        # sh-driver test further down this file. The batch creates child.pid and writes to it as
        # two steps, so `.exists()` goes true while the file is still zero bytes and int() gets
        # "". That was measured once already (ValueError: invalid literal for int() with base 10:
        # '', CI run 32101433859) and only one of the two sites was repaired; this one failed the
        # commit gate on 2026-08-21 under `-n auto` and passes every time on an idle laptop.
        deadline = time.time() + 30
        raw = ""
        while time.time() < deadline:
            try:
                raw = (repo / "child.pid").read_text().strip()
            except OSError:
                raw = ""
            if raw:
                break
            time.sleep(0.1)
        assert raw, "batch child never started"
        child_pid = int(raw)

        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=30)

        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                os.kill(child_pid, 0)
            except OSError:
                break
            time.sleep(0.2)
        else:
            os.kill(child_pid, signal.SIGKILL)
            pytest.fail(f"batch child {child_pid} survived the driver")


class TestNonFatalFailures:
    def test_a_held_back_batch_does_not_abort_the_rest(self, tmp_path):
        """publish_passes exits 1 when a batch listed nothing because every pack was held
        back by the completeness gate. That must not stop later batches."""
        repo = _fake_repo(tmp_path, 12)  # 3 batches
        _install_fake_publisher(repo, (
            "import sys\n"
            "from pathlib import Path\n"
            "Path('batches.log').open('a').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "sys.exit(1)\n"
        ))
        env = {**os.environ, "PYTHONPATH": str(repo), "PROSPECTOR_REPO_ROOT": str(repo)}
        r = subprocess.run(
            [sys.executable, "-u", str(ROOT / "tools" / "_backfill_driver.py")],
            cwd=repo, env=env, capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "done" in r.stdout
        assert len((repo / "batches.log").read_text().strip().splitlines()) == 3


class TestRestartSafety:
    def test_packs_with_a_listing_are_skipped(self, tmp_path):
        repo = _fake_repo(tmp_path, 6)
        already = f"{0:016x}"
        (repo / "store" / "listings" / f"{already}.json").write_text("{}")
        _install_fake_publisher(repo, (
            "import sys\n"
            "from pathlib import Path\n"
            "Path('batches.log').open('a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        ))
        env = {**os.environ, "PYTHONPATH": str(repo), "PROSPECTOR_REPO_ROOT": str(repo)}
        r = subprocess.run(
            [sys.executable, "-u", str(ROOT / "tools" / "_backfill_driver.py")],
            cwd=repo, env=env, capture_output=True, text=True, timeout=60,
        )
        assert "missing=5" in r.stdout
        assert already not in (repo / "batches.log").read_text()

    def test_unreconciled_markers_are_reported(self, tmp_path):
        repo = _fake_repo(tmp_path, 2)
        inflight = repo / "store" / "listings" / ".inflight"
        inflight.mkdir(parents=True)
        (inflight / "deadbeefdeadbeef.json").write_text("{}")
        _install_fake_publisher(repo, "pass\n")
        env = {**os.environ, "PYTHONPATH": str(repo), "PROSPECTOR_REPO_ROOT": str(repo)}
        r = subprocess.run(
            [sys.executable, "-u", str(ROOT / "tools" / "_backfill_driver.py")],
            cwd=repo, env=env, capture_output=True, text=True, timeout=60,
        )
        assert "unreconciled=['deadbeefdeadbeef']" in r.stdout


class TestSingleInstanceLock:
    """REGRESSION: two backfills ran concurrently into one log for hours.

    The lock deliberately lives in the Python driver on fcntl.flock, not in the shell script:
    the flock(1) COMMAND does not exist on macOS, and a shell-level `flock -n 9` there fails
    with 127, which `if ! flock` reads as "already locked" — so every run would have refused
    to start. That is exactly what the first version of this test caught.
    """

    def test_second_driver_refuses_to_start(self, tmp_path):
        repo = _fake_repo(tmp_path, 5)
        _install_fake_publisher(repo, "import time\ntime.sleep(20)\n")
        env = {**os.environ, "PYTHONPATH": str(repo), "PROSPECTOR_REPO_ROOT": str(repo)}
        driver = [sys.executable, "-u", str(ROOT / "tools" / "_backfill_driver.py")]

        first = subprocess.Popen(driver, cwd=repo, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            deadline = time.time() + 20
            while time.time() < deadline and not (repo / "store" / ".backfill_listings.lock").exists():
                time.sleep(0.1)
            time.sleep(1.0)  # let the first driver take the lock

            second = subprocess.run(driver, cwd=repo, env=env, capture_output=True,
                                    text=True, timeout=30)
            assert second.returncode == 3, second.stdout + second.stderr
            assert "already running" in second.stdout
        finally:
            os.killpg(os.getpgid(first.pid), signal.SIGKILL)
            first.wait(timeout=10)

    def test_lock_is_released_when_the_holder_is_sigkilled(self, tmp_path):
        """A pidfile would strand the backfill here; the kernel drops an flock on death."""
        repo = _fake_repo(tmp_path, 5)
        _install_fake_publisher(repo, "import time\ntime.sleep(20)\n")
        env = {**os.environ, "PYTHONPATH": str(repo), "PROSPECTOR_REPO_ROOT": str(repo)}
        driver = [sys.executable, "-u", str(ROOT / "tools" / "_backfill_driver.py")]

        first = subprocess.Popen(driver, cwd=repo, env=env, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + 20
        while time.time() < deadline and not (repo / "store" / ".backfill_listings.lock").exists():
            time.sleep(0.1)
        time.sleep(1.0)
        os.killpg(os.getpgid(first.pid), signal.SIGKILL)
        first.wait(timeout=10)

        _install_fake_publisher(repo, "pass\n")
        second = subprocess.run(driver, cwd=repo, env=env, capture_output=True,
                                text=True, timeout=60)
        assert second.returncode == 0, second.stdout + second.stderr
        assert "already running" not in second.stdout

    def test_lock_is_taken_in_python_not_in_the_shell(self):
        """The lock must stay on fcntl.flock in the driver. See tests/unit/test_shell_portability
        for the repo-wide guard on the flock(1)/setsid(1) trap this came from."""
        assert "fcntl.flock" in (ROOT / "tools" / "_backfill_driver.py").read_text()


class TestShellWrapperStopsTheWholeTree:
    def test_sigterm_to_the_wrapper_kills_driver_and_batch(self, tmp_path):
        """The wrapper must take its whole process group down. Previously killing the shell
        orphaned the driver and the batch (ppid=1) and they kept publishing."""
        repo = _fake_repo(tmp_path, 5)
        (repo / "store" / "control_center" / "runs").mkdir(parents=True)
        _install_fake_publisher(repo, (
            "import os, time\n"
            "from pathlib import Path\n"
            "Path('child.pid').write_text(str(os.getpid()))\n"
            "time.sleep(60)\n"
        ))
        (repo / ".venv" / "bin").mkdir(parents=True)
        os.symlink(sys.executable, repo / ".venv" / "bin" / "python")
        shutil.copy(ROOT / "tools" / "_backfill_driver.py", repo / "tools" / "_backfill_driver.py")
        sh = repo / "tools" / "backfill_missing_listings.sh"
        shutil.copy(ROOT / "tools" / "backfill_missing_listings.sh", sh)
        sh.chmod(0o755)

        # This is the only test that COPIES the driver out of the repo, so it is the only one
        # where `sys.path.insert(parents[1])` lands somewhere with no `prospector` package.
        # In production the driver sits beside it; ROOT on the path restores that, while
        # PROSPECTOR_REPO_ROOT keeps every store/ path pointed at the fake repo.
        env = {**os.environ,
               "PYTHONPATH": os.pathsep.join([str(repo), str(ROOT)]),
               "PROSPECTOR_REPO_ROOT": str(repo)}
        proc = subprocess.Popen(["bash", str(sh)], cwd=repo, env=env, start_new_session=True)
        # Wait for CONTENT, not for the path. The batch creates child.pid and writes to it as
        # two steps, so on a loaded runner this read landed in between and int() got "" --
        # ValueError: invalid literal for int() with base 10: '' in CI run 32101433859, against a
        # test that passes every time on an idle laptop.
        deadline = time.time() + 30
        raw = ""
        while time.time() < deadline:
            try:
                raw = (repo / "child.pid").read_text().strip()
            except OSError:
                raw = ""
            if raw:
                break
            time.sleep(0.1)
        assert raw, "batch never started"
        child_pid = int(raw)

        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=45)

        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                os.kill(child_pid, 0)
            except OSError:
                break
            time.sleep(0.2)
        else:
            os.kill(child_pid, signal.SIGKILL)
            pytest.fail(f"batch child {child_pid} outlived the wrapper")
