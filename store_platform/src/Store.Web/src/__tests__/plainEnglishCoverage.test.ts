import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { plainEnglish, internalResidue } from '@/lib/plainEnglish';

const SRC = fileURLToPath(new URL('..', import.meta.url));

/**
 * The guard runs over the CORPUS, not over the pages, and that is the point.
 *
 * A test that greps `kill-log.tsx` for "candidate" proves the page does not TYPE the word. The
 * word was never typed: it arrives in `data/kill-log.json`, written by the engine, and is rendered
 * verbatim. So the only assertion worth making is over the data a reader will actually be shown,
 * put through the exact function the render path puts it through.
 *
 * This also survives regeneration. `tools/make_kill_log.py` rewrites the JSON, and the next run
 * can introduce a form the translation does not know about -- "candidates" plural, a gate id that
 * `checks.ts` does not name. That fails here, in a message naming the string, rather than shipping.
 */

/** Every string a reader can be shown, from the three files the marketing pages render. */
function proseCorpus(): { file: string; key: string; text: string }[] {
  const out: { file: string; key: string; text: string }[] = [];
  const PROSE_KEYS = /^(reason|rationale|oneLiner|summary|note)$/;
  for (const file of ['kill-log.json', 'kill-log-examples.json', 'sample-report.json']) {
    const raw = readFileSync(join(SRC, 'data', file), 'utf8');
    JSON.parse(raw, (key, value) => {
      if (typeof value === 'string' && PROSE_KEYS.test(key)) out.push({ file, key, text: value });
      return value;
    });
  }
  return out;
}

describe('engine vocabulary does not reach a buyer', () => {
  const corpus = proseCorpus();

  it('reads a corpus at all, from every file', () => {
    // Guards the guard. A renamed data file, or a generator that renames `reason` to `verdict`,
    // would make every assertion below pass over zero strings and report clean having read
    // nothing -- the failure mode where a probe is silent because it is blind, not because the
    // thing is fixed. Measured 2026-08-15: 800 + 120 + 10 = 930 strings.
    expect(corpus.length, 'the prose corpus is nearly empty -- did a data file or a key move?')
      .toBeGreaterThan(800);
    for (const file of ['kill-log.json', 'kill-log-examples.json', 'sample-report.json']) {
      expect(corpus.filter((c) => c.file === file).length, `${file} contributed no prose`)
        .toBeGreaterThan(0);
    }
  });

  /**
   * The terms the translation claims to remove. Each one is here because it was MEASURED in the
   * corpus on 2026-08-15, not because it might appear: 104 strings said "the candidate", 32 named
   * a gate by its snake_case id, 11 said "dossier", 8 said "the hypothesis", 5 carried a backtick,
   * and one each said "hard gate" and "refutation threshold".
   */
  const TRANSLATED: { label: string; pattern: RegExp }[] = [
    { label: 'candidate', pattern: /\bcandidates?('s)?\b/i },
    { label: 'the hypothesis', pattern: /\bthe hypothesis\b/i },
    { label: 'dossier', pattern: /\bdossiers?\b/i },
    { label: 'hard gate', pattern: /\bhard gates?\b/i },
    { label: 'refutation threshold', pattern: /\brefutation threshold\b/i },
    { label: 'backtick', pattern: /`/ },
    // Both forms. The plural does not occur today and is not translated; banning it here is what
    // makes a regeneration that introduces it fail loudly instead of shipping half-translated.
    { label: 'incumbency', pattern: /\bincumbenc(y|ies)\b/i },
    // The snake_case gate ids only. `distribution` and `legality` are gate ids too and are
    // deliberately NOT banned: in this corpus they are only ever ordinary nouns, and banning the
    // word would force a substitution that corrupts the sentence -- see the second note in
    // `plainEnglish.ts`, and the regression test below this one. `incumbency` was in this
    // exemption and should not have been: it is banned above.
    {
      label: 'snake_case gate id',
      pattern: /\b(pain_reality|value_durability|payer_solvency|route_to_market)\b/,
    },
  ];

  it('translates every term it claims to translate, across the whole corpus', () => {
    const survivors: string[] = [];
    for (const { file, key, text } of corpus) {
      const rendered = plainEnglish(text);
      for (const { label, pattern } of TRANSLATED) {
        const hit = rendered.match(pattern);
        if (hit) survivors.push(`${file} [${key}] "${label}" survived as "${hit[0]}" in: ${rendered.slice(0, 140)}`);
      }
    }
    expect(survivors).toEqual([]);
  });

  it('leaves a gate id that is also an ordinary word alone', () => {
    // The defect this pins shipped for the length of one test run: `distribution` and `legality`
    // are gate ids in `checks.ts`, so substituting every id for its check name rewrote 55
    // occurrences of two common English nouns and broke the sentences around them. A translation
    // is only allowed to be mechanical where the token can only mean one thing.
    const sentences = [
      'The passages show bread/bakery distribution dominated by a few large manufacturers.',
      'Regulations wholly unrelated to the legality of scraping school websites.',
    ];
    for (const sentence of sentences) expect(plainEnglish(sentence)).toBe(sentence);

    // `incumbency` is the counter-example, and the reason the rule is per-word and measured
    // rather than a blanket "leave English-looking words alone": read in context, 22 of its 24
    // occurrences are the gate standing in for itself, so it goes.
    expect(plainEnglish('Incumbency checks failed to find existing competitors')).toBe(
      'Incumbent competition checks failed to find existing competitors',
    );
    expect(plainEnglish('incumbency + payer_solvency: the single passage')).toBe(
      'incumbent competition + payer solvency: the single passage',
    );

    // And the snake_case form still goes, in the corpus's own phrasing rather than a coined one.
    expect(plainEnglish('the payer_solvency check returned no supporting evidence')).toBe(
      'the payer solvency check returned no supporting evidence',
    );
    expect(plainEnglish('pain_reality and value_durability returned nothing')).toBe(
      'pain reality and value durability returned nothing',
    );
  });

  it('is idempotent, because the same reason is rendered twice through different paths', () => {
    // /kill-log renders `reason` whole; /how-it-works renders the same string truncated through
    // `firstSentences`. A rule whose output re-matches its own pattern would differ between the
    // two, and the same kill would read differently on two pages that both claim to quote it.
    const drifted = corpus
      .filter(({ text }) => plainEnglish(plainEnglish(text)) !== plainEnglish(text))
      .slice(0, 3)
      .map(({ file, key }) => `${file} [${key}]`);
    expect(drifted).toEqual([]);
  });

  it('changes nothing in prose that was already plain', () => {
    // The translation must be a no-op where there is nothing to translate, or it is editing
    // evidence rather than vocabulary.
    const clean = 'Two passages describe a live commercial service selling UK property data.';
    expect(plainEnglish(clean)).toBe(clean);
    expect(plainEnglish('')).toBe('');
  });

  /**
   * WHAT IS KNOWINGLY LEFT IN, AND WHY IT IS PINNED RATHER THAN BANNED.
   *
   * `unverifiable`, `source-or-die`, `verdict-from-retrieval-only`, bare KILL/PASS tokens and gate
   * ids `checks.ts` does not name cannot be rewritten by a regex without authoring evidence prose
   * -- see the docblock in `lib/plainEnglish.ts`. They need a copy decision or the generator, which
   * the founder's 2026-08-15 pass ranks last, deliberately.
   *
   * So the ceiling is a RATCHET, not an approval. It is the measurement taken the day the
   * translation shipped; the test fails if the next regeneration makes any of them worse, and the
   * ceiling gets lowered by hand each time one is actually fixed. A count that can only go down is
   * the honest way to hold a known defect while the fix is somewhere else in the queue.
   */
  it('leaves no MORE untranslatable residue than the day it was measured', () => {
    // OCCURRENCES, not strings: `internalResidue` counts matches, and one row can say
    // "unverifiable" four times. Measured 2026-08-15 over all 930 strings, post-translation.
    // Anything absent from this map has a ceiling of zero, so a NEW residue class fails here
    // rather than being waved through by a missing key.
    const CEILING: Record<string, number> = {
      unverifiable: 51,
      'snake_case identifier': 17,
      'source-or-die': 14,
      'bare KILL/PASS token': 13,
      'verdict-from-retrieval-only': 10,
    };
    const totals: Record<string, number> = {};
    for (const { text } of corpus) {
      for (const [label, n] of Object.entries(internalResidue(plainEnglish(text)))) {
        totals[label] = (totals[label] ?? 0) + n;
      }
    }
    const worse = Object.entries(totals)
      .filter(([label, n]) => n > (CEILING[label] ?? 0))
      .map(([label, n]) => `${label}: ${n} occurrences, ceiling ${CEILING[label] ?? 0}`);
    expect(worse, 'a regeneration introduced internal vocabulary the translation cannot handle').toEqual(
      [],
    );
  });
});
