#!/usr/bin/env bash
# Stop the test stack started by run_test_stack.sh.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/.test-stack"

for name in web api stripe; do
  pidf="$RUN_DIR/$name.pid"
  if [ -f "$pidf" ]; then
    pid="$(cat "$pidf")"
    kill "$pid" 2>/dev/null && echo "stopped $name (pid $pid)" || echo "$name (pid $pid) not running"
    rm -f "$pidf"
  fi
done
# belt-and-braces: free the ports
lsof -ti tcp:3000 tcp:5291 2>/dev/null | xargs -r kill 2>/dev/null || true
echo "done."
