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

  it('the home page states the kill total exactly once, and the panel that duplicated it is gone', () => {
    // THE HISTORY, because this assertion has now been four different things and each change was
    // made for a measured reason:
    //
    //  1. "exactly ONE mount" -- both breakpoint copies mounted and both ran a polling interval.
    //     The interval is what made that a defect, and it is independently forbidden by `no
    //     polling timer behind a static snapshot` above, which reads LiveKillCard's own source.
    //  2. "exactly TWO, breakpoint-complementary" -- the panel was the hero's right column on
    //     lg+, and stacking it on a phone put the first pack card 1.23 screens down at 390x844.
    //  3. "exactly ONE, after the shelf" -- 2026-08-06. A shop's first screen has to show the
    //     thing you can buy, so the ledger moved below the products at every width.
    //  4. NO MOUNT AT ALL -- founder, 2026-08-14. The panel was removed from this page as a
    //     DUPLICATE, not as a mistake: the strip at index.tsx:2066-2081 already prints the same
    //     kill total in the page's own voice with the /kill-log link beside it, so the panel
    //     restated a number the reader had just been given, in a larger box, further down.
    //
    // So the guarantee this test defends is no longer "where does the panel sit" -- it is that
    // THE PAGE STATES ITS KILL TOTAL ONCE. A count printed twice is the failure mode this file
    // has been circling since 2026-08-05 (two mounts, two intervals, two ledgers); scoping the
    // assertion to the figure rather than to one component is what makes it survive the panel's
    // deletion. The component itself is NOT deleted -- the three assertions above still hold it
    // to its provenance and its freshness claims, so it can be re-mounted anywhere without first
    // re-earning them. /kill-log is where the full ledger lives now.
    const source = stripComments(page);

    expect(
      source.match(/<LiveKillCard\b/g) ?? [],
      'the kill ledger panel is removed from this page; /kill-log carries it',
    ).toHaveLength(0);
    expect(source, 'and its import goes with it, or the bundle still pays for it').not.toMatch(
      /import\s+[^;]*LiveKillCard/,
    );

    // The figure itself, stated once. `RESEARCH_STATS.killed` is the only route to it -- the
    // survivor count is not exported at all (lib/stats.ts) precisely so no page can reprint it.
    expect(
      source.match(/RESEARCH_STATS\.killed/g) ?? [],
      'index.tsx must state the kill total exactly once',
    ).toHaveLength(1);

    // SCOPE, stated so the next reader does not "fix" a failure this test cannot see. This
    // assertion owns index.tsx's own body and nothing else. Two components mounted by this page
    // also reach the same total, and both are deliberate: `MarketingLayout.tsx:472`, the
    // site-wide footer ledger that renders on every route, and `KillGrid`, which names it inside
    // the SVG `<desc>` because the field is a graphic and a screen reader needs the figure it
    // depicts. `TrustGuaranteesRow` printed a third ("N ideas were killed to list
    // these M") until the founder cut it on 2026-08-14. Counting renders across components would
    // make this test fail on another component's copy decision, which is how a guard test starts
    // being deleted rather than read.
    const shelf = source.indexOf('<CatalogBrowser');
    expect(shelf, 'the shelf (<CatalogBrowser>) must still be on the page').toBeGreaterThan(-1);
  });

  it('the kill total on the home page is read, never typed in', () => {
    // The panel's removal must not turn a derived figure into a literal. A hardcoded "1,364"
    // freezes at the moment it is typed and then contradicts /kill-log the next time
    // `tools/make_kill_log.py` runs -- the exact class of drift lib/stats.ts exists to end
    // (two pages disagreed about the same JSON on 2026-08-06; see its docblock).
    const source = stripComments(page);

    expect(source, 'no typed-in thousands figure anywhere in the page body').not.toMatch(
      /\b\d{1,3},\d{3}\b/,
    );
    expect(source, 'the page must not import the kill log JSON and re-derive its own totals').not.toMatch(
      /from ['"]@\/data\/kill-log[^'"]*['"]/,
    );
    expect(source, 'the totals must come from the shared derivation').toMatch(
      /from ['"]@\/lib\/stats['"]/,
    );
    // The receipt stays one click away: the strip that states the total carries the link.
    expect(source, 'the kill log must remain reachable from the home page').toMatch(
      /href="\/kill-log"/,
    );
  });

  it('hero copy remains on the left of the live card (2-column layout)', () => {
    // The hero must be 2-column: copy + live card side by side. The class
    // `lg:grid-cols-2` is the canonical 2-column grid on Tailwind.
    // MEASURED AGAINST THE HERO, not against any two-column grid on the page (2026-08-15). The
    // old regex was `/lg:grid-cols-2/`, which the hero has never carried -- it was matching the
    // SHELF's deleted `mid` band, so this assertion passed for four months on an element three
    // screens below the one it names. The hero's grid is `lg:grid-cols-[1fr_420px]`: copy left,
    // live card right, at a fixed card width.
    // Width-agnostic on purpose. The claim on this line is that the hero is two columns at
    // `lg`, not that the right one is 420px. That measure is a design number and it moved to
    // the drawing's 380px on 2026-08-18; pinning the digits here made a layout change read as
    // a structural regression in a test about the hero's shape.
    const hasTwoColumns = /lg:grid-cols-\[1fr_\d+px\]/.test(page);
    expect(
      hasTwoColumns,
      'index.tsx hero must use a 2-column grid (lg:grid-cols-2)',
    ).toBe(true);
  });
});
