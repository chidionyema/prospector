import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { CHECK_NAMES, cleanProofPoint } from '../proof';

/**
 * Two things are being held here.
 *
 * The vocabulary, against the engine that emits it, the same discipline `facets.test.ts`
 * applies to the C#. If someone adds a seventh check in Python, this fails rather than letting
 * its name quietly ship to a buyer as the opening word of our evidence.
 *
 * And the cleaner's restraint. Most of these cases are about what it must NOT remove, because
 * over-stripping is the dangerous direction: it silently deletes the attribution a buyer would
 * need in order to check us, and it looks fine on screen while doing it.
 */
const DOSSIER_PY = fileURLToPath(
  new URL('../../../../../../prospector/dossier.py', import.meta.url),
);

describe('CHECK_NAMES mirrors the engine', () => {
  it('matches _CHECK_LABEL in prospector/dossier.py, key for key', () => {
    const source = readFileSync(DOSSIER_PY, 'utf8');
    const block = /_CHECK_LABEL = \{([\s\S]*?)\n\}/.exec(source);
    expect(block, 'could not find _CHECK_LABEL in dossier.py').not.toBeNull();
    const keys = [...block![1].matchAll(/"([a-z_]+)":/g)].map((m) => m[1]);
    expect(keys.length).toBeGreaterThan(0);
    expect([...CHECK_NAMES].sort()).toEqual([...keys].sort());
  });
});

describe('cleanProofPoint, strips our markup, never the buyer’s evidence', () => {
  it('removes a leading check name that leaked out of a rationale bullet', () => {
    // The exact shape measured on 20 of 51 live packs on 2026-08-01.
    expect(
      cleanProofPoint('value durability: Passages show direct-payment recipients still face duties.'),
    ).toBe('Passages show direct-payment recipients still face duties.');
  });

  it('removes the underscore spelling too', () => {
    expect(cleanProofPoint('payer_solvency: Councils hold ring-fenced budgets.')).toBe(
      'Councils hold ring-fenced budgets.',
    );
  });

  it('keeps an attribution that merely looks like a label', () => {
    // The failure this prevents: a naive /^[a-z ]+:\s/ eats "Ofgem:" and the sentence stops
    // being checkable, which is the entire value of printing it.
    expect(cleanProofPoint('Ofgem: the price cap fell to £1,690 in April 2024.')).toBe(
      'Ofgem: the price cap fell to £1,690 in April 2024.',
    );
    expect(cleanProofPoint('California Courts self-help: estates under $184,500 qualify.')).toBe(
      'California Courts self-help: estates under $184,500 qualify.',
    );
  });

  it('strips the bullet and the bold that a rationale line arrives with', () => {
    // Measured on 8 of 51 live packs: raw ** survived a publish path that never ran the
    // Python converter, so the boundary has to handle it rather than assume upstream did.
    expect(cleanProofPoint('- **buyer intent:** Listings already sell trunk organizers.')).toBe(
      'Listings already sell trunk organizers.',
    );
    expect(cleanProofPoint('Growers **already pay** for this.')).toBe('Growers already pay for this.');
  });

  it('keeps link text and drops only the target', () => {
    expect(cleanProofPoint('See [the 2024 filing](https://example.com/x) for the figure.')).toBe(
      'See the 2024 filing for the figure.',
    );
  });

  it('folds whitespace so a multi-line bullet renders as one line', () => {
    expect(cleanProofPoint('Councils hold\n  ring-fenced   budgets.')).toBe(
      'Councils hold ring-fenced budgets.',
    );
  });

  it('returns null rather than an empty string for nothing usable', () => {
    // A card must not be able to render an empty proof row by forgetting a truthiness check:
    // a row that looks like a citation and cites nothing is worse than no row.
    expect(cleanProofPoint(undefined)).toBeNull();
    expect(cleanProofPoint(null)).toBeNull();
    expect(cleanProofPoint('   ')).toBeNull();
    expect(cleanProofPoint('value durability:')).toBeNull();
  });

  it('never invents, reorders or truncates the words it keeps', () => {
    const sentence =
      'California Department of Education reports the average public school teacher salary was $103,552 in 2024 to 25.';
    expect(cleanProofPoint(sentence)).toBe(sentence);
    expect(cleanProofPoint(`incumbency: ${sentence}`)).toBe(sentence);
  });
});
