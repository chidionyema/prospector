import { describe, it, expect } from 'vitest';

import config from '../../../vitest.config';

/**
 * The worker cap exists so that N agents running suites in parallel worktrees cannot each claim
 * a whole 12-core box. It shipped once as `test.poolOptions.forks.maxForks`, which vitest 4
 * removed — and an unknown key in this config is IGNORED at runtime, not rejected. The suite
 * stayed green while the cap silently capped nothing:
 *
 *   main's version   -> createVitest(...).config.maxWorkers === undefined
 *   this version     -> 4 on a 12-core machine
 *
 * `tsc --noEmit` rejects the unknown key, and this asserts the other half: that whatever key is
 * used still resolves to an actual number. A cap that is only a comment is worse than no cap,
 * because it stops anyone looking.
 */

describe('vitest worker cap', () => {
  it('sets a numeric maxWorkers, not a key vitest will ignore', () => {
    const test = (config as { test?: Record<string, unknown> }).test ?? {};

    expect(typeof test.maxWorkers, 'maxWorkers must be a number vitest actually reads').toBe('number');
    expect(test.maxWorkers as number).toBeGreaterThanOrEqual(1);

    // Removed in vitest 4. If it reappears, the cap has been moved back under a dead key.
    expect(test.poolOptions, 'poolOptions was removed in vitest 4 and is ignored').toBeUndefined();
  });

  it('caps well below the core count so parallel agents cannot each take the machine', () => {
    const { maxWorkers } = (config as { test: { maxWorkers: number } }).test;
    expect(maxWorkers).toBeLessThanOrEqual(4);
  });
});
