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
  name: 'Prospector Store',
} as const;

export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, '') || undefined;

export const LEGAL = {
  entity: 'Prospector Platform',
  governingLaw: 'England & Wales',
  contactEmail: 'privacy@prospector.store',
  supportEmail: 'support@prospector.store',
} as const;

export const PADDLE_SETTINGS = {
  environment: process.env.NEXT_PUBLIC_PADDLE_ENVIRONMENT || 'sandbox',
  clientToken: process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN || '',
} as const;

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5291';
