"""Global theme & custom CSS injection for the Prospector Control Center.

Provides a modern dark-themed dashboard look via CSS custom properties + utility
classes.  Call inject_theme() once at app startup (after set_page_config).
"""
from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Custom CSS — loaded once and injected into every page
# ---------------------------------------------------------------------------

THEME_CSS = """
/* ═══════════════════════════════════════════════════════════════════════════
   Prospector Control Center — Custom Theme
   ═══════════════════════════════════════════════════════════════════════ */

/* ── Root tokens ────────────────────────────────────────────────────────── */
:root {
    --cc-surface: #1e293b;
    --cc-surface-hover: #273449;
    --cc-border: #334155;
    --cc-primary: #6366f1;
    --cc-primary-muted: rgba(99, 102, 241, 0.15);
    --cc-success: #22c55e;
    --cc-success-muted: rgba(34, 197, 94, 0.15);
    --cc-danger: #ef4444;
    --cc-danger-muted: rgba(239, 68, 68, 0.15);
    --cc-warning: #eab308;
    --cc-warning-muted: rgba(234, 179, 8, 0.15);
    --cc-info: #3b82f6;
    --cc-text: #f1f5f9;
    --cc-text-secondary: #94a3b8;
    --cc-text-muted: #64748b;
    --cc-radius: 10px;
    --cc-radius-sm: 6px;
    --cc-shadow: 0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
    --cc-transition: 150ms ease;
}

/* ── Sidebar polish ─────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #0f172a;
    border-right: 1px solid var(--cc-border);
}
[data-testid="stSidebar"] .stRadio > div {
    gap: 2px;
}
[data-testid="stSidebar"] .stRadio label {
    padding: 6px 12px;
    border-radius: var(--cc-radius-sm);
    transition: background var(--cc-transition);
}
[data-testid="stSidebar"] .stRadio label:hover {
    background: var(--cc-surface-hover);
}
[data-testid="stSidebar"] .stRadio [data-checked="true"] {
    background: var(--cc-primary-muted) !important;
    color: var(--cc-primary);
}

/* ── Global resets ──────────────────────────────────────────────────────── */
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 1rem;
}
h1, h2, h3, h4 {
    color: var(--cc-text) !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
}
hr, [data-testid="stDivider"] {
    border-color: var(--cc-border) !important;
    margin: 0.5rem 0 !important;
}

/* ── cc-card: raised container ──────────────────────────────────────────── */
.cc-card {
    background: var(--cc-surface);
    border: 1px solid var(--cc-border);
    border-radius: var(--cc-radius);
    padding: 1rem 1.25rem;
    box-shadow: var(--cc-shadow);
    transition: box-shadow var(--cc-transition);
}
.cc-card:hover {
    box-shadow: 0 4px 8px rgba(0,0,0,0.4);
}

/* ── cc-kpi: large metric card ──────────────────────────────────────────── */
.cc-kpi {
    text-align: center;
    padding: 0.75rem 1rem;
}
.cc-kpi-value {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.1;
    color: var(--cc-text);
}
.cc-kpi-label {
    font-size: 0.8rem;
    color: var(--cc-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 2px;
}
.cc-kpi-sub {
    font-size: 0.75rem;
    color: var(--cc-text-muted);
    margin-top: 2px;
}
.cc-kpi-delta {
    font-size: 0.85rem;
    font-weight: 600;
    margin-top: 4px;
}
.cc-kpi-delta--up { color: var(--cc-success); }
.cc-kpi-delta--down { color: var(--cc-danger); }

/* ── cc-alarm: severity-coded alert card ────────────────────────────────── */
.cc-alarm {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    border-radius: var(--cc-radius-sm);
    margin-bottom: 0.5rem;
    background: var(--cc-surface);
    border: 1px solid var(--cc-border);
    border-left: 4px solid var(--cc-warning);
}
.cc-alarm--critical {
    border-left-color: var(--cc-danger);
    background: var(--cc-danger-muted);
}
.cc-alarm--warn {
    border-left-color: var(--cc-warning);
    background: var(--cc-warning-muted);
}
.cc-alarm--info {
    border-left-color: var(--cc-info);
}
.cc-alarm-code {
    font-family: "SF Mono", "Cascadia Code", "Fira Code", monospace;
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 2px 6px;
    border-radius: 4px;
    white-space: nowrap;
}
.cc-alarm--critical .cc-alarm-code { color: #fca5a5; background: rgba(239,68,68,0.2); }
.cc-alarm--warn .cc-alarm-code { color: #fde047; background: rgba(234,179,8,0.2); }
.cc-alarm-lane {
    font-size: 0.75rem;
    color: var(--cc-text-secondary);
}
.cc-alarm-msg {
    font-size: 0.85rem;
    color: var(--cc-text);
    line-height: 1.4;
    flex: 1;
}

/* ── cc-pill: inline status indicator ───────────────────────────────────── */
.cc-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.78rem;
    font-weight: 600;
    background: var(--cc-surface);
    border: 1px solid var(--cc-border);
}
.cc-pill--healthy { color: var(--cc-success); border-color: var(--cc-success); }
.cc-pill--dead { color: var(--cc-danger); border-color: var(--cc-danger); }
.cc-pill--recovering { color: var(--cc-warning); border-color: var(--cc-warning); }
.cc-pill-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: currentColor;
}

/* ── cc-header: page header bar ─────────────────────────────────────────── */
.cc-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0 1rem;
}
.cc-header-title {
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--cc-text);
    letter-spacing: -0.02em;
}
.cc-header-status {
    display: flex;
    align-items: center;
    gap: 1rem;
}
.cc-header-status-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    display: inline-block;
}
.cc-header-status-dot--live { background: var(--cc-success); box-shadow: 0 0 6px var(--cc-success); }
.cc-header-status-dot--idle { background: var(--cc-text-muted); }

/* ── Utilities ──────────────────────────────────────────────────────────── */
.cc-muted { color: var(--cc-text-muted); }
.cc-mono { font-family: "SF Mono", "Cascadia Code", "Fira Code", monospace; font-size: 0.85em; }
.cc-actions {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1.25rem;
}

/* ── Progress bar override ──────────────────────────────────────────────── */
[data-testid="stProgress"] > div > div {
    background: var(--cc-primary);
    border-radius: 4px;
}
"""


def inject_theme() -> None:
    """Inject the custom CSS theme into the current Streamlit page.

    Call once after st.set_page_config().  Idempotent — safe to call on every
    page render (Streamlit deduplicates identical markdown blocks).
    """
    st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)
