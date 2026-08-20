// @ledger network | node fetch-subjects.mjs | Refetches every CC0 plate from the Met and rewrites subjects.js (443 KB of base64).
/**
 * SUBJECT ACQUISITION — criterion C27, gates A33 and A34.
 *
 * Each pack gets a REAL archival plate whose subject is what the pack is about. The mapping is
 * CURATED, never derived from a naive search: measured 2026-08-20, the Met's own search returns
 * four portraits for "drafting instruments" and architectural capitals for "abacus". A search
 * term is a guess about a collection; an accession number is a fact about one object.
 *
 * Every object below was fetched, confirmed `isPublicDomain: true`, and its title and date read
 * before it was chosen. CC0 1.0 means no attribution debt and no revocation risk — but the
 * provenance is recorded anyway, because A34 fails a graphic whose licence is not written down.
 *
 * The stored form is a GRAYSCALE 512x640 JPEG. Grayscale because the ten treatments each impose
 * their own colour from the active look's tokens; carrying the original colour would be carrying
 * a decision the look is supposed to make. 4:5 portrait because a cover-crop into any box is a
 * crop, and cropping a portrait into a landscape band loses less than the reverse.
 */
/* Playwright is not a dependency of this prototype; it is borrowed from the storefront's own
 * node_modules. The path is absolute because that is where it lives on this machine, and it
 * is overridable because that will not be true on the next one:
 *   PLAYWRIGHT_MJS=/path/to/playwright/index.mjs node <tool>.mjs
 */
const { chromium } = await import(process.env.PLAYWRIGHT_MJS
  || '/private/tmp/claude-501/-Users-chidionyema-Documents-code-prospector/3fa47c70-c6d2-4273-9620-19dc9810b132/scratchpad/wt-redesign/store_platform/src/Store.Web/node_modules/playwright/index.mjs');
import { writeFileSync } from 'node:fs';

const SUBJECTS = [
  { pack: 'AV-30', id: 193606, why: 'A mechanism that keeps turning whether or not anyone is watching it — which is exactly what an unmaintained dependency does.' },
  { pack: 'NR-38', id: 504752, why: 'A speaking trumpet: the instrument for moving sound a measured distance, on a pack about measuring sound.' },
  { pack: 'RO-34', id: 415070, why: 'Erected scaffolding, drawn in 1773. The pack is a scaffolding permit application.' },
  { pack: 'SC-40', id: 629597, why: 'A balance scale. A chargeback is evidence weighed against evidence.' },
  { pack: 'CC-28', id: 238980, why: 'A wall thermometer. The pack finds the hour a cold chain broke.' },
  { pack: 'RD-23', id:  20365, why: 'A ledger of accounts, 1835–56. The pack turns records into a filed claim.' },
];

const W = 512, H = 640;
const meta = [];

for (const s of SUBJECTS) {
  const r = await fetch(`https://collectionapi.metmuseum.org/public/collection/v1/objects/${s.id}`);
  const o = await r.json();
  if (!o.isPublicDomain) throw new Error(`${s.pack}: object ${s.id} is NOT public domain — gate A34 refuses it`);
  if (!o.primaryImageSmall) throw new Error(`${s.pack}: object ${s.id} has no image`);
  const img = await fetch(o.primaryImageSmall);
  const buf = Buffer.from(await img.arrayBuffer());
  meta.push({
    ...s,
    title: o.title, date: o.objectDate, artist: o.artistDisplayName || null,
    medium: o.medium, dept: o.department, url: o.objectURL,
    licence: 'CC0 1.0', source: 'The Metropolitan Museum of Art, Open Access',
    dataUri: `data:${img.headers.get('content-type') || 'image/jpeg'};base64,${buf.toString('base64')}`,
    bytes: buf.length,
  });
  console.log(`  fetched ${s.pack}  ${o.objectID}  ${o.title.slice(0,44).padEnd(44)}  ${(buf.length/1024).toFixed(0)}KB`);
}

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto('about:blank');

for (const m of meta) {
  m.gray = await page.evaluate(async ({ uri, W, H }) => {
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = uri; });
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const g = c.getContext('2d');
    g.fillStyle = '#fff'; g.fillRect(0, 0, W, H);
    // COVER crop, centred. An archival plate is usually centred in its frame, so a centre crop
    // keeps the subject; the alternative (contain) would band the edges with white and every
    // treatment would then render that band as a feature.
    const s = Math.max(W / img.width, H / img.height);
    const dw = img.width * s, dh = img.height * s;
    g.drawImage(img, (W - dw) / 2, (H - dh) / 2, dw, dh);
    // Rec.709 luminance on GAMMA-ENCODED values is what image editors do for a "desaturate";
    // the linear-light version is more correct but renders engravings noticeably flatter,
    // because linearising pulls the midtones of a high-key plate toward white.
    const d = g.getImageData(0, 0, W, H);
    const p = d.data;
    let lo = 255, hi = 0;
    for (let i = 0; i < p.length; i += 4) {
      const y = (0.2126 * p[i] + 0.7152 * p[i+1] + 0.0722 * p[i+2]) | 0;
      p[i] = p[i+1] = p[i+2] = y; p[i+3] = 255;
      if (y < lo) lo = y; if (y > hi) hi = y;
    }
    // Normalise to full range. Archival scans are routinely low-contrast (a 1579 globe photographed
    // against a grey ground measured 34..231 here), and every downstream treatment — threshold,
    // halftone, dither — is a function of luminance, so an un-normalised source makes ten
    // treatments all look washed out for one reason that has nothing to do with any of them.
    const span = Math.max(1, hi - lo);
    for (let i = 0; i < p.length; i += 4) {
      const v = ((p[i] - lo) * 255 / span) | 0;
      p[i] = p[i+1] = p[i+2] = v;
    }
    g.putImageData(d, 0, 0);
    return { uri: c.toDataURL('image/jpeg', 0.86), lo, hi };
  }, { uri: m.dataUri, W, H });
  console.log(`  gray    ${m.pack}  range ${m.gray.lo}..${m.gray.hi} -> 0..255   ${(m.gray.uri.length/1024).toFixed(0)}KB b64`);
}
await browser.close();

const out = `/* GENERATED by fetch-subjects.mjs on 2026-08-20. Do not hand-edit.
   Every entry is CC0 1.0 from The Met's Open Access programme, fetched and confirmed
   isPublicDomain:true at generation time. Gate A34 reads the licence field below. */
export const SUBJECTS = ${JSON.stringify(
  meta.map((m) => ({
    pack: m.pack, why: m.why, title: m.title, date: m.date, artist: m.artist,
    medium: m.medium, dept: m.dept, objectId: m.id, url: m.url,
    licence: m.licence, source: m.source, src: m.gray.uri,
  })), null, 1)};
`;
writeFileSync('subjects.js', out);
console.log(`\nwrote subjects.js  ${(out.length / 1024).toFixed(0)}KB  ${meta.length} subjects, all CC0`);
