#!/bin/bash
# l8_ab.sh (v2) — does injecting graph evidence actually cost less than letting an agent explore?
#
# COST_PROGRAM §L8 specifies this experiment. Until it runs, the graphify saving is arithmetic
# on an unmeasured N and must stay labelled HYPOTHESIS.
#
#   Arm A (control):   GRAPHIFY_HOOK_OFF=1 — the agent explores with Read/Grep/Glob.
#   Arm B (treatment): hook live — graph evidence injected before the agent acts.
#
# The control switch is real, verified this session:
#   scripts/graphify_session_hook.py:81  and  scripts/graphify_query_hook.py:124
# both return early on GRAPHIFY_HOOK_OFF == "1". Without that, arm A is not a control.
#
# Both arms answer the SAME multi-hop question, graded against the SAME ground truth by
# l8_grade.py, because a cheaper wrong answer is not a saving.
#
# v1 lost 6 paid calls to a quoting SyntaxError in an inlined grader; the grader is now a file.
# `env -u ANTHROPIC_API_KEY` is mandatory: the inherited key is dead ("credit balance too low").
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:?usage: l8_ab.sh <results.jsonl>}"
: > "$OUT"
REPS="${REPS:-3}"
P=/Users/chidionyema/Documents/code/prospector

# Multi-hop on purpose: a one-grep question would measure grep, not exploration.
Q='In this repo: name the function that makes the scheduler skip a generation tick when every trusted brain is dead, give its file:line, and name the field it reads to decide. Answer in ONE line as: function — file:line — field.'

# Ground truth, fixed BEFORE the runs (project CLAUDE.md, verified on disk this session).
MUST=(_moat_blind_reason run_scheduled.py dead_until)

run() {  # run <arm> <rep>
  local arm="$1" rep="$2" t0 t1 json off=""
  [ "$arm" = "A_control" ] && off=1
  t0=$(python3 -c 'import time;print(time.time())')
  json=$(cd "$P" && env -u ANTHROPIC_API_KEY GRAPHIFY_HOOK_OFF="$off" \
           claude -p "$Q" --output-format json 2>/dev/null)
  t1=$(python3 -c 'import time;print(time.time())')
  if [ -z "$json" ]; then echo "  !! $arm rep$rep EMPTY (call failed)"; return; fi
  printf '%s' "$json" | python3 "$HERE/l8_grade.py" "$OUT" "$arm" "$rep" "$t0" "$t1" "${MUST[@]}" \
    || echo "  !! $arm rep$rep GRADER FAILED"
}

echo "=== L8 A/B — $REPS reps per arm ==="
for r in $(seq 1 "$REPS"); do
  run A_control "$r"
  run B_graph   "$r"
done

echo
echo "=== SUMMARY ==="
python3 "$HERE/l8_summary.py" "$OUT"
