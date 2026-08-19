/**
 * Properties of the pages themselves, checked by reading the source.
 *
 * Be clear about what a source scan can and cannot prove. It CANNOT prove "no engine metric is
 * derived in TypeScript" — a scanner cannot see a number built at render time, and claiming
 * otherwise would be exactly the kind of green-that-measures-nothing this repo has been bitten by.
 * What it CAN prove is mechanical and still worth pinning: no page opens a second data path, every
 * screen renders the "read N ago" stamp the founder asked for, and the console's view list has not
 * drifted from the gateway's.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../src', import.meta.url));
const REPO = fileURLToPath(new URL('../../../..', import.meta.url));

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = `${dir}/${name}`;
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(full)) out.push(full);
  }
  return out;
}

const ALL = walk(SRC);
const PAGES = ALL.filter((f) => f.includes('/pages/') && !f.includes('/pages/api/'));
/**
 * Screens an operator reads. Four exclusions, each for a different reason:
 *
 *   `_app` and `_document` are Next wrappers, not screens: neither renders data of its own, so
 *      neither can read through the hook or carry an as-of stamp.
 *   `login` has nothing read yet to stamp, because reading is what it gates.
 *   `pages/s/` is the PUBLIC share view. It is not an operator screen at all: it has no session,
 *      so it cannot use `useOps` (which calls the authed `/api/ops/read` door), and wrapping it in
 *      the Shell would show an outsider the estate's navigation. The exclusion is narrow and its
 *      narrowness is pinned by `share.test.ts`, which asserts that page reaches exactly one
 *      session-less route and imports neither Shell nor the ops client.
 */
const SCREENS = PAGES.filter(
  (f) => !/_app\.tsx$|_document\.tsx$|login\.tsx$|\/pages\/s\//.test(f),
);

describe('one data path', () => {
  it('no page or component reaches the filesystem or spawns anything', () => {
    const offenders = ALL.filter((f) => !f.endsWith('/lib/ops.ts')).filter((f) =>
      /from '(node:)?(fs|child_process|path|os)'/.test(readFileSync(f, 'utf8')),
    );
    expect(offenders.map((f) => f.slice(SRC.length))).toEqual([]);
  });

  it('every screen reads through the one hook', () => {
    const offenders = SCREENS.filter((f) => !readFileSync(f, 'utf8').includes("from '@/lib/useOps'"));
    expect(offenders.map((f) => f.slice(SRC.length))).toEqual([]);
  });

  it('no screen calls fetch directly', () => {
    const offenders = SCREENS.filter((f) => /\bfetch\(/.test(readFileSync(f, 'utf8')));
    expect(offenders.map((f) => f.slice(SRC.length))).toEqual([]);
  });
});

describe('every screen says when it read', () => {
  it('renders the as-of stamp', () => {
    const offenders = SCREENS.filter((f) => !readFileSync(f, 'utf8').includes('<AsOf'));
    expect(offenders.map((f) => f.slice(SRC.length))).toEqual([]);
  });
});

describe('the console and the gateway agree on what exists', () => {
  const gateway = readFileSync(`${REPO}/prospector/ops/console_api.py`, 'utf8');

  function pythonRegistry(name: string): string[] {
    const block = gateway.split(`\n${name}`)[1] ?? '';
    const body = block.slice(0, block.indexOf('\n}'));
    return [
      ...[...body.matchAll(/^\s{4}"([a-z_.]+)":/gm)].map((m) => m[1]),
      // A handler defined after the literal is registered on its own line instead. `job` is one:
      // it needs the tool timeout, which is declared 600 lines below the READS table.
      ...[...gateway.matchAll(new RegExp(`^${name}\\["([a-z_.]+)"\\]\\s*=`, 'gm'))].map(
        (m) => m[1],
      ),
    ];
  }

  it('every view this console offers exists in the gateway', async () => {
    const { VIEWS } = await import('@/pages/api/ops/read/[view]');
    const python = pythonRegistry('READS');
    expect(python.length).toBeGreaterThan(5);
    expect([...VIEWS].filter((v) => !python.includes(v))).toEqual([]);
  });

  it('every action this console offers exists in the gateway', async () => {
    const { ACTIONS } = await import('@/pages/api/ops/act/[action]');
    const python = pythonRegistry('ACTIONS');
    expect(python.length).toBeGreaterThan(3);
    expect([...ACTIONS].filter((a) => !python.includes(a))).toEqual([]);
  });
});

describe('a link that goes somewhere does something when it lands', () => {
  /**
   * The estate's recurring defect is "built and unreachable": a thing exists, a link points at it,
   * and the target ignores what the link said. The Incidents page deep-links a record into the
   * Docs page as `/docs?open=<name>`, and the first version of that link was inert because Docs
   * kept its selection in local state and never looked at the query string.
   *
   * So: any page that emits `/route?param=` must be answered by a page that reads `query.param`.
   */
  const LINKS = /href=[{]?[`'"]\/([a-z0-9-]+)\?([a-z_]+)=/g;

  it('every query-string link is read by the page it points at', () => {
    const found: string[] = [];
    const inert: string[] = [];
    for (const file of SCREENS) {
      const text = readFileSync(file, 'utf8');
      for (const [, route, param] of text.matchAll(LINKS)) {
        found.push(`/${route}?${param}`);
        const target = SCREENS.find((f) => f.endsWith(`/pages/${route}.tsx`));
        if (!target) {
          inert.push(`/${route}?${param} — no such page`);
          continue;
        }
        if (!new RegExp(`query\\.${param}\\b`).test(readFileSync(target, 'utf8'))) {
          inert.push(`/${route}?${param} — ${route}.tsx never reads it`);
        }
      }
    }
    // Anti-vacuity. If nothing matched, this test proves nothing and must say so.
    expect(found.length).toBeGreaterThan(0);
    expect(inert).toEqual([]);
  });
});

describe('no page scrolls the whole document sideways', () => {
  it('wide content is wrapped, and the body cannot scroll horizontally', () => {
    const css = readFileSync(`${SRC}/styles/globals.css`, 'utf8');
    expect(css).toMatch(/body[^}]*overflow-x:\s*hidden/s);
    // Any table wide enough to need it must sit inside the one component that scrolls.
    const offenders = SCREENS.filter((f) => {
      const text = readFileSync(f, 'utf8');
      return /min-w-\[/.test(text) && !text.includes('<Scroll>');
    });
    expect(offenders.map((f) => f.slice(SRC.length))).toEqual([]);
  });
});
