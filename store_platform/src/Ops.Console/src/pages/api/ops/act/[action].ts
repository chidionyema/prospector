/**
 * POST /api/ops/act/<action>
 *
 * The only write door. Two steps, always:
 *
 *   1. `{ preview: true, payload }`  -> what would change, plus a confirmation token
 *   2. `{ confirm: <token>, payload }` -> the write, and a receipt
 *
 * The token is checked in PYTHON, in `console_api.dispatch`. This handler cannot skip it and
 * neither can the CLI, because both land in the same function. A fence in the keyboard is a
 * fence a second caller walks around.
 *
 * Nothing here touches a price. `catalogue.set_price` is refused by name in the gateway with the
 * reason, so the console says why rather than 404ing as though the feature were merely missing.
 */
import type { NextApiRequest, NextApiResponse } from 'next';

import { requireAuth } from '@/lib/auth';
import { opsAct, opsPreview } from '@/lib/ops';

export const ACTIONS = [
  'pause.arm',
  'pause.disarm',
  'routing.set_moat_primary',
  'config.set',
  'config.restore',
  'catalogue.set_listing',
  'shelf.repair_copy',
  'shelf.publish_pending',
  'shelf.regate',
  'daemon.restart',
  'tools.run',
  'tools.undo',
  'deliveries.resend',
  // Which platform the engine runs on. `engine.switch` starts a real cutover, which takes
  // minutes and opens a downtime window, so it returns as soon as the run is started and the
  // page follows the engine_location view to see it land.
  'engine.switch',
  'engine.arm',
  'engine.disarm',
] as const;

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');

  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ ok: false, error: 'writes are POST' });
  }

  const gate = requireAuth(req);
  if (gate) return res.status(gate.status).json(gate.body);

  const action = String(req.query.action || '');
  if (!(ACTIONS as readonly string[]).includes(action)) {
    return res.status(404).json({
      ok: false,
      error: `unknown action ${action}`,
      actions: ACTIONS,
      note:
        'Price writes are not implemented. prospector/bridge.py is the money rail and must ' +
        'mint the Stripe Price and write the catalogue row together. See ' +
        'docs/ADMIN_CONSOLE_PROGRAM.md §7.',
    });
  }

  const body = (req.body ?? {}) as {
    payload?: Record<string, unknown>;
    preview?: boolean;
    confirm?: string;
  };
  const payload: Record<string, unknown> = { ...(body.payload || {}) };

  // The actor is stamped by the SERVER, never taken from the request. An audit row whose actor
  // the caller chose is not an audit row.
  payload.actor = 'ops_console';

  try {
    if (body.preview) {
      const { envelope } = await opsPreview(action, payload);
      return res.status(envelope.ok ? 200 : 400).json(envelope);
    }

    const confirm = String(body.confirm || '');
    if (!confirm) {
      // Do not send an empty token to the gateway just to be told no. Answer with the preview,
      // which is what the operator needs next anyway.
      const { envelope } = await opsPreview(action, payload);
      return res.status(428).json({
        ...envelope,
        ok: false,
        error: 'confirm the preview before this is written',
        error_kind: 'ConfirmationRequired',
      });
    }

    const { envelope, exitCode } = await opsAct(action, payload, confirm);
    if (exitCode === 4) return res.status(428).json(envelope);
    return res.status(envelope.ok ? 200 : 400).json(envelope);
  } catch (err) {
    return res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
      error_kind: 'GatewayUnreachable',
    });
  }
}
