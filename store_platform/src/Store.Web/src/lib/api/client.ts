import { API_BASE_URL } from '@/lib/config';
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
  const res = await fetch(`${API_BASE_URL}/catalog`);
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
  const res = await fetch(`${API_BASE_URL}/catalog/waitlist`, {
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

export async function fetchPackDetails(id: string): Promise<PackDetails> {
  const res = await fetch(`${API_BASE_URL}/catalog/${id}`);
  if (!res.ok) throw new Error('Failed to fetch pack details');
  return res.json();
}

/** Survivorship counts for the storefront's social proof. Best-effort: returns null on any
 *  failure so a stats outage never blocks the catalogue from rendering. */
export async function fetchCatalogStats(): Promise<CatalogStats | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/catalog/stats`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export interface OrderDetails {
  packId: string;
  packTitle: string;
  status: 'active' | 'revoked';
  downloadPath: string;
}

export async function fetchOrder(token: string): Promise<OrderDetails> {
  const res = await fetch(`${API_BASE_URL}/api/orders/${token}`);
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

/** What a checkout session resolved to. `pending` is normal, not an error: the browser
 *  usually gets back from the payment provider before the fulfilment webhook lands, so
 *  the caller polls until the status turns `ready`. */
export interface SessionOrder {
  status: 'pending' | 'ready';
  items: SessionOrderItem[];
}

/** Resolve the checkout session the buyer just completed into real download links.
 *  This is what makes the purchase deliverable on-screen rather than only by email. */
export async function fetchOrderBySession(sessionId: string): Promise<SessionOrder> {
  const res = await fetch(`${API_BASE_URL}/api/orders/by-session/${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error('Failed to resolve checkout session');
  return res.json();
}

// Stub TIE-compat exports — the Store.Web is being repurposed from TIE to Prospector.
// These APIs don't exist in the Store context but several components still import them.
// Each stub returns safe defaults so the app type-checks without the TIE backend.
export const bountiesApi = { mine: async () => [] as unknown[] };
export const proposalsApi = { listMine: async () => [] as unknown[] };
export const authApi = {
  login: async () => ({ token: '', user: null }),
  register: async () => ({ token: '', user: null }),
  me: async () => null,
  logout: async () => {},
};
export const externalAuthApi = {
  providers: async () => ({ providers: [] as unknown[] }),
  callback: async () => ({ token: '' }),
  challengeUrl: (_provider: string, _redirectUrl: string) => '',
};
export const accountApi = {
  get: async () => ({}),
  update: async () => ({}),
  delete: async () => {},
  acceptTos: async (_version: string) => {},
};
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
export function setAccessToken(_token: string | null) {}
export function setOnUnauthorized(_fn: () => void) {}
