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

# --- what is running, MEASURED -----------------------------------------------------------------
# Everything below this line used to be a hand-written paragraph. It went stale the way every
# paragraph about state goes stale: silently, with no tell from the inside. It named
# prospector-ci as the "intended home" of CI for the whole time CI actually ran there.
#
# So the facts are measured by `scripts/estate_map.py --snapshot`, which writes
# <store>/ops/estate_map.json, and this probe RENDERS that file and says how old it is. No
# network here: the map shells into Fly and curls the storefront, which is seconds a session
# must not pay. A missing or old snapshot is reported loudly rather than papered over.
STORE="${PROSPECTOR_STORE_DIR:-$HOME/Documents/code/prospector/store}"
SNAP="$STORE/ops/estate_map.json"

# Self-healing before anything else. A snapshot nobody refreshes rots into the same stale
# paragraph this file replaced, and the founder should not have to remember a command. So an old
# snapshot starts its own refresh, detached, and this session renders the OLD one and moves on.
# Never in the foreground: the map shells into Fly and curls the storefront, and a session start
# must not wait for that. The lock is a directory because mkdir is atomic; a lock left behind by
# a killed process is cleared after 30 minutes rather than blocking refreshes forever.
_refresh_snapshot_if_stale() {
  local lock="$STORE/ops/.estate_map.refresh.lock" repo="" py
  [ -n "$(find "$SNAP" -mmin -360 2>/dev/null)" ] && return 0   # fresh enough, nothing to do
  for c in "$HOME/Documents/code/prospector-live" "$HOME/Documents/code/prospector"; do
    [ -f "$c/scripts/estate_map.py" ] && { repo="$c"; break; }
  done
  [ -z "$repo" ] && return 0
  [ -n "$(find "$lock" -maxdepth 0 -mmin +30 2>/dev/null)" ] && rmdir "$lock" 2>/dev/null
  mkdir "$lock" 2>/dev/null || return 0                          # another session is already on it
  py="$repo/.venv/bin/python"; [ -x "$py" ] || py="$(command -v python3)"
  ( cd "$repo" && "$py" scripts/estate_map.py --snapshot; rmdir "$lock" 2>/dev/null ) \
    >/dev/null 2>&1 &
  echo "  (snapshot was over 6h old -- a refresh is running in the background from $repo)"
}
mkdir -p "$STORE/ops" 2>/dev/null
_refresh_snapshot_if_stale

echo "PRODUCTION IS FLY. This Mac is development and estate support, not production."
python3 - "$SNAP" <<'PYEOF' 2>/dev/null || echo "  (no estate snapshot yet -- run: .venv/bin/python scripts/estate_map.py --snapshot)"
import json, sys, time, calendar
path = sys.argv[1]
d = json.load(open(path))
age_h = (time.time() - calendar.timegm(time.strptime(d["as_of_utc"], "%Y-%m-%dT%H:%M:%SZ"))) / 3600
stamp = f"measured {age_h:.0f}h ago" if age_h >= 1 else f"measured {age_h*60:.0f}m ago"
if age_h > 24:
    stamp = (f"STALE: measured {age_h/24:.0f} DAYS ago. Treat every line below as a lead, and "
             f"refresh with `.venv/bin/python scripts/estate_map.py --snapshot`")
print(f"  {stamp}, by scripts/estate_map.py --snapshot")
for a in d.get("fly_apps", []):
    if not a["name"].startswith("prospector-"):
        continue
    m = (d.get("machines") or {}).get(a["name"]) or {}
    print(f"    {a['state']:<4} {a['name']:<22} {a['why'][:78]}")
    if m.get("note"):
        print(f"         {m['note'][:88]}")
bad = [e for e in d.get("endpoints", []) if e["state"] != "ok"]
print(f"  customer-facing URLs: {len(d.get('endpoints', [])) - len(bad)} ok"
      + (f", {len(bad)} NOT ok -> " + ", ".join(e["url"] for e in bad) if bad else ""))
cr = d.get("ci_runners") or {}
if cr.get("note"):
    print(f"  CI: {cr['note'][:200]}")
PYEOF

# Decisions, not measurements. These do not change when a probe runs, so they are written down.
echo "  The live process table is a command, never a snapshot:"
echo "      fly ssh console -a prospector-engine -C \"supervisorctl status\""
echo "  This Mac's com.prospector.* launchd jobs are pre-2026-08-18 leftovers. Do not read them as"
echo "  production and do not restart them. scripts/process_audit.py grades them SUPERSEDED."
echo "  The actions.runner.* jobs here are offline ON PURPOSE. Do not start them. Ask, never guess:"
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
