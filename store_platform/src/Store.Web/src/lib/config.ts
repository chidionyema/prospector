/**
 * App-level constants that are NOT part of the wire contract.
 *
 * TOS_VERSION: the backend register endpoint (E01-001) requires a non-empty
 * `tos_version`, but the authored Terms copy + canonical version string are owned
 * by E12-001 (status: todo). Until E12 lands, this is the single source of truth for
 * the version we record at registration — swap it (and link the authored copy on the
 * consent checkbox) in one place when E12-001 ships. Do NOT scatter literals.
 */
export const TOS_VERSION = '2026-06-15';

export const BRAND = {
  name: 'Mumchimp',
} as const;

export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, '') || undefined;

export const LEGAL = {
  entity: 'Mumchimp',
  // The full registered legal name + business address shown in the legal docs' "registered
  // details" lines. Single source of truth — set these once here before go-live (they are the
  // only operator-supplied legal facts left). `legalName` defaults to the operating entity.
  legalName: 'Mumchimp',
  address: 'Registered address available on request',
  governingLaw: 'England & Wales',
  // These must be a mailbox the operator actually reads: they are the only refund and privacy
  // contact a buyer is given, and they render on refund.tsx, terms.tsx, privacy.tsx, the footer
  // and every pack page. They previously pointed at prospector.store — a domain registered to
  // someone else and parked on a resale service — so every refund request went to a stranger.
  //
  // RESOLVED 2026-07-30 — the MX dependency this block used to warn about is satisfied:
  //   $ dig +short MX mumchimp.com @8.8.8.8   ->   5 smtp.google.com.
  // So support@mumchimp.com RECEIVES; a buyer's refund or privacy request arrives. The probe
  // re-checks this every run (`verify_store.sh` step 5) — do not re-assert it in prose here.
  //
  // DNS is managed at 123-reg (dcc.123-reg.co.uk -> DNS Management), NOT GoDaddy, even though
  // the nameservers are ns03/ns04.domaincontrol.com. Three docs said GoDaddy and sent the
  // founder to the wrong control panel; the nameserver host is not the registrar.
  //
  // STILL OPEN, and it is the *sending* direction, not this constant: the apex has no SPF and
  // no DKIM at any selector, while _dmarc is already `p=quarantine`. Mail sent AS @mumchimp.com
  // therefore fails DMARC. Receiving is unaffected. See verify_store.sh step 6.
  contactEmail: 'support@mumchimp.com',
  supportEmail: 'support@mumchimp.com',
} as const;

export const PADDLE_SETTINGS = {
  environment: process.env.NEXT_PUBLIC_PADDLE_ENVIRONMENT || 'sandbox',
  clientToken: process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN || '',
} as const;

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5291';
