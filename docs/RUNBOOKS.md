# Runbooks — what to do when a line goes red

One entry per automation in `ops/automations/`. Every entry answers the same five questions, in
the same order, so the reader never has to hunt: what it checks, what red means, what to do, how
long it takes, and what to do if the fix fails.

Rules for this file (`docs/OPS_AUTOMATION_PRINCIPLES.md` R5):

- An automation without an entry here is not finished.
- Commands are copy-pasteable, with the directory they run in.
- No entry says "investigate". Say what to look at and what a good answer looks like.
- Every automation exits **0 clean, 1 findings, 2 could not establish**. Exit 2 is not clean; it
  means the check could not run and the real state is unknown.

This file says what to do while a thing is red. [`INCIDENT_PROCESS.md`](INCIDENT_PROCESS.md) says
what to do once it is green again: sweep for the siblings, land the mechanism that retires the
class, and grade it. A runbook entry that keeps getting used is an incident nobody raised.

---

## Incident runbooks — the five fires

The entries BELOW this section are one per automation in `ops/automations/`: what that job
does, and what to do when its line goes red. The entries in THIS section are one per
INCIDENT CLASS, and they exist because the founder named the gap on 2026-08-21: "we need to
dvelop and naintain runbook/protocols to reduce firefightinh, eg when a pr fails, when nain
is broken, when site goes down, we need sturctured stepes thathave been proven to work,
shortest path to reolutions etc, root cause if first tine occuring etc".

The two halves answer different questions and neither replaces the other. A red automation
line tells you WHICH job failed; an incident runbook tells you what to do when the failure
is not one job — a pull request that will not go green, a storefront that will not serve.

Two rules bind every entry here:

1. **The first command always reads the actual failure text.** Not a status letter, not a
   colour, not a count. LAW 2 exists because six Fly machines were bought to fix a queue
   that was never full, off a table that already said `F` for FAILED.
2. **An unrun step is a proposal, and is marked UNPROVEN.** A runbook that carries a step
   nobody has executed is worse than a short one: it reads as proven and sends the next
   person down a path that may not exist.


Founder directive 2026-08-21: "we need to dvelop and naintain runbook/protocols to reduce
firefightinh, eg when a pr fails, when nain is broken , when site goes down, we need sturctured
stepes thathave been proven to work, shortest path to reolutions etc, root cause if first tine
occuring etc".

Every step below was run on this estate and worked. Where a step has a receipt, the receipt is
named. This file is not advice: it is the record of what actually ended the fire last time, so
the next session does not rediscover it at the same cost.

**Two rules bind every runbook here.**

1. **The first command is always the one that reads the actual failure text.** Not the status
   table, not the colour, not the count. LAW 2 exists because on 2026-08-19 a session read `F`
   in a status column as congestion and bought six machines to fix a queue that was not the
   problem; the failing job log named the real cause — one red test on main — in seconds.
2. **A runbook step that has never been run is a proposal, not a step.** Mark it `UNPROVEN` and
   say so, so nobody follows it into a fire believing it worked before.

### Status

| ID | Runbook | Status | Last proven |
|----|---------|--------|-------------|
| RB1 | A pull request is red | **DONE** | 2026-08-21, PR #568, cause found in 2 commands |
| RB2 | `main` is red | **DONE** | 2026-08-19, one test red on main blocking 12 PRs |
| RB3 | The storefront is down or failing its checks | **DONE** | 2026-08-21, live smoke red on one viewport |
| RB4 | The engine cannot rule a verdict | **DONE** | 2026-08-20, moat blind 19.6h |
| RB5 | Spend spikes | **DONE** | 2026-08-21, $592 day traced to its real owner |
| RB6 | A guard or hook is refusing everything | **DONE** | 2026-08-21, a false alarm on pr-freeze traced to its selftest |
| RB7 | A worktree or checkout has gone bad | **DONE** | 2026-08-21, this session's own tree; 44 of 113 dead |

---

### RB1 — A pull request is red

**How you know.** `gh pr view <n> --repo chidionyema/prospector --json statusCheckRollup`.

**Shortest path, in order. Stop at the first step that answers.**

1. **Read the failing job's log, not the check name.** One command:
   `gh run view <run-id> --repo chidionyema/prospector --log-failed | grep -iE "Error|assert|✘" | head -40`.
   The check name tells you which lane; only the log tells you the cause.
2. **Ask whether the cause is in YOUR diff.** `git diff origin/main...HEAD --name-only`. If the
   failing file is not in that list, the cause is upstream — go to RB2 and do not debug it here.
3. **Refresh on main before anything else.** `git fetch origin main && git merge origin/main
   --no-edit`. A stale branch fails as somebody else's bug: on 2026-08-20 a branch reported five
   failures, three of them in a test file main had already deleted. Merge, never rebase, never
   force push.
4. **If the failure is in your diff, reproduce it locally before editing.**
   `.venv/bin/python scripts/popdd_verify.py --staged`.
5. **Fix at the source, then prove the test grades the fix:**
   `python3 ~/.claude/scripts/edge_test.py --mutate <file> --test "pytest <test> -q"`.
   A mutation that survives means the test would not have caught the bug you just fixed.
6. **Push, then follow it to MERGED.** An open green pull request is not delivered work.

**Proven, 2026-08-21, PR #568.** The check said `python` failed. Step 1 printed
`assert re.search(...)` naming a capacity contract. Step 2 said the file WAS mine. The cause was
a comment I had added in the same diff: the checker greps the workflow source for `pytest -n N`,
and it read the width out of my prose. Two commands from red to cause.

**Root-cause it when it is the first time.** RB1 ends at "merged". LAW 6 then asks what let it
break. That one produced `_uncommented()` in `scripts/ci_capacity.py` and a test that fails if a
commented width ever masks a real one again.

---

### RB2 — `main` is red

**This outranks every open pull request.** While main is red, every branch inherits the failure
and every session debugs a fiction. Nobody's PR can be diagnosed until this is out.

1. **Confirm it is main and not you.**
   `gh run list --repo chidionyema/prospector --branch main --limit 5 --json conclusion,databaseId`.
2. **Read the log** (RB1 step 1) and get the failing symbol.
3. **Search for an existing fix before writing one.** `git log --all --oneline -1 -- <path>`,
   `git show origin/main:<path>`, `rg -l '<the distinctive symbol>'`. On 2026-08-19 the fix for
   the red test blocking twelve pull requests was already open as PR #425.
4. **If a fix exists, land THAT.** If not, the smallest diff that makes main green, on its own
   branch, merged ahead of everything else.
5. **Say it once on the board**, so the other sessions stop debugging their own diffs:
   `~/.claude/ESTATE_BOARD.jsonl` gets every peer message automatically.

**Proven, 2026-08-19.** Seven jobs failed on the same assertion. One red test on main, inherited
by every branch. Reading one job log replaced a day of per-PR diagnosis.

---

### RB3 — The storefront is down or failing its checks

**How you know.** The board's "Shipped — is it live?" section, or
`gh run list --repo chidionyema/prospector --workflow e2e-live-smoke.yml --limit 3`.

1. **Is the site answering at all?** A 200 and a body over 2000 bytes is the floor. Anything
   less is an outage and skips to step 5.
2. **Is it answering with the RIGHT build?** `e2e-live-smoke` runs only after a Deploy Store.Web
   run and on a daily cron — never on a pull request. So a green smoke can be grading a build
   two deploys old. Check `Deploy Store.Web`'s last run before trusting it.
3. **Read which spec failed, and at which viewport.** A single failing viewport is a layout
   defect, not an outage, and it does not justify a rollback.
4. **Reproduce against the same live URL before touching CSS:**
   `cd store_platform/src/Store.Web && WEB_BASE_URL=https://mumchimp.com npx playwright test e2e/<spec> --project=chromium`.
   When local and CI disagree, that disagreement is the finding — take a third measurement
   before believing either.
5. **A real outage rolls back first and diagnoses after.** Restoring service outranks knowing why.

**Proven, 2026-08-21.** The smoke went red on one phone viewport, `360x780`, at 18px of the first
card visible. Local runs of the same spec against the same URL passed at 72px. Blocking webfonts
locally changed nothing, which killed the font-metrics theory. Measuring the stack rather than
the total found the budget: a 490px hero section under a 116px header, on a 780px screen.

---

### RB4 — The engine cannot rule a verdict

**How you know.** `.venv/bin/python scripts/live_checkout.py`, and the daemon's tick log saying
`moat_blind`.

1. **Read which brains carry a dead mark, and why.** A dead mark is TRANSIENT (429/503/529) or
   PERMANENT (402, credit balance, spend allowance). They need different answers: transient
   clears itself in 60s, permanent needs a key or money.
2. **One live brain of any tier is enough to generate.** The generation preflight skips a tick
   only when EVERY configured verdict brain is dead.
3. **The drain is trusted-only, on purpose.** Re-vetting a `provisional` row on a provisional
   brain re-stamps it `provisional`: the row does not move and the money is spent.
4. **When the moat recovers, drain it:** `vet --resume` finalises both populations.

**Proven, 2026-08-20.** The engine was moat blind for 19.6 hours with 75 finished PASSes stranded
off the shelf, and no session noticed, because every session was holding the stack view and none
was holding the platform view. That is now a row on the founder's board.

---

### RB5 — Spend spikes

1. **Get the real owner before touching a knob.** `python3 ~/.claude/scripts/estate_spend.py --json`
   breaks the day down by owner.
2. **Know what your lever actually reaches.** `halt_usd` fires on the DAEMON leg only.
3. **Only then decide.** Money leaving the account is the founder's decision, always.

**Proven, 2026-08-21.** A $516.79 day. The board said "spend halt DISARMED — nothing stops the
spend", which pointed at the wrong lever: the daemon spent $1.51 of it. Arming the halt would
have saved 0.3% and stopped the engine. The other 99.7% was five concurrent interactive coding
sessions, which no halt in this estate can touch.

---

### RB6 — A guard or hook is refusing everything

**Proven 2026-08-21.** The first question is not "which guard is broken". It is **whether the
guard is broken at all**, because the two cheapest instruments both lie in the same direction.

**Step 1 — read the refusal text, not the exit code.** A PreToolUse hook writes its reason to
stderr and exits 2. That text names the guard and usually the escape hatch. An exit code alone
names nothing, and `cmd | tail` reports TAIL's status, so a refused command can read as `exit 0`.

**Step 2 — check the guard's PRECONDITION before believing its selftest.** Most guards here are
inert until something exists on disk. Run the precondition first:

```bash
ls -la ~/.claude/PR_FREEZE            # pr-freeze: absent => it refuses nothing, by design
ls -la store/scheduler/PAUSE          # the engine's kill switch
git config --get core.hooksPath       # set => THAT directory wins over .git/hooks
```

This step exists because skipping it produced a false alarm on 2026-08-21: `pr-freeze.py
--selftest` reported `3 failed`, and the honest-looking conclusion — "the freeze is not blocking
`gh pr create` while every session believes it is" — was written down and reported. It was wrong.
No `~/.claude/PR_FREEZE` existed, so `check()` returned `None` correctly on all three cases. The
SELFTEST was broken, not the guard: it called `check()` with no freeze file on disk and then
asserted a block. It was grading the guard's OFF state and asserting it was ON.

**Step 3 — run every guard's selftest, in parallel, and read the two buckets separately.**

```bash
for f in ~/.claude/scripts/*.py; do python3 "$f" --selftest >/dev/null 2>&1 \
  || echo "$f -> $?"; done
```

Exit 2 with `unrecognized arguments` is not a failing guard. It is a guard that ADVERTISES a
selftest it does not have, which is worse, because every reader assumes it is proven.

**Step 4 — a passing selftest is not a working guard.** Prove the test grades the file:

```bash
python3 ~/.claude/scripts/edge_test.py --mutate ~/.claude/scripts/<guard>.py \
        --test "python3 ~/.claude/scripts/<guard>.py --selftest"
```

A surviving mutant is a line no test grades. On 2026-08-21 this found `pr-freeze.py`'s hook
entry point ungraded: flipping `!= "Bash"` to `==` makes the guard fire for every tool EXCEPT
Bash, so during a real freeze it would refuse nothing and say nothing.

**Step 5 — when two guards are each correct alone and wrong together, the PAIR is the defect.**
Fix the pair, not your own way around it. A workaround gets one session moving and leaves the
next to rediscover the whole thing from a standing start.

**Do not** edit your own permission settings to get past a classifier refusal, and do not ask a
peer to run what your permissions refused. A denial you have to disguise is a denial to respect.

### RB7 — A worktree or checkout has gone bad

**Proven 2026-08-21.** The tell is that tests and guards fail while naming anything but git.

**Step 1 — read what SessionStart already told you.** The `worktree-git-guard` hook prints
`THIS WORKING TREE HAS NO GIT` with the exact path its `.git` file points at. It is above the
first message of the session, which is precisely where nobody looks.

**Step 2 — ask git, never the filesystem.**

```bash
cat .git                              # in a worktree .git is a FILE containing `gitdir:`
git rev-parse --git-common-dir        # the shared dir; hooks-active lives HERE
git ls-files | wc -l                  # 0 with exit 0 is the signature of a dead worktree
```

`git ls-files` printing nothing AND EXITING 0 is the whole trap: every guard and test that asks
git for the tracked file list then grades an empty repo and passes or fails for invented reasons.
Anything that reads `<root>/.git/…` as a directory is a bug for the same reason.

**Step 3 — do not repair it. Make a new one and RE-APPLY.**

```bash
git -C /Users/chidionyema/Documents/code/prospector worktree add --detach ../wt-new origin/main
/Users/chidionyema/Documents/code/prospector/scripts/setup_worktree.sh ../wt-new
```

Re-apply your edits by hand; never copy whole files across. A dead tree can be many commits
adrift from main, and copying reverts other sessions' work without a conflict to warn you.

**Step 4 — `git worktree add` alone produces a tree that LOOKS complete and is not.**
`setup_worktree.sh` is the only correct way to make one. It fixes four traps that each
misdirect the diagnosis: `node_modules` cannot be symlinked (Turbopack rejects any symlink
leaving the project root — use `cp -Rc`); `.lux/keys/agent.pem` is untracked, so the commit gate
runs and then fails for want of a signing key, reading as a gate violation; `.venv` is absent
while the hook pins `.venv/bin/python` relative to cwd, so commits die over a missing
interpreter; and `store/` and `storage/` are TRACKED runtime state that pytest writes to, so
`git add -A` in a worktree commits another session's scratch.

**Step 5 — one session, one worktree.** Sessions sharing a checkout share one `.git/index`, and
`git worktree add` succeeds even while that index is locked, which is exactly the point.

**Files are still readable in a dead tree.** Read your work out of it; write it into the new one.

## retired-terms

**What it checks.** Every tracked file, for names that were deliberately removed from the
business. The names and the allowed exceptions are declared in `ops/config/retired_terms.yaml`;
the engine holds no names of its own.

**Run it.**

```bash
cd /Users/chidionyema/Documents/code/prospector
.venv/bin/python -m ops.automations.retired_terms          # human output
.venv/bin/python -m ops.automations.retired_terms --json   # what the console calls
```

**What red means.** A file names something that no longer exists. That is not cosmetic. The last
one, Paddle, was the literal default provider in five places, so a catalogue row with no provider
sent a buyer to a payment rail nobody could bill. Legal pages named it as a sub-processor when it
processed nothing, which is a false statement in a UK GDPR notice.

**What to do.** Read each finding and put it in one of two buckets.

1. **A live leftover.** Remove it. Replace the name with what actually happens now. If it is a
   default (`?? "name"`, `or "name"`, `|| 'name'`), the replacement is the real current default,
   never an empty string — an empty default is how a row silently routes nowhere.
2. **History.** A dated audit, an applied database migration, a spec with a superseded banner, a
   test that pins the removal. Add its path prefix to the `allow:` list in
   `ops/config/retired_terms.yaml` **with a written reason on the line above it.** A prefix with
   no reason is how this check quietly stops checking.

Then re-run. Exit 0 is the receipt.

**How long.** Minutes for a handful of findings. The Paddle removal itself took a working session
and touched 34 files across C#, TypeScript, Python, config and legal copy.

**If it exits 2 (could not establish).** The check could not run, and the state is unknown.

- `declaration not found` — you are in the wrong directory, or the YAML was moved. Pass
  `--config <path>`.
- `not a git repository` — the automation lists files through `git ls-files`. Run it inside the
  repo or a worktree of it.
- `PyYAML is not installed` — use the project virtualenv (`.venv/bin/python`), not system python.

**When it should run.** On every CI run, and on the console's scheduled sweep. It is pure CPU over
tracked files (about 1,200 files, under a second), so there is no reason to run it rarely.

**Adding a new retired name.** Add a `terms:` entry to `ops/config/retired_terms.yaml` with the
name and one sentence saying why it must not come back. Run the check, and allow-list the history
it finds. No code change.

---

## offsite-backup

**What it checks.** That every irreplaceable thing has a recent copy in storage we control,
outside the account that holds the original. The sources, the storage and the freshness window
are declared in `ops/config/offsite_backup.yaml`; the engine holds none of them.

Declared today: `/data/store.db` on the Fly volume (orders, entitlements, grant tokens, download
counts, price history) and `/data/keys`, the ASP.NET Data Protection key ring.

**Run it.**

```bash
cd /Users/chidionyema/Documents/code/prospector
.venv/bin/python -m ops.automations.offsite_backup          # how old is each copy?
.venv/bin/python -m ops.automations.offsite_backup --json   # what the console calls
.venv/bin/python -m ops.automations.offsite_backup --fix    # take a backup now
```

**What red means.** Either no copy exists, or the newest is older than the declared window (24
hours). Fly's own snapshots are not a substitute: they live in the same Fly account as the
volume, keep 5 days, and nobody has restored one. Lose the account, or notice a corruption on day
six, and the record of who bought what is gone.

**What to do.**

1. Run `--fix`. It fetches, opens the copy to prove it is readable, uploads it under a dated key
   and prunes to the declared `keep`. A copy that fails its check is not uploaded, so a bad copy
   can never displace a good one.
2. If `--fix` fails, read the reason. It names the source and the stage.

**How long.** The database is about 3.6 MB, so a fetch and upload is seconds.

**If it exits 2 (could not establish).** The check could not run, and the state is unknown. Exit 2
is never clean.

- `missing credentials: R2_…` — the run has no `.env` and no environment. Names only are printed,
  never values.
- `local clock is …s from the storage endpoint` — fix the clock, not the keys. A signed request
  with a skewed timestamp is rejected as a bad signature, which reads like a credentials problem
  and is not one.
- `storage endpoint did not answer` — network or R2 outage. Nothing was uploaded and nothing was
  lost; the next run retries from the same state.
- `fetch exited …` — the host CLI failed. Usually `fly auth login`. Note that `fly auth whoami`
  can pass on a dead token, so trust the fetch's own error over a login probe.
- `the copy does not open as SQLite` / `failed PRAGMA integrity_check` — the copy is torn.
  Re-run; if it repeats, the source itself may be damaged, which is an incident, not a backup
  problem.

**When it should run.** Daily. `deploy/com.prospector.offsite-backup.plist` runs `--fix` at 03:50,
and a `--fix` run prints the freshness check too, so one green line in
`store/offsite_backup.log` is the daily receipt. Install it once:

```bash
cd /Users/chidionyema/Documents/code/prospector
cp deploy/com.prospector.offsite-backup.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.prospector.offsite-backup.plist
tail -20 store/offsite_backup.log   # after 03:50 the next morning
```

The read-only check costs one storage listing, so run it as often as you like; the console will
call it on its sweep. It is deliberately not on its own hourly timer yet — an hourly line in a log
nobody reads is not monitoring, and the console screen (R6) is where it becomes visible.

**Restoring.** This automation makes copies; it does not restore. `scripts/restore_drill.py` is
the drill for the engine store. There is no tested restore of `store.db` into a fresh Fly machine
yet — that is expectation E5 in `docs/OPS_AUTOMATION_PRINCIPLES.md` and it is still open.

**Adding a new backup source.** Add a `sources:` entry with `name`, `key`, a `fetch:` command as a list
of arguments (`{dest}` is substituted with the download path), a `why:` in plain words, and
`verify:` — `sqlite` to open it and run an integrity check, `nonempty` for anything else. No code
change.

---

## log-rotation

**What it checks.** Every log named in `ops/config/log_rotation.yaml`, against the size limit
declared next to it. The engine holds no paths and no limits.

**Run it.**

```bash
cd /Users/chidionyema/Documents/code/prospector
.venv/bin/python -m ops.automations.log_rotation          # what is over its limit
.venv/bin/python -m ops.automations.log_rotation --json   # what the console calls
.venv/bin/python -m ops.automations.log_rotation --fix    # rotate what is over
```

**What red means.** A log is past the size at which people still read it. That is not a disk
problem, it is a wrong-answer problem. On 2026-08-16 a `grep -c` over a 25 MB unrotated
`launchd.err.log` counted 97 provider failures and read as "97 today". Today's real number was 8,
and most of the rest named a provider chain that had already been deleted. The wrong number
reached `docs/LAUNCH_OPS_PROGRAM.md` as a blocker.

**What to do.** Run `--fix`. It compresses the content into `<log>.<UTC stamp>.gz`, truncates the
original in place, and prunes to the declared `keep`.

**How long.** Seconds. The first real run compressed 62.7 MB down to 5.5 MB.

**How it rotates, and why you must not "improve" it to a rename.** It copies and truncates in
place. It never renames. A daemon holds its log open by file descriptor, and renaming the file
does not move that descriptor: the daemon keeps writing into the renamed file, the fresh log
stays empty, and the next person to read it sees a process that has gone silent. Every writer
here is under launchd, which redirects stdout by descriptor. `tests/unit/test_log_rotation.py`
pins the inode across a rotation for exactly this reason.

**If it exits 2 (could not establish).** The check could not run, and the state is unknown.

- `declaration not found` — wrong directory, or the YAML moved. Pass `--config <path>`.
- `not a git repository` — relative paths in the declaration are resolved from the git root.
  Run it inside the repo or a worktree of it. Absolute paths in the declaration work anywhere.
- `PyYAML is not installed` — use `.venv/bin/python`, not system python.

**When it should run.** Daily at 04:00 via `deploy/com.prospector.log-rotation.plist`, after the
two backup jobs so a rotation cannot race a copy of the thing being rotated. Install it once:

```bash
cd /Users/chidionyema/Documents/code/prospector
cp deploy/com.prospector.log-rotation.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.prospector.log-rotation.plist
```

**What is deliberately not rotated.** `store/prospector.jsonl` — 211 MB and 761,090 lines on
2026-08-16. It looks like a log and it is the durable spend ledger the daily cap reads, so
truncating it changes what the spend guard believes. Shrinking it is a separate job with its own
reader. `store/scheduler/audit/*.jsonl` is one file per day already, so it rotates by
construction. Both exclusions are written into the declaration with their reasons.

**Adding a log.** Add a `targets:` entry with `path` (a file, a glob, or an absolute path), a
`why:` in plain words, and optionally `max_mb` and `keep`. No code change.

## stranded-packs

**What it checks.** Every pack that passed research (`store/dossiers/<id>.pass.json`) is checked
against the publication gate's own record (`<id>.lint.json`). A pack whose lint record says `ok`
is sellable. A pack whose record says otherwise, or that has no record at all, is *stranded*:
the research was paid for and the pack cannot be bought.

**Command.** `python -m ops.automations.stranded_packs` — read-only, no model calls, no network.
Add `--json` for the console shape, `--root <checkout>` to measure a checkout other than the one
the code lives in (a worktree carries the code but not `store/`).

**What red means.** Exit 1 with a count. The breakdown names the linter rule blocking each pack,
so the output is a work list, not an alarm. Measured 2026-08-16 on the main checkout: 38 of 100
passed packs stranded — 29 failed lint, 9 had never been linted; the rules doing the blocking were
grammar (27 packs), citation_urls (27), shelf_copy (25), title_new_word (11), title_claim (7),
currency (6), title (3), placeholders (2), marketing_audience (1).

**What to do.** Nothing here repairs anything and there is no `--fix`, deliberately: repair means
re-running content generation, which costs model calls (R8, P3). Use the breakdown to decide.
- `never_linted` packs are the cheapest win: `python -m tools.publish_passes --dry-run --all` runs
  the gate and writes the missing lint records, and costs zero model calls.
- `citation_urls` is usually link rot on old packs, not bad writing.
- `grammar`, `shelf_copy` and the `title_*` rules need the pack's copy regenerated.

**How long.** The check itself is seconds over a few thousand files. The repair is not — size it
from the breakdown before starting.

**Exit 2 (`unknown`) reasons, all of them.** No declaration at `ops/config/stranded_packs.yaml`;
the declaration is not valid YAML or not a mapping; pyyaml missing; no dossier directory at the
declared path; **no file matching `pass_glob`** — that last one exists because the dossier naming
is `<id>.pass.json` and reading the id with `Path.stem` yields `<id>.pass`, which finds no lint
record and reports every pack as stranded. A zero match is a naming change, never a clean shelf.

**Adding this to another startup.** Point `dossier_dir`, `pass_glob` and `lint_suffix` at its own
layout. The engine has no fact about this business in it.

---

## human-register

**What it checks.** Every `<id>.lint.json` in the dossier store, for the `human_register` block
that `pack_linter.lint_pack` writes (`pack_linter.py:1858`) and the ops dashboard panel reads.
The store path, the document types and the shape of a dossier are declared in
`ops/config/human_register.yaml`; the engine holds none of them.

**Run it.**

```bash
cd /Users/chidionyema/Documents/code/prospector
.venv/bin/python -m ops.automations.human_register          # human output, writes nothing
.venv/bin/python -m ops.automations.human_register --json   # what the console calls
.venv/bin/python -m ops.automations.human_register --fix    # write the missing blocks
```

**What red means.** Lint records exist that carry no `human_register` block, so the panel that
reads it draws nothing for those packs. It happened because the block shipped after every pack on
disk had already been linted. It will happen again after any change to what the block contains.

**What to do.** Run it with `--fix`. That is the whole fix, and it costs no model call: the block
is pure measurement over text (`register_lint.register_metrics`), so the numbers come from the
prose already on disk. Do **not** answer this by running a batch. A generation cycle costs three
model calls per document to produce a number a re-read produces for free.

Every block `--fix` writes carries `"backfilled": true` and `"corpus": "prose_artifacts"`, so a
backfilled record is never read as a fresh lint. The provenance matters because a live lint grades
`pack_sections or prose` — the assembled 14-section read when the caller has it, the four prose
documents otherwise — and a dossier on disk does not store the assembled read. The backfill takes
the same fallback `lint_pack` itself takes, not a shortcut invented for the backfill.

**Unmeasurable records are not findings.** A lint record whose dossier is gone, or whose dossier
holds no prose, cannot be measured by anything. Those are listed under `unmeasurable` with the
reason, and they do not make the check red. A red line nobody can act on is how a check stops
being read. As of 2026-08-16 there were 22 of them out of 112 records: 15 with no dossier for the
id, 7 with a dossier and no prose.

**Prose outside the human range is not a finding either.** That is the generator's business, and
it is tracked in `docs/PROSE_CORPUS_PROGRAM.md`. This automation only guarantees the number exists
to look at. It reports the tally under `summary.outside_the_human_range` and the per-measure split
under `summary.per_measure`, which is how you see at a glance that (for example) `mattr` and
`punct_hyphen_per_1k` are the two measures failing on nearly every document.

**How long.** Seconds. It reads JSON off local disk and does arithmetic. 112 records took under a
minute including the writes.

**If it exits 2 (could not establish).** The check could not run, and the state is unknown.

- `declaration not found` — you are in the wrong directory, or the YAML was moved. Pass
  `--config <path>`.
- `store directory not found` — `store_dir` in the declaration does not exist under the repo root.
- `not a git repository` — the automation resolves the root through `git rev-parse`. Run it inside
  the repo or a worktree of it.
- `prospector.register_lint.register_metrics is not importable` — you are on a branch that predates
  the human register, or not using the project virtualenv. Use `.venv/bin/python`.
- `PyYAML is not installed` — same cause: use `.venv/bin/python`, not system python.

**When it should run.** On the console's scheduled sweep, and after any batch. It is pure CPU over
local files, so there is no reason to run it rarely.
