/**
 * The two-step write, as one component.
 *
 * Every write in this console goes through here: preview, read what would change, then apply
 * quoting the token the preview handed back. There is no one-step path in the UI, and — more
 * importantly — there is no one-step path in the gateway either (`console_api.py:1431`), so a
 * page that forgot to use this component would be refused rather than silently allowed.
 *
 * The preview is rendered by the caller, because "what will change" looks completely different
 * for a pause, a config edit and a delisting. What is common is the SHAPE of the interaction and
 * the refusal handling, and that is what lives here.
 */
import React, { useState } from 'react';

import { Button, Note, Problem } from '@/components/ui';
import type { Envelope } from '@/lib/contract';
import { applyAction, confirmTokenOf, previewAction } from '@/lib/contract';

type Stage = 'idle' | 'previewing' | 'confirm' | 'applying' | 'done';

/** snake_case_key -> "Snake case key", so a receipt reads as English rather than as a payload. */
function humanise(key: string): string {
  const words = key.replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * A receipt's scalar fields as label/value rows.
 *
 * Scalars only, deliberately. Nested objects and arrays are the part of a receipt that is
 * genuinely a payload -- rendering them here would rebuild the wall of JSON this replaced. They
 * are still in `Raw receipt`, one click away.
 */
function ReceiptSummary({ receipt }: { receipt: Record<string, unknown> }) {
  const rows = Object.entries(receipt).filter(
    ([k, v]) =>
      k !== 'action' &&
      (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'),
  );
  if (rows.length === 0) return null;
  return (
    <dl className="m-0 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-[12.5px]">
      {rows.map(([k, v]) => (
        <React.Fragment key={k}>
          <dt className="text-muted">{humanise(k)}</dt>
          <dd className="wrap-any m-0 font-mono">{String(v)}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

export default function Confirm({
  action,
  payload,
  label,
  kind = 'plain',
  disabled,
  renderPreview,
  onApplied,
  renderReceipt,
  applyLabel = 'Yes, do it',
  requireAck,
}: {
  action: string;
  /** Built fresh on each click by the caller, so it always reflects the current form state. */
  payload: () => Record<string, unknown>;
  label: string;
  kind?: 'plain' | 'primary' | 'danger';
  disabled?: boolean;
  renderPreview: (data: Record<string, unknown>) => React.ReactNode;
  onApplied?: (receipt: Record<string, unknown>) => void;
  /**
   * The result, rendered as the thing the operator actually wanted, not as a field in a blob.
   *
   * Why this exists. Every write in this console ended by dumping `JSON.stringify(receipt)` on
   * screen, on all 11 pages that use this component. For most writes that is merely ugly. For
   * `share.create` it hid the deliverable: the founder minted a link and reported "it mints a
   * link but I don't see the link ... there is a path output but the whole thing isn't user
   * friendly" (2026-08-21). The path WAS there, as `"path": "/s/..."` inside the blob.
   *
   * Callers with a first-class result render it here. Everyone else gets a readable summary,
   * and the raw JSON stays one click away rather than being deleted -- it is the audit
   * affordance, and demoting it is not the same as losing it.
   */
  renderReceipt?: (receipt: Record<string, unknown>) => React.ReactNode;
  applyLabel?: string;
  /**
   * A second, explicit acknowledgement for the cases where the preview reveals the write is
   * destructive. Return the sentence the operator must tick; return null and the apply button
   * behaves normally. It exists because "preview then apply" is one gate for every write, and
   * resending an already-delivered link erases the record that the first email went out.
   */
  requireAck?: (preview: Record<string, unknown>) => string | null;
}) {
  const [stage, setStage] = useState<Stage>('idle');
  const [acked, setAcked] = useState(false);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [sent, setSent] = useState<Record<string, unknown> | null>(null);
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setAcked(false);
    setStage('idle');
    setPreview(null);
    setToken(null);
    setSent(null);
    setReceipt(null);
    setError(null);
  }

  async function doPreview() {
    setStage('previewing');
    setError(null);
    const body = payload();
    try {
      const { envelope } = (await previewAction(action, body)) as {
        envelope: Envelope<Record<string, unknown>>;
      };
      if (!envelope.ok || !envelope.data) {
        setError(envelope.error || 'the engine refused to preview this and gave no reason');
        setStage('idle');
        return;
      }
      setPreview(envelope.data);
      setToken(confirmTokenOf(envelope.data));
      // The token is bound to the payload it was minted for. Applying with a payload the
      // operator changed after previewing would be a different write than the one they read, so
      // the exact bytes that were previewed are what gets sent.
      setSent(body);
      setStage('confirm');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage('idle');
    }
  }

  async function doApply() {
    if (!token || !sent) return;
    setStage('applying');
    setError(null);
    try {
      const { envelope } = (await applyAction(action, sent, token)) as {
        envelope: Envelope<Record<string, unknown>>;
      };
      if (!envelope.ok) {
        setError(
          envelope.error_kind === 'ConfirmationRequired'
            ? `${envelope.error} — the confirmation expired (they last 10 minutes). Preview again.`
            : envelope.error || 'the engine refused and gave no reason',
        );
        setStage('confirm');
        return;
      }
      setReceipt(envelope.data ?? {});
      setStage('done');
      onApplied?.(envelope.data ?? {});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage('confirm');
    }
  }

  if (stage === 'done') {
    const changed = receipt?.changed;
    return (
      <div className="flex flex-col gap-2">
        <div className="rounded-sm border border-ok/40 bg-ok-bg px-3 py-2 text-[13px] text-ok-strong">
          {changed === false
            ? 'Written — nothing actually changed; it was already in that state.'
            : 'Done. A receipt was written to the audit log.'}
        </div>
        {renderReceipt && receipt ? renderReceipt(receipt) : <ReceiptSummary receipt={receipt ?? {}} />}
        <details className="text-[12px] text-muted">
          <summary className="cursor-pointer select-none">Raw receipt</summary>
          <div className="scroll-x mt-1">
            <pre className="font-mono text-[11px] text-muted">
              {JSON.stringify(receipt, null, 1)}
            </pre>
          </div>
        </details>
        <div>
          <Button onClick={reset}>Close</Button>
        </div>
      </div>
    );
  }

  if (stage === 'confirm' || stage === 'applying') {
    const ack = preview && requireAck ? requireAck(preview) : null;
    return (
      <div className="flex flex-col gap-3 rounded-sm border border-warn/50 bg-warn-bg px-3 py-3">
        <div className="text-[13px] font-[560] text-warn-strong">
          Read this, then confirm. Nothing has been written yet.
        </div>
        <div className="text-[13px] text-text">{preview ? renderPreview(preview) : null}</div>
        {ack ? (
          <label className="tap flex items-start gap-2 rounded-sm border border-bad/50 bg-bad-bg px-3 py-2 text-[13px] text-bad-strong">
            <input
              type="checkbox"
              checked={acked}
              onChange={(e) => setAcked(e.target.checked)}
              className="mt-1"
            />
            <span className="wrap-any">{ack}</span>
          </label>
        ) : null}
        {error ? <Problem>{error}</Problem> : null}
        <div className="flex flex-wrap gap-2">
          <Button
            kind={kind === 'plain' ? 'primary' : kind}
            onClick={doApply}
            disabled={stage === 'applying' || !token || (ack !== null && !acked)}
          >
            {stage === 'applying' ? 'writing…' : applyLabel}
          </Button>
          <Button onClick={reset} disabled={stage === 'applying'}>
            Cancel
          </Button>
        </div>
        {!token ? (
          <Note>
            The preview came back without a confirmation token, so this cannot be applied. That is
            the gateway refusing, not a UI bug — read the preview above for the reason.
          </Note>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button kind={kind} onClick={doPreview} disabled={disabled || stage === 'previewing'}>
          {stage === 'previewing' ? 'checking…' : label}
        </Button>
      </div>
      {error ? <Problem>{error}</Problem> : null}
    </div>
  );
}
