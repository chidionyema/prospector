/**
 * `centralLog.ts` exists twice and must stay one file.
 *
 * The storefront and the ops console are separate Next builds with separate `package.json`
 * files and no workspace between them, so neither can import the other's `src/`. The copy is
 * the smallest thing that works; the risk it carries is that a fix -- most dangerously a
 * redaction fix -- lands in one app and not the other, which nobody would notice until a token
 * turned up in a log file.
 *
 * This test exists in BOTH apps' suites, not one. `.github/workflows/ci.yml` decides its lanes
 * from the changed paths: `wb` matches `^store_platform/src/Store\.Web/` and `cn` matches
 * `^store_platform/src/Ops\.Console/`. A single copy of this test, in either lane, would be
 * skipped by a pull request that edited only the other app -- which is exactly the change that
 * causes drift.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const HERE = fileURLToPath(new URL('../src/lib/centralLog.ts', import.meta.url));
const THERE = fileURLToPath(
  new URL('../../Store.Web/src/lib/centralLog.ts', import.meta.url),
);

describe('the two copies of centralLog.ts', () => {
  it('are byte for byte identical', () => {
    const here = readFileSync(HERE, 'utf8');
    const there = readFileSync(THERE, 'utf8');
    expect(there, `${THERE} has drifted from ${HERE}; copy one over the other`).toBe(here);
  });

  it('are both real files, so a rename cannot make this test vacuously pass', () => {
    // A guard that reads an empty or missing file and compares two empties passes while
    // guarding nothing.
    for (const path of [HERE, THERE]) {
      expect(readFileSync(path, 'utf8').length, `${path} is empty`).toBeGreaterThan(2000);
    }
  });
});
