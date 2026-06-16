"""KPI strip widget for the Overview cockpit."""
from __future__ import annotations

import streamlit as st


def kpi_card(label: str, value, delta: str | None = None,
            delta_color: str | None = None,
            help_text: str | None = None) -> None:
    """Render a single KPI card.

    Args:
        label: display label
        value: primary value (number or string)
        delta: optional delta/sub-label
        delta_color: "normal" (green), "inverse" (red), or "off" (grey)
        help_text: optional tooltip
    """
    st.metric(label, value, delta=delta, delta_color=delta_color, help=help_text)


def kpi_row(cards: list[dict]) -> None:
    """Render a row of KPI cards in equal-width columns.

    Each card dict: {label, value, delta, delta_color, help}
    """
    n = len(cards)
    cols = st.columns(n)
    for i, card in enumerate(cards):
        with cols[i]:
            kpi_card(**card)


def spend_progress_bar(spent: float, cap: float, label: str = "Daily spend") -> None:
    """Render a spend progress bar with caption."""
    if cap <= 0:
        return
    pct = min(1.0, spent / cap)
    color = "normal" if pct < 0.8 else "inverse" if pct > 0.95 else "off"
    st.metric(label, f"${spent:.4f}", delta=f"{pct:.0%} of ${cap:.0f}")
    st.progress(pct, caption=f"{pct:.1%} of ${cap:.0f} cap")
