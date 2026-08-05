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

  it('explains the six checks', () => {
    if (!pageExists) return;
    const page = readSource('../pages/about.tsx');
    const mentionsChecks = /six\s*checks|6\s*checks|six brutal|six rigorous/i.test(page);
    expect(
      mentionsChecks,
      'pages/about.tsx must explain the six checks (the filter)',
    ).toBe(true);
  });

  it('links to the kill log', () => {
    if (!pageExists) return;
    const page = readSource('../pages/about.tsx');
    const linksToKillLog = /href=["']\/kill-log["']/.test(page);
    expect(
      linksToKillLog,
      'pages/about.tsx must link to /kill-log (the audit trail)',
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
