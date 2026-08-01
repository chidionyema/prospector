import { API_FETCH_BASE } from '@/lib/config';
import type {
  Advantage,
  Commitment,
  Effort,
  Mechanism,
  Payer,
  Sector,
} from '@/lib/facets';

/** Python-computed snapshot the engine attaches at publish time. Served as an open
 *  string -> string map: the current engine fills it with the six scored axes
 *  ("Pain acuity": "4 of 5"), older packs may carry modelled-economics keys. Both are
 *  just entries here, so render sites read it generically. */
export interface FinancialSnapshot {
  [key: string]: string | undefined;
  month1Revenue?: string;
  ltvCac?: string;
  paybackMonths?: string;
}

/** One scored axis of the opportunity, parsed from a "N of 5" snapshot entry. */
export interface ScoreAxis {
  label: string;
  value: number;
  outOf: number;
}

/** Parse the financial snapshot into 1-to-5 score axes (the stress-test meters).
 *  Only entries shaped like "4 of 5" become axes; anything else is ignored. */
export function scoreAxes(snapshot?: FinancialSnapshot): ScoreAxis[] {
  if (!snapshot) return [];
  const axes: ScoreAxis[] = [];
  for (const [label, raw] of Object.entries(snapshot)) {
    const m = typeof raw === 'string' ? raw.match(/^(\d+)\s+of\s+(\d+)$/i) : null;
    if (m) axes.push({ label, value: parseInt(m[1], 10), outOf: parseInt(m[2], 10) });
  }
  return axes;
}

/** Split a QA verdict summary into the headline summary and the surfaced main risk, so the
 *  storefront can show the cons as their own honest callout (not bury them in a grey line).
 *  Input shape: "...Survived adversarial review. Main risk surfaced: <risk>" */
export function splitVerdict(summary?: string): { summary: string; risk: string | null } {
  if (!summary) return { summary: '', risk: null };
  const marker = 'Main risk surfaced:';
  const i = summary.indexOf(marker);
  if (i === -1) return { summary: summary.trim(), risk: null };
  return {
    summary: summary.slice(0, i).trim(),
    risk: summary.slice(i + marker.length).trim() || null,
  };
}

export interface Pack {
  id: string;
  title: string;
  oneLine: string;
  price: string;
  paymentProvider: string;
  providerPriceId: string;
  // Per-pack conversion specifics. Optional: only packs published by the newer engine carry
  // them, so every render site must degrade gracefully when they are absent.
  headline?: string;
  /** The engine's own ≤60-char description of what the business DOES, written for the shelf.
   *  Absent on every pack published before the engine emitted it, and deliberately empty when
   *  the operator could not write a truthful short line — so the card must always be able to
   *  fall back to the title. Length is enforced engine-side by dropping, never truncating
   *  (`prospector/artifacts.py::_card_line`). */
  cardLine?: string;
  whoPays?: string;
  /** The legacy `low | medium | high` string. Superseded by `effort`, and deliberately NOT
   *  mapped into it: those three values were never defined to mean "how much of delivery is
   *  machine-doable", so a mapping would be a guess wearing the costume of a migration
   *  (spec 2.3). Kept only until no render site reads it. */
  effortTag?: string;
  proofPoint?: string;
  timeToFirstRevenue?: string;
  sourceCount?: number;
  verifiedAt?: string;
  /** Discovery facets, straight from the engine's verified dossier. `null`/absent means the
   *  engine could not justify a value — the browser must render nothing rather than a guess,
   *  and such a pack appears only under "All". Vocabularies: `src/lib/facets.ts`. */
  sector?: Sector | null;
  payer?: Payer | null;
  effort?: Effort | null;
  commitment?: Commitment | null;
  mechanism?: Mechanism | null;
  advantages?: Advantage[] | null;
  /** Jurisdiction the OPPORTUNITY is in ("uk", "us", "us-tx"). Not the buyer's locale:
   *  every pack is priced and sold in GBP regardless of this value. Absent on packs
   *  published before the engine tracked markets. */
  market?: string;
}

export interface PackDetails extends Pack {
  dossierRef: string;
  subhead?: string;
  qaVerdictSummary?: string;
  whatYouGet?: string[];
  sampleExtract?: string[];
  financialSnapshot?: FinancialSnapshot;
}

/** Catalogue-wide survivorship counts (see GET /catalog/stats). */
export interface CatalogStats {
  listed: number;
  registered: number;
}

/** Display price without trailing ".00" so "£30.00" reads as "£30" (real pence kept). */
export function formatPrice(price: string): string {
  return price.replace(/[.,]00\b/, '');
}

/** Human freshness for the verified date, e.g. "Verified today" / "Verified 3 days ago".
 *  Returns null for a missing or unparseable date so callers can simply omit the badge. */
export function freshnessLabel(iso?: string): string | null {
  if (!iso) return null;
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return null;
  const days = Math.floor((Date.now() - then.getTime()) / 86_400_000);
  if (days <= 0) return 'Verified today';
  if (days === 1) return 'Verified yesterday';
  if (days < 30) return `Verified ${days} days ago`;
  const months = Math.floor(days / 30);
  return months <= 1 ? 'Verified last month' : `Verified ${months} months ago`;
}

const MARKET_LABELS: Record<string, string> = {
  uk: 'UK',
  us: 'US',
};

/** Display label for a market code. Falls back to the code itself (upper-cased) so a
 *  newly opened market renders sensibly without a front-end deploy. A subdivision like
 *  "us-tx" renders as "US · TX". */
export function marketLabel(code?: string): string {
  if (!code) return '';
  const [root, sub] = code.toLowerCase().split('-');
  const base = MARKET_LABELS[root] ?? root.toUpperCase();
  return sub ? `${base} · ${sub.toUpperCase()}` : base;
}

export async function fetchCatalog(): Promise<Pack[]> {
  const res = await fetch(`${API_FETCH_BASE}/catalog`);
  if (!res.ok) throw new Error('Failed to fetch catalog');
  return res.json();
}

export interface WaitlistSignup {
  email: string;
  /** Must be explicitly true. The server rejects false — an unticked box is not consent. */
  consent: boolean;
  /** The exact sentence the person was shown. The server hashes this, not a client-supplied
   *  hash, so the stored evidence is of what was actually rendered. */
  consentText: string;
  consentVersion: string;
  /** What they were searching for when the catalogue came back empty. */
  query?: string;
  source?: string;
}

/**
 * POST /catalog/waitlist — the honest end of a catalogue-wide miss.
 *
 * Returns the server's error string on rejection rather than throwing, because every rejection
 * here is a message the buyer needs to read (bad address, consent missing, rate limited).
 */
export async function joinWaitlist(
  signup: WaitlistSignup,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const res = await fetch(`${API_FETCH_BASE}/catalog/waitlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(signup),
  });
  if (res.ok) return { ok: true };
  if (res.status === 429) {
    return { ok: false, error: 'Too many attempts from here. Give it a minute and try again.' };
  }
  const body = (await res.json().catch(() => null)) as { error?: string } | null;
  return { ok: false, error: body?.error ?? 'That did not go through. Try again in a moment.' };
}

/**
 * The buyer's email on a checkout body, or nothing at all.
 *
 * An order is joined to an account by email address alone — `Order.BuyerEmail`, with no user id
 * column — so the address the provider records IS the link between a purchase and a customer.
 * Sending a signed-in customer's address does two things: Stripe pre-fills it AND makes the field
 * read-only (`CustomerEmail` on the session, StripeProvider.cs:385), so the recorded address
 * cannot drift from the account. Without it a signed-in buyer who types a different address at
 * Stripe gets a perfectly valid order that never appears in their account — no error, anywhere.
 *
 * Omitted for a guest, which is the supported case, not a fallback: neither checkout route
 * requires authorization (CheckoutEndpoints.cs:24,40), so the provider collects the address and
 * the webhook records whatever the buyer typed (StripeProvider.cs:133).
 *
 * The address is asserted by the client, because these two routes are called on the API origin
 * directly and carry no session cookie (see the D-63 note in next.config.ts — only `/api/*` is
 * proxied). That is not an escalation: filing an order under an address requires PAYING for it,
 * and reading that order back still requires proving the address (order history is gated on
 * EmailConfirmed). The server is free to override it if these routes ever move behind the proxy.
 */
function checkoutBody(buyerEmail: string | null | undefined, rest: Record<string, unknown> = {}) {
  return JSON.stringify(buyerEmail ? { ...rest, email: buyerEmail } : rest);
}

/**
 * Ask the API to open a Stripe Checkout Session for a pack and return the hosted URL.
 *
 * Lives here rather than in the page because components never call fetch directly
 * (UI-STANDARDS §4). The redirect allow-list travels with the call: it is a property of
 * trusting this response, not of the component that happens to use it.
 */
export async function createStripeCheckout(packId: string, buyerEmail?: string | null): Promise<string> {
  const res = await fetch(`${API_FETCH_BASE}/packs/${packId}/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: checkoutBody(buyerEmail),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to start checkout: ${text}`);
  }
  const { url } = await res.json();
  return assertStripeCheckoutUrl(url);
}

/** What the API opened. `clientSecret` present means the card form can render on our own page;
 *  null means the server fell back to the hosted page and `url` is where the buyer must go. The
 *  caller must handle both — the server decides, not the client. */
export interface CheckoutSession {
  clientSecret: string | null;
  url: string | null;
}

/**
 * Open a checkout session for a pack, asking for the embedded surface.
 *
 * Asking is not getting: the API answers with a hosted URL whenever the provider cannot render
 * embedded (Paddle, or a Stripe account without it). That is why this returns a session rather
 * than a client secret — there is no failure to report when the answer is "use the hosted page",
 * and turning it into one would block a buyer from paying over a cosmetic difference.
 */
export async function createEmbeddedCheckout(
  packId: string,
  buyerEmail?: string | null,
): Promise<CheckoutSession> {
  const res = await fetch(`${API_FETCH_BASE}/packs/${packId}/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: checkoutBody(buyerEmail, { embedded: true }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to start checkout: ${text}`);
  }
  const { clientSecret, url } = await res.json();
  return {
    clientSecret: typeof clientSecret === 'string' && clientSecret ? clientSecret : null,
    // The hosted URL keeps its allow-list check. A session that came back embedded has no URL at
    // all, which is not an error — only a NON-Stripe URL is.
    url: typeof url === 'string' && url ? assertStripeCheckoutUrl(url) : null,
  };
}

/** Raised when the API refuses specific packs — sold out, withdrawn, or not yet priced. Carries
 *  the ids so the basket can prune exactly those rather than making the buyer start again. */
export class PacksUnavailableError extends Error {
  readonly packIds: string[];

  constructor(message: string, packIds: string[]) {
    super(message);
    this.name = 'PacksUnavailableError';
    this.packIds = packIds;
  }
}

/** Raised when a catalogue read fails, carrying the HTTP status so a caller can tell "gone" from
 *  "down". A bare Error collapses that distinction, and it matters wherever the answer becomes a
 *  CACHED artefact: `/og/pack/[id]` must serve 404 for a pack that does not exist and 503 for an
 *  API that is briefly unreachable, because social platforms cache a preview for days and would
 *  otherwise keep serving the wrong one for a blip.
 *
 *  Not `AuthError` (`lib/api/auth.ts:38`): that one requires the auth API's stable `code`, which a
 *  catalogue 503 does not have, so reusing it would mean inventing one. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * Ask the API to open one Stripe Checkout Session for a whole basket.
 *
 * The buyer enters their card once and gets one charge, one statement line and one set of
 * download links, however many packs they picked.
 */
export async function createCartCheckout(
  packIds: string[],
  buyerEmail?: string | null,
): Promise<string> {
  const res = await fetch(`${API_FETCH_BASE}/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: checkoutBody(buyerEmail, { packIds }),
  });

  if (!res.ok) {
    // The API answers 404 with the exact ids it will not sell. A basket can sit in localStorage
    // for weeks, so a withdrawn pack is expected rather than exceptional: name it, prune it, and
    // let the buyer pay for the rest.
    const body = await res.json().catch(() => null);
    const rejected: unknown = body?.packIds;
    if (res.status === 404 && Array.isArray(rejected) && rejected.length > 0) {
      throw new PacksUnavailableError(
        typeof body?.error === 'string' ? body.error : 'Not available for purchase.',
        rejected.filter((id: unknown): id is string => typeof id === 'string'),
      );
    }
    throw new Error(typeof body?.error === 'string' ? body.error : 'Failed to start checkout.');
  }

  const { url } = await res.json();
  return assertStripeCheckoutUrl(url);
}

/** Defence in depth: only ever redirect to Stripe's hosted checkout. Refuse any other value so a
 *  compromised/buggy API response can't turn this into an open redirect. */
function assertStripeCheckoutUrl(url: unknown): string {
  if (typeof url !== 'string' || !url.startsWith('https://checkout.stripe.com/')) {
    throw new Error('Unexpected checkout URL');
  }
  return url;
}

/** Throws `ApiError` (declared above) rather than a bare Error, so a caller can tell "gone" from
 *  "down". Message and `instanceof Error` are unchanged, so existing catch blocks behave as before. */
export async function fetchPackDetails(id: string): Promise<PackDetails> {
  const res = await fetch(`${API_FETCH_BASE}/catalog/${id}`);
  if (!res.ok) throw new ApiError('Failed to fetch pack details', res.status);
  return res.json();
}

/** Survivorship counts for the storefront's social proof. Best-effort: returns null on any
 *  failure so a stats outage never blocks the catalogue from rendering. */
export async function fetchCatalogStats(): Promise<CatalogStats | null> {
  try {
    const res = await fetch(`${API_FETCH_BASE}/catalog/stats`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/** Analytics beacon payload — the client half of the server-side allowlist contract
 *  (AnalyticsEndpoints.cs). Event-name typing lives in src/lib/analytics.ts. */
export interface AnalyticsEventBody {
  name: string;
  path: string | null;
  meta: string | null;
}

/** Fire-and-forget analytics beacon. keepalive lets the request survive a same-instant
 *  navigation (the hero CTAs navigate on click). Failures are swallowed: an uncounted
 *  event is the correct failure mode — analytics must never break the page. */
export function recordAnalyticsEvent(body: AnalyticsEventBody): void {
  try {
    void fetch(`${API_FETCH_BASE}/events`, {
      method: 'POST',
      keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).catch(() => {
      /* swallowed */
    });
  } catch {
    /* swallowed */
  }
}

export interface OrderDetails {
  packId: string;
  packTitle: string;
  status: 'active' | 'revoked';
  downloadPath: string;
}

export async function fetchOrder(token: string): Promise<OrderDetails> {
  const res = await fetch(`${API_FETCH_BASE}/api/orders/${token}`);
  if (res.status === 404) throw new Error('not_found');
  if (!res.ok) throw new Error('Failed to fetch order');
  return res.json();
}

/** One purchased pack resolved from a checkout session. */
export interface SessionOrderItem {
  packId: string;
  packTitle: string;
  orderPath: string;
  downloadPath: string;
}

/** What a checkout session resolved to.
 *
 *  `pending` is normal, not an error: the browser usually gets back from the payment provider
 *  before the fulfilment webhook lands, so the caller polls until the status turns `ready`.
 *
 *  `unfulfilled` and `revoked` are TERMINAL — the caller must stop polling. Both used to be
 *  reported as `pending`, so a buyer whose order could never resolve watched the same spinner
 *  as one whose webhook was half a second away, until the poll timeout gave up on their behalf.
 *  `unfulfilled` means payment was recorded but fulfilment granted nothing (the API can prove
 *  this because the Order is written in the same transaction as any entitlement); `revoked`
 *  means it was granted and later withdrawn by a refund or dispute. */
export interface SessionOrder {
  status: 'pending' | 'ready' | 'unfulfilled' | 'revoked';
  items: SessionOrderItem[];
}

/** Resolve the checkout session the buyer just completed into real download links.
 *  This is what makes the purchase deliverable on-screen rather than only by email. */
export async function fetchOrderBySession(sessionId: string): Promise<SessionOrder> {
  const res = await fetch(`${API_FETCH_BASE}/api/orders/by-session/${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error('Failed to resolve checkout session');
  return res.json();
}
