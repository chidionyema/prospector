#!/usr/bin/env python3
"""Inventory every place the engine turns a FAILURE into a PLAUSIBLE EMPTY ANSWER.

THE BUG CLASS, measured 2026-08-15.  A minimax verdict was destroyed by three layers in a
row, each of which caught a failure and returned something that looked like an answer:
`json.loads` strict failed (caught, next strategy), a bracket scan returned the citations
array instead of the verdict object (parsed fine, wrong shape), and `verdict_for` coerced
the wrong shape to `{}` (below the `except`, so nothing deferred).  Output: a check reading
`unverifiable, conf 0.0, rationale ""` — indistinguishable from a real inconclusive
finding — which the golden promotion gate then recorded as evidence that MINIMAX answers
without reasons.  It doesn't.  We threw its answer away and wrote down that it was silent.

That is one bug appearing 87 times, not 87 bugs.  It is also the reason we only ever find
these in production: a swallowed failure has no stack trace and no red test.  It has a
normal-looking dossier.

THE DISCRIMINATOR is not "does it return empty" — plenty of code legitimately returns `[]`
when a search genuinely found nothing.  It is:

    can the CALLER tell "empty because nothing matched" from "empty because it broke"?

If yes, the empty is a value.  If no, the empty is a lie with a confident face.  This script
computes the mechanical half of that question for every site (does the handler set a
failure flag, does it re-raise, how wide is the except, can the success path return the
same value) and ranks by blast radius, so the human/agent half — reading the callers — is
spent only where it can change something.

Usage:
    .venv/bin/python tools/audit_swallow_sites.py                 # ranked table
    .venv/bin/python tools/audit_swallow_sites.py --json          # machine-readable
    .venv/bin/python tools/audit_swallow_sites.py --tier 1        # only the worst tier
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "prospector"

# A return value that is indistinguishable from a legitimate "nothing here" answer.
EMPTY_LITERALS = ("[]", "{}", "None", "''", '""', "0", "0.0", "set()", "tuple()")

# Names that, if ASSIGNED OR PASSED in the handler, mean the caller was told it broke.
# `retrieval_failed` is the specific one that makes verify.py DEFER instead of KILL.
FAILURE_FLAGS = {
    "degraded", "retrieval_failed", "failed", "error", "errors", "exhausted",
    "ok", "success", "healthy", "unverifiable", "partial", "incomplete", "stale",
}

# A qualified name built on one of those words says the same thing: `price_history_error`
# and `bundle_failed` name a failure as plainly as `error` does. Kept to suffixes so it
# stays a statement about failure names, not a wildcard that waves through any identifier
# with "ok" in the middle of it.
FAILURE_FLAG_SUFFIXES = ("_error", "_errors", "_failed", "_failure", "_exhausted")


def _is_failure_name(name: str) -> bool:
    """Does this identifier tell the caller, by its name, that the thing failed?"""
    return bool(name) and (
        name in FAILURE_FLAGS or name.endswith(FAILURE_FLAG_SUFFIXES))

# Exception types narrow enough that catching them is a decision about a KNOWN condition,
# not a blanket "whatever went wrong, carry on".
NARROW_EXCEPTIONS = {
    "KeyError", "IndexError", "ValueError", "TypeError", "AttributeError",
    "StopIteration", "FileNotFoundError", "JSONDecodeError", "UnicodeDecodeError",
    "ZeroDivisionError", "ParseError",
}


@dataclass
class Site:
    file: str
    line: int
    func: str
    returns: str
    handler_types: list[str]
    is_broad: bool          # `except:` or `except Exception:` — catches bugs, not conditions
    logs: bool              # emits SOMETHING to the log
    logs_at_error: bool     # logger.error/exception, not a debug whisper
    sets_failure_flag: bool # the caller is TOLD, in the return value, that this failed
    reraises_some: bool     # a sibling handler re-raises (a deliberate triage)
    success_can_return_same: bool  # the smoking gun: same value on the happy path
    callers: int = 0
    tier: int = 3
    reason: str = ""
    notes: list[str] = field(default_factory=list)
    waiver: str = ""

    @property
    def ref(self) -> str:
        return f"{self.file}:{self.line}"


def _seg(node: ast.AST) -> str:
    return ast.unparse(node) if node is not None else ""


def _walk_funcs(tree: ast.AST):
    """Yield (func_node, qualified_name) for every function, methods included."""
    stack: list[tuple[ast.AST, str]] = [(tree, "")]
    while stack:
        node, prefix = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                yield child, name
                stack.append((child, f"{name}."))
            elif isinstance(child, ast.ClassDef):
                stack.append((child, f"{prefix}{child.name}."))
            else:
                stack.append((child, prefix))


def _index_tree(tree: ast.AST) -> tuple[list[ast.AST], dict[int, tuple[int, int]]]:
    """One preorder list of every node, plus each node's slice of it.

    `order[lo:hi]` for `span[id(node)] == (lo, hi)` is exactly the set `ast.walk(node)`
    yields — same nodes, different order, and nothing downstream depends on the order
    (`_returns_in` is counted, and the site list is re-sorted by (tier, callers, file, line)).

    This exists for speed, and the speed is the whole cost of the tool. `scan_file` used to
    call `ast.walk` twice per function — once for the returns, once for the try blocks — and
    a function nested inside another was walked again by every enclosing function.
    Measured 2026-08-17 over `prospector/`: 567,284 `ast.walk` calls, 56.8s of the tool's
    116s under cProfile, 55.8s of real time. One walk per FILE replaces all of it.
    """
    order: list[ast.AST] = []
    span: dict[int, tuple[int, int]] = {}

    def visit(node: ast.AST) -> None:
        start = len(order)
        order.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)
        span[id(node)] = (start, len(order))

    visit(tree)
    return order, span


def _returns_in(node: ast.AST) -> list[str]:
    return _returns_under(ast.walk(node))


def _returns_under(nodes: Iterable[ast.AST]) -> list[str]:
    out = []
    for n in nodes:
        if isinstance(n, ast.Return):
            out.append(_seg(n.value) if n.value is not None else "None")
    return out


def _handler_returns_empty(handler: ast.ExceptHandler) -> str | None:
    """The empty literal this handler hands back, if any.

    Counts both `return <empty>` and `<var> = <empty>` followed by a fall-through, because
    verify.py's real defect was the assignment form (`data = {}`), not a return.
    """
    for n in ast.walk(handler):
        if isinstance(n, ast.Return):
            v = _seg(n.value) if n.value is not None else "None"
            if v in EMPTY_LITERALS:
                return v
        if isinstance(n, ast.Assign):
            v = _seg(n.value)
            if v in EMPTY_LITERALS:
                return f"{_seg(n.targets[0])} = {v}"
    return None


def _logger_subtree_ids(handler: ast.ExceptHandler) -> set[int]:
    """Every node that lives INSIDE a logging call.

    This exists because the first version of this script got the answer backwards on the
    highest-blast-radius site in the engine. `ClaudeCliGroundingProvider.search` (119
    call sites) ends `except Exception as e: logger.warning(..., extra={"error": str(e)});
    return []` — and "error" is in FAILURE_FLAGS, so the scan saw a failure flag and filed
    a total grounding outage returning `[]` as TIER 3, legitimate.

    It is the opposite. `extra={"error": ...}` goes to the LOG. The caller gets `[]` and
    has no way on earth to tell "the web has nothing on this" from "the provider threw".
    That confusion is not hypothetical here: it is `learning-exa-silent-grounding-outage`
    and `a-swallowed-outage-returns-empty-it-does-not-raise`, both already in memory.

    A tool built to find code that hides failures must not hide them itself. The flag has
    to be in the RETURN VALUE; anything inside a logger call is unreadable to the caller
    and does not count.
    """
    out: set[int] = set()
    for n in ast.walk(handler):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and isinstance(n.func.value, ast.Name) \
                and n.func.value.id in {"logger", "log", "logging"}:
            for sub in ast.walk(n):
                out.add(id(sub))
    return out


def _sets_failure_flag(handler: ast.ExceptHandler) -> bool:
    """Did the handler tell the caller, IN DATA, that this was a failure?

    Keyword arguments count (`CheckResult(..., retrieval_failed=True)`) and so do plain
    assignments — both reach the caller. A log line does NOT count: the caller cannot read
    the log, and the whole failure mode of this bug class is downstream code proceeding
    confidently on a value it has no way to question.

    A dict ITEM assignment counts too (`rec["error"] = str(exc)`). It reaches the caller by
    exactly the same route as `rec.error = ...`, and handlers that build a result dict are
    the common shape in the ops and console readers. Missing it graded two console sites as
    "no flag reaches the caller" when the flag was sitting in the returned dict — the
    auditor calling a real fix a swallow, which is how a ratchet loses its credibility.
    """
    logged = _logger_subtree_ids(handler)
    for n in ast.walk(handler):
        if id(n) in logged:
            continue
        if isinstance(n, ast.keyword) and _is_failure_name(n.arg or ""):
            return True
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    nm = t.id
                elif isinstance(t, ast.Attribute):
                    nm = t.attr
                elif isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant):
                    nm = t.slice.value if isinstance(t.slice.value, str) else ""
                else:
                    nm = ""
                if _is_failure_name(nm):
                    return True
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                        and _is_failure_name(k.value):
                    return True
    return False


def _log_calls(handler: ast.ExceptHandler) -> tuple[bool, bool]:
    logs = at_error = False
    for n in ast.walk(handler):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if isinstance(n.func.value, ast.Name) and n.func.value.id in {"logger", "log", "logging"}:
                logs = True
                if n.func.attr in {"error", "exception", "critical", "fatal"}:
                    at_error = True
    return logs, at_error


WAIVER_RE = re.compile(r"#\s*swallow-ok:\s*(.+?)\s*$", re.MULTILINE)
MIN_WAIVER_CHARS = 30


def _waiver(src_lines: list[str], h: ast.ExceptHandler) -> str:
    """A per-site, in-diff waiver: `# swallow-ok: <why>` inside the handler body.

    The ladder's step 3 (narrow the except, log at ERROR) is a legitimate ENDING for a
    best-effort path, but this tool grades on except-breadth and return value and cannot see
    that a path is best-effort by contract. Without an escape hatch those sites either sit in
    tier 1 forever — training everyone to ignore the number — or get fixed into worse code.

    The waiver is deliberately awkward in the right way: it lives at the site (so it is in
    the diff a reviewer reads, not in a list far away), it must carry a real reason, and it
    is COUNTED, so quietly waiving the class away is itself a visible regression.
    """
    end = getattr(h, "end_lineno", h.lineno) or h.lineno
    body = "\n".join(src_lines[h.lineno - 1:end])
    m = WAIVER_RE.search(body)
    if not m:
        return ""
    reason = m.group(1).strip()
    if len(reason) < MIN_WAIVER_CHARS:
        return f"REJECTED (reason under {MIN_WAIVER_CHARS} chars): {reason}"
    return reason


def scan_file(path: Path) -> list[Site]:
    src = path.read_text(encoding="utf-8")
    src_lines = src.splitlines()
    tree = ast.parse(src, filename=str(path))
    rel = str(path.relative_to(REPO))
    sites: list[Site] = []

    order, span = _index_tree(tree)

    for func, qname in _walk_funcs(tree):
        lo, hi = span[id(func)]
        under = order[lo:hi]
        all_returns = _returns_under(under)
        for tnode in under:
            if not isinstance(tnode, ast.Try):
                continue
            reraises = any(
                isinstance(n, ast.Raise) for h in tnode.handlers for n in ast.walk(h))
            for h in tnode.handlers:
                empty = _handler_returns_empty(h)
                if empty is None:
                    continue
                # A handler that also re-raises on this path is a triage, not a swallow.
                if any(isinstance(n, ast.Raise) and n.exc is None for n in ast.walk(h)):
                    continue
                types = []
                if h.type is None:
                    types = ["<bare>"]
                elif isinstance(h.type, ast.Tuple):
                    types = [_seg(e) for e in h.type.elts]
                else:
                    types = [_seg(h.type)]
                short = [t.split(".")[-1] for t in types]
                broad = any(t in {"<bare>", "Exception", "BaseException"} for t in short)
                logs, at_err = _log_calls(h)
                # The smoking gun: does the HAPPY path ever return this same value? If so
                # the caller provably cannot tell the two apart — no reading required.
                bare = empty.split("=")[-1].strip()
                same = all_returns.count(bare) > 1 or (
                    bare in all_returns and "return" not in empty)
                sites.append(Site(
                    file=rel, line=h.lineno, func=qname, returns=empty,
                    handler_types=types, is_broad=broad, logs=logs, logs_at_error=at_err,
                    sets_failure_flag=_sets_failure_flag(h),
                    reraises_some=reraises,
                    success_can_return_same=same,
                    waiver=_waiver(src_lines, h)))
    return sites


def classify(s: Site) -> Site:
    """Tier 1 = the caller CANNOT tell. Tier 2 = observable but untyped. Tier 3 = fine."""
    if s.waiver and not s.waiver.startswith("REJECTED"):
        s.tier, s.reason = 3, "waived at the site: " + s.waiver
        return s
    if s.waiver:
        s.notes.append(s.waiver)   # a malformed waiver does NOT demote

    if s.sets_failure_flag:
        s.tier, s.reason = 3, "handler returns a failure flag — caller can tell"
        return s

    if s.is_broad and s.success_can_return_same:
        s.tier = 1
        s.reason = ("broad except returns the SAME value as the success path — "
                    "indistinguishable from a real empty answer")
    elif s.is_broad and not s.logs:
        s.tier = 1
        s.reason = "broad except, silent, no flag — the failure leaves no trace at all"
    elif s.success_can_return_same:
        s.tier = 2
        s.reason = "same value as the success path, but the except is narrow (a known condition)"
    elif s.is_broad:
        s.tier = 2
        s.reason = ("broad except: catches OUR bugs as well as the condition it means to "
                    "handle, and reports them only to the log")
    else:
        s.tier = 3
        s.reason = "narrow except, distinct value — a decision about a known condition"

    if s.is_broad and not s.logs_at_error and s.tier <= 2:
        s.notes.append("not even logged at ERROR")
    if s.reraises_some:
        s.notes.append("sibling handler re-raises — triage already exists here")
    return s


def count_callers(sites: list[Site], files: list[Path]) -> None:
    """Blast radius, approximated by name. Deliberately crude and labelled as such: it is a
    RANKING aid, not a claim. A shadowed name inflates a count; it never hides a site."""
    blob = "\n".join(p.read_text(encoding="utf-8") for p in files)
    for s in sites:
        leaf = s.func.split(".")[-1]
        s.callers = max(0, blob.count(f"{leaf}(") - 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tier", type=int, default=None)
    ap.add_argument("--path", default=str(PKG))
    args = ap.parse_args()

    files = sorted(Path(args.path).rglob("*.py"))
    sites: list[Site] = []
    for f in files:
        try:
            sites.extend(scan_file(f))
        except SyntaxError as e:
            print(f"SKIP {f}: {e}", file=sys.stderr)
    sites = [classify(s) for s in sites]
    count_callers(sites, files)
    sites.sort(key=lambda s: (s.tier, -s.callers, s.file, s.line))

    if args.tier:
        sites = [s for s in sites if s.tier == args.tier]

    if args.json:
        print(json.dumps([asdict(s) for s in sites], indent=2))
        return 0

    by_tier = {1: [], 2: [], 3: []}
    for s in sites:
        by_tier[s.tier].append(s)

    names = {1: "TIER 1 — the caller CANNOT tell failure from a real empty answer",
             2: "TIER 2 — observable in the log, but still untyped to the caller",
             3: "TIER 3 — legitimate: the failure is carried in the return value"}
    for t in (1, 2, 3):
        group = by_tier[t]
        if args.tier and t != args.tier:
            continue
        print(f"\n{'='*100}\n{names[t]}  ({len(group)})\n{'='*100}")
        for s in group:
            note = ("  [" + "; ".join(s.notes) + "]") if s.notes else ""
            print(f"{s.ref:<44} {s.func:<38} -> {s.returns}")
            print(f"{'':<44} except {'/'.join(s.handler_types)}  "
                  f"callers~{s.callers}{note}")
            if t < 3:
                print(f"{'':<44} WHY: {s.reason}")
    print(f"\nTOTAL {len(sites)}   tier1={len(by_tier[1])} "
          f"tier2={len(by_tier[2])} tier3={len(by_tier[3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
