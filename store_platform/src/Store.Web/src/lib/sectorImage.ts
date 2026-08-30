import { SECTOR, type Sector } from '@/lib/facets';

/**
 * THE STOREFRONT'S ONLY PICTURES, one per sector, and the reason there is one per SECTOR rather
 * than one per PACK.
 *
 * The founder's instruction, 2026-08-30: "we can run once through a few hundred categories and
 * then reuse for future packs". A per-pack image is a generation cost on every publish and a
 * blank card whenever the engine is ahead of the artwork. A per-sector image is generated once,
 * costs nothing thereafter, and a pack published tonight in a sector we already drew arrives with
 * its picture already there.
 *
 * THE PATH IS A PURE FUNCTION OF THE FACET CODE. `licensing_admin` maps to
 * `/sector/licensing_admin.jpg` and to nothing else, so adding a sector to `SECTOR` in
 * `lib/facets.ts` and dropping a file of that name into `public/sector/` is the whole of wiring
 * it up. `sectorImage.test.ts` fails when the two sets disagree in either direction: a code with
 * no file renders a broken image on a live shelf, and a file with no code is dead weight in every
 * deploy.
 *
 * The images themselves were generated on MiniMax in the shop's own palette (the `--paper`,
 * `--brand` and `--ink` tokens of `styles/mumchimp.css`), flat vector, no text of any kind. They
 * are decoration and carry no information a reader needs, which is why every render site marks
 * them `alt=""` and `aria-hidden`.
 */
export const SECTOR_IMAGE_DIR = '/sector';

/** The image for a sector code, or null when the pack carries no sector we have drawn. */
export function sectorImage(sector: Sector | string | null | undefined): string | null {
  if (!sector) return null;
  if (!(SECTOR as readonly string[]).includes(sector)) return null;
  return `${SECTOR_IMAGE_DIR}/${sector}.jpg`;
}

/**
 * WHAT A RENDER SITE ACTUALLY CALLS, and it never returns null.
 *
 * Measured against the live catalogue on 2026-08-30: 77 packs, and 13 of them carry
 * `sector: null` -- the publish path never set one. Left to `sectorImage` those 13 render a card
 * with a hole where every card beside them has a picture, which reads worse than a shop with no
 * pictures at all.
 *
 * `other` is not a fallback invented for this. It is a real code in `SECTOR`, its drawing is an
 * assortment of unrelated tools, and "we could not say which trade this belongs to" is exactly
 * what it means. So an unset or unrecognised sector gets the picture that already says so.
 *
 * The right fix is upstream -- the publish path should set a sector on every pack -- and this is
 * not a reason to skip it. It is the reason a missing one cannot reach a buyer as a broken card
 * while that work is done.
 */
export function packImage(sector: Sector | string | null | undefined): string {
  return sectorImage(sector) ?? `${SECTOR_IMAGE_DIR}/other.jpg`;
}
