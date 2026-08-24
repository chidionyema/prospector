/* ===========================================================================
   THE PLATES — ten deterministic graphic renderers.

   C19 asks for quality graphics on the packs. Stock photography is the wrong
   answer twice: it costs money or licence risk, and a photograph of a person at
   a laptop says nothing true about an abandoned-vendor alert feed. So each
   plate is DRAWN FROM THE PACK'S OWN NUMBERS — source count, payback multiple,
   price rung — through a hash of its title. Same pack, same plate, forever; a
   different pack can never collide into the same picture by accident.

   Every renderer takes exactly (g, w, h, d, c): a 2D context already scaled for
   device pixel ratio, the CSS width and height, the pack's data, and the three
   colours the ACTIVE LOOK supplies. A renderer never names a colour.
   =========================================================================== */

/* A tiny stable string hash. Not cryptographic — it only has to be repeatable
   across machines and across reloads, which Math.random is not. */
function hash(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  return h >>> 0;
}
/* A linear congruential generator seeded from that hash: the same sequence every
   time, so a plate is a FUNCTION of its pack rather than a picture of a moment. */
function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; };
}

const PLATES = {

  /* THE LEDGER — an engraved rosette, the way a share certificate is protected.
     Radius carries the source count; the lobes carry the payback multiple; one
     rim tick per source, so the density of the border IS the evidence count. */
  rosette(g, w, h, d, c) {
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.42;
    const lobes = 5 + (d.payback % 9);
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    g.strokeStyle = c.ink; g.lineWidth = 0.6; g.globalAlpha = 0.55;
    for (let ring = 0; ring < 22; ring++) {
      const rr = R * (0.30 + (ring / 22) * 0.70);
      const amp = R * 0.055 * (1 - ring / 30);
      g.beginPath();
      for (let a = 0; a <= 360; a += 2) {
        const t = (a * Math.PI) / 180;
        const r = rr + Math.sin(t * lobes + ring * 0.42) * amp;
        const x = cx + Math.cos(t) * r, y = cy + Math.sin(t) * r;
        a ? g.lineTo(x, y) : g.moveTo(x, y);
      }
      g.stroke();
    }
    g.globalAlpha = 1;
    g.strokeStyle = c.accent; g.lineWidth = 1.4;
    for (let i = 0; i < d.sources; i++) {
      const t = (i / d.sources) * Math.PI * 2 - Math.PI / 2;
      g.beginPath();
      g.moveTo(cx + Math.cos(t) * (R + 6), cy + Math.sin(t) * (R + 6));
      g.lineTo(cx + Math.cos(t) * (R + 14), cy + Math.sin(t) * (R + 14));
      g.stroke();
    }
  },

  /* THE INSTRUMENT — an evidence spectrum. One vertical line per cited source,
     read left to right like a readout on a bench instrument. */
  spectrum(g, w, h, d, c) {
    const r = rng(hash(d.t)), pad = 14, n = d.sources;
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    const step = (w - pad * 2) / n;
    for (let i = 0; i < n; i++) {
      const x = pad + i * step + step / 2;
      const mag = 0.18 + r() * 0.82;
      const tall = mag > 0.78;
      g.strokeStyle = tall ? c.accent : c.ink;
      g.globalAlpha = tall ? 1 : 0.42 + mag * 0.3;
      g.lineWidth = tall ? 2 : 1;
      g.beginPath();
      g.moveTo(x, h - pad);
      g.lineTo(x, h - pad - (h - pad * 2) * mag);
      g.stroke();
    }
    g.globalAlpha = 1;
    g.strokeStyle = c.ink; g.lineWidth = 1;
    g.beginPath(); g.moveTo(pad, h - pad); g.lineTo(w - pad, h - pad); g.stroke();
  },

  /* THE FIELD GUIDE — a stipple specimen, the way an engraved plate builds tone
     from dots. Denser where the evidence is denser. */
  stipple(g, w, h, d, c) {
    const r = rng(hash(d.t)), cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.40;
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    const dots = 900 + d.sources * 40;
    g.fillStyle = c.ink;
    for (let i = 0; i < dots; i++) {
      const t = r() * Math.PI * 2;
      const rad = Math.pow(r(), 0.55) * R;
      const wob = 1 + Math.sin(t * (3 + (d.payback % 5))) * 0.16;
      const x = cx + Math.cos(t) * rad * wob, y = cy + Math.sin(t) * rad;
      g.globalAlpha = 0.10 + (1 - rad / R) * 0.55;
      g.fillRect(x, y, 1.1, 1.1);
    }
    g.globalAlpha = 1; g.strokeStyle = c.accent; g.lineWidth = 1;
    g.beginPath(); g.arc(cx, cy, R + 10, 0, Math.PI * 2); g.stroke();
  },

  /* THE DOSSIER — a redacted page. The bars are the passages that stayed sealed;
     the accent lines are the ones we cited. */
  dossier(g, w, h, d, c) {
    const r = rng(hash(d.t)), pad = 16, lh = 11;
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    let y = pad + 8, line = 0;
    while (y < h - pad) {
      let x = pad;
      while (x < w - pad) {
        const seg = 18 + r() * 74;
        if (x + seg > w - pad) break;
        const cited = line % 4 === (d.sources % 4) && r() > 0.55;
        g.fillStyle = cited ? c.accent : c.ink;
        g.globalAlpha = cited ? 1 : 0.82;
        g.fillRect(x, y, seg, 5.5);
        x += seg + 6;
      }
      y += lh; line++;
    }
    g.globalAlpha = 1;
    g.strokeStyle = c.accent; g.lineWidth = 2;
    g.save(); g.translate(w - 74, 30); g.rotate(-0.14);
    g.strokeRect(-52, -15, 104, 30);
    g.restore();
  },

  /* THE PROSPECTUS — a sparkline with the payback point marked. Financial paper
     draws one line and labels the moment that matters. */
  sparkline(g, w, h, d, c) {
    const r = rng(hash(d.t)), pad = 18, n = 44;
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    g.strokeStyle = c.ink; g.globalAlpha = 0.14; g.lineWidth = 1;
    for (let i = 1; i < 4; i++) {
      const y = pad + ((h - pad * 2) / 4) * i;
      g.beginPath(); g.moveTo(pad, y); g.lineTo(w - pad, y); g.stroke();
    }
    g.globalAlpha = 1;
    const pts = [];
    let v = 0.22;
    for (let i = 0; i < n; i++) {
      v = Math.max(0.06, Math.min(0.96, v + (r() - 0.42) * 0.16 + i / (n * 12)));
      pts.push([pad + ((w - pad * 2) / (n - 1)) * i, h - pad - (h - pad * 2) * v]);
    }
    g.strokeStyle = c.ink; g.lineWidth = 1.6;
    g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.stroke();
    const mark = pts[Math.min(n - 1, Math.max(2, d.payback * 3))];
    g.strokeStyle = c.accent; g.lineWidth = 1.4;
    g.beginPath(); g.moveTo(mark[0], pad); g.lineTo(mark[0], h - pad); g.stroke();
    g.fillStyle = c.accent;
    g.beginPath(); g.arc(mark[0], mark[1], 4, 0, Math.PI * 2); g.fill();
  },

  /* THE ALMANAC — engraved cross-hatch. Hatch angle from the hash, hatch density
     from the source count: the older way of printing a tone. */
  hatch(g, w, h, d, c) {
    const seed = hash(d.t), base = (seed % 40) - 20;
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    const passes = [[base, 4 + (d.sources % 4), c.ink, 0.5],
                    [base + 90, 6 + (d.payback % 5), c.ink, 0.32],
                    [base + 45, 13, c.accent, 0.75]];
    for (const [deg, gap, col, alpha] of passes) {
      g.save(); g.translate(w / 2, h / 2); g.rotate((deg * Math.PI) / 180);
      g.strokeStyle = col; g.globalAlpha = alpha; g.lineWidth = 0.8;
      const R = Math.hypot(w, h);
      for (let y = -R; y < R; y += gap) {
        const t = Math.abs(y) / R;
        if (t > 0.68) continue;
        g.beginPath(); g.moveTo(-R, y); g.lineTo(R, y); g.stroke();
      }
      g.restore();
    }
    g.globalAlpha = 1;
  },

  /* THE SIGNAL — one bold arc sweeping to the survival point. The loudest look
     gets the simplest mark; the whole plate is a single gesture. */
  arc(g, w, h, d, c) {
    const cx = w / 2, cy = h * 0.62, R = Math.min(w, h) * 0.44;
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    g.lineCap = 'round';
    g.strokeStyle = c.ink; g.globalAlpha = 0.16; g.lineWidth = 16;
    g.beginPath(); g.arc(cx, cy, R, Math.PI, Math.PI * 2); g.stroke();
    g.globalAlpha = 1;
    const frac = Math.min(0.97, 0.20 + d.payback / 18);
    g.strokeStyle = c.accent; g.lineWidth = 16;
    g.beginPath(); g.arc(cx, cy, R, Math.PI, Math.PI + Math.PI * frac); g.stroke();
    g.strokeStyle = c.ink; g.globalAlpha = 0.5; g.lineWidth = 1;
    for (let i = 0; i < d.sources; i++) {
      const t = Math.PI + (i / (d.sources - 1)) * Math.PI;
      g.beginPath();
      g.moveTo(cx + Math.cos(t) * (R + 13), cy + Math.sin(t) * (R + 13));
      g.lineTo(cx + Math.cos(t) * (R + 20), cy + Math.sin(t) * (R + 20));
      g.stroke();
    }
    g.globalAlpha = 1; g.lineCap = 'butt';
  },

  /* THE WORKBENCH — an isometric wireframe with dimension lines, drawn the way
     a part is drawn before it is made. */
  isometric(g, w, h, d, c) {
    const r = rng(hash(d.t)), cx = w / 2, cy = h / 2 + 12;
    const u = Math.min(w, h) * 0.085;
    const iso = (x, y, z) => [cx + (x - y) * u * 0.87, cy + (x + y) * u * 0.5 - z * u * 0.72];
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    g.strokeStyle = c.ink; g.globalAlpha = 0.14; g.lineWidth = 0.6;
    for (let i = -4; i <= 4; i++) {
      let p = iso(i, -4, 0), q = iso(i, 4, 0);
      g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.stroke();
      p = iso(-4, i, 0); q = iso(4, i, 0);
      g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.stroke();
    }
    g.globalAlpha = 1;
    const cols = 5;
    for (let i = 0; i < cols; i++) {
      for (let j = 0; j < cols; j++) {
        const zz = Math.round(r() * (1 + d.payback / 5));
        if (zz < 1) continue;
        const x = i - 2, y = j - 2;
        const top = [iso(x, y, zz), iso(x + 1, y, zz), iso(x + 1, y + 1, zz), iso(x, y + 1, zz)];
        g.strokeStyle = (i + j) % 3 === d.sources % 3 ? c.accent : c.ink;
        g.lineWidth = 1;
        g.beginPath(); top.forEach((p, k) => (k ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.closePath(); g.stroke();
        for (const [a, b] of [[top[0], iso(x, y, 0)], [top[1], iso(x + 1, y, 0)], [top[2], iso(x + 1, y + 1, 0)]]) {
          g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
        }
      }
    }
  },

  /* THE BROADSIDE — a cut woodblock. Heavy positive shapes, a hand-cut edge, and
     the grain left in, because a press leaves it in. */
  woodcut(g, w, h, d, c) {
    const r = rng(hash(d.t)), pad = 12;
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    const bars = 4 + (d.payback % 4);
    const bh = (h - pad * 2) / bars;
    for (let i = 0; i < bars; i++) {
      const y = pad + i * bh;
      const inset = r() * (w * 0.30);
      g.fillStyle = i % 3 === d.sources % 3 ? c.accent : c.ink;
      g.beginPath();
      g.moveTo(pad + inset, y + 2);
      g.lineTo(w - pad - r() * 10, y + 1);
      g.lineTo(w - pad - r() * 8, y + bh - 5);
      g.lineTo(pad + inset + r() * 12, y + bh - 4);
      g.closePath(); g.fill();
    }
    g.globalAlpha = 0.5; g.strokeStyle = c.bg; g.lineWidth = 1;
    for (let y = pad; y < h - pad; y += 3.5) {
      g.beginPath(); g.moveTo(pad, y + r() * 1.2); g.lineTo(w - pad, y + r() * 1.2); g.stroke();
    }
    g.globalAlpha = 1;
  },

  /* THE QUIET — one hairline, unrepeated. The whole plate is a single arc whose
     sweep is the payback and whose one tick is the source count. */
  hairline(g, w, h, d, c) {
    const cx = w * 0.5, cy = h * 0.5, R = Math.min(w, h) * 0.36;
    g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
    g.strokeStyle = c.ink; g.globalAlpha = 0.16; g.lineWidth = 1;
    g.beginPath(); g.arc(cx, cy, R, 0, Math.PI * 2); g.stroke();
    g.globalAlpha = 1;
    const frac = Math.min(0.96, 0.14 + d.payback / 16);
    g.strokeStyle = c.accent; g.lineWidth = 1.5;
    g.beginPath(); g.arc(cx, cy, R, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frac); g.stroke();
    g.strokeStyle = c.ink; g.globalAlpha = 0.55; g.lineWidth = 1;
    const t = -Math.PI / 2 + Math.PI * 2 * frac;
    g.beginPath();
    g.moveTo(cx + Math.cos(t) * (R - 7), cy + Math.sin(t) * (R - 7));
    g.lineTo(cx + Math.cos(t) * (R + 7), cy + Math.sin(t) * (R + 7));
    g.stroke();
    g.globalAlpha = 1;
  },
};

/* THE HERO FIGURE. One mark per idea researched — 1,444 of them — and the lit
   ones are the 77 that survived. The stride is prime-ish so survivors scatter
   across the field instead of clumping in a corner, which would read as a
   picture of a decision rather than of a filter. Mark SHAPE comes from the
   look, so the same true count can be a dot, a tick, a bar or a cross. */
const MARK = {
  rosette:'dot', stipple:'dot', hairline:'dot',
  spectrum:'bar', sparkline:'bar', isometric:'bar',
  dossier:'slab', woodcut:'slab',
  hatch:'tick', arc:'tick',
};

function drawField(g, w, h, total, live, colors, shape) {
  g.fillStyle = colors.bg; g.fillRect(0, 0, w, h);
  const cols = Math.ceil(Math.sqrt(total * (w / h)));
  const rows = Math.ceil(total / cols);
  const pad = 10;
  const cw = (w - pad * 2) / cols, ch = (h - pad * 2) / rows;
  /* Scatter the survivors, do not stride them. A fixed stride shares a factor with the column
     count more often than not, and when it does every lit mark lands in the same subset of
     columns: measured here, stride 18 against 44 columns put all 77 survivors into 22 columns
     on a clean diagonal. The chart then reads as wallpaper, and a reader who cannot believe the
     picture will not believe the number either. Hashing the index is deterministic — the same
     77 marks light every render — without being periodic. */
  const lit = new Set();
  for (let i = 0, n = 0; i < total && lit.size < live; i++) {
    let x = (i * 2654435761) >>> 0;          // Knuth's multiplicative hash
    x ^= x >>> 15; x = Math.imul(x, 2246822519) >>> 0; x ^= x >>> 13;
    const remaining = total - i, needed = live - lit.size;
    if ((x >>> 8) / 16777216 < needed / remaining) { lit.add(i); n++; }
  }
  for (let i = 0; i < total; i++) {
    const cx = pad + (i % cols) * cw + cw / 2;
    const cy = pad + Math.floor(i / cols) * ch + ch / 2;
    const on = lit.has(i);
    g.fillStyle = g.strokeStyle = on ? colors.accent : colors.ink;
    g.globalAlpha = on ? 1 : 0.30;
    const s = Math.min(cw, ch);
    if (shape === 'dot') { g.beginPath(); g.arc(cx, cy, on ? s * 0.34 : s * 0.19, 0, Math.PI * 2); g.fill(); }
    else if (shape === 'bar') { g.fillRect(cx - s * 0.10, cy - s * (on ? 0.42 : 0.24), s * 0.20, s * (on ? 0.84 : 0.48)); }
    else if (shape === 'slab') { g.fillRect(cx - s * 0.36, cy - s * 0.13, s * 0.72, s * 0.26); }
    else { g.lineWidth = on ? 1.8 : 1;
           g.beginPath(); g.moveTo(cx - s * 0.28, cy - s * 0.28); g.lineTo(cx + s * 0.28, cy + s * 0.28); g.stroke(); }
  }
  g.globalAlpha = 1;
}
