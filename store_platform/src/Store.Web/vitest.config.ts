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
 */
const maxWorkers = Number(process.env.VITEST_MAX_FORKS)
  || Math.max(1, Math.min(4, Math.floor(availableParallelism() / 2)));

/**
 * Unit tests for the pure discovery core (`src/lib/*`). `environment: 'node'` is deliberate:
 * nothing under test touches the DOM, and jsdom costs ~1s of startup per run for no coverage.
 * A component test added later should set `// @vitest-environment jsdom` in its own file
 * rather than slowing the whole suite down.
 */
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
    exclude: ['node_modules/**', '.next/**', 'e2e/**'],
    maxWorkers,
  },
});
