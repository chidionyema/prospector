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

## Graded against Anthropic's own guidance

Source: <https://code.claude.com/docs/en/best-practices>, read 2026-08-19. Where it and this
estate disagree, the disagreement is written down rather than settled by preference.

| its practice | us, measured 2026-08-19 |
|---|---|
| "Keep CLAUDE.md concise. Bloated files cause Claude to ignore your actual instructions" | **13,496 tokens injected every session** — 5,819 global, 7,677 project. This is the estate's largest single instruction-following risk and the likeliest reason a rule "stopped working" |
| "For workflows only relevant sometimes, use skills. Claude loads them on demand" | 0 project skills before today. Two of the longest CLAUDE.md sections are now `/where-production-runs` and `/worktree-and-gate`, cutting the project file from 7,677 to 5,443 tokens |
| "Hooks are deterministic; CLAUDE.md instructions are advisory" | 12 hooks wired, all ten of the session ones self-testing and graded. Ahead of the guidance here |
| "Give Claude a check it can run" | `scripts/popdd_verify.py`, `scripts/process_audit.py`, `ops/state_probe.sh`, `scripts/live_checkout.py`. Strong |
| "Use subagents for investigation; scope it or it fills your context" | Standing rule, and the delegation trigger is mechanical (second exploratory read → subagent) |
| "Custom subagents in `.claude/agents/`" | two: `estate-recon` (haiku, read-only, returns a verdict and refs, never dumps) and `receipt-auditor` (adversarial diff review against proof-of-claim discipline). Both committed, so every worktree gets them |
| "`/clear` between unrelated tasks; manage context aggressively" | Enforced by measurement: `context-guard-hook.py` nudges at 140K, and 38 of the last 40 sessions still ran past it |
| "Add an adversarial review step in a fresh context" | `receipt-auditor` exists as of today. Making it routine before a PR is the open half |
| "Explore, plan, code, commit — plan mode for multi-file or unfamiliar work" | Partly. "Plan and claim before code" is a rule, but plan mode itself is rarely used |

Two places this estate deliberately goes further, both for reasons that are written down: every
claim ships with its receipt (proof-of-claim discipline, 2026-06-22), and every enforcement is
itself graded, because hooks fail open.

## Ledger

Shipped:

- `ops/state_probe.sh`, installed to `~/.claude/state-probe/prospector.sh`; the audit compares the
  two by hash, so the installed copy cannot drift silently (#373)
- the probe renders `estate_map.py`'s measurement instead of a hand-written paragraph (#381)
- CI location is a `gh api` measurement in the probe, the audit and `estate_map.py` (#373, #381)
- all ten session hooks answer `--selftest`; the audit runs and grades them (#373, #381)
- the hooks are tracked in git; the audit reports any hook file behind `origin/main` (#381)
- `ops/share_memory.sh` and the audit row that grades the memory partition (#381)
- `.claude/agents/estate-recon.md` and `.claude/agents/receipt-auditor.md` — the recon and
  review prompts stop being retyped from memory each session (#381)
- two guards stopped refusing correct commands: `rule-guard` no longer reads a commit
  message as a command (70/70), `hang-guard` no longer reads a heredoc body as one
  (26/26). Both found by being blocked while writing down the rule itself (#381)
- `scripts/rework_metrics.py` and the `/method` rework card (#373)
- the probe refreshes its own snapshot past 6h, in the background, under a lock; the audit
  grades the snapshot's age so a refresh that stopped working is visible (#381)
- the probe names the checkout THIS session is sitting in, how far behind `origin/main` it is,
  and whether its `CLAUDE.md` differs from main's. Measured today: 61 commits behind, and it
  does differ (#381)

Open:

- `bash ops/share_memory.sh --apply` — needs the founder; the auto-mode classifier refuses writes
  under `~/.claude`. Until it runs, a session outside the main checkout sees 13 of 391 memories
- `context-guard-hook.py` nudges at 140K resident context and cannot block. 38 of the last 40
  sessions peaked above it, median 165,553. Enforcement would have to change shape, and that is a
  founder decision (see the handoff in `checkpoints/`)
- both developer checkouts sit ~60 commits behind `origin/main`. The probe now says so at the top
  of every session, but saying so is not fixing it: nothing refreshes those checkouts, and the
  iCloud one has uncommitted work in it that belongs to another session

## Adding to this programme

One rule: **arrive with a measurement.** A practice change is a claim about behaviour, so it needs
the number it moved or the incident it would have caught, in the ledger above, with the command
that reproduces it. A practice with no measurement is a preference, and preferences belong in a
conversation rather than in a programme.
