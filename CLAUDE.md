# Prospector Operating Rules

> Long-form history for every rule below lives in memory
> (`reference-project-claude-md-full-2026-08-06.md` is the verbatim pre-compression text).
> This file carries the RULE; the memory files carry the incident that produced it.
>
> `docs/ARCHITECTURE_SECURITY_BASELINE.md` is the measured state of the system: what it is,
> whether the money path and the engine are tested, the security findings, and where the mud
> is. Re-measure it, never quote it from memory.
>
> `docs/WAYS_OF_WORKING.md` is how work is done here: 25 rules, each one a named repeated
> failure rather than a preference. Part 7 marks honestly which are enforced by a machine
> and which are still only words. `scripts/session_check.py` enforces the first five.
>
> `docs/PLATFORM_MANIFESTO.md` is the constitution: the ten platform laws, the agent tenets
> every session is bound by, the portability target matrix and its drills, and the measured
> automation audit. Read it before proposing anything structural.
>
> **When something breaks, the fix is half the job.** `docs/INCIDENT_PROCESS.md` is the other
> half: sweep for the siblings, land a mechanism that refuses the whole class, and grade it
> afterwards. Records: `docs/incidents/*.json`. Gate: `.venv/bin/python scripts/incident.py check`.
> What takes longest and what repeats: `scripts/incident.py friction`.
>
> Four programmes have their own tracked specs — read and append there, never here:
> `docs/COST_PROGRAM.md` (all cost work, all measurements),
> `docs/GRAPHIFY_ENFORCEMENT_SPEC.md` (estate-wide graph freshness),
> `docs/SITE_SPEC_PROGRAM.md` (the mumchimp.com design/UX/copy spec + its live status ledger —
> it lived only in a chat transcript until 2026-08-07, which is why its status kept evaporating
> between sessions; read it before touching the storefront) and
> `docs/PACK_NARRATIVE_PROGRAM.md` (what the buyer actually reads: the 14-section reading order,
> the eight deterministic renderers and why they must stay model-free, the three gates that were
> grading less than they appeared to, and the switches that are deliberately OFF. Read it before
> touching a `pack_*.py` renderer, the pack linter, or `tools/backfill_bundle_html.py` — the
> diagnosis is the top half, the implementation ledger is the bottom half).

**Source-or-die:** every factual claim and quantitative figure must cite a retrievable source or be marked `unverifiable`. No unsourced numbers ship, ever.

**Verdict-from-retrieval-only:** the model rules solely from passages it actually fetched via web search or fixture. No prior knowledge. Silence (no matching passage) → `unverifiable`, never `supported`.

**The filter is universal:** the same six checks (pain_reality, value_durability, incumbency, payer_solvency, distribution, legality) apply to any business, any sector, any scale, by the same bar.

**Kill-fast:** stop at the first hard fail. Evaluate the cheapest decisive gates first; don't burn research budget on ideas already dead.

**A KILL with a cited reason is first-class:** render a dossier for every KILL, not just passes. The kill log is the receipt that the filter is real and grounded.

**Publish only on PASS:** only ideas that clear all hard gates and survive adversarial review reach the catalogue. A KILL blocks publication entirely.

**Follow RUN.md:** every run (on-demand vet, scheduled batch, signal intake) executes the eight steps in RUN.md exactly. The procedure is the guarantee.

**Use web tools for grounding:** the retrieval chain is `[ddg, exa, claude_cli]` (`config.yaml retrieval.provider`) — free DuckDuckGo, then Exa, then Claude Code's own web search as the always-available backstop. Gemini is gone (no `gemini` key in `config.yaml`). Verdicts are ruled FINALLY only by the brains named in `config.yaml moat_primary:` (read via `operator.moat_primary()`; blank => `operator.MOAT_PRIMARY_DEFAULT` = `{claude_cli}`; `PROSPECTOR_MOAT_PRIMARY` overrides for one process). CONFIG-DECLARED 2026-08-15 — it was a hardcoded frozenset with no config key, the one tier knob that needed a source edit and a daemon re-exec to move, which is what made a cheap brain's throughput unusable at any concurrency. Promotion is that line plus the golden gate, never a patch. **Live on disk 2026-08-15: `operator: [minimax, claude_cli]` (`config.yaml:58`) and `moat_primary: [minimax, claude_cli]` (`config.yaml:81`) — MiniMax LEADS and is TRUSTED, claude_cli is the fallback** (founder directive: "ship with MiniMax running the whole show and claude and fallback"). It was promoted on receipts, not preference: three consecutive golden runs at discrimination 1.00 (9/9) once `verify._calc_confidence` was fixed — that scorer took 70% of its number from citation VOLUME and domain COUNT, so a terse brain was scored ungrounded for a style difference, which is what the earlier 0.96 FAIL was actually measuring. Do NOT revert this roster to a claude-led one on the strength of a single failing run; measure the scorer first. The paid Anthropic API tier `claude` was deleted with its adapter on 2026-08-15 (no ANTHROPIC_API_KEY in this estate, so it could not construct, let alone rule); cursor_cli went the same way 2026-08-06 and standardcompute on 2026-08-15. `is_provisional_provider` (`operator.py:1451`) is what keeps any UNtrusted tail safe: anything outside MOAT_PRIMARY that rules is stamped `provisional`, never publishes on PASS (`run.py:864`), and is auto re-vetted. DeepSeek remains non-critical generation and triage ONLY.

**Write every run to store/:** input (signal or candidate), all verdicts + sources, the kill gate if applicable, cost, timing. This log is the audit trail and the basis for learning.

**Run bounded batches inside the usage allowance:** candidates per signal is config-declared (`config.yaml candidates_per_signal`, 20 as of 2026-08-10; `schedule.batch_size` 15). Generation may run continuously and unattended (founder decision 2026-06-20: no human in the loop) via `prospector/scheduler/` — but ONLY behind the two automated rails that replace human supervision: a daily spend ceiling (`spend.daily_cap_usd`, read from the persistent `store/prospector.jsonl` ledger) and a filesystem kill switch (`store/scheduler/PAUSE`). Unattended generation without them is forbidden. When batches bump the Claude Code usage cap, fund the API operator.

**Generation must not outrun its own drain.** `PAUSE` is the liability rail: it halts the ENTIRE tick, generation and re-vet drain together, because a rail with exceptions is not a rail. The drain must never be collateral damage of a decision to skip generation, so two half-stops exist that leave it running: `store/scheduler/PAUSE_GENERATION` (operator) and `schedule.backlog_cap` (automatic, **default 0 = off**; above the cap a tick drains at `drain_only_resume_per_tick`, defaulting to `batch_size`, on a `drain_only_interval_s` cadence clamped never to exceed the generation interval, and it self-releases under the cap).

**Gate on the RATE, not the stock** (founder decision 2026-08-06, superseding the stock brake). A stock brake has unbounded memory: one outage suppresses generation indefinitely — a six-week-old outage was why the daemon generated nothing that afternoon. `schedule.gate_generation_on_grounding` (default on) runs one bounded live search per tick and suppresses generation only while retrieval is ACTUALLY degraded — the sole condition under which generating adds backlog — and self-clears when the outage ends. The cap stays at 0 as a floor of last resort. Measured basis (and the correction of the earlier "+12 rows/tick by design" diagnosis, which assumed every candidate defers): **generation volume does not create backlog rows; failed retrieval does.** `run.drainable()` is the single definition of "backlog", so the brake can only engage on a number the drain can move; when the count fails it returns `None`, never `0`, and generation stops rather than being waved through. The moat preflight outranks all of it: a blind moat skips the drain too, since re-vetting into it only relabels rows `provisional`→`defer`. Full evidence: memory `gate-on-the-rate-not-the-stock.md`.

**Run it wherever the business is safest — REPLACES the old "no hosted service" rule (founder directive 2026-08-18).** The rule used to read: *"the engine runs locally or within your Claude Code subscription. No hosted inference, no infrastructure beyond your own server. This repo is the complete system."* It was written for a side project. The founder's words killing it: **"forget about CLAUDE.md, that was in the past, this is a commercial business running off a laptop."** Running a commercial engine on one laptop is the risk now, not hosted infrastructure. Hosted inference and hosted compute are ALLOWED. What survives from the old rule is the part that was actually load-bearing: **the repo stays the complete system** — no behaviour may live only in a console, a dashboard or a provider account, and a fresh clone plus an env file must still be able to run the whole engine. See `docs/ENGINE_MIGRATION_PROGRAM.md`.

## Architecture

Pluggable modules:

- **config.py** — operator, model, retrieval, thresholds, weights, generation strategy; no hardcoded values
- **models.py** — Candidate, Verdict, Claim, Dossier, Pack; the contracts
- **operator.py** — swappable brain (Claude CLI/API, DeepSeek, MiniMax, Ollama, Mock). `moat_primary()` — declared by `config.yaml moat_primary:` — is the only set that may rule FINALLY; since 2026-08-15 that set is `[minimax, claude_cli]`, so MiniMax both HEADS the verdict chain and rules finally. DeepSeek still sits in tiered non-critical chains for generation, prescreen and scoring and is never trusted-final: anything outside `moat_primary()` that rules is stamped `provisional` and re-vetted, never finalised. `minimax_concurrency` (`config.yaml:321`, default 8) is installed process-globally by `config.load_config` and measured clean at 16/16 with zero 429s. `_build_operator` raises `ValueError` for the removed `cursor_cli`, so a stale config or plist fails loudly at startup instead of silently building a shorter chain.
- **errors.py / health.py** — failover classifier + persisted dead marks. `classify_exhaustion` (`errors.py:134`) splits TRANSIENT backpressure (429/503/529, `overloaded_error`) from PERMANENT exhaustion (402, credit balance, any spend/usage/monthly allowance via `_ALLOWANCE_LIMIT_RE`, `errors.py:104`); PERMANENT wins ties. **HTTP codes match on WORD BOUNDARIES** — a bare substring let a request id or byte count bench a live brain. The allowance regex exists because the CLI says **spend** limit, not usage limit. Transient → 60s (`health.py:54`), permanent → 1h. `_claim_probe` (`health.py:130`) makes the mark half-open so exactly one caller machine-wide re-probes and a brain that recovers in 90s is back in 90s. Memory: `substring-http-codes-bench-a-live-brain.md`.
- **retrieval.py** — grounding chain `[ddg, exa, claude_cli]`: live fetch, caching, per-provider circuit breakers; fixtures for offline test. `GeminiGroundingProvider` still exists in the file but no config selects it.
- **prompts.py** — generate, prescreen, query_gen, verdict, adversarial, score, content_gen, claim_check, price_comparables
- **generate.py / dedup.py / prescreen.py** — divergent candidate creation from signals; string-similarity match (`difflib.SequenceMatcher` + Jaccard token overlap — not embeddings; `prescreen_prefilter.py` is embedding-based but is wired off in config.yaml) against the catalogue to drop near-duplicates; first triage gate (fast, cheap, preserves novelty)
- **verify.py** — the moat: the lane's checks end-to-end (query gen → fetch → verdict) on a MOAT_PRIMARY brain, kill-fast short-circuit. Tracks provider_chain and per-check provider for audit. Raises `ProviderExhaustedError` when the moat is down so callers DEFER and resume.
- **price_comparables.py** — the seventh check and the only evidence-only one: on a candidate that survived every gate, it extracts CITED prices buyers already pay from retrieved price pages. It can NEVER kill (barred in `kill_filter.is_hard_fail` and in verify's run order) — "no price page on the open web" is a fact about the web, not the idea. Every anchor must appear literally in the passage it cites; FX is config-declared, never inferred.
- **pricing.py** — the L1 ladder: segment (ambition_tier × market) → a rung declared in `config.yaml listing.pricing`, never a computed continuous number. Comparables move it at most one rung, and only when `comparables.rung_adjust_enabled` is on (default off).
- **kill_filter.py** — deterministic gates; KILL or PASS
- **score.py** — ranks survivors on six axes; composite = Σ(score × weight)
- **dossier.py / store.py / publish/publish.py** — compose primary + secondary artifacts and render to JSON; local catalogue state; on PASS write listing JSON + print syndication intent (the top-level publish/ package — prospector/publish.py is a dead 0-byte stub)
- **bridge.py** — the money rail's entry point: one `PriceDecision` mints the provider Price object AND writes the catalogue row, so the two cannot drift (a drift charges the buyer and then fails the fulfilment fence).
- **run.py** — CLI entry point; orchestrates RUN.md's eight steps. Builds the tiered non-critical chain for generation/prescreen/score: `_noncritical_order(cfg)` (`run.py:320`) reads `config.yaml:70 noncritical_operator:`, falling back to the hardcoded default `_NONCRITICAL_ORDER = ("minimax",)`. Handles moat exhaustion with DEFER + `vet --resume`; persists failed signals to `signals/pending/` for `generate --resume`.

## Key constraints

- **Deterministic on config.** Swapping operators (Claude Code → API) requires no code change, only `config.yaml`.
- **Every verdict is grounded in cited sources.** A KILL is not the model's opinion; it is evidence the operator can see.
- **Golden-set regression gates all changes.** Part 13B acceptance tests block ship on any mixed-sector discrimination regression.
- **Creativity lives in generation; constraint lives in verification.** Nothing is killed at generation time; all gates (pre-screen, verify, kill-filter) are downstream.
- **Two loops never merge.** Sales metrics (demand) tune what to offer; truth metrics (grounding integrity, golden-set discrimination) veto what may ship. Demand never overrides truth.
- **Non-critical chains run behind their own breaker and never rule a verdict.** Generation/prescreen/score run the `noncritical_operator` chain (`run.py:320`, consumed at `:679`) behind an independent health file and breaker. **Live on disk 2026-08-15 that chain is `minimax` alone**: claude_cli was BARRED from it on 2026-08-14 (founder: "claude should never be used for non-critical"), enforced where the chain is BUILT (`_noncritical_order` strips it, `_NONCRITICAL_FORBIDDEN`), and standardcompute was deleted with its adapter on 2026-08-15. If every tier fails the chain raises `ProviderExhaustedError` — it never silently promotes itself into ruling — and the signal is saved for `generate --resume`. claude_cli heads the chain (founder, 2026-08-06) because deepseek measured HTTP 402 and cursor_cli was at its usage limit, which left every call to minimax — non-deterministic on structured routing even at temperature 0 (4 of 6 candidates changed tier across 3 repeat runs). The absolute rule is about VERDICTS, not tiers, and it is a rule about the ROSTER rather than about any particular brand: whoever is outside `moat_primary()` never rules as trusted-final (`is_provisional_provider`, `operator.py:1451`). As of 2026-08-15 MiniMax is INSIDE that set, so it rules finally on the moat while still being the only non-critical tier — the two facts are independent and a test that hardcodes "minimax = untrusted" is pinning the roster, not the fence.
- **A dead brain must leave a trace.** A fallback chain that works hides its own degradation: the run succeeds, so nothing looks wrong, while the head of the chain is a guaranteed failure paid before every call. Permanence is classified by ONE shared, tested function (`errors.looks_exhausted`) used by every metered adapter; only a `ProviderExhaustedError` reaches `_health.mark_exhausted`, so a failure the classifier misses is retried forever. 402/"payment required" was missing until 2026-08-06.
- **An exception is never evidence; a failed call DEFERS.** A verdict call that raises — quota, bad JSON, a crashed adapter — returns `retrieval_failed=True` (`verify.py:365`), firing the DEFER gate (`verify.py:693`) instead of contributing an `unverifiable` check to the kill gates. Before 2026-08-06 it did not: `store/dossiers/2102bacc6dd75cf9.kill.json` is a KILL on `min_composite` whose seven checks all read `unverifiable, conf 0.0, "Verdict call failed; fail-safe."` — a candidate killed by our own outage, in a dossier that reads as fully reasoned. DEFER deliberately covers non-quota failures too: the honest verdict on an unevaluated check is "come back to it", never "this idea is dead".
- **Moat exhaustion = PROVISIONAL first, DEFER only when the tail is down too** (founder directive 2026-08-08; before that, exhaustion always meant DEFER). The 2026-08-06 arithmetic is unchanged and still true — `provisional` costs a verdict run now AND a re-vet later (2x) to reach the answer a DEFER reaches once (1x) — but it is now an ACCEPTED cost, because a DEFER stops the line: on 2026-08-08 a monthly spend limit on claude_cli left the daemon producing nothing rulable for hours. `vet --resume` still finalises both populations when the moat recovers.
- **The daemon must not mint work NO brain can finish.** `_moat_blind_reason` (`scheduler/run_scheduled.py:465`) is a generation preflight calling `health.moat_blind_reason(cfg, trusted_only=False)`: the tick is skipped only when EVERY configured verdict brain — trusted or provisional — carries a live dead mark, and is then logged `moat_blind` and counted unproductive so the escalating 5m/10m/20m retry applies instead of the 2h cadence. One live brain of ANY tier is enough; keeping this trusted-only would have made the minimax re-add inert in exactly the situation it exists for. It reads raw `dead_until`, never `is_dead`, so a bookkeeping check cannot consume the half-open probe slot a real verdict call should get.
- **The DRAIN stays trusted-only, and that asymmetry is deliberate.** `run.py::_cmd_resume` runs the same classifier at the default `trusted_only=True`, because re-vetting a `provisional` row on a provisional brain re-stamps it `provisional`: the row does not move, the money is spent, and the drain's CLI load helps keep the trusted brain benched (measured 2026-08-06: provisional −14 / defer +13 over 30 minutes, net −1). Generation may run into a provisional tail; the drain may not. One shared function, one parameter — so the two can never disagree by accident.
- **Price is a rung, and evidence and action are separate decisions.** `price_comparables` retrieves cited willingness-to-pay anchors by default; letting them MOVE a price is a second, explicitly-enabled switch. Same flag for both is how a catalogue re-prices itself the day a feature merges.

## Where production runs (changed again 2026-08-18 — read this before editing a branch)

**Production runs on Fly, in the `prospector-engine` app.** Not this checkout, and no longer the
laptop checkout either. `~/.prospector/ACTIVE` names the side that is serving; `engine_failover.py`
is its writer. Editing a branch here cannot change what production executes.

The live answer is a command, never this paragraph:

```bash
.venv/bin/python scripts/live_checkout.py            # machine state, deployed commit, CI on it
.venv/bin/python scripts/live_checkout.py --update   # build origin/main and release it to Fly
```

Both are console buttons. The probe reads the commit out of the image itself
(`/app/GIT_SHA`, written by `deploy/engine/Dockerfile` from the build argument
`deploy/targets/fly.sh` passes). An image built without it reports "cannot tell which commit
production runs", which is a problem rather than a silence — measured 2026-08-18, every release
up to v15 was in exactly that state, so `fly releases` gave a version number that mapped to no
commit at all.

`--update` builds from `/Users/chidionyema/Documents/code/prospector-live`, a clean checkout
detached at `origin/main`, and refuses if it has local code changes. `fly deploy` uploads a
working tree, so building from this shared developer checkout would ship whatever branch a
session left checked out. A fix reaches production through a PR, not through an edit on the box.

Why it changed twice: production first ran from this shared developer checkout, on whatever branch
a session had left it on. On 2026-08-17 that was `integrate/minimax-into-main`, 75 commits behind
`origin/main`, so the daemon executed 17-hour-old code — visible only by running `lsof` on the pid.
The 2026-08-18 cutover moved the engine to Fly and took the same question with it.

**State did NOT move, and two traps guard that.**

`PROSPECTOR_STORE_DIR` on both plists pins the catalogue, ledger, dossiers and scheduler files to
`/Users/chidionyema/Documents/code/prospector/store`. That is the canonical store. There is exactly
one.

1. **Git does not carry secrets.** The live checkout has no `.env` of its own. The first thing the
   move did was bench every MiniMax tier with `ProviderExhaustedError: All operators in ('minimax',
   'minimax_m27') unavailable — check API keys and credentials`, because the key file was simply not
   there. `.env` and `.lux/keys/agent.pem` are symlinks back to this checkout, and the probe checks
   both.
2. **A store path derived from `__file__` follows the CODE, not the store.** Four constants did
   exactly that, so for twenty minutes the provider health marks, the retrieval cache and the
   scheduler audit trail were written beside the new code while the ledger went to the canonical
   store. `config.store_root()` is the one resolver now; anything needing a store path at module
   level calls it. Never write `Path(__file__).parent.parent / "store"` again — the health file
   records which brains are benched, and a daemon writing one copy while a probe reads another can
   never see a provider recover.

## Working in a git worktree

**As of 2026-08-17 there is NO pre-commit gate in this checkout. Nothing stops a bad commit
locally. Run the gate yourself.** This paragraph has now been wrong in both directions, which
is exactly why the two commands below exist — read them, never this prose.

Measured 2026-08-17: `git config --get core.hooksPath` is empty, and
`.git/hooks/` contains only `pre-commit.DISABLED-2026-08-14` and `pre-commit.sample`. There is
no `pre-commit` file, so `git commit` runs no gate.

History, because both states have happened: the founder disabled the gate on 2026-08-14 by
moving `.git/hooks/pre-commit` aside. On 2026-08-15 at 18:57 someone set `core.hooksPath` to
`.git/hooks-active`, which symlinked `pre-commit` to `.lux/hooks/pre-commit` — and
**`core.hooksPath` overrides the hooks directory entirely, so moving the old hook aside did
nothing while it was set.** That cost a session on 2026-08-16: a commit failed with only
"exit code 1" while the doc said no gate could have refused it. The setting has since been
unset again.

Check which it is, never trust this paragraph:

```bash
git config --get core.hooksPath          # set => THAT directory wins, not .git/hooks
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
```

To actually disable it: `git config --unset core.hooksPath` (and only then does moving
`.git/hooks/pre-commit` aside take effect). To enable: point `core.hooksPath` at a directory
whose `pre-commit` links to `.lux/hooks/pre-commit`.

This cost a session on 2026-08-16: a commit failed with only "exit code 1", and the doc said no
gate could have refused it. The gate had refused it, on one test out of 4124.

**The gate CAN pass, and the number that said otherwise is dead.** This file used to carry "the
suite measures ~3185s serially against a 2400s ceiling, so the gate cannot pass". That sentence
was prose, not a measurement, and it was quoted as fact in a session on 2026-08-16 before anyone
checked it. `pytest.ini:42` sets `addopts = -n auto --dist loadfile`, so nothing runs serially.
Two timings, both real: the gate's own python-lane commands on clean `main` (`0e1e939`) measured
**1.7s of ruff plus 445.5s of pytest, 3925 passed and 3 skipped — 7m25s against the 2400s
ceiling at `scripts/popdd_verify.py:86`, 19% of it**; the merged tree on 2026-08-16, timed while
four CI jobs shared the box, measured **1281.41s, 4612 passed and 3 skipped — 21m21s, 53% of the
ceiling**. Both pass. If you are about to repeat a timing claim from this paragraph, time it
again: the suite grows, and the ceiling does not.

**Install it where git actually LOOKS.** `core.hooksPath` is set in `.git/config` to
`.git/hooks-active`, which makes `.git/hooks/` inert as a DIRECTORY — anything written there is
never read, so the re-enable line this file carried until 2026-08-15
(`ln -s ../../.lux/hooks/pre-commit .git/hooks/pre-commit`) was silently a no-op. The live
control point is:

```bash
# ON. Two deliberate choices. The target is ABSOLUTE, because the link lives in
# .git/hooks-active/ and a relative target would resolve against THAT directory. And it is the
# MAIN checkout's copy, not `--show-toplevel`, because hooks-active sits in the COMMON git dir
# and is shared by every worktree — one link, so the gate cannot be half-on.
ln -sfn "$(dirname "$(cd "$(git rev-parse --git-common-dir)" && pwd -P)")/.lux/hooks/pre-commit" \
        "$(git rev-parse --git-path hooks)/pre-commit"
# OFF
rm "$(git rev-parse --git-path hooks)/pre-commit"
```

Two things the gate now depends on, both of which fail by accusing something else. **`ruff` runs
REPO-WIDE** (`scripts/popdd_verify.py:166`), so one unformatted file anywhere walls every commit
in every worktree — `main` itself carried 12 such errors until they were cleared for this
(2b38ca3), and a worktree still sitting on an older base will fail ruff until it rebases. And
**every worktree needs `.venv` and `.lux/keys/agent.pem`**, neither of which `git worktree add`
creates; without them the gate is BLOCKED over a missing interpreter or an unsigned receipt.
`./scripts/setup_worktree.sh <path>` is the only correct way to make a worktree, and now it is
load-bearing rather than a convenience.

The wedge risk is smaller but not gone: the gate runs INSIDE the hook, so `git commit` holds
`.git/index.lock` for the whole run — now bounded at ~7.5 minutes rather than the 49 minutes that
blocked three sessions on 2026-08-14. `_run_step` kills the process GROUP and drains the pipes,
which is what fixed that specific hang. Preflight a change without committing:
`.venv/bin/python scripts/popdd_verify.py --staged`.

**One session, one worktree** still stands, for the index rather than the gate: sessions sharing
this checkout share one `.git/index`, and `git worktree add` succeeds even while that index is
locked, which is exactly the point. `scripts/popdd_verify.py::single_flight` still refuses a
second gate run in the same tree in under a second when you invoke it by hand
(pinned by `tests/unit/test_popdd_gate_cannot_wedge.py`).

For a Python-only change, skip `node_modules`: the `cp -Rc` clone is the slow part of setup
(>5 min) and the web lane never runs on a diff that contains no web files.

This checkout is often shared by two concurrent sessions, so a worktree is how you merge, build or test without touching another session's tree and index. But `git worktree add` produces a tree that **looks** complete and is not, and each gap fails by accusing something else. Always run:

```bash
git worktree add --detach ../my-worktree <ref>
./scripts/setup_worktree.sh ../my-worktree
```

It fixes four traps, each of which misdirects the diagnosis (detail: memory `worktree-setup-is-a-script-now.md`): **`node_modules` cannot be symlinked** (Turbopack rejects any symlink leaving the project root, same filesystem or not — use `cp -Rc`, an APFS copy-on-write clone); **`.lux/keys/agent.pem` is untracked**, so the shared POPDD hook runs then fails for want of a signing key, reading as a gate violation; **`.venv` is absent while `.lux/hooks/pre-commit:67` pins `.venv/bin/python` relative to cwd**, so commits die with `POPDD gate BLOCKED` over a missing interpreter (a symlink is fine here — `node_modules` is the odd one out); **`store/` and `storage/` are tracked runtime state that pytest writes to**, so never `git add -A` in a worktree.

Two more traps that outlive the setup script: `npm run build 2>&1 | tail` reports **tail's** exit status, so a failed build reads as `exit 0` — capture the build's own status before any pipe. And anything reading `<root>/.git/…` as a directory is a bug: in a worktree `.git` is a **file** containing `gitdir:`. Ask git instead (`git rev-parse --git-path hooks`, `--git-common-dir`), which also honours `core.hooksPath`; `tests/unit/test_popdd_gate_lanes.py` had exactly this defect and reported the POPDD gate uninstalled in a checkout where it was installed and working.
