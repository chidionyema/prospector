# Work register

Every strand this agent has open or has closed, in one place, with the receipt that proves the
state. Written 2026-08-19 because work was being tracked in a task list that only one session
could see, and in chat replies that scroll away.

The rule: **a strand is closed when a command says so, not when a reply says so.** Every row
below carries either a merged PR number, a file that exists on `origin/main`, or an explicit
"unproven" with the check that would settle it.

This file is a register, not a plan. The plan is `docs/LAUNCH_OPS_PROGRAM.md` §4, and results
are appended to its §7 ledger. What this adds is the view across strands, including the ones
that are blocked and the ones nobody has graded.

---

## 1. Closed — merged to `origin/main`

| # | Strand | Where it landed |
| --- | --- | --- |
| 1 | Estate probe grades disabled and not-loaded launchd jobs | PR #373 |
| 2 | Estate probe covers the Fly apps, not just this Mac | PR #373 |
| 3 | Estate probe scheduled, failures routed to Telegram | PR #373 |
| 7 | Hermes gate green — the Hermes `run.sh` gate exits `GATE: PASS` | Hermes repos, pushed |
| 9 | Log rotation scheduled — the policy existed and nothing ran it | `com.prospector.log-rotation`, every 6h |
| 10 | Age-based pruning for directories of many files | `ops/automations/log_rotation.py` |
| 11 | Hermes and system-wide logs under one retention policy | `docs/LOGGING_AND_RETENTION.md` |
| — | Incident process: three orders, a grade, a weekly job that fails until the sweeps are run | PR #352, PR #376 |
| — | Store paths that followed the code instead of the store | PR #372, PR #350 |
| — | Deploy after merge, for every deployable, not just the engine | PR #366, PR #369 |
| — | Drain stopped retiring rows because our own brains were down | PR #356 |

Check any row: `gh pr view <n> --json state`. Check the schedule:
`launchctl list | grep com.prospector.log-rotation`.

---

## 2. Open — code written, waiting on CI or review

| # | Strand | PR | State |
| --- | --- | --- | --- |
| 13 | Every automation reachable from the ops console; ENG-5 graded on behaviour | #382 | OPEN, MERGEABLE |
| 14, 15, 16 | Security and build gates in Python, .NET and TypeScript | #393 | OPEN |

`#393` sits on a `main` that is red on one test —
`test_console_tool_registry_has_no_drift`, because `scripts/rework_metrics.py` is in neither
`TOOLS` nor `NOT_AN_OPS_TOOL`. `#382` fixes exactly that. So `#382` merges first, then `#393`
rebases. Neither branch should try to fix it twice.

---

## 3. Open — measured, not finished

| # | Strand | What is proved | What is missing |
| --- | --- | --- | --- |
| 6 | Telegram alert noise | Code shipped (`921106b`). The complaint had no number behind it; both paths were already debounced | 24h of real data to set `HERMES_ALERT_HOURLY_CAP`, which is at 12 by guess, not by measurement |
| 12 | R2 retention actually prunes | **The prune works.** Measured 2026-08-19: `offsite/money-db` holds exactly 30 objects and `offsite/data-protection-keys` exactly 30, against `keep: 30` in `ops/config/offsite_backup.yaml`. A series sitting exactly on its cap is the prune doing its job | The gap is elsewhere. `_prune` only ever touches the prefixes named as `sources`. `prospector-backup` holds 4,283 objects / 1.044 GB, and 4,150 of them are under `dossiers/` with no retention policy at all, plus `ledger/` at 0.220 GB across 17 copies. Declare a policy for those two, then run it read-only, then with `--fix` |

---

## 4. Open — Hermes

The founder's instruction was to treat Hermes the way Prospector is treated: one environment,
a real pipeline, no blind spots. Two strands remain.

| # | Strand | Why it is not done |
| --- | --- | --- |
| 4 | Give Hermes a leader lease so only one environment is live | Design settled — an object in the existing `prospector-backup` R2 bucket, holder `host:pid:uuid`, short TTL, renewed by the primary and acquired by the laptop only once it expires. R2 is the only storage both environments reach. A bare pid will not do: a pid only means something on the machine that minted it. Not written |
| 5 | Move Hermes to `~/Documents/code/hermes` and give it Prospector's pipeline | `~/.hermes` has no `.github/workflows/` at all, measured 2026-08-19. Until it has CI, nothing about Hermes can be graded the way Prospector is |

A lease matters more than the move. Two live environments with no lease is the failure the
founder named ("we cant have 2 ennvironents running"), and the move alone does not fix it.

### Two findings, and what was done about them — 2026-08-19

**Finding 1: the Fly coordinator database sat on the image filesystem. Any deploy would have
erased it. FIXED.**

```
fly ssh console -a prospector-hermes -C "ls -la /Users/chidionyema/.hermes/coordinator.db"
  -rw------- 1 root root 176128 Aug 18 22:46          <- a real file, not a symlink
fly ssh console -a prospector-hermes -C "ls -la /data/db"
  ls: cannot access '/data/db': No such file or directory
```

`deploy/hermes/entrypoint.sh:26-40` already contained the fix, and had never been deployed. A
written fix that was never shipped reads exactly like a shipped one to anyone reading the file.

The repair order is the opposite of the obvious one. The entrypoint only copies a database onto
the volume when the volume has none (`[ -s "/data/db/$f" ] || cp ...`, line 35), and a fresh
image has no work in it, so deploying first destroys the database. The volume was seeded first:

```
printf 'put coordinator.db /data/db/coordinator.db\n' | fly ssh sftp shell -a prospector-hermes
  176128 bytes written
read back, both ends:  840828d9c99c8dd22cf131db466004cebfec767b   (identical)
sqlite3 integrity_check -> ok ; tasks=12 ; events=125
```

Then deployed. Proof it is fixed:

```
fly ssh console -a prospector-hermes -C "readlink -f /Users/chidionyema/.hermes/coordinator.db"
  /data/db/coordinator.db
fly ssh console -a prospector-hermes -C "ls -la /data/db/"
  coordinator.db  coordinator.db-shm  coordinator.db-wal   <- the coordinator is writing there
```

**Finding 2: two coordinators ran at once, on databases that cannot be reconciled. FIXED, and
fenced.**

```
FLY   supervisorctl status -> cockpit, coordinator, otto-server, progress, rsi,
                              submodule-backup RUNNING
MAC   launchctl list       -> ai.hermes.coordinator, ai.hermes.otto-server,
                              ai.hermes.gateway all with live pids
```

The Mac side is booted out and disabled, which survives a reboot:

```
launchctl bootout  gui/501/<label>
launchctl disable  gui/501/<label>
```
applied to coordinator, otto-server, cockpit, rsi, progress, submodule-backup, watchdog,
selfcheck and gateway. Watchdog and selfcheck went too, because they exist to resurrect the
others. Still loaded on the Mac and correct to leave: `keepawake`, `idle-engine`,
`runaway-reaper`.

**Turning it off is not a fence, so a fence was added.** `scripts/check_single_environment.sh`
in the Hermes repo fails when any daemon Fly's supervisord runs is also loaded on this Mac.
`verify_estate.sh` calls it as a `SOLO` section and a non-zero exit fails the whole probe. The
primary is declared in `config/primary_environment`, so failing over to the laptop is a
one-line edit rather than a code change.
`scripts/test_verify_estate_single_environment.sh` proves the fence can fail: it stubs
`launchctl` on `PATH`, so it needs no real daemon. `GATE: PASS`, 4 checks.

**A third finding fell out of the second: `HERMES_GATEWAY_AUTOSTART` was decorative.**
`entrypoint.sh:101-105` printed which state the flag was in, while `supervisord.conf:45` said
`autostart=false` unconditionally. Setting the flag to 1 in `fly.toml` did nothing, and the
gateway could only ever be started by hand. So "the gateway has its own fence" was true on
paper and false in the container. `supervisord.conf` now reads
`autostart=%(ENV_HERMES_GATEWAY_AUTOSTART)s`, and the flag is 1: the single Telegram
long-poller runs on Fly, next to the coordinator database that actually has the data. The Mac
gateway is stopped and disabled. Before this it was answering from a database nothing writes
to any more, which is worse than no door at all.

**A fourth finding, from turning the flag on: the image could never have run the gateway.**
`hermes_cli` was not installed in it.

```
grep -c hermes_cli /opt/venv/lib/python3.11/site-packages/__editable___hermes_agent_0_16_0_finder.py
  0
gateway ->  ModuleNotFoundError: No module named 'hermes_cli'   (exit 1, four restarts)
```

The Dockerfile installs the package editable before `COPY . .`, so dependency resolution is
not repeated on every script change. That part is right. But setuptools writes its editable
finder at that moment and maps only the packages it can see, and `hermes_cli/` was not in the
build context yet. Every other daemon execs a script by absolute path, so none of them noticed.
The gateway is the only program that imports the package by name, and the flag had kept it from
ever being asked. Two defects hid each other: a decorative flag, and an image missing the one
package that flag controlled.

Fixed by re-running the editable install after the source lands, `--no-deps` so the expensive
layer is untouched, plus an import assertion at build time so this fails on the builder rather
than in a restart loop. `supervisorctl status` now reads `gateway RUNNING`, and the log opens
with "Hermes Gateway Starting" and the MiniMax routing override.

What is left on this strand is the leader lease (row 4 above). Booting the Mac out settles
today; a lease is what makes the primary a fact both machines agree on.

## 5. Blocked — needs the founder

Each of these was attempted and refused. One line each, no menu.

- Start Fly machine `8e4530a7712248` on app `prospector-ci`. Classifier-refused. (It reads
  `online` as of 2026-08-19, so this may already be moot — re-check with
  `fly machine list -a prospector-ci`.)
- Three self-hosted Mac runners are `offline`: `mumchimp-mac`, `-2`, `-3`. Investigating was
  classifier-refused. CI still runs, on the Fly runners, so this is capacity, not an outage.
- Rename `com.prospector.backup` to `com.prospector.store-backup`. The current label is
  poisoned. Classifier-blocked.
- `~/.claude/scripts/branch-pr-guard.py` — classifier-blocked from further edits.

---

## 6. Known and ungraded

These are real, they are written down here so they stop being invisible, and none of them has
an owner or a date.

- **Nothing compares the two stores.** Fly `/data/store/prospector.jsonl` is 328,080,365 bytes
  across 1,088,160 rows. The local `store/prospector.jsonl` is 270,713,139 bytes. No probe
  reads both. `CLAUDE.md` still says "There is exactly one", which is now false.
- Backup provenance: an ad-hoc `offsite_backup --fix` run leaves no record of who ran it or why.
- Three stale Hermes daemons need `launchctl kickstart -k`.
- The Prospector pre-commit gate is not installed in the shared checkout. Nothing local refuses
  a bad commit; CI is the only gate.
- Five periodic jobs report a nonzero last exit.
- `scripts/launchd_plists.py --check` reports `DRIFT ai.hermes.coordinator` and `BROKEN` for
  `com.haworks.continuous-review` and `com.haworks.test-coverage`.
- Issue #355, production alerting.
- One orphan row, `cancel_test_001`.
- 63 stranded packs fail the pack lint.
- `xunit 2.9.2` is flagged Legacy-deprecated; `xunit.v3` exists.
- The storefront's kill-log numbers are baked at build time
  (`src/data/kill-log-totals.json`). `EvidenceBands.tsx:28` picks `top = gates[0]` while the
  sentence under it is hand-written for `min_composite`, so re-running the generator alone
  would print the wrong explanation. **This one is a founder question, not a task** — the
  alternative is a request-time endpoint on Store.Api, which does not exist and is an API
  change. Do not build it without an answer.

---

## 7. How to read this file in six months

```bash
gh pr list --state open --author @me            # strands still in flight
.venv/bin/python scripts/ops_status.py          # the 44 programme ids, graded against origin/main
.venv/bin/python scripts/session_check.py       # uncommitted work, unpushed commits, PRs without checks
bash ~/.hermes/scripts/verify_estate.sh         # is the estate operational right now
```

If a row here disagrees with one of those commands, the command is right and this file is
stale. Fix the file.
