"""Shared page chrome — one-glance hero + log panel for operator pages."""
from __future__ import annotations

from pathlib import Path

import streamlit as st


def page_hero(
    title: str,
    glance: str,
    *,
    tone: str = "idle",
) -> None:
    """Compact page header: title + one-sentence status. No essay."""
    tone_cls = {
        "live": "cc-glance--live",
        "fail": "cc-glance--fail",
        "ok": "cc-glance--ok",
        "idle": "cc-glance--idle",
        "warn": "cc-glance--warn",
    }.get(tone, "cc-glance--idle")
    st.markdown(
        f'<div class="cc-hero">'
        f'<div class="cc-hero-title">{title}</div>'
        f'<div class="cc-glance {tone_cls}">{glance}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def log_panel(
    text: str,
    *,
    path: str = "",
    height: int = 280,
    key: str = "log_panel",
    empty_hint: str = "No log yet.",
) -> None:
    """Monospace log peek with optional path caption. Always visible when called."""
    if path:
        st.caption(f"Log · `{path}`")
    if text:
        st.text_area(
            "log",
            text,
            height=height,
            disabled=True,
            label_visibility="collapsed",
            key=key,
        )
    else:
        st.caption(empty_hint)


def tone_from_job_status(status: str | None) -> str:
    s = (status or "").lower()
    if s == "running":
        return "live"
    if s in ("failed", "unknown"):
        return "fail"
    if s in ("succeeded", "deferred"):
        return "ok"
    if s == "cancelled":
        return "warn"
    return "idle"


def go_page(page_key: str) -> None:
    """Navigate programmatically without fighting the sidebar radio widget.

    Sets active_page and flags a one-shot radio sync. Must not assign
    ``nav_radio`` here — that widget is already instantiated this run;
    app.py applies the sync on the next run *before* creating the radio.
    """
    st.session_state["active_page"] = page_key
    st.session_state["_sync_nav_radio"] = True
    st.rerun()


def job_log_path(job: dict) -> str:
    return job.get("log_file") or (
        f"store/control_center/runs/{job.get('job_id', '')}.log"
        if job.get("job_id")
        else ""
    )


def resolve_log_text(job: dict, n: int = 120) -> str:
    """Prefer runner ring buffer; fall back to disk tail. Never hide finished logs."""
    job_id = job.get("job_id") or ""
    try:
        from prospector.control_center import runner as _runner
        lines = _runner.get_log_lines(job_id, n=n) if job_id else []
        if lines:
            return "\n".join(lines)
    except Exception:
        pass
    from prospector.control_center import readers
    return readers.read_job_log_tail(job, n=n)


def path_exists_hint(path: str) -> str:
    if not path:
        return ""
    try:
        p = Path(path)
        if p.exists():
            return f"{p.stat().st_size:,} B"
    except OSError:
        pass
    return "missing"
