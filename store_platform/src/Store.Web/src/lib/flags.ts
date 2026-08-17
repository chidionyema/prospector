/**
 * Feature flags, resolved on the server and handed to the page as props.
 *
 * WHY NOT `NEXT_PUBLIC_*`. Those are inlined into the bundle at BUILD time, so flipping one means
 * a rebuild and a redeploy -- which is not a flag, it is a release with extra steps. These are read
 * from `process.env` inside `getServerSideProps`, so the operator changes the environment, restarts
 * the app and the next request is on the other path. That is the P10 rule: if it can change, the
 * operator changes it, without an engineer.
 *
 * WHY A URL OVERRIDE TOO. `?ff=filterbar` / `?ff=wizard` forces one path for one request. It is how
 * the founder sees both without touching the environment, and it is how an e2e spec pins the path
 * it is testing instead of inheriting whatever the box happens to be set to. It is deliberately not
 * sticky: no cookie, no localStorage. A flag a reader can turn on and then forget is a support
 * ticket about a page nobody else can reproduce.
 */

/** The parsed value of one boolean environment flag. `undefined` means "not set". */
function envFlag(raw: string | undefined): boolean | undefined {
  if (raw === undefined) return undefined;
  const value = raw.trim().toLowerCase();
  if (value === '1' || value === 'true' || value === 'on' || value === 'yes') return true;
  if (value === '0' || value === 'false' || value === 'off' || value === 'no') return false;
  // A typo is not a decision. Fall through to the default rather than reading "flase" as false.
  return undefined;
}

export interface Flags {
  /**
   * The single filter bar (MASTER-BRIEF §7) instead of the three stacked controls.
   *
   * `false` keeps the wizard path: the search field, the sector rail, the applied chips and
   * `StepFlow`. §8 asks for both to exist for a week so catalogue engagement can be compared
   * before the old path is deleted, which is the only reason the wizard is still in the tree.
   */
  filterBar: boolean;
}

/** What the page falls back to when neither the environment nor the URL says anything. */
export const DEFAULT_FLAGS: Flags = {
  // OFF until the week of comparison §8 asks for has been run. The founder turns it on with
  // `MUMCHIMP_FILTER_BAR=1`; nothing here decides that for them.
  filterBar: false,
};

/** Next's parsed query, the same shape `decodeDiscoveryState` takes. */
export type QueryLike = Record<string, string | string[] | undefined>;

function firstValue(query: QueryLike, key: string): string | null {
  const raw = query[key];
  if (Array.isArray(raw)) return raw.length > 0 ? raw[0] : null;
  return raw ?? null;
}

/**
 * Resolve the flags for one request. URL beats environment, environment beats the default.
 *
 * `env` is passed rather than read here so this is a pure function a test can drive. The caller in
 * `getServerSideProps` passes `process.env`.
 */
export function resolveFlags(
  env: Record<string, string | undefined>,
  query: QueryLike = {},
): Flags {
  const ff = (firstValue(query, 'ff') ?? '').trim().toLowerCase();
  if (ff === 'filterbar') return { filterBar: true };
  if (ff === 'wizard') return { filterBar: false };

  return {
    filterBar: envFlag(env.MUMCHIMP_FILTER_BAR) ?? DEFAULT_FLAGS.filterBar,
  };
}
