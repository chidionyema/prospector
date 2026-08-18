import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * THE PACK PAGE MUST SAY WHAT THE OPPORTUNITY IS, NOT ONLY WHAT THE PRODUCT IS.
 *
 * Founder, 2026-08-16: "the title and description says what it is and what it does, not the
 * opportunity presented, market size, problem and pain point and would-be buyers at a glance ...
 * mandatory". Every description field the page had -- `title`, `oneLine`, `headline`, `cardLine`
 * -- answers "what is this thing". A reader deciding whether to spend a year on the idea needs
 * three other facts first: what is broken, how big it is, and who would pay for the fix.
 *
 * Two of those three fields did not exist anywhere in the chain. This suite pins the whole chain,
 * because a field is only real if every hop carries it:
 *   prompts/content_gen.md  asks the operator for it, under a rule that forbids inventing it
 *   prospector/bridge.py    copies it into the catalogue row
 *   lib/api/client.ts       types it and sanitises it like the other prose
 *   pages/pack/[id].tsx     renders it, and renders nothing when it is absent
 *
 * The mechanism copy is NOT replaced by any of this (founder, same day: "the mechanism can still
 * be kept around"), so the last test here fails if the opportunity block is ever built by taking
 * the product description away.
 */
const WEB = fileURLToPath(new URL('..', import.meta.url));
// src/ -> Store.Web -> src -> store_platform -> repo root. Four hops, not five: five lands in
// the directory ABOVE the checkout, where `prospector/bridge.py` happens not to exist, so the
// suite fails with ENOENT instead of quietly reading another clone.
const REPO = join(WEB, '..', '..', '..', '..');

const packPage = readFileSync(join(WEB, 'pages', 'pack', '[id].tsx'), 'utf8');
const client = readFileSync(join(WEB, 'lib', 'api', 'client.ts'), 'utf8');
const bridge = readFileSync(join(REPO, 'prospector', 'bridge.py'), 'utf8');
const contentGen = readFileSync(join(REPO, 'prompts', 'content_gen.md'), 'utf8');

describe('the opportunity reaches the buyer', () => {
  it('the engine is asked for the problem and the market size', () => {
    expect(contentGen).toMatch(/"the_problem":/);
    expect(contentGen).toMatch(/"market_size":/);
  });

  it('the market-size figure may only be quoted, never estimated', () => {
    // This is the field most likely to be invented, and an invented market size on a page whose
    // whole position is "every claim is sourced" is the worst defect the page could carry. The
    // prompt has to say so in the field itself AND in a rule, so a model skimming either one
    // still meets the constraint.
    expect(contentGen).toMatch(/A SIZE FIGURE ONLY IF A VERIFIED CLAIM STATES ONE/);
    expect(contentGen).toMatch(/OPPORTUNITY RULES/);
    expect(contentGen).toMatch(/Never estimate, never extrapolate/);
    expect(contentGen).toMatch(/An empty `market_size` is a CORRECT answer/);
  });

  it('the publish boundary carries both fields onto the catalogue row', () => {
    expect(bridge).toMatch(/"theProblem": _card_field\(listing\.get\("the_problem"\)\)/);
    expect(bridge).toMatch(/"marketSize": _card_field\(listing\.get\("market_size"\)\)/);
  });

  it('both fields are linted for truncation like the rest of the shelf copy', () => {
    // A market-size sentence cut mid-clause can lose its unit and still read as a whole claim,
    // which is how "1.6 million licensed drivers" becomes "1.6 million licens".
    const texts = bridge.slice(bridge.indexOf('listing_texts={'));
    expect(texts).toMatch(/"theProblem": \(catalog_meta\.get\("theProblem", ""\)/);
    expect(texts).toMatch(/"marketSize": \(catalog_meta\.get\("marketSize", ""\)/);
  });

  it('the client types both and runs them through the site voice', () => {
    expect(client).toMatch(/theProblem\?: string;/);
    expect(client).toMatch(/marketSize\?: string;/);
    const prose = client.slice(client.indexOf('const PROSE_FIELDS'), client.indexOf('] as const;', client.indexOf('const PROSE_FIELDS')));
    expect(prose).toMatch(/'theProblem'/);
    expect(prose).toMatch(/'marketSize'/);
  });

  it('the pack page renders all three opportunity facts, each behind its own guard', () => {
    expect(packPage).toMatch(/\{pack\.theProblem && \(/);
    expect(packPage).toMatch(/\{pack\.marketSize && \(/);
    expect(packPage).toMatch(/The problem</);
    expect(packPage).toMatch(/How big it is</);
    expect(packPage).toMatch(/Who would buy it</);
  });

  it('renders no heading when the pack carries none of the three', () => {
    // Every pack published before 2026-08-16 has an empty `theProblem` and `marketSize`, and
    // `marketSize` stays empty forever on any pack whose dossier states no size. A labelled
    // empty block on those packs would advertise a gap on the money page.
    expect(packPage).toMatch(/\{\(pack\.theProblem \|\| pack\.marketSize \|\| pack\.whoPays\) && \(/);
  });

  it('says who would buy it exactly once', () => {
    // `whoPays` was moved up into the opportunity block; it used to also be a row in the
    // "Could you run this?" list. The page has a standing rule against stating one fact twice.
    const uses = packPage.match(/\{pack\.whoPays\}/g) ?? [];
    expect(uses, 'whoPays is rendered in more than one place on the pack page').toHaveLength(1);
  });

  it('keeps the product description as well as the opportunity', () => {
    // The founder asked for the opportunity to be ADDED, not for the mechanism to be removed.
    // If a later change deletes the lead paragraph or the what-you-get list to make room, this
    // fails rather than shipping a page that says why the idea is good and never what it is.
    expect(packPage).toMatch(/\{lead && </);
    expect(packPage).toMatch(/\{pack\.title\}/);
    expect(packPage).toMatch(/whatYouGet/);
  });
});
