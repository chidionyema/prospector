/**
 * The share card's palette, and the one place it is allowed to be a literal hex.
 *
 * SATORI CANNOT READ CSS CUSTOM PROPERTIES. `pages/og/pack/[id].tsx` renders through Satori, which
 * takes an inline style object and resolves nothing: `var(--text)` reaches it as the string
 * "var(--text)" and draws as black or as nothing. So the card has to carry literal hexes, and for
 * that reason it carried five of them written by hand next to a comment naming the tokens they
 * were copied from.
 *
 * That is not a styling choice, it is an unmaintained copy, and by 2026-08-18 four of the five had
 * drifted from the tokens they claimed to mirror:
 *
 *   card said            token now says        token
 *   #171717              #17191C               --text
 *   #E4E4E7              #E7E7E1               --border
 *   #71717A              #707478               --subtle
 *   #047857              #14706A               --survive -> --success
 *
 * The green is the one that mattered. `--survive` is the only colour this site lets carry meaning,
 * and every share card posted anywhere drew it in a green the site had stopped using.
 *
 * THE FIX IS NOT A BETTER COMMENT. `ogPaletteMatchesTokens.test.ts` parses `styles/tokens.css`,
 * follows the `var()` chain, and fails if any value here stops matching the token named in
 * `OG_TOKEN_OF`. A copy that cannot silently drift is a copy that is safe to keep, which is what
 * lets the card go on being rendered by a library that cannot read the stylesheet.
 *
 * Nothing else may import this. The rest of the site reads the tokens through Tailwind, where the
 * browser does the resolving and a literal would be a second source of truth.
 */

export const OG = {
  /** Headings, the title, the price pill's fill. */
  ink: '#17191C',
  /** The card ground. Near-white rather than pure white on purpose: a social card renders against
   *  an arbitrary background, and a pure-white card disappears into a light timeline. */
  cream: '#FAFAFA',
  /** Drawn as a full 2px frame here. The storefront can rely on the viewport edge; a 1200x630
   *  image cannot. */
  border: '#E7E7E1',
  /** The meta row under the title. Tracks `--subtle`, which moved to the mockups' `--ink-3` on
   *  2026-08-18. The card sets it at 26px, well clear of the size where the 3.03:1 measurement on
   *  the storefront ground becomes a reading problem. */
  subtle: '#8B9096',
  /** The cited-source run. The one colour on this site that carries meaning. */
  survive: '#14706A',
  /** Type on the ink pill. NOT A TOKEN, and correctly so: the storefront has no `--on-ink`,
   *  because in the browser that text is `text-white`, a Tailwind literal rather than a themed
   *  value. There is nothing for the test below to compare it against. */
  onInk: '#FFFFFF',
} as const;

/** Which token each value above mirrors. `onInk` is absent because it mirrors none. */
export const OG_TOKEN_OF: Record<Exclude<keyof typeof OG, 'onInk'>, string> = {
  ink: '--text',
  cream: '--surface2',
  border: '--border',
  subtle: '--subtle',
  survive: '--survive',
};
