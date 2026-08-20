/* REAL catalogue data, pulled from https://mumchimp.com on 2026-08-20. No invented numbers. */
export const SITE = {
  available: 77, killed: 1364, researched: 1444, docs: 14, refundDays: 14,
  survivorsPer100: 6, topKillCause: 'Scored below the bar overall', topKillCount: 624,
  priceLow: '19.99', priceHigh: '99.99',
  rungs: [
    { price: '19.99', packs: 3 }, { price: '29.99', packs: 17 },
    { price: '49.99', packs: 32 }, { price: '79.99', packs: 16 }, { price: '99.99', packs: 9 },
  ],
  comparable: { firm: 'IntoTheMinds', year: 2025, min: '€4,000', avg: '€6,000', checked: '1 Aug 2026' },
  killOfWeek: {
    date: '7 Aug',
    title: 'Sound Check Rounds',
    deck: 'The monthly noise test that keeps a small music venue’s licence safe.',
  },
};
export const PACKS = [
  { t:'Abandoned-vendor alerts for UK software operations managers', cat:'Specialist niches',
    d:'A weekly intelligence feed showing which third-party libraries and vendors in a stack have quietly stopped shipping security fixes.',
    price:'99.99', sources:30, payback:13, id:'AV-30' },
  { t:'Noise report checks for acoustic consultancies', cat:'Professional services',
    d:'Turns sound-meter readings and site notes into checked draft appendices for noise assessments under BS 4142.',
    price:'79.99', sources:38, payback:12, id:'NR-38' },
  { t:'Road occupation permit packs', cat:'Trades and site work',
    d:'Turns a scaffolding site address and dates into a complete, council-specific permit application, ready for submission.',
    price:'49.99', sources:34, payback:6, id:'RO-34' },
  { t:'Stripe chargeback defence packs', cat:'Professional services',
    d:'Pulls order, IP, fulfilment and signature evidence from Shopify and the courier into Stripe’s exact dispute-evidence format.',
    price:'49.99', sources:40, payback:8, id:'SC-40' },
  { t:'Cold chain audit AI for Georgia poultry processors', cat:'Professional services',
    d:'An AI auditor that reads temperature logs and finds the hour a cold chain broke, so a plant can answer a USDA inspector without scrambling.',
    price:'29.99', sources:28, payback:1, id:'CC-28' },
  { t:'R&D tax credit claim builder', cat:'Professional services',
    d:'Drafts HMRC R&D claim narratives from product docs and papers, so UK deep-tech startups file in days rather than weeks.',
    price:'19.99', sources:23, payback:4, id:'RD-23' },
];
export const CATEGORIES = [
  { n:'Professional services', c:19 }, { n:'Care and benefits claims', c:10 },
  { n:'Specialist niches', c:9 }, { n:'Trades and site work', c:8 },
  { n:'Red-tape and licensing', c:7 }, { n:'Property and probate', c:4 },
  { n:'Pay and worker rights', c:3 }, { n:'Housing and tenancy', c:2 },
  { n:'Creator rights', c:1 }, { n:'The pet economy', c:1 },
];
export const DOCS = [
  'Where this starts','What you would be selling','The field: who is already there','The numbers',
  'What would sink this','What you build','How the first customers find you','How it runs once it works',
  'Your first fortnight','The toolkit','Copy you can paste','How to know in 30 days',
  'Everything we read, once','Every check, in full',
];
export const KILL_CAUSES = [
  // Only the leading cause carries a published count (624 of 1,364). The remaining five are
  // published as an ORDER, not as numbers, so no count is shown for them. Source-or-die.
  { n:'Scored below the bar overall', c:624, published:true },
  { n:'No durable value',             c:null, published:false },
  { n:'An incumbent already owns it', c:null, published:false },
  { n:'No solvent payer',             c:null, published:false },
  { n:'No route to distribution',     c:null, published:false },
  { n:'Legality',                     c:null, published:false },
];

/* ---------------------------------------------------------------------------
   THE SEVEN CHECKS, in the order the engine runs them. Six are GATES — any one
   of them can kill an idea, and 1,364 ideas died on one. The seventh can never
   kill: "no price page exists on the open web" is a fact about the web, not a
   fact about the idea. That asymmetry is the most trust-bearing thing on the
   pack page, so it is stated on the page rather than buried here.

   Each carries the question in the BUYER's words, not ours. Gate A48: an
   internal term may appear only where the same screen defines it.
   --------------------------------------------------------------------------- */
export const CHECKS = [
  { k:'pain_reality',     n:'Is the pain real?',        q:'Do the people with this problem describe it themselves, in public, in their own words?', gate:true },
  { k:'value_durability', n:'Does the value last?',     q:'Is this still worth paying for in three years, or does it evaporate once the trend passes?', gate:true },
  { k:'incumbency',       n:'Does someone own it?',     q:'Is an incumbent already doing this well enough that a new entrant has no room?', gate:true },
  { k:'payer_solvency',   n:'Can the payer pay?',       q:'Does the person who feels the pain hold a budget, and is that budget solvent?', gate:true },
  { k:'distribution',     n:'Can you reach them?',      q:'Is there a route to these buyers that does not require money you do not have?', gate:true },
  { k:'legality',         n:'Is it legal to sell?',     q:'Does anything about this need a licence, a registration, or a regulator’s permission?', gate:true },
  { k:'price_comparables',n:'What do people pay now?',  q:'What are buyers already paying for the nearest thing, according to a page you can open?', gate:false },
];

/* Per-pack editorial. This is CMS content — the operator writes it, not the
   engine — which is exactly why it lives in the data file and not in a
   template. `notFor` is the rarest section on any competing product page
   (one seller in ten had it) and the cheapest disqualifier for a bad-fit
   buyer, who is the most expensive refund you can take. */
export const PACK_DETAIL = {
  'AV-30': {
    forWhom:'An operations or platform lead who already owns the dependency list and needs the argument, not the data.',
    notFor:'Anyone looking for a scanner. This is the market case for selling one, not the tool itself.',
    opens:'Dependency abandonment is measurable from public registries, so the pain is observable rather than asserted.',
  },
  'NR-38': {
    forWhom:'A founder with a route into small venues or hospitality already — a supplier, an installer, a trade body.',
    notFor:'A cold start with no way into the trade. Distribution is the thinnest of this pack’s seven checks.',
    opens:'The obligation is statutory, so the payer is identifiable and the deadline is not ours to invent.',
  },
  'RO-34': {
    forWhom:'A surveyor, contractor or proptech operator who can already get on site.',
    notFor:'A pure software team. The margin here sits with whoever holds the site access.',
    opens:'The incumbent check is the interesting one: the field is crowded but the crowd is regional.',
  },
  'SC-40': {
    forWhom:'Someone selling into regulated weighing or metrology, or adjacent to trading standards.',
    notFor:'Anyone who needs a large market. This is a narrow, durable, defensible one.',
    opens:'Value durability is unusually strong: the obligation predates the internet and has outlived every trend since.',
  },
  'CC-28': {
    forWhom:'A cold-chain, pharmacy or food-safety operator with an existing compliance relationship.',
    notFor:'A consumer play. The solvent payer here is an institution, not a household.',
    opens:'Payer solvency is the strongest check in the pack, and it is the one that kills most ideas.',
  },
  'RD-23': {
    forWhom:'A bookkeeper, accountant or fractional finance lead who wants a productised line.',
    notFor:'Anyone hoping to avoid the profession. The distribution route runs through practitioners.',
    opens:'The pain is documented in practitioners’ own public complaints, which is the strongest form this check takes.',
  },
};

/* The publisher identity block. Fogg et al. (CHI 2001, N=1,410) measured a
   physical address at +1.86 and a phone number at +1.71 on a −3..+3
   credibility scale — the two largest single wins available to a seller
   nobody has heard of, and both cheaper than any amount of design.

   These are DELIBERATELY unset. Inventing a business address to make a demo
   look finished is the exact class of thing this programme exists to stop.
   The layout reserves the slot; the gate below refuses to launch without it. */
export const PUBLISHER = {
  legalName: null,   // required before launch
  address:   null,   // required before launch — Fogg +1.86
  phone:     null,   // required before launch — Fogg +1.71
  email:     'hello@mumchimp.com',
  company:   null,   // registered number, required before launch
};
