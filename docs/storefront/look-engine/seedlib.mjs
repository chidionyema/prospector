// @ledger read-only | (imported) | Loads the palette module and turns a hand-picked palette back into a seed.
/* THE SEED LIBRARY. Two tools need the same inversion — the report (seed.mjs) and the
 * rewrite (convert.mjs) — and an inversion that exists twice is a rewrite that can
 * disagree with the report that approved it. So it lives here once.
 *
 * Everything it knows about colour comes from parts/08-palette.js, loaded as text and
 * evaluated. That is deliberate: the module ships to the browser inside one <script>,
 * so it cannot be an ES module, and a second copy for node would be the same defect
 * one level up.
 */
import { readFileSync } from 'node:fs';

const strip = (s) => s.replace(/\nif \(typeof module[\s\S]*$/, '');
export const PALETTE = new Function(
  strip(readFileSync('parts/08-palette.js', 'utf8')) + '\n;return PALETTE;')();
export const LOOKS = new Function(
  readFileSync('parts/03-looks.js', 'utf8') + '\n;return LOOKS;')();

const { hexToOklch, contrast } = PALETTE;
const r3 = (n) => Math.round(n * 1000) / 1000;
const r1 = (n) => Math.round(n * 10) / 10;

/* Hue is meaningless at zero chroma — a neutral grey's hue is whatever rounding left
   behind — so a ratio against it is a divide-by-nothing. Floor it. */
const CFLOOR = 0.0015;

export function seedOf(look) {
  const L = look.light, D = look.dark;
  const [Lg, Cg, Hg] = hexToOklch(L.ground);
  const [Ld, Cd, Hd] = hexToOklch(D.ground);
  const [Li, Ci, Hi] = hexToOklch(L.ink);
  const [LiD, CiD, HiD] = hexToOklch(D.ink);
  const [LsD] = hexToOklch(D.surface);
  const [Ls2D] = hexToOklch(D.surface2);
  const [LhD] = hexToOklch(D.hair);
  const [L2] = hexToOklch(L.ink2), [L2D] = hexToOklch(D.ink2);
  const [L3] = hexToOklch(L.ink3), [L3D] = hexToOklch(D.ink3);
  const [Lacc, Ca, Ha] = hexToOklch(L.accent);
  const [LaccD, Cad] = hexToOklch(D.accent);
  const [Lgood, , Hgood] = hexToOklch(L.good);
  const [LgoodD] = hexToOklch(D.good);
  const [Lbad, , Hbad] = hexToOklch(L.bad);
  const [LbadD] = hexToOklch(D.bad);
  const [Ls] = hexToOklch(L.surface);
  const [Ls2] = hexToOklch(L.surface2);
  const [Lh] = hexToOklch(L.hair);
  const base = Math.max(Cg, CFLOOR);

  /* A dark ground is not obliged to be the light ground turned down. Six of the ten
     looks keep the same hue and four do not, so the seed states it only when the dark
     ground has enough chroma for its hue to mean anything AND it actually differs. */
  const darkHueDiffers = Cd > 0.004 &&
    Math.min(Math.abs(Hd - Hg), 360 - Math.abs(Hd - Hg)) > 8;

  /* Where the filled accent gets its colour, per theme: the ink, the accent, or a
     colour of its own. Read from the palette rather than assumed, because all three
     occur and two looks change their answer between themes. */
  const fillOf = (t, ink, accent) => {
    if (contrast(t.accentFill, ink) < 1.1) return { from: 'ink' };
    if (contrast(t.accentFill, accent) < 1.05) return { from: 'accent' };
    const [Lf, Cf, Hf] = hexToOklch(t.accentFill);
    return { from: 'own', L: r3(Lf), C: r3(Cf), H: r1(Hf) };
  };
  const fL = fillOf(L, L.ink, L.accent), fD = fillOf(D, D.ink, D.accent);
  const own = (f, sfx) => f.from === 'own'
    ? { ['fillL' + sfx]: f.L, ['fillChroma' + sfx]: f.C, ['fillHue' + sfx]: f.H } : {};

  return {
    hue: r1(Hg), chroma: r3(Cg),
    ...(darkHueDiffers ? { hueDark: r1(Hd) } : {}),
    groundL: r3(Lg), darkL: r3(Ld),
    darkChroma: r3(Math.max(Cd, 0) / base),
    inkShift: r1(((Hi - Hg + 540) % 360) - 180),
    /* Measured against the DARK ground's own hue, not the light one. Otherwise a look
       that turns its ground blue at night gets the daytime offset applied to the new
       hue and lands 160 degrees away — which is what The Almanac's dark ink2 did. */
    inkShiftDark: r1(((HiD - (darkHueDiffers ? Hd : Hg) + 540) % 360) - 180),
    inkChroma: r3(Ci / base), inkChromaDark: r3(CiD / base),
    inkL: r3(Li), inkLDark: r3(LiD),
    ink2L: r3(L2), ink2LDark: r3(L2D), ink3L: r3(L3), ink3LDark: r3(L3D),
    accentHue: r1(Ha), accentChroma: r3(Ca),
    darkAccentChroma: r3(Cad / Math.max(Ca, CFLOOR)),
    accentL: r3(Lacc), accentLDark: r3(LaccD),
    /* The three steps away from the ground. Light subtracts for surface2 and hair,
       dark adds — the sign lives in THEME, so what the seed states is the SIZE, and
       each theme states its own. The Quiet's dark hairline is a fifth of a lightness
       step from its ground and its light one is nearly half; one number for both put
       a mid-grey rule on a near-black page. */
    /* Stated only when the heavy rule is NOT the ink. Nine looks copy the ink and
       would be storing a number that means nothing; The Quiet does not, and without
       this its rule converts to near-black — a 0.42 lightness move, which is the
       whole difference between that look and every other one. */
    ...(contrast(L.hairStrong, L.ink) > 1.05 ? { hairStrongL: r3(hexToOklch(L.hairStrong)[0]) } : {}),
    ...(contrast(D.hairStrong, D.ink) > 1.05 ? { hairStrongLDark: r3(hexToOklch(D.hairStrong)[0]) } : {}),
    lift: r3(Math.max(0, Ls - Lg)), sunk: r3(Math.max(0, Lg - Ls2)),
    hairStep: r3(Math.max(0, Lg - Lh)),
    liftDark: r3(Math.max(0, LsD - Ld)), sunkDark: r3(Math.max(0, Ls2D - Ld)),
    hairStepDark: r3(Math.max(0, LhD - Ld)),
    goodHue: r1(Hgood), badHue: r1(Hbad),
    goodL: r3(Lgood), goodLDark: r3(LgoodD),
    badL: r3(Lbad), badLDark: r3(LbadD),
    fillFrom: fL.from, fillFromDark: fD.from,
    ...own(fL, ''), ...own(fD, 'Dark'),
    contrast: 1,
  };
}

