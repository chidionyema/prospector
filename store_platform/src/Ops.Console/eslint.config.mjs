/**
 * ESLint flat config.
 *
 * `npm run lint` was a dead command: the script existed, the packages were on disk, and ESLint 9
 * exited on "couldn't find an eslint.config.(js|mjs|cjs)". A lint that cannot run is worse than no
 * lint, because the script's presence reads as coverage.
 *
 * `eslint-config-next` 16 ships flat configs directly, so they are imported, not translated. Going
 * through `FlatCompat` instead crashes inside the old config validator with "Converting circular
 * structure to JSON" — the eslintrc path cannot serialise a config that already holds plugin
 * objects.
 */
import coreWebVitals from 'eslint-config-next/core-web-vitals';
import typescript from 'eslint-config-next/typescript';

const config = [
  {
    ignores: [
      '.next/**',
      'node_modules/**',
      'next-env.d.ts',
      'playwright-report/**',
      'test-results/**',
    ],
  },
  ...coreWebVitals,
  ...typescript,
  {
    rules: {
      // The console renders engine prose it does not control. Escaping every apostrophe in copy
      // buys nothing here and pushes writers towards worse sentences.
      'react/no-unescaped-entities': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
];

export default config;
