#!/usr/bin/env bash
# Register this container as an EPHEMERAL self-hosted runner, run exactly one job, exit.
#
# WHY EPHEMERAL
#
# A long-lived runner accumulates: a job leaves its node_modules, its .venv, its dotnet
# obj/ and its half-written store/ behind, and the next job on that runner inherits all of
# it. On the Macs that is exactly what happened - `_work/prospector/prospector` is a
# permanent directory, and "green on runner 2, red on runner 4" was a real symptom. A
# container that exits after one job cannot carry state into the next one.
#
# The cost of that is a fresh checkout and a fresh toolchain download per job. actions/cache
# absorbs most of it: the caches live in GitHub's cache service, not on the runner.
#
# WHY A REGISTRATION TOKEN AND NOT A STORED RUNNER CONFIG
#
# Runner registrations are per-runner and single-use. Baking one into the image would mean
# every machine tries to be the same runner, and the second one to start deregisters the
# first. So each start asks GitHub for a fresh registration token (they last an hour, which
# is why they cannot be baked in either) and configures itself with a name derived from the
# machine it is on.

set -euo pipefail

: "${GITHUB_REPO:?set GITHUB_REPO=owner/repo}"
: "${GITHUB_RUNNER_PAT:?set GITHUB_RUNNER_PAT - a PAT with Administration: read+write on the repo}"

# The name has to be unique across the fleet and stable across restarts of the SAME machine,
# so a crashed runner reclaims its own registration instead of leaving a dead one behind.
# FLY_MACHINE_ID is set by Fly; the fallback keeps this working under plain docker and on any
# other platform, which is the whole point of the adapter contract.
RUNNER_NAME="${RUNNER_NAME:-runner-${FLY_MACHINE_ID:-$(hostname)}}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,Linux,X64,container}"
RUNNER_GROUP="${RUNNER_GROUP:-Default}"

cd /home/runner/actions-runner

api() {
  curl -fsSL -X "$1" \
    -H "Authorization: Bearer ${GITHUB_RUNNER_PAT}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${GITHUB_REPO}/actions/runners/$2"
}

# Deregister on the way out, whatever the reason. Without this, every restart leaves an
# "offline" runner in the repo's runner list, and after a week the list is unreadable and
# GitHub starts refusing new registrations against the per-repo limit.
REG_REMOVED=0
cleanup() {
  [ "$REG_REMOVED" = 1 ] && return 0
  REG_REMOVED=1
  local rm_token
  rm_token="$(api POST remove-token | jq -r .token 2>/dev/null || true)"
  [ -n "$rm_token" ] && [ "$rm_token" != null ] \
    && ./config.sh remove --token "$rm_token" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "[runner] asking ${GITHUB_REPO} for a registration token"
REG_TOKEN="$(api POST registration-token | jq -r .token)"
[ -n "$REG_TOKEN" ] && [ "$REG_TOKEN" != null ] || {
  echo "[runner] no registration token - is GITHUB_RUNNER_PAT scoped to Administration: read+write on ${GITHUB_REPO}?" >&2
  exit 1
}

echo "[runner] registering as ${RUNNER_NAME} with labels ${RUNNER_LABELS}"
./config.sh \
  --url "https://github.com/${GITHUB_REPO}" \
  --token "$REG_TOKEN" \
  --name "$RUNNER_NAME" \
  --labels "$RUNNER_LABELS" \
  --runnergroup "$RUNNER_GROUP" \
  --work /home/runner/_work \
  --ephemeral \
  --unattended \
  --replace

# run.sh returns when the single job finishes. The platform restarts the container, which
# comes back here and registers again. That loop IS the fleet: N machines means N concurrent
# jobs, and `deploy/runners.sh up N` is how N changes.
#
# Deliberately not `exec`. An --ephemeral runner deregisters itself on a clean finish, but not
# when it dies mid-job, and exec would replace this shell and take the cleanup trap with it.
# Running it as a child keeps the trap, and the remove call is written to tolerate a
# registration that is already gone.
echo "[runner] waiting for a job"
./run.sh
