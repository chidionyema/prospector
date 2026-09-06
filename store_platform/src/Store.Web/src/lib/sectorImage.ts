import { SECTOR, type Sector } from '@/lib/facets';
import { PACK_IMAGE_IDS } from '@/lib/packImages.generated';

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

/** Where a pack's own drawing lives, one file per pack id. */
export const PACK_IMAGE_DIR = '/pack';

/** Whatever a render site is holding: the pack row, or nothing at all. */
export type PackImageSubject =
  | { id?: string | null; sector?: Sector | string | null }
  | null
  | undefined;

/**
 * WHAT A RENDER SITE ACTUALLY CALLS, and it never returns null.
 *
 * THREE LAYERS, and each exists because the one under it is not good enough on its own.
 *
 * 1. THE PACK'S OWN PICTURE, drawn from its title and description by
 *    `tools/gen_pack_images.py`. Founder, 2026-08-30: "nininax is good enough to use and can even
 *    generate per title and desc". MiniMax lists `image-01` at $0.0035 an image
 *    (https://platform.minimax.io/docs/guides/pricing-paygo, read the same day), so the whole
 *    catalogue costs well under a pound and each new pack a third of a penny. `PACK_IMAGE_IDS` is
 *    generated at build time, so this stays a pure function with no filesystem behind it.
 *
 * 2. THE SECTOR PICTURE, when the pack was published after the last build and has no drawing of
 *    its own yet. Twelve pictures cover every code the facet vocabulary can produce, so the gap
 *    between a pack going live and its own picture being drawn is a real illustration rather than
 *    a hole in the shelf.
 *
 * 3. `other`, when the pack carries no sector at all. Measured against the live catalogue on
 *    2026-08-30: 77 packs, 13 of them with `sector: null`, because the publish path never set
 *    one. `other` is not a fallback invented here -- it is a real code in `SECTOR` and its drawing
 *    is an assortment of unrelated tools, which is exactly what "we could not say which trade this
 *    belongs to" looks like.
 *
 * Layers 2 and 3 are cover, not an excuse. The publish path should set a sector on every pack, and
 * every pack should end up with its own drawing; both are still owed.
 */
export function packImage(pack: PackImageSubject): string {
  if (pack?.id && PACK_IMAGE_IDS.has(pack.id)) return `${PACK_IMAGE_DIR}/${pack.id}.jpg`;
  return sectorImage(pack?.sector) ?? `${SECTOR_IMAGE_DIR}/other.jpg`;
}
