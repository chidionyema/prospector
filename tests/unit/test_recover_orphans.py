"""The recovery loop: abandoned work gets re-vetted, and nothing is paid for twice.

The failure this closes, measured 2026-08-17 on the live store over four audit day-files: 12
candidates had a `candidate_start` and no `candidate_done` from a process that no longer exists,
and 10 of the 12 had NO index row and NO dossier. `run.drainable()` reads index rows, so the
ordinary drain could never see them. Recording the loss is not the same as undoing it — these
pin the undoing.
"""
from __future__ import annotations

import json
import types

import pytest

from prospector import inflight, run
from prospector.errors import ProviderExhaustedError
from prospector.models import Candidate
from prospector.store import Store


def _cand(title: str) -> Candidate:
    return Candidate(title=title, one_liner="does a thing", hypothesis="a problem",
                     who_pays="someone", why_now="now")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A real Store on a temp dir, with the moat sighted and no brain actually called."""
    cfg = types.SimpleNamespace(store_dir=tmp_path)
    store = Store(cfg)
    monkeypatch.setattr("prospector.health.moat_blind_reason", lambda *a, **k: "")
    monkeypatch.setattr("prospector.progress.banner", lambda *a, **k: None)
    monkeypatch.setattr(run, "_resolve_board", lambda args: None)
    vetted: list[Candidate] = []

    def _fake_vet(cand, *a, **k):
        vetted.append(cand)
        return object()

    monkeypatch.setattr(run, "vet_candidate", _fake_vet)
    args = types.SimpleNamespace(limit=None, publish=False, board=None)
    return types.SimpleNamespace(cfg=cfg, store=store, vetted=vetted, args=args, root=store.root)


def _recover(env):
    return run._recover_orphans(env.args, env.cfg, None, None, None, env.store)


def test_an_abandoned_candidate_is_re_vetted(env):
    """THE POINT. Its process died, it has no index row, and it comes back anyway."""
    cand = _cand("Abandoned idea")
    inflight.open_(env.root, cand)

    out = _recover(env)

    assert [c.title for c in env.vetted] == ["Abandoned idea"]
    assert out["recovered"] == 1
    assert out["settled"] == 0


def test_a_record_whose_verdict_already_exists_is_dropped_not_re_vetted(env, monkeypatch):
    """The process died between `store.save` and `inflight.close`. Paying twice would be a bug."""
    cand = _cand("Already ruled")
    inflight.open_(env.root, cand)
    monkeypatch.setattr(env.store, "all",
                        lambda *a, **k: [{"candidate_id": cand.candidate_id}])

    out = _recover(env)

    assert env.vetted == []
    assert out["settled"] == 1
    assert out["recovered"] == 0
    assert inflight.survey(env.root)["counts"] == {"live": 0, "orphaned": 0, "unreadable": 0}


def test_work_a_live_process_holds_is_left_alone(env, monkeypatch):
    """Recovery must never race the process that is doing the work."""
    inflight.open_(env.root, _cand("Being vetted right now"))
    monkeypatch.setattr("prospector.ops.runs.process_alive", lambda pid: True)

    out = _recover(env)

    assert env.vetted == []
    assert out == {}


def test_a_blind_moat_defers_recovery_instead_of_spending_on_it(env, monkeypatch):
    """A re-vet with no brain to rule only buys a more expensive way to write DEFER."""
    inflight.open_(env.root, _cand("Waiting for a brain"))
    monkeypatch.setattr("prospector.health.moat_blind_reason",
                        lambda *a, **k: "every verdict brain is benched")

    out = _recover(env)

    assert env.vetted == []
    assert out["skipped"] == "every verdict brain is benched"
    # AND THE WORK IS STILL THERE. A deferred repair that dropped the record would be the loss
    # this whole ledger exists to prevent, arriving by a different route.
    assert inflight.survey(env.root, alive={})["counts"]["orphaned"] == 1


def test_the_moat_dying_mid_recovery_stops_the_pass_and_keeps_the_rest(env, monkeypatch):
    for i in range(3):
        inflight.open_(env.root, _cand(f"Idea {i}"))

    def _boom(cand, *a, **k):
        raise ProviderExhaustedError("moat went blind")

    monkeypatch.setattr(run, "vet_candidate", _boom)

    out = _recover(env)

    assert out["recovered"] == 0
    assert out["skipped"] == "the moat went blind during recovery"
    assert inflight.survey(env.root, alive={})["counts"]["orphaned"] == 3


def test_one_bad_record_does_not_stop_the_others(env):
    """A record that cannot rebuild its Candidate is counted, and the rest still get recovered."""
    good = _cand("Recoverable")
    inflight.open_(env.root, good)
    (inflight.directory(env.root) / "ruined.json").write_text(json.dumps(
        {"candidate_id": "ruined", "candidate": "not a dict", "pid": 2 ** 22,
         "started_at": 1.0}))

    out = _recover(env)

    assert [c.title for c in env.vetted] == ["Recoverable"]
    assert out["recovered"] == 1
    assert out["unrecoverable"] == 1
    # AND THE FILE SURVIVES. Deleting it would destroy the only remaining trace of the idea.
    assert (inflight.directory(env.root) / "ruined.json").exists()


def test_a_record_that_names_no_process_is_flagged_for_a_human_not_guessed_at(env):
    """Calling it live strands it forever; calling it dead can re-vet work in progress."""
    (inflight.directory(env.root)).mkdir(parents=True, exist_ok=True)
    (inflight.directory(env.root) / "nameless.json").write_text('{"candidate_id": "nameless"}')

    out = _recover(env)

    assert env.vetted == []
    assert out == {}
    view = inflight.survey(env.root, alive={})
    assert view["counts"] == {"live": 0, "orphaned": 0, "unreadable": 1}


def test_limit_bounds_the_pass_the_same_way_the_drain_is_bounded(env):
    for i in range(5):
        inflight.open_(env.root, _cand(f"Idea {i}"))
    env.args.limit = 2

    out = _recover(env)

    assert out["recovered"] == 2
    assert len(env.vetted) == 2


def test_a_claim_held_by_another_drain_is_skipped(env):
    cand = _cand("Someone else is on it")
    inflight.open_(env.root, cand)
    assert inflight.claim(env.root, cand.candidate_id, "other-drain") is True

    out = _recover(env)

    assert env.vetted == []
    assert out["recovered"] == 0


def test_no_ledger_at_all_is_not_an_error(env):
    assert _recover(env) == {}
    assert env.vetted == []
