/**
 * The badge that says which estate is on screen.
 *
 * The rule being pinned: "production" is claimed only when this process is genuinely inside a Fly
 * machine. A console served by a laptop dev server and one served by production look identical,
 * and they are one bookmark apart. A badge that says production when it cannot prove it is worse
 * than no badge, because it is only ever read at a glance.
 *
 * Also pinned: it answers without a session. The operator most in need of knowing which estate
 * they are about to touch is the one still looking at the login screen.
 */
import { afterEach, describe, expect, it } from 'vitest';

import { makeReq, makeRes } from './helpers';

const { default: handler } = await import('@/pages/api/ops/where');
type Where = import('@/pages/api/ops/where').Where;

const KEYS = ['FLY_MACHINE_ID', 'FLY_APP_NAME', 'FLY_REGION'] as const;
const saved = Object.fromEntries(KEYS.map((k) => [k, process.env[k]]));

afterEach(() => {
  for (const k of KEYS) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
});

describe('which engine is this console attached to', () => {
  it('says production, with the machine, when it runs inside a Fly machine', () => {
    process.env.FLY_MACHINE_ID = '80d34da6636478';
    process.env.FLY_APP_NAME = 'prospector-engine';
    process.env.FLY_REGION = 'lhr';

    const { res, captured } = makeRes();
    handler(makeReq({ method: 'GET' }), res);

    expect(captured.status).toBe(200);
    expect((captured.body as Where).place).toBe('production');
    expect((captured.body as Where).machine).toBe('80d34da6636478');
    expect((captured.body as Where).label).toBe('prospector-engine · 80d34d · lhr');
  });

  it('says NOT production when FLY_MACHINE_ID is absent, whatever else is set', () => {
    delete process.env.FLY_MACHINE_ID;
    // A stale FLY_APP_NAME in a shell is exactly how a laptop talks itself into "production".
    process.env.FLY_APP_NAME = 'prospector-engine';

    const { res, captured } = makeRes();
    handler(makeReq({ method: 'GET' }), res);

    expect((captured.body as Where).place).toBe('local');
    expect((captured.body as Where).label).toContain('NOT production');
  });

  it('is never cached, so a console left open across a redeploy stops claiming the old machine', () => {
    const { res, captured } = makeRes();
    handler(makeReq({ method: 'GET' }), res);
    expect(captured.headers['Cache-Control']).toBe('no-store');
  });
});
