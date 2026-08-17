import React from 'react';

import { Dropdown, Button, type DropdownOption } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { SearchTrigger } from '@/components/discovery/CommandPalette';
import {
  facetCounts,
  filterPacks,
  isFiltered,
  priceCeilings,
  EMPTY_DISCOVERY_STATE,
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

  return (
    /* `flex-wrap`, not a fixed grid. Five controls in one row is a desktop shape; on a phone they
       stack, and the shape that stacks is the one that also survives a long category name. */
    <div
      data-filter-bar="1"
      className={cx(
        'flex flex-wrap items-center gap-x-3 gap-y-2 rounded-card border border-line bg-surface p-3',
        className,
      )}
    >
      {/* Search first, and widest. It is the control a reader who knows what they want reaches
          for, and the only one whose input is not a closed vocabulary. */}
      <div className="w-full sm:w-56">
        <SearchTrigger onOpen={onOpenSearch} triggerRef={searchTriggerRef} />
      </div>

      <Dropdown<string>
        label="Category"
        value={state.sector ?? ANY}
        options={sectorOptions}
        onChange={(value) =>
          onChange({ ...state, sector: value === ANY ? null : (value as Sector) })
        }
        className="w-full sm:w-44"
      />

      <Dropdown<string>
        label="Capability"
        value={
          state.advantage.length > 1 ? MANY : (state.advantage[0] ?? ANY)
        }
        options={advantageOptions}
        onChange={(value) =>
          onChange({
            ...state,
            // `MANY` is a readout, never a choice: re-picking it changes nothing, which is the
            // honest behaviour for an option that describes the current state.
            advantage: value === ANY ? [] : value === MANY ? state.advantage : [value as Advantage],
          })
        }
        className="w-full sm:w-44"
      />

      {/* Offered only when the shelf has more than one price. `priceCeilings` returns nothing for
          a uniform shelf, and a control reading "£49 and under" beside a shelf where everything is
          £49 is a choice that is not a choice. */}
      {ceilings.length > 0 && (
        <Dropdown<string>
          label="Price"
          value={state.maxPence === null ? ANY : String(state.maxPence)}
          options={priceOptions}
          onChange={(value) =>
            onChange({ ...state, maxPence: value === ANY ? null : Number(value) })
          }
          className="w-full sm:w-44"
        />
      )}

      <Dropdown<string>
        label="Sort packs"
        value={sort}
        options={sortOptions}
        onChange={onSortChange}
        className="w-full sm:w-44"
      />

      {/* One way out of every filter at once, and it is the only thing that used to need the row
          of applied chips under the bar. The controls themselves now show what is set. */}
      {filtered && (
        <Button
          variant="ghost"
          onClick={() => onChange({ ...EMPTY_DISCOVERY_STATE, advantage: [] })}
          className="sm:ml-auto"
        >
          Clear filters
        </Button>
      )}
    </div>
  );
}

export default FilterBar;
