# Telegram Operator Programme — requirements ledger

The founder's requirement, stated 2026-08-09: **monitor, tune, set parameters in real time,
administer, choose node priority per pipeline step with fallbacks, and have extreme visibility
into what the engine is doing at any moment — all from the Telegram agent.**

This file is the tracked status of that programme. It exists because a spec that lives only in a
chat transcript evaporates between sessions (memory: `a-spec-that-lives-only-in-a-transcript`).
Append results here, never to CLAUDE.md.

**Status is a probe, not a sentence.** Every DONE below carries the command or `file:line` that
proves it. A row with no receipt is not DONE, whatever it says.

---

## Where the code lives

| Piece | Path |
|---|---|
| Telegram gateway (the front door) | `/Users/chidionyema/.hermes/hermes-agent` |
| Live "Now" card | `gateway/operator_shell/prospector_now.py` |
| Daemon control + params | `gateway/operator_shell/prospector_daemon.py` |
| Knob groups / Tune screens | `gateway/operator_shell/cockpit.py` |
| Callback routing | `gateway/operator_shell/estate.py`, `estate_pd.py` |
| Engine state snapshot | `prospector/scheduler/status.py` |
| Engine config | `~/Documents/code/prospector/config.yaml` |

Running gateway is `launchd` job `ai.hermes.gateway`. **It serves the code it started with** —
every change below is inert until the gateway is restarted.

---

## R1 — Monitor ✅ DONE

Live card renders real engine state on demand and after every tick.

- Receipt: `render_prospector_now()` called in-process returned
  `⚙️ sleeping (27s ago · pid 25700)` / `📊 tick: 15 dossiers · 0 pass` /
  `💰 $0.00 / $20.00` / `📦 backlog: 115 deferred · 155 provisional`, matching the state probe
  independently.
- Reachable from three entry points, not just its own Refresh:
  `command_palette.py:46`, `mission.py:514`, `atlas.py:288`.
- Tests: `tests/gateway/operator_shell/test_prospector_now.py` +
  `test_every_button_dispatches.py` → 39 passed.

## R2 — Tune / set parameters in real time ✅ LIVE

> Landed `ac9a86eca6`; gateway restarted 2026-08-09 01:48 and 01:54, both times with a process
> start time later than every edited source file. The live params card reads
> `backlog_cap off · grounding gate on`, and the integrity banner that printed "running
> UNREVIEWED code" on every previous render is gone.

**Defect found and fixed: `batch_size` from the phone patched a COMMENT, not the config.**

The shipped setter ran `re.subn(r"(batch_size:\s*)\d+", ..., count=1)` over the whole file.
`config.yaml:1296` is `# \`batch_size: 15\` mints up to 15 rows per tick` — prose that quotes the
knob in assignment form, 54 lines above the real key on `config.yaml:1350`. So the setter rewrote
the comment, returned `True, "batch_size → N (config.yaml; next tick)"`, and `read_params()` read
the same comment back: the panel displayed a value the daemon had never been given. `daily_cap_usd`
escaped only because no comment carries it with a colon and a number.

- Proof of the defect: patched a copy of the real `config.yaml` with the shipped regex → diff
  landed on line 1296.
- Fix: `_yaml_assign_lines` / `_read_yaml_scalar` / `_patch_yaml_scalar` in
  `prospector_daemon.py` — comment-stripped, and **refuses to write** on 0 or >1 assignments
  rather than picking one.
- Proof of the fix, against the real `config.yaml`: `batch_size` → line 1350,
  `daily_cap_usd` → 1356, `backlog_cap` → 1350, `gate_generation_on_grounding` → 1351.
- The old fixture declared each knob exactly once, so `text.count("batch_size:") == 1` passed
  while production lied. Fixture now carries the prose shape; tests assert the assignment moved
  **and** the prose did not. `pytest tests/gateway/operator_shell/test_prospector_daemon.py`
  → **45 passed**.

**"Real time" is real, and stronger than assumed:** `code_fingerprint()`
(`prospector/scheduler/run_scheduled.py:1257-1279`) hashes every `prospector/*.py` **plus
config.yaml**, and `run_scheduled.py:1343-1347` re-execs the daemon when the fingerprint moves
(`schedule.reload_on_code_change: true`). A phone edit therefore reloads the daemon at the next
tick boundary, not just "gets read eventually".

Knobs now on the phone (`_SAFE_PARAMS`, `prospector_daemon.py`):

| Knob | Writes | Effect |
|---|---|---|
| `interval` | plist `--interval` | needs scheduler restart (done automatically) |
| `concurrency` | plist env | needs scheduler restart (done automatically) |
| `batch_size` | `config.yaml:1350` | next tick (daemon re-execs) |
| `daily_cap` | `config.yaml:1356` | next tick |
| `backlog_cap` **(new)** | `config.yaml:1350` | next tick |
| `grounding_gate` **(new)** | `config.yaml:1351` | next tick |

New `🚦 Rails` knob group in `cockpit.py` carries the two new ones (own group, because the
Prospector group is throughput and is capped at 9 buttons).

**Deliberately NOT phone-editable, with the reason** (recorded in `_YAML_KEYS`):
`min_composite_to_pass` (five occurrences; four are lane overrides at `config.yaml:377,420,486,537`
that win over the global one at `:284`, so a single value would silently not apply), the score
weights (six axes, not a scalar), `retrieval.provider` (an ordered chain — see R4), and the
pricing rungs (money rail; a price change strands fulfilment for packs already sold —
memory `price-change-breaks-fulfilment`).

**Verified 2026-08-09**: `pytest tests/gateway/operator_shell/ -q` → **655 passed, 5 skipped**.
The Rails group renders with all five buttons; the params card reads
`backlog_cap off · grounding gate on`.

Three further defects found by rendering the panels rather than reading them, all now fixed and
pinned:

- **A knob that controlled nothing.** `concurrency` wrote `PROSPECTOR_CURSOR_CONCURRENCY` into
  the scheduler plist and restarted the daemon to apply it. cursor_cli was deleted on 2026-08-06
  and **no live code has read that name since** — the engine repo carries
  `tests/unit/test_moat_resilience.py:215` specifically to assert it stays gone. The button
  moved, the confirm screen agreed, the daemon restarted, and the CLI ceiling never changed.
  Now `PROSPECTOR_CLAUDE_CONCURRENCY` (`prospector/claude_cli.py:48,62`), via a single
  `_CONC_ENV` constant so the read, the write and the confirm screen cannot name different
  variables again.
- **Two screens, two vocabularies.** The params card printed `off`/`on`; the group screen one
  tap away printed `0`/`True` for the same two knobs. `backlog_cap = 0` reads as "capped at
  nothing" when 0 means the brake is OFF.
- **A footer that promised the wrong mechanism.** Every group ended "restarts the daemon" — true
  of the two plist knobs, false of every config.yaml knob, which apply at the next tick. Now
  derived from the knobs in the group (`_apply_note`).

✅ **Live.** Gateway restarted; running pid started `01:54:00` against a newest source mtime of
`01:50:25`, so the process serves these files and not the ones it booted with in the morning.

## R3 — Administer ✅ DONE

- PAUSE armed/cleared: `prospector_daemon.py:431-437`, target verified as
  `/Users/chidionyema/Documents/code/prospector/store/scheduler/PAUSE`.
- Daemon start/stop/restart/run-now via `launchctl bootstrap|kickstart|bootout`,
  `prospector_daemon.py:888-896`. Cron run/pause at `:649`.
- All reachable through `estate_pd.dispatch` with a two-tap confirm on destructive verbs.

## R4 — Node priority per pipeline step + fallbacks ❌ NOT STARTED

Ground truth gathered 2026-08-09 (verify before building — another session is actively editing
`prospector/operator.py`):

- Chains that **are** config-driven: `config.yaml:53 operator: [claude_cli, standardcompute,
  minimax]` (verdict/moat), `config.yaml:69 artifact_operator: [claude_cli, minimax]`,
  `config.yaml:141 provider: [ddg, exa, claude_cli]` (retrieval).
- The chain that is **hardcoded in Python**: `prospector/run.py:317`
  `_NONCRITICAL_ORDER = ("standardcompute", "claude_cli", "minimax")`, consumed at
  `run.py:655,658` for generation / prescreen / score. **Making this config-driven is a
  prerequisite** — there is no per-step chain declaration in config.yaml at all today.
- Step → chain: generate/prescreen/content_gen → non-critical; query_gen/score → non-critical
  with moat fallback; verdict/adversarial/claim_check/price_comparables → moat only.
- Mechanism: `make_operator()` (`operator.py:1253-1299`) turns a list into a
  `FallbackOperator` (`operator.py:1056`) with per-brain circuit breakers.
- **The fence any UI must enforce in the writer:** the verdict chain head must be in
  `MOAT_PRIMARY` (`operator.py:1046`), else every ruling is provisional and the catalogue stops
  publishing. Already asserted by
  `tests/unit/test_moat_resilience.py::test_the_verdict_chain_is_led_by_a_trusted_brain`.

Plan: (a) add `noncritical_operator:` to config.yaml with the current tuple as default and read
it in `run.py`; (b) a `🧠 Nodes` panel listing the four chains, reorder / enable / disable per
step; (c) writer-side refusal if the verdict head leaves `MOAT_PRIMARY`; (d) mirror the existing
`brains.py` pattern (backup + audit row + undo token) since it already solves this shape for
hermes' own 13 roles.

## R5 — Extreme visibility, at any moment ❌ NOT STARTED

Today's card is a **tick-granularity snapshot**: it shows the last completed batch and the
heartbeat phase. Between ticks it cannot say which candidate or which of the six checks is in
flight. Sources that already exist and are not surfaced: `store/scheduler/batch_diagnostics.jsonl`,
`DIAGNOSTICS_LATEST.txt`, `store/scheduler/audit/*.jsonl`, the heartbeat `phase` field.
Needs a design pass — likely a per-candidate/per-check progress line written by the engine and
a live-tailing panel.

## R6 — Requirements tracked ✅ this file

## R7 — Every screen state of the art, seamless, frictionless 🟡 AUDIT DONE, 9 FIXES LIVE

> **One R7 item is left, and it is a product decision, not a wiring fix.**
> `test_every_button_dispatches.py` quarantines **15 actions** in `_UNBUILT` — `fix_all`,
> `fix_all_safe`, `onboard`, `score`, `dependencies`, `correlate`, `compliance`, `logs`,
> `estate_health`, `operator_mode`, `setup_wizard`, `rsi_run`, `rsi_pause`, `rsi_resume`,
> `deploy` — emitted from **30 literal button sites** (AST count 2026-08-09; runtime-built rows
> can only add to it). Tapping any of them renders `⚠️ Unknown action`.
> The quarantine is honest (it is ratcheted, so no new dead button can appear) but it is still
> 30 places where a cockpit button does nothing. Each needs a build-or-delete call from the
> founder; a session cannot guess which of the fifteen are wanted.

Founder, 2026-08-09: *"the whole of the ui and navigation and polish needs to be state of the
art, every screen every component, needs to be super impressive and seamless user experience and
frictionless."*

**What "state of the art" means on this surface.** The canvas is Telegram message text plus
inline keyboards — there is no CSS, no layout, no animation to design. Everything controllable is
information architecture: tap depth to any action, label→callback consistency, one shared chrome
so no screen invents its own, honest feedback on every write, undo, no dead ends, and no screen
that overflows a phone. Judging this surface by visual polish would be judging the wrong axis.

**Inventory taken 2026-08-09** (~57 render functions across `gateway/operator_shell/`). Findings,
each verified directly rather than taken from the sweep:

- ✅ **Shared chrome is near-universal, better than assumed.** Only `discovery.py`, `mdv2.py` and
  `summary_card.py` do not import `panel_chrome`, and all three are helpers, not panels. The
  sweep's claim that many panels hand-roll their own text did not survive checking.
  `panel_chrome` supplies `Group`, `compose`, `nav`, `with_nav`, `panel_stamp`, `clip`, `LEGEND`.
- ✅ **A renderer that can raise — FIXED** (`6b32ace595`, and the assert removed in `194a739f17`).
  `daemons.py` enforced an 8-button cap with a bare `assert` in the render path: tripping it
  returned no panel, and `python -O` strips asserts, so the guard was a crash in dev and nothing
  in prod. It degrades now. **Fixing it exposed a live defect the assert had been hiding**: the
  panel is *already* over cap — 3 actions + a spine that grew from 5 buttons to 6 when
  `🗂 Projects` joined it on 2026-08-06 (`panel_chrome._PROJECTS`) = 9. Nobody re-derived the
  action budget, and the block comment still budgets for 3. So *what* degradation removes became
  the real question: two drafts each lost a recovery verb (once the gateway bounce, once both
  coordinator verbs — a recovery screen that cannot recover the coordinator). It now trims
  button-by-button in declared priority order, spending the last free slot on `♻️ Restart coord`
  and dropping only `▶️ Start coord`, which `launchctl kickstart -k` (`estate.py:1511`) already
  covers for a stopped job. Both recovery callbacks are pinned by test. **Founder decided
  2026-08-09: "raise it."** The cap is now the named constant `MAX_BUTTONS = 9` (`782d707e35`),
  restoring the three action slots the panel was designed around. The trim stays and still binds —
  the point of a cap is that something principled happens at the boundary, not that the number is
  8 — and `test_every_declared_verb_fits_now_that_the_cap_is_nine` fails loudly if a future spine
  eats another slot, instead of quietly hiding a verb again. Proven live against the running tree
  (pid 54384, started 02:27:47, newest source mtime 02:06:52):
  `MAX_BUTTONS 9 | rendered 9`, rows
  `[['♻️ Bounce gateway'], ['♻️ Restart coord', '▶️ Start coord'], [6-button spine]]`,
  `trimmed: False`.
- ✅ **A read that writes — FIXED** (`194a739f17`). `_save_daily_snapshot` is called from
  `render_otto_health`, and appended to `velocity.jsonl` unconditionally: opening the screen was
  a write. Measured live before the fix — 76 rows across 4 dates, 60 of them `2026-08-02` —
  while `_velocity_data` returned `entries[-14:]` under a comment reading "last 14 days", feeding
  a panel labelled *"14-day trend"*. The advertised 14-day trend was 14 **rows** spanning 3 days,
  11 bars re-sampling one day, and every tap made it worse. Writer upserts per date via
  tmp+replace; reader collapses per date, which repairs history already written without
  rewriting the operator's audit file underneath them. Proven live: 3 consecutive renders left
  the row count at 77 and the trend now draws 5 points for 5 dates.
- ✅ **Same thing, two names — PAID DOWN TO 0, AND THE SCANNER'S BLIND SPOT FOUND**
  (`7a83bdcd59` measured, `3d268f70de` paid down; gateway pid 70470 restarted 296s after the
  newest edit, so it serves this code). 81 label rewrites across 23 modules, derived from one
  canonical name per callback rather than hand-typed, so no site could be missed and none
  renamed twice. `BASELINE = 0` — the ratchet is absolute now. Four survivors are *declared*
  rather than renamed (`_DESIGNED`): sdlc.py's four are STAGE names in a pipeline the panel
  prints and glosses on screen (`*5. Ship* — CI / builds / deploys`), and two client-facing
  surfaces say Contact/Feedback because a client has never seen an "Inbox".
  **Then the scanner was taken at its word, and rendering all 46 panels found what it is
  structurally blind to.** `cockpit.render_run` put **two buttons both labelled `♻️ Restart` on
  one screen** — one restarting the signal engine, one the Prospector scheduler. Each sits under
  its own `Group` heading, which reads as unambiguous in the source and is not: headings live in
  the message TEXT, a Telegram inline keyboard is one flat grid, so on a phone they were two
  identical adjacent buttons that restart different daemons. The same blind spot hid
  `💵 Spend` vs `💵 Spend cap` (`cockpit._TUNE_GROUPS` is a **3-tuple**, and the scanner only
  walks 2-tuples) and `📦 Prospector` for `tune:prospector` colliding with `🔭 Prospector` for
  the daemon panel. Both guards therefore ship: `test_destination_vocabulary.py` asks whether a
  destination has one name; `test_no_screen_says_one_word_twice.py` renders the whole cockpit
  and asks whether a name has one destination — the only one that sees what reaches the phone.
  Its first version rendered nothing (every call raised) and reported "0 conflicts", so it now
  carries a floor of 40 rendered panels; a gutted sweep fails instead of going green. Mutation
  check: restoring the `♻️ Restart` collision fails it with the offender named.
  Receipts: 671 passed, 5 skipped in `tests/gateway/operator_shell/`.
  *Method note for the next session: grepping for design never found any of the three worst
  ones. Rendering every panel and reading the keyboards did.*
- 🟡 **Same thing, two names — the original measurement** (`7a83bdcd59`). My earlier claim that
  `estate:room:code` is labelled `2️⃣ Board` in the room **did not reproduce** — both call sites
  (`atlas.py:245`, `fleet.py:173`) read `💻 Code room`. The real finding is larger: an AST scan
  of every `(label, "estate:…")` pair finds **39 of 153 callbacks carrying more than one label**,
  after exempting labels whose whole job is contextual (Cancel / Home / Refresh / Back).
  `estate:otto_health` alone is reachable as *Otto health*, *Health*, *Details*, *Dashboard* and
  *Self-audit*. Renaming 39 destinations across 30 modules in one change is how a navigation
  regression ships, so `tests/gateway/operator_shell/test_destination_vocabulary.py` ratchets it:
  the count may fall, never rise. Fixed now, being two glyphs for one verb inside a single row:
  `mission.py:501` `🔄 Restart Coord` → `♻️ Restart coord`. **The remaining 39 are the next
  session's R7 work, and are mechanical now the scanner exists.**
- ✅ Destructive verbs are confirmed (daemon stop/start/restart, signal-engine stop, the hot-rail
  two-screen `arm_card`), and `estate:approve:{id}` is deliberately one tap because the
  coordinator already gated it.

Three R7-class defects were already fixed under R2 above (a knob that controlled nothing, two
screens with two vocabularies for one knob, a footer naming the wrong apply mechanism) — the same
class the audit is for, found by rendering the panels instead of reading them. **Rendering every
panel and reading the output is the method; grepping for design never finds these.**

---

## Defects raised alongside the requirements

| # | Defect | Status |
|---|---|---|
| D1 | Gateway venv missing `python-json-logger`; every card render logged `moat_blind_reason failed`, so a `🔴 moat blind` card would show no reason. Blast radius checked: `moat_blind` itself comes from `provider_health.json` (`status.py:171`), so the 🟢/🔴 verdict was always sound. | ✅ **LIVE.** Installed, gateway restarted, and `moat_blind_reason failed` / `No module named 'pythonjsonlogger'` occur **0** times across all five gateway logs since. |
| D2 | `brains.py` (628 lines) + `undo_ops.py` (134) untracked in `gateway/operator_shell/`; the shell's own integrity check prints "running UNREVIEWED code" on every render. | ✅ **LANDED** as one commit, `ce8b8270cb` (13 files, +1545/-32), with `undo_ops.py` and its three untracked test files. The integrity banner no longer prints. |
| D3 | Running checkout dirty. | ✅ **LANDED.** It was the 🤖 Brains feature — finished-but-uncommitted, not broken: 1,293 new lines plus 252 wiring lines, fully wired and reachable. Two `tests/hermes_cli` failures were proven pre-existing by call graph, not assumed: they read `telegram_bot_commands()` (:376) and `slack_native_slashes()` (:324), while the WIP's only production change is `telegram_menu_commands` (`hermes_cli/commands.py:925-937`). Left uncommitted deliberately: `cron/scheduler.py` (unrelated) and `docs/audits/`. |
| D4 | ~~`set_role_model` honours a replayed `brains_set:approval\|<key>` with no confirmation — the fence lives in the keyboard.~~ **Corrected on re-verification: the fence IS in the writer** (`brains.py:213 fence_check`, called at `:353` before any write, with the docstring *"Enforced in the WRITER, never only in the keyboard"*). The accurate statement is narrower: the fence ships **unarmed**, because `_allowlist_for` (`:191`) returns `None` when no `operator_shell.role_model_allowlist` is configured, and `brains.py:76` records that which models may arbitrate approvals is a founder policy call. | ✅ **DECIDED AND LIVE** (`782d707e35`). Founder 2026-08-09: *"claude code, and needs to self heal when out of credits."* Arming the allowlist alone would **not** have delivered that, and saying it did would have been the fence reporting green while open. Two holes: (i) `fence_check` permits `auto` by design, and `auto` inherits the agent-brain default, which is DeepSeek (`brain.py:51`); (ii) `call_llm` **silently substitutes providers** when the configured one is unhealthy or returns a payment error (`agent/auxiliary_client.py:2981,3028,5571`) — so a selection-time fence fails open at exactly the moment it exists for. Closed at the point of use: `_smart_approve` (`tools/approval.py:1069`) now checks the model that **answered** and returns `escalate` when it is off the list — never auto-approve, never `deny`. That is also the self-heal: escalation parks the decision for a human, and the 600s provider-health TTL (`auxiliary_client.py:2314`) routes the next call back to Claude unattended. Unknown/unreported model ids fail closed; an unreadable fence is a closed fence. One reader (`hermes_cli.config.role_model_allowlist`) for two enforcement points, because a policy with two readers drifts. Live proof: `role_model_allowlist('approval') -> ['opus','sonnet','haiku']`, unfenced roles still `None`, `fence_check('approval','minimax') -> (False, '…refused')`, `deepseek-v4-pro`/`MiniMax-M3`/`''` all `allowed=False`. `approvals.mode` is `manual`, so blast radius today is zero — which is when to build a fence, not a reason to skip it. Pinned by `tests/test_approval_role_fence.py` (8 tests); 907 passed / 5 skipped across the full blast radius of both symbols. |
