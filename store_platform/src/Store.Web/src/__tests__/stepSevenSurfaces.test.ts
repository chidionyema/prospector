import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

import { FAQS } from '@/lib/faqContent';
import { newSince } from '@/lib/seenPacks';

/**
 * STEP 7 OF THE BUILD ORDER: about, FAQ, account, legal, errors (MASTER-BRIEF sections 7 and 8).
 *
 * These five surfaces have one thing in common: nothing on them is generated, so every property
 * below is a decision somebody made in a text editor and nothing but a test will hold it. The FAQ
 * order in particular is the kind of thing a later edit reverts without noticing, because moving an
 * entry back to its category group looks like tidying.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
const read = (rel: string) => readFileSync(join(SRC, rel), 'utf8');

/** Comments are argument. A note about a deleted control must not read as the control. */
const codeOnly = (src: string) =>
  src
    .split('\n')
    .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
    .join('\n');

describe('the FAQ is ordered by purchase blocker', () => {
  const PAGE = read('pages/faq.tsx');

  it('opens on the objection every visitor arrives with', () => {
    // The page expands the first row on load, so index 0 is the only answer a visitor is
    // guaranteed to read. MASTER-BRIEF section 7: "Why not just ask a chatbot?" is first.
    expect(FAQS[0].question).toBe('Why not just ask a chatbot?');
  });

  it('asks what it is, then why to believe it, before anything about money', () => {
    const order = FAQS.map((f) => f.question);
    const at = (q: string) => order.indexOf(q);
    expect(at('What am I actually buying?')).toBe(1);
    expect(at('What makes a pack evidence-backed?')).toBe(2);
    // The two fears that stop a purchase outrank the mechanics of paying.
    expect(at('If 500 people buy the same pack, aren’t 500 people copying my idea?'))
      .toBeLessThan(at('Can I get a refund?'));
    expect(at('Are the opportunities guaranteed to work?')).toBeLessThan(at('Can I get a refund?'));
    // Housekeeping last: nobody is blocked on a data-removal question before buying.
    expect(at('Can I have my data removed?')).toBe(order.length - 1);
  });

  it('kept every question and every category through the reorder', () => {
    // A reorder that drops an entry is silent: the page still renders, one answer shorter.
    expect(FAQS.length).toBe(13);
    expect(new Set(FAQS.map((f) => f.question)).size).toBe(13);
    expect(new Set(FAQS.map((f) => f.category))).toEqual(new Set(['packs', 'payment', 'process']));
  });

  it('carries no helpfulness widget', () => {
    // DELETED (founder, 2026-08-18, fix list A2): "Was this helpful? Yes/No is still on the FAQ.
    // Delete the component, not just its label." The two tests that used to stand here asserted
    // the control existed and that it reported its vote; both are superseded.
    const code = codeOnly(PAGE);
    expect(code).not.toContain('Was this helpful');
    expect(code).not.toContain('faq_helpful');
  });

  it('keeps the four group filters and the human line', () => {
    expect(PAGE).toContain("{ key: 'packs', label: 'About the packs' }");
    expect(PAGE).toContain("{ key: 'payment', label: 'Payment & access' }");
    expect(PAGE).toContain("{ key: 'process', label: 'Vetting process' }");
    // "All" is the fourth, and it is the one that clears the filter.
    expect(PAGE).toContain('setActiveCategory(null)');
    expect(PAGE).toContain('A human reads every email');
  });
});

describe('the error pages name what happened and offer one action', () => {
  const NOT_FOUND = codeOnly(read('pages/404.tsx'));
  const SERVER = codeOnly(read('pages/500.tsx'));

  it('has stopped promising things about accounts and funded requests', () => {
    // "Your account and any funded request are unaffected" is escrow copy from
    // the-introduction-exchange. This store sells one-off downloads and has no funded requests, so
    // the sentence written to reassure a buyer named something that does not exist.
    for (const page of [NOT_FOUND, SERVER]) {
      expect(page).not.toContain('funded request');
    }
    expect(NOT_FOUND).not.toContain('Nothing is wrong with your account');
  });

  it('does not apologise or guess', () => {
    // MASTER-BRIEF section 7 `Errors`. "The link may be old or mistyped" is a guess offered as an
    // explanation, and it puts a reader in the wrong for following one of our own links.
    for (const page of [NOT_FOUND, SERVER]) {
      expect(page).not.toMatch(/sorry|apolog/i);
    }
    expect(NOT_FOUND).not.toContain('may be old or mistyped');
  });

  it('offers exactly one route onward from each', () => {
    for (const page of [NOT_FOUND, SERVER]) {
      expect(page.split('<Link').length - 1).toBe(1);
    }
  });
});

describe('the about page is set as an essay', () => {
  const ABOUT = read('pages/about.tsx');

  it('uses the 18px, 1.68, 56ch setting on the story', () => {
    // MASTER-BRIEF section 3's type table, "About essay body". The story ran at the site's standard
    // 16px muted body at a 60ch marketing measure, which is why the one human page read like a
    // product description.
    const story = ABOUT.slice(ABOUT.indexOf('id="founder-story"'));
    expect(story).toContain('max-w-[56ch]');
    expect(story).toContain('text-[1.125rem]');
    expect(story).toContain('leading-[1.68]');
  });

  it('signs off under a rule', () => {
    const sign = ABOUT.slice(ABOUT.indexOf('hasFounder()'));
    expect(sign).toContain('border-t');
    expect(sign).toContain('{FOUNDER.name}');
  });

  it('did not touch a word of the copy', () => {
    // MASTER-BRIEF section 7 `/about`: "Copy is verbatim and stays that way." The thesis is the
    // sentence the whole page is built around and it appears twice, as the h1 and in the story.
    expect(ABOUT).toContain('So I built the part I kept losing to doubt.');
    expect(ABOUT).toContain(
      'So I built the part I kept losing to doubt, and made it check every idea harder than I',
    );
    expect(ABOUT).toContain('I always wanted to run my own business, and the ideas were never the hard part.');
  });
});

describe('the account page leads with what the customer owns', () => {
  const ACCOUNT = codeOnly(read('pages/account/index.tsx'));

  it('puts the library first and the return hooks after it', () => {
    // MASTER-BRIEF section 7 `/account`: owned packs with download links first, shortlist second,
    // new since your last visit third.
    expect(ACCOUNT.indexOf('<AccountPanel />')).toBeGreaterThan(-1);
    expect(ACCOUNT.indexOf('<AccountPanel />')).toBeLessThan(ACCOUNT.indexOf('<ReturnBlocks />'));
  });

  it('reads the seen set before it overwrites it', () => {
    // Written first, the visit erases the record it is being compared against and every visit
    // reports nothing new for ever, with no error anywhere.
    const BLOCKS = codeOnly(read('components/account/ReturnBlocks.tsx'));
    expect(BLOCKS.indexOf('readSeen()')).toBeLessThan(BLOCKS.indexOf('rememberSeen('));
  });

  it('calls nothing new on a first visit', () => {
    const packs = [{ id: 'a' }, { id: 'b' }];
    // `null` is "this browser has never recorded a shelf", which is not the same as "recorded an
    // empty one". Announcing the whole catalogue as new since a visit that never happened is a lie
    // told on the first impression.
    expect(newSince(packs, null)).toEqual([]);
    expect(newSince(packs, [])).toEqual(packs);
    expect(newSince(packs, ['a'])).toEqual([{ id: 'b' }]);
  });
});

describe('the three legal documents share one template', () => {
  it('every one of them renders LegalDoc and none rolls its own shell', () => {
    // MASTER-BRIEF section 7 `Legal`: one template for /refund, /terms, /privacy.
    for (const page of ['pages/refund.tsx', 'pages/terms.tsx', 'pages/privacy.tsx']) {
      const src = read(page);
      expect(src, `${page} must use the shared template`).toContain('<LegalDoc');
      expect(src, `${page} must not build its own page shell`).not.toContain('<MarketingLayout');
    }
  });

  it('the template carries a sticky contents rail, a narrow measure and the in-force date', () => {
    const DOC = read('components/LegalDoc.tsx');
    expect(DOC).toContain('<DocRail');
    expect(DOC).toContain('max-w-2xl');
    expect(DOC).toContain('in force since');
    // The rail is built from the real headings, so a renumbered clause cannot send a reader to the
    // wrong paragraph of a contract.
    expect(DOC).toContain('child.type !== LegalHeading');
  });
});
