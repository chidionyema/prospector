/**
 * Send a browser-side crash to the server so it survives the browser.
 *
 * The console runs on Fly. When a page throws there, the only record is one line in one
 * browser's devtools, on a phone, with nobody looking. `fly logs` is where every other
 * failure in this system already shows up, so client failures go there too.
 *
 * Fire and forget on purpose: this is called from an error path, so it must never throw,
 * never await anything the caller depends on, and never turn one broken page into two.
 */
export function reportClientError(where: string, error: unknown, componentStack?: string): void {
  try {
    const e = error as { name?: string; message?: string; stack?: string } | null;
    const message = e?.message ? `${e.name ?? 'Error'}: ${e.message}` : String(error);
    const body = JSON.stringify({
      where,
      message,
      stack: e?.stack ?? '',
      componentStack: componentStack ?? '',
    });
    // `keepalive` so the report still leaves if the throw is followed by a navigation.
    void fetch('/api/ops/client-error', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // Reporting a failure must not be able to cause one.
  }
}
