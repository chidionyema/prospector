# R7: the 15 quarantined cockpit actions

**Status:** spec, nothing built. Written 2026-08-09 after a cost probe found "build them" is not one
job but 15 separate decisions, only a third of which are wiring.

**Source of truth:** `~/.hermes/hermes-agent/tests/gateway/operator_shell/test_every_button_dispatches.py`,
the `_UNBUILT` dict at `:104-175`. That test derives both sides of the check from source at test time,
so the list cannot drift. It is ratcheted at 15 (`:224`) and every entry must still have a live button
(`:213`). This spec adds what the quarantine notes do not say, and corrects three of them.

## The cost call

34 live button sites across the 15 actions (measured, not the ~30 previously stated). Distribution is
the whole story: `fix_all` alone is 11 sites and `onboard` is 6, so two actions carry half the surface
and both are the expensive kind. Nine of the 15 have exactly one button.

Only 4 of 15 are "write a renderer". Three are correctly fixed by deleting a button, not building.
Four mutate real infrastructure and need a confirm screen. Four need a product decision before any
code is worth writing.

## What the probe corrects in the quarantine's own notes

1. **The cited callables are in a different repo.** `cross_project.py`, `predictor.py`,
   `score_driver.py`, `auto_close_identity.py` and `auto_fixer.py` are in `~/.hermes/scripts/`, not in
   `hermes-agent`. The quarantine cites them bare (`cross_project.py:70`) as if local. This is not a
   blocker: `health_panel.py:21` already does `sys.path.insert(0, str(SCRIPTS))` and `estate.py:86-118`
   does the same with a cleanup, so the import precedent exists and is cheap. It does mean every
   renderer in Tranche A inherits that path dance.

2. **`compliance_report` is a method, not a function.** `auto_close_identity.py:671` is
   `def compliance_report(self) -> dict`, indented inside a class. The quarantine says "returns a dict;
   needs a renderer", which understates it: something must construct the owning object first. That is
   the difference between a 20-line renderer and an unknown.

3. **The confirm pattern citation is stale.** The quarantine points the four mutating actions at
   `estate.py:934-961`. That range is now the `estate_diff` and `fleet` handlers. The real two-screen
   pattern to copy is `restart` / `restart_confirm` at `estate.py:1489-1510`: screen one names the
   target and the exact consequence, screen two runs it and reports returncode.

One quarantine note is understated in the cheap direction: `estate_health` says "No renderer of any
name", which is true, but the data source is already wired elsewhere. `builds.py:217` shells
`~/.hermes/scripts/verify_estate.sh`, whose output is the estate's PASS/FAIL contract. So
`estate_health` is a renderer over an existing subprocess call, not a green field.

## Tranche A: build, genuinely cheap (4 actions, 8 button sites)

Each is one renderer plus one line in `estate._PANELS` (`estate.py:337`, shape
`action: (module, function, toast, arg_mode)`). The registry path is already covered by
`test_every_registered_panel_resolves_to_a_real_function` (`:195`), so a typo fails in CI, not on a tap.

| action | sites | source | note |
|---|---|---|---|
| `dependencies` | 2 | `~/.hermes/scripts/cross_project.py:70 dependency_map()` | module-level, returns dict. The clean one. |
| `score` | 3 | `score_driver.py:84 score_burndown()` / `:191 score_leaderboard()` | both module-level; pick one, see decision D1 |
| `correlate` | 2 | `predictor.py:129 correlate_failures()` or `cross_project.py:54 correlate_estate()` | both module-level; see decision D2 |
| `compliance` | 1 | `auto_close_identity.py:671 compliance_report()` | method on a class; needs the owner constructed first |

Ship `dependencies` first as the pattern-setter. If it lands in under an hour, the other three are the
same shape and the tranche is real. If it does not, the cross-repo import is the problem and the rest
of the tranche should be re-costed before starting.

## Tranche B: delete the button, do not build (3 actions, 3 sites)

These are the cheapest wins and they reduce the ratchet.

- **`rsi_pause` and `rsi_resume`** (both `rsi_control.py:109`). Verified on disk: `toggle_learning()`
  (`rsi_control.py:163-173`) writes `~/.hermes/logs/meta-improver/OFF_SWITCH` where present means
  paused. The live switch that the cockpit actually reads is `~/.hermes/meta/OFF_SWITCH`
  (`rsi_panel.py:19`), and `learning_armed()` (`rsi_panel.py:48-49`) returns `OFF_SWITCH.is_file()`,
  so there present means ARMED. Different file, opposite polarity. Wiring as-is toasts "paused" while
  learning stays live. Meanwhile `arm_learning` and `disarm_learning` already work
  (`estate.py:861` and `:886`) and already have buttons (`rsi_panel.py:173, 242, 244`). Fix: point
  `rsi_control.py:109` at the working actions and delete `toggle_learning()`. Roughly two lines plus a
  dead-function removal.
- **`fix_all_safe`** (`command_palette.py:38`). Nothing on disk. `feature_registry.py:36` claims
  `built:2026-08-02` citing a test `test_fix_all_safe` that does not exist. Delete the button and the
  false registry row in the same commit; a registry that lies is worse than a missing feature.

Doing Tranche B alone drops the quarantine 15 to 12 and removes three dead taps.

## Tranche C: needs a decision, then cheap (3 actions, 3 sites)

- **D1, `score`:** `score_burndown()` or `score_leaderboard()`, or a two-button chooser. Burndown is
  the operator question ("are we improving"); leaderboard is the comparison. Recommend burndown as the
  bare tap with leaderboard as a second button.
- **D2, `correlate`:** `correlate_failures()` (failure co-occurrence) and `correlate_estate()`
  (cross-project) are non-overlapping. Recommend `correlate_estate()` for the bare tap, since the
  button sits in the estate palette (`command_palette.py:31`).
- **D3, `logs`** (`command_palette.py:61`): three `render_logs()` exist (`daemons.py:391`,
  `prospector_daemon.py:789`, `signal_engine.py:816`), each needing a unit prefix the bare button does
  not send. Recommend a three-button chooser panel rather than picking a default, because a default
  silently shows the wrong daemon's logs during an incident.
- **`estate_health`** (`command_palette.py:29`): renderer over `verify_estate.sh` (`builds.py:217`
  precedent). Decision is only whether it duplicates the existing `health` panel (`_PANELS` has
  `health` -> `health_panel.render_health`). If it does, delete the button instead.
- **`operator_mode`** (`commercial_ui.py:307`): `ClientMode.set_operator()` exists at
  `commercial_ui.py:267` but `ClientMode` is never instantiated anywhere. Needs a decision about where
  mode state lives and survives a restart. Not a renderer.

## Tranche D: expensive, do not start without a scoped decision (4 actions, 20 sites)

- **`fix_all`, 11 sites** across `command_palette.py:26`, `diagnose_panel.py:62/65/78`,
  `features_panel.py:11` and 6 more, spanning moat checks, incidents, Otto policy and per-project CI,
  with no argument distinguishing them. The only callable, `auto_fixer.py:177 auto_fix_all()`, fixes
  cron, coordinator and config-push, which is none of those four domains. A shared handler is silently
  wrong at most of the 11 sites. Correct fix is per-site: give each button an argument naming its
  domain, then implement domains one at a time. This is the single biggest item in R7 and it is a
  design job, not a wiring job.
- **`onboard`, 6 sites** (`projects.py:390-393, 462, +1`). Root renderer exists at `projects.py:345`,
  but sub-verbs `new_product` / `client` / `template` have no handler, and `add` / `add_all` call
  `onboard_project()` which writes `projects.json` (`projects.py:41-44`) with no confirm screen. Needs
  the confirm pattern plus three sub-verb handlers.
- **`rsi_run`** (`rsi_control.py:106`). `trigger_cycle()` (`rsi_control.py:176`) shells out to
  `self_improve_runner.py --all`, a real code-generating cycle. Needs the `restart_confirm` pattern.
  Medium cost, well-defined, and the confirm pattern is copyable.
- **`deploy`** (`projects.py:342`). No deploy function exists anywhere; the only deploy-adjacent code
  is read-only CI status. This is "build a deployment system", not "wire a button". Recommend deleting
  the button until there is a deploy path worth triggering from a phone.

## Recommended order

1. Tranche B (3 deletes). Lowest cost, removes dead taps, drops the ratchet to 12.
2. `dependencies` from Tranche A as the pattern-setter, then re-cost.
3. Rest of Tranche A behind decisions D1 and D2.
4. `rsi_run` and `logs`, which are bounded.
5. Stop. `fix_all`, `onboard`, `deploy`, `operator_mode` and `setup_wizard` each want their own scope.

`setup_wizard` (`first_run.py:55`) is deliberately last: the only implementation,
`hermes_cli/setup.py:2899 run_setup_wizard()`, is an interactive TTY prompt loop that would block on a
stdin Telegram cannot provide. Porting it is a conversational-flow build, the most expensive item here
per button (one site).

## Gate discipline

Lowering the ratchet at `test_every_button_dispatches.py:224` must happen in the same commit as each
deletion or build, with the reason in the diff. `test_the_quarantine_has_no_stale_entries` (`:210`)
will fail if a button is deleted without removing its `_UNBUILT` entry, so the two edits are forced to
travel together. That is the mechanism working as designed, not an obstacle.
