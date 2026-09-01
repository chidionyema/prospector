/**
 * LIGHTHOUSE CI — the budget for what a buyer's browser has to do.
 *
 * This runs against a RUNNING site (LHCI_URL, defaulting to the live storefront) rather than a
 * build artefact, because every number it produces is about delivery: what was sent, how big it
 * was, when the largest thing on screen finished painting. A build cannot answer that.
 *
 * THE ASSERTIONS ARE MEASURED, NOT ASPIRATIONAL. Each threshold below was set from a real run
 * against the live site and sits at or just under what the site already does, so the first red is
 * a regression rather than a wish. Raising a number to make CI green is the failure mode this
 * comment exists to make visible: move the site, not the budget.
 *
 * Run: npm run test:lighthouse            (live)
 *      LHCI_URL=http://localhost:3000 npm run test:lighthouse
 */
// The live storefront's origin. The estate zone is declared once (the platform's
// clusters/<cluster>/estate-config.yaml; ESTATE_ZONE in the environment here) and never
// spelled in this repo (crew#796); a missing zone stops the run rather than aiming it elsewhere.
function liveSite() {
  const zone = process.env.ESTATE_ZONE;
  if (!zone) throw new Error('ESTATE_ZONE is not set; it is the one place the estate zone lives');
  return `https://${zone}`;
}
const base = process.env.LHCI_URL || liveSite();

module.exports = {
  ci: {
    collect: {
      url: [base, `${base}/ideas`, `${base}/kill-log`],
      // Three runs, median reported. One run on a shared CI box measures the box.
      numberOfRuns: 3,
      settings: {
        // Mobile is the default preset and the harder case; the design brief is mobile-first.
        preset: 'perf',
        onlyCategories: ['performance', 'accessibility', 'best-practices', 'seo'],
        chromeFlags: '--no-sandbox --headless=new',
      },
    },
    assert: {
      /*
       * MEASURED 2026-08-19 against https://mumchimp.com, three runs per URL, medians:
       *
       *   URL         perf   a11y   best-pr   seo    LCP ms   CLS   TBT ms
       *   /           0.46   0.90   0.96      1.00   4226     0     4210
       *   /ideas      0.62   0.92   0.96      1.00   3220     0     2353
       *   /kill-log   0.63   0.96   0.96      1.00   3357     0     1039
       *
       * Every threshold below sits at or just past the WORST of those three, so the first red is
       * a regression rather than a wish. The performance numbers are bad and these budgets do not
       * pretend otherwise: a budget's job is to stop the site getting worse. Making it faster is
       * separate work, and when it lands these numbers come down with it. Raising a number to
       * clear a red is the failure this file exists to make visible.
       */
      assertions: {
        // Scores. Accessibility, SEO and best-practices are things the code controls end to end,
        // so they gate. 0.88/0.98/0.95 each leave one step of slack under the measured floor,
        // because a single audit flipping is noise and two is a regression.
        'categories:accessibility': ['error', { minScore: 0.88 }],
        'categories:seo': ['error', { minScore: 0.98 }],
        'categories:best-practices': ['error', { minScore: 0.95 }],
        // Performance moves with the network the runner happens to have, so it warns rather than
        // gates. 0.45 is just under the worst measured median (0.46 on the home page).
        'categories:performance': ['warn', { minScore: 0.45 }],
        // LCP and TBT are what the home page's JavaScript costs a buyer. Both warn: they are the
        // two numbers most sensitive to a shared CI box.
        'largest-contentful-paint': ['warn', { maxNumericValue: 4500 }],
        'total-blocking-time': ['warn', { maxNumericValue: 4500 }],
        // CLS is the one that gates, and it gates HARD at a twentieth of the industry bar,
        // because the site measured a clean 0.00 on all three pages. Layout shift is not a
        // network artefact -- it is an image without dimensions or a font swap, both of which are
        // in the diff that causes them. 0.1 would let the whole defect in before saying anything.
        'cumulative-layout-shift': ['error', { maxNumericValue: 0.05 }],
      },
    },
    upload: {
      // No server to upload to, and none is wanted: the reports are CI artefacts, kept with the
      // run that produced them.
      target: 'filesystem',
      outputDir: './.lighthouseci',
    },
  },
};
