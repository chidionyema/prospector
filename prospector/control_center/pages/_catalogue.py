"""Catalogue — filter + drill into grounded dossiers (PASS and KILL)."""
from __future__ import annotations

import streamlit as st

from prospector.control_center import readers
from prospector.control_center.components.chrome import go_page, page_hero
from prospector.control_center.components.gate_badge import st_decision_badge


def render():
    rows = readers.catalogue_index()
    stats = readers.catalogue_stats() if rows else {}
    n = len(rows)
    glance = (
        f"{n} dossiers · PASS {stats.get('n_pass', 0)} · "
        f"KILL {stats.get('n_kill', 0)} · DEFER {stats.get('n_defer', 0)}"
        if n
        else "No dossiers yet — launch generate"
    )
    page_hero("Catalogue", glance, tone="ok" if n else "idle")

    if not rows:
        if st.button("Go to Launch", type="primary", key="cat_empty_launch"):
            go_page("launcher")
        return

    preset_lane = st.session_state.pop("catalogue_preset_lane", None)
    preset_decision = st.session_state.pop("catalogue_preset_decision", None)
    if preset_lane is not None or preset_decision is not None:
        st.caption(
            f"Pre-filtered from alarm · lane={preset_lane!r} · decision={preset_decision!r}"
        )

    col1, col2, col3, col4, col5 = st.columns(5)
    decisions = ["all", "pass", "kill", "defer"]
    decision_idx = decisions.index(preset_decision) if preset_decision in decisions else 0
    decision_filter = col1.selectbox("Decision", decisions, index=decision_idx)

    lanes = ["all"] + sorted({r.get("ambition_tier") or "(no lane)" for r in rows})
    if preset_lane is not None:
        lookup = "(no lane)" if preset_lane == "" else preset_lane
        lane_idx = next((i for i, lane in enumerate(lanes) if lane == lookup), 0)
    else:
        lane_idx = 0
    lane_filter = col2.selectbox("Lane", lanes, index=lane_idx)
    actual_lane_filter = "" if lane_filter == "(no lane)" else lane_filter

    personas = ["all"] + sorted({r.get("persona") or "(none)" for r in rows})
    persona_filter = col3.selectbox("Persona", personas)
    actual_persona_filter = "" if persona_filter == "(none)" else persona_filter

    structural_forms = ["all"] + sorted(
        {r.get("structural_form") or "" for r in rows if r.get("structural_form")}
    )
    form_filter = col4.selectbox("Form", structural_forms)
    search = col5.text_input("Search", "").lower()

    filtered = rows
    if decision_filter != "all":
        filtered = [r for r in filtered if (r.get("decision") or "").lower() == decision_filter]
    if lane_filter != "all":
        filtered = [r for r in filtered if r.get("ambition_tier") == actual_lane_filter]
    if persona_filter != "all":
        filtered = [r for r in filtered if (r.get("persona") or "") == actual_persona_filter]
    if form_filter != "all":
        filtered = [r for r in filtered if r.get("structural_form") == form_filter]
    if search:
        filtered = [r for r in filtered if search in (r.get("title") or "").lower()]

    st.caption(f"{len(filtered)} / {n} shown · select a row to open the receipt")

    display = []
    for r in filtered:
        d = (r.get("decision") or "").lower()
        listing = readers.load_listing(r.get("candidate_id") or "")
        display.append({
            "id": (r.get("candidate_id") or "")[:8],
            "title": r.get("title") or "(untitled)",
            "decision": d.upper(),
            "gate_fired": r.get("gate_fired") or "—",
            "composite": r.get("composite"),
            "lane": r.get("ambition_tier") or "—",
            "persona": r.get("persona") or "—",
            "form": r.get("structural_form") or "—",
            "provisional": "Y" if r.get("provisional") else "",
            "published": "Y" if listing else "",
        })

    selected = st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode=["single-row"],
        column_config={
            "id": st.column_config.TextColumn("id", width="small"),
            "title": st.column_config.TextColumn("title", width="large"),
            "decision": st.column_config.TextColumn("Decision", width="small"),
            "gate_fired": st.column_config.TextColumn("Gate", width="medium"),
            "composite": st.column_config.NumberColumn("Composite", format="%.2f", width="small"),
            "lane": st.column_config.TextColumn("Lane", width="small"),
            "persona": st.column_config.TextColumn("Persona", width="small"),
            "form": st.column_config.TextColumn("Form", width="small"),
            "provisional": st.column_config.TextColumn("Prov.", width="tiny"),
            "published": st.column_config.TextColumn("Pub.", width="tiny"),
        },
        height=360,
    )

    if selected and selected.get("selection", {}).get("rows"):
        idx = selected["selection"]["rows"][0]
        row = filtered[idx]
        candidate_id = row.get("candidate_id", "")
        decision = (row.get("decision") or "").lower()
        dossier = readers.load_dossier(candidate_id, decision)

        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader(row.get("title") or "(untitled)")
            st.caption(row.get("one_liner") or candidate_id)
        with col2:
            st_decision_badge(decision)

        if dossier:
            _render_dossier_detail(dossier, row)
        else:
            st.warning(f"Missing dossier JSON for {candidate_id}.{decision}")


def _render_dossier_detail(dossier: dict, row: dict):
    cand = dossier.get("candidate", {})
    checks = dossier.get("checks", [])
    score = dossier.get("score", {})
    adversarial = dossier.get("adversarial", {})

    composite = row.get("composite") or score.get("composite") or 0.0
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Composite", f"{composite:.2f}")
    col2.metric("Gate", row.get("gate_fired") or "—")
    col3.metric("Lane", row.get("ambition_tier") or "—")
    col4.metric("Persona", row.get("persona") or "—")

    if cand.get("why_now"):
        st.caption(f"Why now: {cand.get('why_now')}")

    st.markdown("**Verdicts**")
    if not checks:
        st.caption("No check results in this dossier.")
    else:
        for check in checks:
            name = check.get("check_name", "?")
            verdict = check.get("verdict", "unspecified")
            confidence = check.get("confidence", 0.0)
            rationale = check.get("rationale", "—")
            sources = check.get("sources", [])
            citations = check.get("citations", [])
            with st.expander(
                f"{name} → {str(verdict).upper()} ({confidence:.2f})",
                expanded=(str(verdict).lower() in ("refuted", "unverifiable")),
            ):
                st.markdown(rationale)
                if citations:
                    st.caption("Citations: " + ", ".join(str(c) for c in citations))
                if sources:
                    for src in sources:
                        url = src.get("url", "")
                        text = (src.get("text", "") or "")[:120]
                        if url:
                            st.markdown(f"- [{url[:70]}]({url})")
                            if text:
                                st.caption(text)
                        elif text:
                            st.markdown(f"- {text}")
                if not sources and not citations:
                    st.caption("No cited sources — unverifiable.")

    if adversarial:
        with st.expander("Adversarial", expanded=bool(adversarial.get("kill_case"))):
            st.markdown(
                f"Decisive: {adversarial.get('decisive')} · "
                f"Confidence: {adversarial.get('confidence')}"
            )
            if adversarial.get("kill_case"):
                st.markdown(adversarial["kill_case"])

    with st.expander("Raw JSON", expanded=False):
        st.json(dossier)
