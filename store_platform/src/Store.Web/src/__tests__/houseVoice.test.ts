import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * THE HOUSE VOICE, APPLIED TO THE STOREFRONT.
 *
 * THE RESEARCH-DESK REGISTER (founder 2026-09-03). Reader-facing chrome is an intelligence
 * brief, not a startup landing page. The homepage is the worked example: kicker
 * "RESEARCHED. PRICED. READY TO BUILD.", headline "Business ideas with the research
 * already done.", survival rate "Only the top 6% survive the checks." (founder 2026-09-03 19:46 email), filters "Filter the Archive"
 * never "Narrow it down", kill reasons in the GATE_LABELS map ("Did not score high
 * enough to be viable") never the old engine phrasing ("Scored below the bar overall").
 * Apply that same language on /how-it-works, /kill-log, /about, /faq, /ideas, pack
 * chrome, emails and OG. Do not rewrite the 77 generated pack one-liners to get there.
 * `retired-startup-copy` below is the fence: if the old jargon comes back, this file
 * fails. Contractions and the other rules in this file still bind; the founder lines
 * were adapted to them on the homepage, not pasted over them.
 *
 * `prompts/style/voice.md` at the repo root is the document that says what our prose sounds
 * like. It was written for the engine's pack prose and it is enforced there, by
 * `tests/invariants/test_house_voice.py`. It was never applied to the shop.
 *
 * The shop had two tone guards -- `dashFree.test.ts` and `bannedWords.test.ts` -- and
 * `bannedWords.test.ts` says in its own comments that the grammar rules "are not greppable
 * without a sentence parser ... and reviewed by eye". Nothing was reviewing by eye. The site
 * shipped with 66 breaches of the voice document, 31 of them in `lib/seo/landings.ts`, the file
 * no one reads because it is search-engine prose. `https://mumchimp.com/ideas/b2b-business-ideas`
 * was serving "That changes the shape of the work" and "a conversation rather than an impulse"
 * to buyers.
 *
 * They are greppable. Not perfectly -- a regex cannot parse a sentence -- but every rule below
 * catches its tell at the surface, and the four places where the surface lies are exempted by a
 * `tone-ok:` comment on the line, with the reason written beside it. That is the same opt-out
 * idiom `dashFree.test.ts` uses.
 *
 * Each rule carries the line of voice.md it enforces, so a failure explains itself without
 * anyone having to open the document.
 *
 * Run via `npm test houseVoice`.
 */
const SRC = fileURLToPath(new URL('..', import.meta.url));

const ROOTS = ['pages', 'components', 'lib'];
const SKIP_DIRS = new Set(['__tests__', 'node_modules']);

/** Opt-out pragma. Put the reason on the same line, after it. */
const IGNORE = 'tone-ok:';

/* Block comments collapse to their own newlines so the reported line number is the real one.
   Line comments go entirely: a comment explaining why a word was replaced would otherwise be
   graded for containing the word. */
const stripComments = (src: string) =>
  src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ''))
    .replace(/(^|[^:])\/\/.*$/gm, '$1');

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.tsx?$/.test(entry) && !/\.(test|d)\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

const sources = () => ROOTS.flatMap((root) => walk(join(SRC, root)));

/* WHAT COUNTS AS COPY. A string a buyer reads has spaces and words in it. A path, an import
   specifier, a Tailwind class list, an SVG path or a string that is nothing but interpolation
   is not prose, and grading it produces noise that gets the whole guard switched off. */
const STRING = /(['"`])((?:\\.|(?!\1)[^\\])*?)\1/g;
const JSXTEXT = />([^<>{}]{8,})</g;
const CLASSY = /^[a-z0-9:_[\]\-./%() ]+$/;
/* A content-type header is a wire value. Its semicolon is not a lost full stop. */
const WIRE = /charset=|^[a-z]+\/[a-z0-9+.\-]+$|^[A-Za-z-]+: /;
const SVGPATH = /^[Mm][\d.\-]/;
const ENTITY = /&[a-z]+;|&#\d+;/g;

function isCopy(s: string): boolean {
  const t = s.trim();
  if (t.length < 12 || !t.includes(' ')) return false;
  if (/^(\/|@|http|#|\?|\.|use )/.test(t)) return false;
  if (CLASSY.test(t)) return false;
  if (SVGPATH.test(t)) return false;
  if (WIRE.test(t)) return false;
  // A template made only of ${...} is an expression, not a sentence.
  return (t.replace(/\$\{[^}]*\}/g, ' ').match(/[A-Za-z']{2,}/g) ?? []).length >= 3;
}

type Rule = { name: string; re: RegExp; why: string };

const RULES: Rule[] = [
  {
    name: 'antithesis',
    re: /\bnot (?:a |an |the |just |only |simply )?[^.!?]{2,50}?,? (?:but|it is|it's|they are)\b/i,
    why: 'voice.md: "NEVER DEFINE A THING BY WHAT IT IS NOT. The antithesis is a rhythm, not an argument." State the true thing once.',
  },
  {
    name: 'antithesis-comma',
    re: /,\s*not\s+(?:a|an|the|another|yet)\b/i,
    why: 'voice.md: "X, not Y" is the same antithesis rhythm. Drop the false half.',
  },
  {
    name: 'rather-than',
    re: /\brather than\b/i,
    why: 'voice.md names "rather than" as the antithesis rhythm. Say the true thing.',
  },
  {
    name: 'quantity-without-a-number',
    re: /\b(numerous|significant|substantial|considerable|countless|myriad|several|dozens of|a handful of|a fraction of|a trail of|plenty of|a range of|a variety of)\b/i,
    why: 'voice.md: "NO QUANTITY WORD WITHOUT A QUANTITY." Put the number in, or cut the word.',
  },
  {
    name: 'opens-with-that-or-which',
    re: /(?:^|[.!?]\s+)(?:That|Which|And that|So that) (?:is|was|are|were|has|have|had|does|do|did|changes|change|makes|make|means|mean|leaves|leave|gives|give|puts|put|matters|works|reads|costs|takes|comes|sits|keeps|turns|raises|rules)\b/,
    why: 'voice.md: never open a sentence with "That" or "Which". The reader has to reverse to find what it points at. ("That page isn\'t here" is a determiner and is fine, which is why a verb has to follow.)',
  },
  {
    name: 'outcome-adjective',
    re: /\b(huge|massive|exciting|lucrative|no-brainer|game-changing|revolutionary|cutting[- ]edge|world[- ]class|powerful|effortless|incredible|amazing|stunning|remarkable|exceptional|unparalleled|unrivalled|unmatched|transformative)\b/i,
    why: 'voice.md: "NO ADJECTIVE MAY ASSERT AN OUTCOME", and that rule outranks every style rule below it. The energy comes from the stakes, not the adjective.',
  },
  {
    name: 'internal-vocabulary',
    re: /\b(wedge|moat|lens|taxonomy|candidate pool|signal set)\b/i,
    why: 'voice.md: "NEVER USE OUR INTERNAL VOCABULARY." Say what the thing does.',
  },
  {
    name: 'not-the-everyday-word',
    re: /\b(indemnif\w*|ceases?|thereby|procure[sd]?|commence[sd]?|endeavour\w*|facilitat\w*|comprise[sd]?|prior to|in order to|aforementioned|henceforth|whilst|amongst)\b/i,
    why: 'voice.md: "PREFER THE EVERYDAY WORD." Pays out, not indemnifies. Stops, not ceases. So, not thereby.',
  },
  {
    name: 'stock-model-phrase',
    re: /(in today's|fast[- ]paced|\bdelve\b|\brealm\b|the landscape of|\btapestry\b|testament to|at the end of the day|when it comes to|the world of|look no further|whether you're|whether you are|it's worth noting|it is worth noting|that said|in conclusion|take it to the next level|let's dive|here's the thing|the truth is|more than just|not just a|welcome to)/i,
    why: 'the phrases a model reaches for when it has nothing to say. Cut the sentence, it is carrying no information.',
  },
  {
    name: 'exclamation-mark',
    re: /[a-z]!(?:\s|$|")/,
    why: 'the site does not shout. A full stop carries it.',
  },
  {
    name: 'semicolon-in-a-claim',
    re: /[a-z]; [a-z]/,
    why: 'voice.md: a semicolon is a full stop that lost its nerve. Two sentences.',
  },
  {
    /* Three or more commas before a final "and"/"or", where the run-up segments are short enough
       to be items rather than clauses. Six words is where a list item stops being an item; below
       that the commas are almost always enumerating. */
    name: 'four-or-more-item-list',
    re: /(?:[^,;:.!?()]{2,45},\s+){2,}[^,;:.!?()]{2,45}\s+(?:and|or)\s/,
    why: 'voice.md: "NEVER MORE THAN THREE ITEMS IN A LIST" -- the single strongest tell that the writing ran out of content before it ran out of rhythm. Cut to the three that carry weight.',
  },
  {
    name: 'rhetorical-question',
    re: /\?\s+[A-Z]/,
    why: 'a question inside our own prose is the trick where the writer asks what the reader was going to. Say the answer. (An FAQ heading is a whole string and does not match.)',
  },
  {
    name: 'retired-startup-copy',
    re: /Narrow it down|Scored below the bar overall|Incumbents already own|defensibility claim was not evidence-backed|It failed the second round of checks|The value would not last|The payer cannot actually pay|Six common checks\. Sourced evidence|filter built to kill|kill-first filter/i,
    why: 'founder 2026-09-03: the homepage is the research-desk example. Old startup jargon and the old kill-reason phrasing cannot return on reader-facing copy. Say "Filter the Archive", "6 in 100", and the GATE_LABELS sentences.',
  },
];

/** voice.md: "ONE IDEA PER SENTENCE. Aim under 25 words, never over 28." */
const LONG = 28;

/* The three statutory pages quote the Consumer Contracts Regulations and the Limitation Act.
   The sentence length and the semicolons in them belong to the law, not to us. */
const LEGAL = new Set(['pages/terms.tsx', 'pages/refund.tsx', 'pages/privacy.tsx']);
const LEGAL_EXEMPT = new Set(['over-28-words', 'semicolon-in-a-claim']);
/* The substitution table is the file that REMOVES this vocabulary from model prose. Its entries
   quote the words they replace, so grading it would ban the fix. */
const TABLE = 'lib/plainEnglish.ts';

type Breach = { file: string; line: number; rule: string; hit: string; text: string; why: string };

/** A leading segment of six words or fewer is an item; longer than that it is a clause. */
function isRealList(text: string): boolean {
  const m = text.match(RULES.find((r) => r.name === 'four-or-more-item-list')!.re);
  if (!m) return false;
  const segments = m[0].split(',').slice(0, -1);
  return segments.every((s) => (s.match(/\S+/g) ?? []).length <= 6);
}

function breaches(): Breach[] {
  const found: Breach[] = [];
  for (const file of sources()) {
    const rel = file.slice(SRC.length).replace(/\\/g, '/');
    if (rel === TABLE) continue;
    const original = readFileSync(file, 'utf8').split('\n');
    /* The pragma is read from the file as written, because stripComments deletes the comment it
       lives in. Both split to the same line count: block comments collapse to their own newlines
       and line comments are emptied, not removed. */
    const lines = stripComments(original.join('\n')).split('\n');
    lines.forEach((raw, i) => {
      if ((original[i] ?? '').includes(IGNORE)) return;
      const line = raw.includes('className')
        ? raw.replace(/className=(?:\{[^}]*\}|"[^"]*"|'[^']*')/g, ' ')
        : raw;
      const pieces = [
        ...[...line.matchAll(STRING)].map((m) => m[2]),
        ...[...line.matchAll(JSXTEXT)].map((m) => m[1]),
      ];
      for (const piece of pieces) {
        const raw2 = piece.replace(/\\n/g, ' ').replace(/\\/g, '').trim();
        if (!isCopy(raw2)) continue;
        const text = raw2.replace(ENTITY, ' '); // &middot; is a glyph, not a semicolon
        for (const rule of RULES) {
          if (LEGAL.has(rel) && LEGAL_EXEMPT.has(rule.name)) continue;
          const m = text.match(rule.re);
          if (!m) continue;
          if (rule.name === 'four-or-more-item-list' && !isRealList(text)) continue;
          found.push({
            file: rel,
            line: i + 1,
            rule: rule.name,
            hit: m[0].trim(),
            text: text.slice(0, 160),
            why: rule.why,
          });
        }
        if (LEGAL.has(rel)) continue;
        for (const sentence of text.split(/(?<=[.!?])\s+/)) {
          const n = (sentence.match(/\S+/g) ?? []).length;
          if (n > LONG) {
            found.push({
              file: rel,
              line: i + 1,
              rule: 'over-28-words',
              hit: `${n} words`,
              text: sentence.slice(0, 160),
              why: 'voice.md: "ONE IDEA PER SENTENCE. Aim under 25 words, never over 28."',
            });
          }
        }
      }
    });
  }
  return found;
}

const report = (rows: Breach[]) =>
  rows
    .map((b) => `\n${b.file}:${b.line}  [${b.rule}: ${b.hit}]\n  ${b.text}\n  ${b.why}`)
    .join('\n');

const ALL = breaches();

describe('house voice (prompts/style/voice.md) applies to the storefront too', () => {
  for (const rule of [...RULES.map((r) => r.name), 'over-28-words']) {
    it(`no copy breaks: ${rule}`, () => {
      const rows = ALL.filter((b) => b.rule === rule);
      expect(rows.length, report(rows)).toBe(0);
    });
  }

  /* VACUITY GUARDS. Every rule above is a regex over strings the walker found. If the walker
     stops finding strings -- a moved directory, a changed extension, a stricter isCopy -- every
     assertion above passes on an empty set and the guard is decoration. These fail instead. */
  it('is reading the source tree it claims to read', () => {
    expect(sources().length).toBeGreaterThan(100);
  });

  it('is still finding prose to grade, not just files', () => {
    let copy = 0;
    for (const file of sources()) {
      for (const m of stripComments(readFileSync(file, 'utf8')).matchAll(STRING)) {
        if (isCopy(m[2])) copy += 1;
      }
    }
    expect(copy).toBeGreaterThan(400);
  });

  it('every rule still fires on the sentence it was written for', () => {
    const samples: Record<string, string> = {
      antithesis: 'This is not a directory, it is a research engine.',
      'antithesis-comma': 'A pack is research, not a promise.',
      'rather-than': 'The sale is a conversation rather than an impulse.',
      'quantity-without-a-number': 'Several ideas were killed at that gate.',
      'opens-with-that-or-which': 'The buyer has a budget. That changes the shape of the work.',
      'outcome-adjective': 'This is a huge opportunity for the right operator.',
      'internal-vocabulary': 'The pack gives you a wedge into the market.',
      'not-the-everyday-word': 'The cover ceases prior to the renewal date.',
      'stock-model-phrase': 'In today’s fast-paced market, buyers want proof.',
      'exclamation-mark': 'Your pack is on its way!',
      'semicolon-in-a-claim': 'The research is shared; the ground is not.',
      'four-or-more-item-list': 'The buyer, the price, the margins and the plan.',
      'rhetorical-question': 'So who actually pays? The council does.',
      'retired-startup-copy': 'Narrow it down to the packs that fit.',
    };
    for (const rule of RULES) {
      const sample = samples[rule.name];
      expect(sample, `no sample sentence for ${rule.name}`).toBeTruthy();
      expect(rule.re.test(sample), `${rule.name} stopped matching its own sample`).toBe(true);
      if (rule.name === 'four-or-more-item-list') {
        expect(isRealList(sample), 'the list rule stopped counting items').toBe(true);
      }
    }
  });

  it('does not count clauses as list items', () => {
    // Real copy on kill-log.tsx and PackContents.tsx. Commas separating clauses, not items.
    expect(
      isRealList('Killed ideas, with the check that killed each one, its published sources and the date.'),
    ).toBe(false);
    expect(isRealList('The buyer, the price, the margins and the plan.')).toBe(true);
  });

  it('honours the opt-out pragma, so the exemptions are real', () => {
    const disclaimer = readFileSync(join(SRC, 'lib/disclaimer.ts'), 'utf8');
    expect(disclaimer).toContain(IGNORE);
  });
});
