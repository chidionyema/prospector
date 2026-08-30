import { existsSync, readdirSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { SECTOR } from '@/lib/facets';
import { PACK_IMAGE_IDS } from '@/lib/packImages.generated';
import { packImage, sectorImage, PACK_IMAGE_DIR, SECTOR_IMAGE_DIR } from '@/lib/sectorImage';

/**
 * A picture that 404s is worse than no picture: the card keeps the space, the browser draws its
 * broken-image mark, and every check in this repo stays green because nothing here ever asked the
 * filesystem. So this asks the filesystem.
 */
const WEB = path.resolve(__dirname, '../..');
const IMAGES = path.join(WEB, 'public', SECTOR_IMAGE_DIR.replace(/^\//, ''));

describe('sector images', () => {
  it('draws every sector the facet vocabulary can produce', () => {
    const missing = SECTOR.filter((code) => !existsSync(path.join(IMAGES, `${code}.jpg`)));
    expect(missing).toEqual([]);
  });

  it('ships no image no sector can reach', () => {
    const orphans = readdirSync(IMAGES)
      .filter((f) => f.endsWith('.jpg'))
      .map((f) => f.replace(/\.jpg$/, ''))
      .filter((code) => !(SECTOR as readonly string[]).includes(code));
    expect(orphans).toEqual([]);
  });

  it('maps a code to one path, and anything else to nothing', () => {
    expect(sectorImage('housing_rental')).toBe('/sector/housing_rental.jpg');
    expect(sectorImage('not_a_sector')).toBeNull();
    expect(sectorImage(null)).toBeNull();
    expect(sectorImage(undefined)).toBeNull();
  });

  /**
   * The live catalogue on 2026-08-30 held 77 packs and 13 of them carried `sector: null`. A render
   * site that called `sectorImage` directly drew those 13 as a card with a hole in it, on a shelf
   * where every card beside them had a picture. `packImage` is what a render site calls, and the
   * only thing this has to guarantee is that it never returns nothing.
   */
  it('never leaves a card without a picture, whatever the pack carries', () => {
    expect(packImage({ sector: 'housing_rental' })).toBe('/sector/housing_rental.jpg');
    expect(packImage({})).toBe('/sector/other.jpg');
    expect(packImage(null)).toBe('/sector/other.jpg');
    expect(packImage(undefined)).toBe('/sector/other.jpg');
    expect(packImage({ sector: 'a_sector_the_engine_invented_tonight' })).toBe('/sector/other.jpg');
  });

  it('ships the file every fallback lands on', () => {
    expect(existsSync(path.join(IMAGES, 'other.jpg'))).toBe(true);
  });
});

/**
 * A pack's OWN picture, drawn from its title and description. The sector layer above is what a
 * pack falls back to; this is what it gets when it has been drawn.
 */
describe('pack images', () => {
  const PACK_IMAGES = path.join(WEB, 'public', PACK_IMAGE_DIR.replace(/^\//, ''));

  it('prefers the pack over its sector once the pack has been drawn', () => {
    const [id] = [...PACK_IMAGE_IDS];
    expect(id, 'the manifest is empty: run tools/gen_pack_images.py').toBeTruthy();
    expect(packImage({ id, sector: 'housing_rental' })).toBe(`/pack/${id}.jpg`);
  });

  it('falls back to the sector for a pack published since the last build', () => {
    expect(packImage({ id: 'an_id_no_build_has_drawn', sector: 'housing_rental' })).toBe(
      '/sector/housing_rental.jpg',
    );
  });

  /**
   * The manifest is generated from a directory listing, so the two can only disagree if a file was
   * deleted or committed by hand. Either way the shelf renders a broken-image mark, which is the
   * one outcome the whole three-layer fallback exists to prevent.
   */
  it('ships a file for every id the manifest claims', () => {
    const missing = [...PACK_IMAGE_IDS].filter(
      (id) => !existsSync(path.join(PACK_IMAGES, `${id}.jpg`)),
    );
    expect(missing).toEqual([]);
  });

  it('claims every file it ships', () => {
    const unclaimed = readdirSync(PACK_IMAGES)
      .filter((f) => f.endsWith('.jpg'))
      .map((f) => f.replace(/\.jpg$/, ''))
      .filter((id) => !PACK_IMAGE_IDS.has(id));
    expect(unclaimed).toEqual([]);
  });
});
