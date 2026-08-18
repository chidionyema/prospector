#!/usr/bin/env bash
# Size, inspect and tear down the CI runner fleet. One command, any platform.
#
#   deploy/runners.sh up 4          # build, push, and run four runners
#   deploy/runners.sh status        # what GitHub thinks it has, and what the platform is running
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

cmd_up() {
  local n="${1:?usage: runners.sh up <count>}"
  command -v fly >/dev/null || { echo "fly CLI not installed" >&2; exit 1; }

  grep -q '^GITHUB_RUNNER_PAT=' "$ENV_FILE" || {
    cat >&2 <<'MSG'
No GITHUB_RUNNER_PAT in the env file.

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
  grep -E '^(GITHUB_RUNNER_PAT|RUNNER_LABELS)=' "$ENV_FILE" > "$REPO_ROOT/.runner.env"
  chmod 600 "$REPO_ROOT/.runner.env"
  fly secrets import -a "$APP" --stage < "$REPO_ROOT/.runner.env"
  rm -f "$REPO_ROOT/.runner.env"

  say "building and deploying the runner image"
  fly deploy "$REPO_ROOT" --config "$HERE/runner/fly.toml" -a "$APP" \
    --dockerfile "$HERE/runner/Dockerfile" --strategy immediate --yes

  say "scaling to $n"
  fly scale count "$n" -a "$APP" -r "$REGION" --yes
  echo "  runners will appear at https://github.com/$GH_REPO/settings/actions/runners"
  echo "  they carry the label 'self-hosted', which is what vars.CI_RUNS_ON asks for, so they"
  echo "  start taking jobs immediately alongside the Macs. Nothing in .github/ changes."
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
  up)         shift; cmd_up "$@" ;;
  down)       cmd_down ;;
  status)     cmd_status ;;
  laptop-off) cmd_laptop_off ;;
  laptop-on)  cmd_laptop_on ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
