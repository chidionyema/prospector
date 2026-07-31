import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { PACK_CONTENTS } from '../PackContents';

/**
 * The storefront's deliverable list and the engine's bundle manifest are one claim in two deploy
 * units, and they drifted: this list said four documents while `BUNDLE_FILES` had grown to eight,
 * so buyers silently received an executive summary, a first-week checklist and a marketing-assets
 * file that no page ever mentioned. Nobody noticed because the only thing binding them was a
 * prose comment dated to a single afternoon's audit.
 *
 * This test is that binding, mechanised. It reads the tuple out of the Python source — the same
 * technique `lib/__tests__/facets.test.ts` uses against `PackFacets.cs` — so adding a file to the
 * bundle without advertising it, or advertising a file the bundle does not contain, fails here.
 *
 * Deliberately compared in ORDER, not as a set: the list is rendered to buyers top to bottom, and
 * a download whose files are numbered 00..05 should be described in that sequence.
 */
const BRIDGE_PY = fileURLToPath(new URL('../../../../../../../prospector/bridge.py', import.meta.url));

function bundleFilesFromPython(): string[] {
  const source = readFileSync(BRIDGE_PY, 'utf8');
  const block = /^BUNDLE_FILES\s*=\s*\(([\s\S]*?)\)/m.exec(source);
  if (!block) throw new Error(`Could not find the BUNDLE_FILES tuple in ${BRIDGE_PY}`);
  return Array.from(block[1].matchAll(/"([^"]+)"/g)).map((m) => m[1]);
}

describe('deliverable list agreement with prospector/bridge.py', () => {
  it('finds a non-trivial BUNDLE_FILES tuple to compare against', () => {
    // Guards the regex itself: a silently-empty match would make every assertion below vacuous.
    expect(bundleFilesFromPython().length).toBeGreaterThan(1);
  });

  it('advertises exactly the files the bundle contains, in order', () => {
    expect(PACK_CONTENTS.map((c) => c.filename)).toEqual(bundleFilesFromPython());
  });

  it('gives every advertised file a title and a description', () => {
    for (const item of PACK_CONTENTS) {
      expect(item.title.trim(), `title for ${item.filename}`).not.toBe('');
      expect(item.desc.trim().length, `description for ${item.filename}`).toBeGreaterThan(40);
      expect(item.emoji.trim(), `emoji for ${item.filename}`).not.toBe('');
    }
  });

  it('attaches the per-pack source count to the QA report and nothing else', () => {
    // The count is that pack's real cited-source total. Hanging it off any other file would
    // attribute the receipts to a document that does not carry them.
    const withCount = PACK_CONTENTS.filter((c) => c.showSourceCount);
    expect(withCount.map((c) => c.filename)).toEqual(['QA_Report.md']);
  });
});
