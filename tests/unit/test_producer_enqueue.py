"""The producer: generation ends at a durable queue row, and never at a verdict.

WHY THE SPLIT. Generation and vetting have incompatible clocks. Generation is bounded and
fairly predictable; a single vet was measured at 4127s against a ~251s median. A tick that
must do both under one deadline either sizes generation for the vet's worst case — starving
the queue — or force-exits mid-verdict, which is what was happening (five recorded `os._exit`
breaches, 2026-08-13 to 2026-08-15, every one at batch=15).

`run_signal(vet=False)` is the producer half. What these tests pin is not that a flag exists
but that the flag's promise holds under the failure modes that make a producer worth having:
it must not touch a brain, it must not lose the batch to one bad row, its rows must be the
SAME rows the consumer already knows how to drain, and it must report what it wrote rather
than what it meant to write.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from prospector import run as run_mod
from prospector.config import load_config
from prospector.models import Candidate, Decision
from prospector.store import Store


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _cfg(tmp_path, monkeypatch):
    # `store_dir` is a read-only property; PROSPECTOR_STORE_DIR (config.py:677) is the
    # sanctioned redirect and it is the one that must be used here — these tests SAVE, and a
    # default Config resolves to the repo's real `store/`, which is tracked runtime state.
    # That exact defect is on record twice (tests polluting the production audit log and the
    # durable ledger), which is why conftest.py isolates six other write paths the same way.
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "store"))
    cfg = load_config()
    cfg.operator = "mock"
    # See tests/unit/test_blue_sky.py's docstring: the ancillary chain is built EAGERLY and
    # is key-metered, so keyless CI raises at construction unless it is mocked here too.
    cfg.noncritical_operator = ["mock"]
    assert str(tmp_path) in str(cfg.store_dir), "refuse to run against the real store"
    return cfg


def _op():
    """A brain that is never called for a verdict, but IS read for `model_version` — which
    goes into the row and therefore into JSON. A bare MagicMock serves a MagicMock there and
    every save fails as unserialisable, which the producer then correctly logs and skips: the
    batch survives and the queue is silently empty."""
    op = MagicMock()
    op.model_version = "mock"
    return op


def _producer_run(monkeypatch, tmp_path, *, cands, store=None, k=None):
    """Drive run_signal to the split point with generation stubbed, and return its output.

    Everything upstream of novelty selection is replaced, deliberately: what is under test is
    the branch AT the split, and a real generation chain would make these tests measure a
    model's output instead of the branch.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    store = store if store is not None else Store(cfg)

    monkeypatch.setattr(run_mod, "generate", lambda *a, **k: list(cands))
    monkeypatch.setattr(run_mod, "dedup", lambda c, *a, **k: (list(c), []))
    monkeypatch.setattr(run_mod, "prescreen", lambda op, cfg, cand: (True, 1.0, "", ""))
    monkeypatch.setattr("prospector.novelty.select_diverse_candidates",
                        lambda op, data, k=None: [c for c, _s, _f in data][:(k or len(data))])
    # The tripwire. A producer that reaches this line has not split anything.
    monkeypatch.setattr(run_mod, "vet_candidate", MagicMock(
        side_effect=AssertionError("the producer must not vet")))

    out = run_mod.run_signal("", cfg=cfg, op=_op(), search=object(),
                             store=store, k=k, vet=False)
    return out, store, cfg


# --------------------------------------------------------------------------- #
# 1. The producer writes the queue and stops
# --------------------------------------------------------------------------- #
def test_every_selected_candidate_becomes_one_queue_row(monkeypatch, tmp_path):
    cands = [Candidate(title=f"idea {i}") for i in range(4)]
    out, store, _ = _producer_run(monkeypatch, tmp_path, cands=cands)

    assert len(out) == 4, "one row per selected candidate — nothing dropped, nothing doubled"
    assert {d.candidate.title for d in out} == {c.title for c in cands}
    # Durability is the whole point: an in-memory list is not a queue.
    assert len(store.all(decision="defer")) == 4


def test_a_queued_row_is_a_defer_that_says_why_it_is_waiting(monkeypatch, tmp_path):
    """DEFER is what the house already means by "generated, not yet ruled" — that is why the
    queue needed no new table. But `vet_budget_spent` (started, then the clock ran out) and
    `queued_for_vetting` (never started) are different events, and a store that cannot tell
    them apart cannot say whether a backlog came from over-generation or from a truncated tick.
    """
    out, _, _ = _producer_run(monkeypatch, tmp_path, cands=[Candidate(title="T")])
    d = out[0]

    assert d.decision == Decision.DEFER
    assert d.checks == [], "no check ran; inventing one would be a fabricated verdict"
    # `build_dossier` deliberately clears `gate_fired` for a DEFER — no gate fired, and
    # recording one would corrupt the kill stats (test_tick_budget_rails.py:536). The reason
    # line is where the distinction survives.
    assert d.gate_fired is None
    assert "queue" in d.reason.lower() or "vet" in d.reason.lower()


def test_the_producer_never_opens_the_vet_pool(monkeypatch, tmp_path):
    """The tripwire in the harness is the assertion; this test states the property.

    A producer that reached the pool would still LOOK correct — rows land, counts match — while
    quietly holding the tick open for a moat verdict per candidate, which is the exact coupling
    being removed."""
    _producer_run(monkeypatch, tmp_path, cands=[Candidate(title=f"i{i}") for i in range(3)])
    # Reaching here means run_mod.vet_candidate's AssertionError never fired.


def test_the_producer_needs_no_brain_and_no_search(monkeypatch, tmp_path):
    """A benched moat must cost the producer nothing. `search` here is a bare object with no
    methods at all: any grounding call would raise AttributeError rather than fail a soft
    check, so this passing is proof the vet path was not entered even partially."""
    cfg = _cfg(tmp_path, monkeypatch)
    monkeypatch.setattr(run_mod, "generate", lambda *a, **k: [Candidate(title="T")])
    monkeypatch.setattr(run_mod, "dedup", lambda c, *a, **k: (list(c), []))
    monkeypatch.setattr(run_mod, "prescreen", lambda op, cfg, cand: (True, 1.0, "", ""))
    monkeypatch.setattr("prospector.novelty.select_diverse_candidates",
                        lambda op, data, k=None: [c for c, _s, _f in data])

    out = run_mod.run_signal("", cfg=cfg, op=_op(), search=object(),
                             store=Store(cfg), vet=False)
    assert len(out) == 1


# --------------------------------------------------------------------------- #
# 2. The rows are the consumer's rows
# --------------------------------------------------------------------------- #
def test_queued_rows_are_visible_to_the_consumers_own_selector(monkeypatch, tmp_path):
    """The integration test that matters. `drainable()` is the single definition of "work the
    consumer can take" (run.py:2193), and it applies exclusions the producer knows nothing
    about — orphan rows, attempt caps. A producer whose rows are durable but not DRAINABLE
    fills a store instead of a queue, and every counter would still read healthy.
    """
    cands = [Candidate(title=f"idea {i}") for i in range(3)]
    _out, store, _cfg_ = _producer_run(monkeypatch, tmp_path, cands=cands)

    workable = run_mod.drainable(store)
    assert len(workable) == 3, "the producer's rows must be work the consumer will actually take"


def test_the_queue_row_carries_a_leasable_identity(monkeypatch, tmp_path):
    """Rows the consumer cannot lease are rows two workers will vet twice. The lease is a
    compare-and-swap on `candidate_id`, so a row written without one is unclaimable — and
    would fail open, since `claim` on a nonexistent row returns False and the worker skips."""
    out, store, _ = _producer_run(monkeypatch, tmp_path, cands=[Candidate(title="T")])
    cid = out[0].candidate.candidate_id

    assert cid, "a queue entry with no id cannot be leased, drained or deduped"
    assert store.claim(cid, "worker-a", 60.0) is True
    assert store.claim(cid, "worker-b", 60.0) is False


# --------------------------------------------------------------------------- #
# 3. One writer
# --------------------------------------------------------------------------- #
def test_the_producer_and_the_budget_park_rail_share_one_writer(monkeypatch):
    """Two call sites each building "a queued row" by hand is how the two shapes drift, and
    the consumer is then the thing that has to tell them apart. `reason` is allowed to differ;
    nothing else is."""
    seen: list[dict] = []
    monkeypatch.setattr(run_mod, "enqueue_as_defer",
                        lambda cand, **kw: seen.append(kw) or types.SimpleNamespace(cand=cand))

    run_mod.enqueue_candidates([Candidate(title="A")], store=None, cfg=object(), op=object())

    fut = MagicMock()
    fut.cancelled.return_value = True
    run_mod._defer_unstarted_candidates({fut: 1}, [Candidate(title="B")], set(),
                                        store=None, cfg=object(), op=object(), dossiers=[])

    assert len(seen) == 2, "both rails must go through the one writer"
    assert seen[0]["reason"] == "queued_for_vetting"
    assert seen[1]["reason"] == "vet_budget_spent"
    assert seen[0].keys() == seen[1].keys(), "the shapes may differ only in the reason"


def test_the_writer_raises_rather_than_returning_an_unsaved_row():
    """Both callers catch, but they catch for their own reasons. A writer that swallowed a
    failed save would hand back a row that looks queued and is not, and both callers would
    count a queue entry that does not exist."""
    class _BrokenStore:
        def save(self, d):
            raise OSError("disk full")

    with pytest.raises(OSError):
        run_mod.enqueue_as_defer(Candidate(title="T"), store=_BrokenStore(),
                                 cfg=types.SimpleNamespace(active_persona="default"),
                                 op=types.SimpleNamespace(model_version=""),
                                 reason="queued_for_vetting")


# --------------------------------------------------------------------------- #
# 3b. The deferral vocabulary is a CLOSED set
# --------------------------------------------------------------------------- #
def test_an_unrecognised_reason_would_be_a_kill_so_the_writer_refuses_it():
    """`build_dossier` decides KILL for any `gate_fired` it does not recognise (dossier.py:113).
    That is right for a real gate — an unknown gate name is still a gate that fired — and
    silently catastrophic for a deferral: a typo mints an EVIDENTIARY KILL on a candidate no
    check ever looked at, in a row that reads as fully reasoned. That is the
    `2102bacc6dd75cf9.kill.json` defect, and `enqueue_as_defer` is now the one place it can be
    introduced. Loud at the call, never silent in the catalogue."""
    with pytest.raises(ValueError, match="not a deferral"):
        run_mod.enqueue_as_defer(Candidate(title="T"), store=None,
                                 cfg=types.SimpleNamespace(active_persona="default"),
                                 op=types.SimpleNamespace(model_version=""),
                                 reason="queued_for_veting")  # one letter


def test_every_defer_reason_actually_decides_defer():
    """The set and the branch must not drift. Adding a name to DEFER_REASONS without a reason
    line — or the reverse — is a one-line slip either way, and the failure mode of getting it
    wrong is a KILL rather than an error."""
    from prospector.dossier import build_dossier
    from prospector.models import DEFER_REASONS

    for name in sorted(DEFER_REASONS):
        d = build_dossier(cand=Candidate(title="T"), checks=[], adversarial=None,
                          gate_fired=name, score=None,
                          cfg=types.SimpleNamespace(active_persona="default"),
                          op_model_version="m")
        assert d.decision == Decision.DEFER, f"{name} must never decide KILL"
        assert d.gate_fired is None, f"{name} is not a gate; recording one corrupts kill stats"
        assert "NOT an evidentiary kill" in d.reason, (
            f"{name} has no reason line of its own — it fell through to the retrieval wording, "
            f"which manufactures an outage that did not happen")


# --------------------------------------------------------------------------- #
# 4. Failure reporting
# --------------------------------------------------------------------------- #
def test_one_unwritable_row_does_not_cost_the_batch(monkeypatch, caplog):
    """The rest of the batch is already paid for — generated, deduped, prescreened, selected."""
    calls = {"n": 0}

    def _flaky(cand, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return types.SimpleNamespace(cand=cand)

    monkeypatch.setattr(run_mod, "enqueue_as_defer", _flaky)
    out = run_mod.enqueue_candidates([Candidate(title=f"i{i}") for i in range(3)],
                                     store=None, cfg=object(), op=object())

    assert len(out) == 2, "two rows written; the third is lost, not the batch"


def test_the_producer_returns_what_it_WROTE_not_what_it_attempted(monkeypatch):
    """The counters-lie failure mode, at the one place it would be most expensive: every
    queue-depth reading downstream — the generation brake included — is built on this number.
    A producer reporting 15 queued while 3 landed makes the brake read a queue that is not
    there and keep generating into a store that is losing writes."""
    monkeypatch.setattr(run_mod, "enqueue_as_defer",
                        MagicMock(side_effect=OSError("disk full")))
    out = run_mod.enqueue_candidates([Candidate(title=f"i{i}") for i in range(5)],
                                     store=None, cfg=object(), op=object())

    assert out == [], "nothing was written, so nothing may be reported as queued"


# --------------------------------------------------------------------------- #
# 5. The default is unchanged
# --------------------------------------------------------------------------- #
def test_vet_defaults_to_true_so_no_existing_caller_changes_behaviour():
    """The split ships as an opt-in. Every existing call site — the CLI, the daemon, four test
    suites — passes no `vet` at all, and a default of False would silently convert all of them
    into producers that never rule on anything."""
    import inspect
    sig = inspect.signature(run_mod.run_signal)
    assert sig.parameters["vet"].default is True


def test_no_vet_with_publish_is_refused_not_ignored(monkeypatch, capsys):
    """Producer mode returns before a verdict exists and publishing is gated on PASS, so
    `--publish` could only ever be inert here. Dropping a flag the operator typed is the
    silent-feature-removal defect; the exit code is what makes it visible to a script."""
    args = types.SimpleNamespace(no_vet=True, publish=True, resume=False, config=None)
    monkeypatch.setattr(run_mod, "_build_config_and_overrides", lambda a: object())

    with pytest.raises(SystemExit) as e:
        run_mod._cmd_generate(args, None)

    assert e.value.code == 2
    assert "--no-vet" in capsys.readouterr().err
