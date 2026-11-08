import React, { useState } from 'react';
import { ShieldCheck, Lock, CheckCircle2, AlertCircle, Terminal } from 'lucide-react';
import api from '../services/api';

export default function ConsentModal({ onConsentGiven }) {
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const handleSubmit = async () => {
    if (!agreed) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await api.logConsent(null, 'v1.0-hackathon-2026');
      if (res && res.status === 'CONSENT_REGISTERED') {
        onConsentGiven();
      } else {
        setErrorMsg('Consent could not be verified by backend. Please try again.');
      }
    } catch (e) {
      console.error('Consent logging failed:', e);
      setErrorMsg(e.response?.data?.error || 'Consent registration failed on server. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-sm p-4 animate-in fade-in duration-150">
      <div className="border border-zinc-700 bg-black max-w-lg w-full p-8 space-y-6 shadow-2xl relative select-none font-mono">
        
        <div className="flex items-center justify-between border-b border-zinc-800 pb-4">
          <div className="flex items-center space-x-2">
            <span className="border border-white px-1.5 py-0.2 text-[9px] uppercase text-white font-bold">
              VERIFICATION GATEWAY
            </span>
            <span className="text-[10px] text-zinc-500 uppercase tracking-widest">
              ARTHASHIELD 2026
            </span>
          </div>
          <Lock className="w-4 h-4 text-white" />
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider m-0">
            Zero-Knowledge Privacy & Client Scrubber Covenant
          </h3>
          <p className="text-[11px] text-zinc-400 leading-relaxed m-0">
            ArthaShield enforces client-side pseudonymization and deterministic local arithmetic. No raw account credentials or phone numbers leave this host.
          </p>
        </div>

        {/* Guarantees List */}
        <div className="space-y-3 bg-zinc-950 border border-zinc-800 p-4 text-[11px] text-zinc-300">
          <div className="flex items-start space-x-2.5">
            <span className="text-white font-bold shrink-0">[1]</span>
            <span><strong className="text-white">Zero Banking Credentials:</strong> Passwords, OTPs, and UPI PINs are strictly prohibited and never requested.</span>
          </div>
          <div className="flex items-start space-x-2.5">
            <span className="text-white font-bold shrink-0">[2]</span>
            <span><strong className="text-white">Deterministic Arithmetic:</strong> Liquidity and runaway calculations are executed via verified Python logic.</span>
          </div>
          <div className="flex items-start space-x-2.5">
            <span className="text-white font-bold shrink-0">[3]</span>
            <span><strong className="text-white">One-Click Permanent Shredder:</strong> Purge all local cache, simulated transactions, and logs instantly.</span>
          </div>
        </div>

        {/* Consent Checkbox */}
        <label className="flex items-start space-x-3 cursor-pointer select-none pt-1">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded-none border border-zinc-600 bg-black accent-white cursor-pointer"
          />
          <span className="text-[11px] text-zinc-400 leading-relaxed">
            I verify that I understand ArthaShield's local-first privacy architecture and authorize anonymized simulation.
          </span>
        </label>

        {/* Error Message */}
        {errorMsg && (
          <div className="border border-zinc-700 bg-zinc-950 p-3 text-xs text-zinc-300 flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 text-white shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* CTA Button */}
        <button
          onClick={handleSubmit}
          disabled={!agreed || submitting}
          className="w-full py-3 px-4 font-bold text-xs uppercase tracking-widest bg-white hover:bg-zinc-200 text-black transition disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
        >
          {submitting ? 'INITIALIZING ENGINE...' : 'INITIALIZE ARTHASHIELD SESSION'}
        </button>

      </div>
    </div>
  );
}
