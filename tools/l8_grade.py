#!/usr/bin/env python3
"""Grade one `claude -p --output-format json` run for the L8 A/B and append a row.

Lives in its OWN FILE on purpose. The previous version was inlined as `python3 -c '...'`
inside a single-quoted shell string; the f-string it contained needed double quotes, the
shell passed the backslashes through literally, and Python raised

    SyntaxError: unexpected character after line continuation character

at COMPILE time — i.e. after each paid `claude -p` call had already run. Six calls were
billed and every result discarded. A grader is not a place for nested quoting.

usage: l8_grade.py <out.jsonl> <arm> <rep> <t0> <t1> <must...>   (JSON on stdin)
"""
import json
import sys

out_path, arm, rep, t0, t1 = sys.argv[1:6]
must = sys.argv[6:]

j = json.loads(sys.stdin.read())
txt = j.get("result") or ""
hits = [m for m in must if m.lower() in txt.lower()]
u = j.get("usage") or {}

row = {
    "arm": arm,
    "rep": int(rep),
    "cost_usd": j.get("total_cost_usd"),
    "turns": j.get("num_turns"),
    "wall_s": round(float(t1) - float(t0), 1),
    "in": u.get("input_tokens"),
    "out": u.get("output_tokens"),
    "cache_read": u.get("cache_read_input_tokens"),
    "cache_write": u.get("cache_creation_input_tokens"),
    # A cheaper WRONG answer is not a saving, so correctness is graded mechanically
    # against ground truth fixed before the runs — never judged after seeing the cost.
    "correct": len(hits) == len(must),
    "hits": hits,
    "answer": txt.strip()[:200],
}

with open(out_path, "a") as fh:
    fh.write(json.dumps(row) + "\n")

print("  {} rep{}: ${} turns={} {}s correct={} {}".format(
    row["arm"], row["rep"], row["cost_usd"], row["turns"],
    row["wall_s"], row["correct"], hits))
