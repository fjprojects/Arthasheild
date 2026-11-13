import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  Info,
  LoaderCircle,
  LockKeyhole,
  RotateCcw,
  ShieldCheck,
  ShieldOff,
  Trash2,
  X,
} from 'lucide-react';

/**
 * ArthaShield — Security Command Center
 *
 * The three navbar security controls share one visual language but keep their
 * real states separate:
 *
 *   - Consent is driven only by the backend-confirmed `hasConsented` prop.
 *     Withdrawal is disabled while the request is in flight.
 *   - Zero Credentials describes the actual flow: no bank password, OTP, UPI
 *     PIN or card CVV is requested. It does not claim independent bank
 *     verification.
 *   - Shred opens a confirmation dialog and calls the existing deletion handler
 *     only after the user confirms. Success and failure remain App's toasts.
 */

const CREDENTIAL_TOOLTIP_ID = 'artha-zero-credentials-note';

function ConsentModule({ hasConsented, isWithdrawing, onWithdrawConsent, onOpenConsentModal }) {
  const state = hasConsented ? 'active' : 'withdrawn';
  const actionLabel = hasConsented ? 'Withdraw' : 'Re-authorize';
  const statusLabel = hasConsented ? 'Active' : 'Withdrawn';

  return (
    <div
      className="security-module security-module--consent"
      data-state={state}
      data-busy={isWithdrawing ? 'true' : 'false'}
      aria-label={hasConsented ? 'Consent active' : 'Consent withdrawn'}
    >
      <span className="security-module__sheen" aria-hidden="true" />
      <span className="security-module__head">
        <span className="security-module__head-label">
          {hasConsented ? (
            <ShieldCheck className="security-module__head-icon" aria-hidden="true" />
          ) : (
            <ShieldOff className="security-module__head-icon" aria-hidden="true" />
          )}
          Consent
        </span>
        <span className="security-module__code">01</span>
      </span>

      <div className="security-consent__body" key={state}>
        <span className="security-consent__dot" aria-hidden="true" />
        <span className="security-consent__word">{statusLabel}</span>
        <button
          type="button"
          onClick={hasConsented ? onWithdrawConsent : onOpenConsentModal}
          disabled={isWithdrawing}
          aria-label={hasConsented ? 'Withdraw consent' : 'Authorize consent'}
          title={
            hasConsented
              ? 'Withdraw active consent for this session'
              : 'Open the consent gateway'
          }
          className="security-action"
        >
          {isWithdrawing ? (
            <>
              <LoaderCircle className="security-action__spinner" aria-hidden="true" />
              <span className="security-action__text">Revoking</span>
            </>
          ) : (
            <>
              <span className="security-action__text">{actionLabel}</span>
              <span className="security-action__icon" aria-hidden="true">
                {hasConsented ? <X /> : <RotateCcw />}
              </span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function CredentialModule() {
  return (
    <div
      className="security-module security-module--credential"
      tabIndex={0}
      role="note"
      aria-label="Zero credentials. No bank password, OTP, UPI PIN or card CVV is requested."
      aria-describedby={CREDENTIAL_TOOLTIP_ID}
    >
      <span className="security-module__sheen" aria-hidden="true" />
      <span className="security-module__head">
        <span className="security-module__head-label">
          <LockKeyhole className="security-module__head-icon" aria-hidden="true" />
          Credentials
        </span>
        <span className="security-module__code">02</span>
      </span>
      <span className="security-credential__body">
        <ShieldCheck className="security-credential__shield" aria-hidden="true" />
        <span className="security-credential__label">Zero Credentials</span>
        <Info className="security-credential__info" aria-hidden="true" />
      </span>
      <span className="security-tooltip" id={CREDENTIAL_TOOLTIP_ID} role="tooltip">
        <span className="security-tooltip__title">No bank credentials requested</span>
        <span className="security-tooltip__body">
          ArthaShield never asks for a bank password, OTP, UPI PIN or card CVV.
          Requests use an anonymous session token. This is not an independent
          verification of your bank.
        </span>
      </span>
    </div>
  );
}

function ShredDialog({ open, onCancel, onConfirm }) {
  const dialogRef = useRef(null);
  const cancelRef = useRef(null);
  const previousFocusRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;

    previousFocusRef.current = document.activeElement;
    const focusTimer = window.setTimeout(() => cancelRef.current?.focus(), 0);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusable = dialogRef.current?.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      const previous = previousFocusRef.current;
      if (previous && typeof previous.focus === 'function') previous.focus();
    };
  }, [open, onCancel]);

  if (!open) return null;

  return createPortal(
    <div
      className="shred-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        className="shred-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shred-dialog-title"
        aria-describedby="shred-dialog-description"
        ref={dialogRef}
      >
        <span className="shred-dialog__scan" aria-hidden="true" />

        <div className="shred-dialog__head">
          <span className="shred-dialog__eyebrow">
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            Destructive action // Session purge
          </span>
          <button
            type="button"
            className="shred-dialog__close"
            onClick={onCancel}
            aria-label="Close shred confirmation"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <h2 id="shred-dialog-title" className="shred-dialog__title">
          Erase this session&apos;s data?
        </h2>
        <p id="shred-dialog-description" className="shred-dialog__copy">
          This removes the stored records listed below from the active database,
          clears consent for this session and returns ArthaShield to its
          unconsented state. You will need to authorize again before further
          persistent processing.
        </p>

        <div className="shred-dialog__scope">
          <section className="shred-dialog__scope-block">
            <h3>Deleted from the active database</h3>
            <ul>
              <li>Stored transactions</li>
              <li>Financial snapshots</li>
              <li>EMI decision scenarios</li>
              <li>Consent audit records</li>
            </ul>
          </section>
          <section className="shred-dialog__scope-block shred-dialog__scope-block--retained">
            <h3>Not covered by this action</h3>
            <ul>
              <li>Browser history or local storage</li>
              <li>Files you exported or downloaded</li>
              <li>Server backups</li>
              <li>Other sessions or accounts</li>
            </ul>
          </section>
        </div>

        <p className="shred-dialog__warning">
          This cannot be undone from within ArthaShield.
        </p>

        <div className="shred-dialog__actions">
          <button
            type="button"
            className="shred-dialog__button shred-dialog__button--cancel"
            onClick={onCancel}
            ref={cancelRef}
          >
            Cancel
          </button>
          <button
            type="button"
            className="shred-dialog__button shred-dialog__button--confirm"
            onClick={onConfirm}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            Confirm shred
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default function SecurityCommandCenter({
  hasConsented = false,
  isWithdrawing = false,
  onWithdrawConsent,
  onOpenConsentModal,
  onNukeData,
  isNuking = false,
}) {
  const [shredOpen, setShredOpen] = useState(false);

  const openShred = useCallback(() => {
    if (isNuking) return;
    setShredOpen(true);
  }, [isNuking]);

  const closeShred = useCallback(() => {
    if (isNuking) return;
    setShredOpen(false);
  }, [isNuking]);

  const confirmShred = useCallback(() => {
    setShredOpen(false);
    onNukeData?.();
  }, [onNukeData]);

  return (
    <>
      <div className="security-command" role="group" aria-label="Security controls">
        <ConsentModule
          hasConsented={hasConsented}
          isWithdrawing={isWithdrawing}
          onWithdrawConsent={onWithdrawConsent}
          onOpenConsentModal={onOpenConsentModal}
        />
        <CredentialModule />
        <button
          type="button"
          onClick={openShred}
          disabled={isNuking}
          aria-label={isNuking ? 'Shredding session data' : 'Shred session data'}
          aria-haspopup="dialog"
          className="security-module security-module--shred"
          data-busy={isNuking ? 'true' : 'false'}
        >
          <span className="security-module__sheen" aria-hidden="true" />
          <span className="security-module__head">
            <span className="security-module__head-label">Database</span>
            <span className="security-module__code">03</span>
          </span>
          <span className="security-shred__body">
            {isNuking ? (
              <LoaderCircle className="security-shred__icon security-shred__icon--spin" aria-hidden="true" />
            ) : (
              <Trash2 className="security-shred__icon" aria-hidden="true" />
            )}
            <span className="security-shred__label">
              {isNuking ? 'Shredding' : 'Shred data'}
            </span>
          </span>
        </button>
      </div>

      <ShredDialog open={shredOpen} onCancel={closeShred} onConfirm={confirmShred} />
    </>
  );
}
