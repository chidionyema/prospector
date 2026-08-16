/**
 * The write door.
 *
 * The two things that must never regress: no write reaches the engine without a confirmation
 * token, and no price write exists at all. Both are asserted here AND in the Python gateway
 * (`tests/ops/test_console_api.py`), because a fence that lives only in the button is a fence any
 * second caller walks around.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { envelope, makeReq, makeRes } from './helpers';

const opsAct = vi.fn();
const opsPreview = vi.fn();
vi.mock('@/lib/ops', () => ({
  opsAct: (...args: unknown[]) => opsAct(...args),
  opsPreview: (...args: unknown[]) => opsPreview(...args),
}));

const { default: handler, ACTIONS } = await import('@/pages/api/ops/act/[action]');
const { mintSession, COOKIE_NAME } = await import('@/lib/auth');

function signedIn(): string {
  return `${COOKIE_NAME}=${encodeURIComponent(mintSession())}`;
}

beforeEach(() => {
  opsAct.mockReset();
  opsPreview.mockReset();
  opsPreview.mockResolvedValue({
    envelope: envelope({ data: { confirm: 'tok-123', confirm_expires_in_s: 600 } }),
    exitCode: 0,
    stderr: '',
  });
  opsAct.mockResolvedValue({
    envelope: envelope({ data: { applied: true, changed: true } }),
    exitCode: 0,
    stderr: '',
  });
  process.env.CONTROL_CENTER_PASSWORD = 'test-password';
});

describe('no write happens without a confirmation', () => {
  it('answers 428 with the preview when no token is quoted', async () => {
    const { res, captured } = makeRes();
    await handler(
      makeReq({
        method: 'POST',
        query: { action: 'pause.arm' },
        body: { payload: { scope: 'all', reason: 'testing' } },
        cookie: signedIn(),
      }),
      res,
    );
    expect(captured.status).toBe(428);
    expect((captured.body as { error_kind: string }).error_kind).toBe('ConfirmationRequired');
    expect(opsAct).not.toHaveBeenCalled();
  });

  it('applies only when the token is quoted', async () => {
    const { res, captured } = makeRes();
    await handler(
      makeReq({
        method: 'POST',
        query: { action: 'pause.arm' },
        body: { confirm: 'tok-123', payload: { scope: 'all', reason: 'testing' } },
        cookie: signedIn(),
      }),
      res,
    );
    expect(captured.status).toBe(200);
    expect(opsAct).toHaveBeenCalledWith(
      'pause.arm',
      { scope: 'all', reason: 'testing', actor: 'ops_console' },
      'tok-123',
    );
  });

  it('passes an expired token refusal back as 428, not as a success', async () => {
    opsAct.mockResolvedValue({
      envelope: envelope({ ok: false, error: 'that confirmation expired', error_kind: 'ConfirmationRequired' }),
      exitCode: 4,
      stderr: '',
    });
    const { res, captured } = makeRes();
    await handler(
      makeReq({
        method: 'POST',
        query: { action: 'pause.arm' },
        body: { confirm: 'stale', payload: { scope: 'all', reason: 'x' } },
        cookie: signedIn(),
      }),
      res,
    );
    expect(captured.status).toBe(428);
  });

  it('previews without writing', async () => {
    const { res, captured } = makeRes();
    await handler(
      makeReq({
        method: 'POST',
        query: { action: 'config.set' },
        body: { preview: true, payload: { key: 'spend.daily_cap_usd', value: 5 } },
        cookie: signedIn(),
      }),
      res,
    );
    expect(captured.status).toBe(200);
    expect(opsAct).not.toHaveBeenCalled();
    expect(opsPreview).toHaveBeenCalledOnce();
  });
});

describe('the actor is the server’s to decide', () => {
  it('overwrites an actor supplied by the caller', async () => {
    const { res } = makeRes();
    await handler(
      makeReq({
        method: 'POST',
        query: { action: 'pause.disarm' },
        body: { confirm: 't', payload: { scope: 'all', reason: 'x', actor: 'the-founder' } },
        cookie: signedIn(),
      }),
      res,
    );
    const sent = opsAct.mock.calls[0][1] as { actor: string };
    expect(sent.actor).toBe('ops_console');
  });
});

describe('prices are off limits', () => {
  it('exposes no price action', () => {
    expect(ACTIONS).not.toContain('catalogue.set_price');
    expect(ACTIONS).not.toContain('catalogue.reprice');
    expect(ACTIONS.filter((a) => a.includes('price'))).toEqual([]);
  });

  it('explains itself rather than 404ing as though the feature were merely missing', async () => {
    const { res, captured } = makeRes();
    await handler(
      makeReq({
        method: 'POST',
        query: { action: 'catalogue.set_price' },
        body: { payload: { id: 'x', pence: 100 } },
        cookie: signedIn(),
      }),
      res,
    );
    expect(captured.status).toBe(404);
    expect(String((captured.body as { note: string }).note)).toContain('bridge.py');
    expect(opsPreview).not.toHaveBeenCalled();
    expect(opsAct).not.toHaveBeenCalled();
  });

  it('does allow the one non-price catalogue write', () => {
    expect(ACTIONS).toContain('catalogue.set_listing');
  });
});

describe('the door itself', () => {
  it('is only POST', async () => {
    const { res, captured } = makeRes();
    await handler(makeReq({ method: 'GET', query: { action: 'pause.arm' }, cookie: signedIn() }), res);
    expect(captured.status).toBe(405);
  });

  it('refuses an unauthenticated write before it previews anything', async () => {
    const { res, captured } = makeRes();
    await handler(
      makeReq({ method: 'POST', query: { action: 'pause.arm' }, body: { preview: true } }),
      res,
    );
    expect(captured.status).toBe(401);
    expect(opsPreview).not.toHaveBeenCalled();
  });

  it('refuses every write when no password is configured', async () => {
    delete process.env.CONTROL_CENTER_PASSWORD;
    const { res, captured } = makeRes();
    await handler(
      makeReq({ method: 'POST', query: { action: 'config.set' }, body: { preview: true } }),
      res,
    );
    expect(captured.status).toBe(503);
  });

  it('rejects an action outside the allow-list', async () => {
    const { res, captured } = makeRes();
    await handler(
      makeReq({ method: 'POST', query: { action: 'rm -rf' }, body: {}, cookie: signedIn() }),
      res,
    );
    expect(captured.status).toBe(404);
    expect(opsPreview).not.toHaveBeenCalled();
  });

  it('never caches', async () => {
    const { res, captured } = makeRes();
    await handler(makeReq({ method: 'GET', query: { action: 'pause.arm' } }), res);
    expect(captured.headers['Cache-Control']).toBe('no-store');
  });
});
