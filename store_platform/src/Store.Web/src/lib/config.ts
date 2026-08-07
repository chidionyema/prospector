/**
 * App-level constants that are NOT part of the wire contract.
 *
 * TOS_VERSION: the backend register endpoint (E01-001) requires a non-empty
 * `tos_version`, but the authored Terms copy + canonical version string are owned
 * by E12-001 (status: todo). Until E12 lands, this is the single source of truth for
 * the version we record at registration, swap it (and link the authored copy on the
 * consent checkbox) in one place when E12-001 ships. Do NOT scatter literals.
 */
export const TOS_VERSION = '2026-06-15';

export const BRAND = {
  name: 'Mumchimp',
  /** Typographic wordmark split: first part in ink, second muted, period in teal. */
  wordmark: { first: 'Mum', second: 'chimp' } as const,
} as const;

export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, '') || undefined;

/**
 * The person behind the shop. EMPTY ON PURPOSE, and the site is correct with it empty.
 *
 * The problem it exists to solve is measured, not speculative: on 2026-08-06 the storefront named
 * no human anywhere, and `/about` -- whose own docblock claims to be "the moat rendered as a
 * person" -- contained 453 words, no name, no face, and had zero inbound links from any page
 * (`href="/about"` matched no file under `src/`). A shop selling £29-£199 research products from a
 * fully anonymous operator has to overcome that anonymity with volume of proof, which is exactly
 * the over-proving the site was criticised for. One real name does more than another paragraph of
 * evidence.
 *
 * WHY IT IS NOT FILLED IN HERE: a founder bio is a claim about a real person, and this codebase's
 * first rule is that claims are sourced, not invented. Inventing a plausible name, photo and
 * history for the operator of a shop that sells "every claim has a clickable source" would be the
 * single worst thing on the site. The founder supplies these; nothing else has to change.
 *
 * `name` is the switch. While it is empty every consumer renders nothing at all -- no placeholder,
 * no "coming soon", no grey avatar silhouette -- so an unfilled field can never ship as a visible
 * gap. `photo` is independently optional: a real name with no photo is honest and still works.
 */
export const FOUNDER = {
  /** Full name, as the founder wants to be credited. Empty disables every founder surface. */
  name: 'Chidi',
  /** Optional. What they were doing before this, in a few words. */
  role: '',
  /** Optional. Two or three sentences, first person. Why this shop exists. */
  bio: "I always wanted to run my own business. I spent a lot of time coming up with ideas, and after a few failed attempts at launching them properly, I'd talk myself out of the next one before it got anywhere. What I actually enjoyed was the ideating, not the talking myself out of it. So I built the part I kept losing to doubt, and made it check every idea harder than I ever did. That's the seed this platform grew from.",
  /** Optional. A path under /public, e.g. '/founder.jpg'. Omitted renders text only. */
  photo: '',
  /** Optional. A profile the reader can check: LinkedIn, GitHub, a personal site. */
  profileUrl: '',
} as const;

/** True only when there is a real person to name. Every founder surface branches on this. */
export const hasFounder = (): boolean => FOUNDER.name.trim().length > 0;

export const LEGAL = {
  entity: 'Mumchimp',
  // The full registered legal name + business address shown in the legal docs' "registered
  // details" lines. Single source of truth, set these once here before go-live (they are the
  // only operator-supplied legal facts left). `legalName` defaults to the operating entity.
  legalName: 'Mumchimp',
  address: 'Registered address available on request',
  governingLaw: 'England & Wales',
  // These must be a mailbox the operator actually reads: they are the only refund and privacy
  // contact a buyer is given, and they render on refund.tsx, terms.tsx, privacy.tsx, the footer
  // and every pack page. They previously pointed at prospector.store, a domain registered to
  // someone else and parked on a resale service, so every refund request went to a stranger.
  //
  // RESOLVED 2026-07-30, the MX dependency this block used to warn about is satisfied:
  //   $ dig +short MX mumchimp.com @8.8.8.8   ->   5 smtp.google.com.
  // So support@mumchimp.com RECEIVES; a buyer's refund or privacy request arrives. The probe
  // re-checks this every run (`verify_store.sh` step 5), do not re-assert it in prose here.
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

/**
 * The API's real origin. Correct for server-side fetches, and for links the BROWSER NAVIGATES to
 * (`/download/{token}` answers with a 302 to a presigned URL and must be followed as a navigation,
 * so it cannot go through the proxy). Wrong for browser XHR, use API_FETCH_BASE for that.
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5291';

/**
 * Base for any fetch that MIGHT run in the browser.
 *
 * On the server there is no origin and no CORS, so the API's real origin is used directly. In the
 * browser it resolves to `/api/store`, which next.config.ts rewrites to the same API, making the
 * request first-party to the storefront, exactly as the auth calls already are.
 *
 * This exists because CORS failure here is silent and partial. Reproduced 2026-08-01: with the API
 * allowing only `http://localhost:3000` and the storefront served on `:3001`, sign-in kept working
 * (it goes through the proxy) while `/events` failed with "No 'Access-Control-Allow-Origin' header
 * is present". The same shape on Fly takes out the BUY BUTTON, checkout is a browser POST to the
 * API origin, while every page still renders and every log looks healthy. Routing browser XHR
 * through the proxy removes a whole class of deploy-time misconfiguration from the money path
 * instead of relying on `Store__AllowedOrigin` being written out exhaustively.
 *
 * `Store__AllowedOrigin` still matters and must still be set: the API derives the post-checkout
 * redirect base from it (CheckoutEndpoints.cs BuildRedirectUrls). Getting it wrong there sends a
 * paying buyer to the wrong host, visible and loud, rather than silently breaking checkout.
 */
export const API_FETCH_BASE = typeof window === 'undefined' ? API_BASE_URL : '/api/store';
