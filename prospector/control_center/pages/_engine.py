"""Engine — is it running, what is queued, what is paused, which brains are live.

OPS_CONSOLE_PROGRAM R16 (queue + leases + measured ETA), R17 (the three pause scopes) and R22
(honest provider health), rendered from `prospector.ops.readmodel` — the SAME derivation the
Telegram surface calls. Neither renderer computes anything: a panel that counts the queue its own
way is how a dashboard and a rail come to disagree about whether there is work left
(memory: `one-reader-two-caller-shapes`).

Writes go through `prospector.ops.pause`, the one writer, which stamps an intent receipt. This
page never touches a PAUSE file itself.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from prospector.control_center.components.chrome import page_hero
from prospector.ops import pause as _pause
from prospector.ops import readmodel as _rm


def _age(seconds) -> str:
    if seconds is None:
        return "—"
    s = float(seconds)
    if s < 90:
        return f"{int(s)}s ago"
    if s < 5400:
        return f"{s / 60:.0f}m ago"
    if s < 172800:
        return f"{s / 3600:.1f}h ago"
    return f"{s / 86400:.1f}d ago"


def _cfg():
    """Config loaded the way the engine loads it.

    `load_cfg` installs the process globals (`moat_primary`, minimax concurrency). A cold import
    answers `{claude_cli}` for the trusted set while the daemon rules on `[minimax, claude_cli]` —
    a panel that skipped this would name the wrong brains as trusted (§14.5.1).
    """
    return _rm.load_cfg()


# --------------------------------------------------------------------------- #
def render():
    cfg = _cfg()

    try:
        from prospector.consumer import consumer_liveness
        consumer = consumer_liveness(cfg)
    except Exception as exc:  # noqa: BLE001 — a panel must not take the page down
        consumer = {"state": "unknown", "reason": f"liveness read failed: {exc}"}
    try:
        from prospector.scheduler.run_scheduled import _liveness as _producer_liveness
        producer_ok, producer_why = _producer_liveness(cfg)
    except Exception as exc:  # noqa: BLE001
        producer_ok, producer_why = False, f"liveness read failed: {exc}"

    queue = _rm.queue_view(cfg)
    pause = _rm.pause_view(cfg)
    providers = _rm.provider_view(cfg)

    # ---- hero ------------------------------------------------------------ #
    c_state = str(consumer.get("state", "unknown"))
    if pause["any_armed"]:
        armed = ", ".join(s["scope"] for s in pause["scopes"] if s["armed"])
        glance, tone = f"PAUSED ({armed}) · {queue['backlog']['workable']} rows workable", "warn"
    elif c_state == "dead" or not producer_ok:
        glance, tone = f"producer {'ok' if producer_ok else 'DOWN'} · consumer {c_state}", "fail"
    else:
        glance = (f"producer up · consumer {c_state} · "
                  f"{queue['backlog']['workable']} rows workable")
        tone = "ok" if c_state == "running" else "warn"
    page_hero("Engine", glance, tone=tone)

    if not producer_ok:
        st.error(f"Producer: {producer_why}")
    if c_state in ("dead", "late"):
        st.error(f"Consumer {c_state}: {consumer.get('reason') or '—'}")
    elif c_state == "blocked":
        st.warning(f"Consumer blocked (a rail is refusing it on purpose): {consumer.get('reason')}")

    # ---- R16: queue ------------------------------------------------------ #
    st.subheader("Queue")
    b, l, d = queue["backlog"], queue["leases"], queue["drain"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Workable", b["workable"], help="run.drain_survey — THE definition of backlog")
    k2.metric("Leased now", l["held"], help=f"{l['expired']} expired · {l['unheld']} free")
    k3.metric("Drain rate", f"{d['rate_per_h']:.2f}/h" if d["rate_per_h"] else "—",
              help=f"{d['resumed']} resumed over {d['window_h']}h, {d['events']} pass(es)")
    k4.metric("Drained in", f"{d['eta_h']:.0f}h" if d["eta_h"] is not None else "—",
              help=d["eta_reason"] or (d["eta_at"] or ""))

    # An ETA with no measurement behind it is the failure this panel exists to avoid: a
    # confident null reads as "nearly done" (memory: `a-saturated-metric-prints-as-a-confident-null`).
    if d["eta_h"] is None and d["eta_reason"]:
        st.info(f"No ETA — {d['eta_reason']}")
    if d["caveat"]:
        st.warning(d["caveat"])

    detail = {k: v for k, v in b.items() if k not in ("workable", "oldest_created_at") and v}
    line = " · ".join(f"{v} {k}" for k, v in detail.items()) or "no orphaned/stalled rows"
    st.caption(
        f"{line} · oldest row {b['oldest_created_at'] or '—'} · "
        f"decisions: " + " · ".join(f"{k} {v}" for k, v in sorted(queue["by_decision"].items()))
        + f" · rate from {', '.join(d['sources']) or 'nothing yet'}"
    )

    # ---- R17: the three pause scopes ------------------------------------- #
    st.subheader("Pause")
    st.caption("Existence of the file IS the semantic — every reader decides on `.exists()` alone, "
               "so a hand-`touch`ed file behaves identically and this control adds only provenance.")
    for scope in pause["scopes"]:
        name = scope["scope"]
        with st.container(border=True):
            head, act = st.columns([4, 1])
            with head:
                if scope["armed"]:
                    who = scope["actor"] or "hand-armed"
                    why = f" — {scope['reason']}" if scope["reason"] else ""
                    st.markdown(f"**`{name}` ARMED** · {who}, {_age(scope['age_s'])}{why}")
                else:
                    st.markdown(f"**`{name}`** · not armed")
                st.caption(f"Stops: {scope['stops']} · Keeps running: {scope['keeps_running']}  \n"
                           f"{scope['note']}  \nRead by `{scope['reader']}`")
            with act:
                if scope["armed"]:
                    if st.button("Resume", key=f"disarm_{name}", use_container_width=True):
                        _pause.disarm(cfg, name, actor="control_center")
                        st.rerun()
                else:
                    if st.button("Pause", key=f"arm_{name}", type="secondary",
                                 use_container_width=True):
                        _pause.arm(cfg, name, actor="control_center",
                                   reason=st.session_state.get(f"reason_{name}", ""))
                        st.rerun()
            if not scope["armed"]:
                st.text_input("Reason (recorded with the pause)", key=f"reason_{name}",
                              label_visibility="collapsed", placeholder="why (optional)")

    # ---- R22: provider health -------------------------------------------- #
    st.subheader("Brains")
    if providers["moat_blind"]:
        st.error(f"Moat blind: {providers['moat_blind']}")
    if providers["drain_blind"]:
        st.warning(f"Drain blind (trusted-only, by design): {providers['drain_blind']}")

    st.caption("Every CONFIGURED tier is listed, dead or not — a panel rendering only the health "
               "file cannot show a brain that was never marked. Dead marks are read RAW; this page "
               "never calls `is_dead`, which would spend the single half-open probe.")
    st.dataframe(
        [
            {
                "tier": t["name"],
                "state": t["state"],
                "trusted final": "yes" if t["trusted_final"] else "—",
                "roles": ", ".join(f"{r['role']}#{r['position']}" for r in t["roles"]),
                "dead until": t["dead_until"] or "—",
                "last error": (t["last_error"] or "")[:120],
            }
            for t in providers["tiers"]
        ],
        use_container_width=True, hide_index=True,
    )
    if providers["orphan_marks"]:
        with st.expander(f"{len(providers['orphan_marks'])} stale mark(s) for tiers no chain names"):
            st.caption("Left behind by a retired tier. Harmless, but they are why a health-file-"
                       "shaped panel used to show brains this engine cannot call.")
            st.dataframe(providers["orphan_marks"], use_container_width=True, hide_index=True)

    st.caption(f"Trusted-final set: {', '.join(providers['trusted_final'])} "
               f"(config.yaml moat_primary, read through the process global)")
