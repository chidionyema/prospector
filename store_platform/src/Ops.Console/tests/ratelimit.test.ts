/**
 * The sign-in limiter. It only started mattering on 2026-08-18, when the console stopped being
 * reachable over a tunnel from one laptop and started answering on the open internet. Before
 * that the network was the fence; now the password is, and a password with unlimited guesses is
 * not a fence.
 */
import { afterEach, describe, expect, it } from 'vitest';

import { _reset, clearFailures, clientKey, isLocked, recordFailure } from '@/lib/ratelimit';

afterEach(() => _reset());

describe('clientKey', () => {
  it('prefers the address Fly reports over the socket', () => {
    expect(clientKey({ 'fly-client-ip': '203.0.113.7', 'x-forwarded-for': '198.51.100.1' })).toBe(
      '203.0.113.7',
    );
  });

  it('falls back to the first hop of x-forwarded-for', () => {
    expect(clientKey({ 'x-forwarded-for': '198.51.100.1, 10.0.0.1' })).toBe('198.51.100.1');
  });

  it('never throws when there is no address at all', () => {
    expect(clientKey({})).toBe('unknown');
  });
});

describe('the five-strike window', () => {
  it('allows four wrong answers and locks on the fifth', () => {
    for (let i = 0; i < 4; i++) {
      recordFailure('a');
      expect(isLocked('a')).toBe(false);
    }
    recordFailure('a');
    expect(isLocked('a')).toBe(true);
  });

  it('locks one address without touching another', () => {
    for (let i = 0; i < 5; i++) recordFailure('a');
    expect(isLocked('a')).toBe(true);
    expect(isLocked('b')).toBe(false);
  });

  it('forgets failures older than the window', () => {
    const t0 = 1_000_000_000_000;
    for (let i = 0; i < 5; i++) recordFailure('a', t0);
    expect(isLocked('a', t0)).toBe(true);
    // Fifteen minutes and one second later the whole window has rolled off.
    expect(isLocked('a', t0 + 15 * 60 * 1000 + 1000)).toBe(false);
  });

  it('clears the address on a correct password, so a fumbled login costs nothing later', () => {
    for (let i = 0; i < 4; i++) recordFailure('a');
    clearFailures('a');
    for (let i = 0; i < 4; i++) recordFailure('a');
    expect(isLocked('a')).toBe(false);
  });
});
