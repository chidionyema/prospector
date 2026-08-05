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
import { describe, it } from "vitest";

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
});
