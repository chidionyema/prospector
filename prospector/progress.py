"""Human-readable live console reporter (Part 15 — observability, the *human* view).

The JSON telemetry logger (telemetry.py) is the machine/audit trail — exhaustive,
structured, written to a file you can tail or grep later. THIS module is the
opposite: a small, clean, real-time stream a person watches while a run executes,
so the engine is never a black box.

  - Writes to stderr (stdout is reserved for the final result: dossier / JSON).
  - Thread-safe: the vetting pool calls report_result() concurrently.
  - Silenced with PROSPECTOR_QUIET=1 (e.g. for scripted/piped use).

Nothing here is load-bearing for verdicts — it is purely presentational.
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Any, Dict, Optional

_QUIET = os.environ.get("PROSPECTOR_QUIET") == "1"
_LOCK = threading.Lock()

# Decision glyphs (fall back gracefully if the terminal can't render them).
_GLYPH = {"pass": "✅", "kill": "❌", "defer": "⏸️"}


def _emit(line: str) -> None:
    if _QUIET:
        return
    with _LOCK:
        print(line, file=sys.stderr, flush=True)


def banner(title: str) -> None:
    _emit(f"\n\033[1m🔎 {title}\033[0m")


def step(msg: str) -> None:
    """A pipeline milestone (generate / dedup / prescreen / vet-start)."""
    _emit(f"  ▸ {msg}")


def note(msg: str) -> None:
    """A sub-detail under the current step."""
    _emit(f"      {msg}")


def result(idx: int, total: int, decision: str, title: str,
           gate: Optional[str] = None, composite: Optional[float] = None) -> None:
    """One candidate's outcome, printed the moment its vet finishes."""
    glyph = _GLYPH.get(decision.lower(), "•")
    title_s = (title[:46] + "…") if len(title) > 47 else title
    tail = f"gate={gate}" if gate else (f"composite={composite:.2f}" if composite is not None else "")
    _emit(f"  [{idx}/{total}] {glyph} {decision.upper():4}  {title_s:<48} {tail}")


def _fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def usage_line(usage: Dict[str, Any]) -> None:
    """Render the token/call audit as one readable line."""
    t = usage.get("total", {})
    _emit(
        f"  tokens: {_fmt_tok(t.get('total', 0))} total "
        f"({t.get('calls', 0)} calls, {t.get('web_calls', 0)} web) "
        f"· cached {_fmt_tok(t.get('cached', 0))}"
    )


def summary(n_pass: int, n_kill: int, usage: Optional[Dict[str, Any]] = None,
            n_defer: int = 0) -> None:
    # Survival rate is computed over RULED candidates only — deferrals (retrieval
    # failures) are not evidentiary kills and must not deflate the rate.
    ruled = n_pass + n_kill
    survival = (n_pass / ruled * 100) if ruled else 0.0
    _emit("  " + "─" * 44)
    defer_s = f" / DEFER {n_defer}" if n_defer else ""
    _emit(f"  \033[1mPASS {n_pass} / KILL {n_kill}{defer_s}\033[0m   survival {survival:.0f}% (of ruled)")
    if n_defer:
        _emit(f"  ⚠ {n_defer} deferred — retrieval failed, NOT killed; re-vet when healthy")
    if usage:
        usage_line(usage)
