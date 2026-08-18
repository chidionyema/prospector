"""The console's automations screen: one line per automation, measured now.

Why this is a discovery loop and not a list
-------------------------------------------
`OPS_AUTOMATION_PRINCIPLES.md` R6 says every automation appears on the console as one line, and
E6 says moving the whole set to another startup is copying two directories and writing YAML. A
hand-maintained list of screens breaks both: the fourth automation would need a React file and a
Python edit, and the next startup would inherit our names. So this module discovers them instead.

An automation is anything with BOTH an engine at `ops/automations/<name>.py` and a declaration at
`ops/config/<name>.yaml`. Adding one is those two files. Nothing here needs editing, ever.

Why it runs them instead of reading a cached status
---------------------------------------------------
P4: state is a probe, never a sentence. A stored status is a sentence somebody wrote down, and the
defect this console has had repeatedly is a screen reading stale state as live. So each line is a
real `--json` run, with its own exit code, right now.

The cost of that honesty is latency, so the runs are concurrent and each is bounded. A run that
overruns its bound is reported `unknown`, never `ok` — P6, an empty result and a failed check never
share a code path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

#: Seconds a single automation may take before its line is reported `unknown`. Bounded because the
#: console is a web page: one automation reaching a slow network must not hang the screen.
DEFAULT_TIMEOUT_S = 25.0

#: Exit codes are the interface (R2). 2 is mandatory and distinct: "I could not tell" is never
#: "clean".
_STATUS_BY_CODE = {0: "ok", 1: "findings", 2: "unknown"}


def _repo_root() -> Path:
    """The checkout this module lives in. `parents[2]` is <root>/prospector/ops/<file>."""
    return Path(__file__).resolve().parents[2]


def discover(root: Optional[Path] = None) -> list[str]:
    """Names that have BOTH an engine and a declaration, sorted.

    An engine with no declaration is a half-built automation and an orphan YAML is a leftover;
    neither is something an operator can act on, so neither gets a line.
    """
    root = root or _repo_root()
    engines = {
        p.stem for p in (root / "ops" / "automations").glob("*.py")
        if not p.stem.startswith("_")
    }
    declared = {p.stem for p in (root / "ops" / "config").glob("*.yaml")}
    return sorted(engines & declared)


def declared_timeout(name: str, root: Path, fallback: float = DEFAULT_TIMEOUT_S) -> float:
    """How long this automation is allowed, read from its own declaration.

    P1: the bound is a fact about a particular automation — the offsite backup opens a remote
    machine and a bucket, the log check reads local files — so it belongs in that automation's
    YAML under `console_timeout_s`, never in this engine. Anything unreadable falls back rather
    than raising: a malformed number must not blank the whole screen.
    """
    path = root / "ops" / "config" / f"{name}.yaml"
    try:
        import yaml  # imported here so a checkout without pyyaml still renders the screen

        doc = yaml.safe_load(path.read_text()) or {}
        return float(doc.get("console_timeout_s") or fallback)
    except Exception:
        return fallback


def _probe(name: str) -> str:
    """The exact command a human can re-run (R3). Printed on the screen next to the line."""
    return f"python -m ops.automations.{name} --json"


def run_one(name: str, root: Optional[Path] = None,
            timeout_s: Optional[float] = None) -> dict[str, Any]:
    """Run one automation read-only and return its console line.

    The automation's own `--json` payload is passed through untouched when it parses. It already
    obeys R7 (key names, never values), and re-shaping it here would be a second place to keep in
    step with the contract.
    """
    root = Path(root) if root else _repo_root()
    if timeout_s is None:
        timeout_s = declared_timeout(name, root)
    started = time.time()
    line: dict[str, Any] = {
        "automation": name,
        "status": "unknown",
        "checked": None,
        "findings": [],
        "ran_at": None,
        "probe": _probe(name),
        "took_ms": None,
        "error": None,
    }

    env = dict(os.environ)
    # Without this the child imports `ops` only if cwd happens to be on the path; being explicit
    # means the console works the same when launchd, a test, or a developer runs it.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))

    try:
        proc = subprocess.run(
            [sys.executable, "-m", f"ops.automations.{name}", "--json"],
            cwd=str(root), env=env, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        line["error"] = (f"did not answer within {timeout_s:.0f}s; reported unknown rather than "
                         f"clean")
        line["took_ms"] = round((time.time() - started) * 1000.0, 1)
        return line
    except OSError as exc:
        line["error"] = f"{type(exc).__name__}: {exc}"
        line["took_ms"] = round((time.time() - started) * 1000.0, 1)
        return line

    line["took_ms"] = round((time.time() - started) * 1000.0, 1)

    payload: Any = None
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            payload = None
            line["error"] = f"output was not JSON: {exc}"

    if isinstance(payload, dict):
        line.update({k: v for k, v in payload.items() if k != "automation"})
        line["automation"] = payload.get("automation") or name
        line["probe"] = payload.get("probe") or _probe(name)

    # The exit code is the verdict, not the payload's own status field: a crashed automation can
    # still print a hopeful JSON body, and the shell's answer is the one that cannot lie about
    # whether the process finished.
    coded = _STATUS_BY_CODE.get(proc.returncode)
    if coded is not None and not isinstance(payload, dict):
        # A STATUS NEEDS A PAYLOAD BEHIND IT. `raise RuntimeError(...)` exits 1, which
        # `_STATUS_BY_CODE` reads as "findings" - so a crashed automation rendered as a normal
        # red line with an empty findings list, which is exactly the "failure looks like an
        # answer" defect this view exists to catch. No parsed body means the automation never
        # reported, whatever the exit code was.
        coded = None
    if coded is None:
        line["status"] = "unknown"
        tail = (proc.stderr or "").strip().splitlines()
        line["error"] = (f"exit {proc.returncode}: " + (tail[-1] if tail else "no output"))
    else:
        line["status"] = coded

    if line["status"] == "unknown" and not line["error"] and proc.stderr.strip():
        line["error"] = proc.stderr.strip().splitlines()[-1]

    return line


def read_automations(cfg: Any = None, args: Optional[dict] = None) -> dict[str, Any]:
    """The console view. Runs every discovered automation concurrently and returns their lines.

    Concurrency is bounded by the number of automations, which is small by construction — P9, one
    idea per automation, means the set grows slowly and each run is a subprocess doing IO.
    """
    args = args or {}
    root = Path(args["root"]) if args.get("root") else _repo_root()
    # None means "ask each automation's own declaration"; an explicit value overrides all of them,
    # which is what the tests use.
    timeout_s = float(args["timeout_s"]) if args.get("timeout_s") else None

    names = discover(root)
    if not names:
        # Not an error. A checkout without `ops/automations/` is a valid state — the engines land
        # in a later merge — and reporting it as a failure would put a red line on a healthy
        # console.
        return {"root": str(root), "count": 0, "automations": [],
                "note": "no automation has both an engine and a declaration in this checkout"}

    with ThreadPoolExecutor(max_workers=min(8, len(names))) as pool:
        lines = list(pool.map(lambda n: run_one(n, root, timeout_s), names))

    order = {"unknown": 0, "findings": 1, "ok": 2}
    # Anything needing attention sorts first: the operator should not have to read past green.
    lines.sort(key=lambda row: (order.get(row["status"], 0), row["automation"]))

    return {
        "root": str(root),
        "count": len(lines),
        "needs_attention": sum(1 for row in lines if row["status"] != "ok"),
        "automations": lines,
    }
