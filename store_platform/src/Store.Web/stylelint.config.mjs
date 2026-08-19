/**
 * CSS LINTING, SCOPED TO THE CSS THIS REPO IS ALLOWED TO WRITE.
 *
 * The storefront has three stylesheets and they are not equal:
 *
 *   src/styles/mumchimp.css — the SHIPPED DESIGN BUNDLE. Byte-locked by a test
 *                             (a deviation belongs in globals.css, never here), so a lint
 *                             finding in it is unfixable by definition. Linting a file nobody
 *                             may edit only ever produces noise that trains people to ignore
 *                             the linter. IGNORED, on purpose.
 *   src/styles/tokens.css   — the design tokens. Ours to write, so linted.
 *   src/styles/globals.css  — Tailwind entry plus the deviations from the bundle. Ours, linted.
 *
 * Run: npm run lint:css   (and `npm run lint:css -- --fix` for the mechanical half)
 */
const config = {
  /**
   * `recommended`, NOT `standard`. The difference is stylistic rules, and measured on this repo
   * they report 74 problems in globals.css and tokens.css, of which 67 are "empty line before
   * comment", "#FFFFFF should be #FFF" and "0.07 should be 7%". Not one changes a rendered pixel.
   * Auto-fixing them would rewrite 74 lines of shipped CSS to satisfy a preference, and leaving
   * them red would make the lane noise from day one. `recommended` is the possible-errors half:
   * duplicate properties, unknown units, invalid hex, empty blocks, a shorthand that silently
   * overrides the longhand above it. Those are defects.
   */
  extends: ['stylelint-config-recommended'],
  ignoreFiles: [
    '**/node_modules/**',
    '.next/**',
    'storybook-static/**',
    'playwright-report/**',
    // See the block above. This file is the shipped bundle and is byte-locked.
    'src/styles/mumchimp.css',
  ],
  rules: {
    /**
     * Tailwind v4 is configured in CSS rather than a JS file, so the entry stylesheet is full of
     * at-rules stylelint has never heard of. Without this every one of them reports as an unknown
     * at-rule and the whole lane is red for using the framework as documented.
     */
    'at-rule-no-unknown': [
      true,
      {
        ignoreAtRules: [
          'theme',
          'source',
          'utility',
          'variant',
          'custom-variant',
          'apply',
          'reference',
          'config',
          'plugin',
          'tailwind',
          'layer',
          'screen',
        ],
      },
    ],
    /**
     * A shorthand after a longhand silently wipes it (`margin-top: 4px; margin: 0`). That is a
     * real defect and this is the rule that catches it, so it is on rather than inherited-off.
     */
    'declaration-block-no-shorthand-property-overrides': true,
    /**
     * OFF, on one measured case. It fired on globals.css:132, `main p` appearing after
     * `.htile p`. The rule compares selectors and ignores properties: the first block sets
     * `display`/`line-clamp`/`overflow`, the second sets `text-wrap`, and `.htile p` is the more
     * specific selector so it wins on both wherever they overlap. Nothing is shadowed. Reordering
     * the file to satisfy it would move a comment away from the change it explains for no
     * rendering difference.
     */
    'no-descending-specificity': null,
  },
};

export default config;
