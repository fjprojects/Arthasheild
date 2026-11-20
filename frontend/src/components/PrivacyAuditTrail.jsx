import React, { useState, useEffect, useCallback } from 'react';
import { 
  ShieldCheck, 
  Lock, 
  Clock, 
  FileCheck2, 
  RefreshCw, 
  AlertTriangle,
  FileText,
  KeyRound,
  CheckCircle2,
  Database
} from 'lucide-react';
import api from '../services/api';
import { Card } from './ui/Card';

const EVENT_TYPE_MAP = {
  SESSION_INITIALIZED: {
    label: 'Session Initialized',
    icon: KeyRound,
    color: 'text-white',
    badge: 'border-white text-white',
  },
  CONSENT_REGISTERED: {
    label: 'Consent Registered',
    icon: ShieldCheck,
    color: 'text-emerald-400',
    badge: 'border-emerald-500 text-emerald-400',
  },
  STATEMENT_IMPORTED: {
    label: 'Statement Ingestion',
    icon: Database,
    color: 'text-cyan-400',
    badge: 'border-cyan-500 text-cyan-400',
  },
  CONSENT_WITHDRAWN: {
    label: 'Consent Withdrawn',
    icon: AlertTriangle,
    color: 'text-rose-400',
    badge: 'border-rose-500 text-rose-400',
  },
};

export default function PrivacyAuditTrail({ sessionId }) {
  const [auditData, setAuditData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchAuditTrail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getPrivacyAuditTrail();
      setAuditData(data);
    } catch (err) {
      console.error('Failed to load privacy audit trail:', err);
      setError(
        err?.response?.data?.error || 
        err?.message || 
        'Failed to fetch privacy audit trail'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAuditTrail();
  }, [fetchAuditTrail, sessionId]);

  return (
    <div className="space-y-4">
      {/* Overview & Security Summary Header */}
      <div className="border border-[#202020] bg-black/90 p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Lock className="w-4 h-4 text-white" />
            <span className="text-white font-mono font-bold text-xs uppercase tracking-widest">
              DPDP Privacy &amp; Consent Audit Ledger
            </span>
          </div>
          <button
            onClick={fetchAuditTrail}
            disabled={loading}
            className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider border border-[#333333] hover:border-white text-[#AAAAAA] hover:text-white transition-colors"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            Refresh Trail
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 text-[10px] font-mono uppercase tracking-wider">
          <div className="border border-[#1E1E1E] bg-[#0A0A0A] p-2.5">
            <span className="block text-[#666666]">Active Session</span>
            <span className="block text-white font-bold mt-1 truncate" title={auditData?.session_id || sessionId}>
              {auditData?.session_id || sessionId || 'Unavailable'}
            </span>
          </div>
          <div className="border border-[#1E1E1E] bg-[#0A0A0A] p-2.5">
            <span className="block text-[#666666]">Consent Status</span>
            <span className={`block font-bold mt-1 ${auditData?.active_consent ? 'text-emerald-400' : 'text-rose-400'}`}>
              {auditData?.active_consent ? 'ACTIVE (DPDP VALIDATED)' : 'WITHDRAWN / ABSENT'}
            </span>
          </div>
          <div className="border border-[#1E1E1E] bg-[#0A0A0A] p-2.5">
            <span className="block text-[#666666]">Audit Events Recorded</span>
            <span className="block text-white font-bold mt-1">
              {auditData?.events?.length ?? 0} Lifecycle Entries
            </span>
          </div>
          <div className="border border-[#1E1E1E] bg-[#0A0A0A] p-2.5">
            <span className="block text-[#666666]">Provenance Guarantee</span>
            <span className="block text-cyan-400 font-bold mt-1">
              Deterministic Local
            </span>
          </div>
        </div>

        <p className="text-[10px] font-mono text-[#777777] leading-relaxed border-t border-[#1A1A1A] pt-2 m-0">
          Cryptographically authenticated, tamper-evident audit record for Indian Digital Personal Data Protection (DPDP) compliance. Every consent authorization, statement scrub, and withdrawal is irrevocably recorded with zero exposure of raw credentials.
        </p>
      </div>

      {/* Events List */}
      <Card className="border border-[#202020] bg-black p-4 space-y-3">
        <div className="flex items-center justify-between border-b border-[#202020] pb-2">
          <span className="text-[10px] font-mono uppercase tracking-widest text-white font-bold">
            Recorded Lifecycle Events
          </span>
          <span className="text-[9px] font-mono text-[#888888] uppercase">
            Chronological Order
          </span>
        </div>

        {loading && (
          <div className="py-8 text-center text-xs font-mono text-[#777777]">
            <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-white" />
            Loading cryptographic audit log...
          </div>
        )}

        {error && !loading && (
          <div className="border border-rose-900/50 bg-rose-950/20 p-3 text-xs font-mono text-rose-400 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {!loading && !error && (!auditData?.events || auditData.events.length === 0) && (
          <div className="py-8 text-center text-xs font-mono text-[#666666]">
            No audit events recorded for this session yet.
          </div>
        )}

        {!loading && !error && auditData?.events?.length > 0 && (
          <div className="space-y-3">
            {auditData.events.map((event, idx) => {
              const meta = EVENT_TYPE_MAP[event.event_type] || {
                label: event.event_type,
                icon: FileText,
                color: 'text-white',
                badge: 'border-white text-white',
              };
              const IconComponent = meta.icon;

              return (
                <div 
                  key={idx}
                  className="border border-[#202020] bg-[#0A0A0A] p-3.5 space-y-2 hover:border-[#404040] transition-colors"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <IconComponent className={`w-3.5 h-3.5 ${meta.color}`} />
                      <span className="text-xs font-mono font-bold text-white">
                        {meta.label}
                      </span>
                      <span className={`text-[9px] font-mono uppercase px-1.5 py-0.5 border ${meta.badge}`}>
                        {event.status || 'LOGGED'}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[10px] font-mono text-[#666666]">
                      <Clock className="w-3 h-3" />
                      <span>{event.timestamp ? new Date(event.timestamp).toLocaleString() : 'N/A'}</span>
                    </div>
                  </div>

                  <p className="text-xs font-mono text-[#AAAAAA] m-0 leading-relaxed">
                    {event.description}
                  </p>

                  {event.metadata && Object.keys(event.metadata).length > 0 && (
                    <div className="border-t border-[#181818] pt-2 mt-2 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2 text-[9px] font-mono text-[#777777]">
                      {Object.entries(event.metadata).map(([k, v]) => (
                        <div key={k} className="truncate">
                          <span className="text-[#555555] uppercase">{k.replace(/_/g, ' ')}:</span>{' '}
                          <span className="text-[#999999]">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
