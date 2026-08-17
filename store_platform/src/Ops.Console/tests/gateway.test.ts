/**
 * The gateway subprocess: which ceiling each verb gets, and what the timeout kills.
 *
 * These drive the REAL `runPython` against a fake interpreter, because the two facts under test
 * are the plumbing itself. Mocking `spawn` would prove only that the mock was called.
 *
 * Why a fake interpreter and not `scripts/store_audit.py`: measured 2026-08-16, that tool took
 * 239.9s cold and 49s warm on the same machine. A live run that happens to come in under two
 * minutes cannot tell a fixed ceiling from a lucky one. The fake is slow on demand.
 */
import { chmodSync, existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let dir: string;

/** Write an executable stand-in for `.venv/bin/python` and point the module at it. */
function fakeInterpreter(body: string): string {
  const path = join(dir, 'fake-python');
  writeFileSync(path, `#!/bin/bash\n${body}\n`);
  chmodSync(path, 0o755);
  return path;
}

const ENVELOPE =
  '{"ok":true,"contract":1,"as_of":1,"as_of_iso":"x","took_ms":1,"data":{},' +
  '"error":null,"error_kind":null}';

async function loadOps() {
  vi.resetModules();
  return import('@/lib/ops');
}

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'ops-gateway-'));
  process.env.PROSPECTOR_ROOT = dir;
  delete process.env.OPS_TIMEOUT_MS;
  delete process.env.OPS_ACT_TIMEOUT_MS;
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe('a write gets the act ceiling, not the read one', () => {
  it('finishes a call that outlives the read ceiling', async () => {
    // The regression this exists for: one ceiling of 120s for every verb killed
    // `scripts/store_audit.py` (239.9s) mid-run and blamed the gateway.
    process.env.PROSPECTOR_PYTHON = fakeInterpreter(`sleep 2\necho '${ENVELOPE}'`);
    process.env.OPS_TIMEOUT_MS = '500';
    process.env.OPS_ACT_TIMEOUT_MS = '20000';
    const { opsAct } = await loadOps();
    const { envelope } = await opsAct('tools.run', { id: 'x' }, 'token');
    expect(envelope.ok).toBe(true);
  }, 30_000);

  it('still reports a write that outlives its own ceiling as a timeout', async () => {
    process.env.PROSPECTOR_PYTHON = fakeInterpreter(`sleep 10\necho '${ENVELOPE}'`);
    process.env.OPS_ACT_TIMEOUT_MS = '600';
    const { opsAct } = await loadOps();
    await expect(opsAct('tools.run', { id: 'x' }, 'token')).rejects.toThrow(/within 600ms/);
  }, 30_000);
});

describe('a read keeps the short ceiling, because a panel is waiting on it', () => {
  it('gives up on a slow read rather than holding the panel', async () => {
    process.env.PROSPECTOR_PYTHON = fakeInterpreter(`sleep 10\necho '${ENVELOPE}'`);
    process.env.OPS_TIMEOUT_MS = '500';
    process.env.OPS_ACT_TIMEOUT_MS = '20000';
    const { opsRead } = await loadOps();
    await expect(opsRead('status')).rejects.toThrow(/within 500ms/);
  }, 30_000);
});

describe('the timeout kills the tool, not just the gateway', () => {
  it('leaves nothing running that can still write after the console gave up', async () => {
    // The gateway spawns the tool. Killing only the gateway left the tool writing to store/ with
    // no receipt, no exit code and no undo id. The marker file IS that orphaned write.
    const marker = join(dir, 'the-orphan-wrote-this');
    process.env.PROSPECTOR_PYTHON = fakeInterpreter(
      `( sleep 3; touch "${marker}" ) &\nsleep 30`,
    );
    process.env.OPS_ACT_TIMEOUT_MS = '700';
    const { opsAct } = await loadOps();
    await expect(opsAct('tools.run', { id: 'x' }, 'token')).rejects.toThrow(/within 700ms/);

    await new Promise((r) => setTimeout(r, 5000));
    expect(existsSync(marker)).toBe(false);
  }, 30_000);
});
