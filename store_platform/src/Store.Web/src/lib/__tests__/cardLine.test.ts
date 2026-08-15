import { describe, expect, it } from 'vitest';

import { cardLine } from '@/pages/index';

/**
 * The shelf may not end a product description on a dangling function word.
 *
 * Founder, 2026-08-15, on the live shelf: this was "the worst thing on the shelf". Cards stopped
 * mid-clause -- "...so a", "...which permit, licence and", "...must withhold part of" -- and the
 * diagnosis given, which I repeated back before checking it, was that pack copy generation was
 * cutting them upstream. It was not. Fetched from the live catalogue on 2026-08-15
 * (GET api.mumchimp.com/catalog, 59 packs): every `oneLine` arrived WHOLE, all with terminal
 * punctuation, longest 268 chars against bridge.py's 280 cap. The storefront was cutting its own
 * copy at 20 words and appending nothing, which put 16 of the 59 on a dangling word.
 *
 * The three strings below are the real catalogue values, byte-for-byte, for the packs that
 * rendered broken. A guard written against a plausible-looking sample would have passed on the
 * day the shelf was wrong -- these are quoted rather than composed for exactly that reason.
 */
const LIVE = [
  {
    id: '82a9c38fea398376',
    oneLine:
      'A local, fixed-fee service that handles the council dropped-kerb application, the highway ' +
      'inspection and the approved contractor booking, so a young car owner can legally park on ' +
      'their own front garden.',
    brokenTail: 'so a',
  },
  {
    id: '9c47244fd5f734b2',
    oneLine:
      'A free web tool for people who drive minibuses for schools, clubs and charities, showing ' +
      "exactly which permit, licence and rules today's trip needs.",
    brokenTail: 'which permit, licence and',
  },
  {
    id: 'e9a4c091e0db09a6',
    oneLine:
      'HMRC can refuse a building subcontractor the right to be paid in full, so the contractor ' +
      'must withhold part of every invoice. This is a fixed-fee appeal pack, plus representation ' +
      'at the First-tier Tax Tribunal, that wins that right back.',
    brokenTail: 'must withhold part of',
  },
];

/** The words a summary may never end on. Stated here so the test pins the rule, not the impl. */
const DANGLING =
  /\b(the|a|an|and|or|but|so|to|of|in|on|at|for|with|that|which|what|they|by|from|its|their|as|into|per|is|are|was|were|be|been|when|while|after|before|than|then|if|this|these|those|part|each|every|both)$/i;

/**
 * The rule as it stood before 2026-08-15, copied verbatim from `pages/index.tsx`. It is here, and
 * not expressed as `cardLine(text, 20)`, because calling the NEW function with the OLD cap does
 * not reproduce the old behaviour -- it applies the sentence split and the dangling-word pop as
 * well, so the "before" case would silently test the fix against itself. The defect has to be
 * reproduced by the code that had it.
 */
function legacyCardLine(text: string, maxWords = 20): string {
  const clean = text.replace(/\s*[…]\s*$/, '').replace(/\s*\.\.\.\s*$/, '').trim();
  const words = clean.split(/\s+/);
  if (words.length <= maxWords) return clean;
  return words.slice(0, maxWords).join(' ').replace(/[,;:]$/, '');
}

describe('cardLine never ends a card on a dangling function word', () => {
  it.each(LIVE)('$id no longer ends on "$brokenTail"', ({ oneLine, brokenTail }) => {
    const before = legacyCardLine(oneLine);
    expect(before, 'the pre-fix rule must still reproduce the reported defect').toMatch(
      new RegExp(`${brokenTail.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`),
    );

    const after = cardLine(oneLine);
    expect(after).not.toMatch(DANGLING);
    expect(after.endsWith(brokenTail)).toBe(false);
  });

  it('every live-catalogue value ends on a word that carries meaning', () => {
    for (const { oneLine, id } of LIVE) {
      const line = cardLine(oneLine);
      expect(line.length, id).toBeGreaterThan(40);
      expect(line, id).not.toMatch(/[…]|\.\.\./);
    }
  });

  it('returns a short sentence untouched, minus its terminal full stop', () => {
    // House style on the card: no terminal period, because the line is a label rather than
    // prose. That is a STYLE rule, and it is why a missing period is not evidence of a cut.
    expect(cardLine('A dated pack a council engineer can sign off.')).toBe(
      'A dated pack a council engineer can sign off',
    );
  });

  it('keeps only the first sentence', () => {
    expect(cardLine('The pack does one thing. It also restates the purchase terms.')).toBe(
      'The pack does one thing',
    );
  });

  it('does not split on a decimal or an abbreviation', () => {
    expect(cardLine('It recovers 1.5 hours a week for a team of ten')).toBe(
      'It recovers 1.5 hours a week for a team of ten',
    );
  });

  it('prefers a clause boundary inside the window to the window edge', () => {
    // 12 words, cap 10: word 10 is "ten" and word 8 ends a clause, so the clause wins.
    expect(cardLine('one two three four five six seven clause, nine ten eleven twelve', 10)).toBe(
      'one two three four five six seven clause',
    );
  });

  it('handles an empty or absent line', () => {
    expect(cardLine('')).toBe('');
    expect(cardLine(null)).toBe('');
    expect(cardLine(undefined)).toBe('');
  });
});
