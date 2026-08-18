/**
 * What this browser had already seen on the shelf, so the account page can say what is new.
 *
 * MASTER-BRIEF section 7 `/account` puts "new since your last visit" third and calls it the
 * cheapest return hook available. It is only cheap if it is true, and the obvious implementation is
 * not: comparing each pack's `verifiedAt` against a stored timestamp reads a field that records
 * when the engine RULED on an idea, not when the shelf listed it. A pack re-vetted after a
 * provisional verdict would come back "new" months after it was published, and the block would
 * quietly become a list of packs the reader has already scrolled past.
 *
 * So this stores the ids instead. A pack is new to this reader when its id is not in the set the
 * last visit recorded. That cannot drift, needs no field the API does not have, and it is exact:
 * the answer is a set difference, not an inference from a date.
 *
 * FIRST VISIT DELIBERATELY ANSWERS "NOTHING". With no recorded set, every pack is unseen, and
 * announcing the entire catalogue as new since a visit that never happened is a lie told on the
 * first impression. `readSeen` returns `null` for that case, distinct from an empty set, and
 * `newSince` returns nothing for it.
 *
 * localStorage, not the account: this is a per-browser convenience, not a fact about the customer,
 * and putting it on the server would mean writing a row on every catalogue render.
 */

const KEY = 'mumchimp.seen.v1';

/** Kept well above the live catalogue so a normal shelf is stored whole; a hard cap only exists so
 *  a runaway catalogue can never fill the origin's storage quota and break the basket beside it. */
const MAX_IDS = 2000;

/**
 * The ids recorded on the last visit, or `null` if this browser has never recorded any.
 *
 * Any parse failure also returns `null`, which lands on the first-visit branch: the reader sees no
 * "new" block rather than a wrong one, and the next `rememberSeen` repairs the entry.
 */
export function readSeen(): string[] | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    return parsed.filter((id): id is string => typeof id === 'string');
  } catch {
    return null;
  }
}

/** Record what is on the shelf now. Call AFTER `readSeen`, or this visit erases its own answer. */
export function rememberSeen(ids: readonly string[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(ids.slice(0, MAX_IDS)));
  } catch {
    // A full or disabled store costs the reader this one convenience and nothing else.
  }
}

/** Packs on the shelf now that were not there last time. Empty on a first visit; see the note. */
export function newSince<T extends { id: string }>(packs: readonly T[], seen: string[] | null): T[] {
  if (seen === null) return [];
  const known = new Set(seen);
  return packs.filter((pack) => !known.has(pack.id));
}
