#!/usr/bin/env bash
# Register this container as an EPHEMERAL self-hosted runner, run one job, wipe, repeat.
#
# THE LOOP IS IN HERE, NOT IN THE PLATFORM (changed 2026-08-18, and this is the whole point)
#
# It used to run one job and exit, and rely on `[[restart]] policy = "always"` in fly.toml to
# bring the machine back. Measured on 2026-08-18: that restart is a full VM boot. Machine
# 8e4530a7712248 exited cleanly at 20:25:33, logged `reboot: Restarting system` at 20:26:26 and
# came to rest STOPPED at 20:26:27 -- and it stayed stopped. A second machine had already
# stopped at 15:11 the same way. A three-machine fleet was running as one, CI queued for 25
# minutes, and `scripts/ci_capacity.py` said the contract held because it counted registrations
# instead of online runners.
#
# Two separate costs, both removed by looping in here:
#   - ~50 seconds of dead machine between every job, on a fleet whose jobs take 1-2 minutes
#   - flyd sees a process that exits every couple of minutes. That is what a crash loop looks
#     like from outside, and a machine that stops is the platform being reasonable about it.
#
# What the loop must NOT lose is the isolation that made it ephemeral in the first place, so
# each pass takes a FRESH registration token, registers again, and wipes _work before the next
# job. A job still cannot leave anything for the next one, and its runner credentials are still
# single-use. What it no longer does is boot a virtual machine to achieve that.
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
# TWO WAYS TO HOLD A CREDENTIAL, and the second one is why this is not a single :? check.
#
# GITHUB_RUNNER_PAT is a fine-grained PAT with Administration: read+write. It lets the container
# mint a fresh registration token before every job, which is what --ephemeral requires: an
# ephemeral registration is single-use, so the next pass has to register again.
#
# RUNNER_TOKEN is a REGISTRATION token. It expires in an hour, and anything that can already
# administer the repo can mint one, including `gh`. A container holding only this registers ONCE,
# keeps its .credentials, and long-polls with them for the life of the machine.
#
# The second mode exists because GitHub has no API that CREATES a fine-grained PAT - only a
# signed-in human at the web form can. Standing a fleet up for a NEW repository therefore either
# waits for a person, or uses the credential that can be minted without one. It is also the
# SMALLER credential: the container ends up able to be one runner on one repository, and unable
# to add or remove runners at all. What it gives up is the per-job re-registration; the workspace
# wipe at the bottom of the loop, which is what actually stops one job inheriting another, still
# runs on every pass.
if [ -z "${GITHUB_RUNNER_PAT:-}" ] && [ -z "${RUNNER_TOKEN:-}" ]; then
  echo "set GITHUB_RUNNER_PAT (Administration: read+write) or RUNNER_TOKEN (a registration token)" >&2
  exit 1
fi
if [ -n "${GITHUB_RUNNER_PAT:-}" ]; then
  EPHEMERAL=1; EPHEMERAL_ARG="--ephemeral"; RUN_ARG=""
else
  # --once, so run.sh returns after one job and the loop can wipe the workspace. Without it a
  # persistent runner never leaves run.sh and the wipe never happens.
  EPHEMERAL=0; EPHEMERAL_ARG=""; RUN_ARG="--once"
fi

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
  # A token-only runner holds no credential that can ask for a remove-token, and must not try:
  # its registration is meant to outlive this process, not be tidied away after one job.
  [ "$EPHEMERAL" = 1 ] || return 0
  local rm_token
  rm_token="$(api POST remove-token | jq -r .token 2>/dev/null || true)"
  [ -n "$rm_token" ] && [ "$rm_token" != null ] \
    && ./config.sh remove --token "$rm_token" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

while true; do
  REG_REMOVED=0

  if [ "$EPHEMERAL" = 1 ]; then
    echo "[runner] asking ${GITHUB_REPO} for a registration token"
    REG_TOKEN="$(api POST registration-token | jq -r .token)"
    if [ -z "$REG_TOKEN" ] || [ "$REG_TOKEN" = null ]; then
      # A PAT EXPIRES, AND CI GOES DARK QUIETLY. This used to `exit 1`: the container restarted,
      # failed the same call, restarted again, and every job in both repositories queued forever
      # with nothing on any screen saying why. A fine-grained PAT's maximum life is a year and
      # the fleet's is 90 days, so this is a scheduled outage, not a hypothetical.
      #
      # If this runner has registered before, .runner and .credentials are still on disk. Carry
      # on with that registration, non-ephemerally, and say so loudly. The wipe below is what
      # actually isolates one job from the next, and it still runs.
      #
      # HOW FAR THIS GETS YOU, honestly: an --ephemeral registration is single-use, so if this
      # container has already run a job its registration is gone GitHub-side and run.sh will not
      # connect. The container then idles and retries rather than exiting, which is the same
      # outcome as before but visible. A fleet that must survive PAT expiry outright should run
      # the RUNNER_TOKEN mode above, where the registration is not consumed by a job at all.
      if [ -f .runner ]; then
        echo "[runner] WARNING: ${GITHUB_REPO} refused a registration token - the PAT is expired or unscoped." >&2
        echo "[runner] WARNING: running on the EXISTING registration instead. Renew GITHUB_RUNNER_PAT." >&2
        EPHEMERAL=0; EPHEMERAL_ARG=""; RUN_ARG="--once"
        REG_TOKEN=""
      else
        echo "[runner] no registration token and no prior registration - is GITHUB_RUNNER_PAT scoped to Administration: read+write on ${GITHUB_REPO}?" >&2
        exit 1
      fi
    fi
  else
    REG_TOKEN="$RUNNER_TOKEN"
  fi

  # config.sh writes .runner. A token-only runner registers on its first pass and finds that file
  # on every pass after it, so RUNNER_TOKEN - which expired an hour in - is never used twice.
  if [ "$EPHEMERAL" = 1 ] || [ ! -f .runner ]; then
    echo "[runner] registering as ${RUNNER_NAME} with labels ${RUNNER_LABELS}"
    ./config.sh \
      --url "https://github.com/${GITHUB_REPO}" \
      --token "$REG_TOKEN" \
      --name "$RUNNER_NAME" \
      --labels "$RUNNER_LABELS" \
      --runnergroup "$RUNNER_GROUP" \
      --work /home/runner/_work \
      ${EPHEMERAL_ARG} \
      --disableupdate \
      --unattended \
      --replace
  fi

# --disableupdate because the runner's in-place self-update does not survive here. GitHub told
# 2.328.0 to update to 2.336.0 on first contact; the update rewrote bin/ and the relaunch died
# with "/home/runner/actions-runner/bin/Runner.Listener: No such file or directory", exit 127.
# The machine then rebooted, registered the same old version, and was told to update again. Three
# runners drained to one in four minutes that way, with five jobs queued. In an ephemeral
# container the IMAGE is the update mechanism: bump ARG RUNNER_VERSION and redeploy.
#
# run.sh returns when the single job finishes, and the `while` above sends it round again in
# about five seconds. One machine is one concurrent job; `deploy/runners.sh up N` is how N
# changes. `[[restart]] policy = "always"` in fly.toml stays as the backstop for a real crash,
# but in normal operation nothing restarts any more.
#
# Deliberately not `exec`. An --ephemeral runner deregisters itself on a clean finish, but not
# when it dies mid-job, and exec would replace this shell and take the cleanup trap with it.
# Running it as a child keeps the trap, and the remove call is written to tolerate a
# registration that is already gone.
  echo "[runner] waiting for a job"
  # `|| true` because an --ephemeral runner returns non-zero on some job outcomes and `set -e`
  # would end the fleet over one failed build. A failed JOB is CI's business; only a failure to
  # register is this script's business, and that still exits above.
  ./run.sh ${RUN_ARG} || true

  # The isolation the ephemeral design bought, kept without a reboot. A job leaves node_modules,
  # a .venv, dotnet obj/ and a half-written store/ behind, and "green on runner 2, red on runner
  # 4" was a real symptom of inheriting them.
  echo "[runner] wiping the workspace"
  rm -rf /home/runner/_work/* /home/runner/_work/.[!.]* 2>/dev/null || true

  cleanup
done
