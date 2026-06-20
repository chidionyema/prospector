import { API_BASE_URL } from '@/lib/config';

export interface Pack {
  id: string;
  title: string;
  oneLine: string;
  price: string;
  paymentProvider: string;
  providerPriceId: string;
}

export interface PackDetails extends Pack {
  dossierRef: string;
}

/** Display price without trailing ".00" so "£30.00" reads as "£30" (real pence kept). */
export function formatPrice(price: string): string {
  return price.replace(/[.,]00\b/, '');
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
