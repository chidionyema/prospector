"""The drain's bound must be spent on rows that can still produce something.

Three populations sit in the backlog and they have completely different expected values:

  * provisional PASS — a real PASS the publish gate refuses only because an untrusted brain
    ruled it. One confirming re-vet makes it sellable. This is what the drain is FOR.
  * DEFER — never judged at all. A re-vet produces the first real answer.
  * provisional KILL — already dead. No verdict from any brain lets a KILL reach the publish
    gate, so a re-vet changes `provisional=1 -> 0` and nothing else.

Until 2026-08-06 the drain sorted all three together by age and worked them at 3 per tick. On
the live index that inverted the priority: of the OLDEST 100 drainable rows, 51 were provisional
KILLs and exactly 1 was a provisional PASS, while the 72 provisional PASSes were spread from
2026-06-21 to 2026-08-06. Measured the same day — 318 drainable rows, 161 of them provisional
KILLs, ZERO provisional PASSes left; every drain recorded in ticks.jsonl totalled 39 attempted
for 1 pass; the drain-only tick at 12:23:06Z spent ~$28.65 of subscription CLI on 15 rows for 15
kills and 0 passes, while `backlog_cap` held generation at `batch_size: 0`.

Two fixes, tested here: rank before age, and (config-gated) stop counting provisional KILLs as
backlog at all. The second one has a deadlock hazard the first does not — the scheduler's brake
counts the same population the drain works, so narrowing ONE of the two would leave the brake
waiting on rows nothing is working. Every exclusion test below asserts both sides.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import types

from prospector import drain_state
from prospector import run as run_mod
from prospector.scheduler import run_scheduled as rs
from prospector.store import Store


def _cfg(tmp_path, **schedule):
    sched = {"batch_size": 15}
    sched.update(schedule)
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0),
        schedule=sched,
        operator=["claude_cli"],
    )


def _store_with(tmp_path, rows):
    """A REAL Store whose index holds `rows` = (cid, decision, provisional, created_at)."""
    store = Store(types.SimpleNamespace(store_dir=tmp_path))
    with sqlite3.connect(store.db) as conn:
        for cid, decision, prov, created in rows:
            p = tmp_path / "dossiers" / f"{cid}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"candidate": {"title": cid}, "decision": decision}),
                         encoding="utf-8")
            conn.execute(
                "INSERT INTO dossiers (candidate_id, title, decision, provisional, created_at,"
                " path) VALUES (?,?,?,?,?,?)",
                (cid, cid, decision, 1 if prov else 0, created, str(p)))
    return store


class _FakeStore:
    """Minimal stand-in for Store — only the readers `_cmd_resume` uses.

    Mirrors the double in `test_scheduler_resume_drain.py`; kept local so this file states its
    own fixture rather than importing a sibling test module.
    """

    def __init__(self, rows, on_disk, root="/nonexistent-fake-store"):
        self._rows, self._on_disk, self._root = rows, on_disk, root

    @property
    def root(self):
        from pathlib import Path
        return Path(self._root)

    def all(self, decision=None):
        return [r for r in self._rows if r["decision"] == decision]

    def provisional(self):
        return [r for r in self._rows if r.get("provisional")]

    def get(self, cid):
        return ({"candidate": {"title": cid}, "decision": "defer"}
                if cid in self._on_disk else None)

    def has_dossier(self, cid):
        return self.get(cid) is not None


def _stub_vetting(monkeypatch, seen):
    from prospector.models import Decision

    def fake_vet(cand, *_a, **_k):
        seen.append(cand.title)
        return types.SimpleNamespace(decision=Decision.KILL)

    monkeypatch.setattr("prospector.run.vet_candidate", fake_vet)


#: The live shape in miniature: the dead rows are the OLD ones, so age order serves them first.
_MIXED = [
    {"candidate_id": "deadest", "decision": "kill", "provisional": 1,
     "created_at": "2026-06-14T00:00:00+00:00"},
    {"candidate_id": "dead2", "decision": "kill", "provisional": 1,
     "created_at": "2026-06-15T00:00:00+00:00"},
    {"candidate_id": "old_defer", "decision": "defer", "provisional": 0,
     "created_at": "2026-06-24T00:00:00+00:00"},
    {"candidate_id": "sellable", "decision": "pass", "provisional": 1,
     "created_at": "2026-08-06T00:00:00+00:00"},
]
_MIXED_IDS = {r["candidate_id"] for r in _MIXED}


# ---------------------------------------------------------------------------
# Rank before age
# ---------------------------------------------------------------------------

def test_the_newest_provisional_pass_outranks_the_oldest_dead_row(monkeypatch):
    """A one-row bound must buy the only row that can become inventory.

    Age alone spends it on `deadest` — a KILL that cannot publish under any verdict — and the
    provisional PASS, which is one confirming re-vet away from clearing the publish gate, is
    last in the queue because it is the newest.
    """
    seen: list[str] = []
    _stub_vetting(monkeypatch, seen)
    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=1, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(_MIXED, on_disk=_MIXED_IDS),
    )

    assert seen == ["sellable"], "the bound must go to the population that can publish"
    assert summary["backlog"] == 4, "cfg=None keeps every population counted"


def test_defers_are_worked_before_dead_rows(monkeypatch):
    """Rank 1 (unjudged) still beats rank 2 (already killed), whatever the dates say."""
    seen: list[str] = []
    _stub_vetting(monkeypatch, seen)
    run_mod._cmd_resume(
        argparse.Namespace(limit=2, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(_MIXED, on_disk=_MIXED_IDS),
    )
    assert seen == ["sellable", "old_defer"], (
        "both older provisional KILLs must come after the unjudged DEFER"
    )


def test_age_still_decides_within_one_population(monkeypatch):
    """The rank sort must not undo oldest-first — that is what stops the June rows starving."""
    rows = [
        {"candidate_id": "new", "decision": "defer", "provisional": 0,
         "created_at": "2026-08-05T09:54:00+00:00"},
        {"candidate_id": "old", "decision": "defer", "provisional": 0,
         "created_at": "2026-06-24T20:10:00+00:00"},
        {"candidate_id": "mid", "decision": "defer", "provisional": 0,
         "created_at": "2026-07-28T00:00:00+00:00"},
    ]
    seen: list[str] = []
    _stub_vetting(monkeypatch, seen)
    run_mod._cmd_resume(
        argparse.Namespace(limit=3, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(rows, on_disk={"new", "old", "mid"}),
    )
    assert seen == ["old", "mid", "new"]


def test_the_printed_line_names_the_mix_not_just_the_count(monkeypatch, capsys):
    """"re-vetting 3 of them" cannot be told apart from 3 rows that can never publish.

    That indistinguishability is why the inverted priority survived six weeks unnoticed.
    """
    _stub_vetting(monkeypatch, [])
    run_mod._cmd_resume(
        argparse.Namespace(limit=4, publish=False, board=None),
        cfg=None, op=None, fast_op=None, search=None,
        store=_FakeStore(_MIXED, on_disk=_MIXED_IDS),
    )
    out = capsys.readouterr().out
    assert "1 provisional-pass" in out and "1 defer" in out and "2 provisional-kill" in out


# ---------------------------------------------------------------------------
# The unpublishable exclusion — and the deadlock it must not cause
# ---------------------------------------------------------------------------

def test_provisional_kills_leave_the_drain_and_the_brake_together(tmp_path, capsys):
    """ONE definition. Narrowing the drain alone would freeze generation on unworked rows.

    cap 3, four rows, three of them provisional KILLs: with the exclusion on, the brake counts
    the single workable row and releases. Were the exclusion applied only in the drain, the
    brake would count 4 >= 3 forever while the drain worked none of them.
    """
    store = _store_with(tmp_path, [
        ("dead1", "kill", True, "2026-06-14T00:00:00+00:00"),
        ("dead2", "kill", True, "2026-06-15T00:00:00+00:00"),
        ("dead3", "kill", True, "2026-06-16T00:00:00+00:00"),
        ("live1", "defer", False, "2026-06-24T00:00:00+00:00"),
    ])
    assert len(run_mod.drain_survey(store).workable) == 4, (
        "counterfactual: the pre-fix definition counted all four"
    )

    survey = run_mod.drain_survey(store, revet_provisional_kills=False)
    assert [r["candidate_id"] for r in survey.workable] == ["live1"]
    assert sorted(survey.unpublishable) == ["dead1", "dead2", "dead3"]

    cfg = _cfg(tmp_path, backlog_cap=3, revet_provisional_kills=False)
    assert rs._backlog_size(cfg) == 1, "the brake must count the SAME narrowed population"
    assert rs._generation_suppressed(cfg) == "", "and therefore release generation"
    assert "3 provisional KILLs" in capsys.readouterr().err, (
        "logger.warning never reaches launchd.err.log — the set-aside rows must be PRINTED"
    )


def test_the_exclusion_does_not_defang_the_brake(tmp_path):
    """Excluding dead rows must not release a brake that a real backlog is holding."""
    store = _store_with(tmp_path, [
        (f"live{i}", "defer", False, f"2026-06-{i + 10:02d}T00:00:00+00:00") for i in range(4)
    ] + [("dead1", "kill", True, "2026-06-14T00:00:00+00:00")])
    assert len(store.all(decision="defer")) == 4
    cfg = _cfg(tmp_path, backlog_cap=3, revet_provisional_kills=False)
    assert "backlog brake" in rs._generation_suppressed(cfg)
    assert "4 drainable rows" in rs._generation_suppressed(cfg)


def test_the_exclusion_is_reported_on_every_return_path(tmp_path, monkeypatch, capsys):
    """A silent cap reads as "covered everything". The count must reach ticks.jsonl."""
    monkeypatch.setattr("prospector.health.moat_blind_reason", lambda _cfg: "")
    store = _store_with(tmp_path, [
        ("dead1", "kill", True, "2026-06-14T00:00:00+00:00"),
        ("dead2", "kill", True, "2026-06-15T00:00:00+00:00"),
    ])
    cfg = _cfg(tmp_path, revet_provisional_kills=False)

    summary = run_mod._cmd_resume(
        argparse.Namespace(limit=3, publish=False, board=None, only="all"),
        cfg=cfg, op=None, fast_op=None, search=None, store=store,
    )
    assert summary["attempted"] == 0, "nothing workable is left once the dead rows are excluded"
    assert summary["unpublishable"] == 2, (
        "the summary is what reaches ticks.jsonl and the state probe; a count that is not in "
        "here is a count no operator will ever see"
    )
    assert "provisional KILLs" in capsys.readouterr().out


def test_naming_the_dead_population_still_reaches_it(tmp_path, monkeypatch):
    """The exclusion bounds the AUTOMATIC drain; it is not a lock on the rows.

    `--only provisional-kill` overrides the config default, so the founder can still audit or
    resurrect that population on demand without editing config.yaml.
    """
    monkeypatch.setattr("prospector.health.moat_blind_reason", lambda _cfg: "")
    store = _store_with(tmp_path, [
        ("dead1", "kill", True, "2026-06-14T00:00:00+00:00"),
        ("live1", "defer", False, "2026-06-24T00:00:00+00:00"),
    ])
    seen: list[str] = []
    _stub_vetting(monkeypatch, seen)

    run_mod._cmd_resume(
        argparse.Namespace(limit=5, publish=False, board=None, only="provisional-kill"),
        cfg=_cfg(tmp_path, revet_provisional_kills=False),
        op=None, fast_op=None, search=None, store=store,
    )
    assert seen == ["dead1"]


# ---------------------------------------------------------------------------
# The knob itself
# ---------------------------------------------------------------------------

def test_the_default_is_the_historical_behaviour(tmp_path):
    """Absent config, no config, or a null must all keep working every row.

    The failure direction that matters: a config read that goes wrong must not silently stop
    draining a population, which is how a backlog quietly stops being paid down.
    """
    assert drain_state.revet_provisional_kills(None) is True
    assert drain_state.revet_provisional_kills(_cfg(tmp_path)) is True
    assert drain_state.revet_provisional_kills(_cfg(tmp_path, revet_provisional_kills=None)) is True
    assert drain_state.revet_provisional_kills(
        types.SimpleNamespace(schedule=types.SimpleNamespace(revet_provisional_kills=False))
    ) is False
    assert drain_state.revet_provisional_kills(_cfg(tmp_path, revet_provisional_kills=False)) is False


def test_the_shipped_config_turns_the_exclusion_off_while_the_bugged_kills_are_worked_off():
    """config.yaml is the deployed decision; a test that only checks the knob proves nothing.

    Flipped false -> true on 2026-08-15, and the two measurements that bought `false` are the
    two that changed:

    1. Those rows were not all judgements. They were ruled under `verify._calc_confidence`,
       which scored citation VOLUME and domain COUNT and never read the brain's own confidence
       — so a terse-but-correct brain was scored ungrounded and killed on `moat_ungrounded` /
       `min_composite`. That function was fixed the same day. An unknown share of the 176
       provisional KILLs are therefore artefacts of our scorer, not of the evidence.
    2. The cost that justified the exclusion was claude_cli's (~$28.65 of subscription CLI for
       one 15-row drain tick). minimax now leads the chain at ~$0.0004 a check, which puts the
       whole sweep under a dollar.

    This test pins the DECISION, so it is meant to fail the day someone flips the line back —
    at which point the reason above belongs in the docstring too. Set back to false once the
    backlog is worked off.
    """
    from pathlib import Path

    from prospector.config import load_config
    # Absolute, not "config.yaml": a cwd-relative load makes the assertion silently vacuous
    # (or a collection error) depending on where pytest was invoked from.
    cfg = load_config(str(Path(__file__).resolve().parents[2] / "config.yaml"))
    assert drain_state.revet_provisional_kills(cfg) is True, (
        "schedule.revet_provisional_kills must ship True until the scorer-manufactured KILL "
        "backlog is drained — see config.yaml:1950 for the receipts"
    )


def test_rank_covers_every_row_shape():
    """`_drain_rank` is the classifier BOTH the sort and the exclusion read — one definition."""
    rank = run_mod._drain_rank
    assert rank({"decision": "pass", "provisional": 1}) == run_mod._RANK_PROVISIONAL_PASS
    assert rank({"decision": "defer", "provisional": 0}) == run_mod._RANK_DEFER
    assert rank({"decision": "defer", "provisional": 1}) == run_mod._RANK_DEFER, (
        "a provisional DEFER is still unjudged — it belongs with the DEFERs, not the dead rows"
    )
    assert rank({"decision": "kill", "provisional": 1}) == run_mod._RANK_PROVISIONAL_KILL
    assert rank({"decision": "KILL", "provisional": 1}) == run_mod._RANK_PROVISIONAL_KILL, (
        "decision values are lowercase in the index, but never trust one writer's casing"
    )
