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

---

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
