# Reliability architecture

How this estate knows it is working, and how it says so when it is not.

Written 2026-08-19, after a founder directive: *"we been fixing this one at a time piece by piece
but need coherent AND WELL THOUGHT/ENGINEERED RELIABILITY"*, and *"everything running must be
auditable, configurable and visible from the ops dashboard"*, and *"the enforcements also need to
be visible and alert when failed"*.

## Production is Fly. This Mac is estate support.

Read this before anything else, because getting it wrong is what produced the worst finding in this
document. The engine runs in the `prospector-engine` app on Fly, one machine in `lhr`, declared by
`deploy/engine/fly.toml`. Its image runs seven programs under supervisord — `scheduler`,
`consumer`, `watchdog`, `backup`, `offsite-backup`, `restore-drill`, `ops-console` — and publishes
one public port, 8611. `prospector-store-api` and `prospector-store-web` serve api.mumchimp.com and
mumchimp.com.

The laptop's `com.prospector.*` launchd jobs did that work until 2026-08-18. They are leftovers.
Six sit unloaded and `com.prospector.backup` still fires daily and fails.

On 2026-08-19 an agent read those unloaded jobs as the production process table and reported
"production engine is down". The engine was ruling verdicts in `lhr` that same minute. The audit
now grades Fly first and marks each superseded job `SUPERSEDED`, so the alarm cannot recur.

## The problem, stated once

This estate was never short of watchers. It had launchd jobs, GitHub workflows, pre-commit gates,
harness hooks, provider health marks, a capability receipt ledger, an incident loop, and about a
dozen specialist probes. What it had no way to see was **whether any of them were still working.**

Every watcher reported only to itself, and each one failed silently in its own way:

| watcher | how it fails silently |
| --- | --- |
| a launchd job | its exit code lives in `launchctl print` and nowhere else |
| a GitHub workflow | one that is never triggered produces no run, so it can never be red |
| a repo guard | switched off, it stops objecting; every later commit looks approved |
| a specialist probe | when it errors before it can measure, it reads the same as "all clear" |

Measured on the day this was written, before any of it was visible:

- five loaded launchd jobs carried a non-zero last exit, two of them for two days
- four jobs were running that no file in this repo declared
- two committed workflows had never produced a single run
- the graph-freshness enforcement had failed every 30 minutes for long enough that nobody knew
- two orphaned worktree directories were crashing that sweep, invisible to `git worktree list`
- the only thing writing the offsite git bundle had been dead since 2026-08-17

Not one of those produced a signal. That is the whole problem: **the estate had healers, and
nothing graded the healers.**

## The shape

Four layers. Only the third and fourth are new; the first two already existed and were left alone.

```
  1  COLLECT     each domain keeps its own specialist probe        (unchanged)
  2  OWN         one probe owns only what nothing else owns        (new, thin)
  3  SURFACE     one console page renders the graded result        (new)
  4  ALARM       one existing channel carries the failure out      (reused)
```

### 1. Collect — the specialists stay

Nothing here was rewritten, because each of these is better at its own question than a general
script would be. The list is the answer to "what do we already have":

| probe | owns |
| --- | --- |
| `fly apps list`, `supervisorctl status` | **production** — what is deployed, and the seven engine programs |
| `scripts/launchd_plists.py --check` | drift between live plists and the tracked copies |
| `prospector/ops/supervisor.py` | whether a job is loaded, and restarting it |
| `~/.hermes/scripts/capability_audit.py` | grading the receipt ledger into PASS / FAIL / DARK |
| `~/.hermes/scripts/estate_watchdog.py` | gateway and coordinator liveness, and restarting them |
| `~/.hermes/scripts/verify_estate.sh` | DEPLOY / DOOR / R1–R5 / FENCES |
| `scripts/ops_state.py`, `scripts/estate_map.py` | the platform's own 16 probes and the Fly estate |
| `prospector/health.py` | provider exhaustion, benching and half-open recovery |
| `prospector/scheduler/alerts.py` | live run conditions — zero yield, quality decay, liveness |
| `scripts/incident.py` | incident records, grades, and the weekly GitHub issue |
| `scripts/graphify_sweep.py` | knowledge-graph freshness across every repo |

### 2. Own — `scripts/process_audit.py`

The meta-probe. It deliberately re-implements none of the above. It owns the five questions that
had no owner at all:

1. **last exit code** of every launchd job we own
2. **never-ran** GitHub workflows, and failing ones
3. **the enforcers themselves** — is the pre-commit gate installed where git actually looks, are
   the graphify hooks wired, does every harness hook script still exist, is the CI guard job
   present, is the doc-lint baseline committed
4. **the specialists' own verdicts**, including whether each could answer at all
5. **things running that nothing declares**, and orphaned directories `git worktree list` cannot see

It also enforces documentation mechanically. Every label and workflow filename must appear in
`docs/PROCESS_INVENTORY.md` in backticks, or it is graded `UNDOCUMENTED`. Adding a process means
adding a row, so a process cannot enter the estate quietly.

```bash
python3 scripts/process_audit.py            # everything, graded
python3 scripts/process_audit.py --quiet    # only the problems
python3 scripts/process_audit.py --json     # what the console reads
python3 scripts/process_audit.py --alert    # and tell the operator when it fails
```

### 3. Surface — the Processes page

`/processes` on the ops console, under Engine. It renders the same JSON, worst first, and it is
registered the same way every other view is: a `_read_*` function in `prospector/ops/console_api.py`,
the name in the `READS` dict, the name in the `VIEWS` allowlist in
`store_platform/src/Ops.Console/src/pages/api/ops/read/[view].ts`, a page, and a nav entry that
`tests/nav.test.ts` refuses to let you skip.

Exit 1 from the script is the *normal* answer on that page, not a read failure. Treating it as an
error would blank the page at the only moment it matters.

### 4. Alarm — the door that already existed

`~/.hermes/scripts/estate_alert.py::send_operator_alert()` sends one Telegram message, holds the
credentials, debounces on a key, and is written never to raise at the caller. `--alert` uses it
with `debounce_key="process-audit"` and an hour's window.

A second notifier was considered and rejected: it would be a second thing to keep working, and
this estate's failure mode is not too few channels.

## Why a meta-probe rather than more alerting on each probe

Alerting on each probe individually is the design that produced the problem. Every one of those
ten specialists could be made to alert, and the estate would still not know when one of them
stopped running — because the alert that never fires looks exactly like the alert that had nothing
to report. Grading them from outside is the only arrangement where silence is distinguishable from
health.

## What is deliberately NOT here

- **No new health checks.** If a question already has an owner, the meta-probe asks the owner.
- **No auto-remediation.** `process_audit.py` never fixes anything. Report mode before fix mode;
  the healers that do act (`estate_watchdog`, `supervisor`) are unchanged and still act.
- **No deletion.** Orphaned worktrees and stale plists are reported, never removed. A pruned
  worktree can still hold uncommitted edits, and git can no longer tell us whether it does.

## Still open, and each needs a decision rather than code

1. **Nothing runs the audit on a schedule yet.** It should be a launchd job wrapped in
   `launchd_receipt.py --label com.prospector.process-audit`, running `--alert`, which puts it in
   the ledger that `capability_audit.py` already grades — so the grader is itself graded.
2. **Receipt staleness has no alarm.** The ledger records every run; nothing fires when a
   capability goes DARK.
3. **The two never-ran workflows.** `escape-hatch-drill.yml` and `weekly-estate-review.yml` are
   both committed and scheduled and neither has ever produced a run.
4. **The instruction files are 59 commits stale in both dev checkouts.** The harness injects the
   CLAUDE.md of the session's working directory, so every session there is briefed on the estate we
   ran before the Fly migration. The audit now fails on it. The remedy is a founder decision: the
   iCloud checkout holds 132 uncommitted paths and must not be reset by an agent.
5. **Seven superseded launchd jobs are still installed on the laptop.** Uninstalling them is one
   command per label and needs a human, because an agent cannot run `launchctl` here.
6. **Two failing jobs belong to other products.** `com.tie.ai-review` points at a script that no
   longer exists; both `com.haworks.*` jobs fail `EX_CONFIG` because their working directory is
   gone. Retiring them is the owner's call.
