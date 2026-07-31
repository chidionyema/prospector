import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  ADVANTAGE,
  COMMITMENT,
  EFFORT,
  KIND_LABEL,
  MECHANISM,
  PAYER,
  SECTOR,
  VOCABULARY,
  isFacetValue,
  label,
  shortLabel,
  type FacetKind,
} from '../facets';

/**
 * The vocabulary lives in three languages (engine, API, browser) because they are three deploy
 * units. This test is the thing that makes three copies safe rather than three chances to
 * drift: it reads the C# source off disk and compares value for value. Python is held to the
 * same C# source by `tests/unit/test_facets.py`, so C# is the hub and all three agree.
 */
const PACK_FACETS_CS = fileURLToPath(
  new URL('../../../../Store.Catalog/Domain/PackFacets.cs', import.meta.url),
);

function csharpVocabulary(field: string): string[] {
  const source = readFileSync(PACK_FACETS_CS, 'utf8');
  const block = new RegExp(
    `${field}\\s*=\\s*\\r?\\n?\\s*new HashSet<string>\\(StringComparer\\.Ordinal\\)\\s*\\r?\\n?\\s*\\{([^}]*)\\}`,
  ).exec(source);
  if (!block) throw new Error(`Could not find the ${field} HashSet in ${PACK_FACETS_CS}`);
  return Array.from(block[1].matchAll(/"([^"]+)"/g)).map((m) => m[1]);
}

describe('vocabulary agreement with PackFacets.cs', () => {
  const pairs: ReadonlyArray<[string, readonly string[]]> = [
    ['Advantage', ADVANTAGE],
    ['Payer', PAYER],
    ['Effort', EFFORT],
    ['Commitment', COMMITMENT],
    ['Mechanism', MECHANISM],
    ['Sector', SECTOR],
  ];

  it.each(pairs)('%s matches the C# set exactly', (field, ts) => {
    expect([...ts].sort()).toEqual([...csharpVocabulary(field)].sort());
  });

  it('has the sizes the C# tests assert (5/3/3/3/8/12)', () => {
    expect([
      ADVANTAGE.length,
      PAYER.length,
      EFFORT.length,
      COMMITMENT.length,
      MECHANISM.length,
      SECTOR.length,
    ]).toEqual([5, 3, 3, 3, 8, 12]);
  });
});

describe('label', () => {
  const kinds: FacetKind[] = ['advantage', 'payer', 'effort', 'commitment', 'mechanism', 'sector'];

  it.each(kinds)('gives every %s value buyer-facing English', (kind) => {
    for (const value of VOCABULARY[kind]) {
      const text = label(kind, value);
      expect(text, `${kind}/${value} has no label`).toBeTruthy();
      // A label that still contains the machine token is a token, not English.
      expect(text).not.toContain('_');
    }
  });

  it('renders nothing for an absent facet — the null rule at the copy layer', () => {
    expect(label('payer', null)).toBeNull();
    expect(label('payer', undefined)).toBeNull();
    expect(label('payer', '')).toBeNull();
  });

  it('renders nothing for a value outside the vocabulary rather than prettifying it', () => {
    expect(label('sector', 'gardening')).toBeNull();
    expect(shortLabel('sector', 'gardening')).toBeNull();
  });

  it('uses the compact form where one exists and falls back where it does not', () => {
    expect(shortLabel('payer', 'b2c')).toBe('B2C');
    expect(label('payer', 'b2c')).toBe('Sells to consumers');
    expect(shortLabel('effort', 'part_automatable')).toBe(label('effort', 'part_automatable'));
  });

  it('uses the spec Part 10 chip wording', () => {
    expect(label('effort', 'automatable')).toBe('Mostly automated');
    expect(label('effort', 'part_automatable')).toBe('Part automated');
    expect(label('effort', 'hands_on')).toBe('Hands-on service');
    expect(label('commitment', 'evenings')).toBe('Evenings-friendly');
    expect(label('payer', 'b2b')).toBe('Sells to businesses');
  });

  it('names every facet group in the filter bar', () => {
    for (const kind of kinds) expect(KIND_LABEL[kind]).toBeTruthy();
  });
});

describe('isFacetValue', () => {
  it('accepts members and rejects everything else, including absence', () => {
    expect(isFacetValue('mechanism', 'vertical_tool')).toBe(true);
    expect(isFacetValue('mechanism', 'Vertical_Tool')).toBe(false);
    expect(isFacetValue('mechanism', null)).toBe(false);
    expect(isFacetValue('advantage', 'payments')).toBe(false);
  });
});
