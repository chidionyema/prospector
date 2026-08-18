"""A pack that is finished and simply unlisted must be reachable by the daemon's repair pass.

WHAT BROKE. On 2026-08-18 the founder reported that nothing had been minted and listed that
day. The engine was healthy and had produced 25 PASSes, but 59 of them sat off the shelf, and
three of those were `READY` -- lints clean, complete, never published. The daemon runs a repair
pass every `schedule.recover_interval_s` that exists precisely to pay that backlog down, and it
ran: the live tick at 2026-08-18T18:53Z printed

    SKIP [0fcc840981645d85] publish: route publish not selected

`tools/recover_stranded_passes.py::_route` routes each pack to exactly ONE route, and a pack
with no error-severity lint problems routes to `publish` (`recover_stranded_passes.py:163`).
The daemon passed `--routes audit,rebundle,copy`. The route filter runs BEFORE anything else
(`recover_stranded_passes.py:397`), so every finished-but-unlisted pack -- the single case the
repair pass is cheapest and safest at fixing -- was dropped before the `--publish` flag it was
also given could apply to it.

THE CLASS OF FAILURE. Two switches that have to agree, written down in two places. `--publish`
said list what gates clean; `--routes` said never consider the packs that gate clean. Neither
is wrong alone. The fix derives the route list from the publish switch so they cannot drift,
and this test is what stops them drifting again.
"""
from __future__ import annotations

import subprocess
import types

from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path, **schedule):
    sched = {"recover_stranded_packs": True, "recover_per_tick": 3, "recover_interval_s": 0}
    sched.update(schedule)
    return types.SimpleNamespace(store_dir=str(tmp_path), schedule=sched)


def _child_cmd(tmp_path, monkeypatch, **schedule) -> list[str]:
    """Run the recovery step with the child stubbed out, and return the argv it would have run."""
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rs._recover_pass(_cfg(tmp_path, **schedule))
    assert seen, "the recovery step never launched its child"
    return seen[0]


def _routes(cmd: list[str]) -> set[str]:
    return {r for r in cmd[cmd.index("--routes") + 1].split(",") if r}


def test_publish_route_is_selected_whenever_publishing_is_on(tmp_path, monkeypatch):
    """The regression itself. --publish without the publish route lists nothing."""
    cmd = _child_cmd(tmp_path, monkeypatch, recover_publish=True)
    assert "--publish" in cmd
    assert "publish" in _routes(cmd), (
        "the daemon asked to publish repaired packs but excluded the `publish` route, so a "
        "pack that is finished and merely unlisted is skipped with 'route publish not "
        "selected' -- the exact bug that stranded three sellable packs on 2026-08-18"
    )


def test_publish_route_is_absent_when_publishing_is_off(tmp_path, monkeypatch):
    """The other direction. Publishing off must not smuggle the money-rail action back in via
    the route list -- that would make `recover_publish: false` a lie."""
    cmd = _child_cmd(tmp_path, monkeypatch, recover_publish=False)
    assert "--publish" not in cmd
    assert "publish" not in _routes(cmd)


def test_regenerate_is_never_selected(tmp_path, monkeypatch):
    """Unchanged rule, pinned here because this list is now built rather than written out:
    `regenerate` is full artifact generation and belongs to the generation budget, not to a
    repair pass that runs inside a tick with a deadline."""
    for publish in (True, False):
        cmd = _child_cmd(tmp_path, monkeypatch, recover_publish=publish)
        assert "regenerate" not in _routes(cmd)


def test_the_repair_pass_targets_this_ticks_store(tmp_path, monkeypatch):
    """A money-rail action on someone else's catalogue is the worst way for this to go wrong,
    so the store pin travels with the route change."""
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rs._recover_pass(_cfg(tmp_path, recover_publish=True))
    assert seen["env"]["PROSPECTOR_STORE_DIR"] == str(tmp_path)
