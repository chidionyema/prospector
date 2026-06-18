/**
 * Deterministic "covers" for packs, which ship without imagery. Each pack id maps to a fixed
 * premium gradient + monogram so cards and detail pages stay visually consistent. The class
 * strings are full literals so Tailwind keeps them at build time.
 */
export const COVERS = [
  'bg-[linear-gradient(135deg,#4f46e5_0%,#7c3aed_100%)]',
  'bg-[linear-gradient(135deg,#0d9488_0%,#059669_100%)]',
  'bg-[linear-gradient(135deg,#d97706_0%,#ea580c_100%)]',
  'bg-[linear-gradient(135deg,#e11d48_0%,#be123c_100%)]',
  'bg-[linear-gradient(135deg,#2563eb_0%,#0284c7_100%)]',
  'bg-[linear-gradient(135deg,#334155_0%,#4338ca_100%)]',
];

export function coverFor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return COVERS[h % COVERS.length];
}

// Skipped so monograms read as the idea, not the grammar: "The Probate Locker" → "PL", not "TP".
const STOP = new Set(['the', 'a', 'an', 'of', 'for', 'to', 'and', 'your', 'my', 'with', 'on', 'in']);

export function monogram(title: string): string {
  // Letters only (drop possessives/punctuation), then prefer the meaningful words.
  const words = title
    .trim()
    .split(/\s+/)
    .map((w) => w.replace(/[^A-Za-z]/g, ''))
    .filter(Boolean);
  if (words.length === 0) return 'P';
  const significant = words.filter((w) => !STOP.has(w.toLowerCase()));
  const picks = significant.length >= 1 ? significant : words;
  if (picks.length === 1) return picks[0].slice(0, 2).toUpperCase();
  return (picks[0][0] + picks[1][0]).toUpperCase();
}
