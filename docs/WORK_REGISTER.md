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
| 12 | R2 retention actually prunes | `prospector-backup` 4,234 objects / 0.973 GB; `prospector-packs` 4,250 objects / 0.316 GB. `ops/config/offsite_backup.yaml` declares `keep: 30`, `max_age_hours: 24`. `offsite_backup._prune` is at `ops/automations/offsite_backup.py:339`, called at `:328` | Nothing has ever proved `_prune` ran. It swallows failures. Run it read-only, then with `--fix`, and compare the object count before and after |

---

## 4. Open — Hermes

The founder's instruction was to treat Hermes the way Prospector is treated: one environment,
a real pipeline, no blind spots. Two strands remain.

| # | Strand | Why it is not done |
| --- | --- | --- |
| 4 | Give Hermes a leader lease so only one environment is live | Design settled — reuse the `host:pid:uuid` lease from the Prospector queue, `docs/decisions/0002`. Not written |
| 5 | Move Hermes to `~/Documents/code/hermes` and give it Prospector's pipeline | `~/.hermes` still has no `.github/workflows/` at all. Until it does, Hermes has no CI, so nothing about it can be graded the way Prospector is |

A lease matters more than the move. Two live environments with no lease is the failure the
founder named ("we cant have 2 ennvironents running"), and the move alone does not fix it.

---

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
