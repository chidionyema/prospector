"""Source list renderer — cited sources with retrievable URLs."""
from __future__ import annotations

import streamlit as st


def render_source_list(sources: list[dict]) -> None:
    """Render a list of cited sources as a table with links.

    Args:
        sources: list of Source dicts (url, text, published_at, source_id)
    """
    if not sources:
        st.info("No cited sources.")
        return

    rows = []
    for src in sources:
        url = src.get("url", "")
        text = src.get("text", "")[:100]
        published = src.get("published_at", "")
        src_id = src.get("source_id", "")[:8]

        if url:
            rows.append({
                "source_id": src_id,
                "url": f"[{_truncate(url, 55)}]({url})",
                "published": published,
                "preview": text,
            })
        else:
            rows.append({
                "source_id": src_id,
                "url": text or "—",
                "published": published,
                "preview": "—",
            })

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "source_id": st.column_config.TextColumn("id", width="small"),
            "url": st.column_config.MarkdownColumn("URL", width="medium"),
            "published": st.column_config.TextColumn("published", width="small"),
            "preview": st.column_config.TextColumn("preview", width="large"),
        },
    )


def render_source_summary(sources: list[dict]) -> str:
    """Return a plain-text summary of cited sources for use in summaries."""
    if not sources:
        return "no sources"
    urls = [s.get("url", "") for s in sources if s.get("url")]
    return f"{len(sources)} source(s): {', '.join(urls[:3])}" + \
           ("…" if len(urls) > 3 else "")


def _truncate(s: str, max_len: int) -> str:
    return s[:max_len] + "…" if len(s) > max_len else s
