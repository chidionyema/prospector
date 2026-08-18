/**
 * The console's own black box.
 *
 * WHY THIS EXISTS. On 2026-08-18 every tab in the ops console rendered blank at once. The cause
 * turned out to be an expired session — the reads 401ed and the page bounced to /login — but
 * nothing anywhere recorded that. The only server-side trace was stderr, and `fly logs -a
 * prospector-engine --no-tail` returns exactly 100 lines, which on a generating daemon is about
 * four minutes of history. By the time the founder reported it, the evidence had scrolled away,
 * so the fault was reasoned about instead of read. Founder, that day: "we should log carefully
 * next time this happens".
 *
 * So every refused, failed or unusually slow console request appends one line here, on the same
 * volume as the catalogue, next to `intents.jsonl`. It is an AUDIT TRAIL, not state: nothing
 * reads it to make a decision, so a lost or trimmed line can never change what the console does.
 *
 * It also still writes the line to stderr, so a machine with no readable volume degrades to the
 * behaviour that existed before rather than to silence.
 */
import { appendFileSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";

/** Keep the last N lines. Trimmed at 2N so the rewrite happens once every N appends. */
export const KEEP = 500;

/** Long fields are clipped, not dropped. A stack is evidence; a 200KB stack is a log hose. */
const MAX_FIELD = 2048;

/**
 * Where the log lives. Resolved per call, never at module load: `PROSPECTOR_STORE_DIR` is what
 * pins every other piece of engine state to the one canonical store, and a value captured at
 * import time would follow the code instead of the store.
 *
 * Deliberately self-contained — it does NOT import `repoRoot` from `@/lib/ops`, because the API
 * route tests mock that module and a logger that throws inside a mocked test is a logger that
 * gets deleted.
 */
export function eventsPath(): string {
  const root = process.env.PROSPECTOR_ROOT || `${process.cwd()}/../../..`;
  const dir = process.env.PROSPECTOR_STORE_DIR || path.join(root, "store");
  return path.join(dir, "ops", "console_events.jsonl");
}

export type ConsoleEvent = {
  /** read_refused | read_failed | read_slow | act_failed | client_error | signin_* */
  kind: string;
  view?: string;
  action?: string;
  status?: number;
  took_ms?: number;
  error?: string;
  error_kind?: string;
  who?: string;
  where?: string;
  message?: string;
  detail?: string;
};

function clip(value: unknown): string {
  return typeof value === "string" ? value.slice(0, MAX_FIELD) : "";
}

/**
 * Append one line. NEVER throws: this runs on the failure path of a request that has already
 * gone wrong, and a logger that can turn a 401 into a 500 is worse than no logger.
 */
export function logConsoleEvent(ev: ConsoleEvent): void {
  const now = Date.now();
  const row: Record<string, unknown> = { ts: Math.round(now) / 1000, at: new Date(now).toISOString() };
  for (const [k, v] of Object.entries(ev)) {
    if (v === undefined || v === null) continue;
    row[k] = typeof v === "string" ? clip(v) : v;
  }
  let line = "";
  try {
    line = JSON.stringify(row);
  } catch {
    line = JSON.stringify({ ts: row.ts, at: row.at, kind: "unserialisable" });
  }
  // stderr as well as the file, so `fly logs` still carries it live.
  console.error(`[ops-console event] ${line}`);
  try {
    const p = eventsPath();
    mkdirSync(path.dirname(p), { recursive: true });
    appendFileSync(p, `${line}\n`, "utf8");
    trim(p);
  } catch (err) {
    console.error(
      `[ops-console event] could not persist: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
}

/** Keep the file bounded. Rewrites only once it has grown to twice the keep size. */
function trim(p: string): void {
  const lines = readFileSync(p, "utf8").split("\n").filter((l) => l.trim() !== "");
  if (lines.length <= KEEP * 2) return;
  const tmp = `${p}.tmp`;
  writeFileSync(tmp, `${lines.slice(-KEEP).join("\n")}\n`, "utf8");
  renameSync(tmp, p);
}
