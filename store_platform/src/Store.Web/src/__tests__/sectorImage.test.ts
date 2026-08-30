import { existsSync, readdirSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { SECTOR } from '@/lib/facets';
import { packImage, sectorImage, SECTOR_IMAGE_DIR } from '@/lib/sectorImage';

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
    expect(packImage('housing_rental')).toBe('/sector/housing_rental.jpg');
    expect(packImage(null)).toBe('/sector/other.jpg');
    expect(packImage(undefined)).toBe('/sector/other.jpg');
    expect(packImage('a_sector_the_engine_invented_tonight')).toBe('/sector/other.jpg');
  });

  it('ships the file every fallback lands on', () => {
    expect(existsSync(path.join(IMAGES, 'other.jpg'))).toBe(true);
  });
});
