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
| L8 | Graphify as a context substitute | injection capped at **700 tok**; refresh costs **0 tok** (both proven) — but the number of round trips it replaces **MEASURED 2026-08-06 as ~1** (A/B, n=3: medians within 0.4%) | **ENFORCED LIVE 2026-08-06** (4 triggers); cost-NEUTRAL, saving REFUTED at this n — kept for freshness + a 3/3 vs 2/3 accuracy signal | `scripts/graphify_sweep.py` (exit 0 = enforced); A/B below |

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

**MEASURED 2026-08-06 — the saving did NOT replicate. Do not quote one.** The `(N−1) × $0.1192`
arithmetic below assumed injection collapses several exploratory round trips into one. Run on a
real multi-hop question, it collapsed **one run in three**, and the mean saving is entirely that
one run. See "the A/B result" below. The hypothesis text is kept because the arithmetic is still
correct *given* an N > 1 — what is refuted is that this injection delivers one.

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

**The A/B result (2026-08-06).** Harness `tools/l8_ab.sh` + `tools/l8_grade.py` +
`tools/l8_summary.py`, raw rows in `docs/measurements/l8_ab_2026-08-06.jsonl` — all committed,
because a measurement whose harness lived in a session scratchpad cannot be re-run or checked
(§3 still cites `scratchpad/ab_harness.sh`, which no longer exists anywhere; do not repeat that). One fixed multi-hop question ("name the function that
makes the scheduler skip a tick when every trusted brain is dead, its file:line, and the field it
reads"), 3 reps per arm, `env -u ANTHROPIC_API_KEY claude -p --output-format json`, counters from
the API. Arm A = `GRAPHIFY_HOOK_OFF=1` (explores with Read/Grep); arm B = hook live. The control
switch is real and was verified before spending: `graphify_session_hook.py:81` and
`graphify_query_hook.py:124` both early-return on it — without that, arm A is not a control.

| arm | n | mean | median | turns | correct |
|---|---|---|---|---|---|
| A control (no graph) | 3 | $0.2092 | $0.2081 | 4.0 | 2/3 |
| B graph injected | 3 | $0.1966 | **$0.2090** | 3.3 | 3/3 |

**Read the median, not the mean.** Mean ratio B/A = 0.940 looks like a 6% saving, but the medians
are within 0.4% and the entire mean difference is ONE run — B rep2 finished in **2 turns for
$0.1702** while the other five runs all took 4 turns regardless of arm. Injection short-circuited
exploration once out of three attempts. That is an N of roughly 1, not the multi-round-trip N the
saving arithmetic needs.

**The one thing that did move: correctness.** Arm A rep3 answered without `_moat_blind_reason`
(the function name — the actual question); arm B got all three anchors on every rep. Grading was
mechanical against ground truth fixed before the runs, so this is not a post-hoc read. It is n=3
and cannot carry a significance claim, but it points the other way from cost: the case for
injection here is *accuracy*, not spend.

**Honest status: graphify is cost-NEUTRAL and enforcement is free.** Those two together still
justify it — a free freshness rail that does not cost tokens is worth having — but "graphify saves
money" is refuted at this n and must not be quoted. To overturn this, run more reps and vary the
question class; a single question measures a single retrieval shape.

*Method note, paid for in cash:* v1 of this harness inlined the grader as `python3 -c '…'`
containing an f-string with escaped double quotes. The shell passed the backslashes through and
Python raised `SyntaxError: unexpected character after line continuation character` at compile
time — i.e. *after* each `claude -p` call had already been billed. Six calls, zero rows written.
The grader and summariser are now separate files, smoke-tested on fixtures before any paid run.

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
