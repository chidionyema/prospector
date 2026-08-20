#!/bin/bash
# cost-guard-probe.sh — the LIVE answer to "is the cost configuration actually in effect?"
#
# Written 2026-08-06 after a 40% saving sat un-banked because settings.json was edited
# mid-session. Claude Code reads `model` ONCE at process start, and /clear mints a new
# session ID *inside the same process*. So a brand-new session kept running Opus while
# every config layer said "sonnet". Config being correct is NOT evidence it is in effect.
#
# Two bugs were found in this probe's own first draft, both of which reported PASS
# falsely. They are why the checks below are written the way they are:
#   1. `launchctl getenv MISSING_VAR` exits 0, so a `>/dev/null 2>&1` test on it is
#      VACUOUS. Test with [ -n "$(launchctl getenv X)" ] or not at all.
#   2. macOS `ps -o lstart=` emits "Thu  6 Aug 00:30:31 2026" — day BEFORE month, and a
#      double space. `date -j -f` and strptime("%a %b %d ...") both fail on it, and a
#      failed parse silently skipped the check. Parse by tokens instead. `ps -o etimes=`
#      does not exist on macOS either.
#
# Read-only. Exit 0 = every lever in effect, 1 = at least one is configured but not live.
set -uo pipefail
SETTINGS="$HOME/.claude/settings.json"
FAIL=0

echo "── CLAUDE CODE COST GUARD ── $(date -u '+%Y-%m-%d %H:%M UTC')"

# ── 1+2. CONFIGURED MODEL vs PROCESSES THAT COULD HAVE READ IT ────────────────
python3 - "$SETTINGS" <<'PY' || FAIL=1
import json,os,subprocess,sys,time,datetime
settings=sys.argv[1]
conf_t=os.path.getmtime(settings)
model=json.load(open(settings)).get('model') or '<unset>'
print(f"config   : model={model}   (settings.json {datetime.datetime.fromtimestamp(conf_t):%Y-%m-%dT%H:%M:%S})")
pids=subprocess.run(['pgrep','-x','claude'],capture_output=True,text=True).stdout.split()
stale=[]
for p in pids:
    parts=subprocess.run(['ps','-p',p,'-o','lstart='],capture_output=True,text=True).stdout.split()
    if len(parts)!=5: continue
    _,a,b,hms,yr=parts
    mon,day=(a,b) if a.isalpha() else (b,a)   # handles "Aug 6" and "6 Aug"
    t=time.mktime(time.strptime(f"{day} {mon} {hms} {yr}","%d %b %H:%M:%S %Y"))
    if t<conf_t: stale.append((p,t))
for p,t in stale:
    print(f"  ⚠️  pid {p} started {datetime.datetime.fromtimestamp(t):%Y-%m-%d %H:%M} — PREDATES config")
if stale:
    print(f"processes: ❌ {len(stale)} of {len(pids)} predate the config — they are still on the OLD model.")
    print( "           fix: quit Claude Code entirely and relaunch. /clear is NOT enough —")
    print( "           it mints a new session inside the same process, which never re-reads settings.json.")
    raise SystemExit(1)
print(f"processes: ✅ all {len(pids)} started after the config was written")
PY

# ── 3. ACTUAL MODEL IN USE (transcript truth, not config) ─────────────────────
python3 - "$HOME/.claude/projects" <<'PY'
import json,os,glob,sys,collections
files=sorted(glob.glob(os.path.join(sys.argv[1],'*','*.jsonl')),key=os.path.getmtime)[-3:]
c=collections.Counter()
for f in files:
    try:
        for line in open(f):
            if '"model"' not in line: continue
            try: m=(json.loads(line).get('message') or {}).get('model')
            except Exception: continue
            if m and not m.startswith('<'): c[m]+=1
    except OSError: pass
tot=sum(c.values()) or 1
for m,n in c.most_common():
    print(f"actual   : {m:26s} {n:5d} req ({100*n/tot:3.0f}% of last 3 transcripts)")
PY

# ── 4. AUTH SOURCE ────────────────────────────────────────────────────────────
# A set ANTHROPIC_API_KEY outranks the claude.ai login for any process that has it.
# NOTE: no rc file sets this on this machine (proven 2026-08-06 with `env -i zsh -l`);
# it survives only in the inherited env of long-lived processes. So we test THIS
# process's env — that is exactly the env the running session is using.
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "auth     : ❌ ANTHROPIC_API_KEY present in this session's env — outranks the subscription"
  BODY=$(curl -s --max-time 10 https://api.anthropic.com/v1/messages \
    -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d '{"model":"claude-haiku-4-5-20251001","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}')
  echo "           key status: $(echo "$BODY" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('error',{}).get('message','LIVE and BILLABLE')[:70])" 2>/dev/null)"
  echo "           fix: relaunch claude from a NEW terminal (no rc file sets it; it is inherited)"
  FAIL=1
else
  echo "auth     : ✅ no ANTHROPIC_API_KEY — Claude Code uses the claude.ai subscription"
fi

# ── 5. SESSION FLOOR — re-paid at every session start ─────────────────────────
python3 - <<'PY'
import os
BUDGET=12000
paths=[("global CLAUDE.md",os.path.expanduser('~/.claude/CLAUDE.md')),
       ("project CLAUDE.md",os.path.join(os.getcwd(),'CLAUDE.md')),
       ("MEMORY.md",os.path.expanduser('~/.claude/projects/-Users-chidionyema-Documents-code-prospector/memory/MEMORY.md'))]
tot=0
for label,p in paths:
    if os.path.exists(p):
        t=int(os.path.getsize(p)/3.6); tot+=t
        print(f"floor    : {label:18s} {t:6,d} tok")
ok = tot<=BUDGET
print(f"floor    : {'✅' if ok else '❌'} TOTAL {tot:,} tok (budget {BUDGET:,}) — paid at EVERY session start")
raise SystemExit(0 if ok else 1)
PY
[ $? -ne 0 ] && FAIL=1

echo "──"
if [ "$FAIL" -eq 0 ]; then echo "VERDICT: ✅ every cost lever is IN EFFECT"; else echo "VERDICT: ❌ a lever is configured but NOT live (see ❌ above)"; fi
exit $FAIL
