/**
 * POST /api/ops/client-error — the page tells the server it broke.
 *
 * WHY THIS EXISTS. On 2026-08-18 the founder opened the console and got "a client-side
 * exception has occurred". That message is all Next.js shows in production, and the real
 * error only ever existed in one browser's console on one phone. There was no way to read
 * it from here, so the fault was guessed at instead of read. A crash the operator can see
 * and the operator's engineer cannot is a crash that gets diagnosed twice and fixed never.
 *
 * The ErrorBoundary posts here before it draws anything, so the stack lands in the machine's
 * stderr and comes back out of `fly logs -a prospector-engine`.
 *
 * NO AUTH, DELIBERATELY. The boundary fires when the page is already broken, and the most
 * likely broken state is one where the session is not usable. A route that needed a good
 * session would stay silent in exactly the case it exists for. What stops it being a log
 * hose instead: it takes POST only, reads at most 4KB, keeps the three fields it uses, and
 * answers 204 with no body, so it tells an anonymous caller nothing about the engine.
 */
import type { NextApiRequest, NextApiResponse } from 'next';

const MAX_FIELD = 4096;

function clip(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value.slice(0, MAX_FIELD);
}

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ ok: false, error: 'POST only' });
  }

  const body = (req.body ?? {}) as Record<string, unknown>;
  const where = clip(body.where) || 'unknown';
  const message = clip(body.message) || 'no message';
  const stack = clip(body.stack);
  const componentStack = clip(body.componentStack);

  // One line per field, prefixed, because these land in `fly logs` beside the scheduler's
  // output and have to be greppable there.
  console.error(`[ops-console client-error] where=${where}`);
  console.error(`[ops-console client-error] message=${message}`);
  if (stack) console.error(`[ops-console client-error] stack=${stack}`);
  if (componentStack) console.error(`[ops-console client-error] components=${componentStack}`);

  return res.status(204).end();
}
