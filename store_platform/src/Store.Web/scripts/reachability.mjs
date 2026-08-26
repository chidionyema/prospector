#!/usr/bin/env node
/**
 * AXIS N1 — ENTRY COVERAGE, AS A COMMAND RATHER THAN A SENTENCE.
 *
 *   node scripts/reachability.mjs                       # against https://mumchimp.com
 *   node scripts/reachability.mjs http://localhost:3000  # against a local build
 *
 * The question it answers: a stranger lands on one of our entry routes. How many of the packs we
 * sell can they reach in one click? In two? The baseline in
 * `docs/FIRST_RUN_AND_NAVIGATION_PROGRAM.md` was crawled by hand on 2026-08-21, which means it
 * could not be re-run, so it could not be a target. This makes it re-runnable.
 *
 * WHAT IT MODELS, AND THE ONE PLACE IT DIFFERS FROM THE FR3 GATE. This follows EVERY same-origin
 * link on the page, header nav included, because a reader really can click the nav. FR3 in
 * `e2e/first-run.spec.ts` deliberately counts only links inside `<main>`, because a nav label is
 * not a forward step in a page's own argument. The two measure different things on purpose: FR3
 * asks "does this page lead anywhere", this asks "can the shelf be got to at all".
 *
 * The pack universe comes from `sitemap.xml`, not from any listing page — otherwise a pack that no
 * listing links would be invisible to the very measurement that exists to find it. That is not
 * hypothetical: on 2026-08-21 exactly 14 of 77 were in that state.
 */
import { parseArgs } from 'node:util';

const { positionals } = parseArgs({ allowPositionals: true });
const BASE = (positionals[0] || 'https://mumchimp.com').replace(/\/$/, '');
const MAX_CLICKS = 2;

/* The routes a stranger can actually arrive on: what we link, what search indexes, what we put in
   an email. Kept in step with ROUTES in `e2e/first-run.spec.ts`, with ONE deliberate exception.

   `/packs` is in ROUTES and is NOT here, and the omission is the point. It is the plain index
   added by FR-10, so as an entry route it would score every pack at one click and lift this
   number by grading the fix with the fix. Left out, the 11 routes below are unchanged from the
   2026-08-21 baseline, the denominator is the same 847 pairs, and the only thing that can move
   the figure is that those eleven OTHER pages now reach the whole shelf through the one footer
   link. That is the thing worth measuring. Adding it here later is legitimate, but it is a new
   baseline, not a better score. */
const ENTRY = [
  '/', '/ideas', '/how-it-works', '/faq', '/about', '/sample',
  '/pricing', '/terms', '/privacy', '/refund', '/kill-log',
];

const cache = new Map();

async function get(path) {
  if (cache.has(path)) return cache.get(path);
  let html = '';
  try {
    const res = await fetch(BASE + path, { redirect: 'follow' });
    if (res.ok) html = await res.text();
  } catch {
    /* An unreachable page contributes no links. It is not an error for this measurement — a route
       that 404s is exactly as useless to a reader as one that leads nowhere, and both should show
       up as zero coverage rather than as a crash. */
  }
  cache.set(path, html);
  return html;
}

/** Every same-origin href on the page, normalised to a path, fragments and queries dropped. */
function links(html) {
  const out = new Set();
  for (const m of html.matchAll(/href="(\/[^"]*)"/g)) {
    const p = m[1].split('#')[0].split('?')[0];
    if (p) out.add(p);
  }
  return out;
}

const isPack = (p) => p.startsWith('/pack/');

async function universe() {
  const xml = await get('/sitemap.xml');
  const packs = new Set();
  for (const m of xml.matchAll(/<loc>[^<]*?(\/pack\/[^<#?]+)<\/loc>/g)) packs.add(m[1]);
  return packs;
}

/** Packs reachable from `start` in at most `MAX_CLICKS`, bucketed by the click that first got there. */
async function crawl(start) {
  const byDepth = [];
  let frontier = new Set([start]);
  const seen = new Set([start]);
  const found = new Set();
  for (let depth = 1; depth <= MAX_CLICKS; depth++) {
    const next = new Set();
    for (const page of frontier) {
      for (const href of links(await get(page))) {
        if (seen.has(href)) continue;
        seen.add(href);
        if (isPack(href)) found.add(href);
        else next.add(href);
      }
    }
    byDepth.push(new Set(found));
    frontier = next;
  }
  return byDepth;
}

const packs = await universe();
if (packs.size === 0) {
  console.error(`no packs in ${BASE}/sitemap.xml — nothing to measure`);
  process.exit(2);
}

const rows = [];
const totals = Array.from({ length: MAX_CLICKS }, () => 0);
for (const route of ENTRY) {
  const byDepth = await crawl(route);
  rows.push([route, ...byDepth.map((s) => s.size)]);
  byDepth.forEach((s, i) => { totals[i] += s.size; });
}

const pairs = ENTRY.length * packs.size;
const pct = (n) => ((n / pairs) * 100).toFixed(1).padStart(5) + '%';

console.log(`\nAXIS N1 — entry coverage   base=${BASE}`);
console.log(`${ENTRY.length} entry routes x ${packs.size} packs = ${pairs} pairs\n`);
console.log('  route                 @1 click  @2 clicks');
for (const [route, ...counts] of rows) {
  console.log(`  ${route.padEnd(20)} ${String(counts[0]).padStart(8)}  ${String(counts[1]).padStart(9)}`);
}
console.log('  ' + '-'.repeat(41));
console.log(`  ${'TOTAL pairs'.padEnd(20)} ${String(totals[0]).padStart(8)}  ${String(totals[1]).padStart(9)}`);
console.log(`  ${'coverage'.padEnd(20)} ${pct(totals[0])}     ${pct(totals[1])}`);

/* The packs no entry route reaches inside the budget at all. This is the number that moves the
   coverage figure most, and it is the one a listing page can hide from itself. */
const reached = new Set();
for (const route of ENTRY) for (const s of await crawl(route)) for (const p of s) reached.add(p);
const orphans = [...packs].filter((p) => !reached.has(p)).sort();
console.log(`\n  packs unreachable in ${MAX_CLICKS} clicks from ANY entry route: ${orphans.length} of ${packs.size}`);
for (const o of orphans.slice(0, 20)) console.log(`    ${o}`);
if (orphans.length > 20) console.log(`    ... and ${orphans.length - 20} more`);
console.log();
