#!/usr/bin/env bash
# Wire idle-guard.py into ~/.claude/settings.json as a Stop hook.
#
# WHY A SCRIPT AND NOT AN EDIT
# ----------------------------
# Claude Code's permission classifier refuses an agent editing ~/.claude/settings.json, through
# Bash and through the Edit tool alike. That fence is right: an agent that can rewrite its own
# settings can remove its own guards. So the agent writes the change and you run it.
#
# WHAT IT ENFORCES
#   Never end a turn while a backgrounded command is still running. Measured 2026-08-17:
#   15 minutes 50 seconds idle on one shell, with the rule loaded in context at the time.
#
# WHAT IT DOES
#   1. Backs up settings.json with a timestamp.
#   2. Runs idle-guard's selftest FIRST. A guard that fails its own tests is never wired.
#   3. Adds it to the Stop hook list.
#   4. Idempotent: if already wired, it says so and changes nothing.
#   5. Validates the JSON before writing. If anything is wrong, the original is untouched.
#
# AFTER RUNNING IT
#   settings.json is read ONCE at process start. `/clear` does NOT reload it. Quit Claude Code
#   and relaunch, or the guard stays inert and you will believe it is live.
#
# TO UNDO
#   cp ~/.claude/settings.json.bak-<timestamp> ~/.claude/settings.json
set -euo pipefail

SETTINGS="$HOME/.claude/settings.json"
GUARD="$HOME/.claude/scripts/idle-guard.py"
CMD="python3 $GUARD"

[ -f "$SETTINGS" ] || { echo "no settings at $SETTINGS"; exit 1; }
[ -f "$GUARD" ]    || { echo "no guard at $GUARD"; exit 1; }

echo "== 1. selftest =="
python3 "$GUARD" --selftest || { echo "SELFTEST FAILED — not wiring a guard that fails its own tests"; exit 1; }

BACKUP="$SETTINGS.bak-$(date +%Y%m%dT%H%M%S)"
cp "$SETTINGS" "$BACKUP"
echo "== 2. backup =="
echo "   $BACKUP"

echo "== 3. wiring =="
python3 - "$SETTINGS" "$CMD" <<'PY'
import json, sys, pathlib

path, cmd = pathlib.Path(sys.argv[1]), sys.argv[2]
cfg = json.loads(path.read_text())
stop = cfg.setdefault("hooks", {}).setdefault("Stop", [])

if any(h.get("command") == cmd for e in stop for h in e.get("hooks", [])):
    print("   already wired — nothing to do")
    sys.exit(0)

# Stop hooks take no matcher. Reuse an existing entry if there is one.
target = stop[0] if stop else None
if target is None:
    target = {"hooks": []}
    stop.append(target)
target.setdefault("hooks", []).append({"type": "command", "command": cmd})

text = json.dumps(cfg, indent=2) + "\n"
json.loads(text)          # parse what we are about to write, not what we think we wrote
path.write_text(text)
print("   added to the Stop hook list")
PY

echo "== 4. verify =="
python3 -c "
import json,pathlib,sys
cfg=json.loads(pathlib.Path('$SETTINGS').read_text())
hooks=[h['command'] for e in cfg.get('hooks',{}).get('Stop',[]) for h in e.get('hooks',[])]
ok=any('idle-guard.py' in h for h in hooks)
print('   Stop hooks now:'); [print('    -',h) for h in hooks]
sys.exit(0 if ok else 1)
"

echo
echo "WIRED. Now QUIT Claude Code and relaunch — settings.json is read once at process start,"
echo "so /clear will not pick this up."
echo "Prove it fired: ask for something that backgrounds a long run, and watch the agent be"
echo "refused permission to go quiet while it runs."
