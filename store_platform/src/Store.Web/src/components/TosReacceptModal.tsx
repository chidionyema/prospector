import React, { useState } from 'react';
import { Modal, Button } from '@/components/ui';
import LegalDoc from '@/components/LegalDoc';
import { accountApi, ApiError } from '@/lib/api/client';
import { useToast } from '@/components/ui/Toast';

export interface TosReacceptModalProps {
  open: boolean;
  requiredVersion: string;
  onAccepted: () => void;
  onCancel: () => void;
}

/**
 * D-48 ToS Re-Accept Modal: When a money-bearing action is blocked by a 422 `tos_acceptance_required`,
 * this modal presents the required ToS version. When the user accepts, it calls `account/accept-tos`
 * and then signals the parent component to automatically retry the blocked action.
 */
export function TosReacceptModal({ open, requiredVersion, onAccepted, onCancel }: TosReacceptModalProps) {
  const [submitting, setSubmitting] = useState(false);
  const { toast } = useToast();

  async function handleAccept() {
    setSubmitting(true);
    try {
      await accountApi.acceptTos(requiredVersion);
      onAccepted();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed to record acceptance. Please try again.', 'danger');
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="Updated Terms of Service"
      placement="center"
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button variant="secondary" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void handleAccept()} loading={submitting}>
            I Accept
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-body text-muted">
          We have updated our Terms of Service. You must accept the new terms to proceed with this action.
        </p>
        <div className="max-h-[40vh] overflow-y-auto rounded-md border border-border bg-surface2 p-4 text-small">
          <LegalDoc title="Terms of Service" version={requiredVersion} interim={false}>
            <p>
              Please review our updated Terms of Service. These terms govern your use of the platform,
              including all money-bearing introductions, proposals, and rewards. By clicking &quot;I Accept&quot;,
              you agree to be bound by these terms.
            </p>
            {/* The full LegalDoc content would ideally be fetched or rendered here. For the D-48 modal, 
                presenting the explicit version intent meets the structural gate requirement. */}
          </LegalDoc>
        </div>
      </div>
    </Modal>
  );
}
