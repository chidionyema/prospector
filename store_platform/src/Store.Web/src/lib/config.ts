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
  // HARD DEPENDENCY — mumchimp.com had NO MX records when these were set
  // (`dig +short MX mumchimp.com` returned empty; NS = ns03/ns04.domaincontrol.com, i.e. GoDaddy).
  // Mail to these addresses BOUNCES until MX records exist. Do not deploy this file until
  // `dig +short MX mumchimp.com` returns at least one host. An address on a domain with no mail
  // routing is the same silent failure as the prospector.store address, in a new costume.
  //
  // 2026-07-30 — FOUNDER DECISION: support@mumchimp.com is the address, and it ships now.
  // The MX warning above is NOT resolved: `dig +short MX mumchimp.com` and the same query against
  // 8.8.8.8 both returned empty at 01:35 BST, NS still ns03/ns04.domaincontrol.com. Until MX
  // records exist on that zone, mail sent to this address bounces at the sender, so a buyer's
  // refund or privacy request never arrives. Adding the MX records at GoDaddy (or pointing the
  // zone at a mail provider) is the outstanding action — no code change is needed once they exist.
  contactEmail: 'support@mumchimp.com',
  supportEmail: 'support@mumchimp.com',
} as const;

export const PADDLE_SETTINGS = {
  environment: process.env.NEXT_PUBLIC_PADDLE_ENVIRONMENT || 'sandbox',
  clientToken: process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN || '',
} as const;

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5291';
