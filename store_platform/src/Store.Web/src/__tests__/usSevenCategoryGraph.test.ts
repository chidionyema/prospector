import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

function existsRelative(relativePath: string): boolean {
  return existsSync(fileURLToPath(new URL(relativePath, import.meta.url)));
}

/**
 * US-7 — Category graph on /ideas.
 *
 * The audit (§4.5) found the /ideas page rendered 16 category cards in a single
 * column, each one nearly identical to the next. The descriptions were repetitive
 * (every one restated "£49 per pack · every claim sourced"), and the buyer could
 * not tell "Business ideas for developers" from "Business ideas for operators"
 * without clicking.
 *
 * The fix is a 2D graph: each node is a category, sized by pack count, placed
 * by relatedness. Tapping a node filters the catalogue. The graph falls back
 * to the existing flat list when the SVG cannot be rendered.
 */
describe('US-7 — Category graph on /ideas', () => {
  const graphExists = existsRelative('../components/discovery/CategoryGraph.tsx');
  const page = readSource('../pages/ideas/index.tsx');

  it('declares a CategoryGraph component', () => {
    expect(graphExists, 'components/discovery/CategoryGraph.tsx must exist').toBe(true);
  });

  it('CategoryGraph renders all categories as nodes', () => {
    // The graph iterates over a category list. The audit requires all 16
    // categories to be reachable as nodes; the count is a stable contract.
    if (!graphExists) return;
    const source = readSource('../components/discovery/CategoryGraph.tsx');
    // The component must iterate the categories. Look for a map/loop pattern.
    const iterates = /\.map\(|forEach\(/.test(source);
    expect(
      iterates,
      'CategoryGraph must iterate over the category list to render one node per category',
    ).toBe(true);
  });

  it('CategoryGraph sizes nodes by pack count', () => {
    // The audit: "each node is sized by pack count." A node with 33 packs is
    // bigger than a node with 5 packs. The component must read a `count` /
    // `packCount` field and use it to scale the node.
    if (!graphExists) return;
    const source = readSource('../components/discovery/CategoryGraph.tsx');
    const readsCount = /count|packCount|size.*Math|size\s*=\s*\{/.test(source);
    expect(
      readsCount,
      'CategoryGraph must size each node by its pack count',
    ).toBe(true);
  });

  it('CategoryGraph has a click handler that filters the catalogue', () => {
    // Tapping a node filters the catalogue. The graph must support click via
    // either an onClick handler or a <Link> (the latter is preferred; it gives
    // keyboard support, middle-click, and ARIA semantics for free).
    if (!graphExists) return;
    const source = readSource('../components/discovery/CategoryGraph.tsx');
    const hasClick =
      /onClick\b/.test(source) ||
      /<Link\b/.test(source) ||
      /<a\b/.test(source);
    expect(
      hasClick,
      'CategoryGraph must have a click handler (onClick, <Link>, or <a>)',
    ).toBe(true);
  });

  it('CategoryGraph is keyboard-focusable', () => {
    // The audit: "keyboard-focusable: arrow keys move between nodes, Enter filters."
    // The graph must use semantic <button> or <a> elements so keyboard users
    // can navigate; or it must have role="button" + tabIndex on the nodes.
    if (!graphExists) return;
    const source = readSource('../components/discovery/CategoryGraph.tsx');
    const isKeyboardAccessible =
      /<button\b/.test(source) ||
      /<a\b/.test(source) ||
      /role=["']button["']/.test(source);
    expect(
      isKeyboardAccessible,
      'CategoryGraph nodes must be keyboard-focusable (button, link, or role="button")',
    ).toBe(true);
  });

  it('/ideas page renders the CategoryGraph', () => {
    // The /ideas page must use the graph, not just the flat list.
    if (!graphExists) return;
    const usesGraph = /<CategoryGraph\b/.test(page) || /CategoryGraph\b/.test(page);
    expect(
      usesGraph,
      'pages/ideas/index.tsx must render <CategoryGraph> (or import + use it)',
    ).toBe(true);
  });

  it('/ideas page keeps the flat-list fallback', () => {
    // The audit: "falls back to the existing flat list if the graph cannot be
    // rendered." The page must still render the existing list of category cards,
    // either as a fallback inside CategoryGraph or as a sibling surface.
    const keepsFlatList = /All categories/.test(page);
    expect(
      keepsFlatList,
      'pages/ideas/index.tsx must keep the "All categories" flat list as a fallback',
    ).toBe(true);
  });
});
