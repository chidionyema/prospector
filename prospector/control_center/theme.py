"""Global theme & custom CSS for the Prospector Control Center.

Operator-console aesthetic: deep slate + amber accent (not purple AI defaults).
Call inject_theme() once after set_page_config.
"""
from __future__ import annotations

import streamlit as st

THEME_CSS = """
:root {
    --cc-surface: #1a2332;
    --cc-surface-hover: #243044;
    --cc-border: #2d3a4f;
    --cc-primary: #e8a838;
    --cc-primary-muted: rgba(232, 168, 56, 0.14);
    --cc-success: #3ecf8e;
    --cc-success-muted: rgba(62, 207, 142, 0.14);
    --cc-danger: #f07178;
    --cc-danger-muted: rgba(240, 113, 120, 0.14);
    --cc-warning: #e8a838;
    --cc-warning-muted: rgba(232, 168, 56, 0.14);
    --cc-info: #5eb3f0;
    --cc-text: #e7ecf3;
    --cc-text-secondary: #9aa8bc;
    --cc-text-muted: #6b7a90;
    --cc-radius: 8px;
    --cc-radius-sm: 4px;
    --cc-shadow: 0 1px 2px rgba(0,0,0,0.35);
    --cc-transition: 120ms ease;
    --cc-mono: "SF Mono", "JetBrains Mono", "Cascadia Code", "Fira Code", ui-monospace, monospace;
}

[data-testid="stSidebar"] {
    background-color: #0c121c;
    border-right: 1px solid var(--cc-border);
}
[data-testid="stSidebar"] .stRadio > div { gap: 1px; }
[data-testid="stSidebar"] .stRadio label {
    padding: 5px 10px;
    border-radius: var(--cc-radius-sm);
    transition: background var(--cc-transition);
    font-size: 0.92rem;
}
[data-testid="stSidebar"] .stRadio label:hover {
    background: var(--cc-surface-hover);
}
[data-testid="stSidebar"] .stRadio [data-checked="true"] {
    background: var(--cc-primary-muted) !important;
    color: var(--cc-primary);
}

.block-container {
    padding-top: 1rem;
    padding-bottom: 1.25rem;
    max-width: 1200px;
}
h1, h2, h3, h4 {
    color: var(--cc-text) !important;
    font-weight: 600 !important;
    letter-spacing: -0.015em;
    margin-bottom: 0.35rem !important;
}
hr, [data-testid="stDivider"] {
    border-color: var(--cc-border) !important;
    margin: 0.55rem 0 !important;
}
[data-testid="stCaption"] {
    color: var(--cc-text-muted) !important;
}

/* Hero / glance */
.cc-hero {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.15rem 0 0.85rem;
    border-bottom: 1px solid var(--cc-border);
    margin-bottom: 0.85rem;
}
.cc-hero-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--cc-text);
    letter-spacing: -0.02em;
}
.cc-glance {
    font-size: 1.05rem;
    font-weight: 550;
    font-family: var(--cc-mono);
    line-height: 1.35;
    color: var(--cc-text);
}
.cc-glance--live { color: var(--cc-success); }
.cc-glance--fail { color: var(--cc-danger); }
.cc-glance--ok { color: var(--cc-success); }
.cc-glance--warn { color: var(--cc-warning); }
.cc-glance--idle { color: var(--cc-text-secondary); }

.cc-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.25rem 0 0.75rem;
}
.cc-header-title {
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--cc-text);
    letter-spacing: -0.02em;
}
.cc-header-status {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    font-family: var(--cc-mono);
    font-size: 0.85rem;
}
.cc-header-status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}
.cc-header-status-dot--live {
    background: var(--cc-success);
    box-shadow: 0 0 6px var(--cc-success);
}
.cc-header-status-dot--idle { background: var(--cc-text-muted); }

.cc-card {
    background: var(--cc-surface);
    border: 1px solid var(--cc-border);
    border-radius: var(--cc-radius);
    padding: 0.85rem 1rem;
    box-shadow: var(--cc-shadow);
}
.cc-kpi { text-align: center; padding: 0.5rem 0.65rem; }
.cc-kpi-value {
    font-size: 1.65rem;
    font-weight: 700;
    line-height: 1.1;
    color: var(--cc-text);
    font-family: var(--cc-mono);
}
.cc-kpi-label {
    font-size: 0.72rem;
    color: var(--cc-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-top: 2px;
}

.cc-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--cc-surface);
    border: 1px solid var(--cc-border);
}
.cc-pill--healthy { color: var(--cc-success); border-color: rgba(62,207,142,0.45); }
.cc-pill--dead { color: var(--cc-danger); border-color: rgba(240,113,120,0.55); }
.cc-pill--recovering { color: var(--cc-warning); border-color: rgba(232,168,56,0.5); }

.cc-alarm {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    padding: 0.65rem 0.85rem;
    border-radius: var(--cc-radius-sm);
    margin-bottom: 0.4rem;
    background: var(--cc-surface);
    border: 1px solid var(--cc-border);
    border-left: 3px solid var(--cc-warning);
}
.cc-alarm--critical {
    border-left-color: var(--cc-danger);
    background: var(--cc-danger-muted);
}
.cc-alarm--warn {
    border-left-color: var(--cc-warning);
    background: var(--cc-warning-muted);
}
.cc-alarm-code {
    font-family: var(--cc-mono);
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 2px 6px;
    border-radius: 3px;
    white-space: nowrap;
}
.cc-muted { color: var(--cc-text-muted); }
.cc-mono { font-family: var(--cc-mono); font-size: 0.85em; }

/* Tighten Streamlit chrome */
div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stMetric"]) {
    background: var(--cc-surface);
    border: 1px solid var(--cc-border);
    border-radius: var(--cc-radius);
    padding: 0.35rem 0.5rem;
}
textarea[disabled] {
    font-family: var(--cc-mono) !important;
    font-size: 0.78rem !important;
    line-height: 1.4 !important;
    background: #0c121c !important;
    color: #c8d2e0 !important;
    border: 1px solid var(--cc-border) !important;
}
[data-testid="stProgress"] > div > div {
    background: var(--cc-primary);
    border-radius: 3px;
}
"""


def inject_theme() -> None:
    """Inject custom CSS. Idempotent across Streamlit reruns."""
    st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)
