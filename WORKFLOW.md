# Prospector — Agent Workflow

## Division of Labour (from AGENTS.md)

```
MANAGER (Claude Opus)              EXECUTOR (MiniMax)
─────────────────────────          ─────────────────────────────
• Write specs + edge cases         • Implement against specs
• Review work in depth             • Generate candidates
• Own documentation                • Run triage
• Truth-critical decisions         • Draft content  
• Adversarial passes               • Fetch passages (search)
• The moat (verdict ruling)        • Bulk execution
  NEVER delegates to executor        NEVER rules a verdict
```

## Two Tools, Two Roles

### Claude Code — Manager / Idea Generator

```bash
cd ~/Documents/code/prospector
claude
```

Used for:
- Generating business ideas to vet
- Writing the master spec (`prospector-master-spec.md`)
- Designing the verification gates (pain_reality, value_durability, etc.)
- Reviewing verdicts and adversarial passes
- Architectural decisions
- Documentation

### MiniMax — Executor / Implementer

Corrected 2026-08-05 (founder). **The live executor set is MiniMax and Claude — nothing else.**
Earlier revisions of this file described an `agy` CLI running Gemini, and named Gemini and
DeepSeek as executors. Both are gone. Do not go looking for that CLI; it is not the path.

MiniMax is dispatched **from inside a Claude session**, not from a second terminal, so there is
no hand-off step and no waiting on a human to run something:

```python
from prospector.operator import MiniMaxOperator   # prospector/operator.py
op = MiniMaxOperator()                            # reads MINIMAX_API_KEY from .env
code = op._raw(system_prompt, user_prompt, 0.2)
```

Two practical notes, both learned the hard way. M3 emits its reasoning inside `<think>…</think>`
**before** its answer, so split on `</think>` and take the tail. And it wraps code in markdown
fences however firmly you ask it not to, so strip those too.

**The pattern that works (proven on the L1 price ladder, 2026-08-05):**

1. **The manager writes the contract first** — the test file — plus any data encoding a
   commercial or truth-critical judgement. On the price ladder that meant the golden matrix in
   `tests/test_pricing.py` and the rung values in `config.yaml`. The executor never picks a
   number that costs money if it is wrong.
2. **The executor writes only the implementation.** Its brief is "make this existing test pass,
   exactly as written; do not propose changes to it."
3. **Acceptance is running the contract.** If a delegated unit cannot pass its test, it comes
   back rather than being patched up in review — otherwise the manager is doing the work anyway
   at the worse price.

That run cost **$0.0032** and passed 82/82 of its scope first time.

**But do not stop at green when the code can reach the money path.** On that same run, manager
review caught a defect the golden matrix structurally could not: an index was clamped in one
place and read unclamped one line later, so a typo in `config.yaml` — a data edit that never
passes through code review or the suite — would have crashed publishing. Green proves the
contract; it does not prove the contract was complete.

Used for:
- Implementing features against written specs
- Generating candidate content
- Running triage at scale
- Drafting documentation
- Bulk search/fetch operations

## The Idea Generation Pipeline

```
1. CLAUDE CODE (Manager)
   "Generate 10 business ideas in the fintech space"
   → Writes candidate specs with edge cases
   → Saves to store/ as input signals
   
2. MINIMAX (Executor)
   "For each candidate in store/, fetch grounding evidence"
   → Runs web searches for each candidate
   → Collects passages, citations
   → Drafts initial analysis
   
3. LUX (Verification)
   "Verify the pipeline output against golden set"
   → Runs verification suite
   → Checks invariants from AGENTS.md
   → Reports PASS/FAIL per candidate
   
4. CLAUDE CODE (Manager Review)
   "Review verdicts, rule on edge cases, publish PASSes"
   → Reads executor output + LUX verification
   → Makes final verdict (PASS/KILL)
   → Publishes to catalogue
```

## Quick Commands

```bash
# Start Claude Code for idea generation
cd ~/Documents/code/prospector && claude

# Delegate an implementation to MiniMax — from INSIDE the Claude session, not a
# second terminal. Write the test first, then hand over only the implementation.
# (see "MiniMax — Executor / Implementer" above)

# Run Prospector pipeline
cd ~/Documents/code/prospector && python -m prospector run

# Verify with LUX
cd ~/Documents/code/lux && npm test
```

## Current State

| Component | Status | Model |
|-----------|--------|-------|
| Claude Code | ✅ Installed v2.1.181 | Claude Opus 4.6 |
| MiniMax executor | ✅ In-session via `MiniMaxOperator` | MiniMax-M3 (`MINIMAX_API_KEY`) |
| Prospector | ✅ Configured | AGENTS.md + CLAUDE.md active |
| LUX | ✅ 72 tests passing | Proof system |
| Hermes | ✅ Running | Telegram + Cron |
