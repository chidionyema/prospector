# Content Contract Programme

> Read this before touching `prospector/pack_linter.py`, `prospector/run.py`'s repair or content
> phase, `prospector/bridge.py`'s lint gate, the `listing.*` knobs in `config.yaml`, or adding
> anything to `tools/` that repairs published packs.
>
> Top half is the diagnosis and the design. Bottom half is the implementation ledger. Append
> results to the ledger, never to the diagnosis — the diagnosis is dated evidence, not a plan.

## Why this exists

On 2026-08-17 the engine held 34 PASS packs that no one could buy. Every one of them was made
in the previous three days, and every one was made *after* the rule that blocked it. This is not
old stock waiting for a backfill. The engine was actively producing unsellable packs, at full
cost, and had been doing so for as long as the rules had existed.

The first diagnosis was wrong, and how it was wrong is the point. It said the blocking checks had
no upstream caller, so nothing could fix a field before the gate saw it. The caller map refuted
that within the hour: the two biggest blockers, `check_title` (20 packs) and `check_shelf_copy`
(15 packs), both have callers in `run.py` and `bridge.py`. Having a caller is not the property
that matters.

The property that matters is *when* the rule is applied and *what happens when it fails*.

## §1 The diagnosis, measured

### 1.1 A buyer-facing field is written once and judged once, at opposite ends of the line

A title and a one-liner are written free-form by the generator. Generation asks two questions
about them and neither is about quality: does the `title` key exist (`generate.py:55`), and are
title and one-liner together over 50 characters (`generate.py:599`).

They are then carried untouched through prescreen, verify, kill filter and score. Every one of
those stages judges the *idea*. None reads the words a buyer will see.

They are judged for the first time at the publish gate (`bridge.py:1102`), after a ~7,700-word
pack has been generated, vetted and paid for.

So the maker is a prose prompt and the grader is code, and nothing holds the two together. **The
generator cannot fail.** It has no grader. Drift between the two is not a risk here, it is the
default state.

### 1.2 The self-correcting loop is barred from the two fields that block the most packs

Content generation retries up to three times when a pack comes out unsellable
(`run.py:958`). Title and one-liner are excluded from what that loop grades, deliberately and
with a good local reason (`run.py:700-703`): they come off the Candidate, so regenerating the
pack's copy cannot change them, and grading them inside the loop would escalate to the expensive
chain over fields no regeneration touches.

The local reasoning is sound. The system-level consequence is that the only self-correcting
mechanism in content generation is structurally unable to touch the two fields responsible for
35 of the 34 stranded packs (a pack can fail more than one check).

### 1.3 A repair that cannot succeed still buys the pack

`_repair_title` (`run.py:697`) and `_repair_one_liner` (`run.py:802`) were added on 2026-08-17
and do the right thing: same prompts and same bars as the live-shelf sweep, moved upstream of the
spend. They are best-effort by contract, and a failed repair is swallowed so a PASS is never lost.

When the repair exhausts its attempts it logs, in these words, *"building the pack on its own
title, which the publish gate will refuse"* (`run.py:793-798`), and the engine then builds the
~7,700-word pack anyway.

At that moment the system knows the pack is unsellable and spends the money regardless. Nothing
routes the candidate back, nothing parks it, nothing flags it. It surfaces days later as a number
on a dashboard, and the only way back is a person running a script.

### 1.4 Rules are promoted by hand, one at a time, and each promotion strands what came before

A new check is introduced in measure-only mode because the engine already breaks it. The reason
is written at `bridge.py:1178`: 43.9% of engine sentences already break house rule R1, so a style
knob defaulting to on "would unlist the catalogue the first time someone deployed".

That is the correct call for any single check. As a *process* it means every rule spends an
unbounded period switched off, and turning it on strands every pack made in the interval.

Promotion does happen — `title_block_on_breach: true` (`config.yaml:1759`),
`shelf_copy_block_on_breach: true` (`config.yaml:1783`), `lint_grammar: true`
(`config.yaml:1610`) — but it happens because a person remembered, measured, and edited a config
file. `lint_repetition_block` (`config.yaml:1636`) is still off with its baseline uncollected.
There is no mechanism that promotes a rule the engine has stopped breaking, and no mechanism that
tells anyone a rule is ready.

### 1.5 The cure is a script, and the engine does not get the fix

`tools/` holds 13 hand-run repair and backfill scripts: `retitle_catalogue.py`,
`sweep_shelf_copy.py`, `backfill_pack_currency.py`, `backfill_listing_copy.py`,
`backfill_archived_url.py`, `backfill_audience.py`, `backfill_facets.py`, `backfill_market.py`,
`backfill_bundle_html.py`, `backfill_missing_listings.sh`, `recover_stranded_passes.py`,
`publish_passes.py`, `_backfill_driver.py`. One file per fire.

The divergence this causes was already written into the source by an earlier session
(`run.py:895-897`): *"`tools/publish_passes.py:228` has had this loop since it was written; the
daemon's own path never got it, and the daemon is what produces packs."* The repair tool gets the
fix. The engine does not. That was found once, fixed for one check, and never made a rule.

### 1.6 Nothing shipped is the same as nothing built

The upstream repair described in §1.3 is real, tested and committed — and on 2026-08-17 it was
absent from `origin/main` and absent from the production checkout at
`/Users/chidionyema/Documents/code/prospector-live`. It sat in an open pull request whose CI was
failing. Production had never run a single line of it.

The state probe prints `daemon has <sha>, disk has <sha>` on every session start. Nothing acts on
that line. A design that fixes §1.1–§1.5 and does not fix this changes nothing about what buyers
can buy.

## §2 The design

One idea. **A rule is a contract on a field, enforced at the moment that field is written.**

The publish gate stays exactly where it is, but its job changes from primary enforcement to
regression guard. A block at the gate becomes an alarm that something upstream failed, not the
normal way defects are found.

### P1 — One registry of field contracts

Every buyer-facing field declares, in one place: the checks that apply to it, the repair that
fixes it, and its enforcement level.

Today this knowledge is spread across 13 loose check functions, ad-hoc call sites in six modules,
and five independent booleans in `config.yaml` and code defaults. No one can read "what does
sellable mean" without reading all of it.

The registry is the answer to that question, and it is the single input to P2, P3 and P5.

### P2 — Enforcement moves to the field write

One choke point that every buyer-facing field write passes through: grade, repair, re-grade,
record. The repair is the same code that repairs the live shelf.

This is not a new pattern. It exists correctly once already, for shelf copy: `shelf_copy_repair`
holds one definition of clean and serves two callers, the live sweep and the engine. P2 is that
shape generalised, so the next rule gets it by construction instead of by someone repeating the
move by hand.

### P3 — The generator is handed the checker, not a description of it

The rule text rendered into the generation prompt comes from the same registry the checker reads.
Change a rule once and both ends move.

This is what permanently closes §1.1. As long as the prompt carries its own prose copy of the
rules, the two definitions will drift again, and the drift will only ever be visible as stranded
packs.

### P4 — An unrepairable field parks the candidate instead of buying the pack

When the repair exhausts its attempts, the candidate is parked with the named breach, before the
artifact phase.

The backlog stops being finished unsellable stock and becomes cheap parked candidates with a
reason attached. Same information, a fraction of the cost, and re-enterable the moment the rule
or the repair improves. §1.3's log line becomes an action.

### P5 — Rules ratchet on, with the console as the actuator

A new rule runs in shadow automatically. Its breach rate is recorded per batch. When the rate has
held at zero for a declared number of batches, the rule is marked **ready to promote** and the
operator promotes it from the ops console.

The ratchet only turns one way. Nothing has to be remembered, and nothing turns itself on. This
is the founder's decision of 2026-08-17: the ratchet prepares the promotion, the console approves
it. That matches the standing principle that anything changeable is changed by the operator from
the console, not by a config edit.

### P6 — Refusals feed back

Every breach is recorded per field, per rule, per batch. That record is what drives P5's ratchet,
and it is the only signal that can ever improve generation itself rather than patch its output.

### P7 — The shipping fence

The gap the state probe already prints — daemon SHA versus disk SHA versus `origin/main` — becomes
a blocking condition rather than a line of text, surfaced on the ops console with the age of the
divergence. See §3.

## §3 Ops console visibility

The console is where this programme is legible or it is not legible at all. Four things it must
show:

1. **Stranded now, by rule.** The count, split by which rule blocks it, with the age of the
   oldest. This is the headline number for the whole programme.
2. **Breach rate per rule, per batch.** The shadow measurements from P6. A rule trending to zero
   is a rule about to become promotable.
3. **Rules ready to promote.** P5's output, with the evidence (batches at zero, sample size) and
   the button that promotes it.
4. **Shipping gap.** Daemon SHA, disk SHA, `origin/main` SHA, and how long they have disagreed.

## §4 How we know it worked

The stranded count goes to zero and stays there across batches with nobody running a script.

That is the only measurement that counts. On 2026-08-17 progress was reported as "two blocker
classes removed from the linter" while the stranded count was 34 before and 34 after. Removing a
check is a side effect. Packs on the shelf is the outcome. Report the outcome.

## §5 Implementation ledger

Append here. Each entry: what shipped, the receipt, and the stranded count before and after.

| # | Part | Status | Receipt |
|---|------|--------|---------|
| 0 | Upstream title/one-liner repair (§1.3) | in PR #285; CI was red on three failures, two fixed by #282's merge, one real | `run.py:697,802,950` |
| P1 | Registry of field contracts | **shipped** | `prospector/content_contract.py`; 34 tests in `tests/unit/test_the_content_contract_covers_every_gate_knob.py`; `console_api._shelf_repair_for` now reads it |
| P2 | Enforcement at the field write | not started | — |
| P3 | Generator reads the registry | not started | — |
| P4 | Park instead of buy | not started | — |
| P5 | Ratchet + console promotion | not started | — |
| P6 | Breach recording | not started | — |
| P7 | Shipping fence | not started | — |
| C1 | Console: stranded by rule | **ALREADY EXISTS** — do not rebuild | `console_api.py:823` `_read_shelf` returns `by_reason`, `by_repair`, `stale_verdicts`; rendered on `shelf.tsx` |
| C2 | Console: breach rate per rule | not started — blocked on P6 | — |
| C3 | Console: rules ready to promote | not started — blocked on P5 | — |
| C4 | Console: shipping gap | partly in flight in PR #286 (console build age) | `scripts/live_checkout.py` |

Two things the console already does that this programme must build on rather than beside:

- `_read_shelf` (`console_api.py:823`) is the stranded survey, and it deliberately loads
  `tools/verify_pass_shelf_coverage.py` instead of reimplementing the question, so the console and
  the tool cannot drift. Any new reader here follows that rule.
- `_SHELF_REPAIR` (`console_api.py:805`) already maps a blocking reason to the console action that
  repairs it, with `manual` as the honest default. That map is the seed of P1's registry — it is
  the same reason-to-repair relationship, written for one consumer instead of all of them.

The console also already gets the receipt-staleness problem right (`console_api.py:851-863`): a
stored lint verdict outlives the rules that produced it, so a pack can read as blocked long after
its rule stopped blocking. P5 and P6 must not reintroduce that. Any recorded breach carries the
ruleset version that produced it.

### P1 as built, 2026-08-17

`prospector/content_contract.py` declares 21 rules. Each names the checks' fields, the repair,
the `lint_pack` keyword that switches it on and the `listing.*` config key wired to that keyword.
It imports nothing from the engine, so the gate, the generator, the repair path and the console
can all read it without a cycle.

Three things worth writing down, because each was a defect caught while building it:

1. **The config key and the gate keyword are different words for a third of the rules.**
   `lint_grammar` actuates `grammar_enabled`; `house_spec_block_register` actuates
   `register_block`. The first draft carried a single `actuator` field, which is a defect that
   reads as working: every lookup still returns something and the something is wrong. They are
   now `config_key` and `gate_param`, and
   `test_every_declared_config_key_is_the_one_the_gate_is_wired_to` reads the actual keywords out
   of the `lint_pack(...)` call in `bridge.py` as a syntax tree and fails on a mismatch. Proven to
   fail on both real conflations before it was kept.

2. **The registry is checked against the gate, never trusted over it.** The guard reads
   `inspect.signature(pack_linter.lint_pack)`, finds the ten actuator-shaped keywords, and fails
   if one is undeclared. Proven by deleting the `repetition` rule and watching it name
   `repetition_block`. This is what stops the registry becoming a fourth list to forget, which
   is the §1.4 failure repeated one level up.

3. **What repairs a rule and what the console can do about it are different questions.** Only two
   console actions exist, `shelf.repair_copy` and `shelf.publish_pending`.
   `engine.regenerate_artifacts` is the true repair for nine rules and is not built. The registry
   states the true repair, because P4 and P5 need it; `console_repair_for_check` degrades to
   `manual` for anything unwired, because that is what the operator can act on. Answering the
   second question with the first produces a button that does nothing.

`_SHELF_REPAIR`, the console's private reason-to-repair map, is gone.
`console_api._shelf_repair_for` routes on the parsed check names through the registry, falls back
to lifecycle phrases for a pack that was never published, and keeps the old substring match as a
last resort so no row loses its button. A pack that is both unpublished and breaching a rule
routes to the rule fix first: publishing it while it breaches only strands it again.

### Baseline, 2026-08-17

Stranded PASS packs: **34**. By rule: title 20, shelf_copy 15, citation_urls 4, empty artifacts 2,
placeholders 1, never gated 1. A pack can fail more than one. All 34 made within three days of
the measurement. Source: the project state probe and
`.venv/bin/python tools/verify_pass_shelf_coverage.py`.
