import React, { useState } from 'react';
import { ShieldCheck, Lock, Check, AlertCircle, Terminal } from 'lucide-react';
import api from '../services/api';
import CornerBrackets from './effects/CornerBrackets';
import TargetLock from './effects/TargetLock';

const PRINCIPLES = [
  {
    number: '01',
    title: 'No bank credentials requested',
    body: 'ArthaShield never asks for a bank password, OTP, UPI PIN or card CVV. Only use a statement export you are permitted to analyse.',
  },
  {
    number: '02',
    title: 'Identifiers redacted before AI',
    body: 'The server masks common identifiers such as phone numbers, emails, account/card numbers, PAN, Aadhaar and UPI IDs before any AI request. Pattern matching is not perfect, so review the Privacy Inspector preview before running analysis.',
  },
  {
    number: '03',
    title: 'Deterministic figures, scoped deletion',
    body: 'Financial totals and ratios are calculated by server-side rules, not by the AI. Shred Data removes this session’s stored transactions, snapshots, EMI scenarios and consent records from the active database.',
  },
];

export default function ConsentModal({ onConsentGiven }) {
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const handleSubmit = async () => {
    if (!agreed) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await api.logConsent(null, 'v1.1-2026-11');
      if (res && res.status === 'CONSENT_REGISTERED') {
        onConsentGiven();
      } else {
        setErrorMsg('Consent could not be verified by the backend. Please try again.');
      }
    } catch (e) {
      console.error('Consent logging failed:', e);
      const serverErr = e.response?.data?.error || e.response?.data?.detail;
      setErrorMsg(
        serverErr ||
          'Consent registration failed. Check that the ArthaShield backend is reachable and try again.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/95 p-3 backdrop-blur-md animate-in fade-in duration-200 motion-reduce:animate-none sm:p-6">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="consent-title"
        className="relative w-full max-w-xl space-y-5 border border-[#2A2A2A] bg-black p-5 shadow-[0_0_48px_rgba(255,255,255,0.08)] font-mono sm:p-8"
      >
        <CornerBrackets size={14} strokeWidth={2} />

        <div className="flex items-center justify-between gap-3 border-b border-[#202020] pb-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="border border-white bg-black px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-white">
              VERIFICATION GATEWAY
            </span>
            <span className="text-[10px] uppercase tracking-[0.22em] text-[#B8B8B8]">
              ARTHASHIELD 2026
            </span>
          </div>
          <Lock className="h-4 w-4 shrink-0 text-white" aria-hidden="true" />
        </div>

        <div className="space-y-3">
          <h2
            id="consent-title"
            className="m-0 text-base font-bold uppercase leading-snug tracking-[0.14em] text-white sm:text-lg"
          >
            Privacy & Consent Gateway
          </h2>
          <p className="m-0 text-[12px] leading-relaxed text-[#C8C8C8] sm:text-[13px]">
            ArthaShield includes synthetic demo personas and an optional statement-upload
            workflow. No bank login, password, OTP, UPI PIN or card CVV is requested.
          </p>
          <p className="m-0 text-[11px] leading-relaxed text-[#A8A8A8]">
            Uploaded statement content is sent to the ArthaShield server for parsing and
            redaction. Raw statements are not saved by the demo database; only sanitized
            transactions are stored when you choose <span className="text-white">Import &amp; Save</span>.
            Sanitized text may be sent to the configured AI provider when you run analysis.
          </p>
        </div>

        <div className="divide-y divide-[#1A1A1A] border border-[#202020] bg-[#070707]">
          {PRINCIPLES.map((principle) => (
            <div
              key={principle.number}
              className="grid grid-cols-[2.15rem_1fr] gap-3 p-3.5 sm:p-4"
            >
              <span
                aria-hidden="true"
                className="flex h-7 w-7 items-center justify-center border border-[#404040] bg-black text-[10px] font-bold text-white"
              >
                {principle.number}
              </span>
              <div className="min-w-0 space-y-1">
                <h3 className="m-0 text-[11px] font-bold uppercase tracking-[0.08em] text-white sm:text-[12px]">
                  {principle.title}
                </h3>
                <p className="m-0 text-[11px] leading-relaxed text-[#BDBDBD] sm:text-[12px]">
                  {principle.body}
                </p>
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-2">
          <label className="group flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
              disabled={submitting}
              aria-describedby="consent-detail"
              className="peer sr-only"
            />
            <span
              aria-hidden="true"
              className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center border border-[#555555] bg-black transition-colors duration-150 peer-checked:border-white peer-checked:bg-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-white group-hover:border-white motion-reduce:transition-none"
            >
              <Check
                className={`h-3.5 w-3.5 text-black transition-opacity duration-150 motion-reduce:transition-none ${
                  agreed ? 'opacity-100' : 'opacity-0'
                }`}
                strokeWidth={3}
              />
            </span>
            <span className="text-[11px] leading-relaxed text-[#C8C8C8] sm:text-[12px]">
              I consent to ArthaShield processing statement content I submit for parsing and
              redaction, and to sending sanitized text to the configured AI provider when I run
              analysis. I will not submit bank passwords, OTPs, PINs or card CVVs.
            </span>
          </label>
          <p id="consent-detail" className="m-0 pl-8 text-[10px] leading-relaxed text-[#8F8F8F]">
            You can withdraw consent from the dashboard header at any time. Withdrawal blocks
            persistent writes and AI analysis for this session.
          </p>
        </div>

        {errorMsg && (
          <div
            role="alert"
            aria-live="polite"
            className="flex items-start gap-2 border border-[#555555] bg-[#0A0A0A] p-3 text-[11px] leading-relaxed text-[#D0D0D0]"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-white" aria-hidden="true" />
            <span>{errorMsg}</span>
          </div>
        )}

        <TargetLock className="w-full">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!agreed || submitting}
            aria-busy={submitting}
            className={`w-full border px-4 py-3.5 text-[11px] font-bold uppercase tracking-[0.18em] transition-colors duration-200 motion-reduce:transition-none sm:text-xs ${
              agreed && !submitting
                ? 'cursor-pointer border-white bg-white text-black hover:bg-[#D4D4D4]'
                : 'cursor-not-allowed border-[#2A2A2A] bg-[#0A0A0A] text-[#6F6F6F]'
            }`}
          >
            <span className="inline-flex items-center justify-center gap-2">
              {submitting ? (
                <>
                  <Terminal className="h-3.5 w-3.5" aria-hidden="true" />
                  INITIALIZING ENGINE...
                </>
              ) : (
                <>
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                  INITIALIZE ARTHASHIELD SESSION
                </>
              )}
            </span>
          </button>
        </TargetLock>

        <p className="m-0 text-center text-[9px] uppercase tracking-[0.16em] text-[#777777]">
          Consent version 1.1 · Recorded against this browser session
        </p>
      </div>
    </div>
  );
}
