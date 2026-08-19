# Agent practice programme

The tracked stream for how Claude sessions work in this estate: what an agent is told at the
start, what stops it doing the wrong thing, and how either of those is known to still be working.
Append results here. Do not put them in `CLAUDE.md` — that file carries rules, this one carries
the programme and its ledger.

Tracking issue: [#380](https://github.com/chidionyema/prospector/issues/380).

## The failure class

An agent's picture of the estate comes from text. Text goes stale in hours and **there is no tell
from the inside**: a correct paragraph and a two-month-old one read identically. Three incidents,
all in the same week:

| date | what an agent believed | what was true |
|---|---|---|
| 2026-08-18 | production is the laptop's `com.prospector.*` launchd jobs | production had been on Fly for a day; the agent reported an outage while the engine ruled verdicts in lhr |
| 2026-08-19 | the local GitHub runners are spare capacity to start by hand | they are off by founder decision; the agent told the founder to `launchctl kickstart` them |
| 2026-08-19 | `prospector-ci` is the *intended* home for CI (`estate_map.py`, `ESTATE_MAP.md`) | CI had run there since #335 |

The rule that follows: **a fact that changes belongs in a probe, not in prose.**

## The mechanisms, and the command that proves each one live

Never trust the description. Run the command.

| mechanism | what it does | prove it |
|---|---|---|
| `ops/state_probe.sh` | the SessionStart brief. Renders the measured estate snapshot and its age | `bash ops/state_probe.sh` |
| `scripts/estate_map.py --snapshot` | measures Fly apps, machines, endpoints, runners, laptop jobs; writes `<store>/ops/estate_map.json` | `.venv/bin/python scripts/estate_map.py --quick` |
| `ops/share_memory.sh` | one memory store for every checkout and worktree, instead of one per cwd | `bash ops/share_memory.sh --check` |
| ten session hooks | refuse a forbidden command, stop a drip of one-command turns, block a push with no PR | `<hook> --selftest` — all ten answer it |
| `scripts/process_audit.py` | grades every one of the above, plus launchd, plists, worktree drift | `.venv/bin/python scripts/process_audit.py --quiet` (console: `/processes`) |
| `scripts/live_checkout.py` | is production running the code that was merged | `.venv/bin/python scripts/live_checkout.py` |
| `scripts/rework_metrics.py` | the guard on the efficiency numbers: fixes as a share of classifiable commits | `.venv/bin/python scripts/rework_metrics.py` |

Two properties every mechanism here must have.

**It fails loudly.** Hooks fail OPEN — the harness ignores a broken hook and the turn proceeds —
so a rule that stopped working looks exactly like a rule with nothing to say. That is why each one
carries a `--selftest` and why the audit runs them. An enforcement nobody grades is an enforcement
nobody has.

**It is graded where the founder looks.** A probe that only answers when someone thinks to run it
is prose with extra steps. Every row above appears on `/processes`.

## Ledger

Shipped:

- `ops/state_probe.sh`, installed to `~/.claude/state-probe/prospector.sh`; the audit compares the
  two by hash, so the installed copy cannot drift silently (#373)
- the probe renders `estate_map.py`'s measurement instead of a hand-written paragraph (#381)
- CI location is a `gh api` measurement in the probe, the audit and `estate_map.py` (#373, #381)
- all ten session hooks answer `--selftest`; the audit runs and grades them (#373, #381)
- the hooks are tracked in git; the audit reports any hook file behind `origin/main` (#381)
- `ops/share_memory.sh` and the audit row that grades the memory partition (#381)
- `scripts/rework_metrics.py` and the `/method` rework card (#373)

Open:

- `bash ops/share_memory.sh --apply` — needs the founder; the auto-mode classifier refuses writes
  under `~/.claude`. Until it runs, a session outside the main checkout sees 13 of 391 memories
- no scheduled refresh of `estate_map.json` yet, so the probe's snapshot ages until someone runs
  `--snapshot`. The audit should grade its age
- `context-guard-hook.py` nudges at 140K resident context and cannot block. 38 of the last 40
  sessions peaked above it, median 165,553. Enforcement would have to change shape, and that is a
  founder decision (see the handoff in `checkpoints/`)
- both developer checkouts sit ~60 commits behind `origin/main`, so their injected `CLAUDE.md`
  describes an older estate. Measured today: main's `CLAUDE.md` has replaced the "no hosted
  service" rule; the stale copies still carry it

## Adding to this programme

One rule: **arrive with a measurement.** A practice change is a claim about behaviour, so it needs
the number it moved or the incident it would have caught, in the ledger above, with the command
that reproduces it. A practice with no measurement is a preference, and preferences belong in a
conversation rather than in a programme.
