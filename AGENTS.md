<!-- Governance lives in git. Precedence: lower law number wins. Full text: docs/AGENT-GUIDE.md -->

# The laws

Eighteen rules, in priority order. When two laws want different things, the lower number wins.
Every law was paid for by a real incident. Incident text: `~/.claude/LAWS-INCIDENTS.md`.

Full law narratives: **docs/AGENT-GUIDE.md § "Law text (full narratives)"**

| # | Law | Fires |
|---|-----|-------|
| 1 | Put the fire out first | while anything is broken |
| 2 | Proof before action | before every change to the world |
| 3 | Never make the same mistake twice | before writing any test, script, workflow or guard |
| 4 | Think it through before you touch it | before every change to the world |
| 5 | Unblock yourself | before handing anything back to the founder |
| 6 | Root cause, and the class of mistake | after the thing works again, never during |
| 7 | Refresh on main before you ask for review | before pushing a branch anyone else will read |
| 8 | Fix the trap where you found it | the moment you trip over a defect |
| 9 | Stay on the job | continuously; it bounds every law above |
| 10 | Say it once, on the board | when you learn something other sessions need |
| 11 | Never decide alone what you cannot undo alone | while a critical decision is still a plan |
| 12 | Root out a risk to the pipeline, do not narrate it | the moment shipping is at risk |
| 13 | Hold the platform and the stack at once | every turn, before you report |
| 14 | Take the cost or speed win when you find one | when a measurement shows a cheaper way |
| 15 | Evidence must converge from two angles | before you call anything proven |
| 16 | Leave a path back when you drop something | the moment you park or switch away |
| 17 | Prove it is operational before you say it is done | before the word DONE reaches the founder |
| 18 | Every founder request is a tracked item | the moment he asks for anything |

---

# THE FOUR HARD RULES

Full text: **docs/AGENT-GUIDE.md § "The four hard rules (full text)"**

1. **Verification before assertion.** No status stated unless the exact command output proving it is in the same turn.
2. **Zero speculative numbers.** No timings or counts from memory; cite only fresh reproducible output.
3. **Strict pre-work lookup.** Search branch and commit history before writing any new script or fix.
4. **Stop fighting the harness guards.** Never trigger IDLE GUARD collisions; do next independent work instead.

---

# How to work

Full text: **docs/AGENT-GUIDE.md § "How to work"** (reply format, plain English, proving a claim,
smallest diff, context discipline, long-command discipline, session hygiene, model routing, state probes).

Full compact instructions: **docs/AGENT-GUIDE.md § "Compact instructions"**

---

# Estate-wide rules & Empirical Proof Rule

Loaded automatically from `~/AGENTS.md` and `~/.claude/CLAUDE.md` at every session start. Not repeated here.
Includes: Flux GitOps deploy rule, multi-arch build requirement (R24), empirical proof rule (2026-09-05).

---

# The Prospector contract

Full text: **docs/AGENT-GUIDE.md § "The Prospector contract"**

Short form:
- **Manager (Claude/Opus):** specs, review, truth-critical calls, documentation.
- **Executor (MiniMax):** implements against a written spec. Never rules a verdict.
- **Founder fence:** money, identity, contracts, migrations, moat verdict ruling stay with the manager.

Orient in this order on session start:
1. This file (`AGENTS.md`)
2. `~/.claude/projects/<slug>/checkpoints/LATEST.md`
3. `store_platform/OPERATIONS.md` (before touching the live store)
4. `~/.claude/projects/<slug>/memory/MEMORY.md`
5. `CLAUDE.md`
6. Source-of-truth files (§4 of the contract)

Two maps: [`docs/ESTATE_MAP.md`](docs/ESTATE_MAP.md) (factual spine) and [`docs/personas/`](docs/personas/README.md) (per-seat audits).

---

# The engine's rules (summary)

Full text: **docs/AGENT-GUIDE.md § "Prospector engine rules (full text)"**  
Architecture module map: **docs/AGENT-GUIDE.md § "Architecture module map"**  
Key constraints: **docs/AGENT-GUIDE.md § "Key constraints"**  
Production + worktrees: **docs/AGENT-GUIDE.md § "Where production runs and how to work in a worktree"**

| Rule | One line |
|------|----------|
| Source-or-die | Every claim cites a retrievable source or is marked `unverifiable`. |
| Verdict-from-retrieval-only | Model rules only from fetched passages. Silence → `unverifiable`. |
| Universal filter | Same six checks every idea, same bar; ambition lane changes the floor, not the discipline. |
| Kill-fast | Cheapest decisive gate first; stop at the first hard fail. |
| KILL is first-class | Render a dossier for every KILL. |
| Publish only on PASS | A KILL blocks publication entirely. |
| Config not code | Who may rule a verdict is `config.yaml moat_primary:`, not a code patch. |
| MiniMax leads | `operator:` and `moat_primary:` both `[minimax, claude_cli]`. Do not revert on one failing run. |
| Bounded batches | 120 candidates/day ceiling; scheduler only behind spend cap and `PAUSE` kill switch. |
| Gate on rate not stock | `gate_generation_on_grounding` suppresses only while retrieval is degraded, then self-clears. |
| Repo is the system | No behaviour lives only in a console or provider account. Fresh clone + env = whole engine. |

## Read these docs, do not re-derive them

| Doc | What it answers |
|---|---|
| `RUN.md` | The eight steps every run executes. |
| `docs/ARCHITECTURE_SECURITY_BASELINE.md` | Measured state; re-measure, never quote from memory. |
| `docs/WAYS_OF_WORKING.md` | 25 rules, each a named repeated failure. |
| `docs/PLATFORM_MANIFESTO.md` | Ten platform laws, portability targets and drills. |
| `docs/decisions/` | Settled decisions with evidence (ADRs 0002, 0004–0012). |
| `docs/ENGINE_ARCHITECTURE.md` | Engine design 2026-08-22, fleshed out and measured. |
| `docs/CI_DEBUG_RUNBOOK.md` | Symptom → command for any red gate. Read before acting on red. |
| `docs/INCIDENT_PROCESS.md` | Fix + sweep + mechanism + grade. |
| `docs/COST_PROGRAM.md` | All cost work and measurements. |
| `docs/GRAPHIFY_ENFORCEMENT_SPEC.md` | Estate-wide graph freshness. |
| `docs/AGENT_PRACTICE_PROGRAM.md` | How Claude sessions work here; probes for hooks and state. |
| `docs/SITE_SPEC_PROGRAM.md` | mumchimp.com design/UX/copy spec. |
| `docs/PACK_NARRATIVE_PROGRAM.md` | Buyer-facing pack spec; renderers; what is deliberately OFF. |
| `docs/ENGINE_MIGRATION_PROGRAM.md` | Where the engine runs and why it moved. |
| `docs/MIGRATION_AND_DR_PROGRAM.md` | Platform automation, DR, portability — §10 target + §11 requirements. |
| `docs/MODEL_PINNING_PROGRAM.md` | Model pins per brain; probe that proves a pin arrived. |

**Ask the graph before grepping.** `graphify query "<question>" --budget 2000` is a local BFS over
`graphify-out/graph.json`, zero tokens of inference. Every node is a **lead to verify at a `file:line`**.

---

<!-- growmos:start — managed by `growmos integrate`; edits inside this block will be overwritten -->
## growmos — living knowledge graph (shared memory for humans + agents)

This repository keeps a knowledge graph in `.growmos/` (entities, typed relations, provenance,
profiles, a journal). It is the shared world model that survives context windows. Treat it as
memory you read at the start of work and write to as you develop. Zero-config commands:

1. **Session start** — run `growmos context` (a compact brief: hubs, health, pending work, latest journal).
   If it lists pending work, run the `growmos next` → apply loop (step 4) right away, without being asked —
   it is quick, needs no permission, and is how the graph stays alive.
2. **Before cross-cutting questions** ("what depends on X?", "why was Y decided?") — run
   `growmos query "<question>"`; answer from the returned subgraph and cite edge ids.
3. **When you learn or decide something durable** (new component, architectural decision, ownership,
   dependency, gotcha) — write it back immediately:
   - `growmos remember "<Name>" --type <TYPE> --desc "<one grounded sentence>"`
   - `growmos link "<A>" "<predicate>" "<B>"`   (short verb phrase predicates: "depends on", "replaces")
   - `growmos journal "<what changed and why>"`
4. **Feed the organism** — run `growmos next`. It hands you a *task packet* (extraction / resolution /
   profile / gold set / review) with the exact prompt, the JSON shape, and the `growmos apply …` command.
   Do the judgment work yourself, write the JSON, apply it. Repeat until `growmos next` says the graph is
   up to date — that loop covers everything, including the evaluation gold set and the periodic node review.
   If it reports the daily extraction cap, run `growmos next --force` (the cap only guards unattended runs).
   Never invent facts not in the source; every relation must connect two extracted entities.
5. **Before claiming facts about the repo in a summary/report** — `growmos check "<claim text>"` grounds
   your claims against edges with provenance (evaluator–optimizer loop).
6. **Session end** — `growmos journal "<summary of the session>"` so the next session picks up here.

Store files are plain JSONL under `.growmos/` — commit them with your code. Do not hand-edit
`entities.jsonl`/`relations.jsonl` (use the CLI); prompts in `.growmos/prompts/` are yours to tune.
More: `growmos --help`, docs at https://github.com/codician-team/growmos.
<!-- growmos:end -->
