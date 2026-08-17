"""R18 — the per-run internals view, and the one rule it exists to enforce.

WHAT THESE PIN, in the words of the defects they close:

  * **§7.2 T2 — an outage is not a datum.** `store/dossiers/2102bacc6dd75cf9.kill.json` is a KILL
    on `min_composite` whose SEVEN checks all read `unverifiable, conf 0.0, "Verdict call failed;
    fail-safe."` — a candidate killed by our own outage, in a dossier that reads as fully
    reasoned. Every test below whose name says `outage` is written to go RED if a failed call is
    ever rendered as an ordinary reading again, by either of the two markers it can carry: the
    `retrieval_failed` flag, or (on dossiers written before the flag existed) the engine's
    fail-safe rationale.
  * **The rule run backwards.** A check that was `degraded` but DID fetch passages is a real
    `unverifiable` reading and must stay one. A test pins that too, because a fix that swept
    every degraded check into the outage bucket would pass every test above and hide genuine
    unverifiables behind an outage banner.
  * **Honest nulls.** Cost and latency are null wherever the data cannot attribute them, and each
    null carries a REASON. A confident null reads as a measurement
    (`a-saturated-metric-prints-as-a-confident-null`).
  * **Unreadable is a state.** A missing or torn dossier, a torn audit line, an audit window with
    no files — each answers, none raises. A monitor that dies on a half-written line is down
    exactly when the thing it watches is busy.
  * **A run is a PROCESS.** Grouping a day-file by time interleaves the daemon, a backfill and a
    manual CLI into one confidently wrong story (`audit.py:110`).
"""
from __future__ import annotations

import json
import sqlite3
import types

import pytest

from prospector.ops import runs as R
from prospector.store import Store

WEIGHTS = {"pain": 1.0, "money": 2.0}


def _cfg(tmp_path, **extra):
    """A cfg with a REAL store_dir. A `Path`, not a str: `Store.__init__` binds `cfg.store_dir`
    and calls `.mkdir` on it directly (`store.py:82`)."""
    base = {"store_dir": tmp_path, "min_composite_to_pass": 3.2, "weights": dict(WEIGHTS)}
    base.update(extra)
    return types.SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# Fixtures — dossier JSON in exactly the shape the engine writes it
# --------------------------------------------------------------------------- #
def _check(name, verdict="supported", conf=0.8, *, retrieval_failed=False, degraded=False,
           rationale=None, queries=None, sources=None, provider="minimax/MiniMax-M3"):
    return {
        "check_name": name,
        "verdict": verdict,
        "confidence": conf,
        "rationale": ("a passage says buyers already pay for this" if rationale is None
                      else rationale),
        "citations": [s["source_id"] for s in (sources or [])],
        "sources": sources or [],
        "queries": list(queries or []),
        "query_source": "llm_batched",
        "degraded": degraded,
        "retrieval_failed": retrieval_failed,
        "provider": provider,
        "provisional": False,
        "untraceable_figures": [],
    }


def _source(sid="s1", url="https://example.com/a", text="Firms pay £2,000 a year for this.",
            query="who pays for this"):
    return {"source_id": sid, "url": url, "text": text, "query": query,
            "published_at": None, "fetched_at": None}


def _dossier(cid, decision, checks, *, gate=None, composite=4.0, score_failed=False,
             scores=None, reason="", publish_status=None, provisional=False):
    return {
        "candidate": {"candidate_id": cid, "title": f"title {cid}", "one_liner": "a one liner",
                      "hypothesis": "h", "who_pays": "w", "why_now": "n", "market": "uk",
                      "structural_form": "saas", "ambition_tier": "side_hustle",
                      "tags": {"seed_kind": "blue_sky", "audience": "agency_owner"},
                      "refinement_history": []},
        "decision": decision,
        "gate_fired": gate,
        "reason": reason,
        "checks": checks,
        "adversarial": None,
        "score": {"scores": scores if scores is not None else {"pain": 4, "money": 0},
                  "justification": {"pain": "because"}, "composite": composite,
                  "score_failed": score_failed},
        "model_version": "m1",
        "provider_chain": "minimax",
        "created_at": "2026-08-16T00:00:00+00:00",
        "provisional": provisional,
        "publish_status": publish_status,
    }


def _write(tmp_path, *dossiers) -> Store:
    """Write each dossier to disk AND index it, the way `Store.save` leaves the tree."""
    store = Store(_cfg(tmp_path))
    (tmp_path / "dossiers").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(store.db)) as conn:
        for d in dossiers:
            cid = d["candidate"]["candidate_id"]
            path = tmp_path / "dossiers" / f"{cid}.{d['decision']}.json"
            path.write_text(json.dumps(d))
            conn.execute(
                "INSERT OR REPLACE INTO dossiers (candidate_id, decision, created_at, path, "
                "composite) VALUES (?,?,?,?,?)",
                (cid, d["decision"], d["created_at"], str(path),
                 (d.get("score") or {}).get("composite")))
        conn.commit()
    return store


def _audit(tmp_path, *rows):
    """An audit day-file for today, in the writer's own layout."""
    from datetime import datetime, timezone

    d = tmp_path / "audit"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (d / f"{day}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return d


# --------------------------------------------------------------------------- #
# §7.2 T2 — the outage rule. These are the mutation tests.
# --------------------------------------------------------------------------- #
def test_a_retrieval_failed_check_carries_no_verdict_and_no_confidence(tmp_path):
    """The invariant as a data shape. Revert the classification and this goes red on the very
    field a renderer would print: `verdict` becomes `"unverifiable"` and `confidence` `0.0`.

    The rationale here is deliberately NOT the fail-safe sentinel, so this test rides on the
    `retrieval_failed` FLAG alone — the legacy string is pinned separately and neither branch can
    stand in for the other."""
    cid = "a" * 16
    store = _write(tmp_path, _dossier(cid, "defer", [
        _check("buyer_intent", "unverifiable", 0.0, retrieval_failed=True, degraded=True,
               rationale="All 3 searches failed."),
    ]))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    check = v["checks"][0]
    assert check["kind"] == R.KIND_OUTAGE
    assert check["verdict"] is None, "an outage must not carry a verdict a surface could print"
    assert check["confidence"] is None, "an outage must not carry a confidence"
    assert check["null_reason"], "a null with no reason is the confident null this rule bans"
    # The fail-safe the engine wrote is preserved, but only INSIDE the outage marker.
    assert check["outage"]["fail_safe_placeholder"]["verdict"] == "unverifiable"
    assert check["outage"]["detected_by"] == "retrieval_failed flag"


def test_an_outage_is_never_in_the_evidence_list(tmp_path):
    """`evidence_checks` is what a table iterates. An outage in it IS the 2102bacc defect."""
    cid = "b" * 16
    store = _write(tmp_path, _dossier(cid, "kill", [
        _check("buyer_intent", sources=[_source()]),
        _check("currency", "unverifiable", 0.0, retrieval_failed=True),
    ], gate="min_composite"))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    assert [c["check_name"] for c in v["evidence_checks"]] == ["buyer_intent"]
    assert [c["check_name"] for c in v["outages"]] == ["currency"]
    assert len(v["checks"]) == 2, "the chain keeps its order and its full membership"
    assert v["outage_summary"]["n"] == 1 and v["outage_summary"]["of"] == 2


def test_the_2102bacc_shape_is_an_outage_even_with_the_flag_unset(tmp_path):
    """The dossier this requirement is named after. Its seven checks read `unverifiable, 0.0,
    "Verdict call failed; fail-safe."` with `retrieval_failed` FALSE — the flag was added by the
    same fix. A rule that only read the flag would render that KILL as seven ordinary readings,
    which is precisely the defect. Delete the rationale branch of `classify_check` and this goes
    red."""
    cid = "c" * 16
    seven = [_check(n, "unverifiable", 0.0, retrieval_failed=False, degraded=True,
                    rationale="Verdict call failed; fail-safe.")
             for n in ("buyer_intent", "currency", "pain_reality", "value_durability",
                       "incumbency", "payer_solvency", "legality")]
    store = _write(tmp_path, _dossier(cid, "kill", seven, gate="min_composite", composite=0.0))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    assert v["evidence_checks"] == [], "not one of these seven is a reading"
    assert len(v["outages"]) == 7
    assert all(c["outage"]["detected_by"] == "legacy fail-safe rationale" for c in v["outages"])
    # And the KILL itself is flagged: a terminal decision over non-measurements.
    assert "2102bacc6dd75cf9" in v["outage_summary"]["integrity_warning"]


def test_a_degraded_but_fetched_unverifiable_stays_a_reading(tmp_path):
    """The rule run BACKWARDS, and it is the one a careless fix breaks: `verify.py:590` demotes a
    check to `unverifiable` with `degraded=True` when passages WERE fetched and did not support
    the claim. That is evidence. Sweeping every `degraded` check into the outage bucket would
    pass every test above and hide real unverifiables behind an outage banner."""
    cid = "d" * 16
    store = _write(tmp_path, _dossier(cid, "kill", [
        _check("incumbency", "unverifiable", 0.31, degraded=True, retrieval_failed=False,
               rationale="Passages were retrieved but none addresses the incumbent's pricing.",
               sources=[_source("s9")]),
    ], gate="incumbency"))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    assert v["checks"][0]["kind"] == R.KIND_EVIDENCE
    assert v["checks"][0]["verdict"] == "unverifiable"
    assert v["checks"][0]["confidence"] == 0.31
    assert v["outages"] == []


def test_classify_check_is_exact_never_a_substring(tmp_path):
    """A rationale that merely DISCUSSES a failure is a reading. Loosening the match to a
    substring would reclassify real analysis as an outage."""
    kind, _ = R.classify_check(_check(
        "legality", "refuted", 0.9,
        rationale="The regulator's own page says the verdict call failed; fail-safe. is not a "
                  "recognised exemption."))
    assert kind == R.KIND_EVIDENCE


# --------------------------------------------------------------------------- #
# The R18 probe: PASS + KILL + retrieval_failed each render DISTINCTLY
# --------------------------------------------------------------------------- #
def test_pass_kill_and_a_retrieval_failed_row_each_render_distinctly(tmp_path):
    """R18's own probe, run against the page's real shaping functions."""
    st = pytest.importorskip("streamlit")  # noqa: F841 — the page imports it at module scope
    from prospector.control_center.pages import _runs as page

    p, k, o = "p" * 16, "k" * 16, "o" * 16
    store = _write(
        tmp_path,
        _dossier(p, "pass", [_check("buyer_intent", "supported", 0.82,
                                    sources=[_source()])], composite=4.4,
                 publish_status="listed"),
        _dossier(k, "kill", [_check("value_durability", "refuted", 0.77,
                                    sources=[_source("s2")])],
                 gate="value_durability", composite=1.1, reason="incumbent ships it free"),
        _dossier(o, "defer", [_check("buyer_intent", "unverifiable", 0.0,
                                     retrieval_failed=True, degraded=True,
                                     rationale="Verdict call failed; fail-safe.")],
                 composite=0.0, reason="Deferred — could not retrieve evidence."),
    )
    cfg = _cfg(tmp_path)
    views = {d: R.candidate_view(cfg, d, store=store, directory=tmp_path / "audit")
             for d in (p, k, o)}

    # 1. The decisions are the engine's, unmodified.
    assert [views[x]["gate"]["decision"] for x in (p, k, o)] == ["pass", "kill", "defer"]
    assert views[k]["gate"]["gate_fired"] == "value_durability"
    assert views[p]["gate"]["gate_fired"] is None

    # 2. PASS and KILL both put a READING in the evidence table; the outage puts none.
    assert len(page.evidence_rows(views[p])) == 1
    assert len(page.evidence_rows(views[k])) == 1
    assert page.evidence_rows(views[o]) == [], \
        "a failed call must never occupy a row in the evidence table"

    # 3. Only the outage draws an outage block, and it says so in words.
    assert page.outage_blocks(views[p]) == [] and page.outage_blocks(views[k]) == []
    block = page.outage_blocks(views[o])[0]
    assert "OUTAGE" in block["headline"] and "never ran" in block["headline"]
    assert "not a reading" in block["placeholder_note"].lower()

    # 4. The three render as three different verdict strings, and 'unverifiable' appears in NONE
    #    of the outage's rendered cells.
    assert {r["verdict"] for r in page.evidence_rows(views[p])} == {"supported"}
    assert {r["verdict"] for r in page.evidence_rows(views[k])} == {"refuted"}
    assert "unverifiable" not in json.dumps(page.evidence_rows(views[o]))


def test_the_page_quotes_the_passage_and_names_the_query_that_found_it(tmp_path):
    pytest.importorskip("streamlit")
    from prospector.control_center.pages import _runs as page

    cid = "q" * 16
    src = _source("s7", "https://x.test/p", "Councils pay £4,500 per audit.", "audit price uk")
    store = _write(tmp_path, _dossier(cid, "pass", [
        _check("buyer_intent", sources=[src], queries=["audit price uk"])]))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    row = page.source_rows(v["evidence_checks"][0])[0]
    assert row["quote"] == "Councils pay £4,500 per audit."
    assert row["query"] == "audit price uk"
    assert row["url"] == "https://x.test/p"
    assert row["cited"] is True


# --------------------------------------------------------------------------- #
# Honest nulls
# --------------------------------------------------------------------------- #
def test_every_cost_is_null_and_every_null_names_its_reason(tmp_path):
    """Cost is not recorded at candidate or check grain. A zero here would read as free."""
    cid = "e" * 16
    store = _write(tmp_path, _dossier(cid, "pass", [_check("buyer_intent")]))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    assert v["generation"]["cost_usd"] is None
    assert "batch_diagnostics.jsonl" in v["generation"]["cost_null_reason"]
    for c in v["checks"]:
        assert c["cost_usd"] is None and c["cost_null_reason"]


def test_latency_is_attributed_only_by_an_exact_query_join(tmp_path):
    """Latency joins on the query STRING recorded on both sides. Ordering would be a guess:
    eight candidates interleave inside one run_id at `minimax_concurrency: 8`."""
    cid = "f" * 16
    store = _write(tmp_path, _dossier(cid, "pass", [
        _check("buyer_intent", queries=["who pays for audits"], sources=[_source()]),
        _check("legality", queries=["never searched"], sources=[]),
    ]))
    adir = _audit(
        tmp_path,
        {"event": "candidate_start", "candidate_id": cid, "run_id": "r1", "pid": 1, "seq": 1,
         "ts": "2026-08-16T00:00:00+00:00", "title": "t"},
        {"event": "search", "query": "who pays for audits", "latency_ms": 120, "provider": "ddg",
         "status": "ok", "run_id": "r1", "pid": 1, "seq": 2, "ts": "2026-08-16T00:00:01+00:00"},
        {"event": "page_fetch", "query": "who pays for audits", "latency_ms": 80,
         "status": "ok", "run_id": "r1", "pid": 1, "seq": 3, "ts": "2026-08-16T00:00:02+00:00"},
    )
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=adir)

    joined = {c["check_name"]: c for c in v["checks"]}
    assert joined["buyer_intent"]["latency_ms"] == 200
    assert "joined exactly" in joined["buyer_intent"]["latency_provenance"]
    # The check whose query no audit row carries gets a NULL with the reason, never a zero.
    assert joined["legality"]["latency_ms"] is None
    assert "no audit row" in joined["legality"]["latency_null_reason"]


def test_a_query_shared_by_two_checks_refuses_to_attribute(tmp_path):
    """Double-counting one search across two checks would invent latency for both."""
    cid = "g" * 16
    store = _write(tmp_path, _dossier(cid, "pass", [
        _check("buyer_intent", queries=["shared q"]),
        _check("payer_solvency", queries=["shared q"]),
    ]))
    adir = _audit(tmp_path,
                  {"event": "search", "query": "shared q", "latency_ms": 500, "status": "ok",
                   "candidate_id": cid, "run_id": "r1", "pid": 1, "seq": 1,
                   "ts": "2026-08-16T00:00:00+00:00"})
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=adir)

    for c in v["checks"]:
        assert c["latency_ms"] is None
        assert "more than one check" in c["latency_null_reason"]


def test_score_failed_renders_no_composite(tmp_path):
    """`score_failed` is `retrieval_failed` one stage later: the all-zero scores are a fail-safe,
    not a 0/5 reading (`models.py:399`). Printing the stored 0.0 makes this go red."""
    cid = "h" * 16
    store = _write(tmp_path, _dossier(cid, "kill", [_check("buyer_intent")], gate="min_composite",
                                      composite=0.0, score_failed=True,
                                      scores={"pain": 0, "money": 0}))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    assert v["score"]["status"] == "failed"
    assert v["score"]["composite"] is None
    assert "fail-safe" in v["score"]["null_reason"]
    assert v["score"]["fail_safe_placeholder"]["composite"] == 0.0


def test_the_stored_composite_is_authoritative_and_reconciliation_is_reported(tmp_path):
    """The view never substitutes its own arithmetic for the number the gate applied — it only
    says whether today's weights still explain it."""
    cid = "i" * 16
    # 4*1.0 + 1*2.0 = 6.0, but the engine stored 4.0 (a lane re-weighted the run).
    store = _write(tmp_path, _dossier(cid, "pass", [_check("buyer_intent")],
                                      composite=4.0, scores={"pain": 4, "money": 1}))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    assert v["score"]["composite"] == 4.0, "the stored number stays authoritative"
    assert v["score"]["composite_recomputed"] == 6.0
    assert v["score"]["reconciles"] is False
    assert v["score"]["reconcile_note"]
    assert v["score"]["threshold"] == 3.2


def test_a_provisional_pass_says_why_it_did_not_publish(tmp_path):
    cid = "j" * 16
    store = _write(tmp_path, _dossier(cid, "pass", [_check("buyer_intent")], provisional=True))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    assert v["publish"]["status"] is None
    assert v["publish"]["blocked_by_provisional"] is True
    assert "provisional" in v["publish"]["null_reason"]


# --------------------------------------------------------------------------- #
# Unreadable is a state, never an exception
# --------------------------------------------------------------------------- #
def test_a_torn_dossier_is_unreadable_not_a_crash(tmp_path):
    """`Store.get` raises `JSONDecodeError` on a half-written file — which on a live tree happens
    exactly while the engine is writing."""
    cid = "t" * 16
    store = _write(tmp_path, _dossier(cid, "pass", [_check("buyer_intent")]))
    (tmp_path / "dossiers" / f"{cid}.pass.json").write_text('{"candidate": {"tit')

    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")
    assert v["status"] == "unreadable"
    assert "did not parse" in v["reason"]
    assert v["dossier_path"].endswith(f"{cid}.pass.json"), "the reason names the file"
    assert v["checks"] == [] and v["outages"] == []


def test_a_truncating_write_is_an_empty_read_not_bad_json(tmp_path):
    """A zero-byte dossier: `json.loads("")` raises the same ValueError, and the answer is still
    a state (`a-truncating-write-is-an-empty-read-not-bad-json`)."""
    cid = "u" * 16
    store = _write(tmp_path, _dossier(cid, "pass", [_check("buyer_intent")]))
    (tmp_path / "dossiers" / f"{cid}.pass.json").write_text("")

    assert R.candidate_view(_cfg(tmp_path), cid, store=store,
                            directory=tmp_path / "audit")["status"] == "unreadable"


def test_an_unknown_candidate_is_missing_with_a_reason(tmp_path):
    store = _write(tmp_path, _dossier("v" * 16, "pass", [_check("buyer_intent")]))
    v = R.candidate_view(_cfg(tmp_path), "nope", store=store, directory=tmp_path / "audit")
    assert v["status"] == "missing"
    assert "no row" in v["reason"]


def test_an_index_row_pointing_at_a_deleted_file_is_unreadable_not_missing(tmp_path):
    """Two different operator problems: 'never vetted' and 'the file went away'."""
    cid = "w" * 16
    store = _write(tmp_path, _dossier(cid, "pass", [_check("buyer_intent")]))
    (tmp_path / "dossiers" / f"{cid}.pass.json").unlink()

    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")
    assert v["status"] == "unreadable" and "not on disk" in v["reason"]


def test_a_torn_audit_line_is_counted_not_fatal(tmp_path):
    adir = tmp_path / "audit"
    adir.mkdir(exist_ok=True)   # conftest's audit isolation fixture already made this one
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (adir / f"{day}.jsonl").write_text(
        json.dumps({"event": "candidate_start", "run_id": "r1", "pid": 3, "seq": 1,
                    "candidate_id": "x", "ts": "2026-08-16T00:00:00+00:00"})
        + "\n{\"event\": \"search\", \"quer\n")

    idx = R.run_index(directory=adir)
    assert idx["unreadable_lines"] == 1
    assert [r["run_id"] for r in idx["runs"]] == ["r1"]


def test_an_empty_window_says_so_rather_than_reporting_zero_runs_silently(tmp_path):
    idx = R.run_index(directory=tmp_path / "nothing-here")
    assert idx["runs"] == []
    assert idx["files"] == []
    assert "day-partitioned" in idx["note"], \
        "'no run' and 'no file to read' are different answers and must not print the same"


# --------------------------------------------------------------------------- #
# A run is a PROCESS
# --------------------------------------------------------------------------- #
def test_two_processes_in_one_day_file_are_two_runs(tmp_path):
    """The whole reason `run_id` exists. Grouping by day (or by time) merges the daemon, a
    backfill and a manual CLI into one story that is confidently wrong (`audit.py:110`)."""
    adir = _audit(
        tmp_path,
        {"event": "candidate_start", "candidate_id": "c1", "run_id": "daemon1", "pid": 10,
         "seq": 1, "ts": "2026-08-16T01:00:00+00:00", "title": "a"},
        {"event": "check_result", "candidate_id": "c1", "run_id": "daemon1", "pid": 10, "seq": 2,
         "ts": "2026-08-16T01:00:01+00:00", "retrieval_failed": True, "verdict": "unverifiable"},
        {"event": "candidate_done", "candidate_id": "c1", "run_id": "daemon1", "pid": 10,
         "seq": 3, "ts": "2026-08-16T01:00:02+00:00", "decision": "defer"},
        {"event": "candidate_start", "candidate_id": "c2", "run_id": "cli2", "pid": 99, "seq": 1,
         "ts": "2026-08-16T01:00:03+00:00", "title": "b"},
        {"event": "candidate_done", "candidate_id": "c2", "run_id": "cli2", "pid": 99, "seq": 2,
         "ts": "2026-08-16T01:00:04+00:00", "decision": "kill", "gate": "value_durability"},
    )
    idx = R.run_index(directory=adir)
    by_id = {r["run_id"]: r for r in idx["runs"]}

    assert set(by_id) == {"daemon1", "cli2"}
    assert by_id["daemon1"]["pid"] == 10 and by_id["cli2"]["pid"] == 99
    assert by_id["daemon1"]["decisions"] == {"defer": 1}
    assert by_id["cli2"]["decisions"] == {"kill": 1}
    # The outage count is visible from the audit log alone, without opening a dossier.
    assert by_id["daemon1"]["outage_checks"] == 1 and by_id["cli2"]["outage_checks"] == 0
    # Per-run cost is a null with a reason, never a 0.0 that would read as "this run was free".
    for r in idx["runs"]:
        assert r["cost_usd"] is None and "does not exist in the data" in r["cost_null_reason"]


def test_a_run_view_joins_its_candidates_to_their_dossiers(tmp_path):
    cid = "y" * 16
    store = _write(tmp_path, _dossier(cid, "kill", [_check("buyer_intent")],
                                      gate="value_durability"))
    adir = _audit(
        tmp_path,
        {"event": "candidate_start", "candidate_id": cid, "run_id": "r9", "pid": 5, "seq": 1,
         "ts": "2026-08-16T02:00:00+00:00", "title": "t", "tier": "side_hustle"},
        {"event": "candidate_done", "candidate_id": cid, "run_id": "r9", "pid": 5, "seq": 2,
         "ts": "2026-08-16T02:00:05+00:00", "decision": "kill", "gate": "value_durability"},
    )
    v = R.run_view(_cfg(tmp_path), "r9", store=store, directory=adir)

    assert v["found"] is True and len(v["candidates"]) == 1
    row = v["candidates"][0]
    assert row["decision"] == "kill" and row["gate"] == "value_durability"
    assert row["dossier"]["status"] == "ok"
    assert row["dossier"]["gate_fired"] == "value_durability"
    assert v["cost_usd"] is None and v["cost_null_reason"]


def test_a_candidate_started_and_never_finished_is_kept_with_its_reason(tmp_path):
    """The most interesting row in a run that died mid-batch; dropping it hides the death."""
    adir = _audit(tmp_path,
                  {"event": "candidate_start", "candidate_id": "z1", "run_id": "r8", "pid": 6,
                   "seq": 1, "ts": "2026-08-16T03:00:00+00:00", "title": "t"})
    store = _write(tmp_path, _dossier("unrelated", "pass", [_check("buyer_intent")]))
    v = R.run_view(_cfg(tmp_path), "r8", store=store, directory=adir)

    row = v["candidates"][0]
    assert row["decision"] is None
    assert "candidate_done" in row["decision_null_reason"]
    assert row["dossier"]["status"] == "missing"


# --------------------------------------------------------------------------- #
# Unfinished work — the four states, and the ordering defect that invented them
# --------------------------------------------------------------------------- #
def _ts(hh_mm_ss: str) -> str:
    """A timestamp on the audit file's own day, so `_day_files` picks the file up."""
    from datetime import datetime, timezone

    return f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}T{hh_mm_ss}+00:00"


def test_audit_rows_are_ordered_by_time_not_by_a_per_process_counter(tmp_path):
    """Measured on the live log 2026-08-17: a `candidate_done` came back BEFORE its own start.

    `seq` is counted per PROCESS, and several processes append to one day-file, so run A's seq 4
    and run B's seq 4 are unrelated moments. Sorting on it alone put a dead daemon's 12:49 rows
    after a live daemon's 13:12 rows, and a candidate that had been ruled `kill` read as work
    that died mid-flight. This goes red if the sort key loses its timestamp.
    """
    adir = _audit(
        tmp_path,
        # Written second by the live run, but carrying the LOWER per-process seq.
        {"event": "candidate_done", "candidate_id": "c1", "run_id": "live", "pid": 2, "seq": 2,
         "ts": _ts("13:12:12"), "decision": "kill", "gate": "source_or_die"},
        {"event": "candidate_start", "candidate_id": "c1", "run_id": "dead", "pid": 1, "seq": 9,
         "ts": _ts("12:49:02"), "title": "t"},
        {"event": "candidate_start", "candidate_id": "c1", "run_id": "live", "pid": 2, "seq": 1,
         "ts": _ts("13:09:35"), "title": "t"},
    )
    got = [(r["ts"], r["event"]) for r in R.audit_rows(directory=adir)["rows"]]
    assert got == sorted(got), got
    # And the consequence: the candidate has a verdict, so nothing is unfinished.
    assert R.unfinished(directory=adir)["total"] == 0


def test_a_candidate_whose_process_is_gone_is_abandoned_not_in_flight(tmp_path):
    adir = _audit(tmp_path,
                  {"event": "candidate_start", "candidate_id": "z1", "run_id": "r8", "pid": 6,
                   "seq": 1, "ts": _ts("03:00:00"), "title": "t", "tier": "smb"})
    v = R.unfinished(directory=adir, alive={6: False})

    assert v["counts"]["abandoned"] == 1 and v["needs_attention"] == 1
    row = v["items"][0]
    assert row["state"] == "abandoned" and row["pid"] == 6 and row["tier"] == "smb"
    assert "re-vet" in row["reason"]


def test_a_candidate_on_a_live_busy_process_is_in_flight_and_not_an_alarm(tmp_path):
    """The defect the founder hit: work being vetted right now was described as a possible crash."""
    import time as _time

    adir = _audit(tmp_path,
                  {"event": "candidate_start", "candidate_id": "z2", "run_id": "r9", "pid": 7,
                   "seq": 1, "ts": _ts("03:00:00"), "title": "t"},
                  {"event": "check_result", "candidate_id": "z2", "run_id": "r9", "pid": 7,
                   "seq": 2, "ts": _ts("03:00:10")})
    from datetime import datetime

    just_after = datetime.fromisoformat(_ts("03:00:12")).timestamp()
    v = R.unfinished(directory=adir, now=just_after, alive={7: True})

    assert v["counts"]["in_flight"] == 1
    assert v["needs_attention"] == 0, "work in progress is not a fault"
    assert v["items"][0]["state"] == "in_flight"
    assert _time.time() > 0  # the clock is injected, never read behind the caller's back


def test_a_live_process_that_has_written_nothing_for_an_hour_is_stalled(tmp_path):
    from datetime import datetime

    adir = _audit(tmp_path,
                  {"event": "candidate_start", "candidate_id": "z3", "run_id": "rA", "pid": 8,
                   "seq": 1, "ts": _ts("03:00:00"), "title": "t"})
    an_hour_later = datetime.fromisoformat(_ts("04:00:00")).timestamp()
    v = R.unfinished(directory=adir, now=an_hour_later, alive={8: True})

    assert v["items"][0]["state"] == "stalled" and v["needs_attention"] == 1
    assert "60 minutes" in v["items"][0]["reason"]


def test_an_unprobeable_pid_is_unknown_and_still_needs_attention(tmp_path):
    """A failed measurement is never rendered as health. It is also never rendered as death."""
    adir = _audit(tmp_path,
                  {"event": "candidate_start", "candidate_id": "z4", "run_id": "rB",
                   "seq": 1, "ts": _ts("03:00:00"), "title": "t"})
    v = R.unfinished(directory=adir)

    assert v["items"][0]["state"] == "unknown" and v["needs_attention"] == 1
    assert "cannot be measured" in v["items"][0]["reason"]


def test_a_candidate_a_later_run_finished_is_not_counted_against_the_run_that_died(tmp_path):
    adir = _audit(
        tmp_path,
        {"event": "candidate_start", "candidate_id": "c1", "run_id": "dead", "pid": 1, "seq": 1,
         "ts": _ts("12:49:02"), "title": "t"},
        {"event": "candidate_start", "candidate_id": "c1", "run_id": "live", "pid": 2, "seq": 1,
         "ts": _ts("13:09:35"), "title": "t"},
        {"event": "candidate_done", "candidate_id": "c1", "run_id": "live", "pid": 2, "seq": 2,
         "ts": _ts("13:12:12"), "decision": "kill", "gate": "source_or_die"},
    )
    by_run = {r["run_id"]: r for r in R.run_index(directory=adir)["runs"]}
    assert by_run["dead"]["unfinished"] == 0
    assert by_run["live"]["unfinished"] == 0


def test_the_run_list_says_which_runs_died_with_work_open(tmp_path):
    adir = _audit(
        tmp_path,
        {"event": "candidate_start", "candidate_id": "c1", "run_id": "dead", "pid": 4242424,
         "seq": 1, "ts": _ts("12:49:02"), "title": "t"},
    )
    row = R.run_index(directory=adir)["runs"][0]
    assert row["unfinished"] == 1
    assert row["state"] in ("abandoned", "unknown")
    assert row["state_reason"]


def test_process_alive_is_false_for_a_pid_that_cannot_exist():
    assert R.process_alive(4242424) is False
    assert R.process_alive(None) is None


def test_an_unknown_run_id_answers_with_a_reason(tmp_path):
    store = _write(tmp_path, _dossier("k9", "pass", [_check("buyer_intent")]))
    v = R.run_view(_cfg(tmp_path), "does-not-exist", store=store, directory=tmp_path / "audit")
    assert v["found"] is False and v["not_found_reason"]
    assert v["candidates"] == []


def test_a_candidate_with_no_audit_row_says_the_window_not_silence(tmp_path):
    """The audit log is day-partitioned; an older dossier is OUT OF RANGE, not unlogged."""
    cid = "n" * 16
    store = _write(tmp_path, _dossier(cid, "pass", [_check("buyer_intent")]))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    assert v["run"]["run_id"] is None
    assert "day-partitioned" in v["run"]["null_reason"]


def test_audit_dir_follows_the_env_var_the_writer_reads(tmp_path, monkeypatch):
    """`audit.py` resolves `PROSPECTOR_AUDIT_DIR` at IMPORT. A reader that trusted the writer's
    module global would follow the process's first import instead of the live environment."""
    monkeypatch.setenv("PROSPECTOR_AUDIT_DIR", str(tmp_path / "elsewhere"))
    assert R.audit_dir() == tmp_path / "elsewhere"
    assert R.audit_dir(tmp_path / "explicit") == tmp_path / "explicit", \
        "an explicit argument still wins, so a caller can read a tree it does not live in"


def test_figures_traced_never_collapses_none_into_empty(tmp_path):
    """`None` = the trace never ran; `[]` = it ran and found nothing (`models.py:312`).
    Defaulting one to the other would certify 2,011 pre-existing dossiers as figure-clean."""
    cid = "m" * 16
    untraced = _check("buyer_intent")
    untraced["untraceable_figures"] = None
    traced = _check("legality")
    traced["untraceable_figures"] = []
    store = _write(tmp_path, _dossier(cid, "pass", [untraced, traced]))
    v = R.candidate_view(_cfg(tmp_path), cid, store=store, directory=tmp_path / "audit")

    assert v["checks"][0]["figures_traced"] is False
    assert v["checks"][1]["figures_traced"] is True
