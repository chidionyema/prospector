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
import tailwind from 'eslint-plugin-tailwindcss';

const config = [
  {
    ignores: [
      '.next/**',
      'node_modules/**',
      'next-env.d.ts',
      'playwright-report/**',
      'test-results/**',
      'storybook-static/**',
    ],
  },
  ...coreWebVitals,
  ...typescript,
  /**
   * Tailwind class strings, checked as code rather than read as text.
   *
   * `no-contradicting-classname` is the one that earns its place: `px-2 px-4` in the same string
   * is a bug you cannot see in review and the browser resolves silently by source order.
   *
   * Two rules are deliberately OFF. `classnames-order` was 408 of 517 findings on the storefront
   * -- a wall of ordering advice that buries everything else. `no-custom-classname` fires on
   * every class this console defines itself (`tap`, `wrap-any`, `sw9`), which are the vocabulary
   * of the design, not mistakes.
   */
  {
    ...tailwind.configs.recommended,
    name: 'ops/tailwind',
    files: ['src/**/*.{ts,tsx}'],
    settings: { tailwindcss: { cssConfigPath: './src/styles/globals.css' } },
    rules: {
      ...tailwind.configs.recommended.rules,
      'tailwindcss/no-contradicting-classname': 'error',
      'tailwindcss/enforces-shorthand': 'warn',
      'tailwindcss/classnames-order': 'off',
      'tailwindcss/no-custom-classname': 'off',
    },
  },
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
