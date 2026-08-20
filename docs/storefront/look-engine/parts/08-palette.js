/* ===========================================================================
   THE PALETTE GENERATOR — criterion C35, gates A43 and A44.

   A look does not OWN colours. It owns a SEED: about a dozen perceptual
   decisions. This file turns that seed into the sixteen tokens the component
   layer consumes, in both themes, and then FITS the result against the
   contrast table until every pair passes.

   Why this exists at all. The first ten looks carried 32 hand-picked hex
   values each — 320 decisions — and when a contrast gate was finally pointed
   at them it found 19 failures. Hand-picking was not merely slow, it was
   WRONG, and only a machine noticed. At a hundred looks it is not a choice.

   The important property is the last step, not the first: FIT runs before a
   palette is ever returned, so a generated look cannot be inaccessible. That
   is the difference between a gate that REFUSES bad output and a generator
   that is incapable of emitting it. The operator moves a hue slider; the
   floor holds itself up.

   Working space is OKLCH throughout, for one concrete reason rather than
   fashion: it is perceptually uniform in LIGHTNESS, so "make this text one
   step darker" is one subtraction that behaves identically at every hue. The
   same move in HSL darkens yellow and blue by visibly different amounts,
   which is exactly why HSL palettes need hand-correction per hue.
   =========================================================================== */

const PALETTE = (function () {

  /* --- sRGB transfer function. IEC 61966-2-1. The 0.0031308 knee is the
     spec's, not a rounding of 0.003 — using a rounded knee shifts the darkest
     three or four 8-bit steps, which is precisely where UI hairlines live. */
  const lin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const gam = (c) => (c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);

  /* --- OKLab <-> linear sRGB. Bjorn Ottosson, 2020. The matrices are his
     published values at full precision; truncating them to four places moves
     near-neutral greys by a visible amount because the LMS cube root
     amplifies small errors at low chroma. */
  function oklabToLinear(L, a, b) {
    const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
    const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
    const s_ = L - 0.0894841775 * a - 1.2914855480 * b;
    const l = l_ * l_ * l_, m = m_ * m_ * m_, s = s_ * s_ * s_;
    return [
      +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    ];
  }
  function linearToOklab(r, g, b) {
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [
      0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
      1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
      0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    ];
  }

  const EPS = 1e-6;
  const inGamut = (rgb) => rgb.every((c) => c >= -EPS && c <= 1 + EPS);
  const clip = (rgb) => rgb.map((c) => Math.min(1, Math.max(0, c)));

  /* --- Gamut mapping, CSS Color 4 section 14 ("CSS gamut mapping algorithm", CRD 6 Aug 2026).
     Reduce chroma by binary search, and stop early once simple clipping lands
     within deltaEOK 0.02 of the searched colour — the spec's own tolerance.
     The naive alternative, clipping RGB directly, shifts HUE: clamping a
     too-saturated blue drags it toward purple, which silently breaks the one
     property a look's identity rests on. */
  function oklchToHex(L, C, H) {
    L = Math.min(1, Math.max(0, L));
    if (L >= 1 - EPS) return '#FFFFFF';
    if (L <= EPS) return '#000000';
    const at = (c) => {
      const h = (H * Math.PI) / 180;
      return oklabToLinear(L, c * Math.cos(h), c * Math.sin(h));
    };
    let rgb = at(C);
    if (!inGamut(rgb)) {
      let lo = 0, hi = C;
      while (hi - lo > 1e-5) {
        const mid = (lo + hi) / 2;
        const cur = at(mid);
        if (inGamut(cur)) { lo = mid; continue; }
        const cl = clip(cur);
        const a = linearToOklab(cl[0], cl[1], cl[2]);
        const b = linearToOklab(cur[0], cur[1], cur[2]);
        const dE = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
        if (dE < 0.02) return toHex(cl);
        hi = mid;
      }
      rgb = at(lo);
    }
    return toHex(clip(rgb));
  }

  function toHex(rgbLinear) {
    const h = rgbLinear
      .map((c) => Math.round(Math.min(1, Math.max(0, gam(c))) * 255).toString(16).padStart(2, '0'))
      .join('');
    return ('#' + h).toUpperCase();
  }

  function hexToOklch(hex) {
    const n = parseInt(hex.slice(1), 16);
    const r = lin(((n >> 16) & 255) / 255), g = lin(((n >> 8) & 255) / 255), b = lin((n & 255) / 255);
    const [L, A, B] = linearToOklab(r, g, b);
    let H = (Math.atan2(B, A) * 180) / Math.PI;
    if (H < 0) H += 360;
    return [L, Math.hypot(A, B), H];
  }

  /* --- WCAG 2.2 contrast. Deliberately NOT the OKLCH lightness difference:
     the normative definition is relative luminance per WCAG SC 1.4.3, and a
     gate that grades against a different formula from the one the law names
     is a gate that can pass an illegal page. APCA is the successor but is
     still non-normative in 2026, so it is a second opinion, never the bar. */
  const relLum = (hex) => {
    const n = parseInt(hex.slice(1), 16);
    const r = lin(((n >> 16) & 255) / 255), g = lin(((n >> 8) & 255) / 255), b = lin((n & 255) / 255);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (a, b) => {
    const x = relLum(a), y = relLum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  };

  /* =========================================================================
     DERIVE — seed to sixteen tokens.

     Every number below is a RATIO or an OFFSET against the seed, never an
     absolute. That is what makes the seed the only thing an operator edits,
     and what makes a look survive being re-grounded from cream to charcoal
     without a second pass of hand-fixing.
     ========================================================================= */

  // Direction, stated per theme rather than derived from one clever sign.
  //
  // The first cut of this file tried to express both themes as one formula
  // with a flipped sign, and it was wrong in a way worth recording: light and
  // dark are NOT mirror images. In a light theme a raised card moves AWAY
  // from the text (toward white) while a recessed well moves TOWARD it. In a
  // dark theme BOTH move toward the text, because black is a floor you cannot
  // separate below. One sign cannot say that, so the table says it instead.
  //
  //   sSurface  raised card, relative to the ground
  //   sSurface2 recessed panel
  //   sHair     rules and borders
  //   toInk     from any background, the way legible text lies
  const THEME = {
    light: { inkL: 0.205, ink2L: 0.435, ink3L: 0.505, groundL: (s) => s.groundL,
             sSurface: +1, sSurface2: -1, sHair: -1, toInk: -1 },
    dark:  { inkL: 0.925, ink2L: 0.735, ink3L: 0.645, groundL: (s) => s.darkL,
             sSurface: +1, sSurface2: +1, sHair: +1, toInk: +1 },
  };

  function derive(seed, theme) {
    const T = THEME[theme];
    /* One accessor for every field a look may state twice. `pick('accentL')` reads
       `accentL` in light and `accentLDark` in dark, and undefined means "no opinion,
       use the derivation's own default". Both themes reading one value was the second
       source of drift when the ten shipped looks were regenerated from their own
       seeds: a look whose dark ground leans blue under a warm light ground came back
       warm in both, and the dark hair moved 162 hue degrees. Every step that is
       measured FROM the ground — the ink's hue offset, the card lift, the hairline
       step — reads through `pick`, because a step measured against a hue the dark
       theme does not use is not the same step. */
    const pick = (k) => seed[theme === 'dark' ? k + 'Dark' : k];
    const H = pick('hue') == null ? seed.hue : pick('hue');   // ground hue
    const Cg = theme === 'dark' ? seed.chroma * (seed.darkChroma || 1.35) : seed.chroma;
    const Lg = T.groundL(seed);

    // Ink hue may lean off the ground hue. A warm-grey page carrying cool-grey
    // text is a real printing effect (black ink on cream stock), and it is the
    // cheapest way to stop ten looks reading as ten tints of one grey.
    const Hi = (H + (pick('inkShift') || 0) + 360) % 360;
    const Ci = seed.chroma * (pick('inkChroma') || 1.6);

    // `lift` is whether a card rises off the page or sits flush. Zero is a
    // real choice, not a missing value: a broadsheet has no cards.
    const lift = pick('lift') == null ? 0.02 : pick('lift');
    const sunk = pick('sunk') == null ? 0.03 : pick('sunk');
    const hairStep = pick('hairStep') == null ? 0.1 : pick('hairStep');

    const ground   = oklchToHex(Lg, Cg, H);
    const surface  = oklchToHex(Lg + T.sSurface * lift, Cg * 0.75, H);
    const surface2 = oklchToHex(Lg + T.sSurface2 * sunk, Cg * 1.3, H);
    const hair     = oklchToHex(Lg + T.sHair * hairStep, Cg * 1.5, H);

    /* Ink lightness has a sensible default per theme and is still the operator's to
       state: The Signal's near-black navy sits 0.075 below the default, and that is a
       decision about ink density, not an accident. Stating `inkL` alone moves all
       three together, because ink2 and ink3 are the same ink at two dilutions; a look
       that dilutes further than the default says so with `ink2L`. */
    const inkL = pick('inkL') == null ? T.inkL : pick('inkL');
    const shift = inkL - T.inkL;
    const ink  = oklchToHex(inkL, Ci, Hi);
    const ink2 = oklchToHex(pick('ink2L') == null ? T.ink2L + shift : pick('ink2L'), Ci * 0.85, Hi);
    const ink3 = oklchToHex(pick('ink3L') == null ? T.ink3L + shift : pick('ink3L'), Ci * 0.8, Hi);

    /* The accent's lightness is the OPERATOR'S decision, and legibility is the
       machine's. `hold` is where those two meet: it keeps the lightness the seed
       asked for whenever that lightness clears the ground by the required ratio,
       and repairs it only when it does not.

       This used to call `fitAgainst` unconditionally, which sounds equivalent and
       is not. `fitAgainst` walks away from the ground until the ratio is MET and
       stops — it returns the palest legible accent, never a deep one. Measured
       2026-08-20 by regenerating the ten shipped looks from their own seeds: 61
       tokens moved, and the direction was the same every time. The Ledger's
       oxblood #7A1F1B came back as #A84A42, lighter by 0.141 in OKLCH L, because
       oxblood clears newsprint at 8.9:1 and the fitter only ever needed 4.5. Ten
       looks lost their accent to a floor that was doing exactly what it was told.

       A floor is not a target. Anything with no lightness in its seed still gets
       the old behaviour, so a hue-slider-only seed keeps working. */
    const Ha = seed.accentHue;
    const Ca = seed.accentChroma * (theme === 'dark' ? (seed.darkAccentChroma || 0.82) : 1);
    const wantA = 4.5 * (seed.contrast || 1);
    const pickL = pick;
    const hold = (Lwant, C, H, min) => {
      if (Lwant == null) return fitAgainst(ground, H, C, T.toInk, min);
      const c = oklchToHex(Lwant, C, H);
      return contrast(c, ground) >= min ? c : fitAgainst(ground, H, C, T.toInk, min);
    };
    const accent = hold(pickL('accentL'), Ca, Ha, wantA);

    /* A filled accent (a button) has the OPPOSITE relationship: the label sits ON
       the fill, so the label is solved against the fill, not the reverse. The fill
       is therefore under no obligation to the ground and takes the seed's
       lightness as given. Three cases, because all three exist in the ten looks:
       the fill is the ink (a black button on a broadsheet), the fill is its own
       colour (The Field Guide's bottle green), or the fill is just the accent — and
       which of the three it is can differ BETWEEN THEMES. The Signal fills with ink on
       white and with its coral accent on black; one `fillIsInk` flag for both themes
       put a pale blue where the coral was, 133 hue degrees out. */
    const fillFrom = (pick('fillFrom') || (seed.fillIsInk ? 'ink' : 'accent'));
    const accentFill = fillFrom === 'ink' ? ink
      : fillFrom === 'own'
        ? oklchToHex(pick('fillL') == null ? (theme === 'dark' ? 0.7 : 0.35) : pick('fillL'),
                     pick('fillChroma') == null ? Ca : pick('fillChroma'),
                     pick('fillHue') == null ? Ha : pick('fillHue'))
        : accent;
    const accentInk  = pickOn(accentFill, ground, surface);

    // Semantic colours are a SEPARATE channel from the accent, per the design
    // brief: a look whose accent is already green must still be able to say
    // "this one died". They take the seed's chroma so they belong to the same
    // palette, but never its hue.
    const good = hold(pickL('goodL'), Ca * 0.75, seed.goodHue == null ? 152 : seed.goodHue, 4.5);
    const bad  = hold(pickL('badL'),  Ca * 0.95, seed.badHue  == null ? 27  : seed.badHue,  4.5);

    // The heavy rule is the ink in nine looks out of ten, and in The Quiet it is a
    // mid-grey that clears the ground at 3:1 and nothing more. So it is a DECISION,
    // stated only when it differs; absent, it mirrors the ink and keeps mirroring it
    // through the fit. It carries ink3's chroma because a rule reads as a lighter
    // weight of the same ink, never as a second colour.
    const hsL = pick('hairStrongL');
    const hairStrong = hsL == null ? ink : oklchToHex(hsL, Ci * 0.8, Hi);

    return {
      ground, surface, surface2, hair, hairStrong,
      ink, ink2, ink3,
      accent, accentFill, accentInk,
      good, bad,
      plateBg: surface2, plateInk: ink, plateAccent: accent,
    };
  }

  /* SOLVE, VERIFY, REPAIR. Walk lightness away from a background until the
     ratio is met, at steps of 0.004 in OKLCH L — below the perceptual
     threshold, so the result is the LEAST change that satisfies the
     requirement and the palette gives up only what it must.

     The repair ladder is the part that matters, and it was missing. The first
     cut ran out of lightness and RETURNED THE FAILING COLOUR, which makes the
     claim at the top of this file false: a generated look could ship a pair
     that does not pass. Two facts from the measurement (research/colour.md)
     say what to do instead. First, contrast is measured on the GAMUT-MAPPED
     value, never the requested one — the same OKLCH triple can swing 6.37 in
     ratio across the mapping, so `oklchToHex` runs inside the loop rather
     than after it. Second, at OKLCH L = 0.5 the luminance of a hue sweep
     spans 1.40x, so lightness alone is not a contrast handle: when L runs out
     it is usually the CHROMA that is costing the ratio, and dropping it buys
     back what walking L could not.

     AA is always reachable, so the ladder terminates: black or white clears
     4.5:1 against any background that itself passes. AAA at 7:1 is NOT always
     reachable — it is impossible for any background whose CIE L* lies between
     37.8 and 61.7 — so a caller asking 7:1 of a mid-grey ground gets the best
     available colour and the FIT gate reports the miss rather than this
     function pretending. */
  function fitAgainst(bg, H, C, toInk, want) {
    const bgL = hexToOklch(bg)[0];

    const solve = (chroma) => {
      let L = bgL + toInk * 0.30;
      for (let i = 0; i < 300; i++) {
        const hex = oklchToHex(L, chroma, H);       // mapped, then measured
        if (contrast(hex, bg) >= want) return hex;
        L += toInk * 0.004;
        if (L < 0 || L > 1) return null;
      }
      return null;
    };

    let hit = solve(C);                              // 1. the chroma asked for
    if (hit) return hit;
    for (let c = C * 0.8; c > 0.005; c *= 0.8) {     // 2. buy ratio with chroma
      hit = solve(c);
      if (hit) return hit;
    }
    hit = solve(0);                                  // 3. neutral of this hue
    if (hit) return hit;
    return contrast('#FFFFFF', bg) >= contrast('#000000', bg) ? '#FFFFFF' : '#000000';   // 4. the floor
  }

  /* Which of two candidates sits legibly on a fill. Not "white if dark":
     that rule fails on mid-lightness accents, where BOTH options are poor and
     the honest answer is the better of the two plus a note that the seed's
     accent chroma is too high to fill with. */
  function pickOn(fill, a, b) {
    return contrast(fill, a) >= contrast(fill, b) ? a : b;
  }

  /* =========================================================================
     FIT — gate A44. The derived palette is checked against the REAL pair
     table and any failing foreground is walked until it passes.

     One subtlety that cost a whole repair pass when it was missing: a token
     may appear against SEVERAL backgrounds, and solving it against the first
     one leaves it failing the darkest. So every requirement is collected
     first, and the token is solved once against the hardest of them.
     ========================================================================= */
  /* Tokens that are conventionally a copy of another token. Which of them actually IS
     a copy is measured per look, never assumed. */
  const MIRRORS = [['hairStrong', 'ink'], ['plateInk', 'ink'],
                   ['plateAccent', 'accent'], ['plateBg', 'surface2']];

  function fit(tokens, pairs, theme) {
    const out = Object.assign({}, tokens);
    const toInk = THEME[theme].toInk;

    /* Collect EVERY requirement per token, not the hardest one.
   
       Picking the hardest is what this did before, and it was wrong in a way that only
       showed up once seeds could state their own ink lightness. "Hardest" was scored by
       the ratio the token achieves TODAY, and that is a proxy: a near-white ink3 sits at
       1.02 against the ground and 1.06 against the slightly darker surface2, so the
       ground scored as the harder of the two. The fitter then walked ink3 down until it
       cleared the GROUND at exactly 4.5 and stopped — leaving 4.30 against the darker
       surface2, which is the background that was actually binding. Measured 2026-08-20:
       13 failing pairs in 52,000, every one of them ink3 on surface2.
   
       The binding constraint is not the worst current ratio, and there is no cheap way
       to name it in advance, so nothing here tries: every requirement is kept and each
       candidate is scored against all of them at once. */
    const byFg = new Map();
    for (const p of pairs) {
      if (!(p.fg in out) || !(p.bg in out)) continue;
      if (!byFg.has(p.fg)) byFg.set(p.fg, []);
      byFg.get(p.fg).push(p);
    }

    /* A candidate is judged by the WORST of its requirements, and the winner is the one
       whose worst is best. Two directions are tried for each, because "away from the
       ground" is not always where a legible colour lives: a label sitting on a
       mid-lightness button fill can be unreachable in the ink direction and comfortable
       in the other. Measured 2026-08-20 on a #736F76 fill — black reaches 4.264:1 and
       white reaches 4.925:1, so the only legible label is the lighter one and a fixed
       direction can never find it. Ties go to the colour that travelled least, so a
       palette still gives up only what it must. */
    const margin = (hex, reqs) =>
      reqs.reduce((m, r) => Math.min(m, contrast(hex, out[r.bg]) / r.min), Infinity);

    for (const [fg, reqs] of byFg) {
      if (margin(out[fg], reqs) >= 1) continue;
      const [L0, C0, H0] = hexToOklch(out[fg]);
      const cands = [out[fg]];
      for (const r of reqs) {
        cands.push(fitAgainst(out[r.bg], H0, C0, toInk, r.min));
        cands.push(fitAgainst(out[r.bg], H0, C0, -toInk, r.min));
      }
      let best = out[fg], bestM = margin(out[fg], reqs), bestTravel = 0;
      for (const c of cands) {
        const m = margin(c, reqs);
        const travel = Math.abs(hexToOklch(c)[0] - L0);
        if (m > bestM + 1e-9 || (m >= bestM - 1e-9 && m >= 1 && travel < bestTravel)) {
          best = c; bestM = m; bestTravel = travel;
        }
      }
      out[fg] = best;
    }

    /* Re-mirror after any move — but only the tokens that WERE mirrors when the fit
       started. Assigning `out.hairStrong = out.ink` unconditionally is the same proxy
       defect as the one above, one field along: it treats "usually a copy of the ink"
       as "always a copy of the ink", and it silently overwrote The Quiet's deliberate
       mid-grey rule with near-black. A mirror is a token that came in equal; a token
       that came in different is a decision, and the fit repairs it on its own. */
    for (const [a, b] of MIRRORS) if (tokens[a] === tokens[b]) out[a] = out[b];
    return out;
  }


  /* THE PAIR TABLE — what actually sits on what in the built page, and the ratio each
     pairing owes under WCAG 2.2: 4.5 for body text, 3.0 for large display text and for
     non-text edges (rules, focus rings, plate marks), and a floor of 1.2 for a hairline,
     which is a visibility requirement rather than a WCAG one.

     There were THREE copies of this table before 2026-08-20 — one here, one in
     palette-test.mjs, one in the engine — and they had already drifted apart: the
     engine's carried 19 pairs and this one 13. That is the failure mode a shared
     contract exists to prevent, and it is not hypothetical here. The fitter was proved
     against 13 pairs while the engine REFUSES a look on 19, so a generated palette
     could have been fitted, passed its own gate, and then been rejected at apply time
     by the page it was generated for.

     A pair belongs in this table the moment a rule puts those two tokens together. */
  const PAIRS = [
    { fg: 'ink',   bg: 'ground',   min: 4.5, what: 'body text on the page' },
    { fg: 'ink',   bg: 'surface',  min: 4.5, what: 'body text on a card' },
    { fg: 'ink',   bg: 'surface2', min: 4.5, what: 'body text on a panel' },
    { fg: 'ink2',  bg: 'ground',   min: 4.5, what: 'secondary text on the page' },
    { fg: 'ink2',  bg: 'surface',  min: 4.5, what: 'secondary text on a card' },
    { fg: 'ink2',  bg: 'surface2', min: 4.5, what: 'secondary text on a panel' },
    { fg: 'ink3',  bg: 'ground',   min: 4.5, what: 'captions and notes' },
    { fg: 'ink3',  bg: 'surface',  min: 4.5, what: 'captions on a card' },
    { fg: 'ink3',  bg: 'surface2', min: 4.5, what: 'labels on a panel bar' },
    { fg: 'accent', bg: 'ground',   min: 4.5, what: 'the accent as text' },
    { fg: 'accent', bg: 'surface',  min: 4.5, what: 'the accent on a card' },
    { fg: 'accent', bg: 'surface2', min: 4.5, what: 'the accent on a panel' },
    { fg: 'accentInk', bg: 'accentFill', min: 4.5, what: 'text inside the primary button' },
    { fg: 'good',  bg: 'ground',   min: 4.5, what: 'the survived label on the page' },
    { fg: 'good',  bg: 'surface',  min: 4.5, what: 'the survived label' },
    { fg: 'bad',   bg: 'ground',   min: 4.5, what: 'the killed label on the page' },
    { fg: 'bad',   bg: 'surface',  min: 4.5, what: 'the killed label' },
    { fg: 'hairStrong', bg: 'ground', min: 3.0, what: 'the heavy rule' },
    { fg: 'plateAccent', bg: 'plateBg', min: 3.0, what: 'the lit marks in a graphic' },
    { fg: 'hair',  bg: 'ground',   min: 1.2, what: 'the hairline rule' },
  ];

  /** The whole public contract: a seed in, a fitted two-theme palette out. */
  function build(seed, pairs) {
    const table = pairs || PAIRS;
    return {
      light: fit(derive(seed, 'light'), table, 'light'),
      dark:  fit(derive(seed, 'dark'),  table, 'dark'),
    };
  }


  /* A RANDOM SEED, drawn from the same ranges the fuzz gate uses — because it IS the fuzz
     gate's generator. It lived in palette-test.mjs until 2026-08-20, which meant the page
     could roll a look through code that 80,000 assertions had never touched, and the gate
     could pass on a distribution the page never produced. Two generators for one class is
     the defect this file exists to argue against; there is one now, and both callers use it.

     The lightness fields are drawn across the whole range on purpose: an operator is entitled
     to ask for a mid-grey accent on a mid-grey ground, and the only acceptable answer is a
     legible colour, never a failing pair. Half the seeds state a lightness and half leave it
     to the derivation, so both paths are exercised. */
  function randomSeed(rnd) {
    const pick = (lo, hi) => lo + rnd() * (hi - lo);
    const maybe = (v) => (rnd() < 0.5 ? v : undefined);
    const of = (a) => a[Math.floor(rnd() * a.length)];
    return {
      hue: pick(0, 360), chroma: pick(0, 0.03), groundL: pick(0.86, 0.99), darkL: pick(0.08, 0.22),
      hueDark: maybe(pick(0, 360)),
      inkShift: pick(-40, 40), inkChroma: pick(0.5, 3), darkChroma: pick(1, 2),
      inkShiftDark: maybe(pick(-40, 40)), inkChromaDark: maybe(pick(0.5, 3)),
      inkL: maybe(pick(0.1, 0.6)), inkLDark: maybe(pick(0.6, 0.98)),
      ink2L: maybe(pick(0.3, 0.7)), ink3L: maybe(pick(0.3, 0.7)),
      ink2LDark: maybe(pick(0.5, 0.9)), ink3LDark: maybe(pick(0.5, 0.9)),
      accentHue: pick(0, 360), accentChroma: pick(0.05, 0.30), darkAccentChroma: pick(0.6, 1),
      accentL: maybe(pick(0.15, 0.95)), accentLDark: maybe(pick(0.15, 0.95)),
      goodL: maybe(pick(0.15, 0.95)), badL: maybe(pick(0.15, 0.95)),
      goodLDark: maybe(pick(0.15, 0.95)), badLDark: maybe(pick(0.15, 0.95)),
      lift: pick(0, 0.05), sunk: pick(0, 0.05), hairStep: pick(0.04, 0.18),
      liftDark: maybe(pick(0, 0.05)), sunkDark: maybe(pick(0, 0.05)), hairStepDark: maybe(pick(0.04, 0.18)),
      hairStrongL: maybe(pick(0.1, 0.9)), hairStrongLDark: maybe(pick(0.1, 0.9)),
      fillFrom: of(['accent', 'ink', 'own']), fillFromDark: of(['accent', 'ink', 'own']),
      fillL: pick(0.15, 0.95), fillLDark: pick(0.15, 0.95),
      fillHue: pick(0, 360), fillChroma: pick(0, 0.25),
      goodHue: pick(120, 175), badHue: pick(10, 45), contrast: pick(1, 1.2),
    };
  }

  return { build, derive, fit, contrast, oklchToHex, hexToOklch, relLum, randomSeed, PAIRS };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = PALETTE;
