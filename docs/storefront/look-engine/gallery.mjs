// @ledger writes | node gallery.mjs | Generates gallery.html, the contact sheet, by reading the disk.
/* ===========================================================================
   THE CONTACT SHEET — every sample generated so far, on one page.

   Written as a GENERATOR rather than a page, for one reason: a hand-written
   index is a claim about the disk, and a claim about the disk goes stale the
   first time anyone adds a look. This reads the disk each time `./build.sh`
   runs, so the sheet cannot describe a sample that is not there, and cannot
   miss one that is.

   It never invents metadata. The look names, taglines, plate and treatment
   come out of parts/03-looks.js itself — evaluated, not regexed, so a rename
   in that file lands here on the next build with nothing to keep in step.
   =========================================================================== */

import { readFileSync, writeFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { join, basename, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = fileURLToPath(new URL('.', import.meta.url)).replace(/\/$/, '');

/* --- The look data, from the source of truth. 03-looks.js is pure data with
   no imports, so evaluating it is exact where a regex would be a guess. */
const looksSrc = readFileSync(join(HERE, 'parts/03-looks.js'), 'utf8');
const LOOKS = new Function(looksSrc + '\n;return LOOKS;')();

/* The pack-page link needs a pack that exists. Taking the first id out of
   data.js means the button keeps working when the catalogue is re-cut; a
   hardcoded id would 404 silently on the one page the founder asked for. */
const dataSrc = readFileSync(join(HERE, 'data.js'), 'utf8');
const PACK_ID = (dataSrc.match(/id\s*:\s*'([A-Z]{2}-\d+)'/) || [, ''])[1];

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const kb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.round(n / 1024) + ' KB');
const when = (p) => new Date(statSync(p).mtimeMs).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
const stat = (p) => (existsSync(p) ? { size: kb(statSync(p).size), when: when(p), ms: statSync(p).mtimeMs } : null);

/* Every link is RELATIVE, including the sets in other folders, which come out
   as a run of `../`. An absolute file:// URL was the first cut and it was
   wrong: it works from disk and is dead over a web server, so the sheet would
   be half-broken in whichever way it was opened. A relative path works in
   both, provided the server is rooted at or above the common ancestor. */
const link = (abs) => relative(HERE, abs);

/* --- 1. The looks. Each is a live page plus two screenshots. ------------- */
const shotsDir = join(HERE, 'shots');
const looks = LOOKS.map((l) => {
  const light = join(shotsDir, `${l.id}-light.png`);
  const dark = join(shotsDir, `${l.id}-dark.png`);
  return { ...l, shots: { light: stat(light), dark: stat(dark) }, paths: { light, dark } };
});

/* --- 1b. The looks NOBODY designed. -------------------------------------
   `verify.mjs` writes shots/rolled.json when it runs gate A54, and this reads it.
   The sheet does NOT re-roll them itself: a second caller of the generator is a
   second implementation of it, and the two drift the day the catalogue changes.
   No record on disk means no section, rather than a section of guesses. */
const rolledPath = join(shotsDir, 'rolled.json');
const rolled = (existsSync(rolledPath) ? JSON.parse(readFileSync(rolledPath, 'utf8')) : []).map((r) => {
  const light = join(shotsDir, `${r.id}-light.png`);
  const dark = join(shotsDir, `${r.id}-dark.png`);
  return { ...r, shots: { light: stat(light), dark: stat(dark) }, paths: { light, dark } };
});
const face = (stack) => String(stack || '').split(',')[0].replace(/['"]/g, '').trim();

/* --- 2. Standalone pages that live beside the engine. -------------------- */
const SKIP = new Set(['looks-engine.html', 'gallery.html']);
const standalone = readdirSync(HERE)
  .filter((f) => f.endsWith('.html') && !SKIP.has(f))
  .map((f) => ({ name: f, abs: join(HERE, f), ...stat(join(HERE, f)) }))
  .sort((a, b) => b.ms - a.ms);

/* --- 3. Earlier generations, wherever they were left. --------------------
   Listed by root so a set that has been deleted disappears from the sheet
   instead of becoming a column of dead links. */
const ROOTS = [
  {
    title: 'Page mockups — the build bundle',
    note: 'The earlier sample set: twelve full screens, one file each, static.',
    dir: new URL('../../design/mumchimp-build-bundle/mockups', import.meta.url).pathname,
  },
];
const sets = ROOTS.filter((r) => existsSync(r.dir)).map((r) => ({
  ...r,
  files: readdirSync(r.dir).filter((f) => f.endsWith('.html'))
    .map((f) => ({ name: f, abs: join(r.dir, f), ...stat(join(r.dir, f)) }))
    .sort((a, b) => a.name.localeCompare(b.name)),
}));

/* --- 4. What the research produced. Not a sample, but the reason several of
   the samples look the way they do, so it belongs on the same page. */
const researchDir = join(HERE, 'research');
const research = existsSync(researchDir)
  ? readdirSync(researchDir).sort().map((f) => ({ name: f, abs: join(researchDir, f), ...stat(join(researchDir, f)) }))
  : [];

const engine = stat(join(HERE, 'looks-engine.html'));

/* A screenshot taken before the last source edit is a picture of a page that
   no longer exists. The sheet marks those rather than presenting them as
   current, because an unmarked stale shot is worse than no shot: it is a
   confident wrong answer about what the work looks like now. */
const SRC = ['parts', 'data.js', 'subjects.js'].map((f) => join(HERE, f));
const newestSrc = SRC.reduce((n, p) => {
  const walk = (x) => (statSync(x).isDirectory()
    ? readdirSync(x).reduce((m, f) => Math.max(m, walk(join(x, f))), 0)
    : statSync(x).mtimeMs);
  return existsSync(p) ? Math.max(n, walk(p)) : n;
}, 0);
const isStale = (s) => !!s && s.ms < newestSrc;
const shotCount = looks.reduce((n, l) => n + (l.shots.light ? 1 : 0) + (l.shots.dark ? 1 : 0), 0);
const staleCount = looks.reduce((n, l) => n + (isStale(l.shots.light) ? 1 : 0) + (isStale(l.shots.dark) ? 1 : 0), 0);
const generated = new Date().toLocaleString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });

/* --- The page ------------------------------------------------------------ */
const lookCard = (l) => {
  const pane = (theme) => {
    const s = l.shots[theme];
    if (!s) return `<div class="pane pane--missing"><span>no ${theme} shot on disk</span></div>`;
    const src = link(l.paths[theme]);
    const stale = isStale(s);
    return `<a class="pane${stale ? ' pane--stale' : ''}" href="${esc(src)}" title="${esc(l.name)} — ${theme}, ${esc(s.when)}${stale ? ', older than the source' : ''}">
        <img loading="lazy" src="${esc(src)}" alt="${esc(l.name)}, ${theme} theme">
        <span class="pane__tag">${theme} · ${s.size}${stale ? ' · <b>stale</b>' : ''}</span>
      </a>`;
  };
  return `<article class="card" data-name="${esc((l.name + ' ' + l.id + ' ' + l.plate + ' ' + l.treatment).toLowerCase())}">
    <div class="card__shots">${pane('light')}${pane('dark')}</div>
    <div class="card__body">
      <h3><span class="dot" style="background:${esc(l.dot)}"></span>${esc(l.name)}</h3>
      <p class="tagline">${esc(l.tagline)}</p>
      <dl class="facts">
        <div><dt>id</dt><dd>${esc(l.id)}</dd></div>
        <div><dt>plate</dt><dd>${esc(l.plate)}</dd></div>
        <div><dt>treatment</dt><dd>${esc(l.treatment)}</dd></div>
      </dl>
      <p class="go">
        <a class="btn" href="looks-engine.html?look=${esc(l.id)}&amp;theme=light">Open light</a>
        <a class="btn" href="looks-engine.html?look=${esc(l.id)}&amp;theme=dark">Open dark</a>
        ${PACK_ID ? `<a class="btn btn--quiet" href="looks-engine.html?look=${esc(l.id)}&amp;theme=light#/pack/${esc(PACK_ID)}">Pack page</a>` : ''}
      </p>
    </div>
  </article>`;
};

/* The rolled card carries no "open this look" button on purpose. A rolled look lives in the
   page's memory and does not survive a reload, so a link to `?look=roll-101` would 404 into the
   default look and read as a working link. The console line under it is the honest way back. */
const rolledCard = (r) => {
  const pane = (theme) => {
    const s = r.shots[theme];
    if (!s) return `<div class="pane pane--missing"><span>no ${theme} shot on disk</span></div>`;
    const src = link(r.paths[theme]);
    const stale = isStale(s);
    return `<a class="pane${stale ? ' pane--stale' : ''}" href="${esc(src)}" title="${esc(r.name)} — ${theme}, ${esc(s.when)}">
        <img loading="lazy" src="${esc(src)}" alt="${esc(r.name)}, ${theme} theme">
        <span class="pane__tag">${theme} · ${s.size}${stale ? ' · <b>stale</b>' : ''}</span>
      </a>`;
  };
  return `<article class="card card--rolled">
    <div class="card__shots">${pane('light')}${pane('dark')}</div>
    <div class="card__body">
      <h3><span class="dot" style="background:${esc(r.accent_light || '#888')}"></span>${esc(r.name)}<span class="flag">rolled</span></h3>
      <p class="tagline">${esc(r.tagline || '')}</p>
      <dl class="facts">
        <div><dt>display</dt><dd>${esc(face(r.display))}</dd></div>
        <div><dt>body</dt><dd>${esc(face(r.body))}</dd></div>
        <div><dt>plate</dt><dd>${esc(r.plate)}</dd></div>
        <div><dt>treatment</dt><dd>${esc(r.treatment)}</dd></div>
        <div><dt>hue</dt><dd>${esc(r.seed && r.seed.hue)}</dd></div>
        <div><dt>accent hue</dt><dd>${esc(r.seed && r.seed.accentHue)}</dd></div>
      </dl>
      <p class="recall">Open the engine and run <code>window.rollNewLook(${esc(String(r.id).replace('roll-', ''))})</code> — same number, same look, forever.</p>
    </div>
  </article>`;
};

const fileRow = (f) => `<li><a href="${esc(link(f.abs))}">${esc(f.name)}</a><span>${esc(f.size || '')}</span><span>${esc(f.when || '')}</span></li>`;

const html = `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contact Sheet</title>
<style>
/* A proof sheet, so: neutral dark ground, no colour of its own beyond a wax
   pencil red for the marks. The samples supply every other colour on the
   page and the frame must not compete with them. */
:root{
  --ground:#131211; --card:#1B1A18; --well:#0E0D0C;
  --hair:#2C2A27; --ink:#EFEBE4; --ink2:#A19A8F; --ink3:#6E6961;
  --wax:#E2523B;
  --mono:ui-monospace,'SF Mono',SFMono-Regular,Menlo,monospace;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
     font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1400px;margin:0 auto;padding:0 24px 96px}

header.top{position:sticky;top:0;z-index:5;background:rgba(19,18,17,.92);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--hair)}
.top__in{max-width:1400px;margin:0 auto;padding:16px 24px;display:flex;gap:20px;
  align-items:baseline;flex-wrap:wrap}
.top h1{font-size:19px;margin:0;letter-spacing:-.01em;font-weight:650}
.top h1 em{font-style:normal;color:var(--wax)}
.counts{font-family:var(--mono);font-size:12px;color:var(--ink2);
  font-variant-numeric:tabular-nums;display:flex;gap:14px;flex-wrap:wrap}
.counts b{color:var(--ink);font-weight:600}
#q{margin-left:auto;background:var(--well);border:1px solid var(--hair);color:var(--ink);
  border-radius:2px;padding:7px 10px;font-family:var(--mono);font-size:12px;width:200px}
#q:focus{outline:2px solid var(--wax);outline-offset:1px}

.note{border-left:2px solid var(--wax);padding:10px 0 10px 14px;margin:28px 0 0;
  color:var(--ink2);font-size:13.5px;max-width:70ch}
.note code{font-family:var(--mono);color:var(--ink);font-size:12.5px}

h2.sec{font-size:12px;font-family:var(--mono);text-transform:uppercase;
  letter-spacing:.16em;color:var(--ink3);margin:56px 0 4px;
  border-top:1px solid var(--hair);padding-top:14px}
h2.sec b{color:var(--ink);font-weight:500}
.sec__note{color:var(--ink2);font-size:13.5px;margin:0 0 22px;max-width:70ch}

.grid{display:grid;gap:22px;grid-template-columns:repeat(auto-fill,minmax(400px,1fr))}
.card{background:var(--card);border:1px solid var(--hair);border-radius:3px;overflow:hidden;
  display:flex;flex-direction:column}
.card__shots{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--hair)}
.pane{position:relative;display:block;background:var(--well);aspect-ratio:4/3;overflow:hidden}
.pane img{width:100%;height:100%;object-fit:cover;object-position:top center;display:block;
  transition:transform .35s ease}
.pane:hover img{transform:scale(1.03)}
.pane__tag{position:absolute;left:0;bottom:0;background:rgba(14,13,12,.82);color:var(--ink2);
  font-family:var(--mono);font-size:10.5px;padding:3px 7px;letter-spacing:.04em}
.pane--missing{display:grid;place-items:center;color:var(--ink3);font-family:var(--mono);font-size:11px}
.pane--stale img{opacity:.55;filter:saturate(.55)}
.pane--stale .pane__tag b{color:var(--wax);font-weight:600}
.counts .warn{color:var(--wax)}
.counts a{color:var(--ink);text-decoration-color:var(--ink3);text-underline-offset:3px}
.card__body{padding:16px 18px 18px}
.card h3{margin:0 0 6px;font-size:18px;font-weight:650;letter-spacing:-.01em;
  display:flex;align-items:center;gap:9px}
.dot{width:11px;height:11px;border-radius:50%;flex:none;box-shadow:0 0 0 1px rgba(255,255,255,.14)}
.tagline{margin:0 0 14px;color:var(--ink2);font-size:13.5px}
.facts{display:flex;flex-wrap:wrap;gap:0 20px;margin:0 0 14px;font-family:var(--mono);font-size:11.5px}
.facts div{display:flex;gap:6px}
.facts dt{color:var(--ink3);margin:0}
.facts dd{margin:0;color:var(--ink)}
.go{margin:0;display:flex;gap:8px;flex-wrap:wrap}
.btn{font-family:var(--mono);font-size:11.5px;text-decoration:none;padding:6px 11px;
  border:1px solid var(--hair);border-radius:2px;color:var(--ink);background:var(--well)}
.btn:hover{border-color:var(--wax);color:var(--wax)}
.btn--quiet{color:var(--ink3)}
.card--rolled{border-style:dashed}
.flag{font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--wax);border:1px solid var(--wax);border-radius:2px;padding:1px 5px;font-weight:500}
.recall{margin:0;color:var(--ink3);font-size:12.5px}
.recall code{font-family:var(--mono);color:var(--ink2);font-size:11.5px}

ul.files{list-style:none;margin:0;padding:0;border-top:1px solid var(--hair);
  columns:2;column-gap:32px}
ul.files li{display:flex;gap:12px;align-items:baseline;padding:7px 2px;
  border-bottom:1px solid var(--hair);break-inside:avoid;font-family:var(--mono);font-size:12px}
ul.files a{flex:1;text-decoration:none;font-family:var(--sans);font-size:14px}
ul.files a:hover{color:var(--wax)}
ul.files span{color:var(--ink3);font-variant-numeric:tabular-nums;white-space:nowrap}

footer{margin-top:64px;padding-top:18px;border-top:1px solid var(--hair);
  color:var(--ink3);font-family:var(--mono);font-size:11.5px}
@media (max-width:640px){ .grid{grid-template-columns:1fr} ul.files{columns:1} #q{width:100%;margin:8px 0 0} }
</style>
</head><body>

<header class="top"><div class="top__in">
  <h1>Contact sheet <em>·</em> mumchimp storefront</h1>
  <div class="counts">
    <span><b>${looks.length}</b> looks${rolled.length ? ` + <b>${rolled.length}</b> rolled` : ''}</span>
    <span><b>${shotCount}</b> screenshots${staleCount ? `, <b class="warn">${staleCount} stale</b>` : ''}</span>
    <span><b>${sets.reduce((n, s) => n + s.files.length, 0) + standalone.length}</b> pages</span>
    <span>engine <b>${engine ? engine.size : 'missing'}</b></span>
    <span>built <b>${esc(generated)}</b></span>
    <span><a href="tools.html">the automation ledger &rarr;</a></span>
  </div>
  <input id="q" type="search" placeholder="filter looks  (press /)" autocomplete="off">
</div></header>

<div class="wrap">

<p class="note">This page is generated from the disk, not written by hand: <code>node gallery.mjs</code>,
which <code>./build.sh</code> runs on every build. Nothing here can describe a sample that is not on disk,
and nothing on disk can be missing from it. Links are relative, so serve it from
<code>/private/tmp/claude-501</code> (or open it from disk) and every set on the page resolves.</p>

<h2 class="sec"><b>The looks</b> — one component tree, ${looks.length} identities</h2>
<p class="sec__note">Every look is the same markup under a different <code>data-look</code>. The screenshots
are dimmed and marked <b>stale</b> when they were taken before the last source edit — <code>node verify.mjs</code>
re-takes all twenty and re-runs the contrast, overflow and tap-target gates. The buttons always open the live
engine, which is the thing that is actually true.</p>
<div class="grid" id="looks">${looks.map(lookCard).join('\n')}</div>

${rolled.length ? `<h2 class="sec"><b>Looks nobody designed</b> — gate A54</h2>
<p class="sec__note">Ten hand-built looks only ever prove ten hand-built looks. These ${rolled.length} were
rolled from a number by <code>parts/09-roll.js</code> — palette seed, type pairing, form metrics, plate,
treatment and switches, all from one seeded PRNG — and then measured by the same eight browser checks as the
ten, at four viewports in both themes. Nobody chose a colour or a typeface on this row.</p>
<div class="grid">${rolled.map(rolledCard).join('\n')}</div>` : ''}

${sets.map((s) => `<h2 class="sec"><b>${esc(s.title)}</b></h2>
<p class="sec__note">${esc(s.note)}</p>
<ul class="files">${s.files.map(fileRow).join('')}</ul>`).join('\n')}

${standalone.length ? `<h2 class="sec"><b>One-off pages</b> — beside the engine</h2>
<p class="sec__note">Earlier standalone mockups, kept because they are what the looks were cut down from.</p>
<ul class="files">${standalone.map(fileRow).join('')}</ul>` : ''}

${research.length ? `<h2 class="sec"><b>Research</b> — why several of these look the way they do</h2>
<p class="sec__note">Banked to disk so it survives a session ending. Each file is findings with sources, not notes.</p>
<ul class="files">${research.map(fileRow).join('')}</ul>` : ''}

<footer>Generated ${esc(generated)} from ${esc(HERE)} — re-run <code>./build.sh</code> to refresh.</footer>
</div>

<script>
/* Filter is the only script on the page. It matches the name, id, plate and
   treatment that the generator already wrote onto each card, so it needs no
   copy of the data. */
const q = document.getElementById('q');
const cards = [...document.querySelectorAll('#looks .card')];
q.addEventListener('input', () => {
  const v = q.value.trim().toLowerCase();
  for (const c of cards) c.hidden = v && !c.dataset.name.includes(v);
});
addEventListener('keydown', (e) => {
  if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); q.select(); }
  if (e.key === 'Escape' && document.activeElement === q) { q.value = ''; q.dispatchEvent(new Event('input')); q.blur(); }
});
</script>
</body></html>
`;

writeFileSync(join(HERE, 'gallery.html'), html);
console.log(`gallery.html: ${(html.length / 1024).toFixed(1)} KB — ${looks.length} looks, ${shotCount} shots, ` +
  `${rolled.length} rolled, ${sets.reduce((n, s) => n + s.files.length, 0)} bundled pages, ${standalone.length} one-offs, ${research.length} research files`);
