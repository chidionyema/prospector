# Prospector Operating Rules

> Long-form history for every rule below lives in memory
> (`reference-project-claude-md-full-2026-08-06.md` is the verbatim pre-compression text).
> This file carries the RULE; the memory files carry the incident that produced it.
>
> Two programmes have their own tracked specs — read and append there, never here:
> `docs/COST_PROGRAM.md` (all cost work, all measurements) and
> `docs/GRAPHIFY_ENFORCEMENT_SPEC.md` (estate-wide graph freshness).

**Source-or-die:** every factual claim and quantitative figure must cite a retrievable source or be marked `unverifiable`. No unsourced numbers ship, ever.

**Verdict-from-retrieval-only:** the model rules solely from passages it actually fetched via web search or fixture. No prior knowledge. Silence (no matching passage) → `unverifiable`, never `supported`.

**The filter is universal:** the same six checks (pain_reality, value_durability, incumbency, payer_solvency, distribution, legality) apply to any business, any sector, any scale, by the same bar.

**Kill-fast:** stop at the first hard fail. Evaluate the cheapest decisive gates first; don't burn research budget on ideas already dead.

**A KILL with a cited reason is first-class:** render a dossier for every KILL, not just passes. The kill log is the receipt that the filter is real and grounded.

**Publish only on PASS:** only ideas that clear all hard gates and survive adversarial review reach the catalogue. A KILL blocks publication entirely.

**Follow RUN.md:** every run (on-demand vet, scheduled batch, signal intake) executes the eight steps in RUN.md exactly. The procedure is the guarantee.

**Use web tools for grounding:** the retrieval chain is `[ddg, exa, claude_cli]` (`config.yaml retrieval.provider`) — free DuckDuckGo, then Exa, then Claude Code's own web search as the always-available backstop. Gemini is gone (no `gemini` key in `config.yaml`). Verdicts are ruled ONLY by `MOAT_PRIMARY = {claude_cli, claude}` (`prospector/operator.py:889`); cursor_cli was deleted 2026-08-06. DeepSeek/MiniMax are non-critical generation and triage ONLY and are off the verdict chain (`config.yaml operator: [claude_cli]`), so a blind moat DEFERS instead of serving a `provisional` ruling. `is_provisional_provider` (`operator.py:892`) enforces it: anything outside MOAT_PRIMARY that ever rules is stamped `provisional`, never publishes on PASS, and is auto re-vetted.

**Write every run to store/:** input (signal or candidate), all verdicts + sources, the kill gate if applicable, cost, timing. This log is the audit trail and the basis for learning.

**Run bounded batches inside the usage allowance:** default 5 candidates per signal. Generation may run continuously and unattended (founder decision 2026-06-20: no human in the loop) via `prospector/scheduler/` — but ONLY behind the two automated rails that replace human supervision: a daily spend ceiling (`spend.daily_cap_usd`, read from the persistent `store/prospector.jsonl` ledger) and a filesystem kill switch (`store/scheduler/PAUSE`). Unattended generation without them is forbidden. When batches bump the Claude Code usage cap, fund the API operator.

**Generation must not outrun its own drain.** `PAUSE` is the liability rail: it halts the ENTIRE tick, generation and re-vet drain together, because a rail with exceptions is not a rail. The drain must never be collateral damage of a decision to skip generation, so two half-stops exist that leave it running: `store/scheduler/PAUSE_GENERATION` (operator) and `schedule.backlog_cap` (automatic, **default 0 = off**; above the cap a tick drains at `drain_only_resume_per_tick`, defaulting to `batch_size`, on a `drain_only_interval_s` cadence clamped never to exceed the generation interval, and it self-releases under the cap).

**Gate on the RATE, not the stock** (founder decision 2026-08-06, superseding the stock brake). A stock brake has unbounded memory: one outage suppresses generation indefinitely — a six-week-old outage was why the daemon generated nothing that afternoon. `schedule.gate_generation_on_grounding` (default on) runs one bounded live search per tick and suppresses generation only while retrieval is ACTUALLY degraded — the sole condition under which generating adds backlog — and self-clears when the outage ends. The cap stays at 0 as a floor of last resort. Measured basis (and the correction of the earlier "+12 rows/tick by design" diagnosis, which assumed every candidate defers): **generation volume does not create backlog rows; failed retrieval does.** `run.drainable()` is the single definition of "backlog", so the brake can only engage on a number the drain can move; when the count fails it returns `None`, never `0`, and generation stops rather than being waved through. The moat preflight outranks all of it: a blind moat skips the drain too, since re-vetting into it only relabels rows `provisional`→`defer`. Full evidence: memory `gate-on-the-rate-not-the-stock.md`.

**No hosted service / no API-key calls beyond this repo:** the engine runs locally or within your Claude Code subscription. No hosted inference, no infrastructure beyond your own server. This repo is the complete system.

## Architecture

Pluggable modules:

- **config.py** — operator, model, retrieval, thresholds, weights, generation strategy; no hardcoded values
- **models.py** — Candidate, Verdict, Claim, Dossier, Pack; the contracts
- **operator.py** — swappable brain (Claude CLI/API, DeepSeek, MiniMax, Ollama, Mock). `MOAT_PRIMARY` (`:889`) is the only set that may rule; DeepSeek/MiniMax sit in tiered non-critical chains for generation, prescreen and scoring, and anything of theirs that rules is stamped `provisional` and re-vetted, never finalised. `_build_operator` raises `ValueError` for the removed `cursor_cli`, so a stale config or plist fails loudly at startup instead of silently building a shorter chain.
- **errors.py / health.py** — failover classifier + persisted dead marks. `classify_exhaustion` (`errors.py:134`) splits TRANSIENT backpressure (429/503/529, `overloaded_error`) from PERMANENT exhaustion (402, credit balance, any spend/usage/monthly allowance via `_ALLOWANCE_LIMIT_RE`, `errors.py:104`); PERMANENT wins ties. **HTTP codes match on WORD BOUNDARIES** — a bare substring let a request id or byte count bench a live brain. The allowance regex exists because the CLI says **spend** limit, not usage limit. Transient → 60s (`health.py:54`), permanent → 1h. `_claim_probe` (`health.py:130`) makes the mark half-open so exactly one caller machine-wide re-probes and a brain that recovers in 90s is back in 90s. Memory: `substring-http-codes-bench-a-live-brain.md`.
- **retrieval.py** — grounding chain `[ddg, exa, claude_cli]`: live fetch, caching, per-provider circuit breakers; fixtures for offline test. `GeminiGroundingProvider` still exists in the file but no config selects it.
- **prompts.py** — generate, prescreen, query_gen, verdict, adversarial, score, content_gen, claim_check, price_comparables
- **generate.py / dedup.py / prescreen.py** — divergent candidate creation from signals; embed-match against the catalogue to drop near-duplicates; first triage gate (fast, cheap, preserves novelty)
- **verify.py** — the moat: the lane's checks end-to-end (query gen → fetch → verdict) on a MOAT_PRIMARY brain, kill-fast short-circuit. Tracks provider_chain and per-check provider for audit. Raises `ProviderExhaustedError` when the moat is down so callers DEFER and resume.
- **price_comparables.py** — the seventh check and the only evidence-only one: on a candidate that survived every gate, it extracts CITED prices buyers already pay from retrieved price pages. It can NEVER kill (barred in `kill_filter.is_hard_fail` and in verify's run order) — "no price page on the open web" is a fact about the web, not the idea. Every anchor must appear literally in the passage it cites; FX is config-declared, never inferred.
- **pricing.py** — the L1 ladder: segment (ambition_tier × market) → a rung declared in `config.yaml listing.pricing`, never a computed continuous number. Comparables move it at most one rung, and only when `comparables.rung_adjust_enabled` is on (default off).
- **kill_filter.py** — deterministic gates; KILL or PASS
- **score.py** — ranks survivors on six axes; composite = Σ(score × weight)
- **dossier.py / store.py / publish.py** — compose primary + secondary artifacts and render to JSON; local catalogue state; on PASS write listing JSON + print syndication intent
- **bridge.py** — the money rail's entry point: one `PriceDecision` mints the provider Price object AND writes the catalogue row, so the two cannot drift (a drift charges the buyer and then fails the fulfilment fence).
- **run.py** — CLI entry point; orchestrates RUN.md's eight steps. Builds the tiered non-critical chain `_NONCRITICAL_ORDER = (claude_cli, minimax)` (`run.py:194`) for generation/prescreen/score. Handles moat exhaustion with DEFER + `vet --resume`; persists failed signals to `signals/pending/` for `generate --resume`.

## Key constraints

- **Deterministic on config.** Swapping operators (Claude Code → API) requires no code change, only `config.yaml`.
- **Every verdict is grounded in cited sources.** A KILL is not the model's opinion; it is evidence the operator can see.
- **Golden-set regression gates all changes.** Part 13B acceptance tests block ship on any mixed-sector discrimination regression.
- **Creativity lives in generation; constraint lives in verification.** Nothing is killed at generation time; all gates (pre-screen, verify, kill-filter) are downstream.
- **Two loops never merge.** Sales metrics (demand) tune what to offer; truth metrics (grounding integrity, golden-set discrimination) veto what may ship. Demand never overrides truth.
- **Non-critical chains run behind their own breaker and never rule a verdict.** Generation/prescreen/score run `claude_cli → minimax` (`run.py:194`) behind an independent health file and breaker. If every tier fails the chain raises `ProviderExhaustedError` — it never silently promotes itself into ruling — and the signal is saved for `generate --resume`. claude_cli heads the chain (founder, 2026-08-06) because deepseek measured HTTP 402 and cursor_cli was at its usage limit, which left every call to minimax — non-deterministic on structured routing even at temperature 0 (4 of 6 candidates changed tier across 3 repeat runs). The absolute rule is about VERDICTS, not tiers: DeepSeek/MiniMax never rule as trusted-final (`operator.py:892`).
- **A dead brain must leave a trace.** A fallback chain that works hides its own degradation: the run succeeds, so nothing looks wrong, while the head of the chain is a guaranteed failure paid before every call. Permanence is classified by ONE shared, tested function (`errors.looks_exhausted`) used by every metered adapter; only a `ProviderExhaustedError` reaches `_health.mark_exhausted`, so a failure the classifier misses is retried forever. 402/"payment required" was missing until 2026-08-06.
- **An exception is never evidence; a failed call DEFERS.** A verdict call that raises — quota, bad JSON, a crashed adapter — returns `retrieval_failed=True` (`verify.py:365`), firing the DEFER gate (`verify.py:693`) instead of contributing an `unverifiable` check to the kill gates. Before 2026-08-06 it did not: `store/dossiers/2102bacc6dd75cf9.kill.json` is a KILL on `min_composite` whose seven checks all read `unverifiable, conf 0.0, "Verdict call failed; fail-safe."` — a candidate killed by our own outage, in a dossier that reads as fully reasoned. DEFER deliberately covers non-quota failures too: the honest verdict on an unevaluated check is "come back to it", never "this idea is dead".
- **Moat exhaustion = DEFER, not crash.** `vet --resume` picks up when the moat recovers. A DEFER is cheaper, not worse: a provisional PASS can never publish, so it costs a full verdict run now AND a re-vet later to reach the conclusion a DEFER reaches once.
- **The daemon must not mint work the moat cannot finish.** `_moat_blind_reason` (`scheduler/run_scheduled.py:180`) is a generation preflight: when EVERY trusted brain carries a live dead mark the tick is skipped, logged `moat_blind`, and counted unproductive so the escalating 5m/10m/20m retry applies instead of the 2h cadence. One live brain is enough — a floor, not a fair-weather switch. It reads raw `dead_until`, never `is_dead`, so a bookkeeping check cannot consume the half-open probe slot a real verdict call should get. Without it the daemon minted provisional passes exactly as fast as the drain retired them (229 → 230 rows, net flat, both competing for the same subscription CLI).
- **Price is a rung, and evidence and action are separate decisions.** `price_comparables` retrieves cited willingness-to-pay anchors by default; letting them MOVE a price is a second, explicitly-enabled switch. Same flag for both is how a catalogue re-prices itself the day a feature merges.

## Working in a git worktree

This checkout is often shared by two concurrent sessions, so a worktree is how you merge, build or test without touching another session's tree and index. But `git worktree add` produces a tree that **looks** complete and is not, and each gap fails by accusing something else. Always run:

```bash
git worktree add --detach ../my-worktree <ref>
./scripts/setup_worktree.sh ../my-worktree
```

It fixes four traps, each of which misdirects the diagnosis (detail: memory `worktree-setup-is-a-script-now.md`): **`node_modules` cannot be symlinked** (Turbopack rejects any symlink leaving the project root, same filesystem or not — use `cp -Rc`, an APFS copy-on-write clone); **`.lux/keys/agent.pem` is untracked**, so the shared POPDD hook runs then fails for want of a signing key, reading as a gate violation; **`.venv` is absent while `.lux/hooks/pre-commit:67` pins `.venv/bin/python` relative to cwd**, so commits die with `POPDD gate BLOCKED` over a missing interpreter (a symlink is fine here — `node_modules` is the odd one out); **`store/` and `storage/` are tracked runtime state that pytest writes to**, so never `git add -A` in a worktree.

Two more traps that outlive the setup script: `npm run build 2>&1 | tail` reports **tail's** exit status, so a failed build reads as `exit 0` — capture the build's own status before any pipe. And anything reading `<root>/.git/…` as a directory is a bug: in a worktree `.git` is a **file** containing `gitdir:`. Ask git instead (`git rev-parse --git-path hooks`, `--git-common-dir`), which also honours `core.hooksPath`; `tests/unit/test_popdd_gate_lanes.py` had exactly this defect and reported the POPDD gate uninstalled in a checkout where it was installed and working.
