// @ledger writes | node tools.mjs | Generates tools.html, this ledger, by reading the disk and the logs.
/* ===========================================================================
   THE AUTOMATION LEDGER — every tool this experiment runs, and what it said.

   Criterion C32 asks for "all research tooling, sources, skills, everything
   used in this experiment". The obvious way to answer that is to write the
   list down. The obvious way is wrong for the same reason a hand-written
   contact sheet is wrong: a list is a CLAIM about the disk, and the disk
   moves. This reads the disk.

   Three things are derived rather than declared, so none of them can drift:

     the tools      every *.mjs and *.sh in this directory, whether or not
                    anybody remembered it existed;
     what they are  each tool's own `@ledger` tag and its own leading comment,
                    so the description lives beside the code it describes;
     what they said the real logs/, written by runlog.sh, including the exit
                    code — never a summary of a run, the run itself.

   A tool with no @ledger tag is listed as UNCLASSIFIED and is never run
   automatically. A tool with no log is listed as NOT RUN. Both are louder
   than an omission, which is the point: the failure mode of a ledger is
   silence, not error.
   =========================================================================== */
import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from 'fs';
import { join } from 'path';

const HERE = process.cwd();
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const kb = (n) => (n < 1024 ? n + ' B' : (n / 1024).toFixed(1) + ' KB');

/* ---- the tools ---------------------------------------------------------- */
const files = readdirSync(HERE).filter((f) => /\.(mjs|sh)$/.test(f)).sort();

const CLASS_NOTE = {
  'read-only': 'runs on every build; changes nothing',
  writes: 'produces an artifact; changes no source',
  mutates: 'REWRITES source — never run automatically',
  network: 'calls an external API — never run automatically',
  unclassified: 'no @ledger tag — never run automatically',
};

const tools = files.map((f) => {
  const src = readFileSync(join(HERE, f), 'utf8');
  const tag = src.match(/@ledger\s+(\S+)\s*\|\s*([^|\n]+?)\s*\|\s*([^\n]+)/);
  /* The prose comes from the file's own leading block comment. A description kept here instead
     would be a second copy of something already written once, and the two would disagree. */
  const block = src.match(/\/\*[\s\S]*?\*\//);
  let why = '';
  if (block) {
    why = block[0].replace(/^\/\*+|\*+\/$/g, '')
      .split('\n').map((l) => l.replace(/^\s*\*?\s?/, '')).join('\n')
      .replace(/^[=\s-]*\n/, '').trim();
  }
  /* AUDIT THE TAG. A tag is a claim by the tool about itself, and an unchecked claim is the
     thing this whole page exists to avoid. Anything that writes is caught here, so a tool
     cannot call itself read-only while it puts 20 screenshots on the disk — which verify.mjs
     did until this check was added. */
  const writeEvidence = [...new Set(
    (src.match(/writeFileSync|appendFileSync|rmSync|unlinkSync|renameSync|\.screenshot\(|>\s*"\$log"/g) || [])
  )];
  const disputed = tag && tag[1] === 'read-only' && writeEvidence.length ? writeEvidence : null;
  const base = f.replace(/\.(mjs|sh)$/, '');
  const logPath = join(HERE, 'logs', base + '.log');
  let log = null;
  if (existsSync(logPath)) {
    const text = readFileSync(logPath, 'utf8');
    const head = {};
    for (const line of text.split('\n').slice(0, 5)) {
      const m = line.match(/^(started|node|exit|duration)\s+(.*)$/);
      if (m) head[m[1]] = m[2];
    }
    const exit = (text.match(/\nexit\s+(\d+)/) || [])[1];
    const dur = (text.match(/\nduration\s+(\S+)/) || [])[1];
    const body = text.split('\n---\n').slice(1, -1).join('\n---\n') || text;
    /* A verdict line is found by shape, not by a per-tool pattern. A per-tool pattern is one
       more list to keep in step with eleven tools, and it fails silently when a tool changes
       its wording. */
    const verdict = body.split('\n').filter((l) =>
      /\b(ALL PASS|PASS|FAIL|FAILING|REFUS|ERROR|assertions|bytes|cells measured|— \d+ looks)\b/i.test(l)
    ).slice(0, 4);
    log = { text, exit, dur, started: head.started, node: head.node, body, verdict, bytes: statSync(logPath).size };
  }
  return {
    name: f, cls: tag ? tag[1] : 'unclassified', cmd: tag ? tag[2] : null, disputed,
    role: tag ? tag[3] : null, why, log, mtime: statSync(join(HERE, f)).mtime,
  };
});

/* ---- the outside world -------------------------------------------------- */
/* Every external host the automation touches, found by reading the source rather than by
   remembering. An API this experiment quietly depends on is exactly the thing a written list
   forgets, and it is the thing that breaks the build on somebody else's machine. */
const hosts = new Map();
const scan = (f) => {
  const s = readFileSync(join(HERE, f), 'utf8');
  for (const m of s.matchAll(/https?:\/\/([a-z0-9.-]+\.[a-z]{2,})/gi)) {
    const h = m[1].toLowerCase();
    if (!hosts.has(h)) hosts.set(h, new Set());
    hosts.get(h).add(f);
  }
};
for (const f of files) scan(f);
for (const f of ['parts/01-head.html', 'parts/05-engine.js', 'data.js']) {
  if (existsSync(join(HERE, f))) scan(f);
}

const ran = tools.filter((t) => t.log);
const green = ran.filter((t) => t.log.exit === '0');
const logBytes = ran.reduce((n, t) => n + t.log.bytes, 0);
const stamp = new Date().toISOString().replace('T', ' ').slice(0, 16) + ' UTC';

const card = (t) => `
<article class="tool" id="${esc(t.name)}">
  <header class="tool__head">
    <h3>${esc(t.name)}</h3>
    <span class="cls cls--${esc(t.cls)}">${esc(t.cls)}</span>
    ${t.cmd ? `<code class="cmd">${esc(t.cmd)}</code>` : ''}
  </header>
  ${t.role ? `<p class="role">${esc(t.role)}</p>` : ''}
  ${t.disputed ? `<p class="dispute">TAG DISPUTED — calls itself read-only, but its source contains ${t.disputed.map(esc).join(', ')}.</p>` : ''}
  ${t.why ? `<details class="why"><summary>why it exists, in its own words</summary><pre>${esc(t.why)}</pre></details>` : ''}
  ${t.log ? `
  <div class="run ${t.log.exit === '0' ? '' : 'run--bad'}">
    <div class="run__meta">
      <span><b>${t.log.exit === '0' ? 'exit 0' : 'exit ' + esc(t.log.exit ?? '?')}</b></span>
      <span>${esc(t.log.started || '')}</span>
      <span>${esc(t.log.dur || '')}</span>
      <span>${esc(t.log.node || '')}</span>
      <span>${kb(t.log.bytes)} of log</span>
    </div>
    ${t.log.verdict.length ? `<pre class="verdict">${t.log.verdict.map(esc).join('\n')}</pre>` : ''}
    <details class="full"><summary>the whole log, unedited</summary><pre>${esc(t.log.text)}</pre></details>
  </div>` : `<p class="norun">NOT RUN — no <code>logs/${esc(t.name.replace(/\.(mjs|sh)$/, ''))}.log</code> on disk. ${esc(CLASS_NOTE[t.cls] || '')}</p>`}
</article>`;

const order = ['read-only', 'writes', 'mutates', 'network', 'unclassified'];
const groups = order.map((c) => [c, tools.filter((t) => t.cls === c)]).filter(([, l]) => l.length);

const html = `<!doctype html>
<html lang="en" data-theme="dark"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Automation Ledger</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--ground:#131211;--card:#1B1A18;--card2:#211F1D;--hair:#2C2A27;--ink:#EFEBE4;--ink2:#A29B90;--ink3:#7B746A;
      --wax:#E2523B;--go:#7FB069;
      --mono:'IBM Plex Mono',ui-monospace,Menlo,monospace;--sans:'IBM Plex Sans',system-ui,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font:400 15px/1.6 var(--sans);
     -webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:44px 22px 96px}
h1{font:600 30px/1.15 var(--sans);letter-spacing:-.02em;margin:0 0 10px}
.lede{color:var(--ink2);max-width:66ch;margin:0 0 22px}
.counts{display:flex;flex-wrap:wrap;gap:8px 26px;font:500 12px/1 var(--mono);color:var(--ink3);
        border-top:1px solid var(--hair);border-bottom:1px solid var(--hair);padding:14px 0;margin-bottom:34px;
        font-variant-numeric:tabular-nums}
.counts b{color:var(--ink);font-weight:600}
.counts .bad b,.counts .bad{color:var(--wax)}
h2.sec{font:600 13px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ink3);
       margin:38px 0 6px;padding-bottom:9px;border-bottom:1px solid var(--hair)}
h2.sec b{color:var(--ink);font-weight:600}
.secnote{color:var(--ink3);font-size:13px;margin:0 0 18px}
.tool{background:var(--card);border:1px solid var(--hair);border-radius:4px;padding:16px 18px;margin:12px 0}
.tool__head{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.tool h3{font:600 15px/1 var(--mono);margin:0}
.cls{font:500 10px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;padding:5px 8px;border-radius:3px;
     border:1px solid var(--hair);color:var(--ink3)}
.cls--read-only{color:var(--go);border-color:#2F4A2A}
.cls--writes{color:var(--ink2)}
.cls--mutates,.cls--network,.cls--unclassified{color:var(--wax);border-color:#4A2A24}
.cmd{font:400 12px/1 var(--mono);color:var(--ink3);margin-left:auto}
.role{color:var(--ink2);margin:10px 0 0;max-width:78ch}
details{margin-top:12px}
summary{cursor:pointer;font:500 12px/1 var(--mono);color:var(--ink3);letter-spacing:.02em}
summary:hover{color:var(--ink)}
details pre{margin:10px 0 0;padding:12px 14px;background:var(--ground);border:1px solid var(--hair);border-radius:3px;
            font:400 12px/1.6 var(--mono);color:var(--ink2);white-space:pre-wrap;overflow-x:auto;max-height:460px;overflow-y:auto}
.run{margin-top:14px;border-top:1px solid var(--hair);padding-top:12px}
.run__meta{display:flex;flex-wrap:wrap;gap:6px 20px;font:400 11px/1 var(--mono);color:var(--ink3);
           font-variant-numeric:tabular-nums}
.run__meta b{color:var(--go);font-weight:600}
.run--bad .run__meta b{color:var(--wax)}
pre.verdict{margin:11px 0 0;padding:11px 13px;background:var(--card2);border-left:2px solid var(--go);
            font:500 12px/1.6 var(--mono);color:var(--ink);white-space:pre-wrap;overflow-x:auto}
.run--bad pre.verdict{border-left-color:var(--wax)}
.dispute{margin:10px 0 0;font:500 12px/1.5 var(--mono);color:var(--wax)}
.norun{margin:12px 0 0;font:400 12px/1.5 var(--mono);color:var(--wax)}
.norun code{color:var(--ink2)}
table{width:100%;border-collapse:collapse;margin-top:8px;font:400 13px/1.5 var(--mono)}
th{text-align:left;font-weight:500;color:var(--ink3);font-size:11px;letter-spacing:.1em;text-transform:uppercase;
   padding:8px 10px;border-bottom:1px solid var(--hair)}
td{padding:9px 10px;border-bottom:1px solid var(--hair);color:var(--ink2);vertical-align:top}
td:first-child{color:var(--ink)}
.scroll{overflow-x:auto}
footer{margin-top:52px;padding-top:18px;border-top:1px solid var(--hair);color:var(--ink3);font-size:13px;max-width:70ch}
a{color:var(--ink);text-decoration-color:var(--ink3);text-underline-offset:3px}
</style></head><body>
<div class="wrap">
<h1>The automation ledger</h1>
<p class="lede">Every tool this experiment runs, what it is for in its own words, and what it
actually said the last time it ran — the whole log, exit code included, not a summary of one.
This page is generated by <code>tools.mjs</code> from the directory and from <code>logs/</code>,
so a tool cannot be in the experiment and missing from the list.</p>

<div class="counts">
  <span><b>${tools.length}</b> tools</span>
  <span><b>${ran.length}</b> with a log</span>
  <span><b>${green.length}</b> exited 0</span>
  <span><b>${tools.length - ran.length}</b> not run</span>
  <span><b>${kb(logBytes)}</b> of log</span>
  <span><b>${hosts.size}</b> external hosts</span>
  <span${tools.some((t) => t.disputed) ? ' class="bad"' : ''}><b>${tools.filter((t) => t.disputed).length}</b> tags disputed</span>
  <span>generated ${esc(stamp)}</span>
  <span><a href="gallery.html">the contact sheet →</a></span>
</div>

${groups.map(([c, list]) => `
<h2 class="sec"><b>${esc(c)}</b> — ${esc(CLASS_NOTE[c])}</h2>
${list.map(card).join('')}`).join('')}

<h2 class="sec"><b>The outside world</b> — every host the source reaches for</h2>
<p class="secnote">Found by reading the files, not by remembering. A dependency nobody wrote down
is the one that breaks the build on the next machine.</p>
<div class="scroll"><table>
<thead><tr><th>host</th><th>referenced by</th></tr></thead>
<tbody>${[...hosts.entries()].sort().map(([h, fs]) =>
  `<tr><td>${esc(h)}</td><td>${[...fs].sort().map(esc).join(', ')}</td></tr>`).join('')}
</tbody></table></div>

<footer>How to add to this page: nothing. Drop a tool in this directory, give it an
<code>@ledger</code> tag on line 1, and run it through <code>./runlog.sh</code>. An untagged tool
still appears, marked unclassified; an unrun tool still appears, marked not run. The ledger is
built to be loud about what it does not know.</footer>
</div></body></html>`;

writeFileSync(join(HERE, 'tools.html'), html);
console.log(`tools.html: ${kb(Buffer.byteLength(html))} — ${tools.length} tools, ${ran.length} logged, ${green.length} green, ${tools.length - ran.length} not run, ${hosts.size} external hosts`);
