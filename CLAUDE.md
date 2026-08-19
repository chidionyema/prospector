# LAW 0 — ROOT CAUSE, AND THE CLASS OF MISTAKE

Founder directive 2026-08-19: "our rules root cause and classes of mistakes needs to headline
claude.md file". Everything below this block is detail. This is the rule that outranks it.

**A fix that stops one instance is not a fix.** Fix what broke, then ask what let it break, and
keep asking until the answer names a CLASS of failure rather than one bug. Stop only when the
next link is a decision a person must make, and say so plainly. Reporting the first link and
stopping is the failure this law exists to kill.

**Then close the class mechanically, in this order, every time:**
1. **Self-healing** — can the system correct itself with no agent involved?
2. **A guard** — can a machine REFUSE the mistake? A PreToolUse hook, a test, a CI job, a gate.
3. **A memory file** — only when 1 and 2 are impossible, or already in place.

A memory file on its own is the floor, never the answer. A documented trap is not a guarded trap
(memory `a-documented-trap-is-not-a-guarded-trap.md`). If the failure can recur mechanically, an
incident is not closed until something fails when it recurs.

**The guard must reach EVERY agent, not this session.** Sessions share this estate and cannot see
each other. Six agents will independently find the same defect and fix it six times unless the
refusal lives somewhere all six pass through: a hook in `~/.claude/scripts/`, a test in the suite,
a CI job, or the repo's own gate. "I will remember" is not a mechanism. Neither is a handoff.

**Worked example — the one that produced this law.** 2026-08-19: 22 pull requests open, nothing
merging, every agent grinding the same ground. The chain: no PR had auto-merge enabled → native
auto-merge cannot be enabled here at all (`403 Upgrade to GitHub Pro` on both
`/branches/main/protection` and `/rulesets`) → `.github/workflows/automerge.yml` is the substitute
and only merges a CI run that CONCLUDES green → `.github/workflows/ci.yml` sets
`cancel-in-progress` for every ref that is not main → so every agent push killed the in-flight run
that was about to merge another agent's work. Measured: 7 of the last 60 CI runs succeeded, 16
were cancelled. The class is **an agent action that silently destroys another agent's in-flight
work**. It was closed with a guard, not a note: `~/.claude/scripts/push-pr-fence.py` now refuses a
push while that branch's CI is live.

---

# Prospector Operating Rules

**This file is WHAT PROSPECTOR IS: its rules, its topology, its gates.** `~/.claude/CLAUDE.md` is
HOW to work in any repo, and the two never overlap. Nothing generic belongs here; nothing about
this project belongs there. `~/.claude/scripts/scope-guard.py` refuses a write that crosses the
line (escape marker `SCOPE-LEAK-OK`).

**This file carries the RULE. The incident that produced it is in memory, and the detail is in
docs.** Every cut below names where its detail went. Verbatim pre-cut text:
`reference-project-claude-md-full-2026-08-19.md` (32,542 chars, 2026-08-19), and
`reference-project-claude-md-full-2026-08-06.md` before that.

## Read these, do not re-derive them

| Doc | What it answers |
|---|---|
| `RUN.md` | The eight steps every run executes. The procedure IS the guarantee. |
| `docs/ARCHITECTURE_SECURITY_BASELINE.md` | Measured state: what the system is, what is tested, the security findings, where the mud is. **Re-measure, never quote from memory.** |
| `docs/WAYS_OF_WORKING.md` | 25 rules, each a named repeated failure. Part 7 marks which are machine-enforced. `scripts/session_check.py` enforces the first five. |
| `docs/PLATFORM_MANIFESTO.md` | The constitution: ten platform laws, portability targets and drills, the automation audit. Read before proposing anything structural. |
| `docs/decisions/` | Settled decisions with the evidence. ADR 0002: the engine stays Python; bug rate is fixed by standards S1–S6, not a rewrite. |
| `docs/INCIDENT_PROCESS.md` | When something breaks, the fix is half the job. Sweep the siblings, land a mechanism, grade it. Records `docs/incidents/*.json`; gate `.venv/bin/python scripts/incident.py check`; `scripts/incident.py friction`. |
| `docs/COST_PROGRAM.md` | All cost work and all cost measurements. Append there, never here. |
| `docs/GRAPHIFY_ENFORCEMENT_SPEC.md` | Estate-wide graph freshness. §7 is the operating manual. |
| `docs/AGENT_PRACTICE_PROGRAM.md` | How Claude sessions work here: what an agent is told at the start, what stops it doing the wrong thing, and the command that proves each is still live. Read before changing a hook, the state probe or the process audit. |
| `docs/SITE_SPEC_PROGRAM.md` | The mumchimp.com design/UX/copy spec and its live status ledger. Read before touching the storefront. |
| `docs/PACK_NARRATIVE_PROGRAM.md` | What the buyer reads: the 14-section order, the eight deterministic renderers and why they stay model-free, the three weak gates, the switches deliberately OFF. Read before touching a `pack_*.py` renderer, the pack linter, or `tools/backfill_bundle_html.py`. |
| `docs/ENGINE_MIGRATION_PROGRAM.md` | Where the engine runs and why it moved. |

**Ask the graph before grepping.** `~/.claude/skills/graphify/SKILL.md` owns it (`/graphify`
invokes the skill). `graphify query "<question>" --budget 2000` is a local BFS over
`graphify-out/graph.json`, zero tokens of inference. Every node it returns is a **lead to verify at
a `file:line`**, never proof. Freshness is automatic (four triggers); `python3
scripts/graphify_sweep.py --check-hooks` exits 0 when enforcement is wired.

## The engine's rules

**Source-or-die.** Every factual claim and quantitative figure cites a retrievable source or is
marked `unverifiable`. No unsourced numbers ship, ever.

**Verdict-from-retrieval-only.** The model rules solely from passages it actually fetched. No prior
knowledge. Silence (no matching passage) → `unverifiable`, never `supported`.

**The filter is universal.** The same six checks (pain_reality, value_durability, incumbency,
payer_solvency, distribution, legality) apply to any business, any sector, any scale, same bar.

**Kill-fast.** Stop at the first hard fail. Cheapest decisive gate first; never spend research
budget on an idea already dead.

**A KILL with a cited reason is first-class.** Render a dossier for every KILL. The kill log is the
receipt that the filter is real and grounded.

**Publish only on PASS.** A KILL blocks publication entirely.

**Write every run to `store/`.** Input, all verdicts and sources, the kill gate, cost, timing.

**Who may rule a verdict is CONFIG, not code.** Grounding chain `[ddg, exa, claude_cli]`
(`config.yaml retrieval.provider`). Verdicts are ruled FINALLY only by `config.yaml moat_primary:`
(read via `operator.moat_primary()`; blank ⇒ `operator.MOAT_PRIMARY_DEFAULT`;
`PROSPECTOR_MOAT_PRIMARY` overrides one process). Promotion is that line plus the golden gate,
never a patch. Anything outside that set which rules is stamped `provisional`
(`is_provisional_provider`, `operator.py:1451`), never publishes on PASS (`run.py:864`), and is
auto re-vetted.

**MiniMax leads and is trusted; claude_cli is the fallback** (founder: "ship with MiniMax running
the whole show and claude and fallback"). Live on disk: `operator:` and `moat_primary:` both
`[minimax, claude_cli]`. It was promoted on receipts — three consecutive golden runs at
discrimination 1.00 (9/9) once `verify._calc_confidence` was fixed. **Do NOT revert to a
claude-led roster on one failing run; measure the scorer first**
(memory `feedback-minimax-stays-do-not-revert.md`). DeepSeek is non-critical generation and triage
ONLY. Removed tiers: `claude` API and `standardcompute` (2026-08-15), `cursor_cli` (2026-08-06),
Gemini grounding — `_build_operator` raises `ValueError` on a removed name so a stale config fails
loudly at startup instead of silently building a shorter chain.

**Run bounded batches inside the usage allowance.** `config.yaml candidates_per_signal` (20),
`schedule.batch_size` (15). Generation may run continuously and unattended (founder decision
2026-06-20: no human in the loop) via `prospector/scheduler/` — but ONLY behind the two automated
rails that replace human supervision: the daily spend ceiling (`spend.daily_cap_usd`, read from
`store/prospector.jsonl`) and the filesystem kill switch (`store/scheduler/PAUSE`). Unattended
generation without them is forbidden.

**Generation must not outrun its own drain.** `PAUSE` halts the ENTIRE tick, generation and re-vet
drain together, because a rail with exceptions is not a rail. Two half-stops leave the drain
running: `store/scheduler/PAUSE_GENERATION` (operator) and `schedule.backlog_cap` (automatic,
**default 0 = off**; above the cap a tick drains at `drain_only_resume_per_tick`, defaulting to
`batch_size`, on a `drain_only_interval_s` cadence clamped never to exceed the generation
interval, and it self-releases under the cap).

**Gate on the RATE, not the stock** (founder decision 2026-08-06). A stock brake has unbounded
memory: one outage suppresses generation indefinitely. `schedule.gate_generation_on_grounding`
(default on) runs one bounded live search per tick and suppresses generation only while retrieval
is ACTUALLY degraded, then self-clears. `run.drainable()` is the single definition of "backlog";
when the count fails it returns `None`, never `0`, so generation stops rather than being waved
through. **Generation volume does not create backlog rows; failed retrieval does.**
Memory: `gate-on-the-rate-not-the-stock.md`.

**Run it wherever the business is safest** — REPLACES the old "no hosted service" rule (founder
directive 2026-08-18: *"forget about CLAUDE.md, that was in the past, this is a commercial business
running off a laptop"*). Hosted inference and hosted compute are ALLOWED. What survives is the part
that was load-bearing: **the repo stays the complete system** — no behaviour lives only in a
console, a dashboard or a provider account, and a fresh clone plus an env file runs the whole
engine.

## Architecture

Full measured map: `docs/ARCHITECTURE_SECURITY_BASELINE.md`. The modules, and the one thing about
each that a change is likely to break:

- **config.py** — every knob. No hardcoded values. `config.store_root()` is the ONLY store-path resolver.
- **models.py** — Candidate, Verdict, Claim, Dossier, Pack. The contracts.
- **operator.py** — the swappable brain and the trusted/provisional fence (see the roster rules above).
- **errors.py / health.py** — failover classifier and persisted dead marks. `classify_exhaustion` splits TRANSIENT backpressure (429/503/529, `overloaded_error`, 60s) from PERMANENT exhaustion (402, credit balance, any spend/usage allowance, 1h); PERMANENT wins ties. **HTTP codes match on WORD BOUNDARIES** — a bare substring lets a request id bench a live brain (memory `substring-http-codes-bench-a-live-brain.md`). `_claim_probe` makes a mark half-open so exactly one caller machine-wide re-probes.
- **retrieval.py** — grounding chain, caching, per-provider circuit breakers; fixtures for offline test.
- **prompts.py** — generate, prescreen, query_gen, verdict, adversarial, score, content_gen, claim_check, price_comparables.
- **generate.py / dedup.py / prescreen.py** — divergent candidates from signals; near-duplicate drop by string similarity (`difflib` + Jaccard, NOT embeddings — `prescreen_prefilter.py` is embedding-based and wired off); first cheap triage gate.
- **verify.py** — the moat: query gen → fetch → verdict on a moat_primary brain, kill-fast. Raises `ProviderExhaustedError` when the moat is down so callers DEFER and resume.
- **price_comparables.py** — the seventh check, evidence-only. It can NEVER kill (barred in `kill_filter.is_hard_fail` and in verify's run order): "no price page on the open web" is a fact about the web, not the idea. Every anchor appears literally in the passage it cites; FX is config-declared, never inferred.
- **pricing.py** — the L1 ladder: segment (ambition_tier × market) → a rung in `config.yaml listing.pricing`, never a continuous number.
- **kill_filter.py** — deterministic gates; KILL or PASS. **score.py** — six axes, composite = Σ(score × weight).
- **dossier.py / store.py / publish/publish.py** — artifacts, catalogue state, listing JSON on PASS. (`prospector/publish.py` is a dead 0-byte stub; the real one is top-level `publish/`.)
- **bridge.py** — the money rail's entry: one `PriceDecision` mints the provider Price object AND writes the catalogue row, so the two cannot drift. A drift charges the buyer and then fails the fulfilment fence.
- **run.py** — CLI entry, orchestrates RUN.md. `_noncritical_order(cfg)` builds the generation/prescreen/score chain from `config.yaml noncritical_operator:`. DEFER + `vet --resume` on moat exhaustion; failed signals to `signals/pending/` for `generate --resume`.

## Key constraints

- **Deterministic on config.** Swapping operators requires no code change, only `config.yaml`.
- **Every verdict is grounded in cited sources.** A KILL is evidence the operator can see, not the model's opinion.
- **Golden-set regression gates all changes.** Part 13B acceptance tests block ship on any mixed-sector discrimination regression.
- **Creativity lives in generation; constraint lives in verification.** Nothing is killed at generation time.
- **Two loops never merge.** Sales metrics tune what to offer; truth metrics veto what may ship. Demand never overrides truth.
- **Non-critical chains never rule a verdict.** They run behind their own health file and breaker. claude_cli is BARRED from that chain (founder 2026-08-14), enforced where the chain is BUILT (`_NONCRITICAL_FORBIDDEN`). If every tier fails it raises `ProviderExhaustedError` — it never promotes itself into ruling. The rule is about the ROSTER, not a brand: a test that hardcodes "minimax = untrusted" pins the roster, not the fence.
- **A dead brain must leave a trace.** A fallback chain that works hides its own degradation. Permanence is classified by ONE shared tested function (`errors.looks_exhausted`) used by every metered adapter; only a `ProviderExhaustedError` reaches `_health.mark_exhausted`, so a failure the classifier misses is retried forever.
- **An exception is never evidence; a failed call DEFERS.** A verdict call that raises returns `retrieval_failed=True` (`verify.py:365`), firing the DEFER gate (`verify.py:693`) instead of contributing an `unverifiable` check to the kill gates. `store/dossiers/2102bacc6dd75cf9.kill.json` is the counter-example: a candidate killed by our own outage, in a dossier that reads as fully reasoned.
- **Moat exhaustion = PROVISIONAL first, DEFER only when the tail is down too** (founder 2026-08-08). Provisional costs 2x to reach the answer a DEFER reaches once — an accepted cost, because a DEFER stops the line. `vet --resume` finalises both populations on recovery.
- **The daemon must not mint work NO brain can finish.** `_moat_blind_reason` (`scheduler/run_scheduled.py:465`) skips a tick only when EVERY verdict brain, trusted or provisional, carries a live dead mark; it is then counted unproductive so the 5m/10m/20m retry applies. It reads raw `dead_until`, never `is_dead`, so a bookkeeping check cannot consume the half-open probe slot a real call should get.
- **The DRAIN stays trusted-only, and that asymmetry is deliberate.** Re-vetting a `provisional` row on a provisional brain re-stamps it `provisional`: the row does not move and the money is spent (measured 2026-08-06: provisional −14 / defer +13 in 30 minutes, net −1). Generation may run into a provisional tail; the drain may not. One shared function, one parameter, so the two cannot disagree by accident.
- **Price is a rung, and evidence and action are separate decisions.** Comparables are retrieved by default; letting them MOVE a price is a second explicit switch (`comparables.rung_adjust_enabled`, default off). One flag for both is how a catalogue re-prices itself the day a feature merges.

## Where production runs, and how to work in a worktree

Both used to be long sections here, injected into every session. They are skills now, because
they matter to some sessions and to none of the others: **`/where-production-runs`** and
**`/worktree-and-gate`**. Load the one you need. What stays here is only what a session can get
wrong without ever opening them.

**Production is not this checkout.** The scheduler and consumer run from
`/Users/chidionyema/Documents/code/prospector-live`, detached at `origin/main`. Editing a branch
here cannot change what production executes. The live answer is a command, never a paragraph:

```bash
.venv/bin/python scripts/live_checkout.py            # daemon cwd, live HEAD vs origin/main, secrets
.venv/bin/python scripts/live_checkout.py --update   # roll production forward and restart
```

**Production's store is canonical, and it is not on this laptop** (founder ruling 2026-08-19).
The Fly engine writes `/data/store` on volume `vol_42kyqo6g0kdzew14`. The laptop `store/` is a copy
the cutover stopped updating: measured 2026-08-19 21:11Z, 166,013 ledger rows stamped that day on
Fly against 0 on the laptop. A reader that resolves `config.store_root()` in a laptop process is
reading the dead copy and will report a confident zero. Ask production — `scripts/engine_failover.py`
is how the console's drain view already does it.

**Within one process there is still exactly one store**, pinned by `PROSPECTOR_STORE_DIR` and
resolved only by `config.store_root()`. Never write `Path(__file__).parent.parent / "store"` — a
path derived from `__file__` follows the CODE, and a daemon writing one health file while a probe
reads another can never see a provider recover.

**Never `git add -A` in a worktree.** `store/` and `storage/` are tracked runtime state that
pytest writes to. Stage explicit paths.

**Make worktrees with the script, not by hand.** `git worktree add` produces a tree that looks
complete and is not, and each gap fails by accusing something else:

```bash
git worktree add --detach ../my-worktree <ref>
./scripts/setup_worktree.sh ../my-worktree
```

**Whether a pre-commit gate exists is a command, not a sentence** — this file has been wrong in
both directions:

```bash
git config --get core.hooksPath          # set => THAT directory wins, not .git/hooks
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
```

Preflight without committing: `.venv/bin/python scripts/popdd_verify.py --staged`.
