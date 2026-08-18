/**
 * Fake req/res for a Next Pages API handler.
 *
 * The handlers are plain functions of (req, res), so they can be called directly. That is the
 * point: a test that starts a server measures the server, and every one of these assertions is
 * about the handler's own decisions — the auth gate, the allow-lists, the confirm step.
 */
import type { NextApiRequest, NextApiResponse } from 'next';

export type Captured = {
  status: number;
  body: unknown;
  headers: Record<string, string | string[]>;
};

export function makeReq(init: {
  method?: string;
  query?: Record<string, string | string[]>;
  body?: unknown;
  cookie?: string;
}): NextApiRequest {
  return {
    method: init.method ?? 'GET',
    query: init.query ?? {},
    body: init.body,
    headers: init.cookie ? { cookie: init.cookie } : {},
  } as unknown as NextApiRequest;
}

export function makeRes(): { res: NextApiResponse; captured: Captured } {
  const captured: Captured = { status: 0, body: undefined, headers: {} };
  const res = {
    setHeader(name: string, value: string | string[]) {
      captured.headers[name] = value;
      return res;
    },
    status(code: number) {
      captured.status = code;
      return res;
    },
    json(body: unknown) {
      captured.body = body;
      return res;
    },
    // A 204 has no body, so a route that ends instead of sending JSON needs this to be
    // testable at all. Without it the call throws `res.end is not a function` and the test
    // reads as a broken route.
    end(body?: unknown) {
      captured.body = body;
      return res;
    },
  } as unknown as NextApiResponse;
  return { res, captured };
}

/** An envelope shaped exactly like `console_api`'s, so tests never invent a second contract. */
export function envelope(over: Record<string, unknown> = {}) {
  return {
    ok: true,
    contract: 1,
    as_of: 1_755_300_000,
    as_of_iso: '2026-08-16T00:00:00Z',
    took_ms: 12,
    data: {},
    error: null,
    error_kind: null,
    ...over,
  };
}
