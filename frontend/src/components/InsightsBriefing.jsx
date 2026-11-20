import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  AlertTriangle, 
  TrendingUp, 
  Repeat, 
  AlertCircle, 
  HelpCircle, 
  ChevronDown, 
  ChevronUp, 
  CheckCircle2, 
  ArrowRight,
  ExternalLink,
  Sparkles
} from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/Card';
import CrypticText from './effects/CrypticText';
import api from '../services/api';

const SEVERITY_CONFIG = {
  CRITICAL: {
    color: 'text-red-400',
    borderColor: 'border-red-500/40',
    bg: 'bg-red-950/20',
    badge: 'border-red-500 bg-red-950/40 text-red-300',
    icon: AlertTriangle,
  },
  HIGH: {
    color: 'text-amber-400',
    borderColor: 'border-amber-500/40',
    bg: 'bg-amber-950/20',
    badge: 'border-amber-500 bg-amber-950/40 text-amber-300',
    icon: AlertCircle,
  },
  MEDIUM: {
    color: 'text-yellow-400',
    borderColor: 'border-yellow-500/30',
    bg: 'bg-yellow-950/10',
    badge: 'border-yellow-500/60 bg-yellow-950/30 text-yellow-300',
    icon: TrendingUp,
  },
  LOW: {
    color: 'text-[#AAAAAA]',
    borderColor: 'border-[#303030]',
    bg: 'bg-[#111111]/40',
    badge: 'border-[#404040] bg-[#1a1a1a] text-[#CCCCCC]',
    icon: CheckCircle2,
  },
  INFO: {
    color: 'text-emerald-400',
    borderColor: 'border-emerald-500/30',
    bg: 'bg-emerald-950/10',
    badge: 'border-emerald-500/60 bg-emerald-950/30 text-emerald-300',
    icon: CheckCircle2,
  },
};

export default function InsightsBriefing({
  sessionId,
  includePersona = false,
  hasConsented = true,
  datasetSourceLabel,
}) {
  const [briefing, setBriefing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    setError(null);

    const fetchBriefing = async () => {
      try {
        const data = await api.getEvidenceBriefing(sessionId, includePersona);
        if (isMounted) {
          setBriefing(data);
          setLoading(false);
          // Auto-expand first critical or high insight
          if (data?.insights?.length > 0) {
            const highSev = data.insights.find(i => i.severity === 'CRITICAL' || i.severity === 'HIGH');
            setExpandedId(highSev ? highSev.id : data.insights[0].id);
          }
        }
      } catch (err) {
        if (isMounted) {
          console.error('Failed to load evidence briefing:', err);
          setError(err?.response?.data?.error || 'Unable to generate financial briefing.');
          setLoading(false);
        }
      }
    };

    // Never call the consent-gated briefing endpoint before consent is
    // verified active. Rendering nothing is safer than surfacing a 403.
    if (sessionId && hasConsented) {
      fetchBriefing();
    } else {
      setBriefing(null);
      setLoading(false);
    }

    return () => {
      isMounted = false;
    };
  }, [sessionId, includePersona, hasConsented]);

  if (!hasConsented) return null;

  if (loading) {
    return (
      <Card corners={10} marker className="p-6 font-mono border-[#202020]">
        <div className="flex items-center gap-3 text-xs text-[#AAAAAA] animate-pulse">
          <Sparkles className="w-4 h-4 text-white" />
          <span>Synthesising verified financial evidence...</span>
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card corners={10} marker className="p-6 font-mono border-red-900/30 bg-red-950/10">
        <div className="flex items-center gap-2 text-xs text-red-400">
          <AlertCircle className="w-4 h-4" />
          <span>{error}</span>
        </div>
      </Card>
    );
  }

  if (!briefing || !briefing.has_data || !briefing.insights || briefing.insights.length === 0) {
    return null;
  }

  const toggleExpand = (id) => {
    setExpandedId(prev => (prev === id ? null : id));
  };

  return (
    <div className="space-y-4 font-mono">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-[#202020] pb-3">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shrink-0" />
          <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0 break-words">
            <CrypticText text="EVIDENCE-BASED FINANCIAL BRIEFING" />
          </h3>
          <span className="border border-[#404040] bg-[#111111] text-[9px] uppercase tracking-widest px-2 py-0.5 text-[#AAAAAA]">
            {briefing.reporting_period?.label || 'CURRENT CYCLE'}
          </span>
          <span className="border border-[#404040] bg-[#111111] text-[8px] uppercase tracking-widest px-2 py-0.5 text-[#CCCCCC]">
            {datasetSourceLabel || (includePersona ? 'DEMO PERSONA · SCENARIO' : 'IMPORTED STATEMENT · OBSERVED')}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-[#888888]">
          <span className="border border-emerald-500/40 bg-emerald-950/20 text-emerald-400 px-1.5 py-0.5 text-[8px] uppercase font-bold tracking-wider">
            Deterministic Math
          </span>
          <span>•</span>
          <span>Evidence-Checked Responses</span>
        </div>
      </div>

      {/* Insights list */}
      <div className="grid grid-cols-1 gap-3">
        {briefing.insights.map((insight) => {
          const config = SEVERITY_CONFIG[insight.severity] || SEVERITY_CONFIG.INFO;
          const Icon = config.icon;
          const isExpanded = expandedId === insight.id;

          return (
            <div
              key={insight.id}
              className={`border transition-all duration-200 rounded-sm ${config.borderColor} ${config.bg} overflow-hidden`}
            >
              {/* Insight Header (Clickable) */}
              <button
                type="button"
                onClick={() => toggleExpand(insight.id)}
                className="w-full text-left p-4 flex items-start justify-between gap-4 focus:outline-none hover:bg-white/[0.02]"
              >
                <div className="flex items-start gap-3">
                  <div className={`p-1.5 rounded-sm border ${config.badge} mt-0.5 shrink-0`}>
                    <Icon className="w-3.5 h-3.5" />
                  </div>
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.2 border ${config.badge}`}>
                        {insight.severity}
                      </span>
                      <span className="text-[9px] uppercase tracking-widest text-[#777777]">
                        {insight.type.replace('_', ' ')}
                      </span>
                      <span className="text-[8px] font-bold tracking-widest text-emerald-400 bg-emerald-950/30 border border-emerald-500/20 px-1">
                        CONFIDENCE: {insight.confidence}
                      </span>
                    </div>
                    <p className="text-xs font-semibold text-white tracking-wide leading-relaxed m-0">
                      {insight.finding}
                    </p>
                  </div>
                </div>

                <div className="shrink-0 text-[#666666] pt-1">
                  {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </div>
              </button>

              {/* Expanded Details: Evidence, Explanation, Action */}
              {isExpanded && (
                <div className="p-4 pt-1 border-t border-[#202020] space-y-4 bg-black/40 text-xs">
                  {/* 1. What is the evidence? */}
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-[#888888] font-bold">
                      <span className="w-1.5 h-1.5 bg-[#666666] rounded-full" />
                      1. Evidence & Verified Metrics
                    </div>
                    <div className="p-3 bg-[#0A0A0A] border border-[#202020] rounded-sm grid grid-cols-2 sm:grid-cols-3 gap-3">
                      {Object.entries(insight.evidence || {}).map(([k, v]) => {
                        if (typeof v === 'object' && v !== null) {
                          return null; // Skip complex objects in key-value grid
                        }
                        return (
                          <div key={k} className="space-y-0.5">
                            <span className="text-[9px] uppercase tracking-wider text-[#777777] block">
                              {k.replace(/_/g, ' ')}
                            </span>
                            <span className="text-xs text-white font-bold block">
                              {k.includes('amount') || k.includes('cost') || k.includes('surplus') || k.includes('expenses') || k.includes('income') || k.includes('recovered') 
                                ? `₹${v}` 
                                : String(v)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* 2. Why was it detected? */}
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-[#888888] font-bold">
                      <span className="w-1.5 h-1.5 bg-[#666666] rounded-full" />
                      2. Deterministic Rule / Explanation
                    </div>
                    <p className="text-[11px] text-[#BBBBBB] leading-relaxed m-0 p-3 bg-[#0A0A0A] border border-[#202020] rounded-sm">
                      {insight.explanation}
                    </p>
                  </div>

                  {/* 3. What can the user do? */}
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-emerald-400 font-bold">
                      <ArrowRight className="w-3 h-3" />
                      3. Actionable Next Step
                    </div>
                    <div className="p-3 bg-emerald-950/10 border border-emerald-500/20 rounded-sm text-[11px] text-emerald-200 leading-relaxed flex items-start gap-2">
                      <span>{insight.action}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

