import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DiscoveryWaitlist } from '@/components/discovery/EmptyState';
import { WaitlistCallout } from '../WaitlistCallout';
import { WAITLIST_CONSENT_TEXT, WAITLIST_CONSENT_VERSION } from '../WaitlistForm';

/**
 * The consent promise is one claim in two deploy units, and now in two placements.
 *
 * `WaitlistService` stores a HASH of the sentence the person was shown, not the sentence. That
 * makes the evidence tamper-evident and it also makes drift invisible: a second placement with a
 * reworded promise produces a second hash for what is supposed to be one promise, and nothing
 * fails, you would only discover it when asked to prove what a given subscriber agreed to, which
 * is exactly the moment you cannot afford to find out.
 *
 * Same technique as `marketing/__tests__/packContents.test.ts` against `bridge.py` and
 * `lib/__tests__/facets.test.ts` against `PackFacets.cs`: read the other side's source and compare.
 */
const WAITLIST_SERVICE_CS = fileURLToPath(
  new URL('../../../../../Store.Api/Services/WaitlistService.cs', import.meta.url),
);

function consentVersionFromCSharp(): string {
  const source = readFileSync(WAITLIST_SERVICE_CS, 'utf8');
  const match = /CurrentConsentVersion\s*=\s*"([^"]+)"/.exec(source);
  if (!match) throw new Error(`Could not find CurrentConsentVersion in ${WAITLIST_SERVICE_CS}`);
  return match[1];
}

describe('consent version agreement with Store.Api/Services/WaitlistService.cs', () => {
  it('finds a non-trivial CurrentConsentVersion to compare against', () => {
    // Guards the regex itself: a silently-empty match would make the assertion below vacuous.
    expect(consentVersionFromCSharp()).toMatch(/^waitlist-\d{4}-\d{2}-\d{2}$/);
  });

  it('sends the version the server considers current', () => {
    expect(WAITLIST_CONSENT_VERSION).toBe(consentVersionFromCSharp());
  });
});

describe('every placement makes the same promise', () => {
  // Rendered, not read off the constant: the point is that what reaches the page is what gets
  // hashed. A placement that hand-wrote its own sentence would pass a constant-equality check and
  // fail here.
  const placements: [string, React.ReactElement][] = [
    ['catalogue empty state', <DiscoveryWaitlist key="a" query="oyster farming" />],
    ['sample report footer', <WaitlistCallout key="b" />],
  ];

  for (const [name, element] of placements) {
    it(`renders the exact consent sentence in the ${name}`, () => {
      const html = renderToStaticMarkup(element);
      expect(html).toContain(WAITLIST_CONSENT_TEXT);
    });

    it(`does not promise a recurring send in the ${name}`, () => {
      // The consent text the server hashes says "No newsletter". Copy above the form that implies
      // a cadence would contradict the very sentence being recorded as evidence one line below it.
      const html = renderToStaticMarkup(element).replace(WAITLIST_CONSENT_TEXT, '');
      expect(html).not.toMatch(/newsletter|weekly|monthly|every week|digest|subscribers/i);
    });
  }
});
