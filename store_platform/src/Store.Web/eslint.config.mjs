import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";
import tailwind from "eslint-plugin-tailwindcss";

/**
 * Foundation Wave enforcement (docs/ux/WEB-FOUNDATION-WAVE.md).
 * These rules make the war-room rails fail the build, not just a reviewer's eye:
 *   - no `any` / no ts-suppression  → types stay honest
 *   - no `alert`/`confirm`/`prompt` → no browser-chrome UX
 *   - no `dangerouslySetInnerHTML`  → no XSS sink
 *   - no `localStorage`/`sessionStorage` for tokens → SECURE-UI §3
 *   - no raw `fetch` outside src/lib/api → all HTTP flows through the hardened client
 *   - jsx-a11y/recommended → accessibility rails fail the build (docs/engineering/ACCESSIBILITY-STANDARDS.md)
 */
const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,

  // Accessibility enforcement. eslint-config-next ships only a thin slice of jsx-a11y; we opt into the
  // full recommended ruleset so label/alt/aria/role/keyboard violations are build failures, not review
  // nits. The plugin is already present (a Next dependency), so this adds no install. See
  // docs/engineering/ACCESSIBILITY-STANDARDS.md for the standard these rules enforce.
  {
    name: "tie/a11y",
    files: ["src/**/*.{ts,tsx}"],
    // Apply the recommended RULES only — eslint-config-next already registers the jsx-a11y plugin, so
    // re-registering it (by spreading the whole flat config) throws "Cannot redefine plugin".
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
      // Several domain components (ChatPanel, MeetingSchedulePanel, …) take a `role` PROP meaning
      // Buyer/Seller/Target — not an ARIA role. ignoreNonDOM scopes the check to real DOM elements so
      // those domain props don't trip it; ARIA roles on actual elements are still validated.
      "jsx-a11y/aria-role": ["error", { ignoreNonDOM: true }],
      // A radio/checkbox label that nests its control plus a two-line text block (a styled <span> wrapping
      // a <span> title + <span> description) puts the visible text at tree depth 3. The rule's default
      // depth is 2, so it would mis-fire on a genuinely-accessible nested label (e.g. auth/choose-role).
      // Raise the walk to depth 3 so those labels validate honestly instead of needing an inline disable.
      "jsx-a11y/label-has-associated-control": ["error", { depth: 3 }],
      // `<ul role="list">` reads as redundant to the linter, but it is the documented fix for the
      // Safari + VoiceOver bug where applying `list-style: none` (Tailwind's preflight does this to every
      // <ul>) strips the list role and the announced item count. We genuinely want the explicit role on
      // our card lists (e.g. the board), so allow it for <ul>; nav→navigation still uses the default.
      "jsx-a11y/no-redundant-roles": ["error", { ul: ["list"] }],
    },
  },

  {
    name: "tie/foundation-rails",
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      // A leading underscore is how this codebase already says "deliberately unused" — the stub
      // signatures in lib/api/client.ts keep named parameters so the shape of the real API stays
      // readable. The convention was written but never configured, so it produced warnings for
      // saying exactly what the rule wanted said. Anything NOT underscored still reports.
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
        },
      ],
      "@typescript-eslint/ban-ts-comment": [
        "error",
        { "ts-expect-error": true, "ts-ignore": true, "ts-nocheck": true, "ts-check": false },
      ],
      "no-alert": "error",
      "react/no-danger": "error",
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: "Tokens/PII never go in localStorage (XSS-exfiltratable) — SECURE-UI §3. Use the in-memory token in lib/api/client.ts." },
        { name: "sessionStorage", message: "Use the in-memory token in lib/api/client.ts, not web storage — SECURE-UI §3." },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.name='fetch']",
          message: "Components never call fetch directly. Route all HTTP through src/lib/api/client.ts — UI-STANDARDS §4.",
        },
        {
          selector: "MemberExpression[object.name='window'][property.name='fetch']",
          message: "Components never call fetch directly. Route all HTTP through src/lib/api/client.ts — UI-STANDARDS §4.",
        },
      ],
    },
  },

  // The hardened client is the ONE place allowed to call fetch.
  {
    name: "tie/api-client-exception",
    files: ["src/lib/api/**/*.ts"],
    rules: {
      "no-restricted-syntax": "off",
    },
  },

  // A/B testing exception for landing page.
  {
    name: "tie/landing-page-exceptions",
    files: ["src/pages/index.tsx"],
    rules: {
      "no-restricted-globals": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },

  // Tailwind class hygiene. The storefront's utility classes are written by hand across ~90
  // components, and two failure modes there are invisible in review: a contradiction
  // (`p-2 p-4` — the later one silently wins) and a shorthand that reads as two different
  // properties (`mt-2 mb-2` vs `my-2`). Both are class strings that LOOK fine and render wrong.
  //
  // `no-custom-classname` is OFF, deliberately. The shipped design bundle `src/styles/mumchimp.css`
  // defines the class vocabulary this site is built from (`.d`, `.desc`, `.strip`, `.hdr`, `.tag`),
  // it is byte-locked by a test, and the rule cannot see it — so every one of those classes would
  // report as a typo. A rule that fires on the house style is a rule that gets disabled inline
  // everywhere, which is worse than not having it.
  {
    ...tailwind.configs.recommended,
    name: "tie/tailwind",
    files: ["src/**/*.{ts,tsx}"],
    // Tailwind v4 is configured in CSS, and the plugin looks for `src/style.css` by default --
    // which this app does not have, so eslint died with ENOENT before judging a single file.
    // Point it at the real entry stylesheet.
    settings: { tailwindcss: { cssConfigPath: "./src/styles/globals.css" } },
    rules: {
      ...tailwind.configs.recommended.rules,
      // `p-2 p-4` — the second silently wins, and the class string looks deliberate either way.
      // The only rule here that gates.
      "tailwindcss/no-contradicting-classname": "error",
      // `mt-2 mb-2` reads as two decisions where there is one. Cheap to fix, small count.
      "tailwindcss/enforces-shorthand": "warn",
      // Tailwind v4 moved the important marker to the end (`pt-6!`). The old form still parses,
      // so this is a migration hint rather than a defect.
      "tailwindcss/important-modifier-suffix": "warn",
      /**
       * OFF, on a measurement. Enabled as a warning it reported 408 of the 517 findings in this
       * package, every one of them "these classes are in a different order than the plugin would
       * write them" — no rendering difference, no defect, and autofixing them would rewrite a few
       * hundred lines of JSX to satisfy a preference. A rule at that volume is a rule people learn
       * to scroll past, and it would bury the contradiction rule above it.
       */
      "tailwindcss/classnames-order": "off",
      "tailwindcss/no-custom-classname": "off",
    },
  },

  // Override default ignores of eslint-config-next.
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    ".quarantine/**",
    // Generated Playwright artifacts (git-ignored): minified vendor bundles,
    // not source. Linting them produced 164 phantom errors. Never lint output.
    "playwright-report/**",
    "test-results/**",
    "playwright/.cache/**",
    // Storybook build output. Same reason as above: generated, minified, not source.
    "storybook-static/**",
  ]),
]);

export default eslintConfig;
