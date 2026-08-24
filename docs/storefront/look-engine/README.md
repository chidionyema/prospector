# The look engine

A prototype for the storefront redesign programme in
[`../../STOREFRONT_REDESIGN_PROGRAM.md`](../../STOREFRONT_REDESIGN_PROGRAM.md). Ten identities
render one component tree. Nothing in the markup names a look, and no look carries a hand-written
colour: a look is a **seed plus a switch set plus a type pairing**, and the palette is computed
from the seed under a contrast audit that can refuse it.

`build.sh` concatenates `parts/*` into one self-contained `looks-engine.html` and regenerates the
two index pages. Open that file directly — there is no server and no build step beyond `bash
build.sh`.

## Running it

```bash
bash build.sh                 # -> looks-engine.html, gallery.html, tools.html
bash runlog.sh node verify.mjs    # every tool is run through runlog.sh, which writes logs/<tool>.log
```

Two paths are borrowed rather than owned, and both are overridable by an environment variable
because the defaults are absolute paths on the machine this was written on:

| Variable | What it points at | Default |
|---|---|---|
| `PLAYWRIGHT_MJS` | the storefront's own `playwright/index.mjs` | `store_platform/src/Store.Web/node_modules/playwright/index.mjs` in a scratchpad worktree |
| `PROGRAM_DOC` | the programme doc `check.mjs` audits gate numbers against | `../../STOREFRONT_REDESIGN_PROGRAM.md`, then the worktree copy |

## What is generated and therefore not in git

`looks-engine.html`, `gallery.html`, `tools.html` and `shots/` are all built from what is here.
`shots/` alone is 21MB of PNGs and is rebuilt by `node verify.mjs`. The rule the whole prototype
follows: **generated, not written** — `gallery.html` and `tools.html` are emitted by scripts that
read the disk, so a page cannot claim a sample or a tool that is not there.

## The tools

Every tool starts with an `@ledger` line naming what it does, how it is run, and which gate it
implements. `tools.mjs` regenerates the ledger page from those lines, so the page cannot list a tool
that is not on disk. It does NOT refuse a wrong one: measured 2026-08-20, an `@ledger` line
naming a script that does not exist was rendered into the page and `tools.mjs` exited 0.
That is why it is a generator and not one of the gate's lane steps.

| Tool | Gate | What it refuses |
|---|---|---|
| `verify.mjs` | A54 and the browser gates | contrast, overflow, tap targets under 44px, blank plates, clipped text, painted-leaf collisions, console errors — 104 cells |
| `check.mjs` | A42, A43, gate-number audit | a CSS rule that names a look; a look carrying a hex value; a gate number a tool claims and the doc does not define |
| `coldopen.mjs` | A46, A48, A49 | a first screen that does not answer "what is this" and "is it for me" at 320px |
| `persist.mjs` | A45 | a rolled look that does not survive a reload, a link, or being forgotten |
| `palette-test.mjs` | A44 | a random seed whose palette fails the contrast table |
| `overflow.mjs` | | horizontal overflow at any width |
| `seed.mjs` | | non-determinism in `rollLook(n)` |

`persist.mjs` serves the directory over http on an ephemeral port. That is not a preference:
`file://` has an opaque origin, so `localStorage.setItem` throws and a persistence test run from
`file://` passes by storing nothing.
