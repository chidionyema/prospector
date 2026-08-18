/**
 * A sliding-window limiter for the sign-in route.
 *
 * It exists because the console stopped being reachable only over a tunnel from the founder's
 * laptop and started answering on the open internet (2026-08-18). A shared password with no
 * limiter is a password an attacker can try a few million times a day. This makes that cost
 * real: five wrong answers per address per fifteen minutes, then a locked door.
 *
 * In memory on purpose. The console runs as ONE process on ONE machine, next to the volume it
 * reads, so a shared store would be a second moving part guarding a single process. If the
 * console is ever run more than once, this has to move to the store with it.
 */
const WINDOW_MS = 15 * 60 * 1000;
const MAX_FAILURES = 5;

const failures = new Map<string, number[]>();

/** The caller's address. Fly puts the real one in Fly-Client-IP; the socket is the proxy. */
export function clientKey(headers: Record<string, string | string[] | undefined>): string {
  const fly = headers['fly-client-ip'];
  if (typeof fly === 'string' && fly) return fly;
  const fwd = headers['x-forwarded-for'];
  const first = Array.isArray(fwd) ? fwd[0] : fwd;
  if (typeof first === 'string' && first) return first.split(',')[0]!.trim();
  return 'unknown';
}

/** True when this address has already spent its attempts. Does not record anything. */
export function isLocked(key: string, now = Date.now()): boolean {
  const hits = (failures.get(key) ?? []).filter((t) => now - t < WINDOW_MS);
  if (hits.length) failures.set(key, hits);
  else failures.delete(key);
  return hits.length >= MAX_FAILURES;
}

/** Record one wrong password. */
export function recordFailure(key: string, now = Date.now()): void {
  const hits = (failures.get(key) ?? []).filter((t) => now - t < WINDOW_MS);
  hits.push(now);
  failures.set(key, hits);
}

/** A correct password clears the address, so a fumbled login does not punish the next one. */
export function clearFailures(key: string): void {
  failures.delete(key);
}

/** Test seam. Never called in production. */
export function _reset(): void {
  failures.clear();
}
