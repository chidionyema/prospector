"""Outcomes — what the filter decided, why it decided it, and what that cost.

OPS_CONSOLE_PROGRAM R19 (ask 5), rendered from `prospector.ops.metrics` — the SAME derivation a
phone card or the CLI (`python -m prospector.ops.metrics`) would call. Nothing on this page is
computed here: a panel that counts its own rows is how a console and a rail come to disagree
(memory: `one-reader-two-caller-shapes`).

Three things this page is built to refuse:

1. **It never draws a defer as attrition.** The funnel's vetted→ruled step is an OUTAGE and is
   rendered in its own colour of language, not as drop-off. An outage charted as selectivity
   makes a broken moat look like a stricter filter.
2. **It never prints a number it did not measure.** Where `metrics` returns `None` this renders
   "not measured" WITH the reason beside it — never `0`, never an em-dash on its own (memory:
   `a-saturated-metric-prints-as-a-confident-null`).
3. **It states its own reconciliation, on screen, every render.** R19's probe is "figures
   reconcile to `catalogue_stats()`". If they ever stop reconciling, the page says so at the top
   and refuses to present the charts as catalogue truth.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path
from typing import Optional

import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from prospector.control_center.components.chrome import page_hero
from prospector.ops import metrics as _mx

#: Windows the operator can choose. `None` = every record the emitter has written.
WINDOWS: dict[str, Optional[float]] = {"7d": 7.0, "30d": 30.0, "90d": 90.0, "all": None}


def _pct(value, *, reason: str = "") -> str:
    """A percentage, or the WORDS "not measured" plus why. Never a bare dash.

    "—" and "0%" are both read as answers. The only honest rendering of an unmeasured rate is
    one that cannot be mistaken for a measurement.
    """
    if value is None:
        return "not measured"
    return f"{float(value):.1f}%"


def _usd(value) -> str:
    return "not measured" if value is None else f"${float(value):,.4f}"


def _cfg():
    """Config loaded the way the ENGINE loads it (§14.5.1) — `load_config` installs the process
    globals, and a cold import answers a different roster than the daemon is ruling on."""
    return _mx.load_cfg()


# --------------------------------------------------------------------------- #
def render():
    cfg = _cfg()

    label = st.radio("Window", list(WINDOWS), index=1, horizontal=True,
                     key="metrics_window", label_visibility="collapsed")
    snap = _mx.snapshot(cfg, window_days=WINDOWS[label])

    out, gates = snap["outcomes"], snap["gates"]
    rec = out["reconciliation"]
    cov = snap["coverage"]

    # ---- hero ------------------------------------------------------------ #
    if rec.get("reconciled") is False:
        glance, tone = "figures do NOT reconcile to catalogue_stats() — see below", "fail"
    else:
        glance = (f"{out['counts']['pass']} pass · {out['counts']['kill']} kill "
                  f"({_pct(out['kill_rate_pct'])} of {out['ruled']} ruled) · "
                  f"{out['counts']['defer']} deferred (outage)")
        tone = "ok" if out["ruled"] else "warn"
    page_hero("Outcomes", glance, tone=tone)

    # ---- R19's probe, on screen ------------------------------------------ #
    if rec.get("reconciled") is False:
        st.error(f"{rec['reason']}  \nours={rec['ours']} · catalogue_stats={rec['catalogue_stats']} "
                 f"· deltas={rec['deltas']}")
    elif rec.get("reconciled") is None:
        st.warning(f"Reconciliation could not run: {rec.get('reason')}")
    else:
        st.caption(f"✅ reconciles to `catalogue_stats()` exactly — "
                   f"pass {rec['ours']['pass']} · kill {rec['ours']['kill']} · "
                   f"defer {rec['ours']['defer']} · total {rec['ours']['total']}")

    # ---- catalogue outcomes ---------------------------------------------- #
    st.subheader("Catalogue")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Pass rate", _pct(out["pass_rate_pct"]),
              help=out["rate_basis"] + (f"  ·  {out['rate_reason']}" if out["rate_reason"] else ""))
    k2.metric("Kill rate", _pct(out["kill_rate_pct"]), help=out["rate_basis"])
    k3.metric("Ruled", out["ruled"], help="pass + kill — the only rows that were actually judged")
    k4.metric("Deferred", out["counts"]["defer"], help=out["defer"]["note"])

    if out["rate_reason"]:
        st.info(f"No rate — {out['rate_reason']}")
    st.caption(
        f"A DEFER is an outage, not an outcome: {out['counts']['defer']} row(s) "
        f"({_pct(out['defer']['share_of_catalogue_pct'])} of the catalogue) were never judged "
        f"and are excluded from both rates above. {out['provisional']['n']} ruling(s) are "
        f"`provisional` — {out['provisional']['note']}"
    )
    if out["other_decisions"]:
        st.warning(f"Decision values this page does not model: {out['other_decisions']}")

    # ---- rates over time -------------------------------------------------- #
    st.subheader("Rates over time")
    st.caption(cov["note"] + f"  \nWindow covers {cov['diagnostics_vetted']} vetted row(s) of "
                             f"{cov['catalogue_rows']} in the catalogue "
                             f"({_pct(cov['covered_pct'])}), {cov['first_ts']} → {cov['last_ts']}.")
    points = snap["rates"]["points"]
    if not points:
        st.info(f"No time series — {snap['rates']['reason']}")
    else:
        # Only days that RULED something carry a rate. A day of pure outage is drawn on the
        # volume chart below and deliberately leaves a GAP here rather than a 0% point, which
        # would read as "we passed nothing that day".
        st.line_chart(
            [{"day": p["day"], "pass %": p["pass_rate_pct"], "kill %": p["kill_rate_pct"],
              "outage % (of vetted)": p["outage_rate_pct"]} for p in points],
            x="day", y=["pass %", "kill %", "outage % (of vetted)"], height=260,
        )
        st.bar_chart(
            [{"day": p["day"], "pass": p["pass"], "kill": p["kill"], "defer (outage)": p["defer"]}
             for p in points],
            x="day", y=["pass", "kill", "defer (outage)"], stack=True, height=220,
        )
        blind = [p for p in points if p["pass_rate_pct"] is None]
        if blind:
            st.warning(
                f"{len(blind)} day(s) ruled nothing at all and therefore have NO rate — they are "
                f"gaps in the line above, not zeroes. Most recent: {blind[-1]['day']} — "
                f"{blind[-1]['reason']}")
        with st.expander("Per-day figures"):
            st.dataframe(points, use_container_width=True, hide_index=True)

    # ---- funnel ----------------------------------------------------------- #
    st.subheader("Funnel")
    funnel = snap["funnel"]
    if not funnel["records"]:
        st.info(f"No funnel — {funnel['reason']}")
    else:
        st.bar_chart([{"stage": s["stage"], "candidates": s["n"]} for s in funnel["steps"]],
                     x="stage", y="candidates", height=240)
        st.caption(
            f"{funnel['dropped_total']} candidate(s) were REJECTED · {funnel['outage_total']} "
            f"were never judged (outage) · {funnel['unfinished_total']} were selected but never "
            f"vetted. The three are counted apart on purpose: only the first is the filter "
            f"working.")
        st.dataframe(
            # `None` rather than "" for the first stage's absent loss: a mixed str/int column
            # makes pandas infer `object`, Arrow then reads the first value as the column type
            # and the frame fails to serialise ("Expected bytes, got a 'int' object"). A null
            # is also the honest value — nothing was lost BEFORE the first stage.
            [{"stage": s["stage"], "reached": s["n"],
              "lost before this stage": s.get("lost"),
              "kind": s.get("kind", "—"),
              "attributed to": ", ".join(f"{k} {v}" for k, v in
                                         (s.get("attributed_to") or {}).items()) or "—",
              "note": s.get("note", "")}
             for s in funnel["steps"]],
            use_container_width=True, hide_index=True,
        )
        if funnel["residual_note"]:
            st.warning(funnel["residual_note"])

    # ---- kill reason by gate ---------------------------------------------- #
    st.subheader("Kill reason by gate")
    if not gates["kills"]:
        st.info(f"No gate attribution — {gates['reason']}")
    else:
        st.bar_chart([{"gate": g["gate"], "kills": g["n"]} for g in gates["gates"]],
                     x="gate", y="kills", height=260)
        st.dataframe(gates["gates"], use_container_width=True, hide_index=True)
        if gates["unrecorded"]:
            st.warning(gates["unrecorded_note"])
        if gates["gates_on_non_kill_rows"]:
            st.warning(f"Gate recorded on rows that did not kill: "
                       f"{gates['gates_on_non_kill_rows']}")

    # ---- verdict matrix --------------------------------------------------- #
    st.subheader("Verdict matrix (per check)")
    vm = snap["verdicts"]
    if not vm["observations"]:
        st.info(f"No check observations — {vm['reason']}")
    else:
        st.bar_chart([{"check": r["check"], "supported": r["supported"],
                       "refuted": r["refuted"], "unverifiable": r["unverifiable"]}
                      for r in vm["rows"]],
                     x="check", y=["supported", "refuted", "unverifiable"], stack=True,
                     height=260)
        st.dataframe(
            [{"check": r["check"], "supported": r["supported"], "refuted": r["refuted"],
              "unverifiable": r["unverifiable"], "n": r["n"],
              "unverifiable %": _pct(r["unverifiable_pct"]),
              "why empty": r["reason"][:80] if r["reason"] else ""}
             for r in vm["rows"]],
            use_container_width=True, hide_index=True,
        )
        empty = [r["check"] for r in vm["rows"] if not r["n"]]
        if empty:
            st.info(f"{len(empty)} check(s) recorded NOTHING in this window "
                    f"({', '.join(empty)}). That is kill-fast short-circuiting before them, not "
                    f"a clean bill of health — their columns are blank, not zero.")
        st.caption(f"{vm['retrieval_failed_checks']} check(s) failed retrieval — "
                   f"{vm['retrieval_failed_note']}")

    # ---- composite distribution vs the bar -------------------------------- #
    st.subheader("Composite vs the bar")
    comp = snap["composite"]
    if not comp["scored"]:
        st.info(f"No distribution — {comp['reason']}")
    else:
        st.bar_chart([{"composite": b["bucket"], "pass": b.get("pass", 0),
                       "kill": b.get("kill", 0)} for b in comp["distribution"]],
                     x="composite", y=["pass", "kill"], stack=True, height=260)
        c1, c2, c3 = st.columns(3)
        c1.metric("Bar", comp["bar"] if comp["bar"] else "not set",
                  help=comp["bar_source"] + (f" · {comp['bar_reason']}" if comp["bar_reason"] else ""))
        c2.metric("At/above bar", comp["at_or_above_bar"]
                  if comp["at_or_above_bar"] is not None else "not measured")
        c3.metric("Unscored", comp["unscored"]["total"], help=comp["unscored"]["note"])
        if comp["bar_caveat"]:
            st.warning(comp["bar_caveat"])
        st.caption(
            f"{comp['unscored']['total']} row(s) carry NO composite ({comp['unscored']['by_decision']}) "
            f"and are excluded from the chart rather than drawn at 0.0 — {comp['unscored']['note']}")

    # ---- cost per outcome -------------------------------------------------- #
    st.subheader("Cost per outcome")
    cost = snap["cost"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Metered spend", _usd(cost["total_cost_usd"]),
              help=f"{cost['calls']} call(s) over the window")
    m2.metric("Per vetted", _usd(cost["cost_per_vetted_usd"]),
              help="every candidate the engine STARTED")
    m3.metric("Per ruled", _usd(cost["cost_per_ruled_usd"]),
              help="every candidate it FINISHED — the difference is the outage tax")
    m4.metric("Per pass", _usd(cost["cost_per_pass_usd"]))

    if cost["outage_tax_usd"] is not None:
        st.caption(f"Outage tax {_usd(cost['outage_tax_usd'])} per answer — {cost['outage_tax_note']}")
    if cost["reason"]:
        st.info(cost["reason"])
    if cost["unmetered_note"]:
        st.warning(cost["unmetered_note"])
    if cost["by_provider"]:
        with st.expander("Spend by provider / calls by phase"):
            st.dataframe(
                [{"provider": k, "calls": v["calls"], "cost_usd": v["cost_usd"],
                  "metered": "no" if k in cost["unmetered_providers"] else "yes"}
                 for k, v in cost["by_provider"].items()],
                use_container_width=True, hide_index=True)
            st.caption(" · ".join(f"{k} {v} calls" for k, v in cost["by_phase_calls"].items()))

    st.caption(f"All figures from `prospector.ops.metrics` — the same derivation "
               f"`python -m prospector.ops.metrics` prints. Snapshot {snap['now']}.")
