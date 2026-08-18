/**
 * The one write the shop screens have: put a delivery back in front of the drain.
 *
 * It sends NOTHING itself. The delivery drain stays the only sender, and the preview says so, so
 * nobody reads this button as "email the buyer now" and presses it three times.
 *
 * THERE IS ONE OUTCOME, `requeued`. A second one, `duplicated`, was designed and then refuted by
 * the schema: `PendingDeliveries.EntitlementId` is UNIQUE, which is what makes a duplicate webhook
 * idempotent, so a resend cannot queue a second row beside the first.
 *
 * What splits the two cases is `previousSentAt`. When it is null the row never went out and a
 * requeue is harmless. When it carries a timestamp, that timestamp is DESTROYED by the resend —
 * clearing `SentAt` is the only legal way to put the row back in the queue — so the record that
 * the first email went out is gone and the buyer receives a second one. That case gets its own
 * acknowledgement before the apply button will work; it is not a plain button.
 *
 * A refusal is not a success with a sad face. The store answers 409 when the entitlement is
 * revoked (refunded or disputed), and the gateway returns that as a receipt with `applied: false`.
 * That renders as a loud failure here, because `Confirm`'s own panel would otherwise say "Done".
 *
 * The id is the DELIVERY ROW id, not the order id. The gateway rejects a non-numeric one.
 */
import { useState } from 'react';

import Confirm from '@/components/Confirm';
import { Note, Pill, Problem, Row } from '@/components/ui';
import { resendWords } from '@/lib/shop';
import { ABSENT } from '@/lib/time';

function text(v: unknown): string {
  if (v === null || v === undefined || v === '') return ABSENT;
  return String(v);
}

/**
 * Reads one field off a receipt whichever shape it arrives in: the gateway's own keys are snake
 * case, the store's body is camel case, and the body may sit under `response`. Guessing one and
 * rendering blank for the other is how a destroyed timestamp would go unmentioned.
 */
function field(bag: Record<string, unknown> | null, ...keys: string[]): unknown {
  if (!bag) return null;
  const nested = bag.response;
  const bags: Record<string, unknown>[] = [bag];
  if (nested && typeof nested === 'object') bags.push(nested as Record<string, unknown>);
  for (const b of bags) {
    for (const k of keys) {
      const v = b[k];
      if (v !== undefined && v !== null && v !== '') return v;
    }
  }
  return null;
}

/** Whether the preview says this link has already reached the buyer once. */
function alreadySent(p: Record<string, unknown>): boolean {
  if (field(p, 'previous_sent_at', 'previousSentAt', 'sent_at', 'sentAt')) return true;
  if (String(p.state ?? '').toLowerCase() === 'sent') return true;
  return /already sent/i.test(String(p.effect ?? ''));
}

export default function ResendDelivery({
  deliveryId,
  onDone,
}: {
  deliveryId: string | number;
  onDone?: () => void;
}) {
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null);

  const applied = receipt ? receipt.applied !== false : null;
  const action = receipt
    ? ((field(receipt, 'action', 'outcome') as string | null) ?? null)
    : null;
  const previousSentAt = receipt
    ? ((field(receipt, 'previousSentAt', 'previous_sent_at') as string | null) ?? null)
    : null;
  const status = receipt ? Number(receipt.status) : null;

  return (
    <div className="mt-3">
      <Confirm
        action="deliveries.resend"
        kind="primary"
        label="Send this link again"
        applyLabel="Yes, put it back in the queue"
        payload={() => ({ id: deliveryId })}
        onApplied={(r) => {
          setReceipt(r);
          onDone?.();
        }}
        requireAck={(p) =>
          alreadySent(p)
            ? 'This link was already sent. I understand the buyer will get a second email, and the record of the first send will be erased.'
            : null
        }
        renderPreview={(p) => (
          <div className="text-[13px]">
            <Row label="What will happen">
              <Pill tone={alreadySent(p) ? 'warn' : 'ok'}>{text(p.will)}</Pill>
            </Row>
            <Row label="Effect">
              <span className="wrap-any">{text(p.effect)}</span>
            </Row>
            <Row label="Already sent at">
              <span className="wrap-any">
                {text(field(p, 'previous_sent_at', 'previousSentAt', 'sent_at', 'sentAt'))}
              </span>
            </Row>
            <Row label="Buyer">
              <span className="wrap-any">{text(p.buyer_email)}</span>
            </Row>
            <Row label="Pack">
              <span className="wrap-any">{text(p.pack_id)}</span>
            </Row>
            <Row label="State now">{text(p.state)}</Row>
            <Row label="Attempts so far">{text(p.attempts)}</Row>
            <Row label="Sends the email itself">no — the delivery drain does</Row>
            <Row label="Endpoint">
              <span className="wrap-any font-mono text-[11px]">{text(p.endpoint)}</span>
            </Row>
            {alreadySent(p) ? (
              <p className="mt-2 text-[13px] text-bad-strong">
                Requeuing clears the sent time. It is the only way to put the row back in the
                queue, so the record that the first email went out will not survive this.
              </p>
            ) : null}
            {p.last_error ? (
              <p className="wrap-any mt-1 font-mono text-[11px] text-bad-strong">
                {String(p.last_error)}
              </p>
            ) : null}
            {p.found === false && p.found_note ? <Note>{String(p.found_note)}</Note> : null}
          </div>
        )}
      />

      {receipt && applied === false ? (
        <div className="mt-2">
          <Problem>
            The store refused this resend
            {status ? ` (HTTP ${status})` : ''}. Nothing was queued.
            {status === 409
              ? ' A 409 means the entitlement is revoked — the order was refunded or disputed, so there is no link to send.'
              : ''}
          </Problem>
          <div className="scroll-x mt-1">
            <pre className="font-mono text-[11px] text-muted">
              {JSON.stringify(receipt.response ?? receipt, null, 1)}
            </pre>
          </div>
        </div>
      ) : null}

      {receipt && applied ? (
        <div className="mt-2">
          <div
            className={`wrap-any rounded-sm border px-3 py-2 text-[13px] ${
              previousSentAt
                ? 'border-warn/50 bg-warn-bg text-warn-strong'
                : 'border-ok/40 bg-ok-bg text-ok-strong'
            }`}
          >
            {resendWords(action, previousSentAt)}
          </div>
        </div>
      ) : null}
    </div>
  );
}
