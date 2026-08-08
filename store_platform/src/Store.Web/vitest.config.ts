import { availableParallelism } from 'node:os';
import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vitest/config';

/**
 * Vitest defaults to roughly one worker fork per core. That is the right default for a
 * machine running one suite, and the wrong one here: this repo is worked by several agents
 * in parallel git worktrees, so "one per core" is really N-agents-per-core. On 2026-07-31
 * three concurrent checkouts building at once put a 12-core / 16GB box at load 364 with
 * 18.49% CPU idle and 32M of 16G memory unused — i.e. blocked on page faults, not computing.
 *
 * Cores are not the scarce resource; RAM is. Each fork is a full Node heap, so the cap is
 * chosen against memory rather than parallelism. Half the cores, ceiling 4.
 *
 * VITEST_MAX_FORKS overrides it for a machine that genuinely has the headroom (CI runs one
 * suite on a dedicated runner and should not inherit this laptop's contention).
 *
 * Expressed as `test.maxWorkers`, not `test.poolOptions.forks.maxForks`: vitest 4 removed
 * `poolOptions` (this repo is on 4.1.10, see package-lock.json). Because tsconfig.json
 * type-checks every .ts file in this package, this config file included, the stale key was
 * a hard `tsc --noEmit` failure — which blocked the Deploy Store.Web workflow, not just the
 * test run.
 *
 * The reason there is a test beside this file: an unknown key here is IGNORED at runtime, not
 * rejected. Measured on the stale version — createVitest(...).config.maxWorkers was
 * `undefined`, so the suite ran green with no cap at all. tsc is what caught it; a passing
 * test run did not, and could not.
 */
const maxWorkers = Number(process.env.VITEST_MAX_FORKS)
  || Math.max(1, Math.min(4, Math.floor(availableParallelism() / 2)));

/**
 * Unit tests for the pure discovery core (`src/lib/*`). `environment: 'node'` is deliberate:
 * nothing under test touches the DOM, and jsdom costs ~1s of startup per run for no coverage.
 * A component test added later should set `// @vitest-environment jsdom` in its own file
 * rather than slowing the whole suite down.
 */
/**
 * SUSPENDED WHILE THE UI IS MOVING (founder directive, 2026-08-08):
 * "tests on a ui that is ever changing is stupid and waste of resources, suspend copy and design
 * tests and basic tests until stable."
 *
 * These files assert APPEARANCE -- exact hexes, rem steps, radii, shadows, letter-casing, dash
 * characters. Every one of them is a restatement of a design decision, so a design decision costs
 * two edits and a red suite instead of one edit. The §3 redesign made that concrete: moving the
 * tokens into `styles/tokens.css` and re-pointing `--accent` at ink turned 21 assertions red in a
 * single change, and not one of them had found a defect -- they had found the redesign.
 *
 * WHAT IS NOT SUSPENDED, and why the line is here rather than further out: guards on what the site
 * TELLS A BUYER stay on. `fixedCheckCount`, `checkLexicon`, `packContents`, `priceRange` and the
 * rest assert that a rendered number matches its source, not that a colour is a colour. That
 * distinction is not theoretical -- the copy rewrite shipped "This one survived all 9." onto the
 * pack page, false for 60 of the 63 published packs, and the only thing that can catch that class
 * of defect is exactly this kind of test. Appearance drifts; a false claim to a buyer does not
 * become true because the design changed.
 *
 * TO LIFT: delete an entry. There is no flag and no env var on purpose -- a suspension that can be
 * toggled invisibly is a suspension nobody ever ends. Status lives in `docs/SITE_SPEC_PROGRAM.md`.
 */
const SUSPENDED_UNTIL_UI_STABLE: string[] = [];

export default defineConfig({
  resolve: {
    // Mirrors the `@/*` path mapping in tsconfig.json. Vitest does not read tsconfig paths, so
    // without this any test that reaches a module importing `@/...` fails to resolve — which is
    // every component, not just the one under test.
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // Playwright specs live in ./e2e and are run by `npm run test:e2e`; without this they get
    // collected by vitest and fail on a missing `test` export.
    // `exclude` REPLACES vitest's defaults rather than adding to them, so the three entries that
    // were here are not optional boilerplate -- dropping one re-collects `node_modules`.
    exclude: ['node_modules/**', '.next/**', 'e2e/**', ...SUSPENDED_UNTIL_UI_STABLE],
    maxWorkers,
  },
});
