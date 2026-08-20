#!/usr/bin/env python3
"""EXPERIMENT: does reusing the CLI cwd convert cache_write into cache_read?

Arm A reproduces the daemon's current behaviour exactly (prospector/claude_cli.py:119,
tempfile.mkdtemp per call). Arm B reuses ONE stable dir. Identical prompt, identical
env-stripping, sequential, same binary. The CLI's own `total_cost_usd` is the measurement.

READ-ONLY w.r.t. the repo: writes nothing outside its temp dirs.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 4

# A prompt shaped like the daemon's real non-critical work: structured JSON out, short.
PROMPT = (
    "OUTPUT CONTRACT — READ FIRST: Execute the task below LITERALLY. Return ONLY the JSON "
    "specified — no preamble, no prose, no meta-discussion.\n\n"
    "TASK: Return a JSON object with exactly one key, \"ok\", whose value is the integer 1."
)

CHILD_ENV = {k: v for k, v in os.environ.items()
             if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}


def call(cwd):
    cmd = [CLAUDE, "-p", PROMPT, "--output-format", "json"]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                       timeout=180, stdin=subprocess.DEVNULL, env=CHILD_ENV)
    if p.returncode != 0:
        return {"error": (p.stdout.strip()[-200:] or p.stderr.strip()[-200:])}
    try:
        d = json.loads(p.stdout)
    except ValueError:
        return {"error": "non-json stdout: " + p.stdout[:200]}
    u = d.get("usage") or {}
    cc = u.get("cache_creation") or {}
    return {
        "cost": float(d.get("total_cost_usd") or 0),
        "read": u.get("cache_read_input_tokens", 0),
        "w5": cc.get("ephemeral_5m_input_tokens", 0),
        "w1": cc.get("ephemeral_1h_input_tokens", 0),
        "write_total": u.get("cache_creation_input_tokens", 0),
        "out": u.get("output_tokens", 0),
    }


def run_arm(name, fresh):
    root = os.path.join(tempfile.gettempdir(), "cache_expt_" + name)
    os.makedirs(root, exist_ok=True)
    stable = tempfile.mkdtemp(prefix="s_", dir=root)
    rows = []
    print(f"\n=== ARM {name}: {'FRESH mkdtemp per call (current daemon)' if fresh else 'ONE STABLE cwd reused'} ===")
    print(f"{'#':>3} {'cost$':>8} {'cache_read':>11} {'write_5m':>9} {'write_1h':>9} {'out':>6}")
    for i in range(1, N + 1):
        cwd = tempfile.mkdtemp(prefix="c_", dir=root) if fresh else stable
        r = call(cwd)
        if fresh:
            shutil.rmtree(cwd, ignore_errors=True)
        if "error" in r:
            print(f"{i:>3}  ERROR: {r['error']}")
            continue
        rows.append(r)
        print(f"{i:>3} {r['cost']:>8.4f} {r['read']:>11,} {r['w5']:>9,} {r['w1']:>9,} {r['out']:>6,}")
    shutil.rmtree(root, ignore_errors=True)
    if rows:
        tot = sum(r["cost"] for r in rows)
        print(f"    TOTAL ${tot:.4f}   mean ${tot/len(rows):.4f}/call   "
              f"read {sum(r['read'] for r in rows):,}  written {sum(r['write_total'] for r in rows):,}")
    return rows


a = run_arm("A_fresh", True)
b = run_arm("B_stable", False)

if a and b:
    ma = sum(r["cost"] for r in a) / len(a)
    mb = sum(r["cost"] for r in b) / len(b)
    print(f"\n{'='*62}\nRESULT  A(fresh)=${ma:.4f}/call   B(stable)=${mb:.4f}/call")
    if mb < ma:
        print(f"        stable cwd is {ma/mb:.2f}x cheaper  (saves {1-mb/ma:.1%} per call)")
    else:
        print(f"        NO SAVING — hypothesis refuted ({mb/ma:.2f}x)")
    print(f"        A cache_read total {sum(r['read'] for r in a):,} | "
          f"B cache_read total {sum(r['read'] for r in b):,}")
