#!/bin/bash
# The first thing every session is told, measured instead of remembered.
#
# `~/.claude/scripts/memory-loop.py` runs a project's `.state-probe` at SessionStart and injects
# the output ABOVE the narrative checkpoint, labelled VERIFIED LIVE STATE. This is the script
# behind that pointer.
#
# It exists because of a measured failure on 2026-08-19. The CLAUDE.md the harness injects comes
# from the checkout a session was started in, and both developer checkouts were 59 commits behind
# main, still describing a local production engine. Production had been on Fly since 2026-08-18.
# An agent read the file, graded this Mac's launchd jobs as the production process table, and
# reported an outage while the engine was ruling verdicts in lhr. Stale instructions are
# indistinguishable from correct ones from the inside, so the fix cannot be a better paragraph.
# Anthropic's own guidance says the same: facts that change over time belong in a SessionStart
# hook, not in CLAUDE.md.
#
#   ops/state_probe.sh              print the state
#   ops/state_probe.sh --install    copy this script to ~/.claude/state-probe/prospector.sh and
#                                   point every prospector session at it
#
# The installed copy is what actually runs, so it can drift from this one. It cannot drift
# silently: scripts/process_audit.py compares the two and grades a mismatch BAD.
#
# Rules for anything added below. No network calls — this runs before every session. Absolute
# paths only — memory-loop runs it with cwd=$HOME. Read-only, always exit 0: a probe must never
# be the reason a session fails to start.

set -u

INSTALL_DIR="$HOME/.claude/state-probe"
INSTALL_PATH="$INSTALL_DIR/prospector.sh"

install_probe() {
  mkdir -p "$INSTALL_DIR"
  cp "$0" "$INSTALL_PATH"
  chmod +x "$INSTALL_PATH"
  echo "installed $INSTALL_PATH"
  local n=0
  # Every session started in a prospector checkout or one of its worktrees gets the same brief.
  # The tmp scratchpad slugs are skipped: they are throwaway cwds, not places work is done.
  while IFS= read -r dir; do
    case "$dir" in *-private-*) continue ;; esac
    printf 'bash "$HOME/.claude/state-probe/prospector.sh"\n' > "$dir/.state-probe"
    n=$((n + 1))
  done < <(find "$HOME/.claude/projects" -maxdepth 1 -type d \
             \( -name '*code-prospector' -o -name '*code-wt-*' \) 2>/dev/null)
  echo "pointed $n project directories at it"
}

if [ "${1:-}" = "--install" ]; then
  install_probe
  exit 0
fi

echo "PRODUCTION IS FLY. This Mac is development and estate support, not production."
echo "  engine    prospector-engine (lhr, 1 machine). supervisord runs seven programs: scheduler,"
echo "            consumer, watchdog, backup, offsite-backup, restore-drill, ops-console (port 8611)."
echo "  shop      prospector-store-api = api.mumchimp.com, prospector-store-web = mumchimp.com"
echo "  grounding prospector-searxng, private 6PN, no public IP"
echo "  The live process table is a command, never this text:"
echo "      fly ssh console -a prospector-engine -C \"supervisorctl status\""
echo "  This Mac's com.prospector.* launchd jobs are pre-2026-08-18 leftovers. Do not read them as"
echo "  production and do not restart them. scripts/process_audit.py grades them SUPERSEDED."
echo "  CI        prospector-ci (Fly, lhr) -- 2 Linux container runners, label 'heavy'. CI does"
echo "            NOT run on this Mac. The actions.runner.* jobs here are offline ON PURPOSE;"
echo "            do not start them. A queued pull request is usually capacity, not a dead"
echo "            runner. Ask, never guess:"
echo "      gh api repos/chidionyema/prospector/actions/runners --jq '.runners[] | \"\\(.name) \\(.status) busy=\\(.busy)\"'"

for repo in "$HOME/Documents/code/prospector" \
            "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/code/prospector" \
            "$HOME/Documents/code/prospector-live"; do
  [ -e "$repo/.git" ] || continue
  behind=$(git -C "$repo" rev-list --count HEAD..origin/main 2>/dev/null)
  case "$behind" in
    "" ) : ;;
    0  ) echo "CHECKOUT $repo — level with origin/main (as of its last fetch)" ;;
    *  ) echo "CHECKOUT $repo — $behind commits BEHIND origin/main as of its last fetch. Its" \
              "CLAUDE.md and docs describe an older estate. Check any architectural claim against" \
              "origin/main before acting on it." ;;
  esac
done

echo "AUDIT everything scheduled, across both hosts, graded:"
echo "      .venv/bin/python scripts/process_audit.py --quiet        (console page: /processes)"
exit 0
