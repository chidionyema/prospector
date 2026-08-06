# COST PROGRAM — the single tracked record of Claude Code cost work

**Status: ACTIVE.** This is the canonical doc for every cost-optimisation claim, lever and
measurement across the estate. Any agent (Claude, Gemini, DeepSeek, pi/MiniMax) working on cost
reads this FIRST and appends here. A number that is not in this file is not a tracked number.

**Scope:** the whole estate (prospector, hermes, store_platform, all `~/Documents/code/*`), even
though the file lives in the prospector repo — prospector is the versioned, pushed repo.
Companion spec: [GRAPHIFY_ENFORCEMENT_SPEC.md](GRAPHIFY_ENFORCEMENT_SPEC.md).

---

## 0. Rules of evidence (violating these has already produced two wrong headlines)

1. **Dedup by `message.id` before summing anything.** Claude Code splits ONE assistant turn across
   multiple `.jsonl` records that share a `message.id` and each repeat `usage` byte-identically.
   Counting per-record inflates spend ~1.9x and makes every turn look like a single-call turn.
   Both estate scripts now group by `message.id`; both keep a `--per-record` flag that reproduces
   the old wrong numbers so the gap stays auditable.
2. **Compare WARM-to-WARM only.** Cache warmth swamps every other effect: identical work measured
   $0.01342 fully-warm and $0.16584 cold in the same experiment. Never compare a cold run to a
   warm one and call the difference a saving.
3. **Counterfactuals are token-matched.** Re-price the SAME tokens on the other model. Naive
   $/request ratios are wrong because traffic mixes differ in cache share (68.1% vs 89.6%).
4. **Ratios survive scale bugs; absolutes do not.** When the 1.9x double-count was fixed, the
   saving *percentage* moved 37.4% → 37.2% but every dollar figure fell by half. Prefer ratios.
5. **`cmd | tail` reports tail's exit status.** Capture the real status before any pipe. This has
   caused a failing build and a failing probe to read as `exit 0`.

---

## 1. Levers — measured value and live status

Status vocabulary: **LIVE** (in effect, proven) · **CONFIGURED** (set but not in effect) ·
**MEASURED** (value known, not implemented) · **UNPINNED** (cause not yet established).

| # | Lever | Measured value | Status | Verify with |
|---|---|---|---|---|
| L1 | Default model Opus → Sonnet | **0.601x steady state = 39.9% saving**; $344.51/day on the corrected base | **CONFIGURED, NOT LIVE** | `~/.claude/scripts/cost-guard-probe.sh` (exit 0 = live) |
| L2 | Session floor (CLAUDE.md ×2 + MEMORY.md) | **18,294 tok = 41% of every prompt**; **$0.0055 per warm request** | PARTIAL — 12,595 tok vs 12,000 budget | probe `floor` lines |
| L3 | Batching (one round-trip per intent) | headroom ≈ **2,947 requests/day** by merging single-call turns 3→1 | MEASURED, unenforced | `~/.claude/scripts/batching-compliance.py` |
| L4 | Delegating recon to haiku subagents | ceiling **~4.7%** of spend (read-only turns are 5.5% of turns) | LIVE (standing-authorized) | memory `delegation-is-a-4-percent-lever-model-default-is-40.md` |
| L5 | `pi_execute` dispatch (MiniMax executor) | dispatch is **unmetered**; wins when plan << code | LIVE, opt-in per task | `~/.claude/mcp/README-pi-bridge.md` |
| L6 | Daemon cold-cache gap | **$0.2650/req vs $0.0937/req** interactive | **UNPINNED** — `WorkingDirectory` is stable, so fresh-cwd is REFUTED | see §4 |
| L7 | Dead `ANTHROPIC_API_KEY` in inherited env | outranks the subscription; raw API returns *credit balance too low* | **NOT CLEARED** in live processes | probe `auth` line |
| L8 | Graphify as a context substitute | injection capped at **700 tok**; refresh costs **0 tok** (both proven) — but the number of round trips it replaces is **UNMEASURED** | **ENFORCED LIVE 2026-08-06** (4 triggers); saving still MEASURE NEXT | `scripts/graphify_sweep.py` (exit 0 = enforced); A/B below |

### L1 is one action from shipped
`settings.json` declares `"model": "sonnet"` (mtime 2026-08-06 14:19:22) but **settings.json is read
once at process start** — `/clear` mints a new session *inside* the same process and never re-reads
it. Measured 2026-08-06 17:51: **6 of 8 live `claude` processes predate the config** (oldest
2026-07-31 19:32) and **94% of requests in the last 3 transcripts are `claude-opus-5`**.
**Required action (founder only): quit Claude Code entirely and relaunch from a NEW terminal** —
a new terminal is also what drops the dead `ANTHROPIC_API_KEY` (L7); it survives only in the
inherited env of long-lived processes, no rc file sets it (`env -i` proof).

---

### L8 — what is proven about graphify's economics, and what is not

Proven 2026-08-06, by execution rather than by documentation:

- **Keeping the estate fresh is free of tokens.** `graphify update` completed a full refresh of a
  stale repo in **46.5s with `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` both unset**. Only the
  community-*labelling* path (`label`, `cluster-only`) touches an LLM; 3 of 49 package modules
  reference one at all. So estate-wide auto-refresh is a CPU cost, not a token cost.
- **Injection cost is bounded and local.** `graphify query` is a BFS over `graph.json` with
  `--budget N` capping output at **2,000 tokens by default**. No inference in the query path.

**Not proven — do not quote a saving yet.** How many exploratory round trips a query actually
replaces (call it N) is unmeasured. Today's measured unit cost is **$927.00 / 7,774 = $0.1192 per
request**, ~79% of it re-transporting resident context, so the saving is roughly `(N−1) × $0.1192`
minus a one-off ≤2,000-token injection. That is arithmetic on an unmeasured N, i.e. a HYPOTHESIS.

**What enforcement itself costs (spec R12, measured 2026-08-06).** The point of this row is that
turning enforcement on estate-wide did not quietly buy the saving with a new recurring cost:

| component | token cost | wall/CPU cost | how it stays known |
|---|---|---|---|
| `graphify update` refresh (post-commit, SessionStart, launchd) | **0** — 8 repos refreshed with `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` unset, all exit 0 | 5.6s (vault-201) → 260.2s (haworks-platform, 2,278 files); always **detached**, so no commit and no session ever waits on it | it is CPU, and CPU here is free |
| SessionStart `[graphify]` line | ~100 tok, **once per session** | 1.21s | one line, fixed shape |
| `UserPromptSubmit` injection | **≤700 tok**, only on codebase-shaped prompts (chatty prompts inject nothing — negative control run) | 4.6s query | every injection appends `{ts, repo, chars, est_tokens, query_seconds}` to `~/.claude/graphify-inject.log`, so the real daily cost is a `jq` away rather than an estimate |
| launchd backstop | 0 | ~6s assessment per 30 min, `Nice 5` + `LowPriorityIO` | `launchctl list \| grep graphify` |

The injection is the only component that can grow, which is why it is capped and logged rather
than trusted. The cap started at 1,200 and was cut to **700** the same evening: a real prompt
returned 337 nodes as a flat list and spent the whole budget, with the useful rows in the first
~25. Paying 2,000 tok per codebase prompt for that would be a cost regression wearing a feature's
clothes.

**The experiment that settles it** (reuses `scratchpad/ab_harness.sh` from the model A/B): one
fixed codebase question, 3 reps each, `claude -p --output-format json`, counters from the API.
Arm A explores with Read/Grep. Arm B gets the `graphify query` result pre-injected. Compare total
tokens **and** whether arm B's answer is correct — a cheaper wrong answer is not a saving. Result
goes in §2 as an L8 row.

## 2. Cost ledger — append one row per measurement day

Method: `~/.claude/scripts/cost-baseline.py --date=YYYY-MM-DD` (note the `=`; argparse eats a bare
leading dash). Cross-check with `batching-compliance.py`; a <2% gap is scope, not disagreement.

| date | priced req | day total | $/req | opus share | sonnet counterfactual | note |
|---|---|---|---|---|---|---|
| 2026-08-06 | 7,774 | **$927.00** | $0.1192 | ~94% | $344.51/day (37.2%) | corrected, dedup by `message.id` |
| _(next day after relaunch)_ | | | | | | **the proof L1 shipped** |

**Retired numbers — DO NOT QUOTE.** These circulated before the dedup fix and are ~1.9x too high:
`$1,749.36/day`, `$654.22/day`, `14,398 priced requests`, `$1,765.71`, and the batching compliance
figures `2/5302 = 0.0%` and `17.7%`. The **0.601x model ratio is unaffected** — it came from
headless `claude -p` runs whose counters came straight from the API, never from transcripts.

---

## 3. How savings are proven (the protocol, not an opinion)

1. **A/B on real requests**, identical prompt, `env -u ANTHROPIC_API_KEY claude -p …
   --output-format json`, usage counters from the API. Harness: `scratchpad/ab_harness.sh` +
   `parse_run.py`; raw rows in `scratchpad/results.jsonl`. Run ≥3 reps; steady state is reps 2-3
   (rep 1 pays cache warm-up).
2. **Estate baseline before and after**, same weekday if possible, via `cost-baseline.py`.
3. **Record both in §2** with the exact command used.
4. A lever is only **LIVE** when a probe prints it green — never when a doc says so.

---

## 4. Open problems

- **L6 daemon cold-cache gap is UNPINNED.** Leading theory (fresh cwd per CLI call) is **refuted**:
  launchd `WorkingDirectory` is the stable repo root. Next candidates, untested: no prompt-cache
  reuse across separate `claude -p` invocations; per-call system prompt differences; cache TTL
  expiry between 2h ticks. Prospector is ~99.4% of estate burn, so this is the largest unpinned item.
- **Enforcement scripts are unversioned.** `~/.claude/.git` does not exist, so
  `cost-guard-probe.sh`, `cost-baseline.py` and `batching-compliance.py` cannot be committed,
  pushed, reviewed or restored. See GRAPHIFY_ENFORCEMENT_SPEC.md §G-VCS — the same gap blocks both
  programmes.
- **The probe is not wired to anything.** It exits 1 correctly today, but nothing runs it; a lever
  can silently stop being live between manual runs.

## 5. Decisions needed from the founder

| id | decision | recommendation |
|---|---|---|
| D1 | Floor is 12,595 tok vs a 12,000 budget. Closing it means deleting operating rules; the gap is worth ~$1.30/day. | Raise the budget constant to 12,600 and record why. Do not cut rules for a rounding error. |
| D2 | Version `~/.claude` as a git repo with a strict `.gitignore` (excludes `projects/`, credentials, history, shell snapshots). | Yes — it is the only way the enforcement scripts become "committed and pushed". |
| D3 | Whether the graphify auto-refresh (see companion spec) may spend tokens, and how much per day. | Cap it; measure it into §2 like any other lever. |

---

*Changelog: created 2026-08-06 by Claude (Opus 5). Every subsequent edit appends to §2 and dates
its claim.*
