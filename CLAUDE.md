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

## Where production runs

**Production runs on Fly, in the `prospector-engine` app.** Not this checkout, and not the laptop
checkout. `~/.prospector/ACTIVE` names the serving side; `engine_failover.py` is its writer.
Editing a branch here cannot change what production executes.

The live answer is a command, never this paragraph:

```bash
.venv/bin/python scripts/live_checkout.py            # machine state, deployed commit, CI on it
.venv/bin/python scripts/live_checkout.py --update   # build origin/main and release it to Fly
```

Both are console buttons. The probe reads the commit out of the image (`/app/GIT_SHA`, written by
`deploy/engine/Dockerfile`); an image without it reports "cannot tell which commit production
runs" rather than staying silent. `--update` builds from
`/Users/chidionyema/Documents/code/prospector-live`, a clean checkout detached at `origin/main`,
and refuses local code changes — `fly deploy` uploads a working tree, so building from this shared
checkout would ship whatever branch a session left behind. **A fix reaches production through a PR,
never an edit on the box.** History of both moves: memory `production-runs-from-its-own-checkout.md`.

**State did NOT move.** `PROSPECTOR_STORE_DIR` pins catalogue, ledger, dossiers and scheduler files
to `/Users/chidionyema/Documents/code/prospector/store`. There is exactly one canonical store.

1. **Git does not carry secrets.** `.env` and `.lux/keys/agent.pem` are symlinks back to this
   checkout; the probe checks both. Without them every MiniMax tier benches with
   `ProviderExhaustedError: ... check API keys and credentials`, which accuses the roster.
2. **A store path derived from `__file__` follows the CODE, not the store.** Use
   `config.store_root()`. **Do not sweep for this by grepping** — the trap is the two-step form
   (`ROOT = Path(__file__).resolve().parents[1]` on one line, `ROOT / "store"` on another), so a
   regex found 2 where an AST walk found 40.
   `tests/unit/test_no_store_path_is_derived_from_file.py` is the check; issue #371 has the list.
   Memory: `a-regex-sibling-sweep-counted-2-of-40.md`.

## Working in a git worktree

**One session, one worktree.** Sessions share this checkout's `.git/index`, and `git worktree add`
succeeds even while that index is locked — which is the point.

```bash
git worktree add --detach ../my-worktree <ref>
./scripts/setup_worktree.sh ../my-worktree        # NOT optional
```

`git worktree add` produces a tree that **looks** complete and is not, and each gap fails by
accusing something else. The script fixes four: `node_modules` cannot be symlinked (Turbopack
rejects any symlink leaving the project root — `cp -Rc`, an APFS clone); `.lux/keys/agent.pem` is
untracked, so the POPDD hook runs and then fails for want of a signing key, reading as a gate
violation; `.venv` is absent while the hook pins `.venv/bin/python` relative to cwd, so commits die
with `POPDD gate BLOCKED` over a missing interpreter; `store/` and `storage/` are tracked runtime
state pytest writes to, so **never `git add -A` in a worktree** — stage by explicit name.
Memory: `worktree-setup-is-a-script-now.md`.

**Whether the pre-commit gate is installed is a command, never this file.** It has been on and off
twice, and both times a session lost hours to the paragraph that said otherwise.

```bash
git config --get core.hooksPath                        # set => THAT directory wins, not .git/hooks
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
```

`core.hooksPath` overrides the hooks directory entirely, so moving `.git/hooks/pre-commit` aside
does nothing while it is set, and a link written into `.git/hooks/` is never read.

```bash
# ON. The target is ABSOLUTE (the link lives in the hooks dir, a relative target resolves there)
# and it is the MAIN checkout's copy, because hooks-active sits in the COMMON git dir and is
# shared by every worktree — one link, so the gate cannot be half-on.
ln -sfn "$(dirname "$(cd "$(git rev-parse --git-common-dir)" && pwd -P)")/.lux/hooks/pre-commit" \
        "$(git rev-parse --git-path hooks)/pre-commit"
# OFF
rm "$(git rev-parse --git-path hooks)/pre-commit"
```

Preflight without committing: `.venv/bin/python scripts/popdd_verify.py --staged`. The gate runs
INSIDE the hook, so `git commit` holds `.git/index.lock` for the whole run;
`scripts/popdd_verify.py::single_flight` refuses a second run in the same tree inside a second
(pinned by `tests/unit/test_popdd_gate_cannot_wedge.py`).

Two things the gate depends on that fail by accusing something else: **`ruff` runs REPO-WIDE**
(`scripts/popdd_verify.py:166`), so one unformatted file anywhere walls every commit in every
worktree, and a worktree on an older base fails ruff until it rebases. And **anything reading
`<root>/.git/…` as a directory is a bug** — in a worktree `.git` is a FILE containing `gitdir:`.
Ask git (`git rev-parse --git-path hooks`, `--git-common-dir`), which also honours `core.hooksPath`.

**Do not quote a suite timing from this file. Time it.** The suite grows and the 2400s ceiling
(`scripts/popdd_verify.py:86`) does not; every number this file has carried was stale within days.
`pytest.ini:42` sets `addopts = -n auto --dist loadfile`, so nothing runs serially.
