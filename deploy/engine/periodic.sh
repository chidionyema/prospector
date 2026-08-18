#!/usr/bin/env bash
# Run a command on a fixed interval, forever. This is launchd's `StartInterval` and
# nothing more.
#
# Why a script instead of cron: cron in a container needs its own daemon, its own log
# plumbing and its own copy of the environment, and it fails silently when any of the
# three is wrong. supervisord already supervises, already captures stdout, and already
# passes the environment. A `sleep` loop under it is the whole feature.
#
# Two deliberate choices:
#   * The command runs FIRST, then sleeps. launchd's RunAtLoad=1 does the same, and a
#     watchdog that waits 15 minutes before its first look is useless on a cold start.
#   * A non-zero exit is logged and the loop continues. These are repair jobs; one
#     failed pass must not stop every later pass. supervisord would restart the loop
#     anyway, so exiting would only lose the interval.
set -uo pipefail

INTERVAL_S="${1:?usage: periodic.sh <interval_seconds> <command...>}"
shift

while true; do
    "$@"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "[periodic] $* exited $rc; next attempt in ${INTERVAL_S}s" >&2
    fi
    sleep "$INTERVAL_S"
done
