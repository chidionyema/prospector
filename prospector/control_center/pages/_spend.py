"""Spend — today's money against the ceilings, and when they would be hit.

OPS_CONSOLE_PROGRAM R21, rendered from `prospector.ops.spend` — the SAME derivation a phone card
or the Telegram surface calls. This page computes nothing: the metered figure it shows is
`SchedulerGuard.scan_today()` verbatim, the same call the daemon's rail gates on, so the console
and the rail cannot disagree about whether there is headroom to spend
(memory: `one-reader-two-caller-shapes`).

Two things this page deliberately does NOT do:

  * It never names or opens `store/prospector.jsonl`. That ledger is 193 MB with exactly one
    supported reader, and a second parse fails in the safe-LOOKING direction — $0.00 on a day with
    real spend (memory: `never-hand-parse-the-spend-ledger`).
  * It never renders a projection the model could not measure. Every null hit-time arrives with
    the sentence that says why, and the sentence is shown, because a blank cell reads as "fine"
    (memory: `a-saturated-metric-prints-as-a-confident-null`).

Read-only. There is no actuator here: the cap is changed in `config.yaml`, and the thing that
stops the daemon is the guard, not this page.
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
from prospector.ops import spend as _spend


def _usd(value) -> str:
    return "—" if value is None else f"${float(value):,.2f}"


def _leg_panel(name: str, leg: dict) -> None:
    """One spend leg: figure, ceiling, and either a hit-time or the reason there is none."""
    proj = leg["projection"]
    with st.container(border=True):
        st.markdown(f"**{name}** — {leg['what']}")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Spent today", _usd(leg["usd"]))
        k2.metric("Ceiling", _usd(leg["cap_usd"]) if leg["enforced"] else "none",
                  help=f"config.yaml {leg['cap_key']}")
        k3.metric("Rate",
                  f"${proj['rate_per_h']:.2f}/h" if proj["rate_per_h"] is not None else "—",
                  help="measured over the elapsed part of the LOCAL day")
        k4.metric("Hits ceiling in",
                  f"{proj['hit_in_h']:.1f}h" if proj["hit_in_h"] is not None else "—",
                  help=proj["hit_at"] or proj["reason"])

        if leg["enforced"] and leg["fraction_of_cap"] is not None:
            st.progress(leg["fraction_of_cap"],
                        text=f"{leg['pct_of_cap']:.1f}% of {leg['cap_key']} "
                             f"({_usd(leg['remaining_usd'])} left)")
        if leg["state"] == "at_cap":
            st.error(f"At the ceiling — the guard is refusing work now ({leg['cap_key']}).")
        elif leg["state"] == "warn":
            st.warning(f"Past the warn threshold {_usd(leg['warn_at_usd'])} "
                       f"(config.yaml {leg['warn_key']}).")

        # The null is rendered as a SENTENCE. An empty cell with nothing beside it is read as
        # "nothing to worry about", which is the one thing an unmeasured rate cannot say.
        if proj["hit_at"] is None:
            st.info(f"No projection — {proj['reason']}")
        elif proj["caveat"]:
            st.warning(proj["caveat"])


def render():
    cfg = _rm.load_cfg()

    try:
        view = _spend.spend_view(cfg)
    except Exception as exc:  # noqa: BLE001 — a panel must not take the page down
        # swallow-ok: RENDERED, not swallowed — the exception text goes into the hero in `fail`
        # tone plus an st.error beneath it. A panel must not take the page down, and the daemon
        # evaluates its own spend rail independently of this read.
        page_hero("Spend", f"spend view unavailable: {exc}", tone="fail")
        st.error("The spend read failed. The daemon's own rail is unaffected — it evaluates the "
                 "same guard independently of this page.")
        return

    metered, sub = view["legs"]["metered"], view["legs"]["subscription"]
    if metered["state"] == "at_cap":
        glance, tone = f"AT THE CEILING · {_usd(metered['usd'])} billed today", "fail"
    elif metered["state"] == "warn":
        glance, tone = f"{_usd(metered['usd'])} of {_usd(metered['cap_usd'])} billed today", "warn"
    else:
        glance = (f"{_usd(metered['usd'])} of {_usd(metered['cap_usd'])} billed · "
                  f"{_usd(sub['usd'])} subscription-equivalent")
        tone = "ok"
    page_hero("Spend", glance, tone=tone)

    for warning in view["warnings"]:
        st.error(warning)

    # PROVENANCE ON SCREEN. "reads the cached scan" is a byte offset the operator can check
    # against the file, not a claim in a docstring.
    cache = view["cache"]
    if cache["present"]:
        provenance = (f"resumed from the scan checkpoint at byte {cache['offset']:,} "
                      f"({(cache['lag_bytes'] or 0):,} bytes still to read)")
    else:
        provenance = "no scan checkpoint found — the next read is a full pass over the ledger"
    st.caption(f"{view['day']} ({view['day_note']}) · {view['elapsed_h']:.1f}h elapsed, "
               f"{view['hours_left_today']:.1f}h to the reset · figures from "
               f"`{view['source']}`, the same call the daemon's rail gates on · {provenance}")

    _leg_panel("Metered (billed)", metered)
    _leg_panel("Subscription-equivalent (not invoiced)", sub)

    # ---- per-tier split (the finest split the cache supports) -------------- #
    st.subheader("By tier")
    st.caption("A leg carrying exactly one tier is fully that tier's spend — exact, not "
               "apportioned. Two tiers on one leg cannot be separated from anything cached, and "
               "that cell says so rather than halving the money.")
    st.dataframe(
        [
            {
                "tier": t["name"],
                "leg": t["leg"],
                "serves": ", ".join(t["roles"]),
                "spend today": _usd(t["usd"]) if t["attributable"] else "not attributable",
                "why": t["reason"],
            }
            for t in view["tiers"]
        ],
        use_container_width=True, hide_index=True,
    )

    # ---- per-role split --------------------------------------------------- #
    st.subheader("By role")
    st.caption("A role's figure is filled in only where the attribution is SOUND. The cached scan "
               "buckets by day and by leg, never by provider — so when one tier serves two roles "
               "(minimax heads both verdict and noncritical) the money cannot be split between "
               "them, and the cell says so instead of halving it.")
    st.dataframe(
        [
            {
                "role": r["role"],
                "chain": " → ".join(f"{t['name']} ({t['leg']})" for t in r["tiers"]) or "—",
                "spend today": _usd(r["usd"]) if r["attributable"] else "not attributable",
                "why": r["reason"],
            }
            for r in view["roles"]
        ],
        use_container_width=True, hide_index=True,
    )

    # ---- recent days ------------------------------------------------------ #
    with st.expander("Recent days"):
        st.caption(view["history_horizon_note"])
        st.dataframe(
            [{"day": d, "metered": _usd(v["metered"]),
              "subscription-equivalent": _usd(v["subscription"])}
             for d, v in view["history"].items()],
            use_container_width=True, hide_index=True,
        )
