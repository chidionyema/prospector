#!/usr/bin/env bash
# Size, inspect and tear down the CI runner fleet. One command, any platform.
#
#   deploy/runners.sh up 4          # build, push, and run four runners
#   deploy/runners.sh status        # what GitHub thinks it has, and what the platform is running
#   deploy/runners.sh autoscale     # start/stop machines to match the queue depth
#   deploy/runners.sh heal          # start any machine whose runner still holds a job
#   deploy/runners.sh down          # stop them all; the repo falls back to whatever is left
#   deploy/runners.sh laptop-off    # unload the four Mac runners, after Fly's have taken jobs
#
# WHY A SEPARATE SCRIPT FROM cutover.sh
#
# The engine cutover has a single-writer rule: two engines running at once fork the spend
# ledger. Runners are the opposite - they are stateless and interchangeable, and running the
# Fly fleet and the Mac fleet at the same time is not a hazard, it is the migration plan. The
# two therefore cannot share a script, because cutover.sh's whole shape is "stop the source
# before starting the target" and that would be exactly the wrong thing to do here.
#
# PLATFORM
#
# TARGET names an adapter in deploy/targets/. Fly is the default; the day we leave, this
# script is unchanged and `--target sshdocker` is the whole difference.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
TARGET="${PROSPECTOR_RUNNER_TARGET:-fly}"
APP="${PROSPECTOR_RUNNER_APP:-prospector-ci}"
REGION="${PROSPECTOR_FLY_REGION:-lhr}"
GH_REPO="${GITHUB_REPO:-chidionyema/prospector}"

_default_env() {
  [ -f "$REPO_ROOT/.env" ] && { echo "$REPO_ROOT/.env"; return; }
  local common main
  common="$(cd "$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null || echo .)" && pwd -P)"
  main="$(dirname "$common")"
  [ -f "$main/.env" ] && { echo "$main/.env"; return; }
  echo "$REPO_ROOT/.env"
}
ENV_FILE="${PROSPECTOR_ENV_FILE:-$(_default_env)}"

say() { printf '\n\033[1m[%s] %s\033[0m\n' "$(date +%H:%M:%S)" "$*"; }

cmd_set_pat() {
  # Store the runner credential once, safely, and prove it works before storing it.
  #
  # GitHub has no API that CREATES a personal access token, so this verb cannot mint one - only
  # a signed-in human at the web form can. What it removes is every other step: the token never
  # appears in a shell history, a chat log, or a file mode other than 600, and a token that
  # cannot actually register a runner is refused here rather than at the first CI job.
  #
  # Reads the token from stdin, never from an argument: an argument lands in `ps` output and in
  # the shell's history file.
  local token
  if [ -t 0 ]; then
    cat >&2 <<MSG
Paste the token on stdin, so it never reaches your shell history:

  pbpaste | deploy/runners.sh set-pat

Mint it first, at:
  https://github.com/settings/personal-access-tokens/new
  Repository access : Only select repositories -> prospector
  Permissions       : Repository -> Administration -> Read and write
  Expiration        : 90 days
MSG
    exit 2
  fi
  # `|| true`, because `read` returns non-zero at end of file when the last line carries no
  # newline - which is exactly what `printf '%s' "$tok" | ...` produces. Under `set -e` that
  # killed the script before it printed anything: exit 1, no message, no stored token.
  IFS= read -r token || true
  token="$(printf '%s' "$token" | tr -d '[:space:]')"
  [ -n "$token" ] || { echo "nothing on stdin" >&2; exit 2; }

  say "checking the token can register a runner on $GH_REPO, and nothing more"
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
    -H "Authorization: Bearer $token" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$GH_REPO/actions/runners/registration-token")"
  if [ "$code" != "201" ]; then
    echo "  REFUSED: the token could not mint a registration token (HTTP $code)." >&2
    echo "  It needs Repository -> Administration -> Read and write on $GH_REPO." >&2
    exit 1
  fi
  echo "  ok: HTTP 201, the token can add and remove runners on $GH_REPO"

  # Written to the env file the whole estate already treats as the source of truth, so it is
  # carried into the encrypted offsite backup with everything else and needs no second store.
  local tmp
  tmp="$(mktemp)"
  chmod 600 "$tmp"
  grep -v '^GITHUB_RUNNER_PAT=' "$ENV_FILE" > "$tmp" 2>/dev/null || true
  printf 'GITHUB_RUNNER_PAT=%s\n' "$token" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  say "stored in $ENV_FILE (mode 600)"
  echo "  read it back any time with:  grep '^GITHUB_RUNNER_PAT=' $ENV_FILE"
  echo "  then bring the fleet up:     deploy/runners.sh up 4"
}

cmd_up() {
  local n="${1:?usage: runners.sh up <count>}"
  command -v fly >/dev/null || { echo "fly CLI not installed" >&2; exit 1; }

  # NO PAT, NO PERSON. GitHub has no API that creates a fine-grained PAT, so standing a fleet
  # up for a NEW repository used to stop here and wait for someone to visit a web form. A
  # REGISTRATION token needs no form: anything that can already administer the repo can mint
  # one, including the `gh` CLI. It expires in an hour, which is enough - entrypoint.sh keeps
  # the .credentials that first registration writes and never needs the token again.
  #
  # This is the SMALLER credential, not a shortcut around the PAT: the container ends up able
  # to be one runner on one repository, and unable to add or remove runners at all. What it
  # gives up is per-job re-registration, so the runner is not --ephemeral; the workspace wipe
  # between jobs, which is what stops one job inheriting another, still runs.
  local reg_token=""
  if ! grep -q '^GITHUB_RUNNER_PAT=' "$ENV_FILE" && command -v gh >/dev/null; then
    reg_token="$(gh api -X POST "repos/$GH_REPO/actions/runners/registration-token" \
                   --jq .token 2>/dev/null || true)"
    [ -n "$reg_token" ] && say "no PAT on file - registering $APP with a one-hour registration token"
  fi

  [ -n "$reg_token" ] || grep -q '^GITHUB_RUNNER_PAT=' "$ENV_FILE" || {
    cat >&2 <<'MSG'
No GITHUB_RUNNER_PAT in the env file, and `gh` could not mint a registration token either.

A runner registers itself, and registration tokens last an hour, so they cannot be baked into
an image. The container needs a credential that can mint them. Create a FINE-GRAINED personal
access token, not a classic one:

  https://github.com/settings/personal-access-tokens/new
  Repository access : Only select repositories -> prospector
  Permissions       : Repository -> Administration -> Read and write
  Expiration        : 90 days

That single permission can add and remove runners on this one repository. It cannot read code,
push, or touch any other repo. Then:

  echo "GITHUB_RUNNER_PAT=github_pat_..." >> .env
MSG
    exit 1
  }

  say "provisioning $APP on $TARGET"
  fly apps list 2>/dev/null | awk '{print $1}' | grep -qx "$APP" \
    || fly apps create "$APP" --org personal

  say "pushing the runner credential"
  # Only the two keys the runner needs. A CI runner must never hold the money keys: it runs
  # code from every pull request, including one an outsider opened.
  : > "$REPO_ROOT/.runner.env"
  chmod 600 "$REPO_ROOT/.runner.env"
  if [ -n "$reg_token" ]; then
    # Written to a 600 file and piped straight into fly, so the value is never an argument and
    # never reaches a terminal. GITHUB_REPO rides along because a token-only runner has no way
    # to ask which repository it belongs to.
    printf 'RUNNER_TOKEN=%s\nGITHUB_REPO=%s\n' "$reg_token" "$GH_REPO" >> "$REPO_ROOT/.runner.env"
    grep -E '^RUNNER_LABELS=' "$ENV_FILE" >> "$REPO_ROOT/.runner.env" || true
  else
    grep -E '^(GITHUB_RUNNER_PAT|RUNNER_LABELS)=' "$ENV_FILE" >> "$REPO_ROOT/.runner.env"
  fi
  fly secrets import -a "$APP" --stage < "$REPO_ROOT/.runner.env"
  rm -f "$REPO_ROOT/.runner.env"

  say "building and deploying the runner image"
  # One image, one config per fleet. A second repository needs a different GITHUB_REPO in
  # [env], and that is the only difference, so it gets its own file rather than a flag.
  local cfg="$HERE/runner/fly.$APP.toml"
  [ -f "$cfg" ] || cfg="$HERE/runner/fly.toml"
  fly deploy "$REPO_ROOT" --config "$cfg" -a "$APP" \
    --dockerfile "$HERE/runner/Dockerfile" --strategy immediate --yes

  say "scaling to $n"
  fly scale count "$n" -a "$APP" -r "$REGION" --yes
  # `fly scale count` leaves the machines it keeps in whatever state they were in, and a machine
  # that has just been created by `fly deploy` can be stopped. A stopped runner is invisible in
  # every screen that counts runners, so the fleet reads as "1 machine" and takes no jobs.
  # Measured 2026-08-19 standing hermes-ci up: scale reported success, GitHub showed 0 runners.
  fly machine list -a "$APP" --json 2>/dev/null \
    | jq -r '.[] | select(.state != "started") | .id' \
    | while read -r mid; do
        [ -n "$mid" ] && { say "starting stopped machine $mid"; fly machine start "$mid" -a "$APP" >/dev/null; }
      done
  echo "  runners will appear at https://github.com/$GH_REPO/settings/actions/runners"
  echo "  they carry the label 'self-hosted', which is what vars.CI_RUNS_ON asks for, so they"
  echo "  start taking jobs immediately alongside the Macs. Nothing in .github/ changes."
}

cmd_heal() {
  # START ANY MACHINE WHOSE RUNNER GITHUB STILL BELIEVES IS RUNNING A JOB.
  #
  # THE FAILURE THIS REPAIRS. A GitHub runner registration outlives the machine it runs on.
  # Stop the machine and GitHub keeps the runner on its books with the last state it saw --
  # `status: offline, busy: true`. GitHub does not reassign that job. It holds it against a
  # runner that is gone, waits out the timeout, and marks it failed WITH NO LOG, because no
  # runner ever wrote one. Measured 2026-08-19: 7 of 9 registrations offline and busy, 17 runs
  # queued, and the founder watching jobs die with no output while nothing had been pushed.
  #
  # The runner is NOT --ephemeral here (see cmd_up: a registration token buys a smaller
  # credential than a PAT and costs per-job re-registration), so nothing deregisters it on the
  # way down. That is the whole gap.
  #
  # WHY START AND NOT DELETE. `DELETE /actions/runners/<id>` refuses a busy runner outright:
  #   "Runner runner-<id> is currently running a job and cannot be deleted." (HTTP 422)
  # Proven 2026-08-19 against runner 772. Starting its machine instead brought the runner back
  # online and its job ran. Starting RECOVERS the job; deleting could not even be attempted.
  #
  # This is a reconciler and it is safe to run at any time. It reads live state on both sides
  # and starts machines that are already paid for. If either side cannot be read it does
  # nothing, because acting on half a picture is how the gap opened.
  command -v fly >/dev/null || { echo "fly CLI not installed" >&2; exit 1; }

  local busy machines healed=0
  busy="$(gh api "repos/$GH_REPO/actions/runners" \
            --jq '.runners[] | select(.busy) | .name' 2>/dev/null || true)"
  if [ -z "$busy" ]; then
    echo "  no busy runners on GitHub; nothing to heal"
    return 0
  fi
  machines="$(fly machines list -a "$APP" --json 2>/dev/null || echo '[]')"
  if [ "$machines" = "[]" ]; then
    echo "  could not read the machine list; not healing on half a picture"
    return 0
  fi

  local id
  for name in $busy; do
    # The entrypoint names itself `runner-<machine id>`; that is the only join between the
    # two lists. A registration with any other shape is a Mac runner and not ours to start.
    case "$name" in runner-*) id="${name#runner-}" ;; *) continue ;; esac
    printf '%s' "$machines" | jq -e --arg i "$id" \
      '[.[] | select(.id == $i and .state == "started")] | length > 0' >/dev/null 2>&1 && continue
    printf '%s' "$machines" | jq -e --arg i "$id" '[.[] | select(.id == $i)] | length > 0' \
      >/dev/null 2>&1 || continue
    if fly machine start "$id" -a "$APP" >/dev/null 2>&1; then
      echo "  healed $id (its runner was busy while the machine was stopped)"
      healed=$(( healed + 1 ))
    else
      echo "  could not start $id, whose runner is busy"
    fi
  done
  [ "$healed" -eq 0 ] && echo "  every busy runner has a started machine"
  return 0
}

cmd_autoscale() {
  # Match the number of STARTED machines to the number of queued runs, inside the bounds
  # declared in ops/config/ci_capacity.yaml. Start/stop, never create/destroy: a stopped Fly
  # machine bills no CPU and no RAM, and starting one takes seconds because the image is
  # already on the host.
  #
  # SAFETY: a machine is only stopped when GitHub says its runner is NOT busy. The runners are
  # --ephemeral, so a machine between jobs is idle and safe; one mid-job is never touched.
  # If GitHub cannot be reached the verb scales UP only, because the failure mode of scaling
  # down on bad data is killing a build.
  command -v fly >/dev/null || { echo "fly CLI not installed" >&2; exit 1; }

  # Reconcile before sizing. A machine stopped while its runner holds a job is a job that will
  # die with no log, and it is also capacity the queue reading below cannot see -- the run is
  # not `queued`, it is assigned to a runner that is gone. Healing first means the scaler never
  # sizes the pool against a queue that is short by however many jobs are stranded.
  cmd_heal

  local min max
  min="$(_cfg_num autoscale_min 1)"
  max="$(_cfg_num autoscale_max 3)"

  local queued=""
  queued="$(gh api "repos/$GH_REPO/actions/runs?status=queued&per_page=100" \
              --jq '.workflow_runs | length' 2>/dev/null || true)"

  local machines busy_names
  machines="$(fly machines list -a "$APP" --json 2>/dev/null || echo '[]')"
  busy_names="$(gh api "repos/$GH_REPO/actions/runners" \
                  --jq '.runners[] | select(.busy) | .name' 2>/dev/null || true)"

  local started stopped
  started="$(printf '%s' "$machines" | jq -r '[.[] | select(.state=="started")] | .[].id')"
  stopped="$(printf '%s' "$machines" | jq -r '[.[] | select(.state!="started")] | .[].id')"

  local n_started
  n_started="$(printf '%s\n' "$started" | grep -c . || true)"

  local want
  if [ -z "$queued" ]; then
    # No reading from GitHub. Hold at least `min` and never scale down on a guess.
    want="$min"
    [ "$n_started" -gt "$want" ] && want="$n_started"
    echo "  could not read the queue; holding at $want (scale-down needs real data)"
  else
    want="$queued"
    [ "$want" -lt "$min" ] && want="$min"
    [ "$want" -gt "$max" ] && want="$max"
  fi

  say "queue=${queued:-unknown} started=$n_started want=$want (min=$min max=$max)"

  if [ "$want" -gt "$n_started" ]; then
    local need=$(( want - n_started ))
    for id in $stopped; do
      [ "$need" -gt 0 ] || break
      fly machine start "$id" -a "$APP" >/dev/null 2>&1 \
        && { echo "  started $id"; need=$(( need - 1 )); } \
        || echo "  could not start $id"
    done
    [ "$need" -gt 0 ] && echo "  wanted $need more machine(s) than the pool holds; raise the" \
                              "pool with: deploy/runners.sh up $max"
  elif [ "$want" -lt "$n_started" ] && [ -n "$queued" ]; then
    local excess=$(( n_started - want ))
    for id in $started; do
      [ "$excess" -gt 0 ] || break
      # `runner-<machine id>` is how the entrypoint names itself, which is the only thing that
      # makes the two lists comparable.
      printf '%s\n' "$busy_names" | grep -qx "runner-$id" && continue
      fly machine stop "$id" -a "$APP" >/dev/null 2>&1 \
        && { echo "  stopped $id (idle)"; excess=$(( excess - 1 )); } \
        || echo "  could not stop $id"
    done
  else
    echo "  nothing to do"
  fi
}

_cfg_num() {
  # One key out of ops/config/ci_capacity.yaml without adding a YAML dependency to a shell
  # script. The keys are plain `name: number` at the top level of the autoscale block.
  local key="$1" fallback="$2" val
  val="$(awk -v k="$key" '$1 == k":" {print $2; exit}' "$REPO_ROOT/ops/config/ci_capacity.yaml" 2>/dev/null)"
  case "$val" in
    ''|*[!0-9]*) echo "$fallback" ;;
    *) echo "$val" ;;
  esac
}

cmd_status() {
  say "GitHub's view"
  gh api "repos/$GH_REPO/actions/runners" \
    --jq '.runners[] | "  \(.name)\t\(.status)\t\(if .busy then "BUSY" else "idle" end)\t\(.os)\t\([.labels[].name]|join(","))"' \
    2>/dev/null || echo "  (gh not authenticated)"
  say "the platform's view ($TARGET:$APP)"
  fly machines list -a "$APP" 2>/dev/null | sed 's/^/  /' || echo "  app not created yet"
  say "the laptop's view"
  launchctl list 2>/dev/null | awk '$3 ~ /^actions\.runner\./ {print "  " $3 "\tpid " $1}' \
    || echo "  none"
}

cmd_down() {
  say "scaling $APP to zero"
  fly scale count 0 -a "$APP" --yes
  echo "  the machines deregister themselves on the way out; check with: runners.sh status"
}

cmd_laptop_off() {
  # Deliberately a separate verb, and deliberately last. Run it only once `status` shows the
  # container runners taking jobs. Turning the Macs off before that leaves the repo with no
  # runners at all, and `runs-on: self-hosted` does not fall back to GitHub-hosted - the jobs
  # simply queue forever with no error.
  local live
  live="$(gh api "repos/$GH_REPO/actions/runners" \
          --jq '[.runners[] | select(.os != "macOS" and .status == "online")] | length' 2>/dev/null || echo 0)"
  [ "${live:-0}" -ge 1 ] || {
    echo "refusing: no non-macOS runner is online, so this would leave the repo with none" >&2
    echo "  run: deploy/runners.sh up 4   and wait for status to show them online" >&2
    exit 1
  }
  say "$live container runner(s) online; unloading the Mac runners"
  for l in $(launchctl list 2>/dev/null | awk '$3 ~ /^actions\.runner\./ {print $3}'); do
    launchctl bootout "gui/$(id -u)/$l" 2>/dev/null && echo "  stopped $l" || echo "  could not stop $l"
  done
  echo "  the runner installs under ~/actions-runner* are left on disk, untouched."
  echo "  they are the rollback: deploy/runners.sh laptop-on"
}

cmd_laptop_on() {
  say "reloading the Mac runners"
  for f in "$HOME"/Library/LaunchAgents/actions.runner.*.plist; do
    [ -e "$f" ] || continue
    launchctl bootstrap "gui/$(id -u)" "$f" 2>/dev/null && echo "  started $(basename "$f")" \
      || echo "  already running: $(basename "$f")"
  done
}

case "${1:-}" in
  set-pat) shift; cmd_set_pat "$@" ;;
  up)         shift; cmd_up "$@" ;;
  down)       cmd_down ;;
  status)     cmd_status ;;
  autoscale)  cmd_autoscale ;;
  heal)       cmd_heal ;;
  laptop-off) cmd_laptop_off ;;
  laptop-on)  cmd_laptop_on ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
