# UI Modernization — Phase 1: Global Theme + Overview Page

**Goal:** Modernize the Prospector Control Center from "clunky 80s" to a polished,
dark-themed dashboard. Phase 1 delivers the global theme system and a redesigned
Overview page (~60% of visual impact), establishing patterns the remaining 6 pages
will adopt in Phase 2.

**Constraint:** Stay within Streamlit 1.58. No new dependencies. Keep all existing
data-loading logic, readers, and page routing untouched. Only visual/presentation
layer changes.

---

## 1. Global Theme System

### 1.1 `.streamlit/config.toml`

Add a `[theme]` section with a custom dark palette:

```toml
[theme]
base = "dark"
primaryColor = "#6366f1"
backgroundColor = "#0f172a"
secondaryBackgroundColor = "#1e293b"
textColor = "#f1f5f9"
font = "sans serif"
```

Keep the existing `[client] showSidebarNavigation = false`.

### 1.2 `prospector/control_center/theme.py` (NEW FILE)

A module that injects custom CSS on first import. Exposes a single function:

```python
def inject_theme():
    """Inject custom CSS into the Streamlit app. Idempotent (call on every page render)."""
```

The CSS must provide:

1. **Card class (`.cc-card`)** — rounded container with subtle border/shadow,
   padding, background from secondaryBackgroundColor. Used for KPI cards, alarm
   cards, status panels.

2. **KPI card (`.cc-kpi`)** — large value number, smaller label below, optional
   delta with green/red coloring. Extends `.cc-card`.

3. **Alarm card (`.cc-alarm`)** — severity-colored left border, message body,
   compact layout. Severity classes: `.cc-alarm--critical` (red border),
   `.cc-alarm--warn` (amber border).

4. **Status pill (`.cc-pill`)** — inline colored dot + label for HEALTHY/DEAD/
   RECOVERING states.

5. **Utilities** — `.cc-muted` for secondary text, `.cc-monospace` for IDs/tech
   values, `.cc-divider` (thin hairline instead of chunky st.divider).

6. **Sidebar** — tighter spacing, smaller font for nav items, subtle active-state
   highlight.

All CSS is injected via `st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)`.

### 1.3 Wire `inject_theme()` into `app.py`

Call `inject_theme()` once at the top of `main()`, after `st.set_page_config()`.

---

## 2. Overview Page Redesign

File: `prospector/control_center/pages/_overview.py`

Replace the current flat `st.metric` + `st.divider()` layout with a card-based
dashboard. Keep all existing data readers and fragment refresh logic.

### 2.1 Page header

Replace `st.title("🛰 Prospector Control Center")` with a cleaner header row:

```
[logo/icon] PROSPECTOR    [Engine: 🟢 Running] [Last run: 2m ago]
```

Use `st.html()` for the custom header. The engine status dot comes from
`readers.load_jobs()` (green if a job is currently running, grey otherwise).

### 2.2 KPI strip → KPI cards row

Replace the 4-column `st.metric` grid with 5 KPI cards in a single row using
`st.html()`:

| Card | Content |
|------|---------|
| ✅ Pass rate | Large: `14` — Sub: `4.5%` of ruled — Delta: trend arrow if available |
| 🛑 Kill rate | Large: `300` — Sub: `95.5%` of ruled |
| ⏸ Deferred | Large: `53` — Sub: `since last run` |
| 💰 Spend | Large: `$0.00` — Sub: `0% of $20 cap` — Progress bar below |
| ⏳ Pending | Large: `3` — Sub: `signals in queue` |

Each card is an `st.html()` block with the `.cc-kpi` class. Values are
right-aligned within each card. Keep the `@st.fragment(run_every="10s")` on
this section.

For the golden discrimination: if a run exists, show a mini sparkline or just
the score with PASS/FAIL badge inside one of the cards. If no golden runs, show
"⚡ No golden run" as a muted card.

### 2.3 Moat status → Status panel

Replace the current subheader + table with a horizontal status panel using
`st.html()`. Show each operator as a colored pill:

```
⚡ MOAT   [🟢 gemini_cli HEALTHY] [🟢 claude_cli HEALTHY] [🔴 deepseek DEAD 12m]
```

Use `.cc-pill` classes. If the moat is fully down, show a prominent red banner.
Otherwise, just the pills with a green checkmark header.

### 2.4 Alarms → Severity cards

Replace the current `st.columns([1, 6, 2])` alarm list with proper card-based
alarms using `st.html()`:

Each alarm becomes a card with:
- Left color strip (red for alarm/critical, amber for warn)
- Code label (e.g. `ZERO_YIELD`) in a small monospace pill
- Lane tag (e.g. `[growth]`)
- Message text (first ~120 chars, truncated with ellipsis)
- "View" button on the right side

Only show the first 4 alarms with a "Show all N alarms" expander for the rest.

Keep the `_alarm_view_button()` function for navigation.

### 2.5 Recent runs → Styled table

Keep the existing `st.dataframe` but add column config with:
- Status column as colored pills using `st.column_config.Column` with HTML
  (or use a custom renderer)
- Better column widths
- Monospace font for job_id

### 2.6 Quick actions row

At the very top (above KPI cards), add a row of small action buttons:

```
[🚀 New Run] [📋 Browse Catalogue] [🔬 Diagnostics]
```

These use `st.button` in a row of columns, navigating via session state.

---

## 3. Test

Create `tests/test_ui_theme.py`:

```python
def test_theme_css_injects_without_error():
    """Theme CSS injection must not raise any exception."""
    from prospector.control_center.theme import inject_theme, THEME_CSS
    assert isinstance(THEME_CSS, str)
    assert len(THEME_CSS) > 200
    assert ".cc-card" in THEME_CSS
    assert ".cc-kpi" in THEME_CSS
    assert ".cc-alarm" in THEME_CSS
    assert ".cc-pill" in THEME_CSS


def test_overview_imports_dont_crash():
    """Overview page module must import without errors."""
    from prospector.control_center.pages import _overview
    assert hasattr(_overview, "render")


def test_theme_module_imports_cleanly():
    """Theme module must be importable."""
    from prospector.control_center import theme
    assert hasattr(theme, "inject_theme")
```

---

## 4. Implementation notes

- **Do NOT change any `readers.py` functions.** Only presentation-layer changes.
- **Keep `st.fragment(run_every="10s")` on the KPI section.**
- **Keep `_alarm_view_button()` navigation logic.** Just change its visual presentation.
- **Use `st.html()` for card layouts**, not raw HTML strings in st.markdown.
- **All existing data queries remain identical.** Only the HTML wrapping changes.
- **Do NOT touch:** `_catalogue.py`, `_launcher.py`, `_diagnostics.py`,
  `_parameters.py`, `_reports.py`, `_resume.py`, `readers.py`, `app.py` routing (except
  adding the `inject_theme()` call).

---

## 5. Acceptance criteria

1. `.streamlit/config.toml` has a `[theme]` section with dark palette
2. `prospector/control_center/theme.py` exists and exports `inject_theme()`
3. `app.py` calls `inject_theme()` in `main()`
4. Overview page renders with card-based KPI row (not flat st.metric)
5. Moat status shows as colored pills (not a table)
6. Alarms render as severity-coded cards (not a flat list)
7. Recent runs table has status pills
8. Quick actions row at top
9. `tests/test_ui_theme.py` passes (3 tests)
10. Full test suite still passes (no regressions)
