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
    // Accepts `kill-log-names.json` as well as the full `kill-log.json`. Both are written by the
    // same generator from the same dossiers (tools/make_kill_log.py: OUT at :48, OUT_NAMES at :62,
    // both projections of one build() payload), so provenance is identical -- and the full log is
    // ~507KB of un-tree-shakeable static import, which is why drawing three lines of hero text from
    // it was itself the defect. The property here is PROVENANCE; pinning the 507KB filename turned
    // it into a bundle-size regression the moment the split landed.
    expect(source, 'kill rows must come from the generated kill log').toMatch(
      /from ['"]@\/data\/kill-log(-names)?\.json['"]/,
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

  it('home page mounts LiveKillCard exactly once, after the shelf, at every width', () => {
    if (!liveCardExists) return;
    // THE HISTORY, because this assertion has now been three different things and each change
    // was made for a measured reason:
    //
    //  1. "exactly ONE" -- both breakpoint copies mounted and both ran a polling interval. The
    //     interval is what made that a defect, and it is independently forbidden by `no polling
    //     timer behind a static snapshot` above, which reads LiveKillCard's own source.
    //  2. "exactly TWO, breakpoint-complementary" -- the panel was the hero's right column on
    //     lg+, and stacking it on a phone put the first pack card 1.23 screens down at 390x844
    //     (1.37 at 360x780, 1.08 at 430x932). The mobile copy moved below the shelf; the desktop
    //     copy stayed in the hero.
    //  3. "exactly ONE, after the shelf" -- 2026-08-06. Both of those positions were the same
    //     mistake at two widths. A shop's first screen has to show the thing you can buy, and on
    //     desktop the largest and only coloured object above the fold was a ledger of ideas we had
    //     thrown away. With the panel below the shelf at every width, the breakpoint pair has
    //     nothing left to solve: one mount, no `hidden`/`lg:block` split to keep in sync, and one
    //     fewer way for a class typo to render the same panel twice.
    //
    // The panel is NOT deleted. It is the only claim on the page a sceptic can check without
    // leaving it; what changed is that the reader meets it after seeing the products, i.e. once
    // they have a reason to interrogate the shelf rather than before they know what is on it.
    const mounts = page.match(/<LiveKillCard\b[^>]*>/g) ?? [];
    expect(mounts.length, 'index.tsx must render exactly one <LiveKillCard>').toBe(1);
    expect(
      mounts[0],
      'the single mount must not be breakpoint-gated -- it shows at every width now',
    ).not.toMatch(/\bhidden\b|\blg:block\b|\blg:hidden\b/);
    // Position, not just presence: this is the whole point of the change. `<CatalogBrowser>` is
    // the shelf, so the panel's offset in the source must be after it.
    const shelf = page.indexOf('<CatalogBrowser');
    expect(shelf, 'the shelf (<CatalogBrowser>) must exist to position against').toBeGreaterThan(-1);
    expect(
      page.indexOf('<LiveKillCard'),
      'the kill ledger must render AFTER the shelf, never above the first product',
    ).toBeGreaterThan(shelf);
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
