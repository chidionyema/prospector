# The incident process

> Founder, 2026-08-18: "we don't have a process and we should. self healing and self governing
> with ops visibility. and self improving. by having incident reports, root causes, never
> repeating mistakes, aim to kill issues first time, second order effects... classes of mistakes.
> most platform issues are recurring."

Most of what breaks here has broken before in a different costume. The estate already knows this:
the agent tenets say "never make the same mistake twice" and "follow the root cause chain to the
end". Both were words. This file is the same two sentences made mechanical, and
`scripts/incident.py` is the machine.

## What an incident is

Anything that cost time or money and was not supposed to happen. A production failure, a wrong
number reported to the founder, a guard that did not guard, a doc that sent someone to a path that
does not exist. Severity decides urgency; it does not decide whether a record gets written.

## The three orders

A fix at the first order is not a fix. It is a patch on one instance of a shape that is still
legal everywhere else in the estate.

**First order — the instance.** What broke, and the receipt: a `file:line`, command output, or a
failing test that now passes. This is where we used to stop, which is why things came back.

**Second order — the siblings.** Every other place with the same shape, found by a sweep whose
command is recorded, and whose count is recorded. This is not optional and it is not a judgement
call: the sweep runs, and its result is a number in the record, including when that number is zero.

Worked example, 2026-08-17. Four constants derived a store path from `__file__`. All four were
fixed and the rule was written down. A fifth resolver, `paths.store_root()`, was never swept for.
On 2026-08-18 the live Fly engine was found writing listing files into `/app/store` — the image
layer, erased by every deploy — with eight files already stranded. The rule existed. The sweep did
not. That is the entire cost of skipping the second order.

**Third order — the class.** A mechanism that makes the shape impossible. In this order, and the
order matters:

1. **Heal.** The system detects and repairs it without a human. Always preferred.
2. **Refuse.** A machine blocks it at the moment it is attempted: a `PreToolUse` guard, a CI gate,
   a pre-commit check.
3. **Test.** A test fails if the shape returns.
4. **Memory file.** Last, and only where the failure cannot recur mechanically. A memory file is
   the floor, not the answer.

## The fourth field, which is the one that rots

**Grade.** How many times the signature occurred before the mechanism landed, and how many after.
The record names the signature, the date the mechanism landed, and the window. Zero occurrences
across the window closes the incident; anything else reopens it.

Without this the loop is not a loop. A mechanism nobody grades is a belief, and this estate has
shipped beliefs before: `docs/doc_lint_baseline.json` carries 27 entries while
`scripts/doc_lint.py` reports 184 findings, so 184 known-rotten references have been permanently
green in CI. The gate exists. The grade did not.

## Producer and consumer

The same shape the engine already uses for candidates: generation produces, the drain consumes,
and neither waits on the other.

**Producer.** `~/.claude/scripts/reflect.py`, already scheduled every four hours under
`com.chidionyema.reflect`, already reads every transcript in `~/.claude/projects/`. It emits
incident *candidates*: stops, complaints, and — added here — friction, meaning the operations that
take longest, repeat most, and cost most per outcome.

**Consumer.** A separate pass that takes a candidate and does the work: chases the cause chain,
runs the sibling sweep, picks the mechanism tier, opens the ticket, and records the grade. Nothing
about a candidate is trusted until a consumer has verified it at a `file:line`.

Decoupling them is the point. Detection must not stall waiting for a fix, and a fix must not be
invented by whatever was in context when the failure happened.

## The ticket

Every incident without a live third-order mechanism opens a GitHub issue labelled `incident`. This
is not bookkeeping. Measured on 2026-08-18: the repo had **one** open issue in total, while 55
items of work were tracked nowhere a second session could see them. Work that exists only in one
session's context is work that gets done twice or not at all.

## Ops visibility

`scripts/incident.py --json` writes `store/ops/incidents.json`, read by the ops console, alongside
the `method_metrics.json` that `reflect.py` already writes. The console shows: open incidents,
incidents whose mechanism is unproven, and the friction table with its recommendations.

## Self-improvement

The producer also ranks, per month:

- **Slow** — the operations with the highest wall-clock cost.
- **Repeated** — the tool signatures that recur most across sessions, which is where automation
  pays.
- **Expensive** — output tokens per tool call, already tracked by `reflect.py`.

Each row carries a recommendation, and a recommendation that is acted on becomes an incident
record with a grade like any other, so "we improved it" has a number behind it or it did not
happen.

## What this does not claim

It does not make the system error-free. It makes *repeat* errors rare, over time, because each
incident retires a class rather than an instance and classes are finite. New classes keep arriving.

The grading stage is the one that will rot first, because it is the only stage with no immediate
payoff. That is why it is a required field enforced by `scripts/incident.py check` in CI, and not
a habit.

## Commands

```bash
.venv/bin/python scripts/incident.py list          # every record, by state
.venv/bin/python scripts/incident.py check         # CI gate: required fields, overdue grades
.venv/bin/python scripts/incident.py friction      # slow, repeated, expensive, with recommendations
.venv/bin/python scripts/incident.py ticket        # open issues for incidents with no live mechanism
.venv/bin/python scripts/incident.py --json        # the whole thing, for the ops console
```

## Where this connects

| Read this | For |
|---|---|
| [`RUNBOOKS.md`](RUNBOOKS.md) | what to do while it is red. A runbook entry that keeps getting used is an incident nobody raised. |
| [`WAYS_OF_WORKING.md`](WAYS_OF_WORKING.md) | the same loop for complaints, which arrive in words instead of as broken things. |
| [`ESTATE_MAP.md`](ESTATE_MAP.md) | which component broke, where its state lives, and what sits next to it — the map you sweep with. |
| [`ESTATE_QUIRKS.md`](ESTATE_QUIRKS.md) | platform behaviour that makes a healthy thing look broken. Read it before opening a record. |
| [`incidents/`](incidents/) | the records themselves. |
