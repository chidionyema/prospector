#!/usr/bin/env python3
"""Summarise the L8 A/B rows. Separate file for the same reason as l8_grade.py."""
import json
import statistics as st
import sys

rows = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
if not rows:
    print("no rows — every call failed or the grader never ran")
    sys.exit(1)

for arm in ("A_control", "B_graph"):
    a = [r for r in rows if r["arm"] == arm]
    if not a:
        print("{}: no runs".format(arm))
        continue
    costs = [r["cost_usd"] for r in a if r["cost_usd"] is not None]
    mean_c = st.mean(costs) if costs else float("nan")
    med_c = st.median(costs) if costs else float("nan")
    print("{}: n={} mean=${:.4f} median=${:.4f} turns={:.1f} wall={:.1f}s correct={}/{}".format(
        arm, len(a), mean_c, med_c,
        st.mean([r["turns"] or 0 for r in a]),
        st.mean([r["wall_s"] for r in a]),
        sum(1 for r in a if r["correct"]), len(a)))

A = [r["cost_usd"] for r in rows if r["arm"] == "A_control" and r["cost_usd"] is not None]
B = [r["cost_usd"] for r in rows if r["arm"] == "B_graph" and r["cost_usd"] is not None]
if A and B:
    ratio = st.mean(B) / st.mean(A)
    verdict = "graph is CHEAPER" if st.mean(B) < st.mean(A) else "graph is MORE EXPENSIVE"
    print("\nratio B/A = {:.3f}  ({})".format(ratio, verdict))
    allc = all(r["correct"] for r in rows)
    print("both arms correct on every rep: {}".format(allc))
    if not allc:
        print("!! A saving claim is INVALID while any rep answered wrong — a cheaper wrong "
              "answer is not a saving. Report the correctness split, not the ratio.")
