# Claude Code token playbook — cut weight, keep (or improve) quality

Measured from your real transcripts on 2026-06-02. **Baseline: 30.05B token-weight,
98.0% cache-hit, and 98% of cost-weight is in marathon sessions.** Caching is already
near-perfect — it is NOT your leak. The single lever is `turns × resident_context`.

Hard rule: every item here is **quality-neutral or quality-positive**. Nothing downgrades
the model on work that needs reasoning. Cutting stale context can make Opus reason *better*
(less "lost-in-the-middle" distraction), so the cut and the quality goal point the same way.

---

## 1. The one habit that fixes 98%: session hygiene

Your worst session: **9,425 turns · 4.2 days · ~967K max context · only 5 compactions = $6,884.**
Every one of those turns re-billed the full context. The fix is not technical — it's:

- **`/clear` when you switch to a different task.** A fresh session drops days-old context you
  no longer need. This is lossless to the *current* task and is the highest-leverage action you can take.
- **NEVER `/compact` as a cost move.** Measured §5: one compaction = **$2.53** (253,484 tok written
  at 2×); `/clear` = **$0**. Compact only when the thread genuinely cannot be reconstructed from a
  handoff — and if a handoff can carry it, write the handoff and `/clear` instead.
- **Don't run one session for days.** One session per task/day, not per week.

### What's now in place to support this
- **Statusline (live):** shows `■ ctx 685K  /clear or /compact` — context size goes yellow at 200K,
  red at 400K. You'll *see* it climbing now (before, it was invisible — that's why it hit 967K).
  Script: `~/.claude/scripts/statusline-context.py`, wired in `~/.claude/settings.json`.
- **Active reminder — ON since 2026-06-10** (verified 2026-07-30: `~/.claude/settings.json` →
  `hooks.UserPromptSubmit` → `context-guard-hook.py`). Now **v2**, and it no longer watches context
  size alone (v1's 250K/400K thresholds are obsolete — `CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000`
  caps context, so sessions die LONG, not fat). v2 watches session SHAPE
  (`context-guard-hook.py:20-26`): resident ≥130K warn / ≥170K hard, ≥25 prompts, ≥20MB transcript,
  ≥8h age. Two signals (or one "strong" one) → it injects the `[session-guard]` instruction to write
  a handoff to `checkpoints/LATEST.md` and hand over a one-keystroke `/clear`
  (`context-guard-hook.py:120-129`). Costs ~70 tok when it fires, silent otherwise, never blocks.

---

## 2. Drop the never-used MCP connectors (pure tax, 100% lossless)

Gmail / Drive / Calendar inject **16 tool schemas into every request** and were invoked
**0 times across all your transcripts**. That's per-request weight for nothing.

- Run **`/mcp`** in Claude Code and disconnect Gmail, Google Drive, Google Calendar (or disconnect
  them in the claude.ai connector settings). Re-add only if you actually start using them.
- Prefer CLI tools (`gh`, `gcloud`) over MCP equivalents — CLI tools add **0** schema to context.

---

## 3. Keep Opus for thinking; offload grunt-work to subagents (lossless)

You're 97.5% Opus — keep it, that's your reasoning. The lossless move is to push **mechanical**
work into subagents so their verbose output never lands in (and re-bills from) your main context:

- Big multi-file searches / "where is X" sweeps → `Explore` subagent.
- Running a test suite, scraping docs, parsing logs → a subagent (use Sonnet/Haiku for these —
  the *summary* returns to your Opus thread, so reasoning quality is unaffected).
- One of your sessions had 2,605 Bash calls all kept resident — that's exactly what subagents prevent.

This keeps the main thread lean (smaller resident context = cheaper *and* sharper) with zero
quality cost, because the hard reasoning still happens on Opus over a cleaner window.

---

## 4. Prove it (before / after)

The measurement tool is `~/.claude/scripts/cc-token-report.py` (read-only, no network):

```bash
python3 ~/.claude/scripts/cc-token-report.py                 # all-time
python3 ~/.claude/scripts/cc-token-report.py --since 7d      # rolling window
python3 ~/.claude/scripts/cc-token-report.py --json out.json # machine-readable
```

Baseline snapshot saved: `~/.claude/scripts/baseline-20260602.json`.

**Proof protocol:** work normally for a week with the statusline on + the `/clear` habit + MCP dropped,
then run `--since 7d` and compare to the baseline. Expect: marathon-session share collapses, median
resident context per session drops sharply, MCP tax → 0. Output quality is unchanged-or-better because
the same models do the same reasoning over a leaner context.

---

## 5. Update 2026-07-30 — the cost model is now exact, not estimated

`cc-token-report.py` measures token-weight. The new companion measures **dollars**, because Claude
Code writes its own ledger and it can be reproduced arithmetically:

```bash
python3 ~/.claude/scripts/token-audit.py -Users-chidionyema                 # per-session $ + floor/median/peak
python3 ~/.claude/scripts/token-audit.py -Users-chidionyema --detail 288cc  # per-request + driver split
```

Validated against `~/.claude.json` → `projects."/Users/chidionyema".lastModelUsage.costUSD`, to 7 s.f.:

| model | arithmetic | ledger |
|---|---|---|
| `claude-opus-5[1m]` | `1855*5 + 8758361*0.50 + 264169*10.00 + 62384*25` = **$8.5897455** | `8.589745499999998` |
| `claude-haiku-4-5` | `1124*1 + 301741*0.10 + 29951*1.25 + 4439*5` = **$0.09093185** | `0.09093184999999998` |

Three facts follow from those exact matches, and two of them were NOT known on 2026-06-02:

1. Cache reads bill at **0.1×** base input. (Confirms the 2026-06-02 finding that caching is not the leak.)
2. **The main loop writes cache at 2.0× (1-hour TTL); subagents write at 1.25× (5-minute TTL).**
   So §3's "offload to subagents" is cheaper on the *write* side too, independent of model tier —
   a second, previously unmeasured reason the rule works.
3. **`[1m]` bills at plain $5/$25 — there is no long-context premium.** Any plan premised on the
   1M-context variant being the cost driver is wrong. It isn't. `turns × resident_context` still is.

Measured on 2026-07-30 (4 sessions, $45.56 total). Worst session, 236 requests, $22.90:
`cache_read 53.8% · cache_write 25.2% · output 20.9% · raw_input 0.0%`. **79% of spend is
re-reading context already paid for.** Supporting numbers:

- Fixed floor = **34,238–36,527 tokens at request #1**, before anything is asked. Re-billed every
  request: 35k × 236 × $0.50/MTok = **$4.13/session just to exist**.
- **Zero tool batching**: 1.00 `tool_use` blocks per assistant turn across 71 tool turns. N
  sequential calls = N+1 requests; k batched into one turn = 2. Each avoided round-trip saves
  107,584 × $0.50/MTok = **$0.054**.
- **One compaction = $2.53** (253,484 tokens written at 2×). `/clear` = **$0**. This is the price tag
  on §1.
- A single 5k-token file Read at request 20 of a 236-request session costs 5,000 × 216 ×
  $0.50/MTok = **$0.54**. That is the price tag on §3 — and why `ls -la` dumps (two of them, 7.2 KB
  and 7.0 KB, were left resident) are not free.

### Applied 2026-07-30
- `~/.claude/settings.json`: dropped `swift-lsp@claude-plugins-official` (0 `.swift` files and 0
  `Package.swift`/`.xcodeproj` in the estate — pure floor tax) and set
  `stripe@claude-plugins-official` to `false` (its only two tools are `authenticate` /
  `complete_authentication` and it was never authenticated; live Stripe work is done with `curl` +
  the API key, which per §2 adds **0** schema). Both are one-line reversible.
- `~/.claude/projects/-Users-chidionyema/.state-probe`: 5 lines, 0.46 s, injected at SessionStart so
  a new session opens with verified live state instead of re-deriving it. Re-derivation was costing a
  full recon sweep per session.
- `checkpoints/LATEST.md` cut 16,197 B → ~4,600 B (it is injected every session).

### Still open — the one measurement that would close the floor question
**HYPOTHESIS:** the `claude-in-chrome` MCP server (24 tool names + server instructions, injected
every request) is a large share of the ~29k of harness floor that is not accounted for by the
markdown files (~6k). It is not in `settings.json` — it comes from the Chrome extension, so only
`/mcp` or disabling the extension removes it. **CHECK:** disable it, start a fresh session, ask one
trivial question, then compare the `floor` column from `token-audit.py`. Costs ~$0.02 and is decisive.

**HYPOTHESIS:** the subscription "% used" figure is not provably proportional to these dollars.
**CHECK:** read `/usage` immediately after a session ends and pair the % delta with `lastCost` from
`~/.claude.json`. Two paired points give the $-per-% constant, which converts every number above
into "sessions remaining".

---

## What was deliberately NOT done (and why)
- **No model downgrade on real work** — would risk reasoning quality. Opus stays.
- **No memory trimming** — the per-session memory floor is only ~3.5K tok (index only; big rule files
  load on recall, not every turn). Trimming risks losing saved guidance for <1% gain. Not worth it.
- **No cache tweaking** — your cache-hit rate is already 98%. Nothing to gain.

## §6 — Measured 2026-07-30 (session 02742eb3, Fable 5)

- Typical session (d5044ede, 42 reqs, $2.95) driver split: cache_read 44.1% / output 30.0% /
  cache_write 25.9% / raw_input 0%. Context grew 36,931 → 98,765 tok in 42 reqs (~1.5k/req).
  Per-request cost roughly doubles start→end ($0.045 → $0.098): RESIDENT GROWTH is the compounding
  cost, and tokens added EARLY cost the most (re-billed on every later request).
- Floor 36,931 tok with claude-in-chrome DEFERRED (24 names, no schemas) = highest floor recorded.
  Chrome-MCP-floor hypothesis bounded to ~1–1.5k of 37k → effectively dead. Free decisive floor
  decomposition: `/context` in a fresh session.
- Checkpoint injection: `memory-loop.py:22` INJECT_BUDGET = 8,000 chars. LATEST.md was 9,229 —
  open-items tail silently truncated every session. Keep LATEST.md < 8,000 chars (check:
  `wc -c .../checkpoints/LATEST.md`).
- Batching remains the untaken lever: 1.00 tool_use/turn measured. One avoided request ≈
  median_ctx×0.1× read + new-token write at 2× ≈ $0.05–0.10. Batch every independent call.
