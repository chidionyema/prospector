"""A batch halted by a dead brain must still write its diagnostics.

WHY THIS EXISTS. `run_signal` collected an infrastructure halt during the completion loop and
re-raised it the moment the loop drained — before the summary and before
`persist_batch_diagnostics`. So a tick that lost the moat recorded nothing at all.

Measured on production 2026-08-18: `/data/store/scheduler/batch_diagnostics.jsonl` had not been
written since 2026-08-16T03:33, while the engine produced 326 dossiers that day. `rates_over_time`
— the only per-day pass/kill/outage series in the estate — ended on 2026-08-15 and showed a flat
line where a three-day outage was. The founder found out about the outage before the platform did.

The measurement side was already correct and simply never received the row.
`prospector/ops/metrics.py::_rate_point` distinguishes the two cases explicitly: "N of M vetted
deferred and nothing was ruled — a retrieval/moat outage, not a 0% pass rate". That sentence can
only print if the halted batch wrote a row.

WHY THIS TEST READS THE SOURCE RATHER THAN RUNNING THE PIPELINE. `run_signal` takes a live store,
an operator chain, a retrieval chain and a thread pool, and the defect is a statement ORDER inside
it. The thing that must stay true is "the raise comes after the write", and that is exactly what an
AST walk can assert without standing up half the engine. The two guards below make sure the scan
is not vacuous.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
RUN_PY = REPO / "prospector" / "run.py"


def _run_signal() -> ast.FunctionDef:
    tree = ast.parse(RUN_PY.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run_signal":
            return node
    raise AssertionError("run_signal is gone from prospector/run.py — this guard needs rewriting")


def _lines_of(fn: ast.FunctionDef, predicate) -> list[int]:
    return sorted({n.lineno for n in ast.walk(fn) if predicate(n)})


def _raise_lines(fn: ast.FunctionDef) -> list[int]:
    def is_halt_raise(n):
        return (isinstance(n, ast.Raise) and isinstance(n.exc, ast.Name)
                and n.exc.id == "infra_halt")
    return _lines_of(fn, is_halt_raise)


def _persist_lines(fn: ast.FunctionDef) -> list[int]:
    def is_persist(n):
        return (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "persist_batch_diagnostics")
    return _lines_of(fn, is_persist)


def test_the_scan_finds_both_statements():
    """Guard the guard. If either list comes back empty the ordering assertion below is vacuous."""
    fn = _run_signal()
    assert _raise_lines(fn), "no `raise infra_halt` found in run_signal"
    assert _persist_lines(fn), "no persist_batch_diagnostics call found in run_signal"


def test_the_halt_is_raised_only_after_the_batch_is_recorded():
    fn = _run_signal()
    persist = max(_persist_lines(fn))
    early = [ln for ln in _raise_lines(fn) if ln < persist]
    assert not early, (
        f"`raise infra_halt` at line(s) {early} runs before persist_batch_diagnostics at "
        f"line {persist}. A batch halted by a dead brain will write no diagnostics row, and "
        f"the pass/kill/outage series will show a flat line through the outage."
    )


def test_the_halt_is_still_raised():
    """The fix must not become a swallow. The caller DEFERS on this exception; losing it would
    turn an outage into a silent success, which is worse than the blind spot it fixed."""
    assert _raise_lines(_run_signal()), "run_signal no longer re-raises the infrastructure halt"
