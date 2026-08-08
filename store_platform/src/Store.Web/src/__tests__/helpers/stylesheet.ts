import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

/**
 * Read a stylesheet the way the BROWSER sees it: with its local `@import`s inlined.
 *
 * WHY THIS EXISTS. Six test files read `styles/globals.css` with `readFileSync` and assert on the
 * design tokens declared in it. When the §3 redesign moved the tokens into `styles/tokens.css` and
 * left `@import "./tokens.css";` behind, every one of those assertions failed at once -- 21 of
 * them -- and each failure read as a deleted token ("--bg must be clean white", "--primary must be
 * ink") rather than as what it was: the same tokens, one file to the left. The guards were
 * measuring the wrong bytes, not a regression.
 *
 * The mirror-image failure is the dangerous one and this is the same fix for it. Had the move gone
 * the other way -- a guard that asserts a token is ABSENT, or that a forbidden property never
 * appears -- reading only `globals.css` would have gone GREEN over a violation sitting in the
 * imported file, and nothing would have said so. A file-boundary is not a policy boundary.
 *
 * Scope is deliberately narrow: relative imports only, resolved against the importing file. A
 * bare specifier (`@import "tailwindcss";`) resolves through the bundler and is left as the
 * literal text it is, so a test asserting on the import line still sees it.
 */
export function readStylesheet(absolutePath: string, seen = new Set<string>()): string {
  const path = resolve(absolutePath);
  // A cycle here would recurse until the stack blew, and the stack trace would name the test
  // rather than the stylesheet. Emit the offending path instead.
  if (seen.has(path)) return `/* circular @import skipped: ${path} */`;
  seen.add(path);

  const source = readFileSync(path, 'utf8');
  const here = dirname(path);

  return source.replace(
    /@import\s+(?:url\()?["']([^"']+)["']\)?\s*;/g,
    (whole, specifier: string) => {
      if (!specifier.startsWith('.')) return whole;
      return readStylesheet(resolve(here, specifier), seen);
    },
  );
}
