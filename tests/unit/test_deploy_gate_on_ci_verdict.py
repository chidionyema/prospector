"""Production must not ship a commit CI never passed.

On 2026-08-17 four merges landed on main between 20:11 and 20:36. Three of their CI runs
were cancelled by the next merge landing on top; the one run that reached a verdict
concluded failure. Main's tip `5b8d010` had ZERO check runs against it, and the follower
shipped it to production within 60 seconds. There is no branch protection on this repo to
stop any of that (403 on both `/branches/main/protection` and `/rulesets`), so the gate has
to live in the follower.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "live_checkout.py"


def _load():
    spec = importlib.util.spec_from_file_location("live_checkout", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def lc():
    return _load()


def _rows(*triples: tuple[str, str, str]) -> str:
    return "\n".join("\t".join(t) for t in triples)


FULL_SHA = "5b8d0106d4223a83dbce19c765385d571454c0dc"


def _stub_gh(lc, monkeypatch, rc: int, out: str, *, present: bool = True):
    monkeypatch.setattr(lc.shutil, "which", lambda _: "/usr/bin/gh" if present else None)

    def fake(cmd, cwd=None, timeout=30):
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, FULL_SHA
        return rc, out

    monkeypatch.setattr(lc, "run", fake)


# --------------------------------------------------------------------------- ci_verdict

def test_all_green_is_a_pass(lc, monkeypatch):
    _stub_gh(lc, monkeypatch, 0, _rows(("python", "completed", "success"),
                                       ("web", "completed", "success")))
    assert lc.ci_verdict("deadbeef")[0] == "pass"


def test_a_failure_is_a_fail(lc, monkeypatch):
    _stub_gh(lc, monkeypatch, 0, _rows(("python", "completed", "failure"),
                                       ("web", "completed", "success")))
    verdict, detail = lc.ci_verdict("deadbeef")
    assert verdict == "fail"
    assert "python=failure" in detail


def test_a_cancelled_run_is_a_fail_not_a_pass(lc, monkeypatch):
    """The exact 2026-08-17 shape: the next merge cancelled this one's run."""
    _stub_gh(lc, monkeypatch, 0, _rows(("python", "completed", "cancelled")))
    assert lc.ci_verdict("deadbeef")[0] == "fail"


def test_still_running_is_pending(lc, monkeypatch):
    _stub_gh(lc, monkeypatch, 0, _rows(("python", "in_progress", "None"),
                                       ("web", "completed", "success")))
    verdict, detail = lc.ci_verdict("deadbeef")
    assert verdict == "pending"
    assert "python" in detail


def test_no_run_at_all_is_none_not_pass(lc, monkeypatch):
    """A commit nobody tested. Empty must never read as clean."""
    _stub_gh(lc, monkeypatch, 0, "")
    assert lc.ci_verdict("5b8d010")[0] == "none"


def test_a_queued_run_is_pending_not_none(lc, monkeypatch):
    """5b8d010's run was QUEUED. It had no check runs, which is why this gate reads
    actions/runs — "wait 60s" and "never tested" must not collapse into one answer."""
    _stub_gh(lc, monkeypatch, 0, _rows(("CI", "queued", "None")))
    assert lc.ci_verdict("5b8d010")[0] == "pending"


def test_deploy_and_smoke_runs_are_ignored(lc, monkeypatch):
    """They run after the merge and describe the deployment, not the code."""
    _stub_gh(lc, monkeypatch, 0, _rows(("CI", "completed", "success"),
                                       ("deploy-api", "queued", "None"),
                                       ("e2e live smoke", "completed", "failure")))
    assert lc.ci_verdict("deadbeef")[0] == "pass"


def test_only_ignored_runs_is_none_not_pass(lc, monkeypatch):
    _stub_gh(lc, monkeypatch, 0, _rows(("deploy-web", "completed", "success")))
    assert lc.ci_verdict("deadbeef")[0] == "none"


def test_a_short_sha_is_expanded_before_the_query(lc, monkeypatch):
    """`head_sha` matches on 40 characters and returns an empty list for an abbreviation,
    with rc 0. Unexpanded, every short sha would read as "never tested"."""
    seen: list[str] = []
    monkeypatch.setattr(lc.shutil, "which", lambda _: "/usr/bin/gh")

    def fake(cmd, cwd=None, timeout=30):
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, FULL_SHA
        seen.append(" ".join(cmd))
        return 0, _rows(("CI", "completed", "success"))

    monkeypatch.setattr(lc, "run", fake)

    assert lc.ci_verdict("5b8d010")[0] == "pass"
    assert f"head_sha={FULL_SHA}" in seen[0]


def test_an_unresolvable_sha_is_unknown(lc, monkeypatch):
    monkeypatch.setattr(lc.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(lc, "run", lambda *a, **k: (128, "unknown revision"))
    assert lc.ci_verdict("nosuch")[0] == "unknown"


def test_gh_missing_is_unknown(lc, monkeypatch):
    _stub_gh(lc, monkeypatch, 0, "", present=False)
    assert lc.ci_verdict("deadbeef")[0] == "unknown"


def test_gh_api_error_is_unknown(lc, monkeypatch):
    _stub_gh(lc, monkeypatch, 1, "HTTP 502")
    assert lc.ci_verdict("deadbeef")[0] == "unknown"


def test_a_renamed_workflow_is_still_judged(lc, monkeypatch):
    """The ignore list is a deny list, so a rename cannot silently drop a red run."""
    _stub_gh(lc, monkeypatch, 0, _rows(("Renamed Suite", "completed", "failure")))
    assert lc.ci_verdict("deadbeef")[0] == "fail"


# ------------------------------------------------------------------------------ update

class _Fake:
    """Records what update() ran, and answers the git calls it makes."""

    def __init__(self, target: str, current: str):
        self.target, self.current = target, current
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd=None, timeout=30):
        self.calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[-1]
            sha = self.target if ref == "origin/main" else self.current
            return 0, sha[:7] if "--short" in cmd else sha
        return 0, ""

    @property
    def checked_out(self) -> bool:
        return any(c[:2] == ["git", "checkout"] for c in self.calls)


def _arm(lc, monkeypatch, tmp_path, verdict: str, *, bypass: bool = False):
    monkeypatch.setattr(lc, "LIVE", tmp_path / "live")
    (tmp_path / "live").mkdir()
    monkeypatch.setattr(lc, "NO_AUTO_UPDATE", tmp_path / "NO_AUTO_UPDATE")
    allow = tmp_path / "ALLOW_UNVERIFIED_DEPLOY"
    if bypass:
        allow.write_text("")
    monkeypatch.setattr(lc, "ALLOW_UNVERIFIED_DEPLOY", allow)
    monkeypatch.setattr(lc, "_code_changes", lambda _: [])
    monkeypatch.setattr(lc, "ci_verdict", lambda sha: (verdict, "stubbed"))
    monkeypatch.setattr(lc, "report", lambda: 0)
    fake = _Fake(target="b" * 40, current="a" * 40)
    monkeypatch.setattr(lc, "run", fake)
    return fake


@pytest.mark.parametrize("verdict", ["fail", "none", "pending", "unknown"])
def test_update_refuses_to_ship_a_commit_without_a_green_verdict(
        lc, monkeypatch, tmp_path, verdict):
    fake = _arm(lc, monkeypatch, tmp_path, verdict)
    assert lc.update(unattended=True) == 1
    assert not fake.checked_out, f"deployed on a {verdict} verdict"


def test_update_ships_a_green_commit(lc, monkeypatch, tmp_path):
    fake = _arm(lc, monkeypatch, tmp_path, "pass")
    assert lc.update(unattended=True) == 0
    assert fake.checked_out


def test_the_bypass_file_ships_a_red_commit(lc, monkeypatch, tmp_path):
    fake = _arm(lc, monkeypatch, tmp_path, "fail", bypass=True)
    assert lc.update(unattended=True) == 0
    assert fake.checked_out


def test_an_already_current_checkout_is_not_gated(lc, monkeypatch, tmp_path):
    """A red verdict on code ALREADY live must not take away the restart button."""
    fake = _arm(lc, monkeypatch, tmp_path, "fail")
    fake.target = fake.current
    assert lc.update(unattended=False) == 0


def test_the_kill_switch_still_wins_over_everything(lc, monkeypatch, tmp_path):
    fake = _arm(lc, monkeypatch, tmp_path, "pass")
    lc.NO_AUTO_UPDATE.write_text("")
    assert lc.update(unattended=True) == 0
    assert not fake.checked_out
