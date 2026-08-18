import { describe, expect, it } from 'vitest';
import { CARD_HEADING_MAX, cardHeading } from '@/lib/discovery';

const base = { id: 'p1', title: 'PitchBrief, A very long descriptive subtitle about gig drivers' };

describe('cardHeading', () => {
  it('leads with the engine card line and demotes the brand name to an eyebrow', () => {
    const { name, heading, eyebrow, sub } = cardHeading({
      ...base,
      cardLine: 'Refund insurance excess for under-27 gig drivers',
    });
    expect(heading).toBe('Refund insurance excess for under-27 gig drivers');
    expect(eyebrow).toBe('PitchBrief');
    expect(sub).toBe('A very long descriptive subtitle about gig drivers');
    // The brand name survives regardless of layout, a basket line must still say "PitchBrief".
    expect(name).toBe('PitchBrief');
  });

  it('keeps the old name-first hierarchy for a pack with no card line', () => {
    // Every pack published before the engine emitted cardLine. This is the regression that
    // matters: the shelf must not become headingless for the existing catalogue.
    const { heading, eyebrow, sub } = cardHeading(base);
    expect(heading).toBe('PitchBrief');
    expect(eyebrow).toBeNull();
    expect(sub).toBe('A very long descriptive subtitle about gig drivers');
  });

  it('refuses an over-length card line instead of truncating it', () => {
    // 61 characters. The front end re-checks rather than trusting the wire, because a pack
    // published by an older engine predates the engine-side enforcement.
    const tooLong = 'x'.repeat(CARD_HEADING_MAX + 1);
    const { heading, eyebrow } = cardHeading({ ...base, cardLine: tooLong });
    expect(heading).toBe('PitchBrief');
    expect(eyebrow).toBeNull();
    // Nothing anywhere on the card is a prefix of the rejected line.
    expect(heading.startsWith('xxx')).toBe(false);
  });

  it('accepts a card line exactly at the limit', () => {
    const exact = 'y'.repeat(CARD_HEADING_MAX);
    expect(cardHeading({ ...base, cardLine: exact }).heading).toBe(exact);
  });

  it('treats an empty or whitespace card line as absent', () => {
    expect(cardHeading({ ...base, cardLine: '' }).heading).toBe('PitchBrief');
    expect(cardHeading({ ...base, cardLine: '   ' }).heading).toBe('PitchBrief');
  });

  it('does not print the same string twice', () => {
    // A card line identical to the brand name must not render as both eyebrow and heading.
    // No `id`: `cardHeading` takes `CardHeadingInput` (title/headline/cardLine) rather than a
    // whole `FacetedPack`, so the plain catalogue `Pack` on /collections cards can use it too.
    const same = cardHeading({ title: 'SailCert', cardLine: 'SailCert' });
    expect(same.heading).toBe('SailCert');
    expect(same.eyebrow).toBeNull();

    // Nor as both heading and sub, when the title descriptor repeats it.
    const dup = cardHeading({
      title: 'SpatWindow, Track oyster spat windows',
      cardLine: 'Track oyster spat windows',
    });
    expect(dup.heading).toBe('Track oyster spat windows');
    expect(dup.sub).toBeNull();
    expect(dup.eyebrow).toBe('SpatWindow');
  });
});
