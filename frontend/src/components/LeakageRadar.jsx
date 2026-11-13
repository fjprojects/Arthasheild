import React, { useState, useEffect } from 'react';
import { 
  Flame, 
  AlertTriangle, 
  CheckCircle, 
  Zap, 
  Scissors, 
  HelpCircle,
  TrendingDown,
  DollarSign,
  Terminal,
  Radio,
  Calendar,
  Layers,
  ChevronDown,
  ChevronUp,
  ShieldCheck,
  ShieldAlert,
  Info
} from 'lucide-react';
import CrypticText from './effects/CrypticText';
import { Card } from './ui/Card';
import api from '../services/api';

export default function LeakageRadar({ leaksSummary, sessionId, subscriptions: propSubscriptions }) {
  const [liveSubs, setLiveSubs] = useState(propSubscriptions || []);
  const [metricsSummary, setMetricsSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState(null);
  const [expandedIdx, setExpandedIdx] = useState(null);
  const [activeMode, setActiveMode] = useState('LIVE'); // 'LIVE' | 'DEMO'

  useEffect(() => {
    let isCancelled = false;

    if (propSubscriptions && propSubscriptions.length > 0) {
      setLiveSubs(propSubscriptions);
      setFetchError(null);
      return;
    }

    if (!sessionId) {
      setLiveSubs([]);
      setMetricsSummary(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setFetchError(null);

    api.getSubscriptions(sessionId)
      .then(res => {
        if (!isCancelled) {
          if (res && res.subscriptions) {
            setLiveSubs(res.subscriptions);
            setMetricsSummary(res);
          } else {
            setLiveSubs([]);
            setMetricsSummary(null);
          }
        }
      })
      .catch(err => {
        if (!isCancelled) {
          console.warn('Failed to fetch recurring subscriptions for LeakageRadar:', err);
          setLiveSubs([]);
          setMetricsSummary(null);
          setFetchError(err.response?.data?.error || 'Unable to scan journal for recurring payments.');
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [sessionId, propSubscriptions]);

  // Determine active item list based on mode
  const hasLive = liveSubs && liveSubs.length > 0;
  const hasPersona = leaksSummary && leaksSummary.dormant_subscriptions && leaksSummary.dormant_subscriptions.length > 0;

  // Auto-select mode if only one available
  const currentMode = (activeMode === 'DEMO' && hasPersona) || !hasLive ? 'DEMO' : 'LIVE';

  let items = [];
  let confirmedMonthly = 0;   // confirmed financial commitments (subscription + fixed obligation)
  let probableMonthly = 0;   // probable commitments pending review
  let avoidableMonthly = 0;   // confirmed subscription commitments (potentially avoidable)
  let essentialMonthly = 0;   // fixed obligations (rent, instalment, insurance, utility)
  let patternMonthly = 0;   // repeated discretionary spending - observed, not a commitment
  let weakCount = 0;

  if (currentMode === 'LIVE' && hasLive) {
    items = liveSubs.map(s => {
      const isIrregular = s.cadence === 'irregular';
      const mCost = s.estimated_monthly_cost !== null && s.estimated_monthly_cost !== undefined
        ? parseFloat(s.estimated_monthly_cost)
        : null;
      const aCost = s.estimated_annual_cost !== null && s.estimated_annual_cost !== undefined
        ? parseFloat(s.estimated_annual_cost)
        : null;

      const conf = s.confidence || 'PROBABLE';
      const pType = s.payment_type || 'subscription';
      const commitmentClass = s.commitment_class || null;
      // Task 23: a recurrence is not automatically a commitment. Only a
      // confirmed commitment reserves money; repeated discretionary spending is
      // reported as an observed pattern.
      const isCommitment = s.is_financial_commitment === true;
      const isAvoidable = s.is_potential_leakage === true;
      const isPattern = commitmentClass === 'recurring_discretionary' || commitmentClass === 'recurring_pattern';
      const isEssential = ['rent', 'emi_or_loan', 'utility', 'insurance'].includes(pType);

      if (conf === 'CONFIRMED' && mCost !== null && isCommitment) {
        confirmedMonthly += mCost;
        if (isAvoidable) avoidableMonthly += mCost;
        if (isEssential) essentialMonthly += mCost;
      } else if (conf === 'CONFIRMED' && mCost !== null && isPattern) {
        // Observed repeated spending: never counted as a confirmed commitment.
        patternMonthly += mCost;
      } else if (conf === 'PROBABLE' && mCost !== null) {
        probableMonthly += mCost;
      } else if (conf === 'WEAK') {
        weakCount += 1;
      }

      return {
        service: s.merchant || s.identifier,
        monthly_cost: mCost,
        annual_cost: aCost,
        observed_total: s.observed_total_spend ? parseFloat(s.observed_total_spend) : null,
        cost_label: s.cost_label,
        status: pType.replace(/_/g, ' '),
        payment_type: pType,
        commitment_class: commitmentClass,
        is_commitment: isCommitment,
        is_avoidable: isAvoidable,
        is_pattern: isPattern,
        is_essential: isEssential,
        cadence: s.cadence || 'monthly',
        confidence: conf,
        recurrence_confidence: s.recurrence_confidence || conf,
        amount_variation: s.amount_variation || 'fixed',
        amount_range: s.observed_amount_range || null,
        occurrence_count: s.occurrence_count || (s.candidates ? 2 : 1),
        next_date: s.estimated_next_date,
        is_past_projection: s.is_past_projection,
        projection_status: s.projection_status,
        evidence: s.evidence || [],
        dates: s.transaction_dates || [],
        amounts: s.transaction_amounts || [],
        recommendation: isAvoidable
          ? 'Recurring subscription charge. Review whether it is still used: cancelling it would free this amount each month. Usage is not visible in the statement, so this is a review, not an established saving.'
          : isEssential
          ? 'Essential commitment (rent, instalment, insurance or utility). Non-cancelable outflow in the usual case; monitor the observed amount rather than trying to reduce it.'
          : isPattern
          ? 'Repeated discretionary spending. The amount shown is the observed average of the pattern, not a fixed commitment - it is not counted towards confirmed monthly outflow.'
          : 'Review the counterparty pattern in the audit journal; no commitment evidence was found.',
      };
    });
  } else if (leaksSummary) {
    const personaSubs = leaksSummary.dormant_subscriptions || [];
    const pTotal = leaksSummary.total_monthly_leakage || 0;
    confirmedMonthly = pTotal;
    avoidableMonthly = pTotal;
    items = personaSubs.map(s => ({
      service: s.service,
      monthly_cost: s.monthly_cost || 0,
      annual_cost: (s.monthly_cost || 0) * 12,
      observed_total: null,
      status: s.status?.replace(/_/g, ' ') || 'SUBSCRIPTION',
      payment_type: 'subscription',
      commitment_class: 'subscription_commitment',
      is_commitment: true,
      is_avoidable: true,
      is_pattern: false,
      is_essential: false,
      cadence: 'monthly',
      confidence: 'CONFIRMED',
      recurrence_confidence: 'CONFIRMED',
      amount_variation: 'fixed',
      amount_range: null,
      occurrence_count: 2,
      recommendation: s.recommendation || 'Review the recurring charge: cancelling it would free this amount each month if it is no longer used.',
      evidence: ['Pre-configured synthetic scenario demonstration'],
      dates: [],
      amounts: [],
    }));
  }

  const confirmedAnnual = confirmedMonthly * 12;

  const getConfidenceBadge = (confidence) => {
    switch (confidence) {
      case 'CONFIRMED':
        return (
          <span className="border border-emerald-500/60 bg-emerald-950/40 text-emerald-300 text-[9px] font-mono uppercase px-2 py-0.5 tracking-wider font-bold">
            CONFIRMED
          </span>
        );
      case 'PROBABLE':
        return (
          <span className="border border-amber-500/60 bg-amber-950/40 text-amber-300 text-[9px] font-mono uppercase px-2 py-0.5 tracking-wider font-bold">
            PROBABLE
          </span>
        );
      case 'WEAK':
      default:
        return (
          <span className="border border-zinc-700 bg-zinc-900 text-zinc-400 text-[9px] font-mono uppercase px-2 py-0.5 tracking-wider font-bold">
            WEAK (OBSERVATION)
          </span>
        );
    }
  };

  const getPaymentTypeBadge = (status, isEssential) => {
    return (
      <span className={`border text-[9px] font-mono uppercase px-2 py-0.5 tracking-wider ${
        isEssential 
          ? 'border-blue-500/40 bg-blue-950/30 text-blue-300' 
          : 'border-[#404040] bg-[#111111] text-zinc-300'
      }`}>
        {status}
      </span>
    );
  };

  if (!leaksSummary && items.length === 0 && !loading) {
    return (
      <Card corners={12} cornerStroke={2} className="p-8 font-mono text-center space-y-3">
        <Radio className="w-8 h-8 text-[#8A8A8A] mx-auto animate-pulse" />
        <h3 className="text-sm font-bold uppercase tracking-[0.2em] text-white m-0">
          Leakage Radar Scanning Active Journal
        </h3>
        <p className="text-xs text-[#888888] max-w-md mx-auto leading-relaxed">
          {fetchError || 'Zero recurring drains or subscription traps detected in imported statement transactions. Multi-month import history is recommended to confirm monthly or quarterly cadence.'}
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-6 font-mono">
      
      {/* Leakage Header Banner — Stark Contrast Box with Corner Accents */}
      <Card
        corners={12}
        cornerStroke={2}
        className="p-8 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6"
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="border border-white bg-black px-2 py-0.5 text-[9px] font-mono uppercase text-white font-bold tracking-widest">
              RADAR
            </span>
            <span className="text-[10px] font-mono uppercase text-[#AAAAAA] tracking-widest flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 bg-white rounded-full animate-ping" />
              {items.length} RECURRING STREAMS IDENTIFIED
            </span>
            {hasLive && (
              <span className="border border-emerald-500/40 bg-emerald-950/20 text-emerald-400 text-[8px] font-mono uppercase px-1.5 py-0.2 tracking-widest">
                LIVE STATEMENT AUDIT
              </span>
            )}
            {/* View Mode Toggle Pill Buttons */}
            {hasLive && hasPersona && (
              <div className="flex items-center gap-1 ml-2 border border-[#333333] p-0.5 bg-black">
                <button
                  type="button"
                  onClick={() => setActiveMode('LIVE')}
                  className={`px-2 py-0.5 text-[8px] uppercase tracking-wider font-bold transition-colors ${
                    currentMode === 'LIVE' 
                      ? 'bg-white text-black' 
                      : 'text-[#888888] hover:text-white'
                  }`}
                >
                  Live Statement
                </button>
                <button
                  type="button"
                  onClick={() => setActiveMode('DEMO')}
                  className={`px-2 py-0.5 text-[8px] uppercase tracking-wider font-bold transition-colors ${
                    currentMode === 'DEMO' 
                      ? 'bg-white text-black' 
                      : 'text-[#888888] hover:text-white'
                  }`}
                >
                  Demo Persona
                </button>
              </div>
            )}
          </div>
          <h3 className="text-sm font-bold uppercase tracking-[0.2em] text-white m-0 font-mono">
            Recurring Commitment & Leakage Intelligence
          </h3>
          <p className="text-xs font-mono text-[#AAAAAA] max-w-xl leading-relaxed m-0">
            Separates confirmed commitments (subscriptions and fixed obligations) from repeated
            discretionary spending and from patterns without any commitment evidence.
          </p>
        </div>

        {/* Financial metrics with Segregated Confirmed vs Discretionary */}
        <div className="flex flex-wrap sm:flex-nowrap items-center gap-8 border-t lg:border-t-0 lg:border-l border-[#202020] pt-4 lg:pt-0 lg:pl-8">
          <div>
            <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-white font-bold">
              <CrypticText text={`₹${Math.round(confirmedMonthly).toLocaleString('en-IN')}`} triggerKey={confirmedMonthly} />
            </div>
            <div className="text-[9px] uppercase text-emerald-400 font-mono tracking-widest mt-2 flex items-center gap-1">
              <span>● Confirmed Monthly Commitment</span>
            </div>
            {probableMonthly > 0 && (
              <div className="text-[8px] uppercase text-amber-400/90 font-mono tracking-wider mt-1">
                + ₹{Math.round(probableMonthly).toLocaleString('en-IN')}/mo Probable Review
              </div>
            )}
          </div>

          <div className="sm:border-l sm:border-[#202020] sm:pl-8">
            <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-amber-400 font-bold">
              <CrypticText text={`₹${Math.round(avoidableMonthly).toLocaleString('en-IN')}`} triggerKey={avoidableMonthly} />
            </div>
            <div className="text-[9px] uppercase text-amber-300 font-mono tracking-widest mt-2">
              Potentially Avoidable Recurring
            </div>
            <div className="text-[8px] uppercase text-[#888888] font-mono tracking-wider mt-1">
              ₹{Math.round(essentialMonthly).toLocaleString('en-IN')}/mo Essential Fixed
            </div>
            {patternMonthly > 0 && (
              <div className="text-[8px] uppercase text-[#888888] font-mono tracking-wider mt-1">
                ₹{Math.round(patternMonthly).toLocaleString('en-IN')}/mo Repeated Spending (not a commitment)
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* Commitments & Subscriptions Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {items.map((sub, idx) => {
          const isExpanded = expandedIdx === idx;
          const hasEstimated = sub.monthly_cost !== null && sub.monthly_cost !== undefined;

          return (
            <div 
              key={idx}
              className={`relative border bg-black/90 p-6 transition-all flex flex-col justify-between space-y-4 group shadow-sm ${
                sub.is_essential 
                  ? 'border-[#252535] hover:border-blue-400/60' 
                  : 'border-[#202020] hover:border-white'
              }`}
            >
              <div className="absolute top-1 right-2 text-[8px] font-mono text-[#404040] group-hover:text-white transition-colors" aria-hidden="true">
                +
              </div>
              <div className="flex items-start justify-between border-b border-[#202020] pb-3">
                <div className="space-y-1">
                  <div className="flex items-center space-x-2">
                    <h4 className="text-xs font-mono font-bold uppercase tracking-wider text-white m-0">
                      {sub.service}
                    </h4>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 pt-1">
                    {getPaymentTypeBadge(sub.status, sub.is_essential)}
                    {getConfidenceBadge(sub.confidence)}
                    {sub.commitment_class && (
                      <span className={`border text-[8px] font-mono uppercase px-1.5 py-0.5 tracking-wider ${
                        sub.is_commitment
                          ? 'border-emerald-500/40 bg-emerald-950/20 text-emerald-300'
                          : 'border-[#3a3a3a] bg-[#0E0E0E] text-[#888888]'
                      }`}>
                        {sub.commitment_class.replace(/_/g, ' ')}
                      </span>
                    )}
                    <span className="border border-[#303030] bg-[#0E0E0E] text-[#888888] text-[9px] font-mono uppercase px-2 py-0.5">
                      {sub.cadence}
                    </span>
                    {sub.amount_variation && (
                      <span className="border border-[#252525] text-[#777777] text-[8px] font-mono uppercase px-1.5 py-0.5">
                        {sub.amount_variation.replace('_', ' ')}
                      </span>
                    )}
                    {sub.amount_range && sub.amount_range.includes('-') && (
                      <span className="border border-[#252525] text-[#777777] text-[8px] font-mono uppercase px-1.5 py-0.5">
                        ₹{sub.amount_range}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  {hasEstimated ? (
                    <>
                      <span className="text-2xl font-mono font-bold text-white block">
                        ₹{sub.monthly_cost.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                      <span className="text-[9px] font-mono text-[#AAAAAA] block uppercase">
                        / Month
                      </span>
                      {sub.annual_cost !== null && (
                        <span className="text-[8px] font-mono text-[#8A8A8A] block">
                          ₹{sub.annual_cost.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} / yr
                        </span>
                      )}
                    </>
                  ) : (
                    <>
                      <span className="text-lg font-mono font-bold text-amber-300 block">
                        ₹{(sub.observed_total || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                      <span className="text-[9px] font-mono text-[#AAAAAA] block uppercase">
                        Observed Total
                      </span>
                      <span className="text-[8px] font-mono text-zinc-500 block italic">
                        Annual Cost Withheld
                      </span>
                    </>
                  )}
                </div>
              </div>

              {/* Observed Occurrence Count & Next Date with Past Projections check */}
              {(sub.occurrence_count || sub.next_date) && (
                <div className="flex items-center justify-between text-[9px] text-[#888888] border-b border-[#181818] pb-2">
                  <span>
                    Observed: <strong className="text-white">{sub.occurrence_count} debit{sub.occurrence_count > 1 ? 's' : ''}</strong>
                  </span>
                  {sub.next_date && (
                    <span className="flex items-center gap-1.5">
                      <span>Est. Next:</span>
                      <strong className="text-white">{sub.next_date}</strong>
                      {sub.is_past_projection && (
                        <span className="border border-amber-600/40 bg-amber-950/40 text-amber-400 text-[7px] uppercase px-1 py-0.2 font-bold">
                          {sub.projection_status === 'STALE_HISTORY' ? 'STALE STATEMENT' : 'OVERDUE'}
                        </span>
                      )}
                    </span>
                  )}
                </div>
              )}

              {/* Prune Protocol Callout */}
              <div className={`border-l-2 p-3 space-y-1 ${
                sub.is_essential 
                  ? 'border-blue-500 bg-[#0A0A12]' 
                  : 'border-white bg-[#0A0A0A]'
              }`}>
                <span className={`text-[9px] font-mono uppercase tracking-wider block font-bold ${
                  sub.is_essential ? 'text-blue-300' : 'text-[#AAAAAA]'
                }`}>
                  {sub.is_essential ? 'Preservation Protocol' : 'Prune Protocol'}
                </span>
                <p className="text-xs font-mono text-[#AAAAAA] m-0">
                  {sub.recommendation}
                </p>
              </div>

              {/* Evidence details toggle */}
              {sub.evidence && sub.evidence.length > 0 && (
                <div className="pt-1">
                  <button
                    type="button"
                    onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                    className="flex items-center space-x-1.5 text-[9px] uppercase tracking-wider text-[#888888] hover:text-white transition-colors"
                  >
                    <span>{isExpanded ? 'Hide Evidence Journal' : 'Inspect Evidence Journal'}</span>
                    {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </button>

                  {isExpanded && (
                    <div className="mt-2 p-3 border border-[#202020] bg-[#070707] space-y-2 text-[9px] text-[#AAAAAA]">
                      <div className="font-bold text-white uppercase tracking-wider">
                        Evidence Tracing:
                      </div>
                      <ul className="list-disc pl-4 space-y-1 text-[#999999]">
                        {sub.evidence.map((ev, i) => (
                          <li key={i}>{ev}</li>
                        ))}
                      </ul>
                      {sub.dates && sub.dates.length > 0 && (
                        <div className="pt-2 border-t border-[#181818]">
                          <span className="text-white uppercase font-bold block mb-1">
                            Observed Debits:
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {sub.dates.map((d, di) => (
                              <span key={di} className="border border-[#252525] bg-black px-1.5 py-0.5 text-[8px] text-[#AAAAAA]">
                                {d}: ₹{sub.amounts && sub.amounts[di] ? sub.amounts[di] : (sub.monthly_cost || sub.observed_total)}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Evidence-Aware Runway Recovery Callout */}
      <Card
        interactive={false}
        className="p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 font-mono text-xs text-[#AAAAAA]"
      >
        <div className="flex items-start sm:items-center space-x-2.5">
          <Terminal className="w-4 h-4 text-white shrink-0 mt-0.5 sm:mt-0" />
          <div className="space-y-0.5">
            <div>
              <strong className="text-white uppercase font-bold">Runway Recovery: </strong> 
              Reviewing the recurring subscriptions could free up to{' '}
              <strong className="text-amber-300">₹{Math.round(avoidableMonthly).toLocaleString('en-IN')}/mo</strong>{' '}
              into emergency reserves, if those subscriptions are no longer used.
            </div>
            {essentialMonthly > 0 && (
              <div className="text-[10px] text-[#777777]">
                Essential commitments (₹{Math.round(essentialMonthly).toLocaleString('en-IN')}/mo for Rent, EMI, Utilities, Insurance) are preserved and excluded from cancellation savings.
              </div>
            )}
            {patternMonthly > 0 && (
              <div className="text-[10px] text-[#777777]">
                Repeated discretionary spending (₹{Math.round(patternMonthly).toLocaleString('en-IN')}/mo) is an observed spending pattern, not a commitment - it is not counted as recoverable savings.
              </div>
            )}
          </div>
        </div>
        <span className="border border-white bg-black px-2.5 py-1 text-[9px] uppercase font-bold text-white tracking-widest shrink-0">
          +₹{Math.round(avoidableMonthly).toLocaleString('en-IN')}/MO REVIEWABLE
        </span>
      </Card>

    </div>
  );
}
