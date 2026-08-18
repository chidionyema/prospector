/**
 * GET /api/ops/where — which engine is this console attached to.
 *
 * The founder asked for this after the Fly cutover: "ops need to know from the UI". Until now the
 * only way to tell a production console from one served by a laptop dev server was to look at the
 * address bar, and the two are one bookmark apart. A console that silently shows a developer's
 * laptop while the operator believes they are watching production is how a real pause gets armed
 * on the wrong machine.
 *
 * This is answered on the SERVER, not the browser, and it costs nothing. The ops console is served
 * by the engine process itself, so the engine it reads is always the machine this handler runs on.
 * `FLY_MACHINE_ID` is set by Fly inside a machine and is absent everywhere else, so its presence is
 * the whole discriminator. No probe, no round trip, no chance of the answer being stale.
 *
 * Deliberately readable WITHOUT a session. It carries no secret — an app name, a machine id and a
 * region — and an operator staring at a login screen is exactly the person who needs to know which
 * estate they are about to sign in to.
 */
import type { NextApiRequest, NextApiResponse } from 'next';

export type Where = {
  ok: true;
  /** 'production' when this process runs inside a Fly machine, 'local' otherwise. */
  place: 'production' | 'local';
  app: string | null;
  machine: string | null;
  region: string | null;
  /** One short line fit to print in a header badge. */
  label: string;
};

export default function handler(_req: NextApiRequest, res: NextApiResponse<Where>) {
  // No caching. A console kept open across a redeploy must not keep claiming the old machine.
  res.setHeader('Cache-Control', 'no-store');

  const machine = process.env.FLY_MACHINE_ID || null;
  const app = process.env.FLY_APP_NAME || null;
  const region = process.env.FLY_REGION || null;
  const place = machine ? 'production' : 'local';

  // Six characters of the machine id is enough to see a redeploy move you to a new machine, and
  // short enough to sit in a header on a phone.
  const label =
    place === 'production'
      ? `${app ?? 'fly'} · ${machine!.slice(0, 6)}${region ? ` · ${region}` : ''}`
      : 'this laptop — NOT production';

  res.status(200).json({ ok: true, place, app, machine, region, label });
}
