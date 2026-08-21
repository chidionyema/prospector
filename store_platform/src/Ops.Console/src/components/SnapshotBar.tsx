/**
 * How old this page's answer is, and the button that makes it current.
 *
 * Three views in this console ask other people's services rather than the local disk -- Fly for
 * app and machine state, GitHub for runners and workflow runs, a git fetch per checkout, an HTTP
 * probe per deployable. Measured 2026-08-21, against a median of 0.83s for the other 35 views:
 *
 *     automations   10.16s
 *     deploys       12.45s
 *     processes    141.8s   -- past OPS_READ_TIMEOUT_MS, so it could never load at all
 *
 * They are served from a snapshot now (`prospector/ops/slow_read.py`). This component is the
 * other half of that bargain and it is not decoration: a cached estate audit presented as current
 * is worse than the slow page it replaced, because somebody acts on it. So the age is on the page,
 * in words, above the data it describes.
 */
import Confirm from '@/components/Confirm';
import { Card, Note, Pill } from '@/components/ui';

export type Snapshot = {
  have_snapshot: boolean;
  captured_at_iso: string | null;
  age_s: number | null;
  took_s: number | null;
  stale: boolean;
  stale_after_s: number;
  refreshing: boolean;
  refresh_started?: boolean;
};

/** Seconds as the coarsest unit that is still honest. "41 minutes ago" beats "2481 seconds ago". */
export function ago(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'never';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  const h = Math.floor(s / 3600);
  return h < 48 ? `${h}h ${Math.round((s % 3600) / 60)}m ago` : `${Math.floor(h / 24)} days ago`;
}

export default function SnapshotBar({
  view,
  snapshot,
  what,
  onRefreshed,
}: {
  /** The key in `slow_read.PRODUCERS`. */
  view: string;
  snapshot?: Snapshot;
  /** What was measured, in the page's own words: "the estate audit", "every automation". */
  what: string;
  onRefreshed?: () => void;
}) {
  const have = Boolean(snapshot?.have_snapshot);
  const stale = snapshot?.stale ?? true;
  const busy = Boolean(snapshot?.refreshing);
  const tone = !have ? 'warn' : stale ? 'warn' : 'ok';

  return (
    <Card
      title="How fresh this is"
      tone={tone}
      right={
        <Pill tone={tone}>
          {!have ? 'no measurement yet' : stale ? `stale — ${ago(snapshot?.age_s)}` : ago(snapshot?.age_s)}
        </Pill>
      }
    >
      {!have ? (
        <Note>
          Nothing has been measured here yet.{' '}
          {busy
            ? `A first run of ${what} has just started in the background. It takes a couple of minutes; reload this page when it finishes.`
            : `Press Re-measure to run ${what} now.`}
        </Note>
      ) : (
        <Note>
          {what}, measured {ago(snapshot?.age_s)}
          {snapshot?.took_s ? ` (it took ${snapshot.took_s}s)` : ''}
          {snapshot?.captured_at_iso ? ` — ${snapshot.captured_at_iso}` : ''}.{' '}
          {busy
            ? 'A fresh run is going on right now; reload in a minute to see it.'
            : stale
              ? `Older than ${Math.round((snapshot?.stale_after_s ?? 0) / 60)} minutes, so a fresh run has been started in the background.`
              : `It re-measures itself once it is over ${Math.round((snapshot?.stale_after_s ?? 0) / 60)} minutes old.`}
        </Note>
      )}
      <div className="mt-3">
        <Confirm
          action="snapshot.refresh"
          payload={() => ({ view })}
          label="Re-measure now"
          kind="plain"
          disabled={busy}
          onApplied={() => onRefreshed?.()}
          applyLabel="Yes, measure it now"
          renderPreview={(d) => (
            <Note>
              {String(d.effect ?? '')} {String(d.cost ?? '')}
            </Note>
          )}
        />
      </div>
    </Card>
  );
}
