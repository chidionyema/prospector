/**
 * Every listed document is drawn by something that can read it, and the frame stays inert.
 *
 * The defect this pins, measured 2026-08-21 on origin/main (9e2cfef2): 18 `.html` documents were
 * tracked and listed on `/docs` with `readable: true`, and both readers drew them as text —
 * `docs.tsx` through `react-markdown` with raw HTML disabled, `/s/<token>` through a bare `<pre>`.
 * Each page carried its own copy of the rule, so neither could be fixed by fixing the other.
 *
 * What a source scan can and cannot prove, stated plainly because this file is mostly a scan.
 * It CANNOT prove a document renders correctly — no scanner sees a browser lay out a page. What
 * it CAN prove is that neither reader has its own renderer any more, and that the one sandbox
 * both of them use has not quietly gained `allow-scripts`. Both are the mechanical half of the
 * defect, and both are how it came back if it comes back.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  FRAME_PREAMBLE,
  FRAME_SANDBOX,
  framedSrcDoc,
  isFullDocument,
  kindOf,
  suffixOf,
} from '@/lib/docKind';

const SRC = fileURLToPath(new URL('../src', import.meta.url));
const DOCS_PAGE = `${SRC}/pages/docs.tsx`;
const SHARE_PAGE = `${SRC}/pages/s/[token].tsx`;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = `${dir}/${name}`;
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(full)) out.push(full);
  }
  return out;
}

describe('which renderer a document gets', () => {
  it('reads the suffix the way the python side does', () => {
    expect(suffixOf('docs/ENGINE_END_TO_END.html')).toBe('.html');
    expect(suffixOf('docs/LINKS.MD')).toBe('.md');
    expect(suffixOf('tools/NOTES')).toBe('');
    // A dot in a directory name is not the file's suffix, and a dotfile has no suffix at all.
    expect(suffixOf('docs/v1.2/README.md')).toBe('.md');
    expect(suffixOf('.gitignore')).toBe('');
  });

  it('frames html, renders markdown, and shows everything else as source', () => {
    expect(kindOf('docs/ENGINE_END_TO_END.html')).toBe('html');
    expect(kindOf('docs/design/mockups/index.htm')).toBe('html');
    expect(kindOf('docs/DECISIONS.md')).toBe('markdown');
    // JSON through a markdown parser is one long paragraph, which is worse than the file.
    expect(kindOf('docs/incidents/INC-2026-08-20.json')).toBe('source');
    expect(kindOf('tools/NOTES.txt')).toBe('source');
  });

  it('draws an unrecognised format as source rather than blank', () => {
    // The python read fence decides what may be read at all. Anything that gets past it and has
    // no branch here must still put something on screen: source is never wrong, and an empty
    // panel is the "listed and unreadable" defect wearing a different face.
    expect(kindOf('docs/whatever.rst')).toBe('source');
    expect(kindOf('Makefile')).toBe('source');
  });
});

describe('the frame cannot run anything', () => {
  it('never grants allow-scripts', () => {
    // `allow-same-origin` alone is safe because nothing in the frame can execute. Adding
    // `allow-scripts` beside it removes the sandbox altogether — the frame could reach `parent` —
    // and it is the change someone chasing an auto-height bug reaches for first.
    expect(FRAME_SANDBOX).not.toMatch(/allow-scripts/);
    expect(FRAME_SANDBOX.split(/\s+/)).toEqual(['allow-same-origin']);
  });

  it('injects layout only, never behaviour', () => {
    expect(FRAME_PREAMBLE).not.toMatch(/<script/i);
    expect(FRAME_PREAMBLE).not.toMatch(/\bon[a-z]+=/i);
  });

  it('no component in the console injects unsanitised markup', () => {
    // The prop IN USE, not the word. `DocBody.tsx` explains in its own docstring why it uses a
    // frame and not `dangerouslySetInnerHTML`, and a scan for the bare identifier failed on that
    // sentence — a test that grades prose instead of code. Both real forms are covered: the JSX
    // attribute (`={`) and the prop set in an object that is then spread (`:`).
    const inUse = /dangerouslySetInnerHTML\s*[:=]/;
    const offenders = walk(SRC).filter((f) => inUse.test(readFileSync(f, 'utf8')));
    expect(offenders.map((f) => f.slice(SRC.length))).toEqual([]);
  });
});

describe('assembling the framed document', () => {
  // Both shapes are tracked in this repo. Measured 2026-08-21: 14 of the 18 `.html` files are
  // whole documents (`docs/design/mumchimp-build-bundle/**`), 4 are body fragments written to be
  // wrapped by something else (`docs/storefront/look-engine/**`).
  const WHOLE = '<!DOCTYPE html><html lang="en"><head><title>x</title></head><body>hi</body></html>';
  const FRAGMENT = '<h1>hi</h1><p>a fragment, no doctype and no head</p>';

  it('tells a whole document from a body fragment', () => {
    expect(isFullDocument(WHOLE)).toBe(true);
    expect(isFullDocument('\uFEFF\n  <!-- a note -->\n<!doctype html><html>')).toBe(true);
    expect(isFullDocument(FRAGMENT)).toBe(false);
    // The one that would have been misread: a fragment whose first tag merely STARTS with "head".
    expect(isFullDocument('<header class="masthead">x</header>')).toBe(false);
  });

  it('never displaces the doctype', () => {
    // A doctype that is not first in the stream is not a doctype: the browser drops the page into
    // quirks mode, where box-sizing and percentage heights all behave differently, and nothing on
    // screen says why. This is the reason `framedSrcDoc` exists instead of string concatenation.
    const out = framedSrcDoc(WHOLE);
    expect(out.startsWith('<!DOCTYPE html>')).toBe(true);
    expect(out).toContain(FRAME_PREAMBLE);
    expect(out.indexOf(FRAME_PREAMBLE)).toBeGreaterThan(out.indexOf('<head>'));
  });

  it('puts the preamble first inside the head, so the document overrules it', () => {
    // Ours arrives before the document's own stylesheet, so on any rule they both set the
    // document wins. Showing a page as it was written is the point of the frame.
    const out = framedSrcDoc(WHOLE);
    expect(out.indexOf(FRAME_PREAMBLE)).toBeLessThan(out.indexOf('<title>'));
  });

  it('puts the preamble in front of a fragment, and adds nothing else', () => {
    const out = framedSrcDoc(FRAGMENT);
    expect(out).toBe(FRAME_PREAMBLE + FRAGMENT);
  });

  it('injects exactly once, whatever the shape', () => {
    for (const text of [WHOLE, FRAGMENT, '<!doctype html><html><body>no head element</body></html>']) {
      expect(framedSrcDoc(text).length).toBe(text.length + FRAME_PREAMBLE.length);
    }
  });
});

describe('both readers share one renderer', () => {
  it('the docs page and the share page both use DocBody', () => {
    for (const page of [DOCS_PAGE, SHARE_PAGE]) {
      expect(readFileSync(page, 'utf8')).toMatch(/from '@\/components\/DocBody'/);
    }
  });

  it('neither page decides how to draw a document itself', () => {
    // The rule lives in one file. A page that imports the markdown renderer directly has started
    // a second copy of it, which is exactly how the two readers drifted apart the first time.
    for (const page of [DOCS_PAGE, SHARE_PAGE]) {
      const text = readFileSync(page, 'utf8');
      expect(text).not.toMatch(/from 'react-markdown'/);
      expect(text).not.toMatch(/from 'remark-gfm'/);
    }
  });

  it('the share page still renders a document with no session', () => {
    // `pages.test.ts` excludes `/pages/s/` from the "every screen reads through the one hook"
    // rule, and that exclusion is only safe while this page keeps reaching exactly one
    // session-less route. Adding a renderer must not have added a door.
    const text = readFileSync(SHARE_PAGE, 'utf8');
    expect(text).not.toMatch(/from '@\/lib\/useOps'/);
    expect(text).not.toMatch(/from '@\/components\/Shell'/);
  });
});
