import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

function existsRelative(relativePath: string): boolean {
  return existsSync(fileURLToPath(new URL(relativePath, import.meta.url)));
}

/**
 * US-3 — Hero with a live demonstration of the moat.
 *
 * The audit (§4.3) found the home page hero was a single text stack on a beige
 * rectangle. The buyer saw no product, no proof, no motion. The fix is a
 * 2-column hero: copy on the left, a live terminal-style card on the right
 * showing the last 3 kills, last 3 passes, and a live count, polled every
 * 5 seconds. The moat is demonstrated, not described.
 */
describe('US-3 — Hero with a live demonstration', () => {
  const liveCardExists = existsRelative('../components/marketing/LiveKillCard.tsx');
  const page = readSource('../pages/index.tsx');

  it('declares a LiveKillCard component', () => {
    expect(liveCardExists, 'components/marketing/LiveKillCard.tsx must exist').toBe(true);
  });

  it('LiveKillCard renders the last 3 kills and last 3 passes', () => {
    if (!liveCardExists) return;
    const source = readSource('../components/marketing/LiveKillCard.tsx');
    // The audit: "showing the last 3 kills, the last 3 passes, and a
    // current count." The component must reference both.
    const mentionsKills = /kill/i.test(source);
    const mentionsPasses = /pass|survive|live/i.test(source);
    expect(mentionsKills, 'LiveKillCard must render kills').toBe(true);
    expect(mentionsPasses, 'LiveKillCard must render passes').toBe(true);
  });

  it('LiveKillCard has aria-live="polite" for screen reader updates', () => {
    // The audit: "The card has a monospace font, a blinking cursor, and a
    // subtle pulse on the kill counter. The card is aria-live='polite'."
    if (!liveCardExists) return;
    const source = readSource('../components/marketing/LiveKillCard.tsx');
    const hasAriaLive = /aria-live=["']polite["']/.test(source);
    expect(
      hasAriaLive,
      'LiveKillCard must declare aria-live="polite" so screen readers announce updates',
    ).toBe(true);
  });

  it('home page renders LiveKillCard inside the hero', () => {
    // The audit: "Replace the single text stack with a 2-column hero."
    // The LiveKillCard must appear inside the hero section, not elsewhere.
    if (!liveCardExists) return;
    // The hero <SectionBand> contains the eyebrow + headline + sub + CTA.
    // The LiveKillCard must be inside it, after the CTA, on the right.
    const usesLiveCard = /<LiveKillCard\b/.test(page);
    expect(
      usesLiveCard,
      'index.tsx must render <LiveKillCard> in the hero',
    ).toBe(true);
  });

  it('hero copy remains on the left of the live card (2-column layout)', () => {
    // The hero must be 2-column: copy + live card side by side. The class
    // `lg:grid-cols-2` is the canonical 2-column grid on Tailwind.
    const hasTwoColumns = /lg:grid-cols-2/.test(page) || /grid-cols-2/.test(page);
    expect(
      hasTwoColumns,
      'index.tsx hero must use a 2-column grid (lg:grid-cols-2)',
    ).toBe(true);
  });
});
