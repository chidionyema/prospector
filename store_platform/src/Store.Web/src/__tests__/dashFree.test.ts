/**
 * Contract test: no em-dashes (—) or en-dashes (–) in any TSX source file
 * under pages/ or components/. They are the most universally recognised AI
 * writing signature, and explicit copy on a storefront that pitches source-or-die
 * should not read like a model output.
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

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(full));
    } else if (entry.isFile() && entry.name.endsWith(".tsx")) {
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
        if (line.includes(EM) || line.includes(EN)) {
          offenders.push({
            file,
            line: i + 1,
            text: line.trim().slice(0, 140),
          });
        }
      });
    }
  }

  it("removes em-dashes and en-dashes from every TSX source file", () => {
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
