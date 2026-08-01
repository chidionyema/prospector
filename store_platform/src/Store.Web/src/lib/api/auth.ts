import { API_BASE_URL } from '@/lib/config';

/**
 * The customer-account API.
 *
 * ── Why there is no token in this file ────────────────────────────────────────────────────────
 * The API sets an HttpOnly cookie named "jwt" on login, refresh and social callback
 * (Store.Api/Identity/JwtTokenService.cs:128) and reads it back on every request
 * (AuthServiceCollectionExtensions.cs, JwtBearerEvents.OnMessageReceived). Nothing here ever sees,
 * stores or forwards an access token, so there is no value for an XSS payload to steal, HttpOnly
 * means script cannot read the cookie even from our own origin. localStorage, sessionStorage and a
 * module-level variable all fail that test.
 *
 * ── Why two base URLs ─────────────────────────────────────────────────────────────────────────
 * XHR goes through PROXY_BASE ("/api"), which next.config.ts:78-79 rewrites to the API's /v1. That
 * makes every data call same-ORIGIN, which buys three things at once:
 *   • the SameSite=Strict cookie is sent (a direct cross-origin call would drop it silently),
 *   • CORS never enters the picture, so an Origin the API has not been told about cannot break
 *     the storefront after a domain change,
 *   • the CSP connect-src 'self' already covers it. (next.config.ts:29 derives the cross-origin
 *     allowance from NEXT_PUBLIC_API_URL defaulting to :8080 while config.ts:52 defaults the
 *     client to :5291, a direct call with the variable unset is blocked by our own CSP.)
 *
 * OAuth is the exception and MUST bypass the proxy. The provider's correlation cookie, and the
 * Identity.External cookie the callback reads, are set by the API on the API's own origin; routed
 * through the proxy they would be written against the web origin and the callback would fail
 * correlation. So the social buttons navigate to DIRECT_BASE. It is a top-level navigation, not a
 * fetch, so CSP connect-src does not apply, and it is location.assign rather than a form submit
 * because next.config.ts:33 sets form-action 'self', which WOULD block a cross-origin form post.
 */

/** Same-origin proxy for all data calls. next.config.ts rewrites /api/:path* → {API}/v1/:path*. */
const PROXY_BASE = '/api';

/** The API's real origin. Used ONLY for full-page OAuth navigation, see the note above. */
const DIRECT_BASE = `${API_BASE_URL.replace(/\/+$/, '')}/v1`;

export class AuthError extends Error {
  readonly status: number;
  /** The API's stable error code, e.g. "Auth.InvalidCredentials". Safe to branch on; the message is not. */
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = 'AuthError';
    this.status = status;
    this.code = code;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PROXY_BASE}${path}`, {
    ...init,
    // Explicit even though same-origin is the fetch default: this is the line that makes the
    // whole cookie-session design work, and a default is a poor place to keep a load-bearing fact.
    credentials: 'same-origin',
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  const body: unknown = text ? JSON.parse(text) : {};

  if (!res.ok) {
    const err = body as { error?: string; code?: string };
    throw new AuthError(
      err.error || `Request failed (${res.status})`,
      res.status,
      err.code || 'Unknown',
    );
  }

  return body as T;
}

// ── Shapes, mirroring Store.Api/Identity/AuthDtos.cs ───────────────────────────────────────────

export interface Profile {
  first_name: string;
  last_name: string;
  display_name: string;
  phone: string;
  bio: string;
  website: string;
  avatar_url: string;
  country: string;
}

export interface Account {
  id: string;
  email: string;
  username: string;
  email_confirmed: boolean;
  tos_version_accepted: string | null;
  created_at: string;
  profile: Profile;
}

export interface Session {
  family_id: string;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string;
  expires: string;
  is_current: boolean;
}

export interface OrderItem {
  pack_id: string;
  pack_title: string;
  status: string;
  /** null when the entitlement is not Active, a refunded purchase stays visible but undownloadable. */
  download_path: string | null;
}

export interface Order {
  id: number;
  created_at: string;
  amount_pence: number;
  currency: string;
  status: string;
  items: OrderItem[];
}

export interface OrderHistory {
  email_confirmed: boolean;
  orders: Order[];
}

export interface AuthResponse {
  token: string;
  user_id: string;
  username: string | null;
  email: string | null;
  expires: string;
  message: string | null;
}

export interface Provider {
  name: string;
  display_name: string;
}

export type ProfileEdit = Omit<Profile, 'display_name'>;

// ── Calls ─────────────────────────────────────────────────────────────────────────────────────

export const auth = {
  /**
   * Register. Deliberately does NOT sign the customer in: the API returns an empty token until the
   * address is confirmed (RegisterCommand), because order history is joined to an account by email
   * string and an unverified signup on someone else's address would otherwise read their purchases.
   */
  register: (username: string, email: string, password: string, tosVersion: string) =>
    call<AuthResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password, tos_version: tosVersion }),
    }),

  /** The field is `username`, not `email`, LoginCommand accepts either value in it. */
  login: (username: string, password: string) =>
    call<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  logout: () => call<{ message: string }>('/auth/logout', { method: 'POST' }),

  me: () => call<Account>('/auth/me'),

  updateProfile: (profile: ProfileEdit) =>
    call<Profile>('/auth/me', { method: 'PUT', body: JSON.stringify(profile) }),

  changePassword: (currentPassword: string, newPassword: string) =>
    call<{ message: string }>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  forgotPassword: (email: string) =>
    call<{ message: string }>('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),

  resetPassword: (email: string, token: string, newPassword: string) =>
    call<{ message: string }>('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ email, token, new_password: newPassword }),
    }),

  verifyEmail: (userId: string, token: string) =>
    call<{ message: string }>('/auth/verify-email', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, token }),
    }),

  resendVerification: (email: string) =>
    call<{ message: string }>('/auth/resend-verification', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),

  orders: () => call<OrderHistory>('/auth/me/orders'),

  sessions: () => call<Session[]>('/auth/sessions'),

  revokeSession: (familyId: string) =>
    call<void>(`/auth/sessions/${encodeURIComponent(familyId)}`, { method: 'DELETE' }),
};

export const social = {
  /** Only providers the API actually has credentials for; an empty list means hide the section. */
  providers: () => call<{ providers: Provider[] }>('/auth/external/providers'),

  /** Linked providers for the signed-in customer. */
  linked: () => call<{ providers: string[] }>('/auth/external/logins'),

  unlink: (provider: string) =>
    call<{ message: string }>(`/auth/external/unlink/${encodeURIComponent(provider)}`, {
      method: 'DELETE',
    }),

  /** Exchange the one-time code from the callback redirect. Sent in the BODY, never a URL. */
  exchange: (code: string) =>
    call<AuthResponse>('/auth/external/exchange', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  /** Ask the API for the ticketed start URL that links a provider to an EXISTING account. */
  linkStart: (provider: string) =>
    call<{ start_url: string }>(`/auth/external/link/${encodeURIComponent(provider)}`, {
      method: 'POST',
    }),

  /**
   * Begin sign-in with a provider. A full-page navigation to the API origin, see the two-base
   * note at the top of this file. Never a fetch: the provider answers with a 302 the browser must
   * follow as a document navigation, and never a form, because CSP form-action is 'self'.
   */
  signIn(provider: string, returnTo: string) {
    const url = `${DIRECT_BASE}/auth/external/challenge/${encodeURIComponent(provider)}`
      + `?redirect_url=${encodeURIComponent(returnTo)}`;
    window.location.assign(url);
  },

  /** Same navigation rule as signIn; the path comes from the API because it carries a ticket. */
  followStartUrl(startUrl: string) {
    window.location.assign(`${API_BASE_URL.replace(/\/+$/, '')}${startUrl}`);
  },
};
