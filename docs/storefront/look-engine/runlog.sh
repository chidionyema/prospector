#!/bin/bash
# @ledger writes | ./runlog.sh <cmd...> | Runs one tool and records the whole of its output to logs/, with the exit code.
#
# The log is the artifact. A tool whose output was read once in a terminal and summarised in
# prose is a tool with no receipt: on 2026-08-20 a gate run was piped through `tail -6`, which
# ate the verdict line and reported tail's exit status instead of the gate's, so the run had to
# be repeated. This captures stdout and stderr together, unpiped, and records the real exit
# status before anything can mask it.
set -uo pipefail
mkdir -p logs
# Name the log after the SCRIPT, never after the interpreter. `${1}` is `node` for four of
# these tools, so taking $1 wrote every one of them to logs/node.log and each run silently
# overwrote the last — three tools, one log, no error. Scan the arguments for the thing that
# is actually being run, and if none of them looks like a script, say so loudly rather than
# invent a name.
name=""
for a in "$@"; do case "$a" in *.mjs|*.sh|*.py) name="$(basename "$a")"; name="${name%.*}";; esac; done
if [ -z "$name" ]; then
  echo "runlog: no script argument in: $*" >&2
  echo "runlog: pass the script itself, e.g. ./runlog.sh node verify.mjs" >&2
  exit 2
fi
log="logs/${name}.log"
start_epoch=$(date +%s)
{
  echo "\$ $*"
  echo "started  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "node     $(node -v 2>/dev/null || echo 'n/a')"
  echo "---"
} > "$log"
"$@" >> "$log" 2>&1
code=$?
{
  echo "---"
  echo "exit     $code"
  echo "duration $(( $(date +%s) - start_epoch ))s"
} >> "$log"
echo "$log  exit=$code"
exit $code
