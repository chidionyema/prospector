#!/usr/bin/env bash
# Register this machine as an ephemeral GitHub Actions runner, run exactly one job, exit.
#
# Ephemeral, not long-lived, for one reason: a long-lived runner carries state between jobs, and
# on the Mac that is how a stale node_modules and a half-written .venv survived to poison the next
# run. A container that exits after one job cannot do that. Fly's restart policy brings it back,
# so a fresh runner is waiting within seconds.
set -euo pipefail

: "${GITHUB_REPO:?GITHUB_REPO must be set, e.g. chidionyema/prospector}"
LABELS="${RUNNER_LABELS:-self-hosted,Linux,X64,container,fly}"
NAME="${RUNNER_NAME:-fly-$(hostname)}"

# Two ways in, and the difference matters.
#
# GH_RUNNER_PAT is the durable one: the container mints its own registration token at every boot,
# so a machine that restarts a week from now still registers. It needs administration:write on the
# repository, which is a real credential and a deliberate choice.
#
# RUNNER_TOKEN is the trial one: a registration token minted outside and handed in. It expires an
# hour after it is minted, so a machine using it works now and stops registering later. That is
# enough to prove the image, the toolchains and the job pickup without committing a PAT first.
if [ -n "${GH_RUNNER_PAT:-}" ]; then
  token=$(curl -fsSL -X POST \
    -H "Authorization: Bearer ${GH_RUNNER_PAT}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GITHUB_REPO}/actions/runners/registration-token" \
    | jq -r .token)
elif [ -n "${RUNNER_TOKEN:-}" ]; then
  echo "using a pre-minted RUNNER_TOKEN -- this expires one hour after it was minted"
  token="${RUNNER_TOKEN}"
else
  echo "set GH_RUNNER_PAT (durable) or RUNNER_TOKEN (one hour, for a trial)" >&2
  exit 1
fi

if [ -z "$token" ] || [ "$token" = "null" ]; then
  echo "could not obtain a registration token for ${GITHUB_REPO}" >&2
  exit 1
fi

cd /home/runner

# --ephemeral makes GitHub deregister the runner after one job, so a machine that dies mid-job
# does not leave a phantom 'online' runner that the queue then waits on forever. That phantom is
# exactly what made four Mac runners look busy while nothing ran.
./config.sh \
  --unattended \
  --replace \
  --ephemeral \
  --url "https://github.com/${GITHUB_REPO}" \
  --token "$token" \
  --name "$NAME" \
  --labels "$LABELS" \
  --work /home/runner/_work

cleanup() {
  # Without a PAT there is nothing to mint a removal token with. --ephemeral already makes GitHub
  # drop the runner after one job, so this is belt and braces, not the mechanism.
  [ -z "${GH_RUNNER_PAT:-}" ] && return 0
  echo "deregistering ${NAME}"
  rm_token=$(curl -fsSL -X POST \
    -H "Authorization: Bearer ${GH_RUNNER_PAT}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GITHUB_REPO}/actions/runners/remove-token" | jq -r .token || true)
  [ -n "${rm_token:-}" ] && [ "$rm_token" != "null" ] && ./config.sh remove --token "$rm_token" || true
}
trap cleanup EXIT INT TERM

exec ./run.sh
