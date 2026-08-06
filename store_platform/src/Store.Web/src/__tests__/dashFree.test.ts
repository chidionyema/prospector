/**
 * Contract test: no em-dashes (—) or en-dashes (–) in any TS or TSX source file
 * under pages/, components/ or lib/. They are the most universally recognised AI
 * writing signature, and explicit copy on a storefront that pitches source-or-die
 * should not read like a model output.
 *
 * WIDENED 2026-08-05 from .tsx to .ts. `lib` was already in ROOTS, but `walk()` only collected
 * `.tsx`, and lib/copyConfig.ts is where every word of the marketing copy actually lives. The
 * home page hero subheading shipped "go-to-market plan — every claim backed by a source you can
 * open" with this test green, because the string is in a `.ts` file. The guard was checking the
 * files least likely to hold prose and skipping the one file that is nothing but prose.
 *
 * A line may opt out with a `dash-free-ignore` comment, for code that must match these characters
 * rather than display them (see lib/discovery.ts TITLE_SEPARATORS).
 *
 * The corresponding Python `nodash()` (tools/make_kill_log.py) normalises
 * kill-log.json at publish time. This test pins the equivalent guarantee for
 * every committed source file.
 *
 * Run via `npm test dashFree` (or the project's normal test command).
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";

import { nodash } from "@/lib/text";

// Test runs from src/__tests__/; the pages, components and lib directories are siblings.
const ROOTS = ["pages", "components", "lib"];
const FS_ROOT = path.resolve(__dirname, "..");

const EM = "\u2014";
const EN = "\u2013";
/** Opt-out pragma for lines that must contain these characters as data, not as copy. */
const IGNORE = "dash-free-ignore";

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      // Test files are not shipped copy, and their names legitimately describe behaviour
      // ("extractIntent — natural language → facet values"). Only source is in scope.
      if (entry.name === "__tests__") continue;
      out.push(...walk(full));
    } else if (entry.isFile() && /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

interface Offender {
  file: string;
  line: number;
  text: string;
}

const offenders: Offender[] = [];

describe("dash-free storefront source", () => {
  for (const root of ROOTS) {
    for (const file of walk(path.resolve(FS_ROOT, root))) {
      const text = fs.readFileSync(file, "utf8");
      const lines = text.split("\n");
      lines.forEach((line, i) => {
        if ((line.includes(EM) || line.includes(EN)) && !line.includes(IGNORE)) {
          offenders.push({
            file,
            line: i + 1,
            text: line.trim().slice(0, 140),
          });
        }
      });
    }
  }

  it("removes em-dashes and en-dashes from every TS/TSX source file", () => {
    if (offenders.length === 0) return;
    const summary = offenders
      .slice(0, 20)
      .map((o) => `  ${o.file}:${o.line}: ${o.text}`)
      .join("\n");
    const more = offenders.length > 20 ? `\n  ... and ${offenders.length - 20} more` : "";
    throw new Error(
      `${offenders.length} em/en-dash offender(s) found in source:\n${summary}${more}`,
    );
  });

  /*
   * The hole the rule above left open.
   *
   * Banning the dash characters makes ` -- ` the obvious thing to type instead, and nothing
   * between a template literal and the DOM converts it: the storefront has no markdown parser
   * (the same reason `prospector/plain_text.py` exists on the engine side). /pricing shipped
   * "it is one payment -- no subscription, no upsell" and printed two literal hyphens on the
   * page that argues about money, with this file green (desktop-pricing-fold.png, 2026-08-06).
   *
   * Comments are stripped first, because ` -- ` is the house style INSIDE comments (this
   * paragraph would otherwise fail) and a comment never reaches a buyer. Only the spaced form
   * is matched, so `i--`, `--i` and CSS custom properties like `var(--primary)` are untouched.
   *
   * The fix is never an en dash. It is a colon, a comma, or a shorter sentence.
   */
  const RENDERED_DOUBLE_HYPHEN: Offender[] = [];
  for (const root of ROOTS) {
    for (const file of walk(path.resolve(FS_ROOT, root))) {
      const stripped = fs
        .readFileSync(file, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
        .replace(/^[ \t]*\/\/.*$/gm, "");
      stripped.split("\n").forEach((line, i) => {
        if (/\s--\s/.test(line) && !line.includes(IGNORE)) {
          RENDERED_DOUBLE_HYPHEN.push({ file, line: i + 1, text: line.trim().slice(0, 140) });
        }
      });
    }
  }

  it("has no ` -- ` standing in for a dash in rendered strings", () => {
    expect(
      RENDERED_DOUBLE_HYPHEN.map((o) => `${o.file}:${o.line}: ${o.text}`),
      "` -- ` renders literally; use a colon or a comma, never an en dash",
    ).toEqual([]);
  });

  /*
   * The second hole, and the one that actually shipped. `&mdash;` is an em dash to a browser and
   * an ampersand-m-d-a-s-h to a character scan, so the rule above cannot see it. /pack/[id]
   * rendered "Every source below is a live link — open one and check the claim before you buy."
   * with both tests above green; found by grepping the RENDERED HTML of the production build
   * rather than the source (2026-08-06):
   *
   *   curl -s http://localhost:3111/pack/c8fbb7aa12e1bf48 | grep -o '[—–]'
   *
   * That is the general lesson: a source-text guard proves what was typed, never what was served.
   */
  const ENTITIES = /&(mdash|ndash|#8212|#8211|#x2014|#x2013);/i;
  const ENTITY_OFFENDERS: Offender[] = [];
  for (const root of ROOTS) {
    for (const file of walk(path.resolve(FS_ROOT, root))) {
      fs.readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          if (ENTITIES.test(line) && !line.includes(IGNORE)) {
            ENTITY_OFFENDERS.push({ file, line: i + 1, text: line.trim().slice(0, 140) });
          }
        });
    }
  }

  it("has no dash HTML entity smuggling a dash past the character scan", () => {
    expect(
      ENTITY_OFFENDERS.map((o) => `${o.file}:${o.line}: ${o.text}`),
      "&mdash;/&ndash; render as dashes; use a colon or a comma",
    ).toEqual([]);
  });
});

/*
 * The two rules above cover source files. Catalogue prose is not a source file: it arrives from
 * the API at runtime, and 52 of 61 live pack titles carry an en dash, so the normaliser in
 * `lib/text.ts` is the only thing standing between that copy and the page.
 *
 * `lib/text.ts` claims its substitution rules are "byte-for-byte identical" to the Python
 * `nodash()` in `tools/make_kill_log.py`. Nothing enforced that: the numeric-range rule was added
 * to the TypeScript first and the Python twin lagged behind in the same edit. Each expectation
 * below is the literal output of the Python implementation, captured 2026-08-06:
 *
 *   .venv/bin/python -c "...; print(m.nodash(case))"
 *
 * If a change here makes a case fail, the twin has drifted; fix both or fix neither.
 */
describe("nodash() matches its Python twin in tools/make_kill_log.py", () => {
  const CASES: [input: string, expected: string][] = [
    // A dash between digits is a range. A comma states something the source did not say.
    ["Mothers 25–45 — the parent's tool", "Mothers 25-45, the parent's tool"],
    ["Gen Z gig workers (18–27)", "Gen Z gig workers (18-27)"],
    ["for 2025–2026", "for 2025-2026"],
    // Compound words survive: only a dash with whitespace around it is prose punctuation.
    ["out-of-hours cover — slip-resistance", "out-of-hours cover, slip-resistance"],
    // The comma absorbs the space the dash left behind, rather than printing "Brand , X".
    ["Brand — X", "Brand, X"],
  ];

  it.each(CASES)("normalises %j", (input, expected) => {
    expect(nodash(input)).toBe(expected);
  });
});
