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

export const VIEWS = [
  'status',
  'queue',
  'providers',
  'routing',
  'spend',
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
] as const;

/** Arguments each view accepts. Anything else in the query string is dropped, not forwarded. */
const ALLOWED_ARGS: Record<string, string[]> = {
  status: ['lookback_h'],
  queue: ['lookback_h'],
  metrics: ['window_days'],
  runs: ['days'],
  run: ['run_id', 'days'],
  candidate: ['candidate_id', 'days', 'run_id'],
  config: ['history_limit'],
  intents: ['limit'],
  pack: ['id'],
  job: ['job'],
};

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');

  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).json({ ok: false, error: 'reads are GET' });
  }

  const gate = requireAuth(req);
  if (gate) return res.status(gate.status).json(gate.body);

  const view = String(req.query.view || '');
  if (!(VIEWS as readonly string[]).includes(view)) {
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

  try {
    const { envelope } = await opsRead(view, args);
    if (envelope.contract !== EXPECTED_CONTRACT) {
      // Say it out loud rather than rendering blanks. A console silently talking to an engine
      // whose contract moved is how a panel comes to report zeroes with total confidence.
      return res.status(500).json({
        ok: false,
        error:
          `the engine gateway speaks contract ${envelope.contract}; this console was built ` +
          `for ${EXPECTED_CONTRACT}. Restart the console after pulling.`,
      });
    }
    // The gateway's own failure is passed through with its reason intact, at 502 — it is the
    // engine that failed, not the request.
    return res.status(envelope.ok ? 200 : 502).json(envelope);
  } catch (err) {
    return res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
      error_kind: 'GatewayUnreachable',
    });
  }
}
