#!/usr/bin/env bash
# Wire rule-guard.py into ~/.claude/settings.json as a PreToolUse hook.
#
# WHY A SCRIPT AND NOT AN EDIT
# ----------------------------
# Claude Code's permission classifier refuses an agent editing ~/.claude/settings.json — tried
# through Bash and through the Edit tool, refused every time. That fence is reasonable: an agent
# that can rewrite its own settings can remove its own guards. So the agent writes the change and
# you run it.
#
# WHAT IT DOES
#   1. Backs up settings.json with a timestamp.
#   2. Runs rule-guard's selftest FIRST. A guard that fails its own tests is never wired.
#   3. Adds the hook to the PreToolUse entry whose matcher is "Bash", next to hang-guard.py.
#   4. Idempotent: if it is already wired, it says so and changes nothing.
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
GUARD="$HOME/.claude/scripts/rule-guard.py"
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
pre = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])

def has(entry):
    return any(h.get("command") == cmd for h in entry.get("hooks", []))

if any(has(e) for e in pre):
    print("   already wired — nothing to do")
    sys.exit(0)

# Prefer the entry that already matches Bash, so the guard sits beside hang-guard.py and runs
# on exactly the same calls. Only create a new entry if no Bash matcher exists.
target = next((e for e in pre if e.get("matcher") == "Bash"), None)
if target is None:
    target = {"matcher": "Bash", "hooks": []}
    pre.append(target)
target.setdefault("hooks", []).append({"type": "command", "command": cmd})

text = json.dumps(cfg, indent=2) + "\n"
json.loads(text)          # parse what we are about to write, not what we think we wrote
path.write_text(text)
print("   added to the Bash PreToolUse entry")
PY

echo "== 4. verify =="
python3 -c "
import json,pathlib,sys
cfg=json.loads(pathlib.Path('$SETTINGS').read_text())
hooks=[h['command'] for e in cfg['hooks']['PreToolUse'] for h in e.get('hooks',[])]
ok=any('rule-guard.py' in h for h in hooks)
print('   PreToolUse hooks now:'); [print('    -',h) for h in hooks]
sys.exit(0 if ok else 1)
"

echo
echo "WIRED. Now QUIT Claude Code and relaunch — settings.json is read once at process start,"
echo "so /clear will not pick this up. Prove it fired with:  git add -A   (it must refuse)."
