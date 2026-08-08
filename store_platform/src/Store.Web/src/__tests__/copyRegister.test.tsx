import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import LiveKillCard from '@/components/marketing/LiveKillCard';
import { AmbientKillColumn } from '@/components/marketing/AmbientKillColumn';
import EvidenceExcerptPlate, { recordReference } from '@/components/marketing/EvidenceExcerptPlate';
import { CheckSequence } from '@/components/marketing/CheckSequence';
import killNames from '@/data/kill-log-names.json';
import type { PackDetails } from '@/lib/api/client';

/*
  THE REGISTER GUARD — no engine vocabulary in RENDERED copy.

  WHY THIS IS A RENDER TEST AND NOT A SOURCE CHECK. We already have a source check:
  `scripts/site_spec_probe.py` reads SITE_SPEC 5.2 out of prose (JSX text and sentence-shaped
  string literals) and it reported PASS -- "0 reader-facing instances of
  catalog/shot/grounded/gauntlet/dossier" -- on 2026-08-08, the same day
  `curl https://mumchimp.com/pack/8d5a441749448b69` returned `dossier:8d5a441749448b69` in the
  served HTML.

  Both statements were true. The probe scans SOURCE, and the leaking string existed in no source
  file: `{pack.dossierRef}` is an interpolation whose value the API assembles at runtime. The same
  hole let the home page print "killed by value durability" -- `kill-log-names.json` carried the
  engine's `gate` id and the component de-underscored it, so again no source file contained the
  offending words in prose.

  A vocabulary rule enforced only over source is therefore structurally blind to every retired
  word that arrives as DATA, which is the majority of the words on this storefront. These tests
  assert over the rendered markup instead, where the distinction between a literal and an
  interpolation does not exist. That is the only place the claim "a reader never sees this" is
  actually decidable.

  `renderToStaticMarkup`, not jsdom: these are the server-rendered surfaces (the home page is
  `getServerSideProps`), so the string a stranger receives IS the SSR markup.
*/

/* Retired by SITE_SPEC 5.2, with the replacement the spec names. Deliberately a SHORT list of
   words with a documented retirement -- not every internal noun -- because a guard that fires on
   defensible copy gets disabled, and a disabled guard is what we already had. */
const RETIRED: Record<string, string> = {
  dossier: 'pack (or "evidence record" for the record inside one)',
  gauntlet: 'the checks',
  catalog: 'catalogue (en_GB)',
};

/* The engine's own gate ids and scoring axes, in the shape they leak in. Matching the SHAPE
   (snake_case, and its de-underscored form) rather than a fixed list is what makes this survive a
   gate added tomorrow: `value_durability` and `value durability` are both caught without either
   being enumerated here. The de-underscored form is the one that actually shipped. */
const ENGINE_GATES = [
  'pain_reality', 'value_durability', 'payer_solvency', 'route_to_market',
  'adversarial_decisive', 'moat_ungrounded', 'source_or_die', 'min_composite',
  'buyer_intent', 'gate_fired',
];

function offences(markup: string): string[] {
  // Strip attributes before reading prose: class names, test ids and hrefs are not copy, and
  // `data-testid="checks-log"` must not read as a hyphenated engine term.
  const text = markup
    .replace(/<[^>]*>/g, ' ')
    .replace(/&[a-z]+;|&#\d+;/gi, ' ');
  const found: string[] = [];
  for (const [term, replacement] of Object.entries(RETIRED)) {
    const re = new RegExp(`\\b${term}s?\\b`, 'i');
    if (re.test(text)) found.push(`retired term "${term}" is rendered; SITE_SPEC 5.2 says use ${replacement}`);
  }
  for (const gate of ENGINE_GATES) {
    for (const form of [gate, gate.replace(/_/g, ' ')]) {
      if (text.toLowerCase().includes(form)) {
        found.push(`engine gate id "${form}" is rendered; use the kill-log verdict label (SITE_SPEC 5.1 rule 5)`);
      }
    }
  }
  // Any residual snake_case token in prose is a schema name by construction: no English word
  // carries an underscore. This is the open-ended half of the check.
  for (const m of text.matchAll(/\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g)) {
    found.push(`snake_case identifier "${m[0]}" is rendered as copy`);
  }
  return found;
}

const PACK: PackDetails = {
  // Only the fields this component reads are load-bearing; the cast keeps the fixture honest
  // about being partial rather than inventing 30 plausible values.
  dossierRef: 'dossier:8d5a441749448b69',
  sampleExtract: [
    'Direct-payment recipients still file quarterly returns by hand (source: https://gov.uk/x).',
  ],
} as unknown as PackDetails;

describe('rendered copy carries no engine vocabulary', () => {
  it('the home page kill card names the reason, not the gate id', () => {
    const found = offences(renderToStaticMarkup(<LiveKillCard listed={57} />));
    expect(found, found.join('\n')).toEqual([]);
  });

  it('the ambient kill column names the reason, not the gate id', () => {
    const found = offences(renderToStaticMarkup(<AmbientKillColumn />));
    expect(found, found.join('\n')).toEqual([]);
  });

  it('the evidence plate shows a record id without the wire type prefix', () => {
    const markup = renderToStaticMarkup(<EvidenceExcerptPlate pack={PACK} />);
    const found = offences(markup);
    expect(found, found.join('\n')).toEqual([]);
    // The reference must still BE there. Stripping the leak by dropping the whole value would
    // pass the check above and lose the one value on the plate a reader would quote back to us.
    expect(markup).toContain('8d5a441749448b69');
  });
});

describe('no raw confidence floats on marketing pages', () => {
  /* SITE_SPEC 2 P0 rule 4, verbatim: "never render raw floats (`conf 0.41` reads as 41%
     confident and undermines the verdict). Default = omit on marketing pages, show with
     explanation inside the QA report." /how-it-works is a marketing page.

     Matched as a SHAPE -- a bare decimal in prose -- rather than by searching for the string
     "conf", because the defect is the number reaching the reader, not the word introducing it. */
  it('the check sequence states the verdict in words and prints no bare decimal', () => {
    const text = renderToStaticMarkup(<CheckSequence />)
      .replace(/<[^>]*>/g, ' ')
      .replace(/&[a-z]+;|&#\d+;/gi, ' ');
    const floats = [...text.matchAll(/(?<![\d£$%/-])\d?\.\d{2}(?![\d%/-])/g)].map((m) => m[0]);
    expect(floats, `bare decimals in rendered copy: ${floats.join(', ')}`).toEqual([]);
    // The verdict itself must survive: omitting the number must not omit the ruling, or the
    // component stops making the point it exists to make.
    expect(text).toMatch(/survived|pushed back/);
  });
});

describe('recordReference', () => {
  it('strips the wire type prefix by shape, not by matching one retired word', () => {
    expect(recordReference('dossier:8d5a441749448b69')).toBe('8d5a441749448b69');
    // The point of matching a shape: a field renamed upstream must not start leaking again.
    expect(recordReference('record:abc123')).toBe('abc123');
    expect(recordReference('8d5a441749448b69')).toBe('8d5a441749448b69');
  });

  it('returns null for the empty cases that are reachable today', () => {
    // `client.ts` types dossierRef as a required string, but live rows in `store/listings/*.json`
    // carry null, so the plate must not render an empty mono span.
    expect(recordReference(null)).toBeNull();
    expect(recordReference(undefined)).toBeNull();
    expect(recordReference('   ')).toBeNull();
    expect(recordReference('dossier:')).toBeNull();
  });
});

describe('kill-log-names.json is fit to render', () => {
  const rows = killNames as Array<{ title: string; gate: string; gateLabel?: string }>;

  it('every row carries the buyer-facing label the components render', () => {
    // Without this the components have only `gate` to reach for, which is exactly how
    // "killed by value durability" reached the hero. Regenerating via tools/make_kill_log.py
    // must never drop the field again.
    const missing = rows.filter((r) => !r.gateLabel?.trim()).map((r) => r.gate);
    expect(missing, `rows with no gateLabel: ${missing.join(', ')}`).toEqual([]);
  });

  it('no label is an engine identifier', () => {
    const bad = rows
      .map((r) => r.gateLabel ?? '')
      .filter((label) => /_/.test(label) || ENGINE_GATES.some((g) => label.toLowerCase() === g.replace(/_/g, ' ')));
    expect(bad, `identifier-shaped labels: ${bad.join(', ')}`).toEqual([]);
  });
});
