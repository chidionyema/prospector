import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A `text-*` CLASS THAT MAPS TO NO TOKEN EMITS NOTHING, AND NOTHING IS SILENT.
 *
 * Tailwind v4 builds its utilities from the `@theme` block. `text-h3` compiles only while
 * `--text-h3` is declared there; the day that token is deleted the class stops emitting a rule
 * and the build stays green, the lint stays green, and the element quietly renders at whatever
 * it inherits. Preflight sets every heading to `font-size: inherit`, so a heading that loses its
 * only size class does not fall back to a heading size -- it falls back to the body size, and
 * the page looks slightly wrong in a way nobody can point at.
 *
 * `--text-h3` was deleted from the scale on purpose (`tokens.css`: six steps, "so nothing can
 * reach for a seventh step without editing this block"). The deletion was correct. What it did
 * not do was find the markup already wearing the class. Two rounds of hand-fixing found three
 * call sites -- the pack-prose sub-head and two of the three mosaic tile bands -- and each left
 * a comment explaining the trap, which is the clearest possible sign that nothing was stopping
 * the next one. Two more were still live on 2026-08-30 and were measured on the built pages:
 * every clause heading on /terms, /privacy and /refund, and the amber callout on /sample, all
 * rendering at 16px, the body size, against a page whose next step up is 19px.
 *
 * This is the guard that closes it for the whole family rather than for `text-h3`: any `text-*`
 * token in the markup must resolve to a `--text-*` size or a `--color-*` colour actually
 * declared in the theme. It runs in vitest, which CI runs -- the e2e project that measures the
 * rendered page is not part of any CI job, so a browser-side assertion could not have held this.
 */
const WEB = path.resolve(__dirname, "..", "..");
const SRC = path.join(WEB, "src");
const TOKENS = path.join(WEB, "src/styles/tokens.css");
const SKIP_DIRS = new Set(["node_modules", "__tests__", "styles", ".next"]);

/**
 * Tailwind's own `text-*` utilities that are neither a size nor a colour, so no theme token
 * backs them. `text-current` and `text-transparent` are keyword colours; the rest set
 * `text-align`, `text-wrap` or `text-overflow` and only share the prefix.
 */
const BUILT_IN = new Set([
  "text-center",
  "text-left",
  "text-right",
  "text-justify",
  "text-start",
  "text-end",
  "text-wrap",
  "text-nowrap",
  "text-balance",
  "text-pretty",
  "text-clip",
  "text-ellipsis",
  "text-current",
  "text-transparent",
  "text-inherit",
  "text-white",
  "text-black",
]);

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (!SKIP_DIRS.has(entry)) walk(full, out);
    } else if (/\.(tsx|ts|jsx)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * Comments come out first, and that is not tidiness -- it is the only reason this check can be
 * strict. Every fix in this family left a note behind naming the dead class it had just removed,
 * so a scan of the raw text reports the cure as the disease. Stripping comments leaves the
 * classes an element can actually wear, wherever they are written: an attribute, a `cx()`
 * argument, or a bare constant like `CollectionMosaic`'s `TILE_TITLE`, which is where one of
 * these hid the first time.
 */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
}

function declaredTokens(): Set<string> {
  const css = readFileSync(TOKENS, "utf8");
  const out = new Set<string>();
  for (const m of css.matchAll(/--(?:text|color)-([a-z0-9-]+)\s*:/g)) out.add(`text-${m[1]}`);
  return out;
}

describe("every text utility in the markup resolves to a theme token", () => {
  it("wears no text-* class the theme cannot compile", () => {
    const declared = declaredTokens();
    expect(declared.has("text-h2"), "the token scan found no scale at all").toBe(true);

    const dead: string[] = [];
    for (const file of walk(SRC)) {
      const rel = path.relative(WEB, file);
      const source = withoutComments(readFileSync(file, "utf8"));
      // Not preceded by `-`, so `var(--text-display--font-weight)` is not read as a class.
      /*
       * A trailing `:` means a CSS property, not a class -- `text-decoration: none` in the
       * inline styles of the receipt email. A variant prefix puts its colon BEFORE the class
       * (`hover:text-accent-hover`), so the two never collide.
       */
      for (const m of source.matchAll(/(^|[^-\w])(text-[a-z][a-z0-9]*(?:-[a-z0-9]+)*)(:?)/g)) {
        const cls = m[2];
        if (m[3] === ":" || BUILT_IN.has(cls) || declared.has(cls)) continue;
        dead.push(`${rel}: ${cls}`);
      }
    }
    expect(
      [...new Set(dead)].sort(),
      "a text-* class with no theme token emits no rule; a heading wearing it renders at the body size",
    ).toEqual([]);
  });
});
