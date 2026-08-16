/**
 * Sign in, sign out, and the fail-closed default.
 *
 * The rule being pinned: an UNCONFIGURED console is locked, not open. That is the opposite of the
 * usual default and it is the whole reason the check exists — a portal that ships open because
 * nobody set a variable is a portal that ships open.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { makeReq, makeRes } from './helpers';

const { default: handler } = await import('@/pages/api/ops/session');
const { COOKIE_NAME, mintSession, sessionValid } = await import('@/lib/auth');

beforeEach(() => {
  process.env.CONTROL_CENTER_PASSWORD = 'correct horse';
});

describe('signing in', () => {
  it('mints a cookie for the right password', async () => {
    const { res, captured } = makeRes();
    handler(makeReq({ method: 'POST', body: { password: 'correct horse' } }), res);
    expect(captured.status).toBe(200);
    const cookie = String(captured.headers['Set-Cookie']);
    expect(cookie).toContain(`${COOKIE_NAME}=`);
    expect(cookie).toContain('HttpOnly');
    expect(cookie).toContain('SameSite=Strict');
  });

  it('refuses the wrong password with the same message as an empty one', async () => {
    const a = makeRes();
    handler(makeReq({ method: 'POST', body: { password: 'wrong' } }), a.res);
    const b = makeRes();
    handler(makeReq({ method: 'POST', body: {} }), b.res);
    expect(a.captured.status).toBe(401);
    expect(b.captured.status).toBe(401);
    expect(a.captured.body).toEqual(b.captured.body);
  });

  it('is locked when no password is configured', async () => {
    delete process.env.CONTROL_CENTER_PASSWORD;
    const { res, captured } = makeRes();
    handler(makeReq({ method: 'POST', body: { password: '' } }), res);
    expect(captured.status).toBe(503);
    expect(captured.headers['Set-Cookie']).toBeUndefined();
  });

  it('reports configured=false so the login page can say why', async () => {
    delete process.env.CONTROL_CENTER_PASSWORD;
    const { res, captured } = makeRes();
    handler(makeReq({ method: 'GET' }), res);
    expect(captured.status).toBe(200);
    expect((captured.body as { configured: boolean }).configured).toBe(false);
  });
});

describe('the token itself', () => {
  it('stops working when the password changes', () => {
    const token = mintSession();
    expect(sessionValid(token)).toBe(true);
    process.env.CONTROL_CENTER_PASSWORD = 'a different password';
    expect(sessionValid(token)).toBe(false);
  });

  it('expires', () => {
    const token = mintSession(Date.now() - 13 * 60 * 60 * 1000);
    expect(sessionValid(token)).toBe(false);
  });

  it('rejects a forged expiry', () => {
    const token = mintSession();
    const [, mac] = token.split('.');
    const forged = `${Math.floor(Date.now() / 1000) + 999_999}.${mac}`;
    expect(sessionValid(forged)).toBe(false);
  });

  it('rejects nonsense without throwing', () => {
    expect(sessionValid('')).toBe(false);
    expect(sessionValid('not-a-token')).toBe(false);
    expect(sessionValid('123.short')).toBe(false);
  });
});

describe('signing out', () => {
  it('clears the cookie', () => {
    const { res, captured } = makeRes();
    handler(makeReq({ method: 'DELETE' }), res);
    expect(captured.status).toBe(200);
    expect(String(captured.headers['Set-Cookie'])).toContain('Max-Age=0');
  });
});
