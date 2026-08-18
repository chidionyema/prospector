"""Production must be able to say which commit it is running, on the platform it runs on.

The laptop probe answered this by reading a git checkout. On 2026-08-18 production moved to
Fly, where there is no checkout: `COPY . /app` does not bring `.git`, so the running engine
knew nothing about its own version and neither did anything else. `fly releases` showed v15
and no file on this estate mapped v15 to a commit.

Two halves are pinned here. The image must carry a stamp, and the probe must read it and
grade it rather than grading a laptop directory production no longer uses.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "live_checkout.py"
DOCKERFILE = REPO / "deploy" / "engine" / "Dockerfile"
FLY_SH = REPO / "deploy" / "targets" / "fly.sh"


@pytest.fixture(scope="module")
def lc():
    if not SCRIPT.exists():
        pytest.skip("scripts/live_checkout.py is not in this checkout")
    spec = importlib.util.spec_from_file_location("live_checkout_ver", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTheImageCarriesItsCommit:
    def test_the_dockerfile_writes_the_stamp_the_probe_reads(self):
        """The two halves must name the same path, or the probe reads nothing forever."""
        body = DOCKERFILE.read_text(encoding="utf-8")
        assert "ARG GIT_SHA" in body, "no GIT_SHA build argument in the engine image"
        assert "/app/GIT_SHA" in body, "the image never writes the stamp file"

    def test_the_deploy_passes_the_commit(self):
        """A stamp nothing fills in is worse than none: it reads as a confident 'unknown'."""
        body = FLY_SH.read_text(encoding="utf-8")
        assert "--build-arg" in body and "GIT_SHA=" in body, (
            "deploy/targets/fly.sh releases without stamping the commit"
        )
        assert "rev-parse HEAD" in body

    def test_the_probe_reads_the_same_path_the_image_writes(self, lc):
        assert str(lc.IMAGE_STAMP) == "/app/GIT_SHA"


class TestReadingTheDeployedCommit:
    def test_a_stamp_inside_the_container_is_read_without_shelling_out(self, lc, monkeypatch,
                                                                      tmp_path):
        """The ops console runs INSIDE the image, so its button must not need `fly ssh`."""
        stamp = tmp_path / "GIT_SHA"
        stamp.write_text("a" * 40 + "\n")
        monkeypatch.setattr(lc, "IMAGE_STAMP", stamp)
        monkeypatch.setattr(lc, "run", lambda *a, **k: pytest.fail("shelled out to fly"))
        sha, how = lc.deployed_commit()
        assert sha == "a" * 40
        assert "container" in how

    def test_the_sha_is_matched_not_sliced_out_of_fly_ssh_noise(self, lc, monkeypatch, tmp_path):
        """`fly ssh console` writes `Connecting to fdaa:73:...` on stderr and run() merges it."""
        monkeypatch.setattr(lc, "IMAGE_STAMP", tmp_path / "absent")
        monkeypatch.setattr(lc.shutil, "which", lambda _n: "/usr/local/bin/fly")
        noise = "Connecting to fdaa:73:9c1f:a7b:1f0:2c4e:1234:2... complete\n" + "b" * 40 + "\n"
        monkeypatch.setattr(lc, "run", lambda *a, **k: (0, noise))
        sha, _how = lc.deployed_commit()
        assert sha == "b" * 40

    def test_a_dirty_build_is_reported_as_dirty(self, lc, monkeypatch, tmp_path):
        monkeypatch.setattr(lc, "IMAGE_STAMP", tmp_path / "absent")
        monkeypatch.setattr(lc.shutil, "which", lambda _n: "/usr/local/bin/fly")
        monkeypatch.setattr(lc, "run", lambda *a, **k: (0, "c" * 40 + "-dirty\n"))
        sha, _how = lc.deployed_commit()
        assert sha == "c" * 40 + "-dirty"

    def test_an_image_built_before_stamping_says_so(self, lc, monkeypatch, tmp_path):
        """Silence here would read as a healthy deploy. It is the opposite."""
        monkeypatch.setattr(lc, "IMAGE_STAMP", tmp_path / "absent")
        monkeypatch.setattr(lc.shutil, "which", lambda _n: "/usr/local/bin/fly")
        monkeypatch.setattr(
            lc, "run", lambda *a, **k: (1, "cat: /app/GIT_SHA: No such file or directory"))
        sha, how = lc.deployed_commit()
        assert sha == ""
        assert "predates commit stamping" in how


class TestTheProbeGradesTheActivePlatform:
    def _fly(self, lc, monkeypatch):
        monkeypatch.setattr(lc, "active_side", lambda: "fly")

    def test_report_on_fly_does_not_grade_the_laptop_checkout(self, lc, monkeypatch, capsys):
        """The bug this fixes: a missing standby directory was the whole verdict.

        Production was up, on a commit nobody could name, and the probe exited 1 saying
        `MISSING: /Users/chidionyema/Documents/code/prospector-live`.
        """
        self._fly(lc, monkeypatch)
        monkeypatch.setattr(lc, "fly_machine_state", lambda: "started")
        monkeypatch.setattr(lc, "deployed_commit", lambda: ("d" * 40, "read over fly ssh"))
        monkeypatch.setattr(lc, "ci_verdict", lambda _sha: ("pass", "6 run(s) green"))
        monkeypatch.setattr(lc, "DEV", Path("/nonexistent-dev-checkout"))
        monkeypatch.setattr(lc, "DEPLOY_SOURCE", Path("/nonexistent-standby"))
        rc = lc.report()
        out = capsys.readouterr().out
        assert "d" * 40 in out
        assert rc == 0, "a missing laptop standby must not fail a healthy Fly deployment"

    def test_a_commit_nobody_can_name_is_a_problem(self, lc, monkeypatch, capsys):
        self._fly(lc, monkeypatch)
        monkeypatch.setattr(lc, "fly_machine_state", lambda: "started")
        monkeypatch.setattr(lc, "deployed_commit", lambda: ("", "no stamp"))
        monkeypatch.setattr(lc, "DEV", Path("/nonexistent-dev-checkout"))
        monkeypatch.setattr(lc, "DEPLOY_SOURCE", Path("/nonexistent-standby"))
        assert lc.report() == 1
        assert "cannot tell which commit production runs" in capsys.readouterr().out

    def test_a_stopped_machine_is_a_problem(self, lc, monkeypatch, capsys):
        self._fly(lc, monkeypatch)
        monkeypatch.setattr(lc, "fly_machine_state", lambda: "stopped")
        monkeypatch.setattr(lc, "deployed_commit", lambda: ("e" * 40, "read over fly ssh"))
        monkeypatch.setattr(lc, "ci_verdict", lambda _sha: ("pass", "green"))
        monkeypatch.setattr(lc, "DEV", Path("/nonexistent-dev-checkout"))
        monkeypatch.setattr(lc, "DEPLOY_SOURCE", Path("/nonexistent-standby"))
        assert lc.report() == 1
        assert "not started" in capsys.readouterr().out


class TestUpdateDeploysToTheActivePlatform:
    def test_update_on_fly_refuses_when_there_is_nothing_clean_to_build_from(
            self, lc, monkeypatch, capsys):
        """`fly deploy` uploads a working tree. Building from a random branch ships it."""
        monkeypatch.setattr(lc, "active_side", lambda: "fly")
        monkeypatch.setattr(lc, "DEPLOY_SOURCE", Path("/nonexistent-standby"))
        assert lc.update() == 1
        assert "nothing to build from" in capsys.readouterr().out

    def test_update_on_fly_never_touches_the_laptop_launchd_jobs(self, lc, monkeypatch):
        monkeypatch.setattr(lc, "active_side", lambda: "fly")
        monkeypatch.setattr(lc, "DEPLOY_SOURCE", Path("/nonexistent-standby"))
        monkeypatch.setattr(
            lc, "run", lambda *a, **k: pytest.fail("ran a command on the laptop side"))
        assert lc.update() == 1
