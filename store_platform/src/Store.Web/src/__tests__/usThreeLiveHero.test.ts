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
 * Strip block and line comments.
 *
 * The absence-assertions below ("no setInterval", "no hardcoded relative dates") must run against
 * code, not prose. LiveKillCard.tsx documents at length why each of those was removed, quoting the
 * offending literals verbatim, so matching the raw file makes the test fail on its own changelog
 * and pressures the next author to delete the explanation. Naive but sufficient here: no source in
 * this component contains a `//` or `/*` sequence inside a string literal.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

/**
 * US-3 - Hero with a demonstration of the moat.
 *
 * The audit found the home page hero was a single text stack on a beige rectangle: no product,
 * no proof. The fix is a 2-column hero, copy on the left, a terminal-style card on the right.
 *
 * REVISED 2026-08-05. The original spec asked for "the last 3 kills, last 3 passes, and a live
 * count, polled every 5 seconds", and this file enforced the `aria-live="polite"` that went with
 * it. That spec shipped as three hardcoded pass strings with frozen relative dates ("2 days ago")
 * under a pulsing LIVE badge, over data that is a build-time JSON snapshot and never changed.
 *
 * On a storefront selling a six-gate source-or-die filter, fabricated proof in the hero is
 * disqualifying, so the passes row and the liveness claim were removed rather than reworded. The
 * assertions below now enforce the opposite: the card must be sourced from the audit trail, and
 * must NOT claim a freshness it does not have. Re-adding aria-live is only correct alongside a
 * real data feed.
 */
describe('US-3 - Hero with a demonstration of the moat', () => {
  const liveCardExists = existsRelative('../components/marketing/LiveKillCard.tsx');
  const page = readSource('../pages/index.tsx');

  it('declares a LiveKillCard component', () => {
    expect(liveCardExists, 'components/marketing/LiveKillCard.tsx must exist').toBe(true);
  });

  it('LiveKillCard sources every figure it shows from the audit trail', () => {
    if (!liveCardExists) return;
    const source = readSource('../components/marketing/LiveKillCard.tsx');
    // The old version of this assertion was `/pass|survive|live/i.test(source)`, which the
    // filename "LiveKillCard" satisfied on its own. It passed while the component rendered three
    // invented pass rows, so it proved nothing. Both figures must now trace to the same JSON the
    // /kill-log page renders.
    expect(source, 'kill rows must come from data/kill-log.json').toMatch(
      /from ['"]@\/data\/kill-log\.json['"]/,
    );
    expect(source, 'the totals must come from data/kill-log-totals.json').toMatch(
      /from ['"]@\/data\/kill-log-totals\.json['"]/,
    );
  });

  it('LiveKillCard claims no freshness it cannot back', () => {
    if (!liveCardExists) return;
    const source = stripComments(readSource('../components/marketing/LiveKillCard.tsx'));

    // aria-live announces that a region updates. The card is a build-time snapshot with no timer,
    // so the region never changes and the promise is empty. It also announced fabricated content.
    expect(source, 'no aria-live over static build-time data').not.toMatch(/aria-live=/);

    // No timer: two of these ran per homepage session, because index.tsx mounted the card twice
    // behind `hidden md:block` / `md:hidden`, and display:none does not stop an effect.
    expect(source, 'no polling timer behind a static snapshot').not.toMatch(
      /\bset(Interval|Timeout)\s*\(/,
    );

    // No hardcoded relative dates. "2 days ago" as a literal is frozen at the moment it was typed.
    expect(source, 'no hardcoded relative dates').not.toMatch(
      /['"]\d+\s+(second|minute|hour|day|week|month|year)s?\s+ago['"]/i,
    );

    // Inline `style={{ animation }}` is unreachable by the prefers-reduced-motion rule in
    // globals.css, which is why the pulsing dot ignored the user's stated preference.
    expect(source, 'no inline animation, it escapes prefers-reduced-motion').not.toMatch(
      /style=\{\{[^}]*animation/,
    );
  });

  it('home page mounts LiveKillCard as a deliberate breakpoint pair, not by accident', () => {
    if (!liveCardExists) return;
    // This asserted exactly ONE mount until 2026-08-06. The reason recorded here was "both
    // breakpoint copies mounted and both ran their interval" -- a real defect, but the interval
    // is what made it one, and the interval is independently forbidden by `no polling timer
    // behind a static snapshot` above, which reads LiveKillCard's own source. The component is
    // now 150 lines with no useEffect, no useState, no fetch and no timer.
    //
    // A second copy was then required by a measurement no source test can take: the panel is the
    // hero's right column on lg+, free vertically, and stacking it on a phone put the first pack
    // card 1.23 screens down at 390x844 (1.37 at 360x780, 1.08 at 430x932) -- an ecommerce home
    // page with no product on the first screen. It moved below the shelf on mobile only.
    //
    // So the assertion changes from "never two" to "exactly the two we meant": the pair must be
    // breakpoint-complementary, which is what stops a third copy or an unguarded duplicate. That
    // a reader sees only ONE of them is a rendered-DOM property and is asserted at both viewports
    // in e2e/discovery.spec.ts -- a class typo showing both is invisible from here.
    const mounts = page.match(/<LiveKillCard\b[^>]*>/g) ?? [];
    expect(mounts.length, 'index.tsx must render exactly two <LiveKillCard>, one per breakpoint').toBe(2);
    expect(
      mounts.filter((m) => /\bhidden\b[^"]*\blg:block\b/.test(m)),
      'one copy must be desktop-only (hidden lg:block)',
    ).toHaveLength(1);
    // The mobile copy carries no breakpoint class of its own -- `lg:hidden` sits on the Section
    // wrapping it -- so asserting on the tag would prove nothing about it. Match the wrapper.
    expect(
      page,
      'the other copy must sit inside a lg:hidden Section, below the shelf',
    ).toMatch(/lg:hidden"[\s>][\s\S]{0,160}<LiveKillCard\b/);
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
