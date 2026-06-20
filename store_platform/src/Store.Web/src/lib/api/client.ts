import { API_BASE_URL } from '@/lib/config';

/** Python-computed economics snapshot the engine attaches at publish time. */
export interface FinancialSnapshot {
  month1Revenue?: string;
  ltvCac?: string;
  paybackMonths?: string;
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
  effortTag?: string;
  proofPoint?: string;
  timeToFirstRevenue?: string;
  sourceCount?: number;
  verifiedAt?: string;
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

export async function fetchCatalog(): Promise<Pack[]> {
  const res = await fetch(`${API_BASE_URL}/catalog`);
  if (!res.ok) throw new Error('Failed to fetch catalog');
  return res.json();
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

// Stub TIE-compat exports — the Store.Web is being repurposed from TIE to Prospector.
// These APIs don't exist in the Store context but several components still import them.
// Each stub returns safe defaults so the app type-checks without the TIE backend.
export const bountiesApi = { mine: async () => [] as any[] };
export const proposalsApi = { listMine: async () => [] as any[] };
export const authApi = {
  login: async () => ({ token: '', user: null }),
  register: async () => ({ token: '', user: null }),
  me: async () => null,
  logout: async () => {},
};
export const externalAuthApi = {
  providers: async () => ({ providers: [] as any[] }),
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
