# The three workstreams — index only

> Founder, 2026-08-17: "claude code sloppiness is one stream, hermes agent is another, and
> the whole ops readiness programme also."
>
> This file is an INDEX and nothing else. The first draft of it restated the working-method
> register in full, and there was already one — `LAUNCH_OPS_PROGRAM.md` §9, WM-1 to WM-5.
> Writing a second register is the same defect as losing the first, so the detail was folded
> back into §9 and this page kept to a page.

Each stream names a PROBE: a command that answers "where is this?". A status written in prose
drifts; a status printed by a command cannot.

| # | Stream | Register | Probe | Tasks |
|---|--------|----------|-------|-------|
| A | **Claude Code ways of working** | `LAUNCH_OPS_PROGRAM.md` §9 (WM-1…WM-7) | `python3 ~/.hermes/scripts/complaint_ledger.py --print` | #10 |
| B | **Hermes agent** | `~/.hermes/capabilities.json` | the `capabilities` panel, or `python3 ~/.hermes/scripts/capability_audit.py` (slow) | #5, #6, #7 |
| C | **Ops readiness programme** | `LAUNCH_OPS_PROGRAM.md` §1 and §4 | `.venv/bin/python scripts/ops_status.py` | #11 |

`ESTATE_QUIRKS.md` sits beside these three. It is not a fourth stream. It is the register of
platform behaviours that made a healthy thing look broken, so that the next diagnosis does not
start from scratch. Read it before believing any red line.

The Hermes agent can be across all three and should be. A and C are both things it can grade
on a schedule and report unasked. A workstream nobody probes goes dark exactly like a
capability does.

## Where each one stood on 2026-08-17

- **A** — of seven rails, two are enforced by hooks (`hang-guard.py`, `memory-loop.py`) and
  neither has ever been raised again as a complaint. The rest are instruction-only in the
  global `CLAUDE.md`, and every one of them has been raised more than once. That is the whole
  argument for moving a rail from instruction to enforcement.
- **B** — 34 of 42 capabilities producing, 8 dark; gate `GATE: FAIL` at 20 passed / 4 failed,
  where most remaining failures assert panels that were never built.
- **C** — `ops_status.py` grades 44 ids against `origin/main`, never the working tree. It has
  already caught two claims of "done" that were true only in an unmerged PR.

## How a complaint becomes work

1. The founder says the way we work is wrong.
2. `reflect.py` finds it in the transcripts; `complaint_ledger.py` writes it down so it
   survives the session.
3. It gets a WM number in §9 and a task id.
4. It closes when a rail enforces it, or when the founder says the instruction is enough.

A complaint that only ever produced an apology is still open, whatever the reply said.
