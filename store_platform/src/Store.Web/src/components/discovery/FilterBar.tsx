import React from 'react';

import { type DropdownOption } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { SearchTrigger } from '@/components/discovery/CommandPalette';
import { AppliedFilterChips } from '@/components/discovery/FacetBar';
import {
  activeFacetSelectionCount,
  facetCounts,
  filterPacks,
  isFiltered,
  priceCeilings,
  type DiscoveryState,
} from '@/lib/discovery';
import { label as facetLabel, ADVANTAGE, type Advantage, type Sector } from '@/lib/facets';
import { allCategories } from '@/lib/category';
import { formatPriceForMarket, type Currency } from '@/lib/fx';
import type { Pack } from '@/lib/api/client';

/**
 * THE FILTER BAR (MASTER-BRIEF §7): search, category, capability, price, sort. One row, one system.
 *
 * WHAT IT REPLACES. The shelf carried three filters stacked on top of each other -- a search
 * field, an eleven-chip sector rail, and `StepFlow`, a three-question router -- plus a row of
 * applied-filter chips underneath restating whatever the three had set. All four wrote the same
 * `DiscoveryState` through the same `apply`, and the page had to print a sentence ("Use one or all
 * three. They combine.") to tell the reader they were not competing. A control panel that needs a
 * caption explaining that it is one control panel is the defect the brief names.
 *
 * A NOTE ON WHAT IS LOST, BECAUSE IT IS NOT NOTHING. `StepFlow` reached six facets: advantage,
 * commitment, payer, effort, mechanism and sector. This bar exposes two of them (sector as
 * "Category", advantage as "Capability") plus price and sort, because that is the set §7 names.
 * The other four are NOT removed from the model: `DiscoveryState` still carries them,
 * `filterPacks` still ANDs them, and a URL that sets `?payer=b2b` still filters the shelf and
 * still round-trips. What has gone is the on-page control for them. If the week of comparison in
 * §8 shows readers were using those questions, the answer is another control in this bar, not the
 * wizard back.
 *
 * CAPABILITY IS ONE AT A TIME HERE, AND THE STATE IS STILL A LIST. `advantage` is a multi-select
 * in the model (OR within the facet, up to `MAX_ADVANTAGES`), and a listbox selects one thing.
 * Rather than reduce the model to match the control, the control writes `[value]` and reads the
 * list: a URL that arrives with two capabilities filters on both and the button says so. Building
 * a checkbox popover instead is the right fix if the comparison says buyers pick more than one;
 * it is not worth a bespoke primitive before that.
 *
 * EVERY OPTION CARRIES ITS YIELD, and the yields come from `facetCounts`/`priceCeilings`, which
 * recompute with that one constraint removed. So a number beside an option answers "what do I get
 * if I pick this" rather than "how many of these exist" -- the second is a number the catalogue
 * made up as soon as any other filter is on. An option that would yield nothing is not offered.
 */

/** The sentinel for "no constraint" in a listbox, whose values must be strings. */
const ANY = '__any__';

/** The sentinel for a multi-capability state a single-select listbox cannot represent. */
const MANY = '__many__';

/*
 * THE DRAWING'S `.drop` (`mockups/index.html` section 6): a 40px surface button carrying the facet
 * name, an optional mono count and a chevron, inverted to `.drop.on` while that facet has a
 * selection.
 *
 * WHY NOT THE `Dropdown` PRIMITIVE. `Dropdown` draws its own box in Tailwind utilities, and
 * `globals.css` imports mockup.css into the `components` layer, which sits BELOW Tailwind's
 * `utilities`. So adding `drop` to a Dropdown would leave the class in the markup and lose every
 * property the utilities also set -- height, padding, border, radius, colour -- which is the exact
 * failure the structure check in `scripts/sections.mjs` exists to catch, dressed up as a fix.
 *
 * THE CONTROL IS A NATIVE `<select>`, laid transparently over the drawn button. That keeps the
 * keyboard and screen-reader behaviour of a real listbox (and the platform's own picker on a
 * phone) while the drawn button is what a mouse sees. `.drop` sets no `position`, so the `relative`
 * utility beside it collides with nothing.
 */
function Drop({
  label,
  ariaLabel,
  count,
  on,
  value,
  options,
  onChange,
}: {
  label: string;
  ariaLabel?: string;
  count?: number | null;
  on?: boolean;
  value: string;
  options: readonly DropdownOption<string>[];
  onChange: (value: string) => void;
}) {
  return (
    <span className={cx('drop relative', on && 'on')}>
      {label}
      {count != null && <span className="n num">{count}</span>}
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path
          d="M2.5 4.5 6 8l3.5-3.5"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <select
        aria-label={ariaLabel ?? label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="absolute inset-0 cursor-pointer opacity-0"
      >
        {options.map((option) => (
          <option key={String(option.value)} value={String(option.value)}>
            {option.label}
          </option>
        ))}
      </select>
    </span>
  );
}

export interface FilterBarProps {
  /** The whole shelf, unfiltered. Counts are computed against it. */
  packs: Pack[];
  state: DiscoveryState;
  onChange: (next: DiscoveryState) => void;
  /** The sort control is rendered here so the bar is the only place the shelf is controlled. */
  sort: string;
  sortOptions: readonly DropdownOption<string>[];
  onSortChange: (value: string) => void;
  /** The viewer's currency, so a price ceiling is labelled in the money on the cards. */
  currency: Currency;
  /** Opens the command palette, which is the search half of the bar. */
  onOpenSearch: () => void;
  /* Required, not optional: `SearchTrigger` needs it to return focus after the palette
     closes, and an undefined ref there is a keyboard user dropped at the top of the page. */
  searchTriggerRef: React.RefObject<HTMLButtonElement | null>;
  className?: string;
}

export function FilterBar({
  packs,
  state,
  onChange,
  sort,
  sortOptions,
  onSortChange,
  currency,
  onOpenSearch,
  searchTriggerRef,
  className,
}: FilterBarProps) {
  const sectorCounts = React.useMemo(() => facetCounts(packs, state, 'sector'), [packs, state]);
  const advantageCounts = React.useMemo(
    () => facetCounts(packs, state, 'advantage'),
    [packs, state],
  );
  const ceilings = React.useMemo(() => priceCeilings(packs, state), [packs, state]);

  /* "All" is the same computation with that one constraint cleared -- never `packs.length`, which
     would print 63 beside options summing to 21 whenever another filter is on. */
  const allSectors = React.useMemo(
    () => filterPacks(packs, { ...state, sector: null }).length,
    [packs, state],
  );
  const allAdvantages = React.useMemo(
    () => filterPacks(packs, { ...state, advantage: [] }).length,
    [packs, state],
  );
  const allPrices = React.useMemo(
    () => filterPacks(packs, { ...state, maxPence: null }).length,
    [packs, state],
  );

  const sectorOptions: DropdownOption<string>[] = [
    { value: ANY, label: `Any category · ${allSectors}` },
    ...allCategories()
      .filter((cat) => (sectorCounts[cat.key] ?? 0) > 0)
      .map((cat) => ({ value: cat.key, label: `${cat.label} · ${sectorCounts[cat.key]}` })),
  ];

  const advantageOptions: DropdownOption<string>[] = [
    { value: ANY, label: `Any capability · ${allAdvantages}` },
    ...ADVANTAGE.filter((a) => (advantageCounts[a] ?? 0) > 0).map((a) => ({
      value: a,
      label: `${facetLabel('advantage', a) ?? a} · ${advantageCounts[a]}`,
    })),
  ];
  /* A URL can express a state this control cannot: two capabilities at once. Rather than show the
     first and quietly drop the second, the button says how many are on. Picking anything from the
     list replaces the set, which is the only thing a single-select can honestly do. */
  if (state.advantage.length > 1) {
    advantageOptions.push({
      value: MANY,
      label: `${state.advantage.length} capabilities · ${filterPacks(packs, state).length}`,
    });
  }

  const priceOptions: DropdownOption<string>[] = [
    { value: ANY, label: `Any price · ${allPrices}` },
    ...ceilings
      .filter((c) => c.count > 0)
      .map((c) => ({
        value: String(c.pence),
        label: `${formatPriceForMarket(c.price, currency)} and under · ${c.count}`,
      })),
  ];

  const filtered = isFiltered(state);
  const matching = filterPacks(packs, state).length;
  const active = activeFacetSelectionCount(state);
  const sortLabel = sortOptions.find((option) => option.value === sort)?.label ?? 'Sort';
  const [mobileOpen, setMobileOpen] = React.useState(false);

  /* One set of controls, rendered twice: once in the drawing's desktop row and once in the panel
     the phone's "Filter packs" button opens. Building the list here rather than writing the JSX
     twice is what stops the two drifting, which is the same defect this bar was built to fix one
     level up. */
  const controls = (
    <>
      <Drop
        label="Category"
        count={state.sector ? 1 : sectorOptions.length - 1}
        on={state.sector !== null}
        value={state.sector ?? ANY}
        options={sectorOptions}
        onChange={(value) => onChange({ ...state, sector: value === ANY ? null : (value as Sector) })}
      />

      {/* "What you're good at" is the drawing's wording for this facet. The prop name and the
          accessible name stay "Capability", which is what the rest of the codebase calls it. */}
      <Drop
        label="What you're good at"
        ariaLabel="Capability"
        count={state.advantage.length > 0 ? state.advantage.length : advantageOptions.length - 1}
        on={state.advantage.length > 0}
        value={state.advantage.length > 1 ? MANY : (state.advantage[0] ?? ANY)}
        options={advantageOptions}
        onChange={(value) =>
          onChange({
            ...state,
            // `MANY` is a readout, never a choice: re-picking it changes nothing, which is the
            // honest behaviour for an option that describes the current state.
            advantage: value === ANY ? [] : value === MANY ? state.advantage : [value as Advantage],
          })
        }
      />

      {/* Offered only when the shelf has more than one price. `priceCeilings` returns nothing for
          a uniform shelf, and a control reading "£49 and under" beside a shelf where everything is
          £49 is a choice that is not a choice. */}
      {ceilings.length > 0 && (
        <Drop
          label="Price"
          on={state.maxPence !== null}
          value={state.maxPence === null ? ANY : String(state.maxPence)}
          options={priceOptions}
          onChange={(value) => onChange({ ...state, maxPence: value === ANY ? null : Number(value) })}
        />
      )}
    </>
  );

  const sortControl = (
    <Drop
      label={sortLabel}
      ariaLabel="Sort packs"
      value={sort}
      options={sortOptions}
      onChange={onSortChange}
    />
  );

  return (
    <>
      {/* THE DRAWING'S FILTER BAR (`mockups/index.html` section 6). It was a rounded card of five
          `Dropdown` primitives; the drawing is a sticky band with a hairline top and bottom, a
          search field, three named buttons and a right-hand count. Every class here is the
          drawing's own, and the Tailwind box that used to hold these numbers by hand is gone. */}
      <div
        data-filter-bar="1"
        /* `.filterbar` is `top:58px`, a number the drawing could hard-code because its header
           never contracts. Ours does, so the offset stays the `--h-header` token and the utility
           layer is where it has to live: mockup.css is imported into the `components` layer, which
           Tailwind's `utilities` outrank. Same reason for `z-20`: it has to sit under the header's
           `z-30`, and the drawing's 25 was chosen against a different header. */
        className={cx('filterbar', 'sticky top-[var(--h-header)] z-20', className)}
      >
        <div className="fb-in">
          {/* Search first, and widest. It is the control a reader who knows what they want reaches
              for, and the only one whose input is not a closed vocabulary. */}
          <span className="w-[212px] shrink-0">
            <SearchTrigger onOpen={onOpenSearch} triggerRef={searchTriggerRef} />
          </span>

          {controls}

          <div className="fb-right">
            <span className="mono num">
              {matching} of {packs.length}
            </span>
            {sortControl}
          </div>
        </div>

        {/* The phone row. `mockup.css` hides `.fb-in` and shows this below 980px; above it, this
            button cannot be reached, so the panel it opens cannot be stranded on a desktop. */}
        <div className="fb-mob">
          <button type="button" className="drop grow" onClick={() => setMobileOpen((open) => !open)}>
            Filter packs
            {active > 0 && <span className="badge num">{active}</span>}
          </button>
          <span className="mono num">
            {matching}/{packs.length}
          </span>
        </div>

        {mobileOpen && (
          <div className="hidden flex-col gap-2 px-5 pb-3 max-[980px]:flex">
            <SearchTrigger onOpen={onOpenSearch} triggerRef={searchTriggerRef} />
            {controls}
            {sortControl}
          </div>
        )}
      </div>

      {/* The applied filters, as the drawing draws them: `.active-row` of `.pill` chips with a
          `.clear` link. This replaces the "Clear filters" ghost button that used to sit inside the
          bar, and it says WHICH filters are on rather than only that some are. */}
      {filtered && <AppliedFilterChips state={state} onChange={onChange} />}
    </>
  );
}

export default FilterBar;
