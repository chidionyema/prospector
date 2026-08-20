/**
 * Where to send an operator after they sign in.
 *
 * The gate redirects to `/login?next=/money` so a deep link survives the door. That parameter
 * arrives from the URL bar, so it is attacker-controlled: `?next=https://evil.example` would
 * turn our own login page into an open redirect, which is a real phishing primitive on a
 * console whose password is the only fence. Only a same-origin ABSOLUTE PATH is accepted, and
 * anything else silently becomes `/`.
 */
export function safeNextPath(raw: unknown): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== 'string' || value.length === 0) return '/';
  // Must be rooted at this origin.
  if (!value.startsWith('/')) return '/';
  // `//evil.example` and `/\evil.example` are protocol-relative URLs: the browser reads them as
  // another host, not as a path on ours.
  if (value.startsWith('//') || value.startsWith('/\\')) return '/';
  // A backslash anywhere is never legitimate in one of our paths, and browsers normalise it to
  // a forward slash, which is how `/\/evil.example` sneaks past a naive prefix check.
  if (value.includes('\\')) return '/';
  return value;
}
