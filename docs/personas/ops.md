# Ops: the operator's complete control surface

**What this is:** every button, lever, probe and scheduled job an operator can touch, with the
code that reads each one.
**Read this if** you are about to change what the system does — pause it, publish something,
move a price, roll production forward, or run any tool from the console.
**Measured:** 2026-08-18. Every number and path below came from a command run that day.

**Siblings:** [`sre-on-call.md`](sre-on-call.md) · [`../LOGGING_AND_RETENTION.md`](../LOGGING_AND_RETENTION.md) · [`../OPS_AUTOMATION_PRINCIPLES.md`](../OPS_AUTOMATION_PRINCIPLES.md)

---

## Part 0 — Read this before anything else: the machine layout changed today

Three measurements taken this session contradict the operating rules in `CLAUDE.md`. Establish
where you are before you touch a lever, because half the levers below act on a Mac that is no
longer running the work.

### 0.1 Only one launchd job is loaded

```
$ launchctl list | grep -E '^\S+\s+\S+\s+com\.prospector\.' | sort -k3
-	0	com.prospector.backup
```

One job. `com.prospector.scheduler`, `com.prospector.consumer`, `com.prospector.watchdog` and
`com.prospector.ops-console` are **not loaded**. The producer loop, the drain loop, the watchdog
and the console are all down on this machine.

### 0.2 The documented production checkout does not exist

`CLAUDE.md` states production runs from `/Users/chidionyema/Documents/code/prospector-live`, and
`scripts/live_checkout.py:31` hard-codes that path as `LIVE`.

```
$ ls -d /Users/chidionyema/Documents/code/prospector*
/Users/chidionyema/Documents/code/prospector
```

The directory is absent. `scripts/live_checkout.py:222-224` handles this: it prints
`MISSING: <path>` and returns 1. So the estate's own production probe reports failure by design,
correctly.

### 0.3 There is a `prospector-engine` app on Fly that this repo does not know about

```
$ fly apps list
 prospector-engine    │ personal │ deployed  │ 1h21m ago
 ...

$ fly volumes list -a prospector-engine
 vol_42kyqo6g0kdzew14 │ created │ prospector_store │ 20GB │ lhr │ ... │ 12 hours ago

$ fly ssh console -a prospector-engine -C "sh -c 'du -sh /data/* 2>/dev/null'"
44M	/data/state
558M	/data/store
156K	/data/store.old

$ rg -c "prospector-engine" -g '!node_modules' -g '!graphify-out' . | wc -l
0
```

A live engine, redeployed 1h21m before measurement, holding 558M of store on a volume created
12 hours earlier, with a `store.old` beside it — and zero references anywhere in this
repository.

### 0.4 Confirmed: the engine moved to Fly on 2026-08-18

The three measurements above are one event, not three faults. The engine migrated from this Mac
to Fly. The laptop launchd jobs and `prospector-live` were retired **by** that move, so their
absence is expected.

The engine is running. Its own heartbeats say so, read at wall clock `2026-08-18T13:15:18Z`:

```
$ fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"
{"ts": "2026-08-18T13:15:26.521057+00:00", "mono": 5739.806007703, "pid": 679,
 "phase": "sleeping", "interval_s": 7200, "cycles": 1, "beat_every_s": 60,
 "slept_s": 3840, "code": "617c2538c433"}

$ fly ssh console -a prospector-engine -C "cat /data/store/scheduler/consumer_heartbeat.json"
{"ts": "2026-08-18T13:13:14.563675+00:00", "pid": 680, "role": "consumer",
 "phase": "skipped", "cycle": 8,
 "skipped_reason": "moat blind: every brain it can rule with is marked dead
                    (claude_cli for 2859s more, minimax for 0s more)", ...}
```

Producer sleeping between 2-hour ticks, consumer skipping on a blind moat that is about to
clear. Both healthy.

**What this changes for you as operator, in three lines:**

1. **The store is at `/data/store/` on `prospector-engine`, not `store/` on this Mac.** Every
   lever below that is a file — `PAUSE`, `PAUSE_GENERATION` — must be created there, not here.
   `touch store/scheduler/PAUSE` on the laptop now pauses nothing.
2. **`scripts/live_checkout.py` is a trap.** It probes the retired setup and reports
   `NOT RUNNING` / `MISSING:` for things that are supposed to be gone. Acting on that output
   means restarting a laptop daemon that must never come back — it would be a second writer on a
   store the Fly engine already owns. Full runbook: [`sre-on-call.md`](sre-on-call.md) §3.10.
3. **"Which code is production running" is now the `code` field in the heartbeat**
   (`617c2538c433` above), compared against `git rev-parse --short origin/main`. Not a checkout
   path on a laptop.

Everything else in this document — the dispatcher, the fence, the 81 tools, the risk taxonomy,
the knobs, the invariants — is unchanged. It is the same code. Only the host moved.

---

## Part 1 — The console: one door, one contract

### 1.1 Why it is shaped this way

The ops console is a Next.js app. It cannot import Python. So it does not try. It spawns one
dispatcher and speaks JSON to it:

```
python -m prospector.ops.console_api <verb> [args]
```

`prospector/ops/console_api.py` is 2548 lines and is the entire control plane. Its module
docstring states three rules that explain every design decision in it:

- **"No metric is computed here."** The dispatcher reads other modules. It does not invent
  numbers, so the console and the CLI cannot disagree.
- **"Reads cannot write."** The verb in argv is the fence. A `read` invocation has no code path
  to a write, regardless of what the payload says.
- **"Writes need a confirmation token, and the token check is HERE, not in the UI."** A browser
  is not a security boundary. Anyone can call the dispatcher directly, so the check lives where
  the work happens.

Constants:

| Constant | Value | Location |
|---|---|---|
| `CONTRACT_VERSION` | `1` | `console_api.py:62` |
| `SALT_FILENAME` | `.console_salt` | `console_api.py:67` |
| `CONFIRM_TTL_S` | `600` | `console_api.py:71` |

### 1.2 Verbs and exit codes

Verbs: `read`, `act`, `views`, `actions`, `run-tool`.

`dispatch` at `console_api.py:2422-2538` returns:

| Exit | Meaning |
|---|---|
| 0 | ok |
| 1 | exception |
| 2 | bad args or unknown verb |
| 3 | `RefusedByDesign` |
| 4 | `ConfirmationRequired` |

Exit 3 and exit 4 are different on purpose. 4 means "ask me again with a token". 3 means "this
will never be allowed, stop asking".

`_quiet_stdout()` at `console_api.py:81-97` captures stray prints from imported modules so a
debug `print()` in some library cannot corrupt the JSON on stdout. Without it, one stray line
turns every console page into a parse error.

### 1.3 The write fence, step by step

1. The console calls `act` with no `confirm` token.
2. The dispatcher builds a **preview**: what will change, and what undo will cover.
3. It returns exit 4 `ConfirmationRequired` with a token.
4. The operator confirms. The console calls `act` again with the token.
5. `_valid_tokens` (`console_api.py:1316-1319`) accepts the current **and** previous time
   window, so a confirmation that straddles a window boundary does not fail spuriously.
6. The action runs. A receipt is written to `store/ops/intents.jsonl`.

The token is `sha256(salt + action + canonical_payload + window)`, truncated to 20 hex
characters (`_token`, `console_api.py:1293-1302`). `_canonical` (`:1305-1313`) deliberately
excludes `nonce`, `confirm` and `actor` from the hash, so a token covers **what** will happen
and not who asked or when they clicked.

**Refusals are logged too.** A refused action is an operator intent, and an audit trail that
only records successes cannot answer "did someone try".

---

## Part 2 — Complete tool inventory

### 2.1 How the registry is built

Every tool row is produced by `_t()` at `console_api.py:2187-2203`:

```python
def _t(path, purpose, writes, screen, run=True, danger=None, cmd=None, risk=None):
    if risk is None:
        risk = "local" if writes else "read"
    if risk not in RISKS:
        raise ValueError(f"{path}: risk={risk!r} is not one of {RISKS}")
    command = cmd or f".venv/bin/python {path}"
    ident = hashlib.sha1(f"{path}|{purpose}|{command}".encode()).hexdigest()[:10]
    return {"id": ident, "path": path, "purpose": purpose, "writes": writes,
            "screen": screen, "run": bool(run) and risk != "shell",
            "danger": danger, "risk": risk,
            "undo_covers": {"read": "nothing is written",
                            "local": "everything this writes",
                            "external": "the local half only",
                            "shell": "n/a"}[risk],
            "command": command}
```

Three things worth noticing:

- **The id is derived, not assigned.** `sha1(path|purpose|command)[:10]`. Change the command and
  the id changes, which is what stops a button from silently pointing at different work.
- **`undo_covers` is looked up from `risk`, not written by hand.** The two cannot disagree.
- **`risk="shell"` forces `run=False`.** A tool declared unrunnable cannot be made runnable by
  passing `run=True`.

### 2.2 The risk taxonomy

`RISKS = ("read", "local", "external", "shell")` — `console_api.py:2184`.

| Risk | Writes? | What undo covers | Meaning |
|---|---|---|---|
| `read` | no | "nothing is written" | reports only |
| `local` | yes | "everything this writes" | touches `store/` only; a snapshot restores it fully |
| `external` | yes | **"the local half only"** | reaches Stripe, the live shelf, R2 or a public source |
| `shell` | yes | "n/a" | a daemon; launchd owns it; not runnable from the console |

**`external` is the one that matters.** It is an honest label on a real limit: undo restores
`store/`, and nothing in this repo can un-charge a card, un-publish a page someone already
loaded, or un-delete an R2 object. A tool marked `external` has a half that is permanent.

### 2.3 The shape of the registry, measured

```
$ .venv/bin/python -c "from prospector.ops import console_api as api; ..."
TOOLS COUNT: 81
SCREENS: ['/', '/audit', '/catalogue', '/engine', '/metrics', '/queue', '/runs', '/shelf', '/spend', '/tools']
RISK SPREAD: {'read': 39, 'local': 18, 'external': 22, 'shell': 2}
WRITES: {False: 39, True: 42}
NOT RUNNABLE: ['prospector/scheduler/run_scheduled.py', 'prospector/consumer.py']
```

81 tools. 39 read-only, 42 write. **22 are `external`** — over a quarter of the registry can do
something undo cannot reverse. The only two unrunnable rows are the two daemons, which is
exactly right: launchd owns their lifecycle, and a console that could start a second producer
loop would create two writers on one store.

### 2.4 The full table

Format: `id | risk | writes | path — purpose`.

#### Screen `/` (overview)

| id | risk | w | path | purpose |
|---|---|---|---|---|
| `829e386a39` | read | 0 | `prospector/ops/readmodel.py` | Queue, pause and provider state |
| `d85c2ce40b` | read | 0 | `scripts/ops_state.py` | Live value of every fact the ops programme asserts |

#### Screen `/audit`

| id | risk | w | path | purpose |
|---|---|---|---|---|
| `519e09ce59` | read | 0 | `scripts/doc_lint.py` | Find docs that point at something no longer there |
| `854b847de9` | read | 0 | `scripts/ops_status.py` | Launch-ops programme status, derived from the repo |

#### Screen `/catalogue`

| id | risk | w | path | purpose |
|---|---|---|---|---|
| `d7a0d9dff7` | **external** | 1 | `publish/publish.py` | The single publish entry point |
| `86a2bf2c11` | local | 1 | `scripts/backfill_packs_parallel.sh` | Backfill P5 pack artefacts into listed packs |
| `fcbee2e393` | read | 0 | `scripts/pack_banner_probe.py` | Live packs showing a retired banner |
| `8fd8904b93` | **external** | 1 | `tools/backfill_missing_listings.sh` | Mass publish stranded PASSes |
| `71e8a63cda` | read | 0 | `tools/floor_signature.py` | Deterministic-floor copy still on the shelf |
| `75eac1b9dc` | read | 0 | `tools/pack_defect_census.py` | Live packs carrying each defect |
| `1085b856b1` | read | 0 | `tools/preview_packs.py` | Read any pack in full without buying |
| `72920919d9` | read | 0 | `tools/price_history.py` | Who moved a price and why |
| `293e5656cd` | **external** | 1 | `tools/publish_offline.py` | Publish stored PASSes without regenerating |
| `9dbac2f772` | **external** | 1 | `tools/publish_passes.py` | Generate content then publish |
| `9b073a8e93` | local | 1 | `tools/publish_passes.py` | Re-gate stale verdicts (mints nothing) |
| `1a7e1ea811` | read | 0 | `tools/recover_stranded_passes.py` | Repair PASSes the shelf does not show |
| `c4225b0b17` | **external** | 1 | `tools/retire_rotted_passes.py` | Retire PASSes whose citations rotted |
| `c15286e656` | **external** | 1 | `tools/set_live_pack_price.py` | Set one pack to a named rung |
| `e068bf68d2` | **external** | 1 | `tools/unlist_killed.py` | Unlist packs re-vetted to KILL |
| `d53fc7d46b` | read | 0 | `tools/verify_pass_shelf_coverage.py` | PASSes the shelf does not show |
| `8951f2b648` | read | 0 | `tools/verify_selling_catalogue.py` | Every selling pack backed by a PASS |

Note `tools/publish_passes.py` appears twice with different ids (`9dbac2f772` external,
`9b073a8e93` local). Same file, two commands, two risk levels. The re-gate mode "mints nothing"
so it is local; the generate-and-publish mode reaches the shelf so it is external. The derived
id is what keeps them distinct.

#### Screen `/engine`

| id | risk | w | path | purpose |
|---|---|---|---|---|
| `62b7b10d38` | **shell** | 1 | `prospector/consumer.py` | The drain loop (launchd owns it) |
| `284723e205` | **shell** | 1 | `prospector/scheduler/run_scheduled.py` | The producer loop (launchd owns it) |
| `2021d83521` | local | 1 | `prospector/ops/pause.py` | Arm or clear a pause scope |
| `d2bccfa0ab` | local | 1 | `prospector/ops/routing.py` | Who may rule finally |
| `d308d8e35a` | read | 0 | `prospector/run.py` | Operator state and quotas |
| `67e7d5c014` | read | 0 | `scripts/launchd_plists.py` | Launchd job definitions, and drift against them |

#### Screen `/metrics`

| id | risk | w | path | purpose |
|---|---|---|---|---|
| `123444d84f` | read | 0 | `prospector/ops/metrics.py` | Outcome metrics |
| `ef60ad2847` | read | 0 | `prospector/run.py` | Catalogue / metrics / cost report |
| `6005c351ec` | read | 0 | `tools/citation_quality_by_provider.py` | Which provider gave the evidence |
| `967edf8121` | read | 0 | `tools/generation_survival.py` | Survival by generation axis |
| `e161539992` | read | 0 | `tools/meta_shape_monitor.py` | Are one-liners collapsing into one cluster |

#### Screens `/queue`, `/runs`, `/shelf`, `/spend`

| id | risk | w | screen | path | purpose |
|---|---|---|---|---|---|
| `e33876ef1f` | local | 1 | `/queue` | `prospector/run.py` | Finish the waiting rows (re-vet) |
| `42e1f1bb0c` | read | 0 | `/runs` | `prospector/ops/runs.py` | Run and candidate internals |
| `0a33af67ac` | read | 0 | `/shelf` | `scripts/copy_audit.sh` | Copy audit across marketing and pack lanes |
| `20ecb52192` | read | 0 | `/spend` | `prospector/ops/spend.py` | Spend split against the cap |
| `4dfca512b3` | read | 0 | `/spend` | `scripts/unit_economics.py` | Cost per pack |
| `1a59acad26` | read | 0 | `/spend` | `tools/spend_today.py` | Today's spend against the cap |

#### Screen `/tools` (the long tail)

| id | risk | w | path | purpose |
|---|---|---|---|---|
| `9eebae21b6` | local | 1 | `prospector/run.py` | Vet one idea end to end |
| `354200eeb7` | local | 1 | `prospector/run.py` | Generate candidates from a signal |
| `23871916f6` | local | 1 | `prospector/run.py` | Bounded generation batch |
| `cd6f5c2fa3` | local | 1 | `prospector/run.py` | Drain the queue |
| `7272738c83` | read | 0 | `prospector/run.py` | System diagnostics |
| `b39a8efb09` | local | 1 | `prospector/run.py` | Manage ambition lanes |
| `96c01e11e2` | local | 1 | `prospector/run.py` | Manage markets |
| `1afadea5a5` | **external** | 1 | `scripts/backfill_ladder_prices.py` | Move the catalogue onto the L1 ladder |
| `324000f207` | local | 1 | `scripts/backfill_price_anchors.py` | Backfill cited price anchors |
| `df3de60e14` | local | 1 | `scripts/backfill_tiers.py` | Fill ambition_tier on legacy dossiers |
| `077967ef48` | **external** | 1 | `scripts/backup_store.py` | Back up dossiers and ledger to R2 |
| `abdfd9443d` | read | 0 | `scripts/blocker_probe.py` | Which programme items are blocked |
| `20d3907978` | read | 0 | `scripts/gen_budget_guard.py` | Does generation fit its tick deadline |
| `3eb78f0bc1` | **external** | 1 | `scripts/graphify_sweep.py` | Graph freshness scoreboard |
| `5cb8c54fc0` | read | 0 | `scripts/guard_protected_deletions.py` | Guard silent deletion of protected files |
| `bf5db9fb8a` | read | 0 | `scripts/live_checkout.py` | Which commit is production running? |
| `302fed2ecd` | **external** | 1 | `scripts/live_checkout.py` | Roll production forward to origin/main |
| `3c5e8c0790` | read | 0 | `scripts/load_gate.py` | Is the machine fit to trust a test result |
| `53ac8b5b2e` | read | 0 | `scripts/popdd_verify.py` | The lane-aware proof runner |
| `eb8f19e58b` | **external** | 1 | `scripts/reconcile_orphan_index.py` | Delete index rows with no dossier |
| `00632307cb` | read | 0 | `scripts/restore_drill.py` | Prove the backup restores |
| `c9008dc3ce` | read | 0 | `scripts/site_spec_probe.py` | Site spec ledger against the tree |
| `831c7a64a4` | read | 0 | `scripts/store_audit.py` | Audit the operator's store |
| `339133a267` | read | 0 | `tools/audit_swallow_sites.py` | Rank swallowed failures by blast radius |
| `3b9baa8e38` | local | 1 | `tools/backfill_archived_url.py` | Backfill archived source urls |
| `8afa86d34e` | **external** | 1 | `tools/backfill_audience.py` | Copy audience tag into the index |
| `3125472572` | **external** | 1 | `tools/backfill_bundle_html.py` | Re-render a listed pack's zip |
| `93a6d4b9b9` | **external** | 1 | `tools/backfill_facets.py` | Tag packs with discovery facets |
| `8864802da3` | **external** | 1 | `tools/backfill_listing_copy.py` | Replace floor copy with generated copy |
| `0b685c458c` | local | 1 | `tools/backfill_market.py` | Stamp legacy dossiers with market |
| `0c08156e81` | local | 1 | `tools/backfill_pack_currency.py` | Repair currency on pre-market packs |
| `91fbe31083` | read | 0 | `tools/depth_reprice_preview.py` | Before/after for the depth ladder |
| `2c02176543` | read | 0 | `tools/govern.py` | Run a command under a concurrency ceiling |
| `a249669673` | **external** | 1 | `tools/make_kill_log.py` | Bake the public kill log |
| `22486c31f8` | **external** | 1 | `tools/make_sample_report.py` | Bake the public sample report |
| `fee87e1b00` | read | 0 | `tools/prove_diversity.py` | Diversity proof harness |
| `307c4e3a48` | read | 0 | `tools/prove_reliability.py` | Reliability proof harness |
| `d0a5d69f9c` | **external** | 1 | `tools/reprice_live_packs.py` | Re-price packs with unbillable stub ids |
| `3ce494b6a4` | **external** | 1 | `tools/reprice_to_charm_rungs.py` | Move packs onto charm rungs |
| `3a561f4c61` | **external** | 1 | `tools/retitle_catalogue.py` | Rewrite live pack titles |
| `bacbbe355b` | local | 1 | `tools/review_figures.py` | Human verification of untraceable figures |
| `a1a6fcd71d` | **external** | 1 | `tools/site_wide_dash_cleanup.py` | Rewrite dashes in storefront source |
| `c6f3728c07` | local | 1 | `tools/sweep_shelf_copy.py` | Re-grade and rewrite shelf copy |

---

## Part 3 — The drift test: why adding a tool forces a choice

### 3.1 What it does

`tests/unit/test_console_tools_run.py` (418 lines), first test at line 27:

```
test_console_tool_registry_has_no_drift()
```

It walks `tools/` and `scripts/` on disk and asserts every file is either in `TOOLS` or named in
`NOT_AN_OPS_TOOL` (`console_api.py:2384-2416`, 20 entries). Line 46:

```python
classified = registered | set(api.NOT_AN_OPS_TOOL)
```

and line 50 fails with:

> "these tools are on disk but in neither TOOLS nor NOT_AN_OPS_TOOL, so the operator ..."

It also checks the reverse (line 55): `NOT_AN_OPS_TOOL` naming a file that no longer exists
fails too. And line 58 fails on overlap — a path cannot be both registered and excluded.

### 3.2 Why it exists

The comment at `console_api.py:2377-2383` records the incident: on 2026-08-17 twenty tools were
on disk and invisible from the console, and **no test could tell**. Silence looked identical to
correctness.

The fix is not "remember to register tools". It is that the choice is now **forced**. Adding a
file to `tools/` or `scripts/` makes the suite fail until you either register it or write down
why it is not an ops tool. Both outcomes are fine. Neither can be skipped.

`test_every_excluded_tool_gives_a_reason` (line 62) closes the obvious loophole. Its docstring:

> "An exclusion with no reason is the same silence the drift test exists to end."

Sample exclusions and their reasons:

| Path | Reason |
|---|---|
| `scripts/ci-gate.sh` | the POPDD CI gate; GitHub Actions runs it, not an operator |
| `scripts/seed_action_cache.sh` | CI plumbing, run once on the runner |
| `scripts/setup_worktree.sh` | a developer's machine, not ops |
| `scripts/test_impacted.py` | a developer's loop |
| `scripts/verify_engine_change.sh` | the pre-commit proof that an engine change is safe |

### 3.3 The other guarantees in that file

| Test (line) | What it pins |
|---|---|
| `test_registered_tool_paths_all_exist` (68) | no button points at a deleted file |
| `test_every_tool_id_is_unique` (75) | two buttons cannot share an id |
| `test_tool_ids_are_stable_across_rebuilds` (85) | ids do not churn between runs |
| `test_every_tool_declares_a_known_risk_and_matching_undo_coverage` (93) | risk and `undo_covers` agree |
| `test_the_only_unrunnable_tools_are_the_daemons` (103) | only the two loops are `shell` |
| `test_money_rail_tools_are_runnable_but_declare_that_undo_cannot_reach_stripe` (115) | money tools stay usable and stay honest |
| `test_the_browser_allowlist_matches_the_gateway` (133) | **UI and gateway cannot drift** |
| `test_the_command_comes_from_the_catalogue_not_the_payload` (155) | a payload cannot inject a command |
| `test_a_placeholder_value_is_one_argument_even_when_it_looks_like_a_command` (164) | no shell injection via placeholder |
| `test_the_browser_view_allowlist_matches_the_gateway` (323) | same drift check on the read door |
| `test_a_job_whose_worker_died_is_lost_not_running` (302) | a dead job reports lost, not a forever spinner |

Two of these carry recorded incidents. Line 137: `daemon.restart` "was added to the Python
gateway on 2026-08-16 and never added to the" browser allowlist. Line 305: a console showing a
spinner forever is "the prose-drift failure in UI form."

`test_the_command_comes_from_the_catalogue_not_the_payload` is the security-relevant one. The
command string is taken from the registry by id. The payload supplies values only, and
`test_a_placeholder_value_is_one_argument_even_when_it_looks_like_a_command` proves a value that
looks like `; rm -rf /` arrives as one argument.

---

## Part 4 — Actions, refusals and knobs

### 4.1 The 13 actions

`ACTIONS` — `console_api.py:2123-2137`:

| Action | What it does |
|---|---|
| `shelf.repair_copy` | rewrite shelf copy |
| `shelf.publish_pending` | publish what is waiting |
| `shelf.regate` | re-gate stale verdicts |
| `daemon.restart` | restart a daemon |
| `pause.arm` | arm a pause scope |
| `pause.disarm` | clear a pause scope |
| `routing.set_moat_primary` | change who may rule finally |
| `config.set` | set an allow-listed knob |
| `config.restore` | restore a previous config |
| `catalogue.set_listing` | list or unlist one pack |
| `deliveries.resend` | resend a delivery |
| `tools.run` | run a registered tool |
| `tools.undo` | restore a `store/` snapshot |

### 4.2 The two permanent refusals

`REFUSED_ACTIONS` — `console_api.py:2150-2161`:

| Action | Reason (from the code) |
|---|---|
| `catalogue.set_price` | "A direct catalogue price write is refused because it would drift from Stripe." |
| `catalogue.reprice` | "Same reason ... a bulk row write would leave Stripe holding the old price." |

This is the single most important refusal in the system, and it is worth stating plainly.

The money rail's rule is that **one `PriceDecision` mints the Stripe Price object and writes the
catalogue row together** (`prospector/bridge.py`). If the two ever disagree, the buyer is charged
one amount and the fulfilment fence checks a different one. So there is no console button that
writes a price into the catalogue alone. There is a button that sets a pack to a named rung
(`tools/set_live_pack_price.py`, `c15286e656`), and it is marked `external` because it goes
through the bridge and reaches Stripe.

A refusal returns exit 3, not exit 4. There is no token that makes it work.

### 4.3 The 15 knobs

`KNOBS` — `console_api.py:1114-1189`. An allow-list: `config.set` can write these and nothing
else, so the console cannot rewrite arbitrary config.

**Group `work`**

| Key | Label | Kind |
|---|---|---|
| `generation.candidates_per_signal` | Ideas invented per signal | int 1–… |
| `schedule.batch_size` | Wave size — ideas per batch | int 1–200 |
| `schedule.lease_ttl_s` | How long a worker may hold a row (seconds) | int |
| `schedule.backlog_cap` | Backlog brake (0 = off) | int 0–100000 |
| `schedule.gate_generation_on_grounding` | Stop inventing while search is broken | bool |

**Group `evidence`**

| Key | Label | Kind |
|---|---|---|
| `retrieval.provider` | Search engines, in order | list |
| `retrieval.backstop_only_providers` | Held back for outages only | list |
| `retrieval.min_relevance` | How relevant a passage must be to count | float |

**Group `brains` — all three are `high_blast: True`**

| Key | Label |
|---|---|
| `operator` | Verdict chain — who is asked, in order |
| `moat_primary` | Trusted roster — who may rule FINALLY |
| `noncritical_operator` | Cheap chain — generation, prescreen, scoring |

`high_blast` marks the knobs that change what the system is allowed to believe. `moat_primary` is
the fence between a verdict that publishes and one stamped `provisional`
(`operator.is_provisional_provider`, `operator.py:1451`; publication blocked at `run.py:864`).
Moving it is a founder decision, not an ops decision.

**Group `speed`**

| Key | Label |
|---|---|
| `retrieval.minimax_concurrency` | MiniMax calls at once |
| `retrieval.claude_concurrency` | Claude CLI calls at once |

**Group `money`**

| Key | Label | Kind |
|---|---|---|
| `spend.daily_cap_usd` | Daily spend ceiling (USD) | float 0–1000 |
| `spend.warn_at_usd` | Warn at (USD) | float 0–1000 |

Every knob carries a `label` and a `help` string. The console renders those, not the raw key.

### 4.4 Running a tool, and undo

`_act_tools_run` — `console_api.py:1743-1833`. The order matters:

1. Take the undo snapshot **inside the request**.
2. Spawn the worker with `start_new_session=True`.
3. Return a job id immediately.

The snapshot is taken before the fork, synchronously. If it were taken in the worker, a tool
that crashed early could leave no snapshot and no record that one was missing.

`start_new_session=True` detaches the worker into its own process group, so the tool survives the
console being restarted and does not die with the HTTP request.

`prospector/ops/undo.py` (255 lines):

| Constant | Value | Meaning |
|---|---|---|
| `DEFAULT_KEEP` | `12` | twelve snapshots retained |
| `EXCLUDED` | `{"_cache"}` | the retrieval cache is regenerable, so it is not snapshotted |

Three undo behaviours are pinned by tests (`test_console_tools_run.py`):

- `test_snapshot_skips_the_regenerable_cache` (350)
- `test_undo_restores_a_modified_file_and_deletes_one_written_since` (361)
- `test_the_plan_warns_that_files_written_since_are_deleted` (381)

**That last one is the trap.** Undo is a restore to a point in time, not a reverse of one
action. Files written *after* the snapshot are **deleted**. If two tools ran and you undo the
first, you lose the second's work. The plan says so before you confirm. Read it.

---

## Part 5 — Console pages

```
$ find store_platform/src/Ops.Console/src/pages -type f \( -name '*.tsx' -o -name '*.ts' \) | sort
```

| Page | Shows |
|---|---|
| `index.tsx` | overview: queue, pause and provider state |
| `engine.tsx` | the two daemons, pause levers, routing |
| `queue.tsx` | rows waiting to be re-vetted |
| `runs/index.tsx`, `runs/[id].tsx` | run list and one run's internals |
| `catalogue/index.tsx`, `catalogue/[id].tsx` | catalogue rows and one pack |
| `shelf.tsx` | what the storefront actually shows |
| `orders/index.tsx`, `orders/[id].tsx` | orders, and one order end to end |
| `delivery.tsx` | delivery state |
| `disputes.tsx` | Stripe disputes |
| `money.tsx` | money-rail status |
| `revenue.tsx` | revenue |
| `spend.tsx` | spend against the cap |
| `metrics.tsx` | outcome metrics |
| `method.tsx` | how the filter works |
| `config.tsx` | the 15 knobs |
| `data.tsx` | store data |
| `audit.tsx` | doc lint and ops status |
| `tools.tsx` | the 81-tool registry |
| `queue.tsx` | the drain |
| `login.tsx` | auth |
| `api/ops/read/[view].ts` | read gateway |
| `api/ops/act/[action].ts` | write gateway |
| `api/ops/session.ts` | session |

The two gateway files are where the browser allowlists live, and they are exactly what
`test_the_browser_allowlist_matches_the_gateway` (line 133) and
`test_the_browser_view_allowlist_matches_the_gateway` (line 323) pin against the Python side.

Served by launchd:

```
node next start -H 100.93.240.113 -p 8611
```

Bound to a Tailscale address, not `0.0.0.0`. Env names only: `CONTROL_CENTER_PASSWORD`,
`NODE_ENV`, `PROSPECTOR_PYTHON`, `PROSPECTOR_ROOT`.

---

## Part 6 — The levers

### 6.1 `store/scheduler/PAUSE` — stops everything

Read by `prospector/scheduler/guard.py`: `PAUSE_FILENAME = "PAUSE"` at `:66`, `is_paused()` at
`:137`, refusal in `evaluate()` at `:347` and `:364-365`.

It halts the **entire tick** — generation and the re-vet drain together.

This is deliberate and it is the liability rail. The reasoning in `CLAUDE.md`: "a rail with
exceptions is not a rail". When you pull `PAUSE` you want everything to stop, including the
thing you forgot was running.

### 6.2 `store/scheduler/PAUSE_GENERATION` — stops making, keeps draining

`_GENERATION_PAUSE_FILENAME = "PAUSE_GENERATION"` at `prospector/scheduler/run_scheduled.py:233`,
checked in `_generation_suppressed` at `:634-636`.

The drain keeps running. This exists because the drain must never be collateral damage of a
decision to stop generating. If the only lever were `PAUSE`, every "stop making new ideas" would
also strand every candidate already waiting for a verdict.

### 6.3 `schedule.backlog_cap` — the stock brake, default 0 = off

`run_scheduled.py:651-706`. Above the cap, a tick drains only.

The interesting part is that its two failure modes are **deliberately asymmetric**:

| Condition | Behaviour | Lines |
|---|---|---|
| Cap value unparseable | **FAILS OPEN** — generation continues, CRITICAL alert `backlog_cap_unreadable` | `:654-690`, alert at `:681-687` |
| `_backlog_size(cfg) is None` | **FAILS CLOSED** — generation stops | `:693-702` |

A broken *setting* must not stop the business, so it alerts loudly and carries on. A broken
*measurement* must stop it, because generating against an unknown backlog is the exact thing the
brake exists to prevent. `run.drainable()` is the single definition of "backlog", so the brake
can only engage on a number the drain can actually move.

### 6.4 `schedule.gate_generation_on_grounding` — the rate brake, default on

Runs one bounded live search per tick and suppresses generation only while retrieval is
*actually* degraded. It self-clears when the outage ends.

This replaced the stock brake as the primary control (founder decision 2026-08-06). The reason
is memory-shaped: a stock brake has unbounded memory, so one outage suppresses generation
indefinitely. A six-week-old outage was why the daemon generated nothing one afternoon. The
measured correction: **generation volume does not create backlog rows; failed retrieval does.**

### 6.5 `spend.daily_cap_usd` — the money rail

`guard.py:388-390`. Counts **only** ledger rows with `event: "spend"` (`guard.py:21-49`) from
`store/prospector.jsonl`.

Two things follow:

- Claude-CLI subscription burn is not counted here. That is a separate, default-OFF
  `spend.daily_subscription_cap_usd`.
- The ledger is 270,268,948 bytes (measured 2026-08-18) and is **never rotated**, because
  truncating it changes what the guard believes. See
  [`../LOGGING_AND_RETENTION.md`](../LOGGING_AND_RETENTION.md) §5.2.

`guard.py:366-387` also carries a clock-skew rail, because a cap that reads "today" is only as
good as the clock.

### 6.6 The moat preflight outranks all of them

`_moat_blind_reason` at `run_scheduled.py:720-751`. The body is:

```python
return moat_blind_reason(cfg, trusted_only=False)
```

`trusted_only=False` is the load-bearing argument. The tick is skipped only when **every**
configured verdict brain, trusted or provisional, carries a live dead mark. One live brain of any
tier is enough to proceed.

Gate order in `run_tick` (`:1666`):

| Order | Gate | Lines |
|---|---|---|
| 1 | guard refusal (PAUSE + spend cap) | `:1699-1702` |
| 2 | usage-wall preflight | `:1719-1729` |
| 3 | **moat preflight** | `:1741-1753` |
| 4 | generation brake | `:1766-1828` |

When skipped it logs `moat_blind` and counts the tick unproductive, so the escalating retry
applies (`_RETRY_BACKOFF_S = 300` at `:1566`; `_retry_sleep_s` at `:1569-1588` gives 5m → 10m →
20m, capped at the 7200s interval) rather than waiting the full 2h.

`moat_blind_reason` reads raw `dead_until()` and never `is_dead()` (`health.py:330`, `:340`). A
bookkeeping check must not consume the half-open probe slot that a real verdict call should get.

### 6.7 The drain is trusted-only, and that asymmetry is on purpose

`run.py::_cmd_resume` runs the same classifier at the default `trusted_only=True`.

Re-vetting a `provisional` row on a provisional brain re-stamps it `provisional`. The row does
not move, the money is spent, and the load helps keep the trusted brain benched. Measured
2026-08-06: provisional −14 / defer +13 over thirty minutes. Net −1.

So: generation may run into a provisional tail. The drain may not. One shared function, one
parameter, so the two can never disagree by accident.

---

## Part 7 — Scheduled jobs

### 7.1 Tracked declarations

```
$ ls -1 ops/launchd/com.prospector.*.json
com.prospector.backup.json
com.prospector.consumer.json
com.prospector.control-center.json
com.prospector.ops-console.json
com.prospector.scheduler.json
com.prospector.watchdog.json
```

| Label | Schedule | RunAtLoad | KeepAlive | Command | Logs |
|---|---|---|---|---|---|
| `com.prospector.scheduler` | KeepAlive | yes | yes | `-m prospector.scheduler.run_scheduled --daemon --interval 7200` | `store/scheduler/launchd.{out,err}.log` |
| `com.prospector.consumer` | KeepAlive | yes | yes | `-m prospector.run --config consume --publish` | `store/scheduler/consumer.{out,err}.log` |
| `com.prospector.watchdog` | every 900s | yes | — | `launchd_receipt.py -- -m pro…` | `store/scheduler/watchdog.{out,err}.log` |
| `com.prospector.backup` | 03:40 daily | — | — | `launchd_receipt.py -- … backup_store.py --mirror-only` | `store/backup.log` (both streams) |
| `com.prospector.ops-console` | KeepAlive | yes | yes | `node start -H 100.93.240.113 -p 8611` | `/tmp/ops-console.{out,err}.log` |
| `com.prospector.control-center` | KeepAlive | yes | yes | `run …/control_center/app.py --server.port …` | `/tmp/prospector_control_center.log` |

The scheduler interval is **7200s (2 hours)**.

### 7.2 Installed plists, and the drift

```
$ ls ~/Library/LaunchAgents/com.prospector.*.plist | xargs -n1 basename
com.prospector.backup.plist
com.prospector.consumer.plist
com.prospector.live-update.plist
com.prospector.offsite-backup.plist
com.prospector.ops-console.plist
com.prospector.scheduler.plist
com.prospector.watchdog.plist
```

Compared with the tracked list:

| Drift | Jobs |
|---|---|
| Installed but **not tracked** | `com.prospector.live-update`, `com.prospector.offsite-backup` |
| Tracked but **not installed** | `com.prospector.control-center` |

The session's git status shows `ops/launchd/com.prospector.live-update.json` and
`com.prospector.offsite-backup.json` as **deleted** in the working tree. So two jobs are running
on this machine whose declarations were removed from the repo. That is drift in the dangerous
direction: the installed reality is no longer described anywhere in version control.

### 7.3 The drift detector

`scripts/launchd_plists.py` exists for exactly this:

```
python3 scripts/launchd_plists.py --check       # report drift, exit 1 if any
python3 scripts/launchd_plists.py --snapshot    # accept current state as tracked
```

`load_live()` at `:79`, `load_tracked()` at `:95`, `diff_keys()` at `:107`, `cmd_check()` at
`:140`. It reports `new`, `missing`, `drifted` and `unreadable` counts (`:178`).

It redacts (`redact()` at `:62`). The docstring at `:23-24` explains why: it tracks
"DEFINITIONS, not the secret store, and a tool that logs a password to catch drift is worse than
the drift."

`owned()` at `:58` filters out jobs "we did not install and do not own", so the check does not
report drift on somebody else's launchd jobs.

**Run `--check` before trusting anything in §7.1.** The tracked table is a declaration. The
installed plists are the reality, and §7.2 proves they differ today.

### 7.4 The backup job is broken

Covered in full in [`../LOGGING_AND_RETENTION.md`](../LOGGING_AND_RETENTION.md) Part 0. In one
line: the installed plist passes `--mirror-only`, `backup_store.py` has no such flag
(`grep -c 'mirror.only\|mirror_only' scripts/backup_store.py` → `0`), argparse exits 2, and
nothing alerts. Last receipt in `store/backup.log` is 2026-08-17 09:38.

---

## Part 8 — The probes

### 8.1 `scripts/live_checkout.py` (400 lines)

The answer to "which commit is production running" is this command, never a sentence.

```
.venv/bin/python scripts/live_checkout.py            # report
.venv/bin/python scripts/live_checkout.py --update   # roll forward and restart
```

Both are console buttons: `bf5db9fb8a` (read) and `302fed2ecd` (external).

Constants:

| Name | Value | Line |
|---|---|---|
| `DEV` | `/Users/chidionyema/Documents/code/prospector` | `:30` |
| `LIVE` | `/Users/chidionyema/Documents/code/prospector-live` | `:31` |
| `STORE` | `DEV / "store"` | `:32` |
| `JOBS` | scheduler, consumer, ops-console | `:33` |
| `SECRETS` | `.env`, `.lux/keys/agent.pem` | `:35` |
| `NO_AUTO_UPDATE` | `store/scheduler/NO_AUTO_UPDATE` | `:284` |

What `report()` (`:197`) actually checks, in order:

1. **For each job: the real cwd of the running pid** (`job_cwd()` at `:104`). Not the plist —
   the process. It flags `<- NOT the live checkout` on mismatch.
2. **`PROSPECTOR_STORE_DIR` on each plist** (`plist_store_dir()` at `:189`) against the canonical
   `STORE`. A job writing state somewhere else is a problem even if its code is correct.
3. **Is the live checkout on `origin/main`?** It fetches, then compares `HEAD` to `origin/main`
   and reports how many commits behind and ahead.
4. **Local code changes** in the live checkout (`_code_changes()` at `:76`, using `_STATUS_RE` at
   `:73` so runtime state under `store/` does not read as a code change).
5. Console build staleness (`console_build_is_stale()` at `:140`).
6. Secret symlinks present.

If `LIVE` is missing it prints `MISSING:` and returns 1 (`:222-224`) — which is what happens on
this machine today.

**Why this exists:** production once ran from the shared developer checkout on whatever branch a
session had left it on. On 2026-08-17 that was a branch 75 commits behind `origin/main`, so the
daemon executed 17-hour-old code, and the only way to see it was to run `lsof` on the pid by
hand.

`--update` refuses a live checkout with local code changes. A fix reaches production through a
pull request, not through an edit on the box.

### 8.2 `scripts/ops_status.py` (515 lines)

Grades the launch-ops programme against the repo. Console button `854b847de9` (read), screen
`/audit`.

44 items across seven prefixes: `SRC` (source), `INF` (infrastructure), `DAT` (data), `AST`
(assets), `DNS`, `BIZ` (business), `PAY` (payments), `ENG` (engine), `KEY` (key-person).

Of the 44, **15 have a check function** and the rest are `None` — declared, not measured. That
distinction is in the code, not the prose:

| Measured (has a checker) | Declared only (`None`) |
|---|---|
| SRC-1…SRC-6, INF-1, INF-2, INF-3, DAT-1, DAT-2, DAT-3, ENG-1, ENG-5, ENG-6, PAY-1, BIZ-1, KEY-1 | INF-4, INF-5, DAT-4, DAT-5, AST-1…AST-4, DNS-1…DNS-4, BIZ-2…BIZ-6, PAY-2…PAY-4, ENG-2, ENG-3, ENG-4, ENG-7, KEY-2 |

`ACCEPTED_IDS = {"DAT-5", "AST-4", "DNS-4", "PAY-3", "PAY-4", "INF-5", "BIZ-5"}` (`:278`) —
"understood, deliberately not being fixed", and the comment states these are "not a measurement,
so ... never counted as done."

Items that bear directly on this document:

| Item | Title |
|---|---|
| DAT-1 | Money data has one copy, 5-day window |
| DAT-2 | **Restore never proven end to end** |
| DAT-3 | Spend ledger outgrew its readers |
| DAT-4 | RPO is 24 hours on engine state |
| ENG-5 | **Logs and state grow unbounded** |
| ENG-6 | **Docs describe a system that no longer exists** |
| ENG-2 | The loudest alert names the wrong cause |
| KEY-1 | The engine cannot run anywhere but this Mac |

ENG-6 is a graded programme item. This document's Part 0 is a fresh instance of it.

It also has a **claim register** so two sessions do not work the same item:
`claims_path()` `:286`, `write_claim()` `:334`, `CLAIM_TTL_H = 12` `:283`, `other_agents()`
`:382`. Use `--claim ID --note "what you are doing"` before starting, `--release` when done.

Flags: `--fetch`, `--agents`, `--json`, `--only`, `--claim`, `--release`, `--claims`, `--note`.

**Important:** `on_main(path, needle)` at `:60` grades against `origin/main`, not the local
index. A fix sitting uncommitted in your worktree does not turn an item green.

### 8.3 Probes that have reported false passes

Every row is a recorded incident. This table is the reason nothing in this document says "it
works" without a command beside it.

| Probe | Reported | Reality | Why |
|---|---|---|---|
| `grep -c` over `launchd.err.log` | 97 provider failures today | 8 | the log was never rotated; the count spanned weeks. Recorded in `ops/config/log_rotation.yaml`. |
| `npm run build 2>&1 \| tail` | exit 0 | build failed | a pipe reports **tail's** exit status |
| `dotnet test` | exit 0 | tests failing | recorded in memory `dotnet-test-reports-exit-zero-while-failing.md` |
| `pytest` | exit 0 | collected nothing | `pytest-exits-zero-when-it-collects-nothing.md` |
| `fly auth whoami` | passes | token dead | `fly-auth-whoami-passes-on-a-dead-token.md` |
| macOS `ps` / `launchctl` probes | pass | job not running | `macos-ps-and-launchctl-probes-report-false-pass.md` |
| `/models` endpoint | key valid | balance zero | proves the key, not the balance |
| `grep -rn --include=*.toml` under zsh | 0 hits | never ran | zsh failed the unquoted glob. **I hit this in this session.** |
| single-file regression guard | green | drift elsewhere | `single-file-regression-guard-reports-green.md` |
| ticks in `store/scheduler/ticks.jsonl` | ~59.6 rows/hour | real ticks ~2.5h apart | an adjacent-estate driver fires `--once --dry-run` into the production log. Warning at `run_scheduled.py:115-129`. |

That last one deserves emphasis. **Do not read raw `ticks.jsonl` counts as daemon activity.**

---

## Part 9 — Routine procedures

### 9.1 Establish where you are (always first)

```
launchctl list | grep -E '^\S+\s+\S+\s+com\.prospector\.'
.venv/bin/python scripts/live_checkout.py
fly apps list
python3 scripts/launchd_plists.py --check
```

Four commands, one round trip. Do not skip the last one — §7.2 shows the installed set and the
tracked set differ right now.

### 9.2 Pause everything

```
touch store/scheduler/PAUSE
```

Or console: `pause.arm`. Stops generation and drain. Verify by watching the next tick log a
guard refusal.

### 9.3 Pause generation, keep draining

```
touch store/scheduler/PAUSE_GENERATION
```

Use this when the queue is deep and you want it worked down without adding to it.

### 9.4 Resume

```
rm store/scheduler/PAUSE
rm store/scheduler/PAUSE_GENERATION
```

Or console: `pause.disarm`.

### 9.5 Drain the queue by hand

Console `/queue`, tool `e33876ef1f`, or the CLI resume path (`run.py::_cmd_resume`). It runs
trusted-only (§6.7). If the trusted brain is benched, the drain will correctly do nothing —
check `store/provider_health.json` before assuming it is broken.

### 9.6 Roll production forward

```
.venv/bin/python scripts/live_checkout.py            # look first
.venv/bin/python scripts/live_checkout.py --update   # then roll
```

`--update` refuses if the live checkout has local code changes. `store/scheduler/NO_AUTO_UPDATE`
(`:284`) blocks unattended updates.

**Today this will report `MISSING`** (§0.2). Resolve the machine-layout question in Part 0
before trying to roll anything forward.

### 9.7 Run a tool safely

1. Read its `risk` in the table in Part 2.
2. If `external`, know that undo covers **the local half only**.
3. Preview. Read the plan, especially the line about files written since the snapshot being
   deleted.
4. Confirm within 600 seconds (`CONFIRM_TTL_S`).
5. Note the job id. Check the receipt in `store/ops/intents.jsonl`.

### 9.8 Undo

Console `tools.undo`. Twelve snapshots are kept (`DEFAULT_KEEP = 12`). `_cache` is not
snapshotted, because it is regenerable.

Undo restores `store/` to a point in time. **It deletes files written since.** It cannot reach
Stripe, the live shelf, or R2.

### 9.9 Change a knob

Console `/config`, action `config.set`. Only the 15 keys in §4.3. The three `high_blast` keys in
group `brains` change what the system may believe — treat those as founder decisions.
`config.restore` reverts.

---

## Part 10 — Invariants

| # | Invariant | Enforced at | What breaks if it goes |
|---|---|---|---|
| I1 | Reads cannot write | the verb in argv, `console_api.py` dispatch | the console becomes an unaudited write surface |
| I2 | Writes require a token checked server-side | `_token` `:1293`, `_valid_tokens` `:1316` | a crafted request performs any action |
| I3 | The command comes from the catalogue, not the payload | `test_the_command_comes_from_the_catalogue_not_the_payload:155` | command injection |
| I4 | Every file in `tools/`+`scripts/` is registered or excluded with a reason | `test_console_tool_registry_has_no_drift:27` | tools become invisible again, as on 2026-08-17 |
| I5 | `undo_covers` is derived from `risk` | `_t()` `:2187-2203` | the console promises undo it cannot deliver |
| I6 | Only the two daemons are unrunnable | `test_the_only_unrunnable_tools_are_the_daemons:103` | two producer loops, one store, corrupted state |
| I7 | No catalogue price write without Stripe | `REFUSED_ACTIONS` `:2150-2161`, `bridge.py` | buyer charged one price, fence checks another |
| I8 | Browser allowlists match the Python gateway | tests at `:133` and `:323` | a button exists that the gateway refuses, or worse, the reverse |
| I9 | Only `moat_primary` brains rule finally | `is_provisional_provider` `operator.py:1451`, `run.py:864` | ungrounded verdicts publish |
| I10 | The drain is trusted-only | `run.py::_cmd_resume` default | rows churn without moving, spending money |
| I11 | Generation stops when the backlog size is unknown | `run_scheduled.py:693-702` | unbounded backlog growth |
| I12 | The spend ledger is never truncated | `ops/config/log_rotation.yaml` exclusion | the daily cap believes the wrong number |
| I13 | State paths resolve via `config.store_root()`, never `__file__` | `config.py:15-31` | health marks and cache split across two directories; a recovered provider is never seen |
| I14 | An exception is never evidence | `verify.py:1134-1151` DEFER gate | candidates killed by our own outage |

I13 has a receipt. Four constants derived a store path from `__file__`, so when the code moved,
provider health marks, the retrieval cache and the scheduler audit trail were written beside the
new code while the ledger went to the canonical store. A daemon writing one copy of the health
file while a probe reads another can never see a provider recover.

I14 has one too: `store/dossiers/2102bacc6dd75cf9.kill.json` is a KILL on `min_composite` whose
seven checks all read `unverifiable, conf 0.0, "Verdict call failed; fail-safe."` A candidate
killed by our own outage, in a dossier that reads as fully reasoned.

---

## Part 11 — How to change it safely

### 11.1 Adding a tool

1. Add it to `TOOLS` via `_t()` with an honest `risk`, or add it to `NOT_AN_OPS_TOOL` with a
   reason. The drift test will not let you do neither.
2. If it touches Stripe, the live shelf, R2 or a public source, it is `external`. Not `local`.
   The label is a promise to the operator.
3. If it needs a browser button, add it to the gateway allowlist too — the drift test at line 133
   exists because `daemon.restart` was added to Python on 2026-08-16 and never to the browser.
4. Run the suite.

### 11.2 Adding a knob

Add to `KNOBS` with `path`, `group`, `label`, `kind`, bounds and `help`. If it changes what the
system may believe, set `high_blast: True`. The allow-list is the fence; a key not in it cannot
be written by the console at all.

### 11.3 Adding an automation

Follow [`../OPS_AUTOMATION_PRINCIPLES.md`](../OPS_AUTOMATION_PRINCIPLES.md): generic engine, YAML
declaration, report before fix, `--json` for the console, exit 0 clean / 1 findings / 2 cannot
establish, fail closed and say why. `ops/automations/log_rotation.py` and
`ops/automations/offsite_backup.py` are the two worked examples.

### 11.4 Changing a launchd job

Edit the tracked JSON in `ops/launchd/`, regenerate with `scripts/launchd_plists.py`, then
`--check`. **Never edit `~/Library/LaunchAgents/` by hand.** §7.2 and §7.4 are both what hand
edits look like months later.

---

## Part 12 — Open gaps and the cost of closing each

| Gap | Evidence | Cost to close |
|---|---|---|
| Four launchd jobs not loaded | `launchctl list` shows only `com.prospector.backup` | **not a gap — intended.** They were retired by the Fly migration (§0.4) |
| `scripts/live_checkout.py` probes the retired setup | §0.4; `LIVE` hard-coded at `:31` | one PR: point it at `prospector-engine` and compare the heartbeat `code` field, or delete it |
| The laptop watchdog may re-bootstrap a retired daemon | `alert_state.json` shows it did exactly this on 2026-08-16 | confirm `com.prospector.watchdog` is unloaded, or fence it |
| Backup broken since ≥2026-08-17 | `grep -c mirror_only` → 0; last receipt 17 Aug | one line + a flag-existence test. Under an hour. |
| Nothing alerts on a failed launchd job | no alert path for non-zero exit | half a day |
| Two installed jobs have no tracked declaration | §7.2 | run `--snapshot` after deciding whether they should exist |
| `prospector-engine` absent from the repo | `rg -c` → 0 | half a day to add a deploy config |
| Engine volume not backed up | no source in `offsite_backup.yaml` | config plus verification |
| No restore ever proven | ops_status DAT-2 | one hour per quarter |
| No centralised logs | [`../LOGGING_AND_RETENTION.md`](../LOGGING_AND_RETENTION.md) | Steps 6–10 there |
| Console logs to `/tmp` | `ops/launchd/com.prospector.ops-console.json:21-22` | an hour |
| 29 of 44 ops_status items are unmeasured | `None` checkers in the table at `:231-278` | one checker each |
| Mac at 97% full | `df -h` → 17Gi free | a decision, not a script |
| `ESTATE_MAP.md` does not exist | `rg -l ESTATE_MAP` → 0 hits | it is referenced as if it does |

---

## Part 13 — Where to look next

| You want | Go to |
|---|---|
| What to do when something is down | [`sre-on-call.md`](sre-on-call.md) |
| Log design, retention and backup policy | [`../LOGGING_AND_RETENTION.md`](../LOGGING_AND_RETENTION.md) |
| The rules a new automation must follow | [`../OPS_AUTOMATION_PRINCIPLES.md`](../OPS_AUTOMATION_PRINCIPLES.md) |
| The dispatcher and every tool | `prospector/ops/console_api.py` |
| What the registry guarantees | `tests/unit/test_console_tools_run.py` |
| Snapshot and undo | `prospector/ops/undo.py` |
| The levers | `prospector/scheduler/guard.py`, `prospector/scheduler/run_scheduled.py` |
| Provider health | `prospector/errors.py`, `prospector/health.py` |
| Which commit production runs | `scripts/live_checkout.py` |
| Programme status | `scripts/ops_status.py` |
| Launchd drift | `scripts/launchd_plists.py --check` |

> An estate map was expected at `../ESTATE_MAP.md`. It does not exist: `ls docs/ESTATE_MAP.md`
> returns "No such file or directory" and `rg -l "ESTATE_MAP" .` returns zero hits. The link is
> left unmade rather than pointed at nothing.
