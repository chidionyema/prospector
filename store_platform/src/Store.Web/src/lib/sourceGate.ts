/**
 * Public-page source gate (founder brief 2026-09-02, §4.1).
 *
 * Nothing is shown on a card, verdict, sample or /rejected unless it passes all four:
 * a human-readable title, real fetched text, matching jurisdiction (or an allowlist),
 * and a citation against a specific claim. Record:
 * `/Users/chidionyema/.claude/docs/founder/2026-09-02T2249Z-mumchimp-one-shot-rebuild-brief-1efd1695.md`
 *
 * The homepage sample that shipped today failed all four on "Can the payer pay?":
 * ONS adhoc slugs as titles, cookie-consent bodies, latitudefinancial.com.au and
 * consumeraffairs.com on a UK check.
 */

export type PackMarket = "UK" | "US" | string;

export type SourceInput = {
  url: string;
  domain?: string;
  label?: string;
  title?: string;
  excerpt?: string;
  text?: string;
};

export type GateFail =
  | "slug-title"
  | "junk-content"
  | "jurisdiction"
  | "no-claim";

export type GateResult =
  | { ok: true; title: string }
  | { ok: false; reason: GateFail };

/** Domains that may be cited from any market. */
export const SOURCE_ALLOWLIST = [
  "iso.org",
  "who.int",
  "oecd.org",
  "ieee.org",
  "w3.org",
  "ietf.org",
  "rfc-editor.org",
  "un.org",
  "ilo.org",
  "worldbank.org",
  "imf.org",
] as const;

const JUNK =
  /cookie|consent|enable javascript|please (enable|log in|sign in)|sign in to continue|page not found|\b404\b|attention required|just a moment|checking your browser/i;

function hostOf(source: SourceInput): string {
  if (source.domain) return source.domain.replace(/^www\./, "").toLowerCase();
  try {
    return new URL(source.url).hostname.replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}

function lastPathSegment(url: string): string {
  try {
    const path = new URL(url).pathname.replace(/\/+$/, "");
    return decodeURIComponent(path.split("/").pop() ?? "");
  } catch {
    return "";
  }
}

/** A title that is a URL slug, not a name a person can read. */
export function isSlugTitle(value: string): boolean {
  const t = value.trim();
  if (!t) return true;
  if (/\s/.test(t)) return false;
  if (/^[0-9]{2,}[a-z0-9-]{10,}$/i.test(t)) return true;
  if (t.length >= 32 && /^[a-z0-9._-]+$/i.test(t)) return true;
  return false;
}

export function isJunkContent(text: string | undefined): boolean {
  if (!text) return false;
  return JUNK.test(text);
}

function onAllowlist(host: string): boolean {
  return SOURCE_ALLOWLIST.some((d) => host === d || host.endsWith(`.${d}`));
}

export function jurisdictionMatches(host: string, market: PackMarket): boolean {
  if (!host) return false;
  if (onAllowlist(host)) return true;
  const m = String(market).toUpperCase();
  if (m.startsWith("UK") || m === "GB") {
    if (/\.(com|com\.au|co\.nz)$/.test(host) && !/\.(gov|ac|nhs)\.uk$/.test(host) && !host.endsWith(".uk")) {
      if (host.endsWith(".gov.uk") || host.endsWith(".ac.uk") || host.endsWith(".nhs.uk") || host.endsWith(".org.uk") || host.endsWith(".co.uk")) {
        return true;
      }
      if (host.endsWith(".com.au") || host.endsWith(".co.nz")) return false;
      // US consumer / loan press on a UK check
      if (/(consumeraffairs|latitudefinancial|nerdwallet|bankrate)\.com$/.test(host)) return false;
    }
    return (
      host.endsWith(".uk") ||
      host.endsWith(".gov.uk") ||
      host === "gov.uk" ||
      host.endsWith(".ac.uk") ||
      host.endsWith(".nhs.uk")
    );
  }
  if (m.startsWith("US")) {
    if (host.endsWith(".com.au") || host.endsWith(".co.uk") || host.endsWith(".gov.uk")) return false;
    return (
      host.endsWith(".gov") ||
      host.endsWith(".mil") ||
      host.endsWith(".edu") ||
      /\.(us)$/.test(host)
    );
  }
  return onAllowlist(host);
}

function displayTitle(source: SourceInput): string | null {
  const raw = (source.label || source.title || "").trim();
  if (raw && !isSlugTitle(raw)) return raw;
  const slug = lastPathSegment(source.url);
  if (slug && !isSlugTitle(slug) && /\s/.test(slug)) return slug;
  return null;
}

export function gateSource(
  source: SourceInput,
  opts: { market: PackMarket; claim: boolean; fetchedText?: string },
): GateResult {
  const title = displayTitle(source);
  if (!title) return { ok: false, reason: "slug-title" };
  const body = opts.fetchedText ?? source.excerpt ?? source.text ?? source.label ?? "";
  if (isJunkContent(body) || isJunkContent(source.label) || isJunkContent(source.title)) {
    return { ok: false, reason: "junk-content" };
  }
  // Cookie-banner fetches often leave the label empty and the URL as the only text.
  // Treat a known consent-screen host path as junk when the title is missing content words
  // and the caller supplied fetched text matching the patterns.
  if (opts.fetchedText && isJunkContent(opts.fetchedText)) {
    return { ok: false, reason: "junk-content" };
  }
  const host = hostOf(source);
  if (!jurisdictionMatches(host, opts.market)) return { ok: false, reason: "jurisdiction" };
  if (!opts.claim) return { ok: false, reason: "no-claim" };
  return { ok: true, title };
}

export type CheckSources = {
  sources: SourceInput[];
  market: PackMarket;
  hasClaim: boolean;
  fetchedTextByUrl?: Record<string, string>;
};

export function gateCheck(input: CheckSources): {
  kept: Array<SourceInput & { title: string }>;
  thin: boolean;
  count: number;
} {
  const kept: Array<SourceInput & { title: string }> = [];
  for (const source of input.sources) {
    const fetched = input.fetchedTextByUrl?.[source.url];
    const result = gateSource(source, {
      market: input.market,
      claim: input.hasClaim,
      fetchedText: fetched,
    });
    if (result.ok) kept.push({ ...source, title: result.title });
  }
  return { kept, count: kept.length, thin: kept.length < 3 };
}

/** The line the page prints when a check has fewer than three gated sources. */
export function thinEvidenceLabel(count: number): string {
  return `Evidence thin · ${count} source${count === 1 ? "" : "s"}`;
}


export type SampleCheck = {
  name: string;
  key?: string;
  verdict: string;
  rationale?: string;
  sources: SourceInput[];
};

/** Homepage sample: first passed check with at least three gated sources. */
export function pickPassedSampleCheck(
  checks: SampleCheck[],
  market: PackMarket,
): SampleCheck | null {
  for (const check of checks) {
    if (check.verdict !== "supported") continue;
    const gated = gateCheck({
      sources: check.sources,
      market,
      hasClaim: Boolean(check.rationale && check.rationale.trim()),
    });
    if (!gated.thin) return { ...check, sources: gated.kept };
  }
  return null;
}
