"""The baseline harness must never print a zero where it means "could not read".

Every test here pins a way the harness could go quietly wrong. A reporting tool that fails loudly
is merely broken; one that fails by printing a plausible number is worse than not having it, and
that is the failure mode each of these covers.
"""

from __future__ import annotations

import json

import pytest

from tools import engine_baseline as eb


def _write(store, name: str, payload: dict) -> None:
    (store / "dossiers").mkdir(parents=True, exist_ok=True)
    (store / "dossiers" / name).write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    root = tmp_path / "store"
    (root / "dossiers").mkdir(parents=True)
    monkeypatch.setenv("PROSPECTOR_CORPUS_DIR", str(root / "dossiers"))
    monkeypatch.setenv("PROSPECTOR_CORPUS_DB", str(root / "prospector.db"))
    return root


def test_shares_long_run_needs_a_real_overlap():
    passage = (
        "the 2022 red diesel reform removed the off road entitlement for haulage "
        "operators across the whole of the united kingdom"
    )
    quoting = "As cited, " + passage + ", so the cost is durable."
    assert eb._shares_long_run(quoting, [passage])
    # A paraphrase shares no long literal run. This is why A7 is a LOWER bound and the harness
    # says so on the axis itself; a test that asserted otherwise would be pinning a wish.
    assert not eb._shares_long_run(
        "Fuel duty rules changed in 2022 and hauliers lost their rebate.", [passage]
    )
    # Too short to be evidence of reading rather than of coincidence.
    assert not eb._shares_long_run("the 2022 reform", [passage])


def test_null_control_reads_zero_on_unrelated_evidence():
    """The control is what gives A7 a scale. If it ever reads high, A7 means nothing."""
    pairs = [
        (
            f"rationale about topic number {i} and its many distinctive particulars here",
            [f"passage concerning subject {i} with wholly separate wording throughout it"],
        )
        for i in range(20)
    ]
    assert eb._null_control(pairs) == 0


def test_null_control_is_deterministic_across_runs():
    pairs = [
        (
            f"claim {i} " + " ".join(str(i * 7 + j) for j in range(20)),
            [f"source {i} " + " ".join(str(i * 7 + j) for j in range(20))],
        )
        for i in range(10)
    ]
    assert eb._null_control(pairs) == eb._null_control(pairs)


def test_a5_is_unobtainable_not_zero_when_no_dossier_carries_a_decision(store):
    for i in range(5):
        _write(store, f"{i}.json", {"candidate": {"candidate_id": str(i)}, "checks": []})
    scan = eb.scan_corpus()
    axis = eb.axis_a5(scan)
    assert axis.value == eb.UNOBTAINABLE, "0 passes out of 0 decisions is not a 0% yield"
    assert "decision" in axis.reason


def test_non_dossier_json_in_the_dossier_directory_is_skipped(store):
    # store/dossiers really does hold pack lint reports. Counting them as dossiers drags every
    # rate toward zero while still printing as a measurement.
    _write(
        store,
        "real.pass.json",
        {"candidate": {"candidate_id": "a"}, "decision": "pass", "checks": []},
    )
    _write(store, "c2-depth.lint.json", {"ok": True, "problems": [], "urls_checked": 3})
    scan = eb.scan_corpus()
    assert scan["dossiers"] == 1
    assert scan["non_dossier"] == 1


def test_zero_byte_dossiers_are_reported_rather_than_silently_dropped(store):
    (store / "dossiers" / "empty.pass.json").write_text("", encoding="utf-8")
    _write(
        store,
        "real.pass.json",
        {"candidate": {"candidate_id": "a"}, "decision": "pass", "checks": []},
    )
    scan = eb.scan_corpus()
    assert scan["zero_byte"] == ["empty.pass.json"]
    assert scan["dossiers"] == 1


def test_a4_picks_the_newest_run_by_timestamp_not_by_operator_name(store):
    # Filenames are <operator>_<stamp>.json. Sorting the PATHS orders by operator first, which
    # would make "claude_cli_<new>" lose to "minimax_<old>" and report a stale discrimination.
    golden = store / "golden_runs"
    golden.mkdir()
    (golden / "minimax_20260815T000000000000.json").write_text(
        json.dumps({"discrimination": 0.5, "operator": "minimax", "per_case": []})
    )
    (golden / "claude_cli_20260820T000000000000.json").write_text(
        json.dumps(
            {
                "discrimination": 1.0,
                "operator": "claude_cli",
                "per_case": [{"gate_match": True}, {"gate_match": False}],
            }
        )
    )
    axis = eb.axis_a4(store)
    assert axis.value == 100.0
    assert axis.detail["operator"] == "claude_cli"
    assert axis.detail["gate_accuracy_pct"] == 50.0


def test_a4_is_unobtainable_when_nothing_has_been_stored(store):
    axis = eb.axis_a4(store)
    assert axis.value == eb.UNOBTAINABLE
    assert "diagnose --deep" in axis.command


def test_a6_refuses_to_divide_when_no_row_carries_a_cost(store):
    (store / "prospector.jsonl").write_text(
        "\n".join(json.dumps({"event": "vet", "candidate_id": str(i)}) for i in range(4)),
        encoding="utf-8",
    )
    _write(
        store,
        "a.pass.json",
        {
            "candidate": {"candidate_id": "a"},
            "decision": "pass",
            "checks": [{"check_name": "x", "verdict": "supported"}],
        },
    )
    scan = eb.scan_corpus()
    axis = eb.axis_a6(store, scan)
    assert axis.value == eb.UNOBTAINABLE
    assert "candidate_id" in axis.reason


def test_a6_is_the_median_over_candidates_not_the_mean_over_calls(store):
    """Two calls on one candidate are ONE vet, and the axis reports the typical vet.

    Costs 0.10 + 0.10 on candidate a, 0.30 on b, 5.00 on c. Mean over CALLS is 1.375 and mean
    over candidates is 1.8333 — both dominated by c. The median vet costs 0.30, which is the
    number that answers "what does a candidate cost us".
    """
    rows = [
        {"message": "usage", "candidate_id": "a", "cost_usd": 0.10, "phase": "vetting"},
        {"message": "usage", "candidate_id": "a", "cost_usd": 0.10, "phase": "vetting"},
        {"message": "usage", "candidate_id": "b", "cost_usd": 0.30, "phase": "vetting"},
        {"message": "usage", "candidate_id": "c", "cost_usd": 5.00, "phase": "vetting"},
        {"message": "warm-up, no candidate", "cost_usd": 0.99, "phase": "main"},
    ]
    (store / "prospector.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    axis = eb.axis_a6(store, eb.scan_corpus())

    assert axis.value == 0.30, f"expected the median vet, got {axis.value}"
    assert axis.detail["candidates_priced"] == 3
    assert axis.detail["priced_calls"] == 4
    assert axis.detail["attributed_usd"] == 5.50
    assert axis.detail["unattributed_usd"] == 0.99, "a costed row with no candidate must not vanish"
    assert axis.detail["unattributed_calls"] == 1


def test_a6_reads_the_ledger_even_when_the_dossier_corpus_is_empty(store):
    """The ledger and the corpus are different populations; A6 must not join them.

    Until 2026-08-20 this axis divided total ledger spend by the corpus check count, so an empty
    corpus made a fully populated cost meter read UNOBTAINABLE — and a NON-empty corpus from a
    different month produced a quotient of two unrelated windows, which is worse, because it
    printed as a measurement.
    """
    (store / "prospector.jsonl").write_text(
        json.dumps({"message": "usage", "candidate_id": "z", "cost_usd": 0.25}), encoding="utf-8"
    )
    scan = eb.scan_corpus()
    assert scan["checks"] == 0, "this test is only meaningful against an empty corpus"

    axis = eb.axis_a6(store, scan)
    assert axis.value == 0.25
    assert axis.detail["candidates_priced"] == 1


def test_every_axis_reports_a_value_or_a_reason_never_a_blank(store):
    _write(
        store,
        "a.pass.json",
        {
            "candidate": {"candidate_id": "a"},
            "decision": "pass",
            "checks": [{"check_name": "x", "verdict": "supported"}],
        },
    )
    report = eb.build_report(store, ["minimax"])
    assert len(report["axes"]) == 8
    for axis in report["axes"]:
        if axis["value"] == eb.UNOBTAINABLE:
            assert axis["reason"].strip(), f"{axis['id']} is unobtainable with no reason given"
        else:
            assert axis["value"] is not None
    # The renderer must survive every axis being unreadable.
    assert "UNOBTAINABLE AXES" in eb.render(report)
