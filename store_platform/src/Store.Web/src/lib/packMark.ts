/**
 * Deterministic generative identity for a pack.
 *
 * WHY THIS EXISTS. The shelf carries 57 products and zero photographs. There is no photography
 * for a business blueprint, and the obvious fix -- stock imagery -- is the one option actually
 * barred here: a shop whose entire proposition is "every claim is sourced" cannot illustrate
 * itself with a picture of a stranger at a laptop. Stock photography would not be neutral
 * decoration on this site, it would be the first unsourced claim on the page.
 *
 * So the mark is COMPUTED from the thing it identifies. Every pack already carries a 16-character
 * hex id (`939b559421982379`), which is a content address the engine minted -- so a mark derived
 * from it is not invented, it is a rendering of an identifier that already exists. Two packs
 * cannot collide unless their ids collide, and the same pack looks identical on every render,
 * every session and every machine.
 *
 * `Math.random()` is BANNED in this module and in everything that consumes it. A cover that
 * changes on reload is worse than no cover: a buyer who scrolls back up the shelf cannot find the
 * card they were looking at, so the mark stops being an identity and becomes noise.
 * `__tests__/usTwoPackArt.test.ts` already asserts this for the existing cover art; the same rule
 * binds here.
 */

/**
 * FNV-1a, 32-bit.
 *
 * Chosen over a hand-rolled `charCodeAt` sum for one concrete reason: a sum is order-insensitive
 * and heavily clustered, so `abc123` and `321cba` produce the SAME mark, and ids sharing a prefix
 * produce marks a few units apart -- which on a shelf sorted by id (the default) would render as
 * a run of near-identical neighbours, the exact uniformity this is here to break.
 *
 * `Math.imul` rather than `*` because the 32-bit multiply overflows a double past 2^53 and JS
 * would silently lose the low bits, making the hash engine-dependent. `>>> 0` keeps it unsigned
 * so the value is stable across the sign boundary.
 */
export function hashId(id: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i += 1) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/**
 * xorshift32, seeded from the hash.
 *
 * The hash alone gives ONE number; a mark needs a dozen independent-looking values (band heights,
 * offsets, opacities). Slicing bit-ranges out of a single 32-bit hash runs out of entropy at about
 * five draws and the sixth starts correlating with the first, which shows up as marks whose top
 * band predicts their bottom band. A PRNG re-seeded per pack gives an unlimited stream that is
 * still fully determined by the id.
 *
 * Returns floats in [0, 1).
 */
export function seededSequence(seed: number, count: number): number[] {
  const out: number[] = [];
  // A zero state is a fixed point for xorshift -- it emits zero forever. Only reachable if the
  // hash is exactly 0, but an id that renders a blank mark is a bug worth one `|| 1`.
  let s = seed >>> 0 || 1;
  for (let i = 0; i < count; i += 1) {
    s ^= s << 13;
    s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    out.push(s / 0x100000000);
  }
  return out;
}

export interface Stratum {
  /** Top edge, as a fraction of the mark's height. */
  y: number;
  /** Band thickness, as a fraction of the mark's height. */
  h: number;
  /** Fill opacity. */
  o: number;
  /** Horizontal inset of the band's left edge, as a fraction of width. */
  x: number;
  /** Band width, as a fraction of the mark's width. */
  w: number;
}

/**
 * The mark's form: STRATIGRAPHY -- a core sample read top to bottom.
 *
 * The form is not arbitrary. The alternatives considered were a blobby gradient (reads as a
 * generic SaaS avatar, and a gradient carries no countable structure) and an identicon grid
 * (reads as a GitHub default avatar, which is a well-known signal for "this user set nothing").
 * Strata read as a core sample or a sediment column: layered, measured, extracted from
 * somewhere. That is the same claim the product makes, so the mark argues for the product
 * instead of merely labelling it.
 *
 * Band count varies 5-9 with the id, because a fixed count is the tell that a mark is a template
 * with the numbers swapped. Bands are laid out cumulatively so they never overlap and always fill
 * exactly 100% of the height -- an overlap would double the opacity at the seam and read as a
 * rendering fault rather than as a layer.
 */
export function strata(id: string): Stratum[] {
  const seed = hashId(id);
  const count = 5 + (seed % 5); // 5..9
  // Three draws per band (weight, inset, opacity) plus one spare, taken in one call so the
  // stream's order is fixed and adding a band later cannot reshuffle the existing ones.
  const r = seededSequence(seed, count * 3 + 1);

  // Raw weights first, then normalise, so the bands always sum to exactly 1 regardless of count.
  const weights = Array.from({ length: count }, (_, i) => 0.4 + r[i * 3]);
  const total = weights.reduce((a, b) => a + b, 0);

  let cursor = 0;
  return weights.map((weight, i) => {
    const h = weight / total;
    const y = cursor;
    cursor += h;
    // Inset is capped at 22% so the column still reads as a column: a band starting at 60% of the
    // width looks like a separate object, not a layer of the same core.
    const x = r[i * 3 + 1] * 0.22;
    return {
      y,
      h,
      x,
      w: 1 - x,
      // 0.10-0.34. The ceiling is deliberate: the mark sits BEHIND a title and a sector chip on
      // the card, and anything past ~0.35 of the category hue starts competing with the text for
      // the eye. It is furniture, not an illustration.
      o: 0.1 + r[i * 3 + 2] * 0.24,
    };
  });
}

/**
 * The `view-transition-name` for a pack's mark.
 *
 * Must be unique in the document at the instant a navigation starts: two elements sharing one
 * name aborts the ENTIRE transition silently, so a duplicate here does not degrade the morph, it
 * removes every animation on the page and leaves no error behind. Derived from the pack id, which
 * is unique per card by construction.
 *
 * The `pm-` prefix is required, not cosmetic -- a `view-transition-name` is a CSS custom-ident and
 * may not begin with a digit, and roughly 6 in 16 pack ids do (`939b...`, `224578...`).
 */
export function markTransitionName(id: string): string {
  return `pm-${id}`;
}
