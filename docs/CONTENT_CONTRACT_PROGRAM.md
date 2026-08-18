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

#### P4 as built, 2026-08-17

**It ships measure-first, and the default is a decision.** `run._unrepaired_shelf_breaches` grades
the title and one-liner one last time after `_repair_shelf_lines`, on the gate's own checkers, and
logs every breach at ERROR with `shelf_unrepaired: True`. It only skips the pack when
`listing.park_unrepairable_shelf_lines` is on, and that key defaults to **False**
(`config.LISTING_DEFAULTS`). The reason is that parking is not free in the way it first looks:
buying a pack the gate refuses wastes the deliverable chain, but parking turns a PASS into a pack
that does not exist. Which is cheaper is a count, and the log is what produces the count before
anyone pays for the answer. A test pins the log OUT of the `if _park:` branch, because a log that
only fires once the switch is on can never justify the switch.

**The grader asks the gate, it does not restate it.** The title goes through
`pack_linter.check_title(title, max_chars=TITLE_MAX_CHARS)` filtered to `severity == "error"`; the
one-liner through `shelf_copy_repair.voice_breaches` plus the `_ONE_LINER_CUT_AT` length.
`test_the_grader_agrees_with_the_publish_gates_own_title_check` asserts the two produce the
identical list for the same title, so a cap moving in the linter cannot leave the park behind.

**A parked candidate is stamped, never silently empty.** `cand.tags["shelf_parked"]` carries the
breaches. An empty artifacts dict with no reason is a failure shape this repo has already had
(memory `learning-empty-artifacts-root-cause.md`); the tag is what lets the stranded-pack scan and
the ops console tell a deliberate park from a breakage.

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
| 0 | Upstream title/one-liner repair (§1.3) | **MERGED** — PR #285 is on `main` and running in production | `run.py:697,802,977` |
| P1 | Registry of field contracts | **shipped** | `prospector/content_contract.py`; 34 tests in `tests/unit/test_the_content_contract_covers_every_gate_knob.py`; `console_api._shelf_repair_for` now reads it |
| P2 | Enforcement at the field write | **shipped** — one loop, one grader per field; `run.py`'s two hand-written repair loops are now three-line declarations | `prospector/field_write.py`; 19 tests in `tests/unit/test_one_choke_point_grades_every_buyer_facing_field.py`; the 34 behaviour tests in `test_a_breached_title_is_repaired_before_the_pack.py` pass unchanged |
| P3 | Generator reads the registry | **shipped** | `generate._shelf_line_directive`; 5 tests in `tests/unit/test_the_generator_is_told_the_shelf_rules.py` |
| P4 | Park instead of buy | **shipped, measure-first** — logs always, parks only when `listing.park_unrepairable_shelf_lines` is on (default off) | `run._unrepaired_shelf_breaches`; 15 tests in `tests/unit/test_the_engine_does_not_buy_a_pack_the_gate_will_refuse.py` |
| P5 | Ratchet + console promotion | **promotion shipped** — 10 generated console switches; the automatic ratchet is still manual | `console_api._content_rule_knobs`, group `content` |
| P6 | Breach recording | **shipped as a READER** — nothing new is written; the counts were already in the 123 `*.lint.json` receipts | `prospector/ops/content_breaches.py`; 22 tests in `tests/unit/test_content_breach_rates_come_from_the_receipts.py` |
| P7 | Shipping fence | not started | — |
| C1 | Console: stranded by rule | **ALREADY EXISTS** — do not rebuild | `console_api.py:823` `_read_shelf` returns `by_reason`, `by_repair`, `stale_verdicts`; rendered on `shelf.tsx` |
| C2 | Console: breach rate per rule | **shipped** — served on both doors AND rendered on the Stranded page | `console_api._read_content_rules` in `READS`; `'content_rules'` in `VIEWS` (`pages/api/ops/read/[view].ts`); the panel in `shelf.tsx`, pinned by `test_a_page_actually_fetches_it` |
| C3 | Console: rules ready to promote | **shipped** — `ready_to_promote`, `never_observed` and `undeclared` all rendered | `content_breaches.breach_report`; second card in `shelf.tsx` |
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


### P6 as built, 2026-08-17

**It writes nothing.** The counts were already on disk. The publish gate leaves a
`store/dossiers/<id>.lint.json` per pack it grades, each carrying `problems`, each problem naming
its check. 123 receipts, 10,704 findings. `prospector/ops/content_breaches.py` reads them. A second
recorder beside a receipt that already exists is how a dashboard gets two numbers for one fact, and
the older one is usually the one people trust.

**A rule that never ran looks exactly like a rule with a clean record.** Both are zero, and P5
promotes on zero. That is the defect that would have made this module worse than useless, because
promoting an unobserved rule puts a gate nobody has seen fire onto the money path. `breach_report`
splits them: `ready_to_promote` requires evidence the rule has fired at least once in history AND a
clean streak across every graded day; everything else with no findings goes to `never_observed`,
which is a question for a human. `RuleBreaches.rate()` returns `None` rather than `0.0` when
nothing was graded, for the same reason.

**Blocking vs shadow is not in the receipt.** The same `house_quote` finding refuses a pack when
`house_spec_block_quotes` is on and is a note in a file when it is off, so the split comes from
`content_contract.blocking_checks(listing_cfg)` at read time. The module never restates a switch.

**What it says about the live store right now** (2026-08-17, 123 graded packs, 3 grading days):

| check | enforced | packs | rate | findings |
|---|---|---|---|---|
| `house_style` | shadow | 120 | 98% | 4,633 |
| `house_quote` | shadow | 120 | 98% | 2,803 |
| `human_register` | shadow | 120 | 98% | 300 |
| `register` | shadow | 112 | 91% | 425 |
| `grammar` | **blocking** | 111 | 90% | 111 |
| `repetition` | shadow | 106 | 86% | 1,600 |
| `citation_urls` | **blocking** | 85 | 69% | 254 |
| `register_repeat` | shadow | 72 | 59% | 286 |
| `shelf_copy` | shadow | 61 | 50% | 110 |
| `title_new_word` | **blocking** | 51 | 41% | 51 |
| `title` | **blocking** | 21 | 17% | 27 |

Two things to read off it. The shadow rules are not idle — `house_style` and `house_quote` fire on
98% of packs, so promoting either today would strand almost the whole catalogue, which is the
measurement P5's ratchet exists to respect. And `ready_to_promote` is empty: nothing has both a
history of firing and a clean recent streak. Three grading days is not enough evidence yet, and the
module says so rather than offering a promotion it cannot justify.

**Coverage, stated on the panel.** One receipt per pack GRADED, not per pack generated — a
candidate that never reached the gate is not in the denominator. `by_day` is keyed on when a pack
was linted, so a re-lint backfill lands on one day.


### P5 as built, 2026-08-17 — promotion, not yet the ratchet

**The switches are generated from the registry, not typed out.** `console_api._content_rule_knobs`
reads `content_contract.RULES` and emits one console knob per CONFIG KEY, giving 10 switches in a
new `content` group. Typing 24 near-identical entries by hand is how a console ends up offering a
switch the gate no longer reads, or missing one it does.

**One knob per switch, not per rule, and the label says so.** `title_block_on_breach` moves
`title` AND `title_claim`; `house_spec_block_register` moves `register` AND `register_repeat`. The
label names every rule the switch promotes, so an operator turning one on can see they are
promoting two checks rather than the one they came for. A test pins that.

**What is NOT built: the automatic ratchet.** P5 as specified also promotes a rule automatically
once its breach rate has held at zero for a declared number of batches. That is deliberately not
shipped. `ready_to_promote` is computed and empty, and it is empty for a good reason — three
grading days of receipts is not enough evidence to auto-arm a gate on the money path. The
threshold belongs in config once there is enough history to choose it, and choosing it now would
be picking a number to make a table look finished. The operator promotes from the console today,
with the rate in front of them.

**`title_new_word` has no switch, and that is correct.** It carries no `config_key` because
nothing in `lint_pack` gates it — it is enforced unconditionally. It shows as blocking at 41% in
the table above. A knob for it would be a control that does nothing.

## P2 as built, 2026-08-17 — one loop, one grader per field

**The defect was a rule typed out twice, not a missing repair.** The engine already repaired its
shelf lines. What it did not have was one place that said what clean meant. Measured before the
change:

- `run.py:827` and `run.py:882` both carried the one-liner length bar, as the same sentence
  written twice, twelve lines apart. One copy was in the repair, the other in the park check P4
  added.
- `_repair_title` and `_repair_one_liner` were two hand-written copies of the same four-step
  loop. They differed only in which checker and which rewriter they called.

Two copies of a rule do not raise when they drift. They start disagreeing, and the disagreement
shows up as a pack the engine graded clean and the publish gate refused, after the pack was paid
for. That is the same failure P4 exists to prevent, arriving through a different door.

**What shipped.** `prospector/field_write.py` holds the loop once — grade, repair, re-grade,
record — and each field is a declaration:

```python
"one_liner": Field(name="one_liner", noun="one-liner",
                   read=..., write=..., grade=grade_one_liner,
                   propose=_propose_one_liner, attempts=1, skip_when_empty=True)
```

`run._repair_title` and `run._repair_one_liner` are now three lines each. They stay as named
functions because `_generate_pack_content` and its tests reach them by module attribute.
`run._unrepaired_shelf_breaches` is one line: `field_write.breaches(cand, "title", "one_liner")`.
The park check and the repair now ask the *same object*, not a matching one.

**One behaviour change, and it is a tightening.** A one-liner rewrite used to be re-graded on
length only, because `rewrite_one` already re-graded voice. It is now re-graded on the full
grader. A rewrite that fixes the voice and blows the length was previously accepted; it is now
refused. Pinned by `test_the_rewrite_is_regraded_on_every_bar_not_just_the_one_that_failed`.

**How we know nothing was lost.** The 34 behaviour tests in
`tests/unit/test_a_breached_title_is_repaired_before_the_pack.py` were not touched and pass
against the refactor. The new tests are about identity, not behaviour: same grader object on both
doors, the length bar appearing exactly once in the tree, and no field repair growing its own
attempt loop again.

**What P2 does NOT do.** `tools/retitle_catalogue.py:408` still writes a live catalogue title
through its own path. That is the live-shelf repair tool, not the engine, and moving it is a
separate change with its own blast radius — it writes rows that are already published. The engine
side is closed.

## P3, 2026-08-18 — the title and one-liner journeys, traced end to end

Written after a repair spent 23 minutes and $0.059 and produced nothing. The two fields turned
out to be on the same rails with different wiring, and only one of them worked.

### The two journeys, in order

| | **title** | **one-liner** |
|---|---|---|
| born | generation, then `run._generate_pack_content` | same |
| graded by | `field_write.grade_title` → `pack_linter.check_title` | `field_write.grade_one_liner` → `shelf_copy_repair.voice_breaches` + the length bar |
| the bar | `TITLE_MAX_CHARS = 60` (`pack_linter.py:689`) | `ONE_LINER_CUT_AT = 280` (`field_write.py:47`) |
| rewritten by | `_propose_title` → `prompts/retitle.md` | `_propose_one_liner` → `shelf_copy_repair.rewrite_one` |
| the bar in the prompt | renders `{max_chars}` (`retitle.md:85`) | **carried its own number: 200** |
| rejection reaches the model | yes, `feedback=feedback` | **no, the argument was dropped** |
| attempts | 2 | **1** |
| written to the shelf | `bridge.py` catalogue row | `bridge.py:843`, then cut at 280 by `bridge.py:878` |
| live-shelf repair | `tools/retitle_catalogue.py` | `tools/sweep_shelf_copy.py`, `tools/repair_stranded_shelf_lines.py` |

Every cell in bold is a defect, and all three are in the same column. The title path already had
the design; the one-liner path had a copy of the number, a retry that could not fire, and a
feedback string that was assembled and thrown away.

### What the machine knew and never said

`field_write._reject_feedback` exists to quote a refusal verbatim, counts included — its own
comment says "a vague 'too long' gets a draft one character shorter". For the one-liner it was
never sent. `_propose_one_liner` took a `feedback` argument and did not pass it on, and the field
was declared `attempts=1`, so the loop computed the rejection on its way out and discarded it.
Three attempts at that pack therefore sent three identical prompts.

### The obvious fix was measured, and it does not work

The first fix written for this was to render `ONE_LINER_CUT_AT` in the prompt, so 280 replaced
200 and the two numbers could not drift. Run live against the same model and the same line, only
the number changing:

```
limit=200   601s   no answer at all — the streamed response hit the 600s deadline
limit=280   254s   a 320-character line — over the gate anyway
```

A number in the prompt does not control the length of the reply, because the model cannot count
its own characters. Raising it turns a stall into a wrong answer. That branch was dropped.

### The 280 itself is right, and that was checked too

Across the 2,805 dossiers in `store/dossiers/` that carry a one-liner, 217 are over 280. Replaying
`bridge.py:878` over them: **215 are a single runaway sentence** that the bridge would cut with an
ellipsis, which `check_shelf_copy` then refuses as "trails off on the shelf". Only 2 would be cut
cleanly on a sentence boundary. So the gate is not stricter than the defect it mirrors — 0.9% of
the population is gated for nothing, and loosening it would trade that for silently dropping a
whole sentence of sourced facts.

### What shipped

The character count came out of the ask and went into the loop:

- `shelf_copy_repair.USER` states no length. It says "keep it as short as the facts allow" and
  "do not count characters; if it comes back too long you will be told by how much".
- `rewrite_one` measures the answer it got and, when it is over `ONE_LINER_CUT_AT`, re-asks with
  the exact overage — "it is 320 characters and the shelf cuts at 280, so it needs to lose 40
  characters without losing a fact". That figure is arithmetic on the reply, which is the one
  thing only the machine can supply.
- `rewrite_one` takes a `feedback` argument and puts it in the prompt.
- `_propose_one_liner` passes `_reject_feedback` through to it.
- `MAX_ONE_LINER_REPAIR_ATTEMPTS = 2`, so the informed retry can fire at all.

Pinned by `tests/unit/test_the_machine_counts_the_characters_not_the_model.py`: no character
count in the template, the overage arithmetic in the second prompt, the feedback reaching the
prompt, a clean answer never re-asked, and the attempt count above one.

### The next link: the runaway call was the only call with no label

CLOSED 2026-08-19, issue #360. The paragraph that used to sit here said the fix was a per-call
`max_tokens` parameter threaded through every operator's `_raw`. That was the wrong answer, and
the reason is worth keeping.

An unsatisfiable ask still costs 600 seconds. `operator.py` gave every MiniMax call
`max_tokens: 65536` from one process-wide environment variable, so a one-sentence rewrite got the
same budget as a full dossier and billed all of it when it ran away.

That ceiling could not simply be lowered. Measured over the 33,553 `event: "spend"` records in
`store/prospector.jsonl`, MiniMax output tokens per call:

| stage | n | p50 | p95 | max |
|---|---:|---:|---:|---:|
| generate | 480 | 32,094 | 65,536 | 70,017 |
| **(no stage)** | **5,015** | **1,601** | **15,652** | **55,522** |
| content_gen | 1,217 | 5,626 | 24,615 | 47,934 |
| claim_check | 2,147 | 1,755 | 7,282 | 47,146 |
| query_gen | 1,494 | 1,262 | 4,800 | 38,673 |
| score | 164 | 2,016 | 3,012 | 15,911 |
| artifacts | 212 | 3,706 | 9,451 | 15,583 |
| price_comparables | 140 | 1,111 | 3,183 | 8,210 |
| verdict | 5,252 | 390 | 1,160 | 6,591 |
| adversarial | 140 | 711 | 2,217 | 5,794 |
| prescreen | 935 | 646 | 972 | 1,611 |

`generate` uses the whole ceiling. `verdict` never needs a tenth of it.

The mechanism to tell them apart already existed: `telemetry.stage()`, a contextvar recorded on
every spend row by 14 call sites. **The two calls outside one were `shelf_copy_repair.py`'s
rewrite and `field_write.py`'s title repair.** The call that spent 23 minutes and $0.059 is
therefore inside that 5,015-row `(no stage)` bucket, indistinguishable from a full generation.
The same missing label made it invisible to the ledger and impossible to bound.

So the fix is one change, not two. Both sites declare a stage, and
`operator.minimax_max_tokens_for_stage` resolves the ceiling from the stage in force —
config-declared at `config.yaml retrieval.minimax_max_tokens`, installed process-wide from
`config.load_config`, with `PROSPECTOR_MINIMAX_MAX_TOKENS` still overriding everything so an
incident is capped from the plist without a deploy. Each ceiling is the next power of two at or
above twice the observed maximum.

An undeclared stage keeps 65536. Narrowing blind is the expensive direction: a clipped answer
raises `_MiniMaxTruncated` and buys two more full-budget retries. The two newly-labelled repair
stages get no ceiling yet, deliberately — they have never been measured, because they were never
labelled, and the number follows the data.

Pinned by `tests/unit/test_minimax_max_tokens_is_per_stage.py`, which also fails if any
`complete_json` on the publish path is outside a stage, with a non-vacuity floor so a rename
cannot make it green by scanning nothing.

