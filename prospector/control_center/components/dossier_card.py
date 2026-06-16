"""Dossier card renderer — renders the full dossier header + verdict panels.

Used by _catalogue.py for the drill-in view.
"""
from __future__ import annotations

import streamlit as st


def render_dossier_card(dossier: dict, row: dict) -> None:
    """Render the full dossier header with composite + per-axis scores + gate info.

    Args:
        dossier: parsed dossier JSON dict
        row:     catalogue index row dict (candidate_id, title, etc.)
    """
    cand = dossier.get("candidate", {})
    decision = (row.get("decision") or "").lower()
    gate = row.get("gate_fired") or "—"
    composite = row.get("composite") or dossier.get("score", {}).get("composite", 0.0)
    lane = row.get("ambition_tier") or "—"
    title = row.get("title") or cand.get("title", "(untitled)")
    one_liner = row.get("one_liner") or cand.get("one_liner", "")

    # ── Header ──────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.subheader(title)
        if one_liner:
            st.caption(one_liner)
    with col2:
        _render_decision_badge(decision)
    with col3:
        st.metric("Composite", f"{composite:.2f}")
        st.metric("Gate", gate)
        st.metric("Lane", lane)

    # ── Per-check verdict panels ─────────────────────────────────────────────
    _render_checks(dossier.get("checks", []))

    # ── Adversarial ─────────────────────────────────────────────────────────
    _render_adversarial(dossier.get("adversarial", {}))

    # ── Secondary artifacts (PASS only) ──────────────────────────────────────
    if decision == "pass":
        _render_artifacts(dossier.get("artifacts", {}))

    # ── Provenance footer ────────────────────────────────────────────────────
    _render_provenance(dossier, row)


def _render_decision_badge(decision: str) -> None:
    """Coloured decision badge."""
    d = (decision or "").lower()
    if d == "pass":
        st.success("✅ PASS")
    elif d == "kill":
        st.error("🛑 KILL")
    elif d == "defer":
        st.warning("⏸ DEFER")
    else:
        st.info(str(decision or "—"))


def _render_checks(checks: list[dict]) -> None:
    """Render the per-check verdict panels."""
    st.subheader("🔍 Verdict per check")
    if not checks:
        st.info("No check results in this dossier.")
        return

    for check in checks:
        name = check.get("check_name", "?")
        verdict = (check.get("verdict") or "unspecified").upper()
        confidence = check.get("confidence", 0.0)
        rationale = check.get("rationale", "—")
        citations = check.get("citations", [])
        sources = check.get("sources", [])

        verdict_color = "green" if verdict in ("SUPPORTED",) else \
                        "red" if verdict in ("REFUTED",) else "yellow"

        with st.expander(
            f"**{name}** → `{verdict}` conf {confidence:.2f}",
            expanded=(verdict in ("REFUTED", "UNVERIFIABLE")),
        ):
            st.markdown(f"**Rationale:** {rationale}")

            if citations:
                st.markdown(f"**Citations:** `{', '.join(str(c) for c in citations)}`")

            if sources:
                _render_sources(sources)

            if not sources and not citations:
                st.caption("No cited sources — verdict is UNVERIFIABLE.")


def _render_sources(sources: list[dict]) -> None:
    """Render a list of cited sources with URLs."""
    st.markdown("**Sources:**")
    for src in sources:
        url = src.get("url", "")
        text = src.get("text", "")[:150]
        published = src.get("published_at", "")
        if url:
            short = url[:60]
            st.markdown(f"- [{short}]({url})")
            if text:
                st.caption(text[:120])
            if published:
                st.caption(f"  Published: {published}")
        elif text:
            st.markdown(f"- {text[:120]}")


def _render_adversarial(adversarial: dict) -> None:
    """Render the adversarial pass result."""
    if not adversarial:
        return
    st.subheader("⚔️ Adversarial pass")
    decisive = adversarial.get("decisive", "?")
    confidence = adversarial.get("confidence", 0.0)
    kill_case = adversarial.get("kill_case", "")
    st.markdown(f"**Decisive:** `{decisive}`  **Confidence:** {confidence:.2f}")
    if kill_case:
        st.markdown(f"**Kill case:** {kill_case}")


def _render_artifacts(artifacts: dict) -> None:
    """Render secondary artifacts (PASS only)."""
    if not artifacts:
        return
    st.subheader("📦 Secondary artifacts")
    for name, content in artifacts.items():
        with st.expander(f"**{name}**"):
            st.markdown(str(content))


def _render_provenance(dossier: dict, row: dict) -> None:
    """Render the provenance footer: provider chain, cost, timing."""
    st.divider()
    st.caption("**Provenance**")
    provider_chain = dossier.get("provider_chain", [])
    if provider_chain:
        st.caption(f"Provider chain: {' → '.join(provider_chain)}")

    cost = dossier.get("cost_usd") or row.get("cost_usd")
    if cost:
        st.caption(f"Cost: ${cost:.4f}")

    created = row.get("created_at") or dossier.get("created_at", "—")
    st.caption(f"Created: {created}")
    model_version = dossier.get("model_version", "—")
    st.caption(f"Model: {model_version}")
