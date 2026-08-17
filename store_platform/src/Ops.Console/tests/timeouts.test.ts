/**
 * The two gateway ceilings, and the one that must not drift.
 *
 * The console kills the gateway subprocess itself, so its ceiling is the real limit on a tool run
 * no matter what Python allows. Until 2026-08-16 there was one ceiling of 120s for every call and
 * the launchd plist raised it with `OPS_TIMEOUT_MS`; a console started any other way killed
 * `scripts/store_audit.py` (over two minutes) at two minutes and blamed the gateway.
 *
 * This test reads the Python constant off disk on purpose. A number copied into a comment goes
 * stale silently; a number read from the file it must clear fails the moment someone raises it.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { beforeEach, describe, expect, it, vi } from 'vitest';

const CONSOLE_API = join(__dirname, '..', '..', '..', '..', 'prospector', 'ops', 'console_api.py');

function pythonToolTimeoutSeconds(): number {
  const src = readFileSync(CONSOLE_API, 'utf8');
  const shelf = /^_SHELF_TIMEOUT_S\s*=\s*(\d+)/m.exec(src);
  if (!shelf) throw new Error('console_api.py no longer declares _SHELF_TIMEOUT_S as a literal');
  if (!/^_TOOL_TIMEOUT_S\s*=\s*_SHELF_TIMEOUT_S\b/m.test(src)) {
    throw new Error(
      '_TOOL_TIMEOUT_S is no longer _SHELF_TIMEOUT_S — read the new value here before trusting it',
    );
  }
  return Number(shelf[1]);
}

async function loadOps() {
  vi.resetModules();
  return import('@/lib/ops');
}

beforeEach(() => {
  delete process.env.OPS_TIMEOUT_MS;
  delete process.env.OPS_ACT_TIMEOUT_MS;
});

describe('the act ceiling clears the tool ceiling without any environment', () => {
  it('outlives the longest run Python will allow', async () => {
    const { OPS_ACT_TIMEOUT_MS } = await loadOps();
    expect(OPS_ACT_TIMEOUT_MS).toBeGreaterThan(pythonToolTimeoutSeconds() * 1000);
  });

  it('does not need OPS_TIMEOUT_MS to be set, because most consoles are not launchd jobs', async () => {
    const { OPS_ACT_TIMEOUT_MS, OPS_READ_TIMEOUT_MS } = await loadOps();
    expect(OPS_ACT_TIMEOUT_MS).toBeGreaterThan(OPS_READ_TIMEOUT_MS);
  });

  it('is still overridable', async () => {
    process.env.OPS_ACT_TIMEOUT_MS = '90000';
    const { OPS_ACT_TIMEOUT_MS } = await loadOps();
    expect(OPS_ACT_TIMEOUT_MS).toBe(90_000);
  });
});

describe('the read ceiling stays short, because a panel is waiting on it', () => {
  it('defaults to two minutes', async () => {
    const { OPS_READ_TIMEOUT_MS } = await loadOps();
    expect(OPS_READ_TIMEOUT_MS).toBe(120_000);
  });

  it('takes OPS_TIMEOUT_MS, the name the plist already uses', async () => {
    process.env.OPS_TIMEOUT_MS = '30000';
    const { OPS_READ_TIMEOUT_MS } = await loadOps();
    expect(OPS_READ_TIMEOUT_MS).toBe(30_000);
  });
});
