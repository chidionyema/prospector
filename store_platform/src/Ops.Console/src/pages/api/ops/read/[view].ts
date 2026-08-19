/**
 * GET /api/ops/read/<view>
 *
 * The only read door. Every panel in the console comes through here, and everything it returns
 * is whatever `prospector.ops.console_api` produced — this handler adds no number of its own.
 *
 * The view name is checked against an allow-list rather than passed through. It becomes an argv
 * element in a spawned process; an unchecked one is an argument-injection surface even though
 * `spawn` takes an array and never a shell string.
 */
import type { NextApiRequest, NextApiResponse } from 'next';

import { requireAuth } from '@/lib/auth';
import { EXPECTED_CONTRACT, opsRead } from '@/lib/ops';
import { logConsoleEvent } from '@/lib/oplog';

export const VIEWS = [
  'engine_location',
  'status',
  'queue',
  'drain',
  'providers',
  'routing',
  'spend',
  'money',
  'data',
  'metrics',
  'runs',
  'run',
  'candidate',
  'config',
  'intents',
  'tools',
  'job',
  'undo',
  'catalogue',
  'pack',
  'shelf',
  'method',
  'docs',
  'incidents',
  'content_rules',
  'orders',
  'order',
  'sales',
  'deliveries',
  'disputes',
  'console_log',
] as const;

/** Arguments each view accepts. Anything else in the query string is dropped, not forwarded. */
const ALLOWED_ARGS: Record<string, string[]> = {
  status: ['lookback_h'],
  queue: ['lookback_h'],
  drain: ['side'],
  metrics: ['window_days'],
  runs: ['days'],
  run: ['run_id', 'days'],
  candidate: ['candidate_id', 'days', 'run_id'],
  config: ['history_limit'],
  intents: ['limit'],
  pack: ['id'],
  job: ['job'],
  orders: ['q', 'status', 'packId', 'limit', 'offset'],
  order: ['order_id'],
  sales: ['days'],
  deliveries: ['state', 'limit'],
  disputes: ['days'],
  docs: ['name'],
  console_log: ['limit'],
};

/**
 * A read slower than this earns a line even though it worked. Measured in the container on
 * 2026-08-18, the slowest view was `data` at 2.32s and the rest were under 2s, so anything at
 * five seconds is a change worth having a record of.
 */
const SLOW_MS = 5_000;

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');

  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).json({ ok: false, error: 'reads are GET' });
  }

  const view = String(req.query.view || '');

  const gate = requireAuth(req);
  if (gate) {
    // THE BLANK-TAB SIGNATURE. When a session expires, every panel on the page 401s at the same
    // moment and the page redirects to /login. That is what happened on 2026-08-18, and it left
    // no trace at all, so the cause was argued about rather than read. One line per refused read
    // makes the next one obvious: a burst of `unauthenticated` across many views, at one time.
    logConsoleEvent({
      kind: 'read_refused',
      view,
      status: gate.status,
      error_kind: gate.status === 401 ? 'unauthenticated' : 'unconfigured',
    });
    return res.status(gate.status).json(gate.body);
  }

  if (!(VIEWS as readonly string[]).includes(view)) {
    logConsoleEvent({ kind: 'read_failed', view, status: 404, error_kind: 'UnknownView' });
    return res.status(404).json({
      ok: false,
      error: `unknown view ${view}`,
      views: VIEWS,
    });
  }

  const args: Record<string, string> = {};
  for (const key of ALLOWED_ARGS[view] || []) {
    const v = req.query[key];
    if (typeof v === 'string' && v !== '') args[key] = v;
  }

  const started = Date.now();
  try {
    const { envelope } = await opsRead(view, args);
    const tookMs = Date.now() - started;
    if (envelope.contract !== EXPECTED_CONTRACT) {
      // Say it out loud rather than rendering blanks. A console silently talking to an engine
      // whose contract moved is how a panel comes to report zeroes with total confidence.
      const error =
        `the engine gateway speaks contract ${envelope.contract}; this console was built ` +
        `for ${EXPECTED_CONTRACT}. Restart the console after pulling.`;
      logConsoleEvent({
        kind: 'read_failed',
        view,
        status: 500,
        took_ms: tookMs,
        error_kind: 'ContractMismatch',
        error,
      });
      return res.status(500).json({ ok: false, error });
    }
    // The gateway's own failure is passed through with its reason intact, at 502 — it is the
    // engine that failed, not the request.
    if (!envelope.ok) {
      logConsoleEvent({
        kind: 'read_failed',
        view,
        status: 502,
        took_ms: tookMs,
        error_kind: String((envelope as { error_kind?: unknown }).error_kind ?? 'EngineFailed'),
        error: String((envelope as { error?: unknown }).error ?? ''),
      });
      return res.status(502).json(envelope);
    }
    if (tookMs >= SLOW_MS) {
      logConsoleEvent({ kind: 'read_slow', view, status: 200, took_ms: tookMs });
    }
    return res.status(200).json(envelope);
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err);
    logConsoleEvent({
      kind: 'read_failed',
      view,
      status: 500,
      took_ms: Date.now() - started,
      error_kind: 'GatewayUnreachable',
      error,
    });
    return res.status(500).json({ ok: false, error, error_kind: 'GatewayUnreachable' });
  }
}
