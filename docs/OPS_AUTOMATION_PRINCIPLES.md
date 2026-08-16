# Ops automation — principles, requirements, expectations

**What this document is for.** Every automation we build for this business must also work for the
next one. This file says how to build them so that is true, and what "done" means. Read it before
writing any monitor, guard, backup job, or console screen. It is the contract; the individual
programmes (`LAUNCH_OPS_PROGRAM.md`, `COST_PROGRAM.md`, `ADMIN_CONSOLE_PROGRAM.md`) are the work.

**Scope decision, 2026-08-16.** All of this stays in **this repo** for now. We do not split a
package or a second repo yet. Build it so that extracting it later is a copy of two directories,
not a rewrite.

---

## Part 1 — Principles

### P1. The engine is generic. The startup is data.
No automation may contain a fact about this business. Company name, domain, provider names,
thresholds, file paths, alert channels: all of those live in a declaration file. The code reads
the declaration. Dropping the engine into another startup means writing its YAML, nothing else.

The test: grep the automation's source for "mumchimp", "prospector", "stripe", "fly", or any of
our thresholds. A hit is a defect.

### P2. Every automation is three things or it is not finished.
1. **The automation** — code that acts or measures without a person.
2. **The runbook** — what a human does when it goes red, in words, with the exact commands.
3. **The console screen** — the result on one line in the Next.js admin portal.

One or two of the three is not a partial delivery. It is an unmanaged risk with extra steps: an
automation nobody sees is the same as no automation, and a red line with no runbook is a scare.

### P3. Report before fix.
Every sweep, backfill, or repair ships read-only first. It prints what it found and changes
nothing. `--fix` is a second, explicit run. This is not caution for its own sake: the read-only run
is what produces the count that tells us whether the fix is worth building.

### P4. State is a probe, never a sentence.
"Is it working?" is answered by running one command that prints the truth right now. No document,
no memory, no dashboard cache. Any automation must expose that command, and the console must call
it rather than storing a status somebody wrote down.

### P5. No LLM in the loop.
An agent may build an automation. An agent may never be required to run it. Every control has to
work when the agent is unavailable, out of credit, or wrong. If a step needs a model to decide,
that step is not automated yet.

### P6. Fail closed, and say why.
When an automation cannot establish the truth, it says "unknown" and stops. It never guesses green.
An empty result and a failed check are different answers and must never share a code path.

### P7. Alerts name the cause and the first action.
An alert that says something is dead when it was deliberately paused trains the reader to ignore
alerts. Every alert message states what was measured, what the threshold was, and the single first
thing to do. Every "deliberately idle" state is excluded from every streak counter in the same
commit that introduces it.

### P8. Smallest thing that works.
Extend the mechanism that exists before writing a new one. A new module needs a demonstrated reason
the old one cannot serve. Reusability means a small generic core, not a framework.

### P9. One idea per automation.
A script does one job and prints one verdict. Composition happens in the scheduler and the console,
not inside the script. This is what lets another startup take four of our nine automations.

---

## Part 2 — Requirements

Requirements are binding. A pull request that breaks one is rejected regardless of what it fixes.

### R1. Structure
- Generic engines live in `ops/automations/`. One file per automation. No business facts inside.
- Declarations live in `ops/config/<automation>.yaml`. One file per automation. All business facts
  inside, each with a one-line reason it has that value.
- Every engine is runnable as `python -m ops.automations.<name>` and as an import.

### R2. Interface
Every automation supports exactly this shape:

| Flag | Meaning |
|---|---|
| *(none)* | Read-only. Human-readable output. Exit 0 clean, 1 findings, 2 could not establish. |
| `--json` | Same run, machine-readable. This is what the console calls. |
| `--fix` | Acts. Only where a fix is possible and safe. Never the default. |
| `--config PATH` | Which declaration to read. Defaults to `ops/config/<name>.yaml`. |

Exit code 2 is mandatory and distinct: "I could not tell" must never be reported as "clean".

### R3. Output
The `--json` payload always carries: `automation`, `status` (`ok`/`findings`/`unknown`), `checked`
(what was scanned, as a count), `findings` (a list, each with `where` and `what`), `ran_at`, and
`probe` (the exact command a human can re-run). The console renders from that and nothing else.

### R4. Tests
Every automation ships with a test that proves it **fires on the broken state**, not only that it
passes on the clean one. A guard that has never been seen to fail is not known to work.

### R5. Documentation
Every automation ships with a runbook entry in `docs/RUNBOOKS.md`: what it checks, what red means,
what to do, how long the fix takes, and what to do if the fix fails.

### R6. Console
Every automation appears on a console screen as one line: name, status colour, when it last ran,
and either a button that runs the fix or a link to its runbook entry. No automation is complete
while its result is only visible in a terminal.

### R7. No secrets in output
Automations report key names, never key values. This holds in `--json` too, which is served over
HTTP to the console.

### R8. Cheap by default
An automation that runs on a schedule must cost nothing per run beyond CPU. No paid API calls
inside a routine check. Where a paid call is unavoidable, it is a separate, explicitly-invoked
automation with its cost printed in its own output.

---

## Part 3 — Expectations

Expectations are what the founder should be able to rely on once this is built. They are how we
judge whether the programme worked.

### E1. One URL
The founder opens the admin portal and sees every risk as one green or red line. No terminal, no
plist, no agent, no guessing. If a question can only be answered by SSH or by asking Claude, that
is a gap in the programme, not a normal way to work.

### E2. Green means measured today
A green line states when it was measured. "No news" is never green. A check that has not run inside
its own declared interval shows amber and says so.

### E3. Red comes with a next action
Every red line has a button that fixes it, or a runbook link that says exactly what to type. Never
a red line on its own.

### E4. Nothing needs an agent
Every control survives Claude being unavailable. Nothing in the operating loop is blocked on model
credit, model availability, or a model being right.

### E5. Recovery is written and has been tested at least once
Restoring the database, moving hosts, changing DNS, and rotating a key each have a written
procedure that somebody has actually run, with the measured time it took recorded next to it.

### E6. It moves to the next startup in an afternoon
Copy `ops/automations/` and `docs/RUNBOOKS.md`, write new YAML in `ops/config/`, point the console
at it. The measure of success is that no engine file is edited during that move.

---

## Part 4 — What counts as done

An automation is done when all six are true:

1. It runs on a schedule or a trigger, without a person.
2. It has a read-only mode and, where relevant, an explicit `--fix`.
3. Its business facts are in a YAML declaration and its code has none.
4. A test proves it fires on the broken state.
5. It has a runbook entry.
6. It shows one line on the admin portal.

Anything less gets recorded in the relevant programme doc as partial, with the missing item named.

---

## Ledger

| Date | Automation | Engine | Declaration | Runbook | Console | Notes |
|---|---|---|---|---|---|---|
| 2026-08-16 | retired terms | `ops/automations/retired_terms.py` | `ops/config/retired_terms.yaml` | `docs/RUNBOOKS.md` | **pending** | Built out of the Paddle removal: stops a deleted dependency reappearing in code, config, legal copy or operator docs. |
| 2026-08-16 | offsite backup | `ops/automations/offsite_backup.py` | `ops/config/offsite_backup.yaml` | `docs/RUNBOOKS.md` | **pending** | Closes DAT-1. Copies `/data/store.db` and the ASP.NET key ring off the Fly account into R2, opens each copy before it counts, and answers "is there a fresh copy right now?" as a measurement. First run 2026-08-16: the monitor read `STALE … never` on both sources before the fix and `OK` after it. Restore into a fresh machine (E5) is still untested. |
| 2026-08-16 | log rotation | `ops/automations/log_rotation.py` | `ops/config/log_rotation.yaml` | `docs/RUNBOOKS.md` | **pending** | Closes ENG-5. Copy-truncate, never rename, so a daemon's open descriptor keeps working; the test pins the inode across a rotation. First run 2026-08-16 compressed 62.7 MB into 5.5 MB across three logs. Built because an unrotated 25 MB log made a lifetime count read as today's and put a wrong blocker in `LAUNCH_OPS_PROGRAM.md`. |
