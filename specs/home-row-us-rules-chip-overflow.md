# Spec — `Built for US rules` row chip clipped at viewport edge

## Bug (grounded from a 1284x2778 iOS screenshot, 2026-08-09)

On the home page (`/`), the off-market `Built for US rules` section renders its packs as rows
(`pages/index.tsx:1391-1418`, `weight="row"`). The row's tags line carries three facts in
this order: `category` -> `EvidenceBar` -> `{market} rules` chip.

On a 430px-wide iPhone viewport (Pro Max at 3x), the line overflows. Two failure modes seen
in the same screenshot:

1. **Chip pushed entirely off-screen.** Items 1, 2, 4 (category `Care and benefits claims`,
   18 chars) -- the category + EvidenceBar together consume the available middle-span width,
   so the trailing `US rules` chip is rendered past the viewport edge and the user sees only
   the EvidenceBar.
2. **Chip truncated mid-word.** Item 5 (no category, ~40 sources) -- the EvidenceBar is wide
   enough that `US rules` is partially clipped; the user reads `US ru`.

The chip is the only thing on the row that says "this pack is written for US rules". The
section heading carries the same fact once, but each row's chip is what stops a UK buyer
from buying a US pack by mistake, so the comment block on the section deliberately passes no
`viewerMarket` to force it on. Losing it visually is a defect, not a polish item.

## Cause (one-line)

The tags row is `flex items-center gap-3` with `category` and the `US rules` chip both
`flex-none`, and the `EvidenceBar` given no flex constraint. Every child demands its natural
width; the row's middle-span parent has `min-w-0 flex-1` so it shrinks, but its child row
does not, so the row's children overflow the middle span and the last child (the chip) is
the one that disappears.

## Fix (smallest correct change)

Mirror the pattern already used on the row's own heading line two spans up:

```tsx
<span className="flex min-w-0 items-center gap-2">
  <span className="truncate text-body font-semibold text-text">{heading}</span>
  {viewed && <span className="flex-none font-mono text-caption text-subtle">seen</span>}
</span>
```

Heading `truncate`s, `seen` chip is `flex-none`, container has `min-w-0`. That guarantees
the rightmost element stays visible at the cost of the heading's tail. The same pattern on
the tags line:

```tsx
<span className="mt-1.5 flex min-w-0 items-center gap-3">
  {cat.tagged && (
    <span className={cx('truncate font-mono text-caption', cat.ink)}>{cat.label}</span>
  )}
  <EvidenceBar count={pack.sourceCount} label={false} className="min-w-0 shrink" />
  {pack.market && pack.market !== viewerMarket && (
    <span className="flex-none font-mono text-caption text-warning">
      {marketLabel(pack.market)} rules
    </span>
  )}
</span>
```

Changes, three:

1. Tags row container: add `min-w-0` so the row itself can shrink within `min-w-0 flex-1`.
2. Category span: replace `flex-none` with `truncate` -- 18-char category names ("Care and
   benefits claims") collapse to "Care and benefits\u2026" before they push the chip out.
   Same CSS class the heading uses, so the truncation idiom is consistent on the same row.
3. EvidenceBar: pass `className="min-w-0 shrink"` so a 40-source bar gives way to the chip.
   The bar's ticks fade toward the tail (`EvidenceBar.tsx:91-92`), so the lost ink is the
   LEAST informative part of the bar; the head -- the part being compared across cards --
   stays. The chip stays `flex-none`.

The `US rules` chip is untouched: it remains the rightmost, `flex-none`, fully visible.

## Why not other options

- **`flex-wrap` on the row.** Wraps the chip to a second line on narrow widths, doubling
  row height and misaligning the divider rhythm. Larger change than the bug requires.
- **Move the chip to the cover** (`PackCoverArt` already has a `For {market} rules` chip).
  This is the card variant only; rows do not call `PackCoverArt`, and the chip needs to live
  in the row for the row layout to remain a row.
- **Hide the chip on narrow viewports.** The chip is the only per-row signal that the pack
  is for a different market. Hiding it on phone is the bug, fixed.
- **Drop the category on rows.** The category is shown by the sector chips above the shelf
  and on every card. The category on the row is supplementary; truncating it preserves
  every fact, just at fewer characters.

## Test (source-level guard)

Add `src/__tests__/homeRowChipOverflow.test.ts`. Reads `pages/index.tsx`, asserts:

1. The tags row carries `min-w-0` (so it can shrink).
2. The category span is `truncate` (so it yields width before pushing the chip).
3. The `EvidenceBar` receives `min-w-0` in its `className` prop (so it yields width too).
4. The `{market} rules` chip is `flex-none` (so it stays full-width).
5. The section that uses rows passes no `viewerMarket` to `PackCard` (the existing comment
   is the contract; this guard catches a future PR that "helpfully" passes one and silently
   drops the chip on its view).

## Verification

```bash
cd store_platform/src/Store.Web
npm test -- --run src/__tests__/homeRowChipOverflow.test.ts \
                src/lib/__tests__/checksBlock.test.ts \
                src/lib/__tests__/checkLexicon.test.ts \
                src/lib/__tests__/howItWorksDisplayId.test.ts
npm test       # full suite, 836+ pass
npm run verify # typecheck + lint, exit 0
```

Then visual on a 430px viewport with the actual US pack data (mock by setting
`?market=uk` on `/`, which routes the US packs into the "Built for US rules" group):
`npm run dev` -> http://localhost:3000/?market=uk -> screenshot. The five chips must read
`US rules` in full on every row.

## Non-goals

- No change to the card layout's `PackCoverArt` chip.
- No change to the `Built for UK rules` section (same bug, same fix applies if reported --
  this PR keeps the diff to the row layout only).
- No change to the heading / line truncation (already correct).
- No new copy. The chip's text is unchanged.
