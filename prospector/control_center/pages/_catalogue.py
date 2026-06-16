"""Catalogue — dossier browser.

Purpose: browse, filter, and drill into the full grounded receipt for any candidate.
Both PASS and KILL are first-class — KILL is rendered with its cited sources.
"""
from __future__ import annotations

import streamlit as st

from prospector.control_center import readers
from prospector.control_center.components.gate_badge import st_decision_badge


def render():
    st.title("📋 Catalogue")
    rows = readers.catalogue_index()

    if not rows:
        st.info("No dossiers yet. Run `vet` or `signal` first.")
        return

    # ── Read navigation presets from alarm links (one-shot) ─────────────────
    preset_lane = st.session_state.pop("catalogue_preset_lane", None)
    preset_decision = st.session_state.pop("catalogue_preset_decision", None)
    if preset_lane is not None or preset_decision is not None:
        lane_label = f"lane={preset_lane or '(no lane)'}" if preset_lane == "" else f"lane={preset_lane or '(any)'}"
        dec_label = f"decision={preset_decision}" if preset_decision else ""
        st.info(f"🔍 Pre-filtered from alarm: {lane_label}  {dec_label}")

    # ── Filters ─────────────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    decisions = ["all", "pass", "kill", "defer"]
    decision_idx = decisions.index(preset_decision) if preset_decision in decisions else 0
    decision_filter = col1.selectbox("Decision", decisions, index=decision_idx)
    
    lanes = ["all"] + sorted({r.get("ambition_tier") or "(no lane)" for r in rows})
    # Pre-select lane from alarm link; "all" = no filter.
    # preset_lane="" means the [all] alarm — rows with empty ambition_tier, displayed
    # as "(no lane)" in the dropdown.
    if preset_lane is not None:
        lookup = "(no lane)" if preset_lane == "" else preset_lane
        lane_idx = next((i for i, l in enumerate(lanes) if l == lookup), 0)
    else:
        lane_idx = 0
    lane_filter = col2.selectbox("Lane", lanes, index=lane_idx)
    # Map display value "(no lane)" back to empty string for filtering
    actual_lane_filter = "" if lane_filter == "(no lane)" else lane_filter

    personas = ["all"] + sorted({r.get("persona") or "(none)" for r in rows})
    persona_filter = col3.selectbox("Persona", personas)
    actual_persona_filter = "" if persona_filter == "(none)" else persona_filter

    structural_forms = ["all"] + sorted({r.get("structural_form") or "" for r in rows if r.get("structural_form")})
    form_filter = col4.selectbox("Form", structural_forms)
    search = col5.text_input("Search title", "").lower()

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

    st.caption(f"Showing {len(filtered)} / {len(rows)} dossiers")

    # ── List view ────────────────────────────────────────────────────────────
    display = []
    for r in filtered:
        d = (r.get("decision") or "").lower()
        listing = readers.load_listing(r.get("candidate_id") or "")
        display.append({
            "id": (r.get("candidate_id") or "")[:8],
            "title": r.get("title") or "(untitled)",
            "decision": d.upper(),
            "gate_fired": r.get("gate_fired") or r.get("gate_fired") or "—",
            "composite": r.get("composite"),
            "lane": r.get("ambition_tier") or "—",
            "persona": r.get("persona") or "—",
            "form": r.get("structural_form") or "—",
            "provisional": "⚠️" if r.get("provisional") else "",
            "published": "✅" if listing else "",
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
            "composite": st.column_config.NumberColumn(
                "Composite", format="%.2f", width="small"),
            "lane": st.column_config.TextColumn("Lane", width="small"),
            "persona": st.column_config.TextColumn("Persona", width="small"),
            "form": st.column_config.TextColumn("Form", width="small"),
            "provisional": st.column_config.TextColumn("Prov.", width="tiny"),
            "published": st.column_config.TextColumn("Pub.", width="tiny"),
        },
        height=400,
    )

    # ── Drill-in ────────────────────────────────────────────────────────────
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
            st.caption(row.get("one_liner") or "")
        with col2:
            st_decision_badge(decision)

        if dossier:
            _render_dossier_detail(dossier, row)
        else:
            st.warning(f"Could not load dossier JSON for {candidate_id}.{decision}")


def _render_dossier_detail(dossier: dict, row: dict):
    """Render the full dossier: verdict panels per check + sources + score."""
    cand = dossier.get("candidate", {})
    checks = dossier.get("checks", [])
    score = dossier.get("score", {})
    adversarial = dossier.get("adversarial", {})

    # ── Composite + per-axis scores ───────────────────────────────────────
    composite = row.get("composite") or score.get("composite") or 0.0
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Composite", f"{composite:.2f}")
    with col2:
        gate = row.get("gate_fired") or "—"
        st.metric("Gate fired", gate)
    with col3:
        lane = row.get("ambition_tier") or "—"
        st.metric("Lane", lane)
    with col4:
        persona = row.get("persona") or "—"
        st.metric("Persona", persona)

    # ── Per-check verdict panels ──────────────────────────────────────────
    st.subheader("🔍 Verdict per check")
    if not checks:
        st.info("No check results in this dossier.")
    else:
        from prospector.models import Verdict
        for check in checks:
            name = check.get("check_name", "?")
            verdict = check.get("verdict", "unspecified")
            confidence = check.get("confidence", 0.0)
            rationale = check.get("rationale", "—")
            sources = check.get("sources", [])
            citations = check.get("citations", [])

            with st.expander(f"**{name}** → {verdict.upper()} (conf {confidence:.2f})",
                            expanded=(verdict.lower() in ("refuted", "unverifiable"))):
                st.markdown(f"**Rationale:** {rationale}")
                if citations:
                    st.markdown(f"**Citations:** {', '.join(str(c) for c in citations)}")
                if sources:
                    st.markdown("**Sources:**")
                    for src in sources:
                        url = src.get("url", "")
                        text = src.get("text", "")[:120]
                        if url:
                            st.markdown(f"- [{url[:60]}]({url})")
                            if text:
                                st.caption(text)
                        elif text:
                            st.markdown(f"- {text[:120]}")
                if not sources and not citations:
                    st.caption("No cited sources — unverifiable.")

    # ── Adversarial ────────────────────────────────────────────────────────
    if adversarial:
        st.subheader("⚔️ Adversarial pass")
        adv_decisive = adversarial.get("decisive")
        adv_kill = adversarial.get("kill_case")
        adv_conf = adversarial.get("confidence")
        st.markdown(f"**Decisive:** {adv_decisive}  **Confidence:** {adv_conf}")
        if adv_kill:
            st.markdown(f"**Kill case:** {adv_kill}")

    # ── Raw JSON ───────────────────────────────────────────────────────────
    with st.expander("📄 Raw dossier JSON"):
        st.json(dossier)
