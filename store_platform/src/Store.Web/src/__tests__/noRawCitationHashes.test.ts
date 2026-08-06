/**
 * Contract test: no raw passage hash reaches a rendered page.
 *
 * The engine references retrieved passages inline as `(a95e55366ce78462)` or
 * `[e646bf90d84a4530, a95e55366ce78462]`. That is an internal handle. To a reader it is a 16-hex
 * blob in parentheses where a citation should be, which on a storefront whose entire pitch is
 * source-or-die reads as an invented reference: the one thing the free report exists to disprove.
 *
 * `tools/make_kill_log.py` already resolved them to real URLs and dropped the unresolvable ones.
 * `tools/make_sample_report.py` did not, so /sample printed
 * "(a95e55366ce78462)" and "(e646bf90d84a4530, a95e55366ce78462)" literally in the premortem panel,
 * which is also the ONE block on that page with no citation chips under it, so the only visible
 * references on the page were the unusable ones (desktop-sample-full.png, 2026-08-06).
 *
 * These files are regenerated from dossiers on every batch, so the fix has to be re-checked rather
 * than remembered. That is what this test is.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";

const DATA = path.resolve(__dirname, "..", "data");

/** A 16-hex handle in citation position. Not a bare hex run: an id or a hash elsewhere is fine. */
const CITATION_REF = /[([]\s*[0-9a-f]{16}(?:[,;]\s*[0-9a-f]{16})*\s*[)\]]/g;

describe("baked report data carries no raw passage hashes", () => {
  const files = fs
    .readdirSync(DATA)
    .filter((f) => f.endsWith(".json"))
    .map((f) => path.join(DATA, f));

  it("has JSON data files to check", () => {
    // Without this, a rename of the data directory makes every assertion below pass on an empty
    // list, which is the failure mode this whole suite is written against.
    expect(files.length).toBeGreaterThan(0);
  });

  for (const file of files) {
    it(`${path.basename(file)} prints no citation hash`, () => {
      const raw = fs.readFileSync(file, "utf8");
      const hits = [...raw.matchAll(CITATION_REF)].map((m) => m[0]);
      expect(
        [...new Set(hits)],
        `resolve these to a real URL or drop them, the way make_kill_log.py does:\n${hits.join("\n")}`,
      ).toEqual([]);
    });
  }
});
