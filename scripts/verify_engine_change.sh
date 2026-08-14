#!/usr/bin/env bash
#
# THE ENGINE IS THE CROWN JEWEL. This is the proof that a change to it is safe to commit.
#
# WHY THIS EXISTS
# ---------------
# On 2026-08-13, commit 9089ebc raised `generation.candidates_per_signal` from 5 to 50 in
# config.yaml. Nothing ran. `.yaml` is not in scripts/popdd_verify.py's SOURCE_EXTS, so
# `lanes_for()` classified the change as covered-by-nothing and the POPDD gate let it through
# with no proof at all — the one file that steers the live daemon was the one file no lane
# guarded.
#
# The result, measured from store/scheduler/alerts.jsonl on 2026-08-14:
#   11:23-15:57Z  critical  barren_streak x18  "produced nothing for 21 ticks in a row"
#   20:48:25Z     critical  tick_error         "tick_hard_deadline: exceeded 10800s during
#                                               generation (batch=15); force-exited"
# Generation was not returning empty — it was never returning. Every tick was killed at the
# 3h deadline mid-generation, so 21 consecutive ticks vetted nothing and stocked nothing.
# The founder discovered it by asking. That is the failure this script exists to prevent.
#
# WHAT IT PROVES, AND WHAT IT CANNOT
# ----------------------------------
# It proves the daemon can LOAD and can COMPLETE a guarded tick with the staged config, and
# that the generation budget is within the declared ratio. It does NOT prove yield: no gate
# can, because yield needs paid live retrieval. Say that out loud rather than implying a
# green run means the engine is producing — that conflation is how a broken engine reads as
# healthy.
#
# USAGE
#   ./scripts/verify_engine_change.sh            # run every check, non-zero on any failure
#   ./scripts/verify_engine_change.sh --no-tick  # skip check 3 (CI: no .env, no spend ledger)
# Run by the POPDD gate's `engine` lane (scripts/popdd_verify.py) on any staged change to
# config.yaml or prospector/scheduler/**, and by ci.yml's `engine` job as the backstop for
# when the local hook is not installed — which, on 2026-08-14, it was not: the main
# checkout had no .git/hooks/pre-commit at all, so every commit made from it, including
# 9089ebc, ran with the gate absent rather than merely blind.
#
# --no-tick exists because check 3 needs a real .env and the spend ledger, neither of which a
# CI runner has. What CI keeps is checks 1, 2 and 4 — enough to catch an unloadable daemon and
# an out-of-budget k, which is the class that took the engine down. The skip is PRINTED, never
# silent: a check that quietly stops running is worse than one that was never written.

set -uo pipefail

RUN_TICK=1
for arg in "$@"; do
  case "$arg" in
    --no-tick) RUN_TICK=0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.." || exit 2
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
fail=0

step() { printf '\n── %s\n' "$1"; }
verdict() {
  if [ "$1" -eq 0 ]; then printf '   PASS  %s\n' "$2"; else printf '   FAIL  %s\n' "$2"; fail=1; fi
}

# 1. The daemon must be able to load its own module. A syntax or import error here is total
#    downtime: launchd restarts the scheduler, the import raises, and the engine is simply gone.
step "1/4  daemon module imports"
out="$("$PY" -c 'import prospector.scheduler.run_scheduled as m; print(m.__file__)' 2>&1)"
verdict $? "import prospector.scheduler.run_scheduled${out:+ ($(printf '%s' "$out" | tail -1))}"

# 2. Lint the engine paths. Cheap, and it runs before the slow checks so a typo comes back fast.
step "2/4  ruff on the engine"
"$PY" -m ruff check --output-format concise prospector/scheduler prospector/config.py >/tmp/eng_ruff.txt 2>&1
verdict $? "ruff clean ($(wc -l </tmp/eng_ruff.txt | tr -d ' ') finding(s))"
[ -s /tmp/eng_ruff.txt ] && head -5 /tmp/eng_ruff.txt

# 3. A guarded tick must COMPLETE with this config. --dry-run evaluates the guards and the
#    generation plan without generating, so this is safe to run against production state and
#    costs no provider budget. It is the check that would have caught a config the daemon
#    cannot even plan with.
step "3/4  dry-run tick completes"
if [ "$RUN_TICK" -eq 1 ]; then
  timeout 180 "$PY" -m prospector.scheduler.run_scheduled --once --dry-run --config config.yaml \
    >/tmp/eng_tick.txt 2>&1
  rc=$?
  verdict $rc "guarded tick exits 0 (timeout 180s)"
  tail -2 /tmp/eng_tick.txt
else
  echo "   SKIP  --no-tick: this runner has no .env and no spend ledger, so the tick would"
  echo "         fail on its environment rather than on the change. NOT PROVEN HERE."
fi

# 4. THE GENERATION TIME BUDGET — a projection over the values the daemon actually reads.
#    The old check here compared generation.candidates_per_signal to schedule.batch_size.
#    That ratio was built on an INERT value: the daemon always passes an explicit
#    k=batch_size (run_scheduled.py `_default_generate`), so candidates_per_signal never
#    reaches the daemon path — the 2026-08-13 5->50 change this script exists because of
#    did nothing THROUGH that setting (the damage came via batch-shaped generation cost),
#    and the ratio would have blocked batch_size=50 (3.33 > 3) on grounds that measured
#    nothing. Replaced 2026-08-14 with a wall-clock projection using the runtime's own
#    wave-planning formula; constants and provenance are documented in the script.
step "4/4  generation time budget (scripts/gen_budget_guard.py)"
"$PY" scripts/gen_budget_guard.py --config config.yaml
verdict $? "projected generation time fits schedule.gen_budget_frac x tick deadline"

printf '\n'
if [ "$fail" -eq 0 ] && [ "$RUN_TICK" -eq 0 ]; then
  echo "ENGINE VERIFY: PASS (--no-tick) — the daemon loads and the budget ratio holds."
  echo "NOT proven here: that a tick completes, or yield. Run without --no-tick on a machine"
  echo "that has .env to prove the first."
elif [ "$fail" -eq 0 ]; then
  echo "NOT proven here: yield. Only a live paid tick can show the engine is producing."
else
  echo "ENGINE VERIFY: FAIL — do not commit. The live daemon runs this code."
fi
exit "$fail"
