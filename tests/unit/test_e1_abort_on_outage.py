"""E1 must abort when the denominator is empty, not print a table of `0/0`.

2026-08-08, live run `ba5ah4zyn`. A usage wall was up ("capacity returns 2026-08-08
00:25:47, observed by prospector-cli"), so every one of the 48 verdict calls deferred. E1
ground through all of them and then printed:

    check             ctrl_unv  treat_unv    delta  separable
    payer_solvency   0/0       0/0             n/a         no
    ...
    separable on 0 of 3 checks at 95% Wilson; E1's kill bar is 'no drop in unverifiable rate'

Nothing was measured, and the output says the kill bar was met. `_rate` returns rate=None at
n=0, the delta goes None, and `intervals_overlap` is True over two zero-width intervals — so a
total outage renders as the experiment's own negative finding. That is the exact trap the
module docstring names for the INERT ARM ("an experiment whose null result and whose broken
result are the same output is not an experiment"); the fence existed for the arm and not for
the denominator.

Everything here is stubbed at `prospector.verify.run_check` and `gen_queries_batched`. No
verdict call, no search, no spend.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from prospector.models import CheckResult, Verdict

REPO = Path(__file__).resolve().parents[2]
E1_PATH = REPO / "tools" / "experiments" / "e1_hybrid_query_arms.py"
CHECKS = ("payer_solvency", "incumbency", "legality")
ARGS = ["--live", "--quiet-daemon-ok", "--candidates", "4", "--checks", ",".join(CHECKS)]


def _fixture_dossier(i: int) -> tuple[str, dict]:
    """One synthetic dossier that RAN all of CHECKS, shaped for the treatment arm.

    Every field here is load-bearing, and an omission fails as a DIFFERENT refusal than the one
    under test:

      * `who_pays` fills `{payer}` and `market` fills `{market}` (verify._entity_queries);
      * `tags["audience"]` fills `{aud}`, and it must be a TAG, not an attribute — `audience` is
        a read-only property over `tags` (`models.py:145-163`), not a dataclass field, so
        `Candidate(audience=...)` is a TypeError and a candidate without the tag yields ZERO
        incumbency queries. That trips `REFUSING: the treatment arm produces NO queries` at
        `e1_hybrid_query_arms.py:449` — an abort that looks like the outage abort these tests
        assert on, and would make them pass for the wrong reason;
      * `checks` must name all of CHECKS, because `_load_candidates` selects on "ran the check".

    The path is a LABEL, never opened: `corpus.candidate_id` (`_corpus.py:124-126`) prefers the
    dossier's own `candidate_id` and only falls back to the basename. It deliberately does not
    read `store/dossiers` — a synthetic path that spells the real store is the exact string
    `test_no_test_reads_the_operators_own_store` exists to flag, and that guard is right to be
    lexical: it cannot tell a path a test opens from one it merely names.
    """
    return (f"fixtures/dossiers/fixture{i:02d}.json", {
        "candidate": {
            "candidate_id": f"fixture{i:02d}",
            "title": f"Damp survey scheduling for letting agents {i}",
            "one_liner": "A booking service for damp surveys",
            "who_pays": "letting agents managing rented flats",
            "market": "uk",
            "tags": {"audience": "letting agents"},
        },
        "checks": [{"check_name": c} for c in CHECKS],
    })


@pytest.fixture
def e1(monkeypatch):
    # `import _corpus` inside the module resolves only because Python auto-adds the script's
    # own directory to sys.path when it is run as `python tools/experiments/e1_...py`. Loading
    # it by spec gets no such favour, so supply the path explicitly.
    monkeypatch.syspath_prepend(str(E1_PATH.parent))
    spec = importlib.util.spec_from_file_location("_e1_under_test", E1_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # The corpus is stubbed for the same reason the moat is: this file tests E1's ABORT logic,
    # and `_load_candidates` (`:80`) reads the live dossier store, which is not committed —
    # `git ls-tree store/dossiers` is EMPTY on every ref. So in CI and in any fresh worktree
    # these tests failed with `REFUSING: only 0 dossier(s) ran all of [...]`, red since before
    # the merge that surfaced it, while passing locally off a 1640-dossier store. That is a
    # test whose result depends on the machine, not the code.
    #
    # Stubbed rather than SKIPPED deliberately. A skip would go green everywhere and guard
    # nothing precisely where the guard is wanted — CI is the only place the E1 fence is
    # checked at all, since nobody runs this file by hand.
    monkeypatch.setattr(mod, "_load_candidates",
                        lambda n, seed_checks: [_fixture_dossier(i) for i in range(n)])
    # The verdict chain is pinned for the same reason, one level up. `_resolve_live_path`
    # (`:150`) reads the LIVE `config.yaml` through `_arm_config`, so these tests inherited
    # whatever `operator:` happened to say that day. On 2026-08-08 the founder re-added a
    # `minimax` tail and all six live-path tests died at once on E1's provisional fence — a
    # correct fence, firing on a config change, in a file that tests abort-on-OUTAGE logic and
    # has no opinion about the chain. Same defect as the corpus above, with config in place of
    # the machine: a result that moves when something unrelated to the code under test moves.
    #
    # Pinned, not stubbed away: the fence itself is worth testing, so it is tested directly and
    # deterministically in `test_the_fence_refuses_a_chain_a_provisional_brain_could_rule`
    # rather than left to be exercised by accident by whatever config.yaml currently ships.
    _real_arm_config = mod._arm_config

    def _trusted_arm_config(checks, hybrid):
        cfg = _real_arm_config(checks, hybrid)
        cfg.operator = ["claude_cli"]
        return cfg

    monkeypatch.setattr(mod, "_arm_config", _trusted_arm_config)
    return mod


def _deferred(check: str) -> CheckResult:
    """Exactly what verify.py:619 returns when the moat will not answer."""
    return CheckResult(check_name=check, verdict=Verdict.UNVERIFIABLE, confidence=0.0,
                       rationale="Retrieval unavailable — all searches failed (infra/outage). "
                                 "Cannot rule; candidate deferred for re-vet.",
                       queries=["q"], query_source="", degraded=True, retrieval_failed=True)


def _ruled(check: str, hybrid: bool) -> CheckResult:
    """A cell that actually ruled. `query_source` must satisfy E1's inert-arm fence."""
    return CheckResult(check_name=check, verdict=Verdict.SUPPORTED, confidence=0.8,
                       rationale="ruled", queries=["q"],
                       query_source="entity_template" if hybrid else "llm_batched",
                       provider="claude-cli/test")


@pytest.fixture
def stub_moat(monkeypatch):
    """Install a stubbed verify layer; `behaviour(check, hybrid, n)` picks each cell's result."""
    import prospector.verify as V

    def install(behaviour):
        calls: list[tuple[str, bool]] = []

        def fake_run_check(op, search, cfg, cand, check_name, precomputed_queries=None, **kw):
            hybrid = bool(getattr(getattr(cfg, "retrieval", None), "hybrid_entity_checks", None)
                          or getattr(cfg, "hybrid_entity_checks", None))
            calls.append((check_name, hybrid))
            return behaviour(check_name, hybrid, len(calls))

        monkeypatch.setattr(V, "run_check", fake_run_check)
        monkeypatch.setattr(V, "gen_queries_batched",
                            lambda op, cand, checks, cfg=None: {c: ["q"] for c in checks})
        return calls

    return install


def test_a_total_outage_aborts_instead_of_reporting_a_null(e1, stub_moat):
    stub_moat(lambda check, hybrid, n: _deferred(check))
    out = e1.run(ARGS)

    assert out["headline"]["aborted"] == "moat_outage"
    # The three fields an operator would read as a result must be absent, not zero.
    assert out["headline"]["deltas"] is None
    assert out["headline"]["separable_checks"] is None
    assert "table" not in out
    assert "NOT a null result" in out["abort_reason"]
    # And the abort names the cause rather than reporting an unattributed hole.
    assert "Retrieval unavailable" in out["abort_reason"]


def test_arm_B_is_not_billed_once_arm_A_is_dead(e1, stub_moat):
    calls = stub_moat(lambda check, hybrid, n: _deferred(check))
    e1.run(ARGS)

    # 2 candidates x 3 checks = the streak threshold, and then it stops. The moat that refused
    # arm A rules arm B too, so continuing spends 42 more cells to learn the same nothing.
    assert len(calls) == 2 * len(CHECKS), calls
    assert not any(hybrid for _, hybrid in calls), "arm B was billed after arm A died"


def test_one_empty_cell_aborts_even_when_the_streak_never_fires(e1, stub_moat):
    """The scattered outage: `legality` never rules, but never six in a row either."""
    stub_moat(lambda check, hybrid, n:
              _deferred(check) if check == "legality" else _ruled(check, hybrid))
    out = e1.run(ARGS)

    assert out["headline"]["aborted"] == "moat_outage"
    assert "legality/llm" in out["abort_reason"]
    assert "legality/entity" in out["abort_reason"]


def test_a_healthy_run_still_reports_a_table(e1, stub_moat):
    """Non-vacuity. Without this, a fence that always aborted would pass every test above."""
    stub_moat(lambda check, hybrid, n: _ruled(check, hybrid))
    out = e1.run(ARGS)

    assert "aborted" not in out["headline"]
    assert [t["check"] for t in out["table"]] == list(CHECKS)
    assert all(t["control"]["n_ruled"] > 0 and t["treatment"]["n_ruled"] > 0
               for t in out["table"])
    assert out["headline"]["deltas"] == dict.fromkeys(CHECKS, 0.0)


def test_the_abort_and_the_rate_share_one_definition_of_ruled(e1):
    """`_is_ruled` is the denominator. If `_rate` ever disagrees, the fence has a blind spot."""
    rows = [{"check": "legality", "arm": "llm", "retrieval_failed": True, "error": None,
             "verdict": "unverifiable", "rationale": "deferred"},
            {"check": "legality", "arm": "llm", "retrieval_failed": False,
             "error": "RuntimeError: boom", "verdict": None, "rationale": ""}]
    assert not any(e1._is_ruled(r) for r in rows)
    assert e1._rate(rows, "legality", "llm")["n_ruled"] == 0
    assert e1._rate(rows, "legality", "llm")["rate"] is None


def test_a_run_records_whether_the_daemon_fence_actually_held(e1, monkeypatch, stub_moat):
    """The startup PAUSE check proves the fence existed at t=0 and nothing after that.

    Observed live 2026-08-08 (run `bo2mosjog`): PAUSE was created at 00:25Z and gone by 00:35Z
    with the run still billing cells and the daemon up. Nothing in the repo unlinks PAUSE, so
    this cannot be prevented from inside the process — only recorded, which is what makes the
    latency/cost half of the receipt honest.
    """
    seen: list[bool] = []
    flips = iter([True] * 4 + [False] * 200)

    def _fence():
        v = next(flips)
        seen.append(v)
        return v

    monkeypatch.setattr(e1, "_quiet_now", _fence)
    stub_moat(lambda check, hybrid, n: _ruled(check, hybrid))
    out = e1.run(ARGS)

    q = out["headline"]["quiet_fence"]
    assert q["held"] is False
    assert q["lost_at_cell"] == 5, q
    assert q["cells_unfenced"] == q["cells_observed"] - 4
    assert "must not be quoted" in q["note"]


def test_a_fully_fenced_run_reports_held_with_no_note(e1, monkeypatch, stub_moat):
    """Non-vacuity: a report that always said 'contaminated' would pass the test above."""
    monkeypatch.setattr(e1, "_quiet_now", lambda: True)
    stub_moat(lambda check, hybrid, n: _ruled(check, hybrid))
    out = e1.run(ARGS)
    q = out["headline"]["quiet_fence"]
    assert q["held"] is True and q["note"] == "" and q["lost_at_cell"] is None
    assert q["cells_observed"] > 0, "a zero-cell run must never report the fence as held"


def _cell(cid, check, arm, unverifiable, *, ruled=True):
    return {"candidate_id": cid, "check": check, "arm": arm,
            "verdict": "unverifiable" if unverifiable else "supported",
            "error": None, "retrieval_failed": not ruled, "n_citations": 3,
            "query_source": "entity_template" if arm == "entity" else "llm_batched"}


def _paired_rows(pattern):
    """pattern[check] = list of (control_unverifiable, treatment_unverifiable) per candidate."""
    rows = []
    for check, pairs in pattern.items():
        for i, (cu, tu) in enumerate(pairs):
            rows.append(_cell(f"c{i}", check, "llm", cu))
            rows.append(_cell(f"c{i}", check, "entity", tu))
    return rows


def test_the_paired_test_uses_the_pairing_the_design_paid_for(e1):
    """Per-check n is 6-8; only the pooled read has any power, and it must say so.

    These counts reproduce live run `bo2mosjog`: every check leans treatment-worse, no single
    check is separable, and pooling reaches p<0.05. An analysis that could only ever report the
    per-check nulls would retire E1 as 'no effect' when the direction is consistent 9-to-1.
    """
    W, B, C = (False, True), (True, False), (True, True)   # worse / better / concordant
    rows = _paired_rows({
        "payer_solvency": [W, W, W, C, C, C, C, C],
        "incumbency":     [W, W, W, B, C, C, C, C],
        "legality":       [W, W, W, C, C, C, C, C],
    })

    per = {ck: e1._mcnemar(rows, ck) for ck in ("payer_solvency", "incumbency", "legality")}
    assert not any(m["separable"] for m in per.values()), per
    assert all(m["direction"] == "treatment_worse" for m in per.values()), per

    pooled = e1._mcnemar(rows, None)
    assert (pooled["treatment_worse"], pooled["treatment_better"]) == (9, 1)
    assert pooled["p_exact"] == 0.0215 and pooled["separable"] is True
    assert pooled["n_pairs"] == 24, "pooling must key on (candidate, check), not candidate"


def test_a_pair_is_dropped_whenever_EITHER_arm_failed_to_rule(e1):
    """The five quota failures of `bo2mosjog` all fell in arm B. A half-pair must not count."""
    rows = [_cell("c0", "legality", "llm", False),
            _cell("c0", "legality", "entity", True, ruled=False),  # treatment never ruled
            _cell("c1", "legality", "llm", False),
            _cell("c1", "legality", "entity", True)]
    m = e1._mcnemar(rows, "legality")
    assert m["n_pairs"] == 1, m
    assert (m["treatment_worse"], m["treatment_better"]) == (1, 0), m


def test_mcnemar_is_silent_rather_than_significant_when_nothing_is_discordant(e1):
    rows = _paired_rows({"legality": [(True, True), (False, False)]})
    m = e1._mcnemar(rows, "legality")
    assert m["p_exact"] is None and m["separable"] is False and m["direction"] is None


def test_the_fence_refuses_a_chain_a_provisional_brain_could_rule(e1, monkeypatch):
    """E1 must refuse a verdict chain whose tail is provisional — on CONFIG, not on the env.

    Until 2026-08-08 nothing tested this fence. It was reachable only through the ambient
    `config.yaml`: while `operator:` was trusted-only every test sailed past it, and the moment
    a `minimax` tail was added every live-path test died on it. Neither state was a test of the
    fence; both were a test of the config file.

    The assertion on the message is deliberate. The fence must name the offending provider,
    because the failure it guards against is silent: an E1 delta measured on a provisional tail
    is not a weaker number, it is a number about a different brain.
    """
    from prospector.config import load_config

    def _provisional(checks, hybrid):
        cfg = load_config()
        cfg.retrieval.hybrid_entity_checks = list(checks) if hybrid else []
        cfg.operator = ["claude_cli", "minimax"]
        return cfg

    monkeypatch.setattr(e1, "_arm_config", _provisional)
    with pytest.raises(SystemExit) as exc:
        e1._resolve_live_path(("payer_solvency",))
    msg = str(exc.value)
    assert "provisional provider" in msg, msg
    assert "minimax" in msg, msg
    # No credential is needed to reach this refusal: the fence precedes the constructors.
    assert "API_KEY" not in msg, f"fence ran after construction and reported a key instead: {msg}"
