/**
 * The one place this app talks to the engine.
 *
 * Everything goes through `prospector.ops.console_api`, which imports the six `prospector/ops/*`
 * read models. NOTHING in TypeScript computes an engine number. That is not style: when a
 * dashboard and a rail disagree about the backlog, it is because someone counted twice, and
 * `run.drain_survey` is the single definition of "waiting rows" that both the drain and the
 * generation brake already use.
 *
 * WHY A SUBPROCESS AND NOT AN HTTP SERVICE. The engine has no server. Adding one would be a new
 * always-on process to supervise, a port to fence, and a second thing that can be down. A spawn
 * per request costs ~350ms of Python import (measured below) and cannot be up while the engine
 * is down, because it IS the engine's code.
 */
import { spawn } from 'node:child_process';

/**
 * The repo the console reads. MUST be the founder's main checkout in production: `store/` holds
 * the heartbeats, the queue database and the ledger, and a git worktree's `store/` is a
 * copy-on-write clone that diverges the moment either tree writes. Pointing this at a worktree
 * makes every panel read a fossil and report the engine dead.
 */
export function repoRoot(): string {
  return process.env.PROSPECTOR_ROOT || `${process.cwd()}/../../..`;
}

/**
 * The interpreter that runs the gateway. It comes from the environment and there is deliberately
 * NO hardcoded fallback path in this file.
 *
 * That is a build constraint, not a preference. Turbopack constant-folds `process.cwd()` and any
 * literal joined to it, turns the result into a file dependency, and resolves it at BUILD time.
 * A path ending `.venv/bin/python` is a symlink out of the project root in every git worktree, so
 * Turbopack panicked with "Symlink … is invalid, it points out of the filesystem root" and
 * `next build` failed outright. Measured 2026-08-16: `path.join(repoRoot(), '.venv/bin/python')`
 * failed as a DirAssetReference, the template-string version failed as a FileSourceReference, and
 * removing the literal builds. The default now lives in `package.json` (`npm run dev` / `npm
 * start` compute it from the repo root) and in the launchd plist
 * `~/Library/LaunchAgents/com.prospector.ops-console.plist`, where no bundler reads it.
 */
export function pythonBin(): string {
  const bin = process.env.PROSPECTOR_PYTHON;
  if (!bin) {
    throw new Error(
      'PROSPECTOR_PYTHON is not set, so there is no interpreter to run the engine gateway with. ' +
        'Start it with `npm run dev` or `npm start`, which point it at the repo\'s .venv, or ' +
        'through the launchd job com.prospector.ops-console, whose plist names the interpreter.',
    );
  }
  return bin;
}

/**
 * TWO CEILINGS, BECAUSE A READ AND A TOOL RUN ARE DIFFERENT JOBS.
 *
 * A read is a panel waiting on a number. `read metrics` scans the diagnostics window and is the
 * slow one; everything else measured under 400ms. A request that outlives this is reported as a
 * TIMEOUT, never as an empty result — an outage is the end of a measurement, not a datum, and a
 * swallowed one returns `[]` and reads as "nothing to show".
 */
export const OPS_READ_TIMEOUT_MS = Number(process.env.OPS_TIMEOUT_MS || 120_000);

/**
 * A write may spawn a batch tool, and those run for minutes. `console_api._TOOL_TIMEOUT_S` is
 * 1800s, so anything lower here kills the gateway while the tool it started is still working.
 *
 * That was live until 2026-08-16: the default was 120s for every call, the launchd plist papered
 * over it with `OPS_TIMEOUT_MS=1900000`, and a console started any other way — `npm run dev`,
 * `npm start`, a plist edited later — killed `scripts/store_audit.py` at two minutes and reported
 * a gateway timeout. The env var is still accepted, but the DEFAULT now clears the Python ceiling
 * on its own, so no console depends on an environment it was not given.
 * `tests/timeouts.test.ts` reads the Python constant and fails if this drops below it.
 */
export const OPS_ACT_TIMEOUT_MS = Number(process.env.OPS_ACT_TIMEOUT_MS || 1_860_000);

export type OpsEnvelope<T = unknown> = {
  ok: boolean;
  contract: number;
  view?: string;
  action?: string;
  verb?: string;
  as_of: number;
  as_of_iso: string;
  took_ms: number;
  data: T;
  error: string | null;
  error_kind: string | null;
};

export type OpsResult<T = unknown> = {
  envelope: OpsEnvelope<T>;
  exitCode: number;
  stderr: string;
};

/** The contract version this app was written against. `console_api.CONTRACT_VERSION`. */
export const EXPECTED_CONTRACT = 1;

function runPython(
  args: string[],
  timeoutMs: number,
): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonBin(), ['-m', 'prospector.ops.console_api', ...args], {
      cwd: repoRoot(),
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
      // Its own process group, so the timeout below can kill the tool the gateway spawned and not
      // just the gateway. Killing the parent alone leaves the tool running, writing to `store/`
      // with no receipt and no undo id — a timeout that abandons a live write is worse than one
      // that waits.
      detached: true,
    });

    let stdout = '';
    let stderr = '';
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      // SIGKILL, not SIGTERM: a wedged child holding a pipe is the hang this timeout exists for,
      // and a polite signal it may ignore turns a timeout into a leak. The negative pid kills the
      // whole group — see `detached` above.
      try {
        if (child.pid) process.kill(-child.pid, 'SIGKILL');
      } catch {
        child.kill('SIGKILL'); // the group is already gone, or this platform refused it
      }
      reject(
        new Error(`the engine gateway did not answer within ${timeoutMs}ms (${args.join(' ')})`),
      );
    }, timeoutMs);

    child.stdout.on('data', (c) => {
      stdout += c;
    });
    child.stderr.on('data', (c) => {
      stderr += c;
    });
    child.on('error', (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(new Error(`could not run ${pythonBin()}: ${err.message}`));
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code: code ?? -1, stdout, stderr });
    });
  });
}

function parse<T>(
  raw: { code: number; stdout: string; stderr: string },
  label: string,
): OpsResult<T> {
  let envelope: OpsEnvelope<T>;
  try {
    envelope = JSON.parse(raw.stdout);
  } catch {
    // A parse failure means the gateway printed something other than its document. Report the
    // real output rather than "unknown error" — the last 400 characters are almost always the
    // Python traceback that explains it.
    throw new Error(
      `the engine gateway did not return JSON for ${label} (exit ${raw.code}). ` +
        `stdout: ${raw.stdout.slice(-400) || '(empty)'} stderr: ${raw.stderr.slice(-400) || '(empty)'}`,
    );
  }
  return { envelope, exitCode: raw.code, stderr: raw.stderr };
}

/** Read one view. Never writes: the verb is the fence, and `read` has no write path behind it. */
export async function opsRead<T = unknown>(
  view: string,
  args: Record<string, string | number | undefined> = {},
): Promise<OpsResult<T>> {
  const argv = ['read', view];
  for (const [k, v] of Object.entries(args)) {
    if (v !== undefined && v !== null && v !== '') argv.push('--arg', `${k}=${v}`);
  }
  return parse<T>(await runPython(argv, OPS_READ_TIMEOUT_MS), `read ${view}`);
}

/**
 * Describe a write without performing it. Returns the change plus a confirmation token.
 *
 * The token binds the ACTION and its ARGUMENTS, so a token issued for "pause the consumer"
 * cannot confirm "pause everything" — confirming a different action than the one shown is
 * exactly what a confirmation step exists to catch.
 */
export async function opsPreview<T = unknown>(
  action: string,
  payload: Record<string, unknown>,
): Promise<OpsResult<T>> {
  // A preview only DESCRIBES the write, so it runs on the read ceiling. It never spawns the tool.
  return parse<T>(
    await runPython(
      ['act', action, '--payload', JSON.stringify(payload), '--preview'],
      OPS_READ_TIMEOUT_MS,
    ),
    `preview ${action}`,
  );
}

/**
 * Perform a write. The token check happens in PYTHON, not here.
 *
 * A fence in the keyboard is a fence a second caller walks around. Every caller — this app, the
 * CLI, the Telegram surface — lands in the same `console_api.dispatch`, so the check cannot be
 * skipped by reaching the engine a different way.
 */
export async function opsAct<T = unknown>(
  action: string,
  payload: Record<string, unknown>,
  confirm: string,
): Promise<OpsResult<T>> {
  return parse<T>(
    await runPython(
      ['act', action, '--payload', JSON.stringify(payload), '--confirm', confirm],
      OPS_ACT_TIMEOUT_MS,
    ),
    `act ${action}`,
  );
}
