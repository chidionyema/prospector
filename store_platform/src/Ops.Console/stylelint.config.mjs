/**
 * STYLELINT for the ops console.
 *
 * `recommended` rather than `standard`, for the reason measured on the storefront the same day:
 * `stylelint-config-standard` reported 74 problems there and 67 of them were cosmetic
 * (quote style, number notation, keyword case). A first run that is 90% noise is a run whose
 * genuine findings are never read, and it is how a linter gets switched off in week two.
 * `recommended` is the set that only fires on things that are actually wrong.
 *
 * There is one stylesheet here, `src/styles/globals.css`, and it is Tailwind v4 CSS-first: the
 * config lives in the stylesheet as at-rules rather than in a JS file. Those at-rules are the
 * ignore list below -- without it every one reads as an unknown at-rule and the whole file is a
 * wall of false positives.
 */
const config = {
  extends: ['stylelint-config-recommended'],

  rules: {
    'at-rule-no-unknown': [
      true,
      {
        ignoreAtRules: [
          // Tailwind v4 CSS-first configuration.
          'theme',
          'source',
          'utility',
          'variant',
          'custom-variant',
          'apply',
          'reference',
          'config',
          'plugin',
          // v3 spellings, still valid in files not yet migrated.
          'tailwind',
          'layer',
          'screen',
        ],
      },
    ],

    // A shorthand written after a longhand silently erases it. This one is worth failing on: it
    // is invisible in review and it is always a mistake.
    'declaration-block-no-shorthand-property-overrides': true,

    // OFF, with the receipt. On the storefront this rule's single finding was a proven false
    // positive: the two selectors it paired set entirely different properties. The rule cannot
    // see that, so it costs more attention than it returns.
    'no-descending-specificity': null,
  },
};

export default config;
