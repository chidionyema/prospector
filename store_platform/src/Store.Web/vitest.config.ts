import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vitest/config';

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
  },
});
