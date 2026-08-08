// Turns docs/audit/audit-raw.json into a findings report scored against the
// thresholds in docs/DESIGN_UX_AUDIT_PROGRAM.md §1 (T1-T16).
//
// No dependencies, no judgement: it prints numbers and the bar each number is
// measured against. Deciding severity, and what to do about it, stays with a human.
//
//   node scripts/design-audit/report.mjs
//
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../../../../..');
const OUTDIR = path.resolve(process.env.AUDIT_OUT ?? path.join(REPO_ROOT, 'docs/audit'));
const raw = JSON.parse(fs.readFileSync(path.join(OUTDIR, 'audit-raw.json'), 'utf8'));
const rows = (raw.results ?? []).filter((r) => !r.error);

const where = (r) => `${r.id}@${r.viewport}`;
const uniq = (xs) => [...new Set(xs)].sort();
const P = (s = '') => console.log(s);

P(`# Design/UX audit — measured against DESIGN_UX_AUDIT_PROGRAM.md §1`);
P(`base: ${raw.base}   generated: ${raw.generatedAt}   pairs: ${(raw.results ?? []).length}`);

// ---------------------------------------------------------------- T1
P(`\n## T1 Contrast (bar: AAA 7:1 body, 4.5:1 at >=24px)`);
const cRows = rows.filter((r) => r.contrast);
for (const r of cRows) {
  const worst = r.contrast.failures?.[0]?.ratio ?? '-';
  const flag = r.contrast.failureCount > 0 ? ' <<' : '';
  P(
    `  ${where(r).padEnd(22)} checked ${String(r.contrast.checked).padStart(4)}  ` +
      `failures ${String(r.contrast.failureCount).padStart(3)}  worst ${String(worst).padStart(5)}${flag}`,
  );
}
const allC = cRows.flatMap((r) => (r.contrast.failures ?? []).map((f) => ({ ...f, at: where(r) })));
allC.sort((a, b) => a.ratio - b.ratio);
P(`\n  worst 15 individual text nodes sitewide:`);
for (const f of allC.slice(0, 15)) {
  P(
    `   ${String(f.ratio).padStart(5)}:1 (need ${f.required})  ${f.at.padEnd(20)} ` +
      `${f.size}px/${f.weight}  fg ${f.fg} on ${f.bg}  "${f.text}"  ${f.sel}`,
  );
}
if (!allC.length) P(`   none — every text node clears its bar.`);

// ---------------------------------------------------------------- T3
// Two classes of "failure" here are not failures, and reporting them would burn
// the founder's trust in every other number:
//   * sr-only skip links are 1x1 BY DESIGN until focused (verified on /: the
//     "Skip to content" anchor is a.sr-only.focus-visible:not-sr-only).
//   * WCAG 2.5.8 exempts links inline in a sentence — their box is the text.
// They are counted separately, never silently dropped.
const isHidden = (f) => /sr-only/.test(f.sel) || (f.w <= 2 && f.h <= 2);
const isInline = (f) => !isHidden(f) && /(^|>)(p|li|span)[.>]/.test(f.sel) && f.h < 30;
const cls = (f) => (isHidden(f) ? 'hidden' : isInline(f) ? 'inline' : 'real');

P(`\n## T3 Tap targets (bar: 44x44 minimum)`);
P(`  "real" excludes sr-only/hidden-until-focus and WCAG 2.5.8 inline-in-text links.`);
for (const r of rows.filter((r) => r.tapTargets)) {
  const fs = r.tapTargets.failures ?? [];
  const real = fs.filter((f) => cls(f) === 'real').length;
  const inl = fs.filter((f) => cls(f) === 'inline').length;
  const hid = fs.filter((f) => cls(f) === 'hidden').length;
  P(
    `  ${where(r).padEnd(22)} interactive ${String(r.tapTargets.checked).padStart(3)}  ` +
      `under 44px ${String(r.tapTargets.failureCount).padStart(3)}  ` +
      `[real ${String(real).padStart(3)}${real > 0 ? ' <<' : '   '} inline ${String(inl).padStart(3)} hidden ${hid}]`,
  );
}
const allT = rows
  .flatMap((r) => (r.tapTargets?.failures ?? []).map((f) => ({ ...f, at: where(r) })))
  .filter((f) => cls(f) === 'real');
allT.sort((a, b) => a.w * a.h - b.w * b.h);
P(`\n  smallest 15 REAL targets sitewide:`);
for (const f of allT.slice(0, 15)) {
  P(`   ${String(f.w).padStart(4)}x${String(f.h).padEnd(4)} ${f.at.padEnd(20)} "${f.name}"  ${f.sel}`);
}
if (!allT.length) P(`   none — every non-exempt interactive element is at least 44x44.`);

// ---------------------------------------------------------------- T5/T6
P(`\n## T5/T6 LCP & CLS (bar: LCP < 1200ms, CLS 0.00)`);
for (const r of rows.filter((r) => r.perf)) {
  const bad = [];
  if (r.perf.lcp > 1200) bad.push('LCP');
  if (r.perf.cls > 0) bad.push('CLS');
  P(
    `  ${where(r).padEnd(22)} lcp ${String(r.perf.lcp).padStart(5)}ms  cls ${String(r.perf.cls).padEnd(6)}` +
      (bad.length ? ` << ${bad.join('+')}` : ''),
  );
}
const noBox = rows.filter((r) => (r.imagesNoBox?.count ?? 0) > 0);
P(`\n  images with no reserved box (a CLS source): ${noBox.length} page/viewport pairs`);
for (const r of noBox.slice(0, 10)) {
  P(`   ${where(r).padEnd(22)} ${r.imagesNoBox.count}  e.g. ${r.imagesNoBox.items[0]?.src}`);
}

// ---------------------------------------------------------------- T9
P(`\n## T9 Reflow (bar: no horizontal scroll at any width, nothing clipped)`);
const ovf = rows.filter((r) => r.overflow?.overflows);
if (!ovf.length) P(`  clean — no horizontal overflow at any audited width.`);
for (const r of ovf) {
  P(`  ${where(r).padEnd(22)} scrollWidth ${r.overflow.scrollWidth} > viewport ${r.overflow.innerWidth} <<`);
  for (const c of (r.overflow.culprits ?? []).slice(0, 5)) {
    P(`     left ${String(c.left).padStart(6)} right ${String(c.right).padStart(6)}  ${c.sel}`);
  }
}

// ---------------------------------------------------------------- T11
P(`\n## T11 Type scale (bar: <= 6 distinct sizes sitewide, 45-75ch measure)`);
const sizeUnion = uniq(rows.flatMap((r) => r.sizes ?? [])).sort((a, b) => a - b);
P(`  sitewide distinct font-sizes: ${sizeUnion.length}${sizeUnion.length > 6 ? ' <<' : ''}`);
P(`  ${sizeUnion.join('px, ')}px`);
const byRoute = {};
for (const r of rows) (byRoute[r.id] ??= new Set()).add(...(r.sizes ?? []));
for (const r of rows.filter((r) => r.viewport === '1440')) {
  P(`   ${r.id.padEnd(16)} ${(r.sizes ?? []).length} sizes: ${(r.sizes ?? []).join(', ')}`);
}
const styleKeys = uniq(rows.flatMap((r) => Object.keys(r.typeCensus ?? {})));
P(`  distinct size/weight/line-height triples sitewide: ${styleKeys.length}`);

// ---------------------------------------------------------------- T12
P(`\n## T12 Colour (bar: one accent, <=3 neutrals, every value a token)`);
const colU = uniq(rows.flatMap((r) => r.styleCensus?.colors ?? []));
const bgU = uniq(rows.flatMap((r) => r.styleCensus?.backgrounds ?? []));
const bcU = uniq(rows.flatMap((r) => r.styleCensus?.borderColors ?? []));
P(`  distinct text colours:   ${colU.length}`);
P(`   ${colU.join('  ')}`);
P(`  distinct backgrounds:    ${bgU.length}`);
P(`   ${bgU.join('  ')}`);
P(`  distinct border colours: ${bcU.length}`);

// ---------------------------------------------------------------- T13
P(`\n## T13 Consistency (bar: one primitive per job)`);
P(`  distinct border-radius values: ${uniq(rows.flatMap((r) => r.styleCensus?.radii ?? [])).length}`);
P(`   ${uniq(rows.flatMap((r) => r.styleCensus?.radii ?? [])).join('  ')}`);
P(`  distinct box-shadows:          ${uniq(rows.flatMap((r) => r.styleCensus?.shadows ?? [])).length}`);
P(`  distinct grid/flex gaps:       ${uniq(rows.flatMap((r) => r.styleCensus?.gaps ?? [])).length}`);
P(`   ${uniq(rows.flatMap((r) => r.styleCensus?.gaps ?? [])).join('  ')}`);

// ---------------------------------------------------------------- T10
P(`\n## T10 Motion (bar: reduced-motion honoured, <=200ms, one easing curve)`);
const durU = uniq(rows.flatMap((r) => r.styleCensus?.durations ?? []));
const easeU = uniq(rows.flatMap((r) => r.styleCensus?.easings ?? []));
P(`  distinct durations: ${durU.length} — ${durU.join('  ')}`);
P(`  distinct easings:   ${easeU.length}${easeU.length > 1 ? ' <<' : ''} — ${easeU.join('  ')}`);
const rm = rows.filter((r) => r.reducedMotion);
for (const r of rm) {
  const m = r.reducedMotion;
  // Older runs carry the discredited `stillAnimating` shape; say so rather than
  // silently printing a number that meant something else.
  if (m.over200ms === undefined) {
    P(`  ${r.id.padEnd(16)} (legacy metric: counted declared non-zero durations, not violations — re-run)`);
    continue;
  }
  P(
    `  ${r.id.padEnd(16)} @reduce rules:${m.reducedMotionRules}  declared:${m.declaredNonZero}  ` +
      `over 200ms: ${m.over200ms}${m.over200ms > 0 ? ' <<' : ''}`,
  );
}

// ---------------------------------------------------------------- T16
P(`\n## T16 Dark mode (bar: decided explicitly — everywhere or nowhere)`);
const darkRows = rows.filter((r) => r.dark);
const light = new Map(rows.filter((r) => r.viewport === '360').map((r) => [r.id, r.styleCensus?.backgrounds?.[0]]));
const changed = [];
for (const r of darkRows) {
  P(`  ${r.id.padEnd(16)} dark body bg ${r.dark.bg}  fg ${r.dark.fg}`);
}
const darkBgs = uniq(darkRows.map((r) => r.dark.bg));
if (darkBgs.length === 1) {
  P(`  VERDICT: every route reports the same body background under prefers-color-scheme: dark`);
  P(`           (${darkBgs[0]}) — dark mode is not differentiated. Consistent, i.e. "nowhere".`);
} else {
  P(`  VERDICT: HALF-STATE — routes disagree under dark: ${darkBgs.join(' / ')} <<`);
}

// ---------------------------------------------------------------- Axe
P(`\n## Axe (automated a11y floor, never the ceiling)`);
const axeAgg = {};
for (const r of rows.filter((r) => Array.isArray(r.axe))) {
  for (const v of r.axe) {
    const a = (axeAgg[v.id] ??= { impact: v.impact, help: v.help, nodes: 0, at: new Set(), sample: v.sample });
    a.nodes += v.nodes;
    a.at.add(where(r));
  }
}
const axeList = Object.entries(axeAgg).sort((a, b) => b[1].nodes - a[1].nodes);
if (!axeList.length) P(`  no violations reported.`);
for (const [id, a] of axeList) {
  P(`  ${String(a.impact).padEnd(8)} ${id.padEnd(30)} ${String(a.nodes).padStart(4)} nodes  ${a.at.size} pairs`);
  P(`     ${a.help}`);
  P(`     e.g. ${a.sample}`);
}

// ---------------------------------------------------------------- Headings
P(`\n## Headings (structure, and the sceptic's scan path)`);
for (const r of rows.filter((r) => r.viewport === '1440')) {
  const levels = (r.headings ?? []).map((h) => h.level);
  const skips = [];
  for (let i = 1; i < levels.length; i++) {
    if (levels[i] > levels[i - 1] + 1) skips.push(`h${levels[i - 1]}->h${levels[i]}`);
  }
  const bad = r.h1Count !== 1 || skips.length;
  if (bad) {
    P(`  ${r.id.padEnd(16)} h1Count=${r.h1Count}${r.h1Count !== 1 ? ' <<' : ''}  skips: ${skips.join(', ') || 'none'}`);
  }
}

// ---------------------------------------------------------------- Fold
P(`\n## T4 Fold budget — block ledger at 360x780 (the worst-case Android)`);
for (const r of rows.filter((r) => r.viewport === '360' && r.blockLedger?.length)) {
  P(`  ${r.id}  (first screen = 780px)`);
  for (const b of r.blockLedger.slice(0, 8)) {
    P(`    y=${String(b.y).padStart(5)} h=${String(b.h).padStart(5)}  ${b.sel.slice(0, 50).padEnd(52)} "${b.text.slice(0, 34)}"`);
  }
}

// ---------------------------------------------------------------- Errors
P(`\n## Errors and gaps`);
const errs = (raw.results ?? []).filter((r) => r.error);
for (const r of errs) P(`  ${where(r)}  ${r.error}`);
for (const s of raw.skipped ?? []) P(`  SKIPPED ${s}`);
if (!errs.length && !(raw.skipped ?? []).length) P(`  none.`);
