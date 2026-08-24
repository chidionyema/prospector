---
name: model-routing
description: Which model to run, why, and what it costs. Load when choosing or changing the session model, when picking a model for a subagent, when asked why a session is expensive, or when the pi-bridge executor comes up. The operative rules are in CLAUDE.md; this is the measured history behind them.
---

# Model routing — the measurements behind the rule

Moved out of the global CLAUDE.md on 2026-08-19. It was 3,809 characters of reference
material re-billed on every turn of every session in every project, to answer a question
that comes up once at session start. Anthropic names the over-specified CLAUDE.md as the
first failure pattern: rules get lost in the noise. The rule stayed; the evidence moved here.


**On disk right now the default is Opus** — measured 2026-08-17, `~/.claude/settings.json:17` reads
`"model": "opus[1m]"`. This file said `"sonnet"` (founder decision 2026-08-06) and that was wrong:
either the decision was never written to disk or it was reverted. **Do not trust this line; run
`grep -n '"model"' ~/.claude/settings.json`.** If Sonnet is still what the founder wants as the
default, that one-word edit is outstanding and worth a flat 40% cut on every rate.
Opus and Fable are the escalations, chosen at session start.
Verify the live answer with
`python3 ~/.claude/scripts/token-audit.py -Users-chidionyema --detail <session>` (the `model` column is
per-request truth). There is **no per-directory or per-project override** — settings.json and `/model`
are the only controls, and **settings.json is read ONCE at process start, so `/clear` does NOT apply a
model change; only quitting and relaunching does** (memory:
`settings-json-is-read-once-at-process-start.md`).

Why Sonnet: Opus→Sonnet is exactly **0.6x on every rate** = a flat 40% cut with no behaviour change,
and an A/B on identical prompts measured 0.601x steady-state. Use plain `sonnet`, **not** `sonnet[1m]`
— the 1M variant carries a long-context premium above 200K and `context-guard-hook.py:30-36` already
hard-stops at `RESIDENT_HARD = 140_000`. (The `[1m]`-is-free finding is an **Opus** fact; do not carry
it to Sonnet.) Full measurements: memory `delegation-is-a-4-percent-lever-model-default-is-40.md`.

- **Sonnet 5 — the default brain.** Normal engineering: integration, backend, web, deploys, refactors,
  test work, reviews of other agents' output.
- **Opus 5 — escalate at session START** (mid-session switches invalidate the prompt cache): money-rail
  / identity / contract / migration design and implementation, production incidents, and final review
  of money-adjacent diffs. `/model opus[1m]` — the founder fence, now protected by DISCIPLINE AT
  SESSION START, not by config. When the heavy work ends, take the /clear safe point; do not run
  routine follow-ups on Opus.
- **Fable 5 — war-rooms only.** `/model claude-fable-5`, the rarest escalation.
- **Haiku 4.5 — ALL recon.** Pass `model: "haiku"` on every Explore / search-style subagent.
- **Do NOT set `CLAUDE_CODE_SUBAGENT_MODEL`.** It is FIRST in the subagent resolution order — ABOVE the
  per-invocation `model:` parameter — so pinning it to haiku makes escalating a single subagent
  impossible. Leave it unset; subagents inherit Sonnet and per-call `model:` still works.
- **Delegation is a SMALL lever — do not overrate it.** Read-only turns are 5.5% of turns / 4.7% of
  spend. Delegating recon is right, but its ceiling is ~2-4%. Batching and the default model are the
  headline.
- **The cheap dev-work executor EXISTS**: `~/.claude/mcp/pi_bridge.py` shells out to `pi -p -ne`
  (MiniMax-M3) from a self-contained plan and returns a summary + diffstat, while Claude plans and
  verifies in-session. It must be two processes because `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`
  replace the WHOLE session brain including verification. Usage is passive — prompt Claude Code as
  normal, never invoke `pi` yourself. Money/identity/contract/migrations never leave Claude; the bridge
  enforces that fence in the server, not a prompt. Traps and docs: memory
  `pi-bridge-headless-executor.md`, `~/.claude/mcp/README-pi-bridge.md`. (Prospector's own `minimax`
  config references are a SEPARATE thing — the candidate pipeline, none of which writes code.)
- The quality floor stands: never do the hard reasoning itself on a smaller model to save tokens — when
  in doubt on money/identity, escalate. Savings come from defaults and routing.

