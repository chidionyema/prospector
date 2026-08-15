import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { PACK_CONTENTS, PACK_DOCUMENTS, PACK_EXTRAS } from '../PackContents';

/**
 * The storefront's deliverable list and the engine's bundle manifest are one claim in two deploy
 * units, and they drifted: this list said four documents while `BUNDLE_FILES` had grown to eight,
 * so buyers silently received an executive summary, a first-week checklist and a marketing-assets
 * file that no page ever mentioned. Nobody noticed because the only thing binding them was a
 * prose comment dated to a single afternoon's audit.
 *
 * This test is that binding, mechanised. It reads the tuples out of the Python source, the same
 * technique `lib/__tests__/facets.test.ts` uses against `PackFacets.cs`, so adding a file to the
 * bundle without advertising it, or advertising a file the bundle does not contain, fails here.
 *
 * 2026-08-15: there are now THREE tuples to bind, because bridge.py split the one that was doing
 * two jobs. `PACK_DOCUMENTS` is what a buyer reads, `BUNDLE_FILES` is what the zip must contain,
 * `BUNDLE_BONUS_FILES` is what it also contains without promising. The eight Markdown files stopped
 * being zip entries on that date; a test still asserting they are would be pinning the render input
 * as if it were the product.
 *
 * Deliberately compared in ORDER, not as a set: the lists are rendered to buyers top to bottom.
 */
const BRIDGE_PY = fileURLToPath(new URL('../../../../../../../prospector/bridge.py', import.meta.url));

/** Pulls a top-level tuple of string literals out of bridge.py by name. */
function tupleFromPython(name: string): string[] {
  const source = readFileSync(BRIDGE_PY, 'utf8');
  const block = new RegExp(`^${name}\\s*=\\s*\\(([\\s\\S]*?)^\\)`, 'm').exec(source);
  if (!block) throw new Error(`Could not find the ${name} tuple in ${BRIDGE_PY}`);
  return Array.from(block[1].matchAll(/"([^"]+)"/g)).map((m) => m[1]);
}

const bundleFilesFromPython = () => tupleFromPython('BUNDLE_FILES');
const bonusFilesFromPython = () => tupleFromPython('BUNDLE_BONUS_FILES');
const packDocumentsFromPython = () => tupleFromPython('PACK_DOCUMENTS');

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

describe('the documents a buyer reads agree with prospector/bridge.py', () => {
  it('finds a non-trivial PACK_DOCUMENTS tuple to compare against', () => {
    // Guards the regex itself: a silently-empty match would make every assertion below vacuous.
    expect(packDocumentsFromPython().length).toBeGreaterThan(1);
  });

  it('describes every composed document, in the order the engine composes them', () => {
    // The engine's `BUNDLE_READING_ORDER` is derived, not a literal tuple, so it cannot be read out
    // by regex the way the others can. What IS literal is PACK_DOCUMENTS, and the derivation adds
    // exactly one entry to it — asserted separately below — so pinning against PACK_DOCUMENTS and
    // then pinning the insertion point covers the whole reading order without re-implementing it.
    const fromPython = packDocumentsFromPython();
    const shown = PACK_DOCUMENTS.map((d) => d.section);
    expect(shown.filter((s) => fromPython.includes(s))).toEqual(fromPython);
  });

  it('shows the evidence document where the engine inserts it', () => {
    // `BUNDLE_READING_ORDER` puts `pack_reference.FILENAME` immediately before the QA report, so
    // the receipts land next to the checks that produced them. It is a document, not a file: it is
    // in neither BUNDLE_FILES nor BUNDLE_BONUS_FILES, and listing it as an archive entry — which
    // this page did until 2026-08-15 — advertises something the download does not contain.
    const shown = PACK_DOCUMENTS.map((d) => d.section);
    expect(shown).toContain('Evidence_and_Constraints.md');
    expect(shown.indexOf('Evidence_and_Constraints.md')).toBe(shown.indexOf('QA_Report.md') - 1);
    const archive = [...bundleFilesFromPython(), ...bonusFilesFromPython()];
    expect(archive).not.toContain('Evidence_and_Constraints.md');
  });

  it('never renders a document name to a buyer', () => {
    // The `section` field is a `.md` filename and these stopped shipping on 2026-08-15. Putting one
    // on the page would be the rarest kind of drift: a name true of our source tree and false of
    // the product. The `filename` field on PACK_CONTENTS is rendered on purpose and must stay so
    // -- a real zip entry a buyer can check against their download is falsifiable in a way another
    // adjective is not -- so what is banned is specifically the DOCUMENT name.
    //
    // Asserted as "the JSX never reads the field", not "the string never appears in the file":
    // these are source-level tests, so the data literal and the markup live in the same file and
    // the literal necessarily contains every name. Matching the string would fail on the array
    // that defines it, which is the vacuous-inverse of a guard.
    const rendered = copySource();
    expect(rendered, 'the component must actually map over the documents').toContain(
      'PACK_DOCUMENTS.map',
    );
    // `key={item.section}` is exempt and deliberately so: a React key is a reconciliation
    // identity, never markup, and the section name is the right stable one to use for it.
    expect(rendered).not.toMatch(/(?<!key=)\{\s*(item|doc|d)\.section\s*\}/);
  });

  it('gives every document a title and a description', () => {
    for (const item of PACK_DOCUMENTS) {
      expect(item.title.trim(), `title for ${item.section}`).not.toBe('');
      expect(item.desc.trim().length, `description for ${item.section}`).toBeGreaterThan(40);
    }
  });

  it('attaches the per-pack source count to the QA report and nothing else', () => {
    // The count is that pack's real cited-source total. Hanging it off any other document would
    // attribute the receipts to writing that does not carry them.
    const withCount = PACK_DOCUMENTS.filter((c) => c.showSourceCount);
    expect(withCount.map((c) => c.section)).toEqual(['QA_Report.md']);
  });
});

describe('the files a buyer receives agree with prospector/bridge.py', () => {
  it('finds a non-trivial BUNDLE_FILES tuple to compare against', () => {
    expect(bundleFilesFromPython().length).toBeGreaterThan(1);
  });

  it('advertises exactly the files the bundle contains, in order', () => {
    expect(PACK_CONTENTS.map((c) => c.filename)).toEqual(bundleFilesFromPython());
  });

  it('promises no Markdown file, because the bundle no longer contains one', () => {
    // The founder's objection, mechanised: "i dont like md files at all, we are not selling to
    // developers". Measured across the 59 live packs, the eight `.md` were duplicates — 0 of 853
    // headings, 0 of 208 table cells and 0 of 6,743 prose runs in them were absent from the
    // rendered index.html — so they were render input shipped beside the render output. If one
    // ever comes back into the archive this fails on both sides at once.
    const archive = [...bundleFilesFromPython(), ...bonusFilesFromPython()];
    expect(archive.filter((f) => f.endsWith('.md'))).toEqual([]);
    expect([...PACK_CONTENTS, ...PACK_EXTRAS].map((c) => c.filename).filter((f) => f.endsWith('.md')))
      .toEqual([]);
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
    // one answer to "markdown files is not the one" and never told it was there. Four of those
    // five are contract files now; this guards whatever is left riding along.
    //
    // Compared as a SET, not in order: BUNDLE_BONUS_FILES is ordered by when each renderer landed,
    // and the page orders by what a buyer cares about first, which is a legitimate difference.
    // Membership is the claim that must not drift.
    expect([...PACK_EXTRAS.map((c) => c.filename)].sort()).toEqual([...bonusFilesFromPython()].sort());
  });

  it('gives every extra a title and a description', () => {
    for (const item of PACK_EXTRAS) {
      expect(item.title.trim(), `title for ${item.filename}`).not.toBe('');
      expect(item.desc.trim().length, `description for ${item.filename}`).toBeGreaterThan(40);
    }
  });
});

/**
 * Each rendered count must be beside the thing it counts.
 *
 * The count read "8 files" and "8 plain-text files in a zip" for months while the zip held nine or
 * ten entries, so the guard used to be one-sided: never put "files" beside the count. That was the
 * right rule while there was ONE list and the noun had to carry the discrepancy.
 *
 * Since 2026-08-15 the two numbers are genuinely different — nine documents arrive as five files —
 * so the rule becomes symmetrical, and stricter: the document count may never be called files, and
 * the file count may never be called documents. Either mistake restates the exact false claim
 * ("N files") that this test was written for.
 *
 * The Python half of this guard is `undeclared_bundle_entries` + `BUNDLE_BONUS_FILES`
 * (tests/unit/test_bundle_declared_entries.py), which catches a NEW file entering the zip. This
 * half catches the copy counting the wrong noun.
 */
describe('each rendered count names the right noun', () => {
  it('has something to match against', () => {
    // Without this the assertions below pass on an empty string — the vacuous-guard failure mode,
    // which is how a guard reports green while guarding nothing.
    expect(copySource()).toContain('PACK_DOCUMENTS.length');
    expect(copySource()).toContain('PACK_CONTENTS.length');
  });

  it('never puts the word "files" beside the document count', () => {
    const nearCount = Array.from(copySource().matchAll(/PACK_DOCUMENTS\.length\}([\s\S]{0,80})/g));
    expect(nearCount.length, 'the count must actually be rendered somewhere').toBeGreaterThan(0);
    const offenders = nearCount.map((m) => m[1]).filter((tail) => /\bfiles\b/i.test(tail));
    expect(offenders.map((t) => t.replace(/\s+/g, ' ').trim())).toEqual([]);
  });

  it('never puts the word "documents" beside the file count', () => {
    const nearCount = Array.from(copySource().matchAll(/PACK_CONTENTS\.length\}([\s\S]{0,80})/g));
    expect(nearCount.length, 'the count must actually be rendered somewhere').toBeGreaterThan(0);
    const offenders = nearCount.map((m) => m[1]).filter((tail) => /\bdocuments?\b/i.test(tail));
    expect(offenders.map((t) => t.replace(/\s+/g, ' ').trim())).toEqual([]);
  });
});
