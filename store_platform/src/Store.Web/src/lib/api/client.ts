import { API_BASE_URL } from '@/lib/config';

export interface Pack {
  id: string;
  title: string;
  oneLine: string;
  price: string;
  paddlePriceId: string;
}

export interface PackDetails extends Pack {
  dossierRef: string;
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
