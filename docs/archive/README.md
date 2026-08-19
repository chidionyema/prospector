# Archive — historical documents, not procedure

Nothing in here is current. Do not follow any command in these files.

They live here rather than at the repo root because a stale runbook is not a neutral old file:
it is a set of instructions that still reads as authoritative. `DEPLOYMENT.md` opened with
*"Executable, command-level steps to ship the storefront"* and described 11 listed packs and a
store that had not yet taken real money. Both were false — 42 listed, live money since
2026-07-30. Someone acting on it would operate on a store that no longer exists. A warning
banner does not fix that, because the file still sits next to `README.md` looking like the
deploy doc.

They are kept, not deleted, because they record *why* decisions were made — which the git
history alone does not.

## Where the current answers live

| Question | Document |
|---|---|
| What do I run when something is wrong? | `store_platform/OPERATIONS.md` |
| How do I deploy? | `store_platform/deploy/PROD_DEPLOY.md` |
| How does the engine work? | `README.md`, `RUN.md`, `prospector-master-spec.md` |
| What are the operating rules? | `CLAUDE.md` |

## Contents

### `2026-06/`

Written 15–20 June 2026, when the store was pre-launch, in Stripe TEST mode, with 11 packs.

- `DEPLOYMENT.md` — go-live procedure. Superseded by `store_platform/deploy/PROD_DEPLOY.md`,
  which adds the hard rule this one lacks: `fly deploy` ships the **working tree**, not `HEAD`.
- `GO_LIVE_SPEC.md` — pre-launch readiness assessment. The launch happened.
- `HANDOVER.md`, `HANDOVER_BRIDGE_TO_LAUNCH.md` — build-ready specs for an agent continuing the
  build. Useful as design rationale; wrong as instructions.

### `2026-08/`

Moved here 2026-08-19 from the repo ROOT, where they sat beside `README.md` and `RUN.md` reading
as current procedure. Neither is referenced by any tracked file.

- `GENERATION_PROCESS.md` — a map of the generation path written 2026-06-22. Its headline number
  is false today: it reports "50 candidates vetted -> 0 PASS -> 0 published", and the live
  catalogue carries 75 published packs. Its `file:line` citations were gathered by subagents in
  June and have drifted; the file says so itself.
- `POSTMORTEM_ZERO_YIELD_2026-06-28.md` — the postmortem for that zero-yield fortnight. The bug
  it describes (a silent fallback to a broken query generator) was fixed on 2026-06-28. Kept for
  the reasoning, not the state.

## Adding to this archive

Move the file here rather than banner it in place, and say in its notice **which specific claim
is false and what the live value is**. "Possibly outdated" gives a reader nothing to act on;
"says 11 packs, live is 42" ends the argument.
