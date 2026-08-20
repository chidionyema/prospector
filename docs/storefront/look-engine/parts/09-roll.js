/* ===========================================================================
   THE ELEVENTH LOOK — criterion C35, and the only honest proof of it.

   The founder's ask was never ten looks: "the zenith of it is to generate as many as you
   want". Ten hand-built looks cannot demonstrate that, however good they are, because the
   proof of a generator is a look NOBODY DESIGNED that is nonetheless whole — contrast-fitted,
   structurally complete, and indistinguishable in kind from the ten.

   So a look is four rolls and nothing else:
     seed      -> PALETTE.randomSeed, the fuzz gate's own generator (one generator, not two)
     switches  -> a value per structural axis, from the SWITCHES catalogue below
     type      -> a display face, a body face and a mono, with the metrics that face wants
     form      -> radius, rule weights, density, shadow

   Everything downstream already refuses bad input: applyLook runs the contrast audit and
   REFUSES a look that fails it, so a rolled look cannot reach the screen inaccessible. This
   file therefore states RANGES, never results.
   =========================================================================== */

/* The structural axes. This is the catalogue the CSS implements and gate A42 checks BOTH
   ways: every value here needs a rule, and every rule needs a value here. A switch nobody
   implemented does nothing, silently, forever — which is the failure mode of a look system
   that grew by copying. `d` is the default, present so the roll can decline an axis. */
const SWITCHES = {
  masthead:     { d: 'plain',    v: ['centred'],              p: 0.4 },
  mastheadRule: { d: 'single',   v: ['double'],               p: 0.3 },
  wordmark:     { d: 'plain',    v: ['sheet'],                p: 0.3 },
  readout:      { d: 'plain',    v: ['boxed'],                p: 0.35 },
  plateEdge:    { d: 'plain',    v: ['underline', 'capped'],  p: 0.45 },
  nav:          { d: 'plain',    v: ['filed'],                p: 0.3 },
  sectionHead:  { d: 'plain',    v: ['ruled'],                p: 0.35 },
  dropcap:      { d: 'off',      v: ['on'],                   p: 0.3 },
  figureMarks:  { d: 'plain',    v: ['corners'],              p: 0.3 },
  headlineCase: { d: 'sentence', v: ['upper'],                p: 0.25 },
  panel:        { d: 'raised',   v: ['flat'],                 p: 0.35 },
};

/* The faces, with the metrics each one actually needs. A didone at 0.99 leading is right and
   the same leading on a grotesque is wrong, so tracking and leading are properties of the
   FACE, not free numbers the roll invents. `f` is the family, used for the one pairing rule
   below; `w` are the weights this face has (Archivo Black has exactly one). */
const FACES = {
  display: [
    { f: 'Bodoni Moda',         n: "'Bodoni Moda', Didot, Georgia, serif",                 g: 'serif', w: ['600', '700', '900'], tr: '-0.025em', ld: '0.99' },
    { f: 'Fraunces',            n: "'Fraunces', Georgia, serif",                           g: 'serif', w: ['500', '600', '700'], tr: '-0.015em', ld: '1.02' },
    { f: 'EB Garamond',         n: "'EB Garamond', Garamond, Georgia, serif",              g: 'serif', w: ['500', '600', '700'], tr: '-0.005em', ld: '1.06' },
    { f: 'Newsreader',          n: "'Newsreader', Georgia, serif",                         g: 'serif', w: ['400', '500', '600'], tr: '-0.012em', ld: '1.04' },
    { f: 'Archivo Black',       n: "'Archivo Black', 'Arial Black', sans-serif",           g: 'sans',  w: ['400'],               tr: '-0.02em',  ld: '0.95' },
    { f: 'Archivo',             n: "'Archivo', 'Helvetica Neue', Arial, sans-serif",       g: 'sans',  w: ['600', '700', '800'], tr: '-0.018em', ld: '1.0'  },
    { f: 'Chivo',               n: "'Chivo', 'Helvetica Neue', Arial, sans-serif",         g: 'sans',  w: ['600', '700', '900'], tr: '-0.02em',  ld: '1.0'  },
    { f: 'Bricolage Grotesque', n: "'Bricolage Grotesque', 'Helvetica Neue', sans-serif",  g: 'sans',  w: ['500', '600', '800'], tr: '-0.02em',  ld: '0.98' },
    { f: 'Courier Prime',       n: "'Courier Prime', ui-monospace, Menlo, monospace",      g: 'mono',  w: ['400', '700'],        tr: '-0.01em',  ld: '1.08' },
  ],
  body: [
    { f: 'Source Serif 4', n: "'Source Serif 4', Georgia, serif",        g: 'serif', w: ['400'], ld: '1.58' },
    { f: 'EB Garamond',    n: "'EB Garamond', Garamond, Georgia, serif", g: 'serif', w: ['400'], ld: '1.62' },
    { f: 'Newsreader',     n: "'Newsreader', Georgia, serif",            g: 'serif', w: ['400'], ld: '1.6'  },
    { f: 'Public Sans',    n: "'Public Sans', system-ui, sans-serif",    g: 'sans',  w: ['400'], ld: '1.6'  },
    { f: 'Cabin',          n: "'Cabin', system-ui, sans-serif",          g: 'sans',  w: ['400'], ld: '1.62' },
  ],
  mono: [
    { f: 'Spline Sans Mono', n: "'Spline Sans Mono', ui-monospace, Menlo, monospace" },
    { f: 'IBM Plex Mono',    n: "'IBM Plex Mono', ui-monospace, Menlo, monospace"    },
    { f: 'Martian Mono',     n: "'Martian Mono', ui-monospace, Menlo, monospace"     },
    { f: 'Sometype Mono',    n: "'Sometype Mono', ui-monospace, Menlo, monospace"    },
    { f: 'Courier Prime',    n: "'Courier Prime', ui-monospace, Menlo, monospace"    },
  ],
};

/* One pairing rule, and it is the only one worth machine-enforcing: the display and the body
   must not be the SAME FAMILY. Bodoni over Source Serif is two serifs and it is the best
   pairing we ship, so "never two serifs" would forbid The Ledger. EB Garamond over EB
   Garamond is not a pairing at all — it is one face doing two jobs, which reads as an
   unfinished design rather than a quiet one. */
const samePair = (d, b) => d.f === b.f;

/* Deterministic PRNG, so a rolled look can be REPRODUCED from its number alone. A look you
   cannot get back is a look you cannot file a bug against. */
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function rollLook(n) {
  const rnd = mulberry32(n);
  const of = (a) => a[Math.floor(rnd() * a.length)];
  const num = (lo, hi, dp) => (lo + rnd() * (hi - lo)).toFixed(dp);

  const d = of(FACES.display);
  let b = of(FACES.body);
  for (let i = 0; i < 8 && samePair(d, b); i++) b = of(FACES.body);
  const m = of(FACES.mono);

  const switches = {};
  for (const [k, ax] of Object.entries(SWITCHES)) if (rnd() < ax.p) switches[k] = of(ax.v);

  /* Radius is a RUNG, not a number: 4.7px is not a decision anybody made, and the gap between
     0 and 3 is the whole difference between a broadsheet and a console. Same argument as the
     pricing ladder — a continuous knob invites a value nobody chose. */
  const radius = of(['0px', '0px', '2px', '3px', '6px', '10px']);
  const shadow = of([
    'none', 'none',
    '0 1px 2px rgba(13,16,20,.06), 0 10px 26px -14px rgba(13,16,20,.2)',
    '0 1px 0 rgba(13,16,20,.05)',
  ]);

  return {
    id: `roll-${n}`,
    name: `Roll ${n}`,
    tagline: `Generated, not designed: seed ${n}. ${d.f} over ${b.f}, ${Object.keys(switches).length} structural switch${Object.keys(switches).length === 1 ? '' : 'es'}.`,
    rolled: true,
    plate: of(Object.keys(PLATES)),
    treatment: of(Object.keys(TREATMENTS)),
    switches,
    form: {
      radius,
      ruleW: of(['1px', '1px', '2px']),
      ruleWStrong: of(['1px', '2px', '3px']),
      sp: num(0.9, 1.1, 2),
      shadow,
    },
    type: {
      display: d.n, body: b.n, mono: m.n,
      displayW: of(d.w), track: d.tr, lead: d.ld,
      italic: rnd() < 0.3 ? 'italic' : 'normal',
      bodyW: of(b.w), bodyLead: b.ld,
      labelCase: of(['uppercase', 'uppercase', 'none']),
      labelTrack: of(['0.16em', '0.12em', '0.08em', '0.02em']),
      labelW: of(['500', '600', '700']),
      labelSize: of(['0.6875rem', '0.6875rem', '0.75rem']),
    },
    seed: PALETTE.randomSeed(rnd),
  };
}
