# Spec — `/how-it-works` engine id display

## Problem

The how-it-works page renders the engine's gate id inside a `<code>` chip beneath each check
heading, e.g.:

```tsx
<code className="bg-bg px-1.5 py-0.5 rounded-md text-caption">{gateIdFor(check, example)}</code>
```

`gateIdFor` returns the raw engine id (`pain_reality`, `value_durability`, `incumbency`,
`payer_solvency`, `distribution`/`route_to_market`, `legality`). On a buyer-facing page that
promises a clean, repeatable mechanism, the underscored machine identifiers read as a leak of
internal vocabulary and are visually unprofessional.

The codebase already addresses this for one surface — the homepage method band used to print
`engineGateIds()`, and that function explicitly replaces `_` with ` ` before joining. The
how-it-works page never picked up the same convention.

## Fix

Smallest correct change, no scope creep:

1. **`store_platform/src/Store.Web/src/lib/checks.ts`** — add a tiny exported helper next to
   `engineGateIds()`:

   ```ts
   /** The engine id formatted for display: underscores become spaces. */
   export function formatGateId(id: string): string {
     return id.replace(/_/g, ' ');
   }
   ```

   `engineGateIds()` should be refactored to call it (one-liner), so the transform is stated
   once and any future change (e.g. handling hyphens) lands in one place.

2. **`store_platform/src/Store.Web/src/pages/how-it-works.tsx`** — import `formatGateId` and
   wrap the rendered value:

   ```tsx
   <code ...>{formatGateId(gateIdFor(check, example))}</code>
   ```

   No other behaviour on the page changes. The `<code>` styling stays — the chip's
   affordance (a small monospaced token that signals "this is the machine's name") is the
   right design choice; only the contents were wrong.

3. **Test** — add a guard that pins the contract:
   - A unit test for `formatGateId` (replaces `_` with ` `, leaves everything else alone).
   - A source-level assertion that `how-it-works.tsx` no longer passes raw `gateIdFor(...)`
     straight to a JSX text node — it must route through `formatGateId`. This stops a
     regression where someone adds a second chip and forgets to format it.

## Non-goals

- Do NOT change `check.id`, the kill-log JSON, the engine, or any other surface that consumes
  the raw id. The raw id is the contract with the engine; only the *display* is wrong here.
- Do NOT remove the `<code>` chip — the affordance is correct, the contents were not.
- Do NOT touch the homepage. `engineGateIds()` already does the right thing.
- Do NOT re-style the chip (size, color, spacing).

## Verification

```bash
cd store_platform/src/Store.Web
npm test -- --run src/lib/__tests__/checksBlock.test.ts \
                src/lib/__tests__/checkLexicon.test.ts \
                src/lib/__tests__/howItWorksDisplayId.test.ts
npm run verify   # typecheck + lint
```

Green is necessary, not sufficient — also visually confirm in the dev server that the chips
read "pain reality", "value durability", "incumbency", "payer solvency", "distribution /
route to market", "legality" (matching `check.name`'s prose where possible; the transform is
mechanical and only touches the underscored ids).
