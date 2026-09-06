"""crew#326: scripts/setup_worktree.sh wrote its pre-push shim through
`git rev-parse --git-path hooks`, which honours core.hooksPath, so with the estate router
installed it overwrote ~/.estate/guards/hooks/_router and every commit and push on the
machine was refused (2026-08-23, 2026-08-26 17:06, 2026-08-26 20:55).
Rule: the shim is never written when core.hooksPath is set, and never through a symlink."""
import os
import pathlib
import subprocess

SHIM = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "install_push_shim.sh"


def _repo(tmp_path: pathlib.Path, name: str) -> pathlib.Path:
    r = tmp_path / name
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    return r


def _run(repo: pathlib.Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SHIM)], cwd=repo, env=env, capture_output=True, text=True)


def test_incident_crew326_shim_leaves_the_estate_router_alone(tmp_path):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig")}
    router_dir = tmp_path / "estate-hooks"
    router_dir.mkdir()
    router = router_dir / "_router"
    router.write_text("#!/bin/sh\necho router\n")
    (router_dir / "pre-push").symlink_to(router)
    subprocess.run(["git", "config", "--global", "core.hooksPath", str(router_dir)], env=env, check=True)
    repo = _repo(tmp_path, "with-router")
    r = _run(repo, env)
    assert r.returncode == 0, r.stderr
    assert router.read_text() == "#!/bin/sh\necho router\n"
    assert "not writing a shim" in r.stdout


def test_incident_crew326_shim_is_written_when_no_hookspath(tmp_path):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig")}
    repo = _repo(tmp_path, "plain")
    r = _run(repo, env)
    assert r.returncode == 0, r.stderr
    hook = repo / ".git" / "hooks" / "pre-push"
    assert hook.exists() and os.access(hook, os.X_OK)
    assert "refusing rather than skipping" in hook.read_text()
