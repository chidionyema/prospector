# Prospector — Agent Workflow

## Division of Labour (from AGENTS.md)

```
MANAGER (Claude Opus)              EXECUTORS (MiniMax / DeepSeek)
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

### AGY CLI — Executor / Implementer

```bash
cd ~/Documents/code/prospector
agy --model "Gemini 3.5 Flash (High)"
```

AGY (`~/.local/bin/agy`, v1.0.9) runs Gemini on the working OAuth key; `agy models` lists
the available Gemini and Claude tiers. NOT Aider — that was a misread of "agy cli"; no API
key is stored in-repo.

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
   
2. AGY + GEMINI (Executor)  
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

# Start AGY for implementation
cd ~/Documents/code/prospector && agy --model "Gemini 3.5 Flash (High)"

# Run Prospector pipeline
cd ~/Documents/code/prospector && python -m prospector run

# Verify with LUX
cd ~/Documents/code/lux && npm test
```

## Current State

| Component | Status | Model |
|-----------|--------|-------|
| Claude Code | ✅ Installed v2.1.181 | Claude Opus 4.6 |
| AGY CLI | ✅ Installed v1.0.9 | Gemini (OAuth key) |
| Prospector | ✅ Configured | AGENTS.md + CLAUDE.md active |
| LUX | ✅ 72 tests passing | Proof system |
| Hermes | ✅ Running | Telegram + Cron |
