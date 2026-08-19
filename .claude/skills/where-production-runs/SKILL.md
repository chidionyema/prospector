---
name: where-production-runs
description: Where the prospector engine, store API and console actually run, how the live checkout works, and the two traps that broke when production moved off this laptop. Load before rolling production forward, before reading the laptop's launchd jobs as a process table, or when a store path looks wrong.
---

# Where production runs

This was 968 tokens of CLAUDE.md, injected into every session including the ones that never touch
production. The live answer is a command and the SessionStart probe already prints it, so the
history belongs here and loads only when it is needed.

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
   level calls it — the health file records which brains are benched, and a daemon writing one
   copy while a probe reads another can never see a provider recover.

   **The trap is the two-step form, not the one-liner.** This rule used to end "never write
   `Path(__file__).parent.parent / "store"` again", and the sibling sweep was a regex for exactly
   that string. It found 2. An AST walk on 2026-08-19 found 40, because almost nobody writes it
   on one line:

   ```python
   ROOT = Path(__file__).resolve().parents[1]   # line 43, looks harmless
   ...
   DOSSIERS = ROOT / "store" / "dossiers"       # line 49, the actual bug
   ```

   A regex over one line cannot see a name bound on another. Do not sweep for this by grepping.
   `tests/unit/test_no_store_path_is_derived_from_file.py` is the check: it tracks the names, so
   it catches both forms and any third one, and its allow-list carries a reason per entry.
   Issue #371 has the full list and what was fixed.

