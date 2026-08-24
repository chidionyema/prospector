# Onboarding — the offsite restore drill

## What it is for

A backup is not a backup until something has been restored from it. Until 23 August 2026 nothing
on this estate had ever restored anything. The nightly job wrote thirteen things to Cloudflare R2,
checked its own work with a command that only reads file headers, and reported success. The first
time anybody actually tried to open one of those files, the most important of them — the complete
copy of the source repository — had been unopenable for five nights.

This drill is the thing that tries. Once a night it pulls the newest object from every one of the
thirteen prefixes, opens each one according to its kind, and refuses to say PASS unless the
contents came out. SQLite files are opened and integrity-checked. Tarballs are listed. Repository
bundles are cloned, because cloning is what a real restore does and it is the only check that
reads every object in the file. The secret store is decrypted and the number of secrets counted —
the count only, never a value.

Then it deletes everything it downloaded. A drill that leaves a copy of the money database sitting
on the same disk it is protecting has created a second exposure rather than closing one.

## What it costs

About fifteen seconds of laptop time a night and roughly 136 MB of egress from R2. Cloudflare R2
does not charge for egress, so the money cost is zero. The API calls are thirteen LISTs and
thirteen GETs a day, which is inside the free tier by three orders of magnitude.

## What it watches

The thirteen sources declared in `ops/config/offsite_backup.yaml`, against the `prospector-backup`
bucket:

`money-db`, `data-protection-keys`, `agent-estate`, `hermes-state`, `maestro-experience`,
`secret-store`, `architect-code`, `maestro-code`, `logs`, `engine-ledger`, `engine-store-db`,
`repo-mirror`, `engine-logs`.

It watches the backups, not the live data. If a source stops being written the drill notices,
because the newest object in that prefix goes stale and there is nothing new to restore. If a
source is written but corrupt, the drill notices, because it opens it. It cannot tell you that
something the estate depends on was never added to the backup list in the first place — that is a
different question and the answer to it is a code review of the yaml.

## Where it lives

| thing | where |
|---|---|
| the drill itself | `ops/automations/offsite_restore_drill.py` in this repository |
| what it restores | `ops/config/offsite_backup.yaml` |
| the schedule | `~/Library/LaunchAgents/com.prospector.restore-drill.plist`, tracked as `ops/launchd/com.prospector.restore-drill.json` |
| the register entry | `~/.claude/scripts/drills/register.json`, id `offsite-backup-restore` |
| the run log | `~/Documents/code/prospector/store/restore_drill.log` |
| the receipt | `~/.hermes/state/capability_receipts.jsonl`, script `offsite_restore_drill` |
| the grade | `~/.hermes/capabilities.json`, id `offsite_restore_drill` |

The copy that actually runs is in `~/Documents/code/prospector-live`, which is the checkout the
production jobs use. This repository is where it is developed and reviewed.

## How to turn it off

```
launchctl bootout gui/501/com.prospector.restore-drill
```

That is the whole of it. Nothing else on the estate depends on the drill running, so nothing
breaks when it stops. The nightly backup job is a separate launchd job and keeps writing.

The one consequence is that the estate's health audit will start reporting `offsite_restore_drill`
as dark, because it grades the job on having produced a receipt within its budget. That is
correct — with the drill off, nobody is checking the backups, and the board should say so rather
than go quiet.

## How to turn it back on

```
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.prospector.restore-drill.plist
```

It runs immediately on load and then every 24 hours. If the plist itself has been lost, it can be
rebuilt from the tracked copy at `ops/launchd/com.prospector.restore-drill.json`.

## What goes wrong

**The machine was asleep.** launchd's calendar schedules are skipped outright when the machine is
asleep at that minute — the run is not deferred, it simply never happens. This job deliberately
uses `StartInterval` instead, which fires on wake, so a laptop that is shut overnight still gets
its drill. The cost is that the run time drifts.

**The drill runs but reads nothing.** `~/.hermes` resolves into `~/Documents`, which macOS TCC
protects, and `/usr/bin/python3` under launchd is refused there with `Operation not permitted`.
The job runs under `prospector-live/.venv/bin/python`, which has been granted access. If the
launch agent ever starts failing with exit code 2 and a permissions error, that is what has
happened, and the fix is the interpreter, not the file.

**Green for the wrong reason.** The capability is declared `requires: exit0` rather than the
default `artifacts`, because the drill deliberately leaves no files behind. If somebody changes
that declaration to `artifacts`, the job will grade dark on every clean run and the estate will
believe the backups are unchecked when they are fine.

**A source is added to the backup and not to the drill.** They read the same yaml, so this cannot
drift — a new source is restored on the next night automatically. It can fail on the first night
if the restore method for a new kind of file has not been taught to the drill; the failure is
explicit and names the source.
