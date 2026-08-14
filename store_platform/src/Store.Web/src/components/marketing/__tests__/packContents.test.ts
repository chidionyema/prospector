import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { PACK_CONTENTS, PACK_EXTRAS } from '../PackContents';

/**
 * The storefront's deliverable list and the engine's bundle manifest are one claim in two deploy
 * units, and they drifted: this list said four documents while `BUNDLE_FILES` had grown to eight,
 * so buyers silently received an executive summary, a first-week checklist and a marketing-assets
 * file that no page ever mentioned. Nobody noticed because the only thing binding them was a
 * prose comment dated to a single afternoon's audit.
 *
 * This test is that binding, mechanised. It reads the tuple out of the Python source, the same
 * technique `lib/__tests__/facets.test.ts` uses against `PackFacets.cs`, so adding a file to the
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

function bonusFilesFromPython(): string[] {
  const source = readFileSync(BRIDGE_PY, 'utf8');
  const block = /^BUNDLE_BONUS_FILES\s*=\s*\(([\s\S]*?)^\)/m.exec(source);
  if (!block) throw new Error(`Could not find the BUNDLE_BONUS_FILES tuple in ${BRIDGE_PY}`);
  return Array.from(block[1].matchAll(/"([^"]+)"/g)).map((m) => m[1]);
}

const COMPONENT_TSX = fileURLToPath(new URL('../PackContents.tsx', import.meta.url));

/**
 * The component with its comments removed — i.e. roughly what a buyer ends up reading.
 *
 * The comments are where the reasoning lives and they legitimately use the word "files" to explain
 * why the copy must not. Matching against raw source would make the guard below fail on its own
 * explanation.
 */
function copySource(): string {
  return readFileSync(COMPONENT_TSX, 'utf8')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '');
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
    }
  });

  it('does not advertise a bonus file as one of the deliverables', () => {
    // `BUNDLE_BONUS_FILES` ships in the zip but is not promised, so a missing one cannot block a
    // listing. Listing one in PACK_CONTENTS would reverse that: it would become a promise, and
    // `audit_bundle` — which only iterates BUNDLE_FILES — would not enforce it. They are shown to
    // buyers via PACK_EXTRAS instead, which is a description of the archive, not a contract.
    const bonus = bonusFilesFromPython();
    expect(bonus.length, 'guards the regex: an empty tuple makes this vacuous').toBeGreaterThan(0);
    expect(PACK_CONTENTS.map((c) => c.filename).filter((f) => bonus.includes(f))).toEqual([]);
  });

  it('shows every bonus file the bundle carries, and invents none', () => {
    // The other half of the same drift, and the one that actually bit: the bundle grew a typeset
    // PDF, a printable first-fortnight sheet, an assumptions CSV and an evidence document (commit
    // 40212a3) while the shelf went on describing eight Markdown files. Buyers were shipped the
    // one answer to "markdown files is not the one" and never told it was there.
    //
    // Compared as a SET, not in order: BUNDLE_BONUS_FILES is ordered by when each renderer landed,
    // and the page orders by what a buyer cares about first (the PDF), which is a legitimate
    // difference. Membership is the claim that must not drift.
    expect([...PACK_EXTRAS.map((c) => c.filename)].sort()).toEqual([...bonusFilesFromPython()].sort());
  });

  it('gives every extra a title and a description', () => {
    for (const item of PACK_EXTRAS) {
      expect(item.title.trim(), `title for ${item.filename}`).not.toBe('');
      expect(item.desc.trim().length, `description for ${item.filename}`).toBeGreaterThan(40);
    }
  });

  it('attaches the per-pack source count to the QA report and nothing else', () => {
    // The count is that pack's real cited-source total. Hanging it off any other file would
    // attribute the receipts to a document that does not carry them.
    const withCount = PACK_CONTENTS.filter((c) => c.showSourceCount);
    expect(withCount.map((c) => c.filename)).toEqual(['QA_Report.md']);
  });
});

/**
 * The count beside the list is a claim about DELIVERABLES, never about the archive.
 *
 * It read "8 files" and "8 plain-text files in a zip" for months while the zip held nine or ten
 * entries — bridge.py also writes index.html and manifest.jsonld, both deliberately outside
 * BUNDLE_FILES so they cannot trip the drift test above. The list was right; the noun was not.
 *
 * The Python half of this guard is `undeclared_bundle_entries` + `BUNDLE_BONUS_FILES`
 * (tests/unit/test_bundle_declared_entries.py), which catches a NEW file entering the zip. This
 * half catches the copy going back to counting the archive.
 */
describe('the deliverable count is not a claim about the zip', () => {
  it('has something to match against', () => {
    // Without this the two assertions below pass on an empty string — the vacuous-guard failure
    // mode, which is how a guard reports green while guarding nothing.
    expect(copySource()).toContain('PACK_CONTENTS.length');
  });

  it('never puts the word "files" beside the rendered count', () => {
    const nearCount = Array.from(copySource().matchAll(/PACK_CONTENTS\.length\}([\s\S]{0,80})/g));
    expect(nearCount.length, 'the count must actually be rendered somewhere').toBeGreaterThan(0);
    const offenders = nearCount.map((m) => m[1]).filter((tail) => /\bfiles\b/i.test(tail));
    expect(offenders.map((t) => t.replace(/\s+/g, ' ').trim())).toEqual([]);
  });
});
