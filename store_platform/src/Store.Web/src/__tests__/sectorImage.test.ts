import { existsSync, readdirSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { SECTOR } from '@/lib/facets';
import { sectorImage, SECTOR_IMAGE_DIR } from '@/lib/sectorImage';

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
});
