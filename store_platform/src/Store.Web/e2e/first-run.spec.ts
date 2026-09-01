/**
 * THE FIRST-RUN GATE. What a stranger meets, in the order they meet it.
 *
 * WHY THIS FILE EXISTS. On 2026-08-21 the founder opened the site as a first-time visitor and
 * said: "first tine user just gets hit with kill log no contexxt no idea wtf is going on",
 * "NOno brand acquainyance", "just a static headline about kill log".
 *
 * He was right, and it was not one page. Measured the same day against live mumchimp.com, all
 * twelve marketing routes opened with the identical line, ABOVE the logo:
 *
 *     Killed 7 Aug · Sound Check Rounds, the monthly noise test that keeps a small music
 *     venue's licence safe · Read the verdict
 *
 * The first sentence a stranger read on this shop was a dated rejection of a business they had
 * never heard of. The brand appeared second.
 *
 * WHAT LET IT SHIP. `TodayRibbon` was added on 2026-08-18 for PIXEL PARITY: the drawings put a
 * dark strip above the header on all eleven pages, the app had none, so every built page
 * rendered 44px higher than its drawing and missed on 5.96% of pixels. That defect was real and
 * the fix was correct. But the drawings document TWO variants of the strip
 * (`docs/design/mumchimp-build-bundle/components.html:541` — "Ribbon — a kill" and
 * "Ribbon — a survivor"), and only the kill one was built. Nothing in the estate graded which
 * variant leads, because nothing in the estate graded MEANING IN READING ORDER at all:
 *
 *   - `scripts/component_parity.mjs` compares tag names and classes. A kill and a survivor
 *     ribbon are the same DOM.
 *   - `scripts/visual_regression.mjs` compares pixels against a drawing that also shows a kill.
 *   - `e2e/fold-budget.spec.ts` measures GEOMETRY on the first screen: is the shelf visible.
 *     It is the closest gate there was, and a page can pass it while its first words are
 *     incomprehensible.
 *
 * So the class is: EVERY GATE GRADED THE SHAPE OF THE FIRST SCREEN AND NONE GRADED WHAT IT SAID.
 * This file is the missing half. It runs in CI's `nextjs` job against a locally built server,
 * before merge, alongside `fold-budget.spec.ts`.
 *
 * WHAT IT DOES NOT DO. It cannot judge whether copy is good. It grades three things a machine
 * can decide and a stranger feels immediately: the brand comes first, the product is named
 * before the jargon, and no page is a dead end.
 */
import { test, expect } from '@playwright/test';

/**
 * Every route a stranger can arrive on from search or a link. Deliberately NOT read from the
 * router: a new page must be added here by hand, which is the moment someone asks what it looks
 * like cold.
 */
const ROUTES = [
  '/',
  '/packs',
  '/ideas',
  '/how-it-works',
  '/faq',
  '/about',
  '/sample',
  '/pricing',
  '/terms',
  '/privacy',
  '/refund',
];

/**
 * House words that mean nothing to someone who arrived thirty seconds ago. They are not banned —
 * they are most of what makes this shop different — they may not be the FIRST thing said.
 * `/kill-log` is exempt from FR2 by being absent from ROUTES: a visitor who clicked "Kill log"
 * has asked for exactly this and is oriented by their own click.
 */
const JARGON = /\b(killed|kill log|verdict|prescreen|dossier|the moat)\b/i;

/**
 * A page is a dead end when nothing inside `<main>` moves the visitor toward a product. Header
 * and footer links do not count: a stranger who has finished reading a page should not have to
 * go back up to the chrome to find out what is for sale.
 */
const FORWARD = 'main a[href^="/pack/"], main a[href="/#catalog"], main a[href^="/ideas"]';

/**
 * FR3 DEBT. Empty, and it stays empty.
 *
 * It held ['/faq', '/about', '/terms', '/privacy', '/refund'] when this gate was written on
 * 2026-08-21 — five routes with zero forward links in `<main>`, waived so the gate could be green
 * on main and refuse any NEW dead end while the queue was worked. All five were fixed the same
 * day: `/faq` and `/about` had a button pointing at `/`, the top of a long marketing page, and the
 * three legal pages shared a closing block pointing at `/faq`. All five now point at `/#catalog`,
 * the shelf itself. Never add a route here to make a build pass; add the link instead.
 */
const FR3_WAIVED = new Set<string>([]);

for (const route of ROUTES) {
  test(`FR1 the brand is the first thing on ${route}`, async ({ page }) => {
    await page.goto(route, { waitUntil: 'domcontentloaded' });

    const header = page.locator('header').first();
    await expect(header, `${route} has no header, so there is no brand to be first`).toBeVisible();
    await expect(header.locator('.wordmark'), 'the header has no wordmark').toBeVisible();
    const brand = await header.boundingBox();
    expect(brand, 'the header rendered with no box').not.toBeNull();

    /* Anything with its own text that renders ABOVE the header is what a stranger reads first.
       Measured against the HEADER's box, not the wordmark's: the nav sits a pixel or two above the
       wordmark's glyph box on some faces, and the nav is part of the brand, not ahead of it.
       `:scope > *` walks top-level bands rather than every nested span, so one band is one
       offender instead of five. The skip link is exempt: off-screen until focused, for keyboards. */
    const bands = page.locator('body >> :is(div, section, aside, a, p) >> visible=true');
    const offenders: string[] = [];
    for (const el of await bands.all()) {
      const box = await el.boundingBox();
      if (!box || box.height === 0 || box.y >= brand!.y) continue;
      const cls = (await el.getAttribute('class')) ?? '';
      if (cls.split(/\s+/).includes('skip')) continue;
      const text = ((await el.textContent()) ?? '').trim().replace(/\s+/g, ' ');
      if (!text) continue;
      /* Keep only the outermost band: a wrapper and its child say the same sentence. */
      if (offenders.some((o) => text.includes(o) || o.includes(text))) continue;
      offenders.push(text.slice(0, 90));
    }
    expect(
      offenders,
      `something is printed above the header on ${route}, so it is the first thing a stranger ` +
        `reads instead of the brand: ${JSON.stringify(offenders.slice(0, 3))}`,
    ).toEqual([]);
  });

  test(`FR2 ${route} names the product before it uses house words`, async ({ page }) => {
    await page.goto(route, { waitUntil: 'domcontentloaded' });

    const h1 = page.locator('h1').first();
    await expect(h1, `${route} has no h1, so it never says what it is`).toBeVisible();
    const heading = await h1.boundingBox();
    expect(heading, 'the h1 rendered with no box').not.toBeNull();

    const jargon = page.locator('body :is(a, p, span, h2, button)').filter({ hasText: JARGON });
    const early: string[] = [];
    for (const el of await jargon.all()) {
      const box = await el.boundingBox();
      if (!box || box.height === 0) continue;
      if (box.y >= heading!.y) continue;
      /* The site header is exempt, and only the site header. A nav label sits in a list of its
         peers -- Categories, How it works, Kill log, FAQ, Account -- and a stranger reads that
         list as navigation, not as a claim about the product. What the founder was hit by was a
         SENTENCE above the brand with nothing around it. Anything outside <header> is graded. */
      if (await el.evaluate((n) => !!n.closest('header'))) continue;
      early.push(((await el.textContent()) ?? '').trim().replace(/\s+/g, ' ').slice(0, 90));
    }
    expect(
      early,
      `${route} uses house words above its own headline, so a stranger reads them with no ` +
        `context: ${JSON.stringify(early.slice(0, 3))}`,
    ).toEqual([]);
  });

  test(`FR3 ${route} is not a dead end`, async ({ page }) => {
    test.skip(FR3_WAIVED.has(route), 'known dead end, tracked in FIRST_RUN_AND_NAVIGATION_PROGRAM');
    await page.goto(route, { waitUntil: 'domcontentloaded' });
    const forward = await page.locator(FORWARD).count();
    /* `/ideas` is the one route whose every forward link is catalogue DATA. The CI `nextjs` job
       builds and serves the site with no API behind it, so the page honestly renders "No
       categories are available right now" and has nowhere to send anyone -- a fact about the
       harness, not about the page. Against live it carries 15 forward links. So skip it, and
       ONLY it, and only after proving this server has no catalogue at all: if `/` serves a
       single pack link, the data is there and the route is graded like every other. */
    if (forward === 0 && route === '/ideas') {
      const home = await (await page.request.get('/')).text();
      test.skip(
        !/href="\/pack\//.test(home),
        'no catalogue behind this server, so /ideas has no data to link to; graded against a ' +
          'seeded build or WEB_BASE_URL=<the live storefront>',
      );
    }
    expect(
      forward,
      `nothing in <main> on ${route} leads to a pack, the catalogue or a category, so a ` +
        `visitor who finishes reading it has nowhere to go`,
    ).toBeGreaterThan(0);
  });
}
