/**
 * The read door.
 *
 * These tests pin the decisions the handler makes on its own: fail-closed auth, the view
 * allow-list, the argument allow-list, and the contract check. The gateway itself is mocked,
 * because what is under test is the door, not the engine behind it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { envelope, makeReq, makeRes } from './helpers';

const opsRead = vi.fn();
vi.mock('@/lib/ops', () => ({
  EXPECTED_CONTRACT: 1,
  opsRead: (...args: unknown[]) => opsRead(...args),
}));

const { default: handler, VIEWS } = await import('@/pages/api/ops/read/[view]');
const { mintSession, COOKIE_NAME } = await import('@/lib/auth');

const PASSWORD = 'test-password';
function signedIn(): string {
  return `${COOKIE_NAME}=${encodeURIComponent(mintSession())}`;
}

beforeEach(() => {
  opsRead.mockReset();
  opsRead.mockResolvedValue({ envelope: envelope(), exitCode: 0, stderr: '' });
  process.env.CONTROL_CENTER_PASSWORD = PASSWORD;
});

describe('auth is a fence, not a suggestion', () => {
  it('refuses everything when no password is configured', async () => {
    delete process.env.CONTROL_CENTER_PASSWORD;
    const { res, captured } = makeRes();
    await handler(makeReq({ query: { view: 'status' } }), res);
    expect(captured.status).toBe(503);
    expect(opsRead).not.toHaveBeenCalled();
  });

  it('refuses an unauthenticated read', async () => {
    const { res, captured } = makeRes();
    await handler(makeReq({ query: { view: 'status' } }), res);
    expect(captured.status).toBe(401);
    expect(opsRead).not.toHaveBeenCalled();
  });

  it('refuses a session signed with a different password', async () => {
    const cookie = signedIn();
    process.env.CONTROL_CENTER_PASSWORD = 'the-password-was-changed';
    const { res, captured } = makeRes();
    await handler(makeReq({ query: { view: 'status' }, cookie }), res);
    expect(captured.status).toBe(401);
  });
});

describe('the view allow-list', () => {
  it('rejects a view it does not know', async () => {
    const { res, captured } = makeRes();
    await handler(makeReq({ query: { view: '../../etc/passwd' }, cookie: signedIn() }), res);
    expect(captured.status).toBe(404);
    expect(opsRead).not.toHaveBeenCalled();
  });

  it('accepts every view it advertises', async () => {
    for (const view of VIEWS) {
      const { res, captured } = makeRes();
      await handler(makeReq({ query: { view }, cookie: signedIn() }), res);
      expect(captured.status, view).toBe(200);
    }
  });

  it('names the catalogue and pack views, so store admin is reachable', () => {
    expect(VIEWS).toContain('catalogue');
    expect(VIEWS).toContain('pack');
  });
});

describe('the argument allow-list', () => {
  it('forwards an argument the view accepts', async () => {
    const { res } = makeRes();
    await handler(makeReq({ query: { view: 'run', run_id: 'abc', days: '3' }, cookie: signedIn() }), res);
    expect(opsRead).toHaveBeenCalledWith('run', { run_id: 'abc', days: '3' });
  });

  it('drops an argument the view does not accept', async () => {
    const { res } = makeRes();
    await handler(
      makeReq({ query: { view: 'status', run_id: 'abc', evil: ';rm -rf /' }, cookie: signedIn() }),
      res,
    );
    expect(opsRead).toHaveBeenCalledWith('status', {});
  });

  it('drops an empty argument rather than forwarding a blank', async () => {
    const { res } = makeRes();
    await handler(makeReq({ query: { view: 'pack', id: '' }, cookie: signedIn() }), res);
    expect(opsRead).toHaveBeenCalledWith('pack', {});
  });
});

describe('what comes back', () => {
  it('is only GET', async () => {
    const { res, captured } = makeRes();
    await handler(makeReq({ method: 'POST', query: { view: 'status' }, cookie: signedIn() }), res);
    expect(captured.status).toBe(405);
  });

  it('carries as_of on every read, because every screen must say when it read', async () => {
    for (const view of VIEWS) {
      const { res, captured } = makeRes();
      await handler(makeReq({ query: { view }, cookie: signedIn() }), res);
      const body = captured.body as Record<string, unknown>;
      expect(typeof body.as_of, view).toBe('number');
      expect(typeof body.as_of_iso, view).toBe('string');
    }
  });

  it('never caches', async () => {
    const { res, captured } = makeRes();
    await handler(makeReq({ query: { view: 'status' }, cookie: signedIn() }), res);
    expect(captured.headers['Cache-Control']).toBe('no-store');
  });

  it('says so out loud when the gateway speaks a different contract', async () => {
    opsRead.mockResolvedValue({ envelope: envelope({ contract: 2 }), exitCode: 0, stderr: '' });
    const { res, captured } = makeRes();
    await handler(makeReq({ query: { view: 'status' }, cookie: signedIn() }), res);
    expect(captured.status).toBe(500);
    expect(String((captured.body as { error: string }).error)).toContain('contract 2');
  });

  it("passes the engine's own failure through at 502, reason intact", async () => {
    opsRead.mockResolvedValue({
      envelope: envelope({ ok: false, error: 'the ledger is unreadable', error_kind: 'ReadFailed' }),
      exitCode: 1,
      stderr: '',
    });
    const { res, captured } = makeRes();
    await handler(makeReq({ query: { view: 'spend' }, cookie: signedIn() }), res);
    expect(captured.status).toBe(502);
    expect((captured.body as { error: string }).error).toBe('the ledger is unreadable');
  });

  it('reports an unreachable gateway as an error, never as empty data', async () => {
    opsRead.mockRejectedValue(new Error('could not run python'));
    const { res, captured } = makeRes();
    await handler(makeReq({ query: { view: 'queue' }, cookie: signedIn() }), res);
    expect(captured.status).toBe(500);
    expect((captured.body as { error_kind: string }).error_kind).toBe('GatewayUnreachable');
    expect((captured.body as { data?: unknown }).data).toBeUndefined();
  });
});
