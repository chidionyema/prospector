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
# Rules for anything added below. No network call a session WAITS ON — this runs before every
# session. A detached background refresh behind a staleness gate and a lock is allowed, and there
# are two below; only the founder-task one leaves this machine, and nothing reads its result until
# the NEXT session. Absolute paths only — memory-loop runs it with cwd=$HOME. Read-only, always
# exit 0: a probe must never be the reason a session fails to start.

set -u

INSTALL_DIR="$HOME/.claude/state-probe"
INSTALL_PATH="$INSTALL_DIR/prospector.sh"

MAIN_CHECKOUT="$HOME/Documents/code/prospector"

# Claude Code names a project directory after the session's cwd with '/', ' ', '~' and '.' all
# flattened to '-'. That is lossy, so this only ever runs FORWARDS: slug a known path and compare.
path_slug() { printf '%s' "$1" | tr '/ ~.' '----'; }

# Every place a prospector session could plausibly be started. Worktrees under /private/tmp are
# included so a session in one still gets graded; the INSTALL step skips them because their
# project directories are throwaway.
candidate_checkouts() {
  printf '%s\n' "$MAIN_CHECKOUT" \
    "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/code/prospector" \
    "$HOME/Documents/code/prospector-live"
  git -C "$MAIN_CHECKOUT" worktree list --porcelain 2>/dev/null \
    | sed -n 's/^worktree //p'
}

install_probe() {
  mkdir -p "$INSTALL_DIR"
  cp "$0" "$INSTALL_PATH"
  chmod +x "$INSTALL_PATH"
  echo "installed $INSTALL_PATH"
  # The founder-task reader is installed beside the probe rather than called out of a checkout.
  # A checkout is the wrong thing to depend on here: the main one was 11 commits behind when this
  # was written, and prospector-live is pinned to origin/main by a different job on its own
  # cadence. Installing it makes the probe self-contained, and process_audit.py compares this copy
  # to the source exactly as it does the probe itself, so the second copy cannot drift in silence.
  local reader; reader="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)/scripts/founder_tasks.py"
  if [ -f "$reader" ]; then
    cp "$reader" "$INSTALL_DIR/founder_tasks.py"
    chmod +x "$INSTALL_DIR/founder_tasks.py"
    echo "installed $INSTALL_DIR/founder_tasks.py"
  else
    echo "NOT installed: scripts/founder_tasks.py was not found next to $0 --"
    echo "  run --install from a checkout, not from the installed copy, or the task list stays blank"
  fi
  local n=0 m=0
  # Every session started in a prospector checkout or one of its worktrees gets the same brief.
  # The tmp scratchpad slugs are skipped: they are throwaway cwds, not places work is done.
  #
  # The pointer carries the checkout it belongs to. A probe run by the harness has cwd=$HOME, so
  # without this it can say where the ESTATE is but nothing about the checkout the session is
  # actually sitting in -- and that checkout is what supplies the session's CLAUDE.md. Both
  # developer checkouts were ~60 commits behind main on 2026-08-19, briefing every session there
  # on an estate we no longer run. Baking the path in at install time is the only way the probe
  # can grade it, because the project directory name is a lossy slug: '/', ' ', '~' and '.' all
  # become '-', so it cannot be turned back into a path. Matching forwards works; reversing does not.
  while IFS= read -r dir; do
    case "$dir" in *-private-*) continue ;; esac
    local slug checkout=""
    slug="$(basename "$dir")"
    # Read a line at a time. `for cand in $(...)` splits on spaces, and the iCloud checkout path
    # contains one ("Mobile Documents") -- which is exactly the checkout that went unmatched when
    # this was first written.
    while IFS= read -r cand; do
      [ -n "$cand" ] || continue
      if [ "$(path_slug "$cand")" = "$slug" ]; then checkout="$cand"; break; fi
    done < <(candidate_checkouts)
    if [ -n "$checkout" ]; then
      # The path is QUOTED in the pointer. The iCloud checkout has a space in it, so an
      # unquoted argument arrives as two words and the probe grades a path that is not there.
      printf 'bash "$HOME/.claude/state-probe/prospector.sh" --checkout \"%s\"\n' "$checkout" \
        > "$dir/.state-probe"
      m=$((m + 1))
    else
      printf 'bash "$HOME/.claude/state-probe/prospector.sh"\n' > "$dir/.state-probe"
    fi
    n=$((n + 1))
  done < <(find "$HOME/.claude/projects" -maxdepth 1 -type d \
             \( -name '*code-prospector' -o -name '*code-wt-*' \) 2>/dev/null)
  echo "pointed $n project directories at it ($m matched to a checkout on disk)"
}

if [ "${1:-}" = "--install" ]; then
  install_probe
  exit 0
fi

# The checkout this session is sitting in, baked into the pointer at install time. Empty when the
# probe is run by hand, and the block that uses it is skipped rather than guessed at.
SESSION_CHECKOUT=""
[ "${1:-}" = "--checkout" ] && SESSION_CHECKOUT="${2:-}"

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

# --- which store is canonical -------------------------------------------------------------------
# Founder ruling 2026-08-19: production is canonical. This block exists because the docs said the
# opposite for a day after the cutover and an agent believed them: the where-production-runs skill
# read "State did NOT move ... That is the canonical store", naming the laptop path. Measured that
# evening, Fly's ledger carried 166,013 rows stamped that day and the laptop copy carried 0. A
# reader pointed at the laptop store does not show less than the truth. It shows a confident zero.
# Local only: an mtime, no network, so this costs a session nothing.
_ledger="$STORE/prospector.jsonl"
if [ -f "$_ledger" ]; then
  _mt="$(stat -f %m "$_ledger" 2>/dev/null || echo 0)"
  _age_h=$(( ( $(date +%s) - _mt ) / 3600 ))
  echo "STORE  canonical is /data/store on prospector-engine, volume vol_42kyqo6g0kdzew14."
  echo "  the laptop store is a stopped copy: $STORE last written ${_age_h}h ago, and"
  echo "  config.store_root() in ANY process on this Mac resolves to it. Ask production instead:"
  echo "      fly ssh console -a prospector-engine -C \"tail -1 /data/store/prospector.jsonl\""
fi
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

# How far behind is the code this session is reading? A checkout does not merely hold old code:
# the harness injects ITS CLAUDE.md as authoritative instructions. So a stale checkout hands the
# agent an old description of the estate and calls it a rule. The session's own checkout is named
# first and marked, because "one of these three is stale" is not something an agent can act on.
grade_checkout() {
  local repo="$1" mark="$2" behind head_desc
  [ -e "$repo/.git" ] || return 0
  behind=$(git -C "$repo" rev-list --count HEAD..origin/main 2>/dev/null) || return 0
  [ -z "$behind" ] && return 0
  head_desc=$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null)
  [ "$head_desc" = "HEAD" ] && head_desc="detached $(git -C "$repo" rev-parse --short HEAD 2>/dev/null)"
  if [ "$behind" = "0" ]; then
    echo "CHECKOUT$mark $repo ($head_desc) — level with origin/main as of its last fetch"
    return 0
  fi
  echo "CHECKOUT$mark $repo ($head_desc) — $behind commits BEHIND origin/main as of its last fetch."
  # Only the session's OWN checkout gets the detail. This text is injected into every session, so
  # three paragraphs about checkouts nobody is sitting in is pure cost.
  [ -z "$mark" ] && return 0
  # Naming the file that actually changed turns a vague warning into something to check. The rules
  # a session is briefed on live in CLAUDE.md, so that one is called out by name.
  if ! git -C "$repo" diff --quiet HEAD origin/main -- CLAUDE.md 2>/dev/null; then
    echo "           Its CLAUDE.md DIFFERS from origin/main, so some rule injected into this"
    echo "           session has already been changed or retired. Read the main copy before"
    echo "           acting on any rule that matters:  git -C \"$repo\" diff HEAD origin/main -- CLAUDE.md"
  else
    echo "           Its CLAUDE.md matches origin/main; the drift is in code and docs."
  fi
}

if [ -n "$SESSION_CHECKOUT" ]; then
  grade_checkout "$SESSION_CHECKOUT" "  >> THIS SESSION IS HERE:"
fi
for repo in "$HOME/Documents/code/prospector" \
            "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/code/prospector" \
            "$HOME/Documents/code/prospector-live"; do
  [ "$repo" = "$SESSION_CHECKOUT" ] && continue
  grade_checkout "$repo" ""
done

# --- the founder's task list ----------------------------------------------------------------------
# Measured 2026-08-20: the task list was already persisted, at ~/.claude/tasks/<session-id>/<n>.json.
# Persistence was never the problem, discovery was. That store is keyed by SESSION, so a new session
# opens on an empty list: 231 open tasks across 45 prospector session directories, 231 distinct
# subjects, zero overlap, because no session can see another one's. Dumping those 231 here would
# spend a screen of every agent's context on another session's scratch work, forever. So the durable
# list is GitHub issues labelled `founder-task` — already the estate's claim mechanism, and readable
# by the founder without a terminal.
#
# Printing is local and always exits 0. The refresh that WRITES the cache needs the network, so it
# runs detached, only when the cache is over 6h old, behind a lock — the same shape as
# _refresh_snapshot_if_stale above. If it never works (no `gh` on PATH, no auth), nothing here
# breaks: the printed line starts saying STALE after 24h and carries the command that fixes it.
_founder_tasks_reader() {
  local cand
  # The installed copy first: it is the one --install put there, and it does not go stale when a
  # checkout does. The checkouts are a fallback for a probe run straight out of a tree.
  for cand in "$INSTALL_DIR/founder_tasks.py" \
              "$SESSION_CHECKOUT/scripts/founder_tasks.py" \
              "$MAIN_CHECKOUT/scripts/founder_tasks.py" \
              "$HOME/Documents/code/prospector-live/scripts/founder_tasks.py"; do
    case "$cand" in /scripts/*) continue ;; esac        # SESSION_CHECKOUT empty
    [ -f "$cand" ] && { printf '%s' "$cand"; return 0; }
  done
  return 1
}
_ft_reader="$(_founder_tasks_reader)" || _ft_reader=""
if [ -z "$_ft_reader" ]; then
  # Saying nothing here is the failure this section exists to fix. A list that silently disappears
  # is indistinguishable from a list with nothing on it.
  echo "FOUNDER TASKS: reader not installed, so the list is not being shown. Fix it with:"
  echo "      bash ops/state_probe.sh --install     (from a checkout that has scripts/founder_tasks.py)"
else
  python3 "$_ft_reader" 2>/dev/null || true
  _ft_state="$HOME/.claude/state"
  # find on a missing file prints nothing, so a cache that does not exist yet takes this branch too.
  if [ -z "$(find "$_ft_state/founder-tasks.json" -maxdepth 0 -mmin -360 2>/dev/null)" ]; then
    _ft_lock="$_ft_state/.founder-tasks.refresh.lock"
    mkdir -p "$_ft_state" 2>/dev/null
    [ -n "$(find "$_ft_lock" -maxdepth 0 -mmin +30 2>/dev/null)" ] && rmdir "$_ft_lock" 2>/dev/null
    if mkdir "$_ft_lock" 2>/dev/null; then          # another session is already refreshing
      ( python3 "$_ft_reader" --refresh; rmdir "$_ft_lock" 2>/dev/null ) \
        >/dev/null 2>&1 &
    fi
  fi
fi

echo "AUDIT everything scheduled, across both hosts, graded:"
echo "      .venv/bin/python scripts/process_audit.py --quiet        (console page: /processes)"
exit 0
