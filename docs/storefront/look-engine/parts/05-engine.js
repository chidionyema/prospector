/* ===========================================================================
   THE ENGINE. Three jobs, and nothing else:
     1. turn a look (data) into custom properties on <html>,
     2. refuse a look that would ship a contrast failure,
     3. redraw the graphics in the look's own colours.

   It knows no project noun. Swap LOOKS and DATA and this file is unchanged,
   which is the portability requirement (A30) tested rather than asserted.
   =========================================================================== */

/* ---- WCAG 2.2 relative luminance and contrast ratio. -------------------- */
const srgb = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
};
const lum = (hex) => { const [r, g, b] = srgb(hex); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const contrast = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

/* The pairs that actually appear on screen, and the ratio each owes. The table lives in
   the palette module (parts/08-palette.js), because the generator has to FIT against the
   same list this audit REFUSES against — a fitter proved on a shorter table produces
   palettes this engine then rejects. One table, three readers: the fitter, this audit,
   and check.mjs outside the browser. */
const PAIRS = PALETTE.PAIRS;

/* A look states a SEED — about two dozen perceptual decisions — and the sixteen tokens
   are generated from it and fitted against PAIRS before they are ever applied. Built
   once per look and kept, because the arithmetic is the same every time and a chip
   click should not pay for it twice.

   A look that still carries hand-written `light` and `dark` blocks keeps working
   unchanged. That is not politeness to old data: it is what lets the ten shipped looks
   be converted one at a time and compared against the palette they had. */
const _built = new Map();
function palette(look, theme) {
  /* A look with no seed must still name its palette. Returning `look[theme]` blind is how
     both plate renderers came to read `.plateBg` off `undefined` the moment the ten looks
     were converted: the page kept rendering, the contrast audit kept passing — it goes
     through this same resolver — and the only trace was a console error in every cell. */
  if (!look.seed) {
    if (!look[theme]) throw new Error(`look ${look.id} has neither a seed nor a ${theme} palette`);
    return look[theme];
  }
  let p = _built.get(look.id);
  if (!p) { p = PALETTE.build(look.seed); _built.set(look.id, p); }
  return p[theme];
}

function auditLook(look, theme) {
  const t = palette(look, theme);
  return PAIRS.map(({ fg, bg, min, what }) => {
    const got = contrast(t[fg], t[bg]);
    return { a: fg, b: bg, need: min, what, got: Math.round(got * 100) / 100, pass: got >= min };
  });
}

/* ---- Look -> custom properties. The ONE place a token name is written. ---- */
const VARS = {
  ground: '--ground', surface: '--surface', surface2: '--surface-2',
  hair: '--hair', hairStrong: '--hair-strong',
  ink: '--ink', ink2: '--ink-2', ink3: '--ink-3',
  accent: '--accent', accentFill: '--accent-fill', accentInk: '--accent-ink',
  good: '--good', bad: '--bad',
  plateBg: '--plate-bg', plateInk: '--plate-ink', plateAccent: '--plate-accent',
};
const FORM = { radius: '--radius', ruleW: '--rule-w', ruleWStrong: '--rule-w-strong', sp: '--sp', shadow: '--shadow' };
const TYPE = {
  display: '--display', body: '--body', mono: '--mono',
  displayW: '--display-w', track: '--display-track', lead: '--display-lead', italic: '--display-italic',
  bodyW: '--body-w', bodyLead: '--body-lead',
  labelCase: '--label-case', labelTrack: '--label-track', labelW: '--label-w', labelSize: '--label-size',
};

const root = document.documentElement;
let current = LOOKS[0];
let themeChoice = 'system';                        // system | light | dark
const mq = matchMedia('(prefers-color-scheme: dark)');
const resolved = () => (themeChoice === 'system' ? (mq.matches ? 'dark' : 'light') : themeChoice);

/* `figureMarks` -> `data-figure-marks`, the same rule the DOM's own dataset uses. */
const attrOf = (k) => 'data-' + k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());
/* Every axis in the CATALOGUE, not every axis the ten happen to use. Derived from LOOKS, a
   rolled look could set a switch none of the ten declares, and nothing would ever clear it:
   the next look you picked would keep it. The catalogue is the list of axes that exist. */
const SWITCH_KEYS = Object.keys(SWITCHES);

function applyLook(look, { announce = true } = {}) {
  const theme = resolved();
  const audit = auditLook(look, theme);
  const fails = audit.filter((r) => !r.pass);

  /* A26: a look that would ship a contrast failure is refused at apply time,
     which in the console will be refused at SAVE time. It is never a warning
     you can click past — the failing look does not go on screen. */
  if (fails.length) {
    report(look, audit, false);
    if (announce) console.warn('[look] refused', look.id, fails);
    return false;
  }

  const t = palette(look, theme);
  for (const [k, v] of Object.entries(VARS)) root.style.setProperty(v, t[k]);
  for (const [k, v] of Object.entries(FORM)) root.style.setProperty(v, look.form[k]);
  for (const [k, v] of Object.entries(TYPE)) root.style.setProperty(v, look.type[k]);
  /* Structural switches. Every switch ANY look declares is cleared first, then this look's
     are set — otherwise the last look's dropcap survives into the next one, and the page you
     are looking at is a mix of two looks that nobody designed. The list is derived from the
     data, so adding a switch to a look is enough; there is no second list to keep in step. */
  for (const k of SWITCH_KEYS) root.removeAttribute(attrOf(k));
  for (const [k, v] of Object.entries(look.switches || {})) root.setAttribute(attrOf(k), v);
  root.setAttribute('data-look', look.id);
  root.setAttribute('data-theme', theme);
  current = look;
  try { localStorage.setItem('look', look.id); localStorage.setItem('theme', themeChoice); } catch {}
  paintChips();
  report(look, audit, true);
  draw();
  return true;
}

/* ---- The console strip ------------------------------------------------- */
const chipsEl = document.getElementById('chips');
function renderChips() {
  chipsEl.innerHTML = LOOKS.map((l) => `
  <button class="chip${l.rolled ? ' chip--rolled' : ''}" type="button" data-id="${l.id}" aria-pressed="false" title="${l.tagline}${l.rolled ? ' — shift-click to forget' : ''}">
    <i></i>${l.name.replace(/^The /, '')}
  </button>`).join('');
}
renderChips();
chipsEl.addEventListener('click', (e) => {
  const b = e.target.closest('.chip');
  if (b) applyLook(LOOKS.find((l) => l.id === b.dataset.id));
});

/* ROLL — the eleventh look, minted in the browser with no deploy and no edit.
   `rollLook(n)` is deterministic in n, so every rolled look can be brought back by its
   number; the button just picks a number nobody has used yet. applyLook still runs the
   contrast audit and still REFUSES, so this button cannot put an illegible page on screen —
   if a roll is refused the console says so and the previous look stays up. */
let rollN = 0;

/* A45 says the console can ADD a look without a deploy. A look that vanishes on reload is
   half of that, so the numbers are remembered here. What is stored is the NUMBER and never
   the built look: `rollLook(n)` is deterministic in n, so the number is the whole record.
   Storing the palette and the type stack instead would freeze a copy of a generator that is
   still changing — the day the catalogue gains a typeface, every stored look would be a
   fossil of the old one and nothing on the page would say so. Same defect as a hand-written
   colour beside a seed, in a different coat. */
const ROLL_KEY = 'rolled';
const readRolls = () => {
  try { return JSON.parse(localStorage.getItem(ROLL_KEY) || '[]').filter((n) => Number.isFinite(n)); }
  catch { return []; }
};
const writeRolls = (ns) => { try { localStorage.setItem(ROLL_KEY, JSON.stringify(ns)); } catch {} };

function addRolled(look) {
  const at = LOOKS.findIndex((l) => l.id === look.id);
  if (at >= 0) LOOKS[at] = look; else LOOKS.push(look);
}

function rollNewLook(n, { remember = true } = {}) {
  const num = n == null ? ++rollN : n;
  const look = rollLook(num);
  addRolled(look);
  renderChips();
  const ok = applyLook(look);
  /* A refused roll is NOT remembered. Restoring it on the next load would apply a look the
     contrast audit already turned down, and the page would open on the previous look with no
     explanation for the chip that did nothing. */
  if (ok && remember) {
    const ns = readRolls();
    if (!ns.includes(num)) writeRolls([...ns, num]);
  }
  return ok ? look.id : null;
}
window.rollNewLook = rollNewLook;

/* Restored before boot picks a look, so `?look=roll-101` and the saved look both resolve
   against a table that already contains the rolled ones. Restoring does not APPLY: the
   boot block below decides what is on screen, and two things deciding that is a flicker. */
(function restoreRolls() {
  const ns = readRolls();
  for (const n of ns) addRolled(rollLook(n));
  if (ns.length) { rollN = Math.max(rollN, ...ns); renderChips(); }
})();

document.getElementById('rollBtn').addEventListener('click', () => {
  rollN = Math.max(rollN, ...readRolls(), 0) + 1;
  const id = rollNewLook(rollN);
  if (!id) console.warn('[roll] refused', rollN);
});

/* Forget one: shift-click its chip. The chip's own title says so, because an affordance
   nobody can find is the same as no affordance. */
chipsEl.addEventListener('click', (e) => {
  const b = e.target.closest('.chip');
  if (!b || !e.shiftKey) return;
  const l = LOOKS.find((x) => x.id === b.dataset.id);
  if (!l || !l.rolled) return;
  e.stopPropagation();
  const num = Number(String(l.id).replace('roll-', ''));
  writeRolls(readRolls().filter((n) => n !== num));
  LOOKS.splice(LOOKS.indexOf(l), 1);
  renderChips();
  if (current.id === l.id) applyLook(LOOKS[0]);
  else paintChips();
}, true);
/* The swatch is the look's OWN accent in the theme you would get if you picked it — derived,
   never stated. Each look used to carry a `dot:'#7A1F1B'` hex beside its name, which is the
   last hand-written colour in the table and exactly what gate A43 forbids: a second copy of a
   decision the seed already makes, free to drift from it, and wrong in the other theme. */
function paintChips() {
  chipsEl.querySelectorAll('.chip').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.id === current.id));
    const l = LOOKS.find((x) => x.id === b.dataset.id);
    if (l) b.querySelector('i').style.background = palette(l, resolved()).accent;
  });
}

const themeBtn = document.getElementById('themeBtn');
themeBtn.addEventListener('click', () => {
  themeChoice = { system: 'light', light: 'dark', dark: 'system' }[themeChoice];
  themeBtn.textContent = 'Theme: ' + themeChoice;
  applyLook(current);
});
mq.addEventListener('change', () => { if (themeChoice === 'system') applyLook(current); });

/* The live contrast readout. It is in the demo deliberately: the founder should
   be able to SEE the gate holding, not take its existence on trust. */
function report(look, audit, applied) {
  const bad = audit.filter((r) => !r.pass);
  const el = document.getElementById('a11y');
  if (!el) return;
  el.textContent = bad.length
    ? `${look.name}: REFUSED — ${bad.map((r) => `${r.what} ${r.got}:1`).join(', ')}`
    : `contrast ${audit.length}/${audit.length} pass · min ${Math.min(...audit.map((r) => r.got)).toFixed(2)}:1`;
  el.dataset.state = bad.length ? 'bad' : 'good';
  if (!applied) el.dataset.state = 'bad';
}

/* ---- Graphics ----------------------------------------------------------- */
/* Returns null for a canvas that has no layout box, and every caller must check it.
   The trap this closes: the two views share one chrome, so when the pack page is on
   screen the home page's canvases are still IN the document, just inside a hidden
   <main>. A hidden element measures 0x0. Clamping that to 1x1 and drawing anyway gave
   drawField a cell width of (1 - 20)/38 = -0.5, so it asked for a circle of radius
   -0.17 and threw IndexSizeError. The throw happened INSIDE draw(), which meant every
   line after it was skipped: the subject plates never painted and the router never
   moved focus. One exception, three symptoms, none of which named the cause.
   Skipping an unlaid-out canvas is also the correct thing on its own terms -- there is
   nothing to see, and resizing a canvas wipes it. Whichever view is unhidden next gets
   its own draw() from route(). */
function ctxFor(canvas) {
  const dpr = Math.min(3, devicePixelRatio || 1);
  const r = canvas.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return null;
  const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  return [g, w, h];
}
function plateColors() {
  const t = palette(current, resolved());
  return { bg: t.plateBg, ink: t.plateInk, accent: t.plateAccent };
}
/* The subject plates. Each pack owns a real CC0 archival image of what the pack is ABOUT
   (criterion C27); the active look owns the process that image is rendered through. Neither
   knows about the other, which is the whole reason six subjects and ten looks make sixty
   pictures instead of sixty drawings.

   The sampler is cached on (pack, width, height) because a look switch re-renders every plate
   and re-reading pixels for an unchanged source at an unchanged size is the one avoidable cost
   in the whole switch. Switching looks has to feel instant — that is criterion C23, and a
   150ms stall while six canvases re-sample would break it. */
const SUBJ = Object.create(null);
const SAMPLE = new Map();
let subjectsReady = false;
Promise.all(DATA.SUBJECTS.map((m) => new Promise((res) => {
  const im = new Image();
  im.onload = () => { SUBJ[m.pack] = { meta: m, img: im }; res(); };
  im.onerror = () => { console.warn('subject failed to decode:', m.pack); res(); };
  im.src = m.src;
}))).then(() => { subjectsReady = true; draw(); });

function samplerFor(pack, w, h) {
  const key = pack + ':' + w + 'x' + h;
  let s = SAMPLE.get(key);
  if (!s) { s = sampleSource(SUBJ[pack].img, w, h); SAMPLE.set(key, s); }
  return s;
}

function drawSubjects() {
  if (!subjectsReady) return;
  const t = palette(current, resolved());
  /* The treatment is handed the look's OWN tokens and no others. A treatment that reached for a
     literal colour would look wrong in nine looks out of ten and would break the theme swap in
     all of them. */
  const C = { ground: t.plateBg, ink: t.plateInk, accent: t.plateAccent, hair: t.hair };
  document.querySelectorAll('canvas.subject').forEach((cv) => {
    const pack = cv.dataset.pack;
    if (!SUBJ[pack]) return;
    const cx = ctxFor(cv);
    if (!cx) return;
    const [g, w, h] = cx;
    const S = samplerFor(pack, w, h);
    /* Seed from the pack id AND the treatment, so the two stippled looks of one subject are
       different pictures rather than the same picture in two colours. Gate A32 hashes the
       rendered output and fails on a collision, so this is checked, not assumed. */
    let seed = 2166136261 >>> 0;
    const key = pack + '/' + current.treatment;
    for (let i = 0; i < key.length; i++) { seed ^= key.charCodeAt(i); seed = Math.imul(seed, 16777619) >>> 0; }
    TREATMENTS[current.treatment](g, w, h, S, C, seed >>> 0);
  });
}

function draw() {
  const c = plateColors();
  const hero = document.getElementById('heroCanvas');
  const heroCtx = hero && ctxFor(hero);
  if (heroCtx) {
    const [g, w, h] = heroCtx;
    /* The hero stays generative, and deliberately so. It is not a picture of anything — it is
       1,444 marks with 77 lit, which IS the survivorship number. Abstract generative art is the
       right answer for data and the wrong answer for a subject; C27 rejected it as pack imagery
       for exactly that reason and does not reject it here. */
    drawField(g, w, h, DATA.SITE.researched, DATA.SITE.available, c, MARK[current.plate]);
  }
  document.querySelectorAll('canvas.plate').forEach((cv) => {
    const cx = ctxFor(cv);
    if (!cx) return;
    PLATES[current.plate](cx[0], cx[1], cx[2], DATA.PACKS[+cv.dataset.i], c);
  });
  drawSubjects();
  document.querySelectorAll('.key i').forEach((k) => {
    k.style.background = k.dataset.key === 'live' ? c.accent : c.ink;
    k.style.opacity = k.dataset.key === 'live' ? '1' : '0.3';
  });
}
let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { SAMPLE.clear(); draw(); }, 120); });

/* ---- Content. Every string below comes from DATA, never from markup, which is
   what makes the mini-CMS possible: edit DATA, no rebuild. ----------------- */
const S = DATA.SITE, n = (x) => x.toLocaleString('en-GB');

document.getElementById('dateline').innerHTML =
  `<b>${n(S.researched)}</b> ideas researched · <b>${n(S.killed)}</b> killed with the reason published · <b>${n(S.available)}</b> available now`;
document.getElementById('hHead').textContent = n(S.researched);
document.getElementById('hHead2').textContent = n(S.killed);
document.getElementById('hSurv').textContent = `${S.survivorsPer100} in every 100`;
document.getElementById('availN').textContent = n(S.available);
document.getElementById('catN').textContent = DATA.CATEGORIES.length;
document.getElementById('refundN').textContent = S.refundDays;
document.getElementById('killTotal').textContent = `${n(S.killed)} killed`;
document.getElementById('footNote').innerHTML =
  `<span id="a11y" data-state="good"></span> · £${S.priceLow}–£${S.priceHigh}, once · ${S.refundDays}-day refund`;

document.getElementById('readouts').innerHTML = [
  ['Researched', n(S.researched)], ['Killed', n(S.killed)],
  ['Available', n(S.available)], ['Documents each', S.docs],
].map(([k, v]) => `<div class="readout"><span class="label">${k}</span><b>${v}</b></div>`).join('');

document.getElementById('causes').innerHTML = DATA.KILL_CAUSES.map((c, i) => {
  const pct = c.published ? Math.round((c.c / S.killed) * 100) : null;
  return `<div class="cause${c.published ? '' : ' cause--nocount'}">
    <div class="cause__row">
      <span>${c.n}</span>
      <em>${c.published ? `${n(c.c)} · ${pct}%` : `rank ${i + 1} · count not published`}</em>
    </div>
    <span class="cause__track"><i style="${c.published ? `width:${pct}%` : ''}"></i></span>
  </div>`;
}).join('');

document.getElementById('kotwTitle').textContent = S.killOfWeek.title;
document.getElementById('kotwDeck').textContent = S.killOfWeek.deck;
document.getElementById('kotwDate').textContent = `Killed ${S.killOfWeek.date}. The full reason, and every source behind it, is in the kill log.`;

const SUBJ_META = Object.fromEntries(DATA.SUBJECTS.map((m) => [m.pack, m]));
document.getElementById('packs').innerHTML = DATA.PACKS.map((p) => {
  const m = SUBJ_META[p.id];
  return `
  <article class="pack">
    <div class="pack__media">
      <canvas class="subject" data-pack="${p.id}" width="600" height="375" role="img"
              aria-label="${m.title}, ${m.date}. ${m.why}"></canvas>
      <p class="prov"><span><b>${m.title}</b>, ${m.date}</span><span>${m.source.split(',')[0]}</span><span>${m.licence}</span></p>
    </div>
    <div class="pack__body">
      <p class="label label--good">${p.cat}</p>
      <h3 class="pack__title"><a href="#/pack/${p.id}">${p.t}</a></h3>
      <p class="pack__deck">${p.d}</p>
      <div class="meters">
        <div class="meter__row"><span class="label">Sources</span>
          <span class="meter__track"><i style="width:${Math.min(100, (p.sources / 40) * 100)}%"></i></span><b>${p.sources}</b></div>
        <div class="meter__row meter--good"><span class="label">Payback</span>
          <span class="meter__track"><i style="width:${Math.min(100, (p.payback / 13) * 100)}%"></i></span><b>${p.payback}\u00d7</b></div>
      </div>
    </div>
    <div class="pack__side">
      <span class="pack__price">\u00a3${p.price}</span>
      <a class="btn" href="#/pack/${p.id}">Read the pack</a>
      <p class="pack__note">${DATA.SITE.refundDays}-day refund</p>
    </div>
  </article>`;
}).join('');

document.getElementById('docs').innerHTML = DATA.DOCS.map((d, i) =>
  `<div><span>${String(i + 1).padStart(2, '0')}</span><b>${d}</b></div>`).join('');

const maxRung = Math.max(...S.rungs.map((r) => r.packs));
document.getElementById('rungs').innerHTML = S.rungs.map((r) => `
  <div class="rung"><b>£${r.price}</b>
    <span class="rung__track"><i style="width:${(r.packs / maxRung) * 100}%"></i></span>
    <em>${r.packs} pack${r.packs === 1 ? '' : 's'}</em></div>`).join('');

const cmp = S.comparable;
document.getElementById('compare').innerHTML = `
  <div><p class="label">What a research firm charges</p>
    <p><strong>${cmp.min} minimum, ${cmp.avg} average.</strong> ${cmp.firm}'s published ${cmp.year} price list for one market study, checked ${cmp.checked}.</p></div>
  <div><p class="label label--accent">What this costs</p>
    <p><strong>£${S.priceLow} to £${S.priceHigh}, once.</strong> ${S.docs} documents, every claim cited, ${S.refundDays}-day refund with no reason required.</p></div>`;

/* ---- Boot --------------------------------------------------------------- */
/* A link from the contact sheet is a URL, not a stored preference, so
   ?look=ledger&theme=dark must beat whatever this browser last looked at.
   Without that, every link in the gallery opens the same look and the sheet
   is useless as a way to review ten of them. Both values are checked against
   the real lists rather than trusted, because a hand-edited URL should fall
   back to the saved look, not blank the page. */
try {
  const q = new URLSearchParams(location.search);
  const wantTheme = q.get('theme');
  const savedTheme = ['system', 'light', 'dark'].includes(wantTheme)
    ? wantTheme : localStorage.getItem('theme');
  if (savedTheme) { themeChoice = savedTheme; themeBtn.textContent = 'Theme: ' + themeChoice; }
  const wantLook = q.get('look');
  /* A rolled look is a NUMBER, so `?look=roll-101` is a complete description of one and the
     link works on a browser that has never rolled anything. Without this the link falls back
     to the default look and reads as a working link, which is worse than a dead one. */
  const rollAsk = /^roll-(\d+)$/.exec(wantLook || '');
  if (rollAsk && !LOOKS.some((l) => l.id === wantLook)) addRolled(rollLook(Number(rollAsk[1])));
  const saved = LOOKS.some((l) => l.id === wantLook) ? wantLook : localStorage.getItem('look');
  const first = LOOKS.find((l) => l.id === saved) || LOOKS[0];
  applyLook(first, { announce: false });
} catch { applyLook(LOOKS[0], { announce: false }); }

/* Keyboard: 1-9 and 0 select a look, so a review session is one keystroke per
   look rather than a hunt for the right chip. */
addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
  const i = e.key === '0' ? 9 : '123456789'.indexOf(e.key);
  if (i >= 0 && LOOKS[i]) applyLook(LOOKS[i]);
});

/* The self-check every look must survive, printed once at boot. This is gate
   A21 in miniature: all ten looks, both themes, every pair. */
console.table(LOOKS.flatMap((l) => ['light', 'dark'].map((th) => {
  const a = auditLook(l, th), bad = a.filter((r) => !r.pass);
  return { look: l.id, theme: th, min: Math.min(...a.map((r) => r.got)).toFixed(2), failures: bad.length,
           worst: bad.length ? `${bad[0].what} ${bad[0].got}:1` : '' };
})));

/* ---- The pack page ------------------------------------------------------
   The reported defect was "read the pack page isn't there": every catalogue
   card linked to #/pack/<id> and nothing listened. This is the listener.

   It is a HASH router on purpose. The demo is one file opened from disk, so
   there is no server to answer /pack/AV-30, and history.pushState against a
   file:// origin throws. The real site will swap this for a server route; the
   markup and the render function below do not change when it does.

   The two views live under one chrome (see 02-body.html): the masthead, the
   nav and the footer are outside both, so moving between them changes the
   content and nothing else. No header is rebuilt, so nothing flickers. */

const viewHome = document.getElementById('viewHome');
const viewPack = document.getElementById('viewPack');
const DOC_TITLE = document.title;

function packById(id) { return DATA.PACKS.find((p) => p.id === id) || null; }

function renderPack(p) {
  const d = DATA.PACK_DETAIL[p.id] || {};
  const m = SUBJ_META[p.id];
  const S = DATA.SITE;

  /* The seven checks. Six are GATES — any one of them failing kills the idea
     and the pack is never published. The seventh, price_comparables, is
     evidence-only and can never kill: "no price page on the open web" is a
     fact about the web, not about the idea. The rail says which is which
     rather than showing seven identical ticks, because a row of ticks is what
     a first-time visitor reads as marketing. */
  const checks = DATA.CHECKS.map((c, i) => `
    <div class="check">
      <span class="check__n">${String(i + 1).padStart(2, '0')}</span>
      <p class="check__q">${c.n}</p>
      <p class="check__sub">${c.q}</p>
      <span class="check__v" data-v="${c.gate ? 'pass' : 'evidence'}">${c.gate ? 'Passed' : 'Evidence'}</span>
    </div>`).join('');

  /* Every unfilled publisher slot is RENDERED, in red, in the mono face. UK
     consumer law wants a trading name and a geographic address on the page
     that takes the money. We do not have them yet, and a missing row nobody
     can see is a missing row nobody fixes. */
  const pub = [
    ['Trading name', DATA.PUBLISHER.legalName],
    ['Company number', DATA.PUBLISHER.company],
    ['Address', DATA.PUBLISHER.address],
    ['Email', DATA.PUBLISHER.email],
    ['Telephone', DATA.PUBLISHER.phone],
  ].map(([k, v]) => `<dt>${k}</dt><dd${v ? '' : ' data-todo'}>${v || 'not yet supplied'}</dd>`).join('');

  const related = DATA.PACKS.filter((o) => o.id !== p.id).slice(0, 4).map((o) =>
    `<a href="#/pack/${o.id}"><span>${o.t}</span><em>£${o.price}</em></a>`).join('');

  viewPack.innerHTML = `
  <nav class="crumbs" aria-label="Breadcrumb">
    <a href="#catalogue">Catalogue</a><span aria-hidden="true">/</span><span>${p.cat}</span>
  </nav>

  <div class="artefact">
    <div class="artefact__main">
      <p class="artefact__eyebrow">${p.cat}</p>
      <h1 class="artefact__title" id="packTitle" tabindex="-1">${p.t}</h1>
      <p class="artefact__deck">${p.d}</p>

      <div class="pack__media">
        <canvas class="subject" data-pack="${p.id}" width="600" height="375" role="img"
                aria-label="${m.title}, ${m.date}. ${m.why}"></canvas>
        <p class="prov"><span><b>${m.title}</b>, ${m.date}</span><span>${m.source.split(',')[0]}</span><span>${m.licence}</span></p>
      </div>

      <section class="band">
        <h2 class="band__title">Why this one opened</h2>
        <p>${d.opens || ''}</p>
        <p class="band__note">Every pack starts from something observable. If the opening claim cannot be checked against a page you can open, the idea never reaches this catalogue.</p>
      </section>

      <div class="who">
        <div><h4>Who this is for</h4><p>${d.forWhom || ''}</p></div>
        <div><h4>Who this is not for</h4><p>${d.notFor || ''}</p></div>
      </div>

      <section class="band">
        <h2 class="band__title">The seven checks</h2>
        <p class="band__note">Six of these are gates. One fails and the idea is killed, with the reason published in the kill log. The seventh is evidence only and can never kill an idea.</p>
        <div class="checks">${checks}</div>
      </section>

      <section class="band">
        <h2 class="band__title">What is inside</h2>
        <p class="band__note">${S.docs} documents, in the order you would read them.</p>
        <div class="docs">${DATA.DOCS.map((t, i) =>
          `<div><span>${String(i + 1).padStart(2, '0')}</span><b>${t}</b></div>`).join('')}</div>
      </section>

      <section class="band">
        <h2 class="band__title">An extract</h2>
        <div class="extract">
          <p class="extract__body">${d.opens || ''}</p>
          <p class="extract__cut">The rest of this section, and the ${p.sources} sources behind it, are in the pack.</p>
        </div>
      </section>

      <div class="cited">
        <b>${p.sources} sources, every one of them a page you can open.</b>
        <p>No claim in this pack is ours. Each one carries the address it came from and the date it was checked, so you can disagree with the conclusion and still trust the evidence.</p>
        <cite>Source-or-die: an unsourced number never ships.</cite>
      </div>
    </div>

    <aside class="artefact__rail">
      <div class="buy">
        <p class="buy__price"><b>£${p.price}</b><span>once, not a subscription</span></p>
        <a class="btn" href="#account">Buy this pack</a>
        <p class="buy__terms"><b>${S.refundDays}-day refund.</b> No reason required, and you keep nothing you have to send back.</p>
      </div>

      <div class="scope">
        <div><b>${p.sources}</b><span>Sources</span></div>
        <div><b>${p.payback}&times;</b><span>Payback</span></div>
        <div><b>${S.docs}</b><span>Documents</span></div>
        <div><b>${DATA.CHECKS.length}</b><span>Checks</span></div>
      </div>

      <dl class="publisher">${pub}</dl>

      <nav class="related" aria-label="Other packs">${related}</nav>
    </aside>
  </div>`;
}

/* One place decides which view is on screen. Anything else — a link, the back
   button, a hand-typed URL — goes through the hash. */
function route() {
  const m = (location.hash || '').match(/^#\/pack\/(.+)$/);
  const p = m ? packById(decodeURIComponent(m[1])) : null;

  if (m && !p) {                       /* a pack id that does not exist */
    viewHome.hidden = true;
    viewPack.hidden = false;
    viewPack.innerHTML = `<nav class="crumbs"><a href="#catalogue">Catalogue</a></nav>
      <div class="artefact"><div class="artefact__main">
        <h1 class="artefact__title" id="packTitle" tabindex="-1">No pack with that reference.</h1>
        <p class="artefact__deck">The address asked for <code>${decodeURIComponent(m[1])}</code>. Every pack in the catalogue is listed below the fold.</p>
        <p><a class="btn" href="#catalogue">Back to the catalogue</a></p>
      </div></div>`;
    document.title = 'Not found — ' + DOC_TITLE;
  } else if (p) {
    renderPack(p);
    viewHome.hidden = true;
    viewPack.hidden = false;
    document.title = p.t + ' — ' + DOC_TITLE;
  } else {
    viewPack.hidden = true;
    viewPack.innerHTML = '';
    viewHome.hidden = false;
    document.title = DOC_TITLE;
  }

  /* Repaint. The pack view owns a canvas that did not exist when the look was
     applied, so the treatment has to be drawn onto it now. draw() is
     idempotent and cheap — the sampled source is cached per pack and size. */
  /* Move focus to the new heading. Without this a keyboard user's focus stays
     on the link they just followed, which is now hidden, and the next Tab
     starts from the top of the document. */
  if (!viewPack.hidden) {
    const h = document.getElementById('packTitle');
    if (h) h.focus({ preventScroll: true });
    scrollTo(0, 0);
  }

  draw();
}

addEventListener('hashchange', route);
route();
