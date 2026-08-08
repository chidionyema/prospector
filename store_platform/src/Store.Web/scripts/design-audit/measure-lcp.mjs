// LCP probe — docs/DESIGN_UX_AUDIT_PROGRAM.md F-005, and the T5 "in a lab" gap.
//
// F-005 reported 2.3-3.8s on four routes but left an explicit HYPOTHESIS open: that the slow
// set is the routes doing client-side data fetching after hydration. It could not be tested
// because the earlier probe read `entry.element` AFTER the fact, by which time React had
// re-rendered the node and the field was null -- so every route reported an LCP element of
// `?`, and a number with no element attached names no fix.
//
// This probe fixes exactly that: the PerformanceObserver is installed via addInitScript,
// BEFORE any page script runs, and it serialises a stable descriptor of the element inside
// the observer callback, synchronously, while the node is still the one the browser measured.
//
// It also throttles, which F-005 says the numbers need before they mean anything (T5). CPU
// 4x and Lighthouse's mobile network shape are applied over CDP. Unthrottled runs are taken
// in the same session for contrast, because "slow" with no baseline is not a finding.
//
//   LCP_BASE=http://localhost:3411 node scripts/design-audit/measure-lcp.mjs
//   LCP_RUNS=5 LCP_BASE=... node scripts/design-audit/measure-lcp.mjs
//
import { chromium } from '@playwright/test';

const BASE = process.env.LCP_BASE ?? 'http://localhost:3000';
const RUNS = Number(process.env.LCP_RUNS ?? 5);

// The bar and the floor, from §1 of the programme doc.
const BAR_MS = 1200;
const FLOOR_MS = 2500;

// Lighthouse mobile throttling. Named constants because a magic 209715 in a perf probe is
// how a lab config silently drifts from the standard it claims to implement.
const LH_MOBILE = {
  cpuSlowdown: 4,
  latencyMs: 150,
  downloadBps: Math.round((1.6 * 1024 * 1024) / 8), // 1.6 Mbps
  uploadBps: Math.round((750 * 1024) / 8), // 750 Kbps
};

// The four routes F-005 names as consistently over the floor, plus the fast controls it
// measured in the same session. Without the controls a slow lab reads as a slow site.
const SLOW_SET = ['/', '/how-it-works', '/ideas'];
const CONTROLS = ['/pricing', '/about', '/kill-log'];

const OBSERVER = () => {
  window.__lcp = { ms: 0, el: null, url: null, size: 0 };
  const describe = (el) => {
    if (!el) return null;
    const tag = el.tagName ? el.tagName.toLowerCase() : '?';
    const id = el.id ? `#${el.id}` : '';
    const cls =
      typeof el.className === 'string' && el.className
        ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.')
        : '';
    const text = (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    return `${tag}${id}${cls}${text ? ` "${text}"` : ''}`;
  };
  // EVERY candidate, not just the winner. A single final number cannot tell "nothing painted
  // until 1.8s" from "something painted at 0.2s and a bigger thing replaced it at 1.8s", and
  // those two have opposite fixes: the first is a blocked paint, the second is a late-arriving
  // element that should have been reserved or rendered on the server.
  window.__lcpAll = [];
  window.__fcp = null;
  window.__fontsReady = null;
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        // Serialise INSIDE the callback: entry.element is live here and null later.
        const rec = {
          ms: Math.round(entry.startTime),
          el: describe(entry.element),
          url: entry.url || null,
          size: Math.round(entry.size || 0),
        };
        window.__lcpAll.push(rec);
        window.__lcp = rec;
      }
    }).observe({ type: 'largest-contentful-paint', buffered: true });
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.name === 'first-contentful-paint') window.__fcp = Math.round(e.startTime);
      }
    }).observe({ type: 'paint', buffered: true });
    // Webfont swap is the classic cause of a late second LCP candidate for the SAME node.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => { window.__fontsReady = Math.round(performance.now()); });
    }
  } catch {
    window.__lcp = { ms: -1, el: 'PerformanceObserver unavailable', url: null, size: 0 };
  }
};

async function measure(browser, route, { throttle }) {
  // A fresh context per run: a warm HTTP cache turns the second measurement of a route into
  // a measurement of the cache, which is the classic way a perf probe reports a fix it did
  // not make.
  const ctx = await browser.newContext({
    viewport: { width: 360, height: 780 },
    userAgent:
      'Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Mobile Safari/537.36',
  });
  const page = await ctx.newPage();
  await page.addInitScript(OBSERVER);

  const cdp = await ctx.newCDPSession(page);
  if (throttle) {
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: LH_MOBILE.cpuSlowdown });
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false,
      latency: LH_MOBILE.latencyMs,
      downloadThroughput: LH_MOBILE.downloadBps,
      uploadThroughput: LH_MOBILE.uploadBps,
    });
  }

  let bytes = 0;
  let requests = 0;
  let xhrAfterLoad = 0;
  let loadFired = false;
  page.on('response', (res) => {
    requests++;
    const t = res.request().resourceType();
    if (loadFired && (t === 'xhr' || t === 'fetch')) xhrAfterLoad++;
    const len = Number(res.headers()['content-length'] ?? 0);
    if (Number.isFinite(len)) bytes += len;
  });

  try {
    const resp = await page.goto(BASE + route, { waitUntil: 'load', timeout: 90000 });
    loadFired = true;
    const status = resp ? resp.status() : 0;
    // Let post-hydration work land; LCP can move after `load` when a client fetch replaces
    // the node, which is precisely the hypothesis under test.
    await page.waitForTimeout(3000);
    const lcp = await page.evaluate(() => window.__lcp);
    const trace = await page.evaluate(() => ({ all: window.__lcpAll, fcp: window.__fcp, fontsReady: window.__fontsReady }));
    const nav = await page.evaluate(() => {
      const n = performance.getEntriesByType('navigation')[0];
      return n ? { ttfb: Math.round(n.responseStart), domReady: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd) } : null;
    });
    return { ok: status === 200, status, ...lcp, trace, nav, requests, xhrAfterLoad, kb: Math.round(bytes / 1024) };
  } catch (e) {
    return { ok: false, error: e.message.slice(0, 120) };
  } finally {
    await ctx.close();
  }
}

const stats = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return {
    min: s[0],
    med: s[Math.floor(s.length / 2)],
    max: s[s.length - 1],
    spread: s[s.length - 1] - s[0],
    ratio: (s[s.length - 1] / s[0]).toFixed(2),
  };
};

const browser = await chromium.launch();
const results = [];

for (const mode of [{ throttle: false, label: 'unthrottled' }, { throttle: true, label: 'LH-mobile' }]) {
  for (const route of [...SLOW_SET, ...CONTROLS]) {
    const samples = [];
    let last = null;
    for (let i = 0; i < RUNS; i++) {
      const r = await measure(browser, route, mode);
      if (!r.ok) {
        // An unreachable route is the END of the measurement, not a slow datum.
        results.push({ mode: mode.label, route, error: r.error ?? `HTTP ${r.status}` });
        samples.length = 0;
        break;
      }
      samples.push(r.ms);
      last = r;
    }
    if (samples.length) {
      results.push({ mode: mode.label, route, ...stats(samples), samples, el: last.el, url: last.url, trace: last.trace, nav: last.nav, requests: last.requests, xhrAfterLoad: last.xhrAfterLoad, kb: last.kb });
    }
  }
}

await browser.close();

console.log(`\nLCP PROBE — ${BASE}  (${RUNS} runs/route, fresh context each, 360x780)`);
console.log(`bar ${BAR_MS}ms · floor ${FLOOR_MS}ms · throttled = CPU ${LH_MOBILE.cpuSlowdown}x, ${LH_MOBILE.latencyMs}ms RTT, 1.6Mbps down\n`);

for (const mode of ['unthrottled', 'LH-mobile']) {
  console.log(`  == ${mode} ==`);
  // TTFB is printed beside LCP because without it this table cannot tell "the page paints
  // slowly" from "the server took a second to answer". `/` is getServerSideProps calling the
  // PRODUCTION API across the internet from whatever machine runs this probe, so a local run
  // can attribute the round trip to the page. LCP minus TTFB is the part the front end owns.
  console.log(`  ${'route'.padEnd(16)} ${'ttfb'.padStart(6)} ${'lcp-min'.padStart(7)} ${'med'.padStart(6)} ${'max'.padStart(6)}  ${'render'.padStart(6)}  ${'xhr>load'.padStart(8)}  LCP element`);
  for (const r of results.filter((x) => x.mode === mode)) {
    if (r.error) {
      console.log(`  ${r.route.padEnd(16)} ERROR ${r.error}`);
      continue;
    }
    const flag = r.med > FLOOR_MS ? ' OVER-FLOOR' : r.med > BAR_MS ? ' over-bar' : '';
    const ttfb = r.nav?.ttfb ?? 0;
    console.log(
      `  ${r.route.padEnd(16)} ${String(ttfb).padStart(6)} ${String(r.min).padStart(7)} ${String(r.med).padStart(6)} ${String(r.max).padStart(6)}  ${String(r.med - ttfb).padStart(6)}  ${String(r.xhrAfterLoad).padStart(8)}  ${r.el ?? '?'}${flag}`,
    );
  }
  console.log('');
}

// The hypothesis, tested rather than restated: is the slow set the set doing post-load fetches?
const th = results.filter((r) => r.mode === 'LH-mobile' && !r.error);
const slow = th.filter((r) => r.med > FLOOR_MS);
const fast = th.filter((r) => r.med <= FLOOR_MS);
const xhrSlow = slow.filter((r) => r.xhrAfterLoad > 0).length;
const xhrFast = fast.filter((r) => r.xhrAfterLoad > 0).length;
console.log('F-005 HYPOTHESIS — "the slow set is the routes doing client-side data fetching after hydration"');
console.log(`  over-floor routes with a post-load xhr/fetch: ${xhrSlow}/${slow.length}`);
console.log(`  under-floor routes with a post-load xhr/fetch: ${xhrFast}/${fast.length}`);
if (!slow.length) console.log('  -> no route is over the floor in this run; the hypothesis is untestable here, NOT refuted.');
else if (xhrSlow === slow.length && xhrFast === 0) console.log('  -> CONSISTENT with the hypothesis (not proof: confounded with page weight).');
else console.log('  -> NOT explained by post-load fetching alone. The LCP element column names the real cost.');

// The candidate trace. This is the line that distinguishes a blocked first paint from a late
// replacement, so it is printed for every route rather than only the failing ones.
console.log('\nLCP CANDIDATE TRACE (unthrottled, last run of each route) — fcp / fontsReady / every candidate:\n');
for (const r of results.filter((x) => x.mode === 'unthrottled' && !x.error)) {
  const t = r.trace ?? {};
  console.log(`  ${r.route}  fcp=${t.fcp ?? '?'}ms  fontsReady=${t.fontsReady ?? '?'}ms`);
  for (const c of t.all ?? []) console.log(`      @${String(c.ms).padStart(5)}ms  size=${String(c.size).padStart(7)}  ${c.el ?? c.url ?? '?'}`);
}

const overFloor = th.filter((r) => r.med > FLOOR_MS).length;
console.log(`\nRESULT: ${overFloor} route(s) over the ${FLOOR_MS}ms floor under LH-mobile throttling.`);
process.exit(results.some((r) => r.error) ? 1 : 0);
