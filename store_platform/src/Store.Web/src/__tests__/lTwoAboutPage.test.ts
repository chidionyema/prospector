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
 * L2 - The about page.
 *
 * The audit (§6) said: "The IA is missing four pages entirely: ... a real
 * /about page. The store is a single voice. The buyer wants to know who
 * is behind this. The about page is missing. The story is the moat."
 *
 * The about page is the human face of the brand. It must be the voice
 * ("source-or-die") rendered as a person, not a corporate boilerplate
 * "About Us" page. The story: the engine, the six checks, the kill log,
 * and why.
 */
describe('L2 - The about page', () => {
  const pageExists = existsRelative('../pages/about.tsx');

  it('declares an /about page', () => {
    expect(pageExists, 'pages/about.tsx must exist').toBe(true);
  });

  it('explains the checks', () => {
    if (!pageExists) return;
    const page = readSource('../pages/about.tsx');
    const mentionsChecks = /\bchecks\b|\bfronts\b/i.test(page);
    expect(
      mentionsChecks,
      'pages/about.tsx must explain the checks (the filter)',
    ).toBe(true);
  });

  /**
   * The page must NOT promise a fixed count. Measured 2026-08-06 against the live /catalog
   * detail endpoint across all 63 published packs, `qaVerdictSummary` reports "6/6 checks
   * cleared" 40x, "8/8" 15x, "7/8" 4x, "9/9" 3x and "6/8" 1x -- so "all six checks" was false
   * for 23 of them, on a page the buyer reads before paying. The check set is lane-dependent
   * (config.yaml `lanes.side_hustle` adds buyer_intent, currency and claims_verifiable), and
   * pack/[id].tsx has always rendered the engine's real numerator and denominator. This test
   * stops the fixed count coming back into the copy while the engine still varies it.
   */
  it('never promises a fixed number of checks', () => {
    if (!pageExists) return;
    const page = readSource('../pages/about.tsx');
    const body = page.replace(/\/\*[\s\S]*?\*\/|\{\/\*[\s\S]*?\*\/\}/g, '');
    const fixedCount = body.match(/\b(all six|the six|six brutal|six rigid|six rigorous)\b/i);
    expect(
      fixedCount?.[0] ?? null,
      'pages/about.tsx must not claim a fixed check count: the engine\'s denominator varies by lane (6, 7, 8 or 9 on live packs)',
    ).toBe(null);
  });

  it('links to the kill log', () => {
    if (!pageExists) return;
    const page = readSource('../pages/about.tsx');
    const linksToKillLog = /href=["']\/(rejected|kill-log)["']/.test(page);
    expect(
      linksToKillLog,
      'pages/about.tsx must link to /rejected (the audit trail; /kill-log 301s there)',
    ).toBe(true);
  });

  it('renders in the source-or-die voice (no marketing boilerplate)', () => {
    if (!pageExists) return;
    const page = readSource('../pages/about.tsx');
    // The about page must use the source-or-die voice, not generic
    // "About Us" boilerplate. The kill log citation and the "sourced,
    // not sold" framing are the markers.
    const voice = /source-or-die|every claim cited|cited a source|every one cited/i.test(page);
    expect(
      voice,
      'pages/about.tsx must use the source-or-die voice (cited sources, no embellishment)',
    ).toBe(true);
  });

  it('links to the sample report', () => {
    if (!pageExists) return;
    const page = readSource('../pages/about.tsx');
    const linksToSample = /href=["']\/sample["']/.test(page);
    expect(
      linksToSample,
      'pages/about.tsx must link to /sample (the free dossier)',
    ).toBe(true);
  });
});
