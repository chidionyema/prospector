/**
 * D-24 (E06-009 / WR-013): server-side fetch for the verified-identity avatar photo.
 *
 * The OIDC `picture` is a LinkedIn CDN URL. Hot-linking it from the buyer's browser leaks the
 * buyer's IP / User-Agent to LinkedIn on every render of the confirm page. This helper lets the
 * `/api/identity-photo` route fetch the image **server-side** and serve it same-origin, so the
 * browser only ever talks to us.
 *
 * It lives under `src/lib/api/**` because that is the ONE place the foundation rails permit a raw
 * `fetch` (see web/eslint.config.mjs). The API route must call THIS — never `fetch` directly.
 *
 * SSRF guard: this fetches an attacker-influenced URL (it arrives as a query param), so the host is
 * allow-listed to LinkedIn's CDN only. Without that, the route is an open proxy / SSRF pivot into
 * anything the server can reach (cloud metadata, internal services). Keep the allow-list tight.
 */

// LinkedIn serves headshots from media.licdn.com and regional variants (media-exp*.licdn.com).
function isLicdnHost(hostname: string): boolean {
  const h = hostname.toLowerCase();
  return h === 'licdn.com' || h.endsWith('.licdn.com');
}

/** True only for an https URL on LinkedIn's CDN. Reject everything else (SSRF guard). */
export function isAllowedPhotoUrl(raw: string): boolean {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return false;
  }
  return url.protocol === 'https:' && isLicdnHost(url.hostname);
}

export interface IdentityPhoto {
  contentType: string;
  body: Buffer;
}

const FETCH_TIMEOUT_MS = 5_000;
const MAX_BYTES = 5 * 1024 * 1024; // 5 MB. A headshot is well under this; cap abuse.

/**
 * Fetch an allow-listed LinkedIn photo. Returns null on any failure (bad host, timeout, non-image,
 * oversize, upstream error) — the caller maps null to a 502 and the avatar degrades to initials.
 */
export async function fetchIdentityPhoto(raw: string): Promise<IdentityPhoto | null> {
  if (!isAllowedPhotoUrl(raw)) return null;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(raw, {
      signal: controller.signal,
      redirect: 'error', // a 30x off the allow-listed host would defeat the SSRF guard.
      headers: { Accept: 'image/*' },
    });
    if (!res.ok) return null;

    const contentType = res.headers.get('content-type') ?? '';
    if (!contentType.toLowerCase().startsWith('image/')) return null;

    const declared = res.headers.get('content-length');
    if (declared && Number(declared) > MAX_BYTES) return null;

    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.byteLength > MAX_BYTES) return null;

    return { contentType, body: buf };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
