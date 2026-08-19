"""`deploy/runners.sh autoscale` decides how much CI capacity is running and costing money.

Three decisions, each with a way to be expensive or destructive if it goes wrong:

  scale up    too few machines and every session waits behind the queue that prompted this.
  scale down  stopping a machine that is mid-job kills a build. The verb must only ever stop a
              machine whose runner GitHub reports as NOT busy.
  no data     if the queue cannot be read, scaling DOWN on that guess is the damaging half, so
              the verb holds and never shrinks.

The script is bash, so the test runs it for real with `fly` and `gh` replaced by stubs on PATH
and reads what it tried to do. Nothing here talks to Fly or GitHub.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNNERS = REPO / "deploy" / "runners.sh"
CFG = REPO / "ops" / "config" / "ci_capacity.yaml"


def _stub_bin(tmp_path: Path, machines: list[dict], busy: list[str], queued: str | None) -> Path:
    """A PATH directory whose `fly` and `gh` answer from fixtures and log every call."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"

    (bin_dir / "fly").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "fly $*" >> {calls}\n'
        "if [ \"$1 $2\" = 'machines list' ]; then\n"
        f"  cat {tmp_path / 'machines.json'}\n"
        "fi\n"
        "exit 0\n"
    )
    # `gh api` with no queue fixture exits non-zero, which is how "cannot read GitHub" is spelled.
    gh = ["#!/usr/bin/env bash", f'echo "gh $*" >> {calls}']
    if queued is None:
        gh.append("case \"$*\" in *actions/runs*) exit 1 ;; esac")
    else:
        gh.append(f"case \"$*\" in *actions/runs*) echo '{queued}'; exit 0 ;; esac")
    gh.append(f"case \"$*\" in *actions/runners*) printf '%s' '{chr(10).join(busy)}'; exit 0 ;; esac")
    gh.append("exit 0")
    (bin_dir / "gh").write_text("\n".join(gh) + "\n")

    for f in ("fly", "gh"):
        (bin_dir / f).chmod(0o755)
    (tmp_path / "machines.json").write_text(json.dumps(machines))
    return bin_dir


def _run(tmp_path: Path, machines, busy, queued) -> tuple[str, str]:
    bin_dir = _stub_bin(tmp_path, machines, busy, queued)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    proc = subprocess.run(["bash", str(RUNNERS), "autoscale"], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    calls = (tmp_path / "calls.log").read_text() if (tmp_path / "calls.log").exists() else ""
    return proc.stdout + proc.stderr, calls


def _machines(started: int, stopped: int) -> list[dict]:
    out = [{"id": f"s{i}", "state": "started"} for i in range(started)]
    out += [{"id": f"z{i}", "state": "stopped"} for i in range(stopped)]
    return out


@pytest.mark.skipif(not RUNNERS.exists(), reason="runners.sh not in this checkout")
def test_a_queue_starts_stopped_machines(tmp_path):
    out, calls = _run(tmp_path, _machines(started=1, stopped=2), busy=[], queued="3")
    assert "want=3" in out, out
    assert "machine start z0" in calls, calls
    assert "machine start z1" in calls, calls
    assert "machine stop" not in calls, calls


@pytest.mark.skipif(not RUNNERS.exists(), reason="runners.sh not in this checkout")
def test_an_empty_queue_stops_idle_machines_but_never_a_busy_one(tmp_path):
    # s0 is mid-job. Stopping it kills a build, so the verb must walk past it and stop s1.
    # The floor comes from the config, not from a number typed here: autoscale_min moves when the
    # fleet is resized, and a hardcoded 1 would then fail for a reason that has nothing to do with
    # the behaviour under test.
    lo = int(re.search(r"^autoscale_min:\s*(\d+)", CFG.read_text(), re.M).group(1))
    out, calls = _run(tmp_path, _machines(started=lo + 2, stopped=0), busy=["runner-s0"], queued="0")
    assert f"want={lo}" in out, out
    assert "machine stop s0" not in calls, calls     # busy, so it must be walked past
    assert "machine stop s1" in calls, calls


@pytest.mark.skipif(not RUNNERS.exists(), reason="runners.sh not in this checkout")
def test_an_unreadable_queue_never_scales_down(tmp_path):
    out, calls = _run(tmp_path, _machines(started=3, stopped=0), busy=[], queued=None)
    assert "could not read the queue" in out, out
    assert "machine stop" not in calls, calls


@pytest.mark.skipif(not RUNNERS.exists(), reason="runners.sh not in this checkout")
def test_the_ceiling_is_the_config_not_the_queue(tmp_path):
    # A 50-run pile-up must not start 50 machines. The ceiling is ops/config/ci_capacity.yaml.
    cfg = CFG.read_text()
    want_max = int(re.search(r"^autoscale_max:\s*(\d+)", cfg, re.M).group(1))
    out, _ = _run(tmp_path, _machines(started=0, stopped=10), busy=[], queued="50")
    assert f"want={want_max}" in out, out
