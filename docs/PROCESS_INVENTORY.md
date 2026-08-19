# Process inventory

Every automated process that runs on this estate, in one place, because nothing else knew.

**This file is machine-checked.** `scripts/process_audit.py` reads it, and any launchd label or
workflow filename that is not written here in backticks is reported `UNDOCUMENTED` and fails the
audit. Adding a process therefore means adding a row. That is the whole point: a process cannot
enter the estate quietly.

The live status is a command, never this page:

```bash
python3 scripts/process_audit.py            # everything, graded
python3 scripts/process_audit.py --quiet    # only the problems
python3 scripts/process_audit.py --json     # what the ops console reads
```

It also appears on the ops console **Engine** page as *Estate processes*.

## What the grades mean

| grade | meaning |
| --- | --- |
| `FAILING` | loaded and its last run exited non-zero. Nothing else reports this. |
| `NEVER-RAN` | a committed workflow that has never produced a single run. A workflow that never fires is never red, so this is the only place it shows. |
| `UNDECLARED` | loaded on this Mac but declared in no `ops/launchd/*.json`. It survives no rebuild. |
| `UNDOCUMENTED` | absent from this file. |
| `warn` | declared but not installed — intended, not running. |

A negative exit is a signal, which is how a keepalive daemon normally stops. Only a positive exit
code counts as a failure.

---

## Prospector engine (this repo)

Production runs from `/Users/chidionyema/Documents/code/prospector-live`, not from a developer
checkout. See the "Where production runs" section of `CLAUDE.md`.

| label | schedule | what it does |
| --- | --- | --- |
| `com.prospector.scheduler` | keepalive | The generation daemon: `prospector.scheduler.run_scheduled --daemon --interval 7200`. |
| `com.prospector.consumer` | keepalive | Drains the queue and publishes: `prospector.run consume --publish`. |
| `com.prospector.watchdog` | every 900s | `run_scheduled --watchdog`; restarts the scheduler when a tick stops landing. |
| `com.prospector.ops-console` | keepalive | Serves the Next.js ops console on the tailnet address. |
| `com.prospector.live-update` | every 60s | `scripts/live_checkout.py --unattended`; rolls the live checkout forward to `origin/main`. |
| `com.prospector.backup` | 03:40 | `scripts/backup_store.py --mirror-only`. **The git bundle mirror, and the only thing that writes it.** The full store backup runs on Fly under `fly:prospector-engine`; this job is not a duplicate of it. |
| `com.prospector.offsite-backup` | 03:50 | `ops.automations.offsite_backup --fix`. |

Three failover jobs run from `~/.prospector/bin/failover`, which is installed by the engine
migration and lives outside this repo. `docs/ENGINE_MIGRATION_PROGRAM.md` is the specification.

| label | schedule | what it does |
| --- | --- | --- |
| `com.prospector-control.failover-watch` | every 60s | Checks whether the Fly engine is answering, and fails over when it is not. |
| `com.prospector-control.receipt-bridge` | every 900s | Copies capability receipts off Fly into the local ledger. |
| `com.prospector-control.standby-sync` | every 900s | Keeps the local standby store in step with Fly. |

## GitHub Actions runners

Four self-hosted runners are declared; historically only some are loaded, which is deliberate —
they are spare capacity, started by hand when CI queues.

`actions.runner.chidionyema-prospector.mumchimp-mac`,
`actions.runner.chidionyema-prospector.mumchimp-mac-2`,
`actions.runner.chidionyema-prospector.mumchimp-mac-3`,
`actions.runner.chidionyema-prospector.mumchimp-mac-4`

## Estate agents (`~/.hermes`, `~/.claude`)

These belong to the agent harness rather than to Prospector. They are declared in `ops/launchd/`
because this repo is where the estate's launchd plists are kept and rebuilt
(`scripts/launchd_plists.py`).

| label | schedule | what it does |
| --- | --- | --- |
| `ai.hermes.gateway` | keepalive | The Hermes CLI gateway. |
| `ai.hermes.coordinator` | keepalive | Agent coordinator daemon. |
| `ai.hermes.cockpit` | keepalive | Cockpit UI daemon. |
| `ai.hermes.otto-server` | keepalive | Otto server daemon. |
| `ai.hermes.ngrok` | keepalive | Public tunnel for the above. |
| `ai.hermes.idle-engine` | keepalive | Runs work while the machine is idle. |
| `ai.hermes.keepawake` | keepalive | `caffeinate -dims`; stops the Mac sleeping through scheduled work. |
| `ai.hermes.watchdog` | every 300s | `estate_watchdog.py`; restarts dead estate daemons. |
| `ai.hermes.runaway-reaper` | every 300s | Kills agent processes that have run away. |
| `ai.hermes.progress` | every 3600s | Writes a progress snapshot. |
| `ai.hermes.rsi` | 04:30 | The nightly self-improvement run. |
| `ai.hermes.submodule-backup` | every 86400s | Backs up the estate submodules. |
| `ai.hermes.selfcheck` | every 3600s | `hermes_selfcheck.py --alert`. **Installed by hand and declared in no repo** — see the open items below. |
| `com.chidionyema.graphify-sweep` | every 1800s | `scripts/graphify_sweep.py --fix`; keeps every repo's knowledge graph fresh. |
| `com.chidionyema.reflect` | every 14400s | `reflect.py --json`; reads session transcripts and produces the incident-loop input. |
| `com.estate.costsentinel` | every 900s | `estate_cost_sentinel.py --digest`; watches token spend. |

## Other products on this Mac

Declared here, owned elsewhere. They are listed so the audit can grade them rather than skip them.

| label | schedule | what it does |
| --- | --- | --- |
| `com.signalengine.daemon` | keepalive | The Signal Engine daemon (`~/Documents/code/signalengine`). |
| `com.tie.ai-review` | 02:00 | Consensus review for the-introduction-exchange. |
| `com.haworks.continuous-review` | every 21600s | `haworks-review` for haworks-platform. |
| `com.haworks.test-coverage` | every 21600s | `haworks-testcov` for haworks-platform. |

## GitHub workflows

| file | trigger | what it does |
| --- | --- | --- |
| `ci.yml` | push, PR, dispatch | The gate. Change detection, then the python, engine, dotnet, nextjs and ops-console lanes. |
| `automerge.yml` | workflow_run | Merges a green PR, then dispatches by hand every deploy the merged files touch. It must dispatch, because GitHub creates no run from a `GITHUB_TOKEN` push. |
| `cancel-ci-on-pr-close.yml` | pull_request | Cancels in-flight CI when a PR closes. |
| `deploy-web.yml` | push paths, dispatch | Deploys the storefront. |
| `deploy-api.yml` | push paths, dispatch | Deploys the store API. |
| `deploy-engine.yml` | push paths, dispatch | Deploys the engine image to Fly. |
| `e2e-live-smoke.yml` | workflow_run | Playwright against the live site after a deploy. |
| `escape-hatch-drill.yml` | schedule, dispatch | Weekly proof that the state can be pulled off Fly intact. |
| `weekly-estate-review.yml` | schedule Mondays 08:00 UTC, dispatch | Grades the incident loop and opens one issue. |

---

## Open items

Recorded here rather than in a chat, because that is where the last inventory went.

1. **`ai.hermes.selfcheck` is loaded and declared nowhere.** It is installed in
   `~/Library/LaunchAgents` and runs hourly, but no `ops/launchd/*.json` describes it, so a
   rebuild of the estate's plists would not recreate it.
2. **`com.tie.ai-review` points at a script that is gone.** Its command is
   `the-introduction-exchange/consensus/engine.py`, which does not exist on disk. Hence exit 2.
   Retiring the job is the owner's call.
3. **Both `com.haworks.*` jobs exit 78 (`EX_CONFIG`) because their `WorkingDirectory`,
   `~/Documents/code/haworks-platform`, does not exist.** The repo was moved or deleted. Same
   call as above.
4. **22 stale `.bak` and `.RETIRED-*` plists sit in `~/Library/LaunchAgents`.** launchd ignores
   them, so they are litter rather than jobs, but they make the directory unreadable.
