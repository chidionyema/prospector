"""Runs — one run, every candidate, every check, and the outages named as outages.

OPS_CONSOLE_PROGRAM R18 (ask 4), rendered from `prospector.ops.runs` — the same derivation the
Telegram surface would call. This renderer computes nothing: the decision, the gate, the composite
and the publish status are shown as the engine WROTE them (`one-reader-two-caller-shapes`).

THE ONE RENDERING RULE THIS PAGE EXISTS FOR (§7.2 T2). A check whose verdict call failed is drawn
as an **outage marker**, in its own block, never as a row in the evidence table. `evidence_rows()`
below is the whole enforcement: it filters on `kind`, and the read model has already set
`verdict`/`confidence` to `None` on an outage, so there is no reading to leak into a table even if
someone widened the filter. The defect this closes is on disk —
`store/dossiers/2102bacc6dd75cf9.kill.json`, a KILL on `min_composite` whose seven checks all read
`unverifiable, conf 0.0, "Verdict call failed; fail-safe."`: a candidate killed by our own outage,
in a dossier that reads as fully reasoned.

`evidence_rows`, `outage_blocks` and `source_rows` are module-level and pure so the rendering rule
is testable without a Streamlit runtime — a rule that can only be checked by looking at a screen
is a rule that regresses.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from prospector.control_center.components.chrome import page_hero
from prospector.ops import readmodel as _rm
from prospector.ops import runs as _runs

#: What a null renders as. One dash everywhere, always paired with the REASON beside it — a bare
#: dash with no reason is the confident null this console exists to stop
#: (`a-saturated-metric-prints-as-a-confident-null`).
DASH = "—"


def _num(value, suffix: str = "") -> str:
    return DASH if value is None else f"{value}{suffix}"


# --------------------------------------------------------------------------- #
# Pure shaping — the rendering rule lives here so a test can hold it
# --------------------------------------------------------------------------- #
def evidence_rows(view: dict) -> list[dict]:
    """The check table. EVIDENCE checks only — an outage has no reading to tabulate.

    Filtering here rather than at the call site is deliberate: one table builder, one filter, so a
    new panel cannot reintroduce the mixed table by iterating `view["checks"]` itself.
    """
    rows = []
    for c in view.get("checks") or []:
        if c.get("kind") != _runs.KIND_EVIDENCE:
            continue
        conf = c.get("confidence")
        rows.append({
            "check": c.get("check_name"),
            "verdict": c.get("verdict"),
            "confidence": DASH if conf is None else f"{float(conf):.2f}",
            "provider": c.get("provider") or DASH,
            "sources": c.get("n_sources"),
            "queries": len(c.get("queries") or []),
            "latency": (f"{c['latency_ms']} ms" if c.get("latency_ms") is not None
                        else DASH),
            "cost": DASH,
            "provisional": "yes" if c.get("provisional") else DASH,
        })
    return rows


def outage_blocks(view: dict) -> list[dict]:
    """One block per failed call: the check, why it is an outage, and the placeholder it left.

    Deliberately NOT a table. An outage rendered as a row acquires the visual authority of the
    readings around it, which is the whole defect: the KILL that started this looks reasoned
    because seven non-measurements were laid out exactly like seven measurements.
    """
    return [{
        "check": c.get("check_name"),
        "headline": f"OUTAGE — {c.get('check_name')} never ran",
        "why": (c.get("outage") or {}).get("why", ""),
        "detected_by": (c.get("outage") or {}).get("detected_by", ""),
        "placeholder": (c.get("outage") or {}).get("fail_safe_placeholder", {}),
        "placeholder_note": (c.get("outage") or {}).get("placeholder_note", ""),
        "provider": c.get("provider") or DASH,
    } for c in (view.get("outages") or [])]


def source_rows(check: dict, *, quote_chars: int = 400) -> list[dict]:
    """The passages a check quoted, with the query that surfaced each one."""
    return [{
        "query": s.get("query") or DASH,
        "url": s.get("url") or DASH,
        "quote": (s.get("quote") or "")[:quote_chars],
        "source_id": s.get("source_id"),
        "cited": s.get("source_id") in (check.get("citations") or []),
    } for s in (check.get("sources") or [])]


def run_rows(index: dict) -> list[dict]:
    """The run picker's table: what each process actually did."""
    return [{
        "run_id": r["run_id"],
        "pid": r.get("pid"),
        "from": (r.get("first_ts") or DASH),
        "to": (r.get("last_ts") or DASH),
        "candidates": r.get("candidates"),
        "decisions": " · ".join(f"{k} {v}" for k, v in sorted((r.get("decisions") or {}).items()))
                     or DASH,
        "checks": r.get("checks"),
        "outages": r.get("outage_checks"),
        "searches": f"{r.get('searches')} ({r.get('search_errors')} err)",
        "cost": DASH,
    } for r in (index.get("runs") or [])]


# --------------------------------------------------------------------------- #
def render():
    cfg = _rm.load_cfg()
    days = int(st.session_state.get("runs_days", _runs.DEFAULT_DAYS))

    try:
        index = _runs.run_index(days=days)
    except Exception as exc:  # noqa: BLE001 — a panel must not take the page down
        index = {"runs": [], "files": [], "note": f"audit read failed: {exc}",
                 "unreadable_lines": 0, "dir": "?"}

    runs = index.get("runs") or []
    outage_total = sum(int(r.get("outage_checks") or 0) for r in runs)
    if not runs:
        glance, tone = f"no run recorded in the last {days}d", "warn"
    else:
        glance = (f"{len(runs)} run(s) in {days}d · "
                  f"{sum(int(r.get('candidates') or 0) for r in runs)} candidates · "
                  f"{outage_total} outage check(s)")
        tone = "warn" if outage_total else "ok"
    page_hero("Runs", glance, tone=tone)

    st.caption(
        "A run is one PROCESS (`prospector.audit` mints `run_id` at import), not a time window — "
        "the daemon, a backfill and a manual CLI share a day-file and reading them as one run "
        "produced a confidently wrong answer twice in one session on 2026-07-31. "
        f"Reading `{index.get('dir')}` · {len(index.get('files') or [])} day-file(s)."
    )
    st.slider("Days of audit log to read", 1, 14, days, key="runs_days")
    if index.get("note"):
        st.info(index["note"])
    if index.get("unreadable_lines"):
        st.warning(f"{index['unreadable_lines']} audit line(s) would not parse and were skipped "
                   "— torn writes, most likely mid-append. They are not counted anywhere above.")

    # ---- the run spine --------------------------------------------------- #
    st.subheader("Runs")
    if runs:
        st.dataframe(run_rows(index), use_container_width=True, hide_index=True)
        st.caption(f"Cost is `{DASH}` on purpose — {_runs.COST_NULL_REASON}.")
    else:
        st.info("Nothing to show. Widen the window, or the engine has not run.")

    picked = st.selectbox("Run", [r["run_id"] for r in runs], index=0,
                          key="runs_pick") if runs else None

    candidates: list[dict] = []
    if picked:
        try:
            rv = _runs.run_view(cfg, picked, days=days)
        except Exception as exc:  # noqa: BLE001
            rv = {"found": False, "not_found_reason": f"run read failed: {exc}",
                  "candidates": [], "retrieval": {}}
        if not rv.get("found"):
            st.warning(rv.get("not_found_reason") or "run not found")
        candidates = rv.get("candidates") or []
        ret = rv.get("retrieval") or {}
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Candidates", len(candidates))
        k2.metric("Retrieval", _num(ret.get("latency_ms"), " ms"),
                  help=ret.get("latency_null_reason") or
                  f"{ret.get('distinct_queries')} distinct queries, {ret.get('errors')} errors")
        k3.metric("Events", rv.get("events"))
        k4.metric("Cost", DASH, help=_runs.COST_NULL_REASON)
        st.dataframe(
            [{"candidate": c["candidate_id"], "title": (c.get("title") or DASH),
              "tier": c.get("tier") or DASH,
              "decision": c.get("decision") or DASH,
              "gate": c.get("gate") or DASH,
              "checks": c.get("checks_seen"),
              "outages": c.get("outage_checks"),
              "dossier": c["dossier"]["status"]}
             for c in candidates],
            use_container_width=True, hide_index=True)
        unfinished = [c for c in candidates if not c.get("decision")]
        if unfinished:
            st.warning(f"{len(unfinished)} candidate(s) started and never finished in this run: "
                       + ", ".join(c["candidate_id"] for c in unfinished[:8]))

    # ---- one candidate, the whole chain ---------------------------------- #
    st.subheader("Lineage")
    default_cid = candidates[0]["candidate_id"] if candidates else ""
    cid = st.text_input("Candidate id", value=st.session_state.get("runs_cid", default_cid),
                        key="runs_cid_input",
                        help="Any candidate_id — it need not belong to the run above.").strip()
    if not cid:
        st.info("Pick a run above or paste a candidate id to see its whole causal chain.")
        return

    try:
        view = _runs.candidate_view(cfg, cid, days=days, run_id=picked if candidates else None)
    except Exception as exc:  # noqa: BLE001
        # swallow-ok: RENDERED, not swallowed — st.error puts the exception on the page the
        # operator is looking at. Narrowing here would let one unforeseen exception blank the
        # whole console instead of the single panel that failed.
        st.error(f"Could not build the lineage: {exc}")
        return

    if view.get("status") != "ok":
        # UNREADABLE IS A STATE, not a crash and not an empty page. The reason names the file.
        st.error(f"{view['status']}: {view.get('reason')}")
        if view.get("dossier_path"):
            st.caption(f"Path on record: `{view['dossier_path']}`")
        return

    _render_lineage(view)


def _render_lineage(view: dict) -> None:
    gate, gen, score = view["gate"], view["generation"], view["score"]
    outage = view["outage_summary"]

    # The outage banner comes FIRST, above the decision, because it is the thing that decides how
    # much of the decision below can be believed.
    if outage["any"]:
        st.error(f"{outage['banner']}")
        if outage["integrity_warning"]:
            st.error(outage["integrity_warning"])

    st.markdown(f"### {view['candidate'].get('title') or view['candidate_id']}")
    st.caption(view["candidate"].get("one_liner") or "")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Decision", str(gate["decision"] or DASH).upper(),
              help=gate.get("reason") or "")
    d2.metric("Gate fired", gate["gate_fired"] or DASH,
              help="a KILL names the gate; a PASS and a DEFER do not")
    d3.metric("Composite", _num(score.get("composite")),
              help=score.get("null_reason") or f"threshold {score.get('threshold')}")
    d4.metric("Provisional", "yes" if gate["provisional"] else "no",
              help="a provisional ruling never publishes on PASS and is auto re-vetted")
    if score.get("null_reason"):
        st.warning(f"No composite — {score['null_reason']}")
    if score.get("reconcile_note"):
        st.info(score["reconcile_note"])

    run = view["run"]
    st.caption(
        f"run `{run.get('run_id') or DASH}`"
        + (f" ({run.get('events')} audit rows)" if run.get("run_id")
           else f" — {run.get('null_reason')}")
        + f" · dossier `{view.get('dossier_path') or DASH}`"
    )

    # ---- generation ------------------------------------------------------ #
    with st.expander("1 · Generation", expanded=False):
        st.dataframe([{k: (v if v is not None else DASH) for k, v in gen.items()
                       if k not in ("cost_usd", "cost_null_reason")}],
                     use_container_width=True, hide_index=True)
        st.caption(f"Cost {DASH} — {gen['cost_null_reason']}")
        for label, key in (("Hypothesis", "hypothesis"), ("Who pays", "who_pays"),
                           ("Why now", "why_now")):
            if view["candidate"].get(key):
                st.markdown(f"**{label}.** {view['candidate'][key]}")

    # ---- checks ---------------------------------------------------------- #
    st.markdown("#### 2 · Checks")
    rows = evidence_rows(view)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("Readings only. A failed call is not in this table — it is below, as an "
                   "outage. Cost is per-check unavailable: " + _runs.COST_NULL_REASON)
    else:
        st.info("No check produced a reading." if outage["any"]
                else "This dossier records no checks.")

    for block in outage_blocks(view):
        with st.container(border=True):
            st.error(block["headline"])
            st.caption(f"{block['why']}  \nDetected by: {block['detected_by']} · "
                       f"provider `{block['provider']}`")
            ph = block["placeholder"]
            st.caption(f"The engine wrote `{ph.get('verdict')}` / conf `{ph.get('confidence')}` / "
                       f"\"{ph.get('rationale')}\" — {block['placeholder_note']}.")

    for c in view["evidence_checks"]:
        srcs = source_rows(c)
        title = (f"{c['check_name']} — {c['verdict']} "
                 f"({float(c['confidence']):.2f})" if c.get("confidence") is not None
                 else f"{c['check_name']} — {c['verdict']}")
        with st.expander(f"{title} · {len(srcs)} passage(s)"):
            st.markdown(c.get("rationale") or "_no rationale recorded_")
            st.caption(
                f"provider `{c.get('provider') or DASH}` · queries: "
                + (" · ".join(f"`{q}`" for q in c.get("queries") or []) or DASH)
                + f" · query source `{c.get('query_source') or DASH}` · latency "
                + (f"{c['latency_ms']} ms ({c.get('latency_provenance')})"
                   if c.get("latency_ms") is not None
                   else f"{DASH} ({c.get('latency_null_reason')})")
            )
            if not c.get("figures_traced"):
                st.caption("Figure trace never ran for this check (`untraceable_figures` is null "
                           "— which is NOT the same as 'no untraceable figures').")
            elif c.get("untraceable_figures"):
                st.warning("Figures in the rationale that appear in no retrieved passage: "
                           + ", ".join(c["untraceable_figures"]))
            for s in srcs:
                st.markdown(f"> {s['quote']}")
                st.caption(f"[{s['url']}]({s['url']}) · found by `{s['query']}` · "
                           f"{'CITED' if s['cited'] else 'retrieved, not cited'}")

    # ---- adversarial, score, publish ------------------------------------- #
    adv = view.get("adversarial") or {}
    if adv:
        st.markdown("#### 3 · Adversarial")
        st.caption(f"decisive: {adv.get('decisive')} · confidence {adv.get('confidence')} · "
                   f"provider `{adv.get('provider') or DASH}`")
        st.markdown(adv.get("kill_case") or "_no kill case recorded_")

    st.markdown("#### 4 · Score")
    if score.get("axes"):
        st.dataframe([{**{k: (a[k] if a[k] is not None else DASH)
                          for k in ("axis", "score", "weight", "contribution")},
                       "justification": (a.get("justification") or "")[:160]}
                      for a in score["axes"]],
                     use_container_width=True, hide_index=True)
        st.caption(
            f"stored composite {_num(score.get('composite'))} vs threshold "
            f"{score.get('threshold')} · Σ(score × weight) under today's weights = "
            f"{score.get('composite_recomputed', DASH)} "
            f"({'reconciles' if score.get('reconciles') else 'DOES NOT reconcile'}). "
            "The stored number is the one the gate applied."
        )
    else:
        st.info(score.get("null_reason") or "no score recorded")

    st.markdown("#### 5 · Publish")
    pub = view["publish"]
    if pub.get("status"):
        st.success(f"publish_status: {pub['status']}")
    else:
        st.info(pub["null_reason"])
    if pub.get("error"):
        st.error(f"publish_error: {pub['error']}")
    if pub.get("blocked_by_provisional"):
        st.warning("This PASS is provisional, so it does not publish — it is re-vetted by a "
                   "trusted brain first (`is_provisional_provider`, `run.py:864`).")
