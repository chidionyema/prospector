import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";

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
  ]),
]);

export default eslintConfig;
