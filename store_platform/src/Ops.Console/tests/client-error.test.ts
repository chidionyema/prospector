/**
 * The route that carries a browser crash back to the server.
 *
 * The rule being pinned: it answers without a session. It is called from a page that has
 * already broken, and the state most likely to break a page is a bad session — a reporter
 * that needed a good one would go silent in exactly the case it exists for.
 */
import { describe, expect, it, vi } from 'vitest';

import { makeReq, makeRes } from './helpers';

const { default: handler } = await import('@/pages/api/ops/client-error');

describe('client error reporting', () => {
  it('accepts a report with no session at all and answers 204', () => {
    const { res, captured } = makeRes();
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    handler(
      makeReq({ method: 'POST', body: { where: 'render', message: 'TypeError: x of undefined' } }),
      res,
    );
    expect(captured.status).toBe(204);
    expect(spy.mock.calls.flat().join('\n')).toContain('TypeError: x of undefined');
    spy.mockRestore();
  });

  it('refuses anything but POST, so it cannot be triggered by a link', () => {
    const { res, captured } = makeRes();
    handler(makeReq({ method: 'GET' }), res);
    expect(captured.status).toBe(405);
  });

  it('clips a runaway stack instead of writing it all to the machine log', () => {
    const { res, captured } = makeRes();
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    handler(makeReq({ method: 'POST', body: { message: 'x'.repeat(50_000) } }), res);
    expect(captured.status).toBe(204);
    const logged = spy.mock.calls.flat().join('');
    expect(logged.length).toBeLessThan(10_000);
    spy.mockRestore();
  });
});
