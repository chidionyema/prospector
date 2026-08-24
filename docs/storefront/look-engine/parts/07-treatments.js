/* ===========================================================================================
   TREATMENTS — the second half of criterion C27.

   A pack graphic is SUBJECT x TREATMENT. The subject belongs to the pack: a real CC0 archival
   plate of the thing the pack is actually about. The treatment belongs to the LOOK: how that
   plate is re-rendered in this look's world. Six subjects times ten treatments is sixty distinct
   pictures with no repeat, and the count grows by multiplication rather than by drawing.

   Two rules make this reusable (criterion C28, gates A33 and A35):
     - nothing in this file names a pack. A treatment receives luminance and colours.
     - nothing in this file names a look. A look SELECTS a treatment by name, in 03-looks.js.
   Break either one and the two layers stop being independent, and 60 pictures collapses back
   into 60 hand-drawn ones.

   Every treatment is a real reprographic process, implemented rather than approximated with a
   CSS filter. A `filter: grayscale(1) contrast(2)` is the same picture with the contrast turned
   up; a 45-degree dot screen is a different picture.
   =========================================================================================== */

/* Sample the source plate into a luminance buffer at render resolution, cover-cropped.
   Sampling at render size rather than sampling the full plate matters: every process below is a
   function of local average tone, and averaging happens correctly only if the pixel grid the
   process walks is the grid the tone was measured on. */
function sampleSource(img, w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.fillStyle = '#fff'; g.fillRect(0, 0, w, h);
  const s = Math.max(w / img.naturalWidth, h / img.naturalHeight);
  const dw = img.naturalWidth * s, dh = img.naturalHeight * s;
  g.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
  const px = g.getImageData(0, 0, w, h).data;
  const lum = new Float32Array(w * h);
  for (let i = 0, j = 0; i < px.length; i += 4, j++) lum[j] = px[i] / 255;
  return { lum, w, h };
}

/* Bounded read. Every process below walks a lattice that does not align to the pixel grid, so
   out-of-range reads are normal rather than exceptional; clamping is cheaper than guarding. */
const L = (S, x, y) => {
  const xi = x < 0 ? 0 : x >= S.w ? S.w - 1 : x | 0;
  const yi = y < 0 ? 0 : y >= S.h ? S.h - 1 : y | 0;
  return S.lum[yi * S.w + xi];
};

/* Mean tone of a cell. A halftone dot's area must come from the cell's AVERAGE, not from its
   centre pixel: a centre sample on an engraving lands on a line or between two lines, so the
   screen renders the line frequency of the original instead of its tone. */
function cellMean(S, x0, y0, size) {
  let sum = 0, n = 0;
  const step = size > 6 ? 2 : 1;
  for (let y = y0; y < y0 + size; y += step) for (let x = x0; x < x0 + size; x += step) { sum += L(S, x, y); n++; }
  return n ? sum / n : 1;
}

/* Deterministic noise. Math.random would give a different picture on every render, and a
   graphic that changes when you reload cannot be hashed, which is how gate A32 checks that no
   graphic repeats. mulberry32 — seedrandom has been unmaintained since 2019. */
function prng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ---------------------------------------------------------------------------------------- */

/* 1. HALFTONE — the rotated dot screen a press actually uses.
   45 degrees because the eye resolves a vertical or horizontal lattice as a grid and a
   45-degree one as tone; it is also the angle the black plate is given in four-colour work,
   for the same reason. Dot AREA carries the tone, so the radius is a square root: a cell at
   50% ink gets a radius of 0.707, not 0.5, and skipping that is what makes an amateur halftone
   look chalky in the midtones. */
function halftone(g, w, h, S, C, seed) {
  const cell = Math.max(4, Math.round(Math.min(w, h) / 46));
  g.fillStyle = C.ground; g.fillRect(0, 0, w, h);
  g.fillStyle = C.ink;
  const a = Math.PI / 4, cos = Math.cos(a), sin = Math.sin(a);
  const diag = Math.ceil((w + h) / cell) + 2;
  for (let j = -diag; j < diag; j++) {
    for (let i = -diag; i < diag; i++) {
      const cx = (i + 0.5) * cell * cos - (j + 0.5) * cell * sin + w / 2;
      const cy = (i + 0.5) * cell * sin + (j + 0.5) * cell * cos + h / 2;
      if (cx < -cell || cy < -cell || cx > w + cell || cy > h + cell) continue;
      const ink = 1 - cellMean(S, cx - cell / 2, cy - cell / 2, cell);
      if (ink < 0.02) continue;
      const r = (cell / 2) * Math.sqrt(Math.min(1, ink)) * 1.34;
      g.beginPath(); g.arc(cx, cy, r, 0, 6.2832); g.fill();
    }
  }
}

/* 2. RASTER — a phosphor scan. Threshold against a LOCAL mean rather than a fixed level, so an
   unevenly lit plate does not go solid black at one end; then drop the odd scan lines. The
   local window is deliberately large (an eighth of the short side): a small window turns every
   engraved line into its own local mean and the picture dissolves into noise. */
function raster(g, w, h, S, C, seed) {
  g.fillStyle = C.ground; g.fillRect(0, 0, w, h);
  const win = Math.max(8, Math.round(Math.min(w, h) / 8));
  const line = 3;
  g.fillStyle = C.ink;
  for (let y = 0; y < h; y += line) {
    for (let x = 0; x < w; x++) {
      const local = cellMean(S, x - win / 2, y - win / 2, win);
      if (L(S, x, y) < local - 0.06) g.fillRect(x, y, 1, 2);
    }
  }
  g.globalAlpha = 0.5; g.fillStyle = C.accent;
  for (let y = 0; y < h; y += line * 4) g.fillRect(0, y, w, 1);
  g.globalAlpha = 1;
}

/* 3. STIPPLE — density, not dots on a grid.
   Secord's weighted-Voronoi relaxation is the right answer and is too slow to run per card at
   render time, so this is Mitchell's best-candidate: draw k candidates, keep the one furthest
   from its neighbours. It gives blue-noise spacing — no clumps, no lattice — for a fraction of
   the cost, and the difference from a relaxed set is not visible at this size. Rejection is on
   (1-tone)^1.35: the exponent is what stops mid-greys from filling in solid. */
function stipple(g, w, h, S, C, seed) {
  g.fillStyle = C.ground; g.fillRect(0, 0, w, h);
  const rnd = prng(seed);
  const target = Math.round((w * h) / 62);
  const grid = 12, gw = Math.ceil(w / grid), gh = Math.ceil(h / grid);
  const occ = new Float32Array(gw * gh).fill(1e9);
  g.fillStyle = C.ink;
  let placed = 0, tries = 0;
  while (placed < target && tries < target * 26) {
    tries++;
    let best = null, bestD = -1;
    for (let k = 0; k < 3; k++) {
      const x = rnd() * w, y = rnd() * h;
      const ink = Math.pow(1 - L(S, x, y), 1.35);
      if (rnd() > ink) continue;
      const gx = Math.min(gw - 1, (x / grid) | 0), gy = Math.min(gh - 1, (y / grid) | 0);
      let d = 1e9;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const nx = gx + dx, ny = gy + dy;
        if (nx < 0 || ny < 0 || nx >= gw || ny >= gh) continue;
        d = Math.min(d, occ[ny * gw + nx]);
      }
      if (d > bestD) { bestD = d; best = { x, y, gx, gy }; }
    }
    if (!best) continue;
    const ink = 1 - L(S, best.x, best.y);
    const r = 0.55 + ink * 1.45;
    g.beginPath(); g.arc(best.x, best.y, r, 0, 6.2832); g.fill();
    occ[best.gy * gw + best.gx] = 0;
    placed++;
  }
}

/* 4. ATKINSON — the error-diffusion dither of the original Macintosh, and the right one for a
   file-copy register. It pushes only 6/8 of the error to six neighbours and DISCARDS 2/8, which
   is technically a tonal error and is exactly why it looks like a photocopy: highlights blow to
   paper white and shadows block up to solid, instead of Floyd-Steinberg's even grey mush.
   Serpentine scan, because a single-direction scan leaves a directional worm artefact. */
function atkinson(g, w, h, S, C, seed) {
  const buf = new Float32Array(w * h);
  buf.set(S.lum);
  const img = g.createImageData(w, h);
  const [ir, ig, ib] = hexRgb(C.ink), [br, bg, bb] = hexRgb(C.ground);
  for (let y = 0; y < h; y++) {
    const ltr = (y & 1) === 0;
    for (let n = 0; n < w; n++) {
      const x = ltr ? n : w - 1 - n;
      const old = buf[y * w + x];
      const nv = old > 0.5 ? 1 : 0;
      const err = (old - nv) / 8;
      const push = (dx, dy) => {
        const X = x + (ltr ? dx : -dx), Y = y + dy;
        if (X >= 0 && X < w && Y >= 0 && Y < h) buf[Y * w + X] += err;
      };
      push(1, 0); push(2, 0); push(-1, 1); push(0, 1); push(1, 1); push(0, 2);
      const i = (y * w + x) * 4;
      img.data[i] = nv ? br : ir; img.data[i+1] = nv ? bg : ig; img.data[i+2] = nv ? bb : ib; img.data[i+3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
}

/* 5. LINE SCREEN — the engraved rule. One family of parallel lines whose STROKE WIDTH carries
   the tone, which is how a bank-note engraver works and how a line-conversion screen works.
   The line is drawn as a run of short segments rather than one stroked path so the width can
   change along it; a constant-width line is a hatching pattern, not a tonal process. */
function linescreen(g, w, h, S, C, seed) {
  g.fillStyle = C.ground; g.fillRect(0, 0, w, h);
  g.strokeStyle = C.ink; g.lineCap = 'butt';
  const pitch = Math.max(3, Math.round(Math.min(w, h) / 78));
  const step = 2;
  for (let y = pitch / 2; y < h; y += pitch) {
    for (let x = 0; x < w; x += step) {
      const ink = 1 - cellMean(S, x, y - pitch / 2, pitch);
      if (ink < 0.03) continue;
      g.lineWidth = Math.min(pitch * 0.96, ink * pitch * 1.06);
      g.beginPath(); g.moveTo(x, y); g.lineTo(x + step, y); g.stroke();
    }
  }
}

/* 6. CROSS-HATCH — the woodblock and pen-and-ink method: tone is built in PASSES, each pass a
   whole family of lines laid at a new angle, each gated on a tonal threshold. Three passes give
   four printable tones (paper, one, two, three), which is what a book engraver had. The angles
   are 20/70/-25 rather than 0/45/90 so the passes never coincide into a plaid. */
function crosshatch(g, w, h, S, C, seed) {
  g.fillStyle = C.ground; g.fillRect(0, 0, w, h);
  const pitch = Math.max(4, Math.round(Math.min(w, h) / 40));
  const passes = [
    { ang:  20 * Math.PI / 180, at: 0.30 },
    { ang:  70 * Math.PI / 180, at: 0.55 },
    { ang: -25 * Math.PI / 180, at: 0.76 },
  ];
  g.strokeStyle = C.ink; g.lineWidth = 1; g.lineCap = 'butt';
  const diag = Math.hypot(w, h);
  for (const p of passes) {
    const cos = Math.cos(p.ang), sin = Math.sin(p.ang);
    for (let d = -diag; d < diag; d += pitch) {
      let drawing = false;
      g.beginPath();
      for (let t = -diag / 2; t < diag; t += 2) {
        const x = w / 2 + t * cos - d * sin, y = h / 2 + t * sin + d * cos;
        const on = x >= 0 && y >= 0 && x < w && y < h && (1 - L(S, x, y)) >= p.at;
        if (on && !drawing) { g.moveTo(x, y); drawing = true; }
        else if (on) g.lineTo(x, y);
        else drawing = false;
      }
      g.stroke();
    }
  }
}

/* 7. DUOTONE — the one photographic treatment, and the only one that keeps continuous tone.
   Two inks with a shaped transfer curve: shadows to the accent, midtones to the ink, highlights
   to the ground. A straight linear ramp between two colours is the cliche version and reads as
   a CSS filter; the smoothstep on the shadow leg is what puts weight in the darks. */
function duotone(g, w, h, S, C, seed) {
  const img = g.createImageData(w, h);
  const gr = hexRgb(C.ground), ik = hexRgb(C.ink), ac = hexRgb(C.accent);
  for (let i = 0, j = 0; i < S.lum.length; i++, j += 4) {
    const t = S.lum[i];
    let r, gg, b;
    if (t < 0.5) {
      const u = t * 2, s = u * u * (3 - 2 * u);
      r = ac[0] + (ik[0] - ac[0]) * s; gg = ac[1] + (ik[1] - ac[1]) * s; b = ac[2] + (ik[2] - ac[2]) * s;
    } else {
      const u = (t - 0.5) * 2;
      r = ik[0] + (gr[0] - ik[0]) * u; gg = ik[1] + (gr[1] - ik[1]) * u; b = ik[2] + (gr[2] - ik[2]) * u;
    }
    img.data[j] = r; img.data[j+1] = gg; img.data[j+2] = b; img.data[j+3] = 255;
  }
  g.putImageData(img, 0, 0);
}

/* 8. CYANOTYPE — a blueprint, which is a NEGATIVE process: the plate's whites become deep blue
   and its blacks become paper. Inverting is the whole point rather than a stylistic choice, and
   it is why a blueprint of an engraving looks like a drawing rather than a photograph. The
   drafting grid is laid UNDER the image at low alpha so the plate sits on the paper instead of
   floating over it. */
function cyanotype(g, w, h, S, C, seed) {
  g.fillStyle = C.ground; g.fillRect(0, 0, w, h);
  g.strokeStyle = C.hair; g.lineWidth = 1; g.globalAlpha = 0.85;
  const gp = Math.max(12, Math.round(Math.min(w, h) / 14));
  g.beginPath();
  for (let x = gp; x < w; x += gp) { g.moveTo(x + 0.5, 0); g.lineTo(x + 0.5, h); }
  for (let y = gp; y < h; y += gp) { g.moveTo(0, y + 0.5); g.lineTo(w, y + 0.5); }
  g.stroke(); g.globalAlpha = 1;
  const img = g.getImageData(0, 0, w, h);
  const ik = hexRgb(C.ink), ac = hexRgb(C.accent);
  for (let i = 0, j = 0; i < S.lum.length; i++, j += 4) {
    const t = 1 - S.lum[i];             // the negative
    const k = t * t * (3 - 2 * t);      // the process is contrasty; a linear map is not a cyanotype
    if (k < 0.06) continue;             // leave the grid visible in the clear areas
    img.data[j]   = img.data[j]   * (1 - k) + (ik[0] * 0.35 + ac[0] * 0.65) * k;
    img.data[j+1] = img.data[j+1] * (1 - k) + (ik[1] * 0.35 + ac[1] * 0.65) * k;
    img.data[j+2] = img.data[j+2] * (1 - k) + (ik[2] * 0.35 + ac[2] * 0.65) * k;
  }
  g.putImageData(img, 0, 0);
}

/* 9. WOODCUT — a reduction to two tones, then CARVED. What separates a woodcut from a plain
   threshold is the gouge: the mid-tones are opened up with tapered strokes that follow one
   carving direction, so the block shows the hand that cut it. Strokes are seeded, so the same
   pack always carves identically. */
function woodcut(g, w, h, S, C, seed) {
  g.fillStyle = C.ground; g.fillRect(0, 0, w, h);
  g.fillStyle = C.ink;
  const img = g.createImageData(w, h);
  const ik = hexRgb(C.ink), gr = hexRgb(C.ground);
  for (let i = 0, j = 0; i < S.lum.length; i++, j += 4) {
    const dark = S.lum[i] < 0.52;
    img.data[j] = dark ? ik[0] : gr[0]; img.data[j+1] = dark ? ik[1] : gr[1];
    img.data[j+2] = dark ? ik[2] : gr[2]; img.data[j+3] = 255;
  }
  g.putImageData(img, 0, 0);
  const rnd = prng(seed);
  g.strokeStyle = C.ground; g.lineCap = 'round';
  const ang = -0.42, cos = Math.cos(ang), sin = Math.sin(ang);
  const n = Math.round((w * h) / 380);
  for (let i = 0; i < n; i++) {
    const x = rnd() * w, y = rnd() * h;
    const t = L(S, x, y);
    if (t > 0.52 || t < 0.14) continue;          // carve the mid-darks only; keep the true blacks solid
    const len = 4 + rnd() * 13;
    const wid = 0.5 + (t / 0.52) * 1.9;
    g.lineWidth = wid;
    g.beginPath(); g.moveTo(x, y); g.lineTo(x + cos * len, y + sin * len); g.stroke();
  }
}

/* 10. CONTOUR — marching squares on the luminance field. Four iso-lines and nothing else: no
   fill, no dots, no tone. It is the most restrained possible way to render a photograph and it
   is the only one here that draws the SHAPE of the tone rather than the tone itself. The cell
   is coarse (an eightieth of the short side) because a fine contour of a photograph is noise;
   the restraint has to be in the sampling, not only in the line weight. */
function contour(g, w, h, S, C, seed) {
  g.fillStyle = C.ground; g.fillRect(0, 0, w, h);
  const cell = Math.max(3, Math.round(Math.min(w, h) / 80));
  const levels = [0.26, 0.44, 0.62, 0.80];
  g.lineCap = 'round'; g.lineJoin = 'round';
  levels.forEach((lv, li) => {
    g.strokeStyle = li === 1 ? C.accent : C.ink;
    g.lineWidth = li === 1 ? 1.1 : 0.7;
    g.globalAlpha = 0.42 + li * 0.16;
    g.beginPath();
    for (let y = 0; y + cell < h; y += cell) {
      for (let x = 0; x + cell < w; x += cell) {
        const a = L(S, x, y), b = L(S, x + cell, y), c = L(S, x + cell, y + cell), d = L(S, x, y + cell);
        const idx = (a > lv ? 8 : 0) | (b > lv ? 4 : 0) | (c > lv ? 2 : 0) | (d > lv ? 1 : 0);
        if (idx === 0 || idx === 15) continue;
        // Linear interpolation along each crossed edge. Snapping to the midpoint instead is the
        // usual shortcut and it produces the stair-stepped look that gives marching squares a
        // bad name; the interpolation is one divide and it is what makes the line smooth.
        const ip = (p, q) => (lv - p) / (q - p || 1e-6);
        const T = { x: x + cell * ip(a, b), y };
        const R = { x: x + cell,            y: y + cell * ip(b, c) };
        const B = { x: x + cell * ip(d, c), y: y + cell };
        const Lf = { x,                     y: y + cell * ip(a, d) };
        const seg = (p, q) => { g.moveTo(p.x, p.y); g.lineTo(q.x, q.y); };
        switch (idx) {
          case 1: case 14: seg(Lf, B); break;
          case 2: case 13: seg(B, R); break;
          case 3: case 12: seg(Lf, R); break;
          case 4: case 11: seg(T, R); break;
          case 6: case  9: seg(T, B); break;
          case 7: case  8: seg(Lf, T); break;
          case 5: seg(Lf, T); seg(B, R); break;
          case 10: seg(T, R); seg(Lf, B); break;
        }
      }
    }
    g.stroke();
  });
  g.globalAlpha = 1;
}

function hexRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const TREATMENTS = { halftone, raster, stipple, atkinson, linescreen, crosshatch, duotone, cyanotype, woodcut, contour };
