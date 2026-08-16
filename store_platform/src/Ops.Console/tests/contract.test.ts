/**
 * The confirmation token's NAME.
 *
 * This test exists because it was got wrong. The client read `data.confirm_token`; the gateway
 * emits `data.confirm` (`console_api.py:1425`). The console previewed, found no token, and could
 * never apply anything — a write path that fails silently on a spelling difference.
 */
import { describe, expect, it } from 'vitest';

import { confirmTokenOf } from '@/lib/contract';

describe('confirmTokenOf', () => {
  it('reads the field the gateway actually emits', () => {
    expect(confirmTokenOf({ confirm: 'tok-1', confirm_expires_in_s: 600 })).toBe('tok-1');
  });

  it('returns null rather than a plausible-looking empty string', () => {
    expect(confirmTokenOf({})).toBeNull();
    expect(confirmTokenOf(null)).toBeNull();
    expect(confirmTokenOf({ confirm_token: 'wrong-field' })).toBeNull();
  });
});
