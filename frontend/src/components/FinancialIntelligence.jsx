import React, { useState, useEffect, useRef } from 'react';
import { 
  Zap, 
  TrendingUp, 
  TrendingDown, 
  AlertTriangle, 
  Repeat, 
  PieChart, 
  RefreshCw, 
  ShieldAlert, 
  Calendar,
  Layers,
  ArrowUpRight,
  ArrowDownLeft,
  CheckCircle2,
  Terminal,
  Clock,
  Radio,
  ShieldCheck,
  HelpCircle,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import api from '../services/api';
import { safeCounterpartyName } from '../utils/display';
import CrypticText from './effects/CrypticText';
import TargetLock from './effects/TargetLock';
import { Card } from './ui/Card';

export default function FinancialIntelligence({
  sessionId = null,
  onRefreshParent,
  includePersona: parentIncludePersona,
  onIncludePersonaChange,
  datasetSourceLabel,
}) {
  // The app owns one active dataset selection. This control still works when
  // the component is mounted standalone, but in the dashboard it derives from
  // and propagates back to that single app-level source.
  const [localIncludePersona, setLocalIncludePersona] = useState(false);
  const includePersona =
    typeof parentIncludePersona === 'boolean' ? parentIncludePersona : localIncludePersona;
  const handleIncludePersonaChange = (next) => {
    if (onIncludePersonaChange) onIncludePersonaChange(next);
    else setLocalIncludePersona(next);
  };
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Selected Reporting Period (derived from dataset or user-selected)
  const [selectedYear, setSelectedYear] = useState(null);
  const [selectedMonth, setSelectedMonth] = useState(null);

  // Phase 2 Datasets
  const [categorized, setCategorized] = useState([]);
  const [budget, setBudget] = useState(null);
  const [subscriptions, setSubscriptions] = useState([]);
  const [unusual, setUnusual] = useState([]);
  const [patterns, setPatterns] = useState(null);
  const [expandedSubIdx, setExpandedSubIdx] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState(null);

  // Monotonic request counter: every fetch takes a ticket, and only the newest
  // ticket is allowed to write state. This stops an outdated sessionId /
  // includePersona response from overwriting the current view.
  const requestSeqRef = useRef(0);

  const resetSessionState = () => {
    setCategorized([]);
    setBudget(null);
    setSubscriptions([]);
    setUnusual([]);
    setPatterns(null);
    setExpandedSubIdx(null);
    setSelectedCategory(null);
    setSelectedYear(null);
    setSelectedMonth(null);
  };

  // Fetch all 5 intelligence APIs
  const fetchAllInsights = async (isStale = () => false, reqYear = null, reqMonth = null) => {
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    const isCancelled = () => isStale() || requestSeqRef.current !== requestSeq;

    setLoading(true);
    setError(null);
    try {
      const yearToFetch = reqYear !== undefined ? reqYear : selectedYear;
      const monthToFetch = reqMonth !== undefined ? reqMonth : selectedMonth;

      const [catRes, budgetRes, subsRes, unusualRes, patternsRes] = await Promise.all([
        api.getCategorization(sessionId, includePersona),
        api.getMonthlyBudget(sessionId, yearToFetch, monthToFetch, includePersona),
        api.getSubscriptions(sessionId, includePersona),
        api.getUnusualSpending(sessionId, includePersona),
        api.getSpendingPatterns(sessionId, 6, includePersona),
      ]);

      // Every state write below is guarded: a stale request must not touch
      // any part of the current session's data.
      if (isCancelled()) return;
      setCategorized(catRes.transactions || []);
      setBudget(budgetRes);
      if (budgetRes?.year && budgetRes?.month) {
        setSelectedYear(budgetRes.year);
        setSelectedMonth(budgetRes.month);
      }
      setSubscriptions(subsRes.subscriptions || []);
      setUnusual(unusualRes.flagged || []);
      setPatterns(patternsRes);
    } catch (err) {
      if (isCancelled()) return;
      console.error('Failed to load financial intelligence:', err);
      setError(err.response?.data?.error || 'Failed to fetch financial intelligence from backend.');
    } finally {
      if (!isCancelled()) setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    // Drop the previous session's intelligence while the new one loads so stale
    // financial data is never displayed under another session/persona flag.
    resetSessionState();
    // Task 20: never fire an authenticated request before the session exists.
    // The API client would otherwise have to create one from this component.
    if (!sessionId) {
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }
    fetchAllInsights(() => cancelled, null, null);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, includePersona]);

  const formatInr = (val) => {
    const num = parseFloat(val) || 0;
    return `₹${num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-150 font-mono">
      
      {/* Top Banner & Controls — Stark Contrast Box with SVG Corner Brackets */}
      <Card
        corners={12}
        cornerStroke={2}
        className="p-8 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6"
      >
        
        <div className="space-y-2">
          <div className="flex items-center space-x-2">
            <span className="border border-white bg-black px-2 py-0.5 text-[9px] uppercase text-white font-bold tracking-widest">
              PHASE 2 ENGINE
            </span>
            <span className="border border-[#404040] bg-[#111111] px-2 py-0.5 text-[8px] uppercase text-[#CCCCCC] font-bold tracking-wider">
              {datasetSourceLabel || (includePersona ? 'DEMO PERSONA · SCENARIO' : 'IMPORTED STATEMENT · OBSERVED')}
            </span>
            <span className="text-[10px] uppercase text-[#AAAAAA] tracking-widest flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 bg-white rounded-full animate-ping" />
              FINANCIAL INTELLIGENCE COGNITION
            </span>
          </div>
          <h2 className="text-sm font-bold uppercase tracking-[0.2em] text-white m-0">
            Automated Cashflow & Anomaly Intelligence
          </h2>
          <p className="text-xs text-[#AAAAAA] max-w-xl leading-relaxed m-0 font-mono">
            Real-time deterministic analysis: category categorization, monthly budget reconciliation, recurring subscription detection, explainable median outlier modeling, and 6-month trend trajectory.
          </p>
        </div>

        {/* Toggle & Refresh Actions */}
        <div className="flex flex-wrap items-center gap-4 border-t lg:border-t-0 lg:border-l border-[#202020] pt-4 lg:pt-0 lg:pl-8">
          <label className="flex items-center space-x-2 cursor-pointer select-none text-[10px] text-[#AAAAAA] uppercase">
            <input 
              type="checkbox"
              checked={includePersona}
              onChange={(e) => handleIncludePersonaChange(e.target.checked)}
              className="rounded-none border-[#404040] bg-black accent-white cursor-pointer h-4 w-4"
            />
            <span>Use Demo Persona Dataset</span>
          </label>

          <TargetLock>
            <button
              onClick={() => {
                setSelectedYear(null);
                setSelectedMonth(null);
                fetchAllInsights(() => false, null, null);
                if (onRefreshParent) onRefreshParent();
              }}
              disabled={loading}
              className="text-[10px] uppercase tracking-wider px-4 py-2 bg-white text-black font-bold hover:bg-[#AAAAAA] transition flex items-center gap-2 disabled:opacity-50 cursor-pointer shadow-sm"
              aria-label="Synchronize financial intelligence"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span>{loading ? 'Reconciling...' : 'Sync Intelligence'}</span>
            </button>
          </TargetLock>
        </div>
      </Card>

      {/* Error Banner */}
      {error && (
        <div className="border border-[#404040] bg-[#0A0A0A] p-4 text-xs text-[#AAAAAA] flex items-center gap-3">
          <AlertTriangle className="w-4 h-4 text-white shrink-0" />
          <span>Error loading intelligence: {error}</span>
        </div>
      )}

      {/* 1. Monthly Budget Analyzer Panel */}
      {budget && (
        <Card corners={10} cornerStroke={1.5} marker className="p-6 space-y-6">
          <div className="flex flex-wrap items-center justify-between border-b border-[#202020] pb-4 gap-2">
            <div className="flex items-center space-x-2">
              <Calendar className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                1. Monthly Budget Analyzer ({budget.statement_period?.label || `${budget.year}-${String(budget.month).padStart(2, '0')}`})
              </h3>
            </div>
            <div className="flex items-center gap-2">
              {budget.available_months && budget.available_months.length > 1 && (
                <div className="flex items-center gap-1.5 mr-2">
                  <span className="text-[9px] text-[#8A8A8A] uppercase">Period:</span>
                  <select
                    value={`${budget.year}-${budget.month}`}
                    onChange={(e) => {
                      const [y, m] = e.target.value.split('-').map(Number);
                      setSelectedYear(y);
                      setSelectedMonth(m);
                      fetchAllInsights(() => false, y, m);
                    }}
                    className="bg-black border border-[#404040] text-white text-[10px] px-2 py-0.5 uppercase font-mono cursor-pointer focus:border-white focus:outline-none"
                    aria-label="Select budget reporting period"
                  >
                    {budget.available_months.map((am) => (
                      <option key={`${am.year}-${am.month}`} value={`${am.year}-${am.month}`}>
                        {am.label} ({am.transaction_count} tx)
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {budget.overspending ? (
                <span className="border border-white bg-black px-2 py-0.5 text-[9px] uppercase font-bold text-white flex items-center gap-1.5 animate-pulse">
                  <span className="w-1.5 h-1.5 bg-white rounded-full animate-ping" />
                  Deficit Detected
                </span>
              ) : (
                <span className="border border-[#404040] bg-[#111111] px-2 py-0.5 text-[9px] uppercase text-[#AAAAAA]">
                  Surplus Inflow
                </span>
              )}
            </div>
          </div>

          {/* Partial Month Statement Banner */}
          {budget.data_coverage?.is_partial_month_likely && (
            <div className="border border-[#333333] bg-[#0A0A0A] p-3 text-[10px] text-[#AAAAAA] flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <span className="border border-white bg-black px-1.5 py-0.5 text-[8px] uppercase text-white font-bold">
                  PARTIAL-MONTH STATEMENT
                </span>
                <span>
                  Statement covers {budget.data_coverage.days_covered} days ({budget.data_coverage.start_date} to {budget.data_coverage.end_date}). Figures reflect observed totals only and are not extrapolated to full-month estimates.
                </span>
              </div>
            </div>
          )}

          {/* 4 Metric Summary: Operating Income, Total Inflows, Living Outflows, Operating Surplus */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="border border-[#202020] bg-[#0A0A0A] p-4">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">
                  {budget.operating_income_includes_probable
                    ? 'Operating income — includes probable credits'
                    : 'Operating Income'}
                </span>
                {budget.operating_income_status === 'PROBABLE' && (
                  <span className="border border-[#AAAAAA] bg-[#1a1a1a] px-1.5 py-0.2 text-[8px] uppercase text-white font-bold">
                    PROBABLE
                  </span>
                )}
                {budget.operating_income_status === 'CONFIRMED' && (
                  <span className="border border-white bg-black px-1.5 py-0.2 text-[8px] uppercase text-white font-bold">
                    CONFIRMED
                  </span>
                )}
              </div>
              <div className="text-xl font-bold text-white mt-1">
                {budget.has_data === false ? (
                  <span className="text-xs text-[#8A8A8A] font-bold tracking-wider">Unavailable / Insufficient data</span>
                ) : (
                  <CrypticText text={formatInr(budget.operating_income || budget.income)} triggerKey={budget.operating_income || budget.income} />
                )}
              </div>
              <span className="text-[9px] text-[#8A8A8A] block mt-1 uppercase">
                {budget.has_data === false ? (
                  'No transaction records for period'
                ) : budget.operating_income_includes_probable ? (
                  `${formatInr(budget.confirmed_operating_income || budget.earned_income || 0)} confirmed / ${formatInr(budget.probable_operating_income || budget.business_income || 0)} probable`
                ) : (
                  `Earned: ${formatInr(budget.earned_income || 0)} | Yield: ${formatInr(budget.investment_yield || 0)}`
                )}
              </span>
            </div>

            <div className="border border-[#202020] bg-[#0A0A0A] p-4">
              <span className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Total Inflows (All Credits)</span>
              <div className="text-xl font-bold text-white mt-1">
                {budget.has_data === false ? (
                  <span className="text-xs text-[#8A8A8A] font-bold tracking-wider">Unavailable / Insufficient data</span>
                ) : (
                  <CrypticText text={formatInr(budget.total_credits || budget.total_inflow || budget.income)} triggerKey={budget.total_credits} />
                )}
              </div>
              <span className="text-[9px] text-[#8A8A8A] block mt-1 uppercase">
                {budget.has_data === false ? (
                  'Zero credit records observed'
                ) : (
                  'Gross inflows (incl. transfers & capital)'
                )}
              </span>
            </div>

            <div className="border border-[#202020] bg-[#0A0A0A] p-4">
              <span className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Net Living Outflows</span>
              <div className="text-xl font-bold text-white mt-1">
                {budget.has_data === false ? (
                  <span className="text-xs text-[#8A8A8A] font-bold tracking-wider">Unavailable / Insufficient data</span>
                ) : (
                  <CrypticText text={formatInr(budget.net_living_expenses || budget.living_expenses_after_refunds || budget.expenses)} triggerKey={budget.net_living_expenses || budget.expenses} />
                )}
              </div>
              <span className="text-[9px] text-[#8A8A8A] block mt-1 uppercase">
                {budget.has_data === false ? (
                  'Zero debit records observed'
                ) : (
                  `Gross: ${formatInr(budget.gross_living_expenses || budget.living_expenses)} | Offset: -${formatInr(budget.same_period_matched_refunds || 0)}`
                )}
              </span>
            </div>

            <div className="border border-[#202020] bg-[#0A0A0A] p-4">
              <span className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Operating Surplus</span>
              <div className={`text-xl font-bold mt-1 ${parseFloat(budget.operating_surplus || budget.savings) < 0 ? 'text-[#AAAAAA]' : 'text-white'}`}>
                {budget.has_data === false ? (
                  <span className="text-xs text-[#8A8A8A] font-bold tracking-wider">Unavailable / Insufficient data</span>
                ) : (
                  <CrypticText text={formatInr(budget.operating_surplus || budget.savings)} triggerKey={budget.operating_surplus || budget.savings} />
                )}
              </div>
              <span className="text-[9px] text-[#8A8A8A] block mt-1 uppercase">
                {budget.has_data === false ? (
                  'Requires active income & expense data'
                ) : budget.operating_income_status === 'PROBABLE' ? (
                  `Includes ${formatInr(budget.business_income || budget.probable_operating_income)} probable income — verify`
                ) : (
                  'Operating Income - Net Living Outflows'
                )}
              </span>
            </div>
          </div>

          {/* Income Classification Transparency */}
          {budget.operating_income_status && budget.operating_income_status !== 'CONFIRMED' && (
            <div className="border border-[#404040] bg-[#0A0A0A] p-3 text-[10px] text-[#AAAAAA] space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="border border-white bg-black px-1.5 py-0.5 text-[8px] uppercase text-white font-bold">
                  {budget.operating_income_status === 'PROBABLE'
                    ? 'PROBABLE OPERATING INCOME — NEEDS REVIEW'
                    : budget.operating_income_status === 'UNCLASSIFIED'
                      ? 'INCOME UNCLASSIFIED'
                      : budget.operating_income_status === 'NO_CREDITS'
                        ? 'NO CREDITS OBSERVED'
                        : 'NO OPERATING INCOME OBSERVED'}
                </span>
                {parseFloat(budget.income_classification?.probable_operating_income || budget.business_income || 0) > 0 && (
                  <span className="uppercase text-white font-medium">
                    {budget.income_classification?.probable_income_transaction_count || 0} probable receipt(s)
                    {' '}· {formatInr(budget.income_classification?.probable_operating_income || budget.business_income)}
                  </span>
                )}
                {parseFloat(budget.income_classification?.unclassified_credit_amount || budget.credit_breakdown?.unclassified || 0) > 0 && (
                  <span className="uppercase text-[#888888]">
                    {budget.income_classification?.unclassified_credit_count || 0} unclassified credit(s)
                    {' '}· {formatInr(budget.income_classification?.unclassified_credit_amount || budget.credit_breakdown?.unclassified)}
                  </span>
                )}
              </div>
              <p className="leading-relaxed m-0">
                {budget.operating_income_status === 'PROBABLE' ? (
                  `${formatInr(budget.confirmed_operating_income || 0)} confirmed / ${formatInr(budget.probable_operating_income || budget.business_income || 0)} probable — verify the source of probable credits before relying on this figure.`
                ) : (
                  budget.income_classification?.note || 'Income classification is uncertain for this statement period.'
                )}
              </p>
              <p className="text-[9px] text-[#777777] uppercase m-0">
                Transfers, refunds, reimbursements and capital movements are excluded from operating income.
                Only probable business/freelance receipts are included, and they remain marked for review.
              </p>
            </div>
          )}

          {/* Account Cash Movement Bar */}
          <div className="border border-[#202020] bg-[#070707] px-4 py-2.5 flex flex-wrap items-center justify-between text-xs text-[#AAAAAA]">
            <div className="flex items-center space-x-2">
              <span className="text-[9px] uppercase font-bold tracking-wider text-white">Account Cash Movement:</span>
              {budget.has_data === false ? (
                <span className="text-[10px] text-[#8A8A8A] font-bold">Unavailable / Insufficient data</span>
              ) : (
                <>
                  <span className={`font-bold ${parseFloat(budget.total_account_cash_movement || budget.net_cashflow) >= 0 ? 'text-white' : 'text-[#888888]'}`}>
                    {formatInr(budget.total_account_cash_movement || budget.net_cashflow)}
                  </span>
                  <span className="text-[9px] text-[#8A8A8A] uppercase">
                    (Total Credits {formatInr(budget.total_credits)} - Total Debits {formatInr(budget.gross_debits || budget.gross_expenses)})
                  </span>
                </>
              )}
            </div>
            <div className="text-[9px] text-[#777777] uppercase">
              Distinct from Operating Surplus
            </div>
          </div>

          {/* Refund Matching Policy & Audit Callouts */}
          {(parseFloat(budget.cross_month_matched_refunds || 0) > 0 || parseFloat(budget.unmatched_refunds || 0) > 0 || parseFloat(budget.probable_same_period_refunds || 0) > 0) && (
            <div className="border border-[#333333] bg-[#0A0A0A] p-3 text-[10px] text-[#AAAAAA] space-y-1.5">
              {parseFloat(budget.probable_same_period_refunds || 0) > 0 && (
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="border border-[#AAAAAA] bg-[#1a1a1a] px-1.5 py-0.5 text-[8px] uppercase text-white font-bold">SUGGESTED ATTRIBUTION</span>
                    <span>Probable refunds: <strong className="text-white">{formatInr(budget.probable_same_period_refunds)}</strong> (Normalized merchant match identified, but excluded from automatic expense offsets pending manual verification).</span>
                  </div>
                </div>
              )}
              {parseFloat(budget.cross_month_matched_refunds || 0) > 0 && (
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="border border-white bg-black px-1.5 py-0.5 text-[8px] uppercase text-white font-bold">CROSS-MONTH ATTRIBUTION</span>
                    <span>Cross-month refunds: <strong className="text-white">{formatInr(budget.cross_month_matched_refunds)}</strong> (Attributed to original prior-period purchases; does not offset unrelated current expenses).</span>
                  </div>
                </div>
              )}
              {parseFloat(budget.unmatched_refunds || 0) > 0 && (
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="border border-[#666666] bg-[#111111] px-1.5 py-0.5 text-[8px] uppercase text-[#AAAAAA] font-bold">UNMATCHED / AMBIGUOUS</span>
                    <span>Unmatched or weak-evidence refunds: <strong className="text-white">{formatInr(budget.unmatched_refunds)}</strong> (Retained in total cash movement; not applied to living expenses).</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Credit Classification Breakdown — 9 Granular Categories */}
          {budget.credit_breakdown && (
            <div className="space-y-2 border border-[#202020] bg-black p-4">
              <div className="flex items-center justify-between border-b border-[#202020] pb-1.5">
                <span className="text-[10px] text-[#AAAAAA] uppercase tracking-wider font-bold">
                  Credit Inflow Taxonomy & Breakdown
                </span>
                <span className="text-[9px] text-[#8A8A8A] uppercase">
                  Single-Account Deterministic Classification
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-9 gap-2 pt-1 text-[11px]">
                <div className="border border-[#202020] bg-[#0A0A0A] p-2">
                  <span className="text-[8px] text-[#888888] uppercase block">Earned Income</span>
                  <span className="font-bold text-white block mt-0.5">{formatInr(budget.credit_breakdown.earned_income)}</span>
                </div>
                <div className="border border-[#202020] bg-[#0A0A0A] p-2">
                  <span className="text-[8px] text-[#888888] uppercase block">Probable Business</span>
                  <span className="font-bold text-white block mt-0.5">{formatInr(budget.credit_breakdown.business_income || 0)}</span>
                </div>
                <div className="border border-[#202020] bg-[#0A0A0A] p-2">
                  <span className="text-[8px] text-[#888888] uppercase block">Yield (FD/Div)</span>
                  <span className="font-bold text-white block mt-0.5">{formatInr(budget.credit_breakdown.investment_yield || budget.credit_breakdown.investment_income)}</span>
                </div>
                <div className="border border-[#202020] bg-[#0A0A0A] p-2">
                  <span className="text-[8px] text-[#888888] uppercase block">Capital (MF/Eq)</span>
                  <span className="font-bold text-white block mt-0.5">{formatInr(budget.credit_breakdown.capital_liquidation || 0)}</span>
                </div>
                <div className="border border-[#202020] bg-[#0A0A0A] p-2">
                  <span className="text-[8px] text-[#888888] uppercase block">Broker Transfer</span>
                  <span className="font-bold text-white block mt-0.5">{formatInr(budget.credit_breakdown.investment_transfers || 0)}</span>
                </div>
                <div className="border border-[#202020] bg-[#0A0A0A] p-2">
                  <span className="text-[8px] text-[#888888] uppercase block">Refunds</span>
                  <span className="font-bold text-white block mt-0.5">{formatInr(budget.credit_breakdown.refunds)}</span>
                </div>
                <div className="border border-[#202020] bg-[#0A0A0A] p-2">
                  <span className="text-[8px] text-[#888888] uppercase block">Self Transfers</span>
                  <span className="font-bold text-white block mt-0.5">{formatInr(budget.credit_breakdown.transfers)}</span>
                </div>
                <div className="border border-[#202020] bg-[#0A0A0A] p-2">
                  <span className="text-[8px] text-[#888888] uppercase block">Reimbursements</span>
                  <span className="font-bold text-white block mt-0.5">{formatInr(budget.credit_breakdown.reimbursements)}</span>
                </div>
                <div className="border border-[#202020] bg-[#0A0A0A] p-2">
                  <span className="text-[8px] text-[#888888] uppercase block">Unclassified</span>
                  <span className="font-bold text-white block mt-0.5">{formatInr(budget.credit_breakdown.unclassified)}</span>
                </div>
              </div>
            </div>
          )}

          {/* Refund Attribution Details (if refunds detected) */}
          {budget.refund_details && budget.refund_details.length > 0 && (
            <div className="border border-[#202020] bg-[#0A0A0A] p-4 space-y-3">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between border-b border-[#202020] pb-2 gap-1">
                <div>
                  <span className="text-[10px] text-white uppercase tracking-wider font-bold block">
                    Evidence-Aware Refund Attributions ({budget.refund_details.length})
                  </span>
                  <span className="text-[9px] text-[#888888]">
                    Strict Policy: Only CONFIRMED matches have allocation_status=APPLIED and reduce net living expenses. PROBABLE matches have allocation_status=SUGGESTED_NOT_APPLIED with allocated_amount=0.
                  </span>
                </div>
                <span className="text-[8px] uppercase tracking-wider text-[#8A8A8A] border border-[#333333] px-2 py-0.5">
                  Multi-Tier Evidence Verification
                </span>
              </div>
              <div className="space-y-3">
                {budget.refund_details.map((ref, idx) => {
                  const allocStatus = ref.allocation_status || 'NOT_ALLOCATED';
                  const isApplied = allocStatus === 'APPLIED';
                  const isSuggested = allocStatus === 'SUGGESTED_NOT_APPLIED';
                  const isNotAllocated = allocStatus === 'NOT_ALLOCATED';
                  const conf = ref.match_confidence || 'UNMATCHED';

                  return (
                    <div key={idx} className="border border-[#202020] bg-black p-3.5 space-y-2">
                      <div className="flex flex-wrap items-center justify-between text-[11px] gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-white font-bold">{safeCounterpartyName(ref.merchant)}</span>
                          <span className="text-[9px] text-[#888888] uppercase">[{ref.associated_category}]</span>

                          {/* Allocation Status & Confidence Badges */}
                          {isApplied && (
                            <span className="px-2 py-0.5 text-[8px] font-bold uppercase border border-white bg-black text-white flex items-center gap-1">
                              <ShieldCheck className="w-3 h-3" />
                              APPLIED ({conf})
                            </span>
                          )}
                          {isSuggested && (
                            <span className="px-2 py-0.5 text-[8px] font-bold uppercase border border-[#AAAAAA] bg-[#1a1a1a] text-white flex items-center gap-1">
                              <HelpCircle className="w-3 h-3 text-[#AAAAAA]" />
                              SUGGESTED — NOT APPLIED ({conf})
                            </span>
                          )}
                          {isNotAllocated && conf === 'WEAK' && (
                            <span className="px-2 py-0.5 text-[8px] font-bold uppercase border border-[#666666] bg-[#111111] text-[#AAAAAA] flex items-center gap-1">
                              <AlertTriangle className="w-3 h-3 text-[#AAAAAA]" />
                              NOT ALLOCATED (WEAK EVIDENCE)
                            </span>
                          )}
                          {isNotAllocated && conf !== 'WEAK' && (
                            <span className="px-2 py-0.5 text-[8px] font-bold uppercase border border-[#444444] bg-black text-[#777777]">
                              NOT ALLOCATED (UNMATCHED)
                            </span>
                          )}

                          {/* Temporal Relation Badge */}
                          {ref.temporal_relation && (
                            <span className="px-1.5 py-0.5 text-[8px] uppercase border border-[#333333] text-[#AAAAAA]">
                              {ref.temporal_relation === 'SAME_PERIOD' ? 'SAME PERIOD' : 'CROSS MONTH'}
                            </span>
                          )}
                        </div>
                        <div className="text-right">
                          <span className="text-white font-bold text-xs">+{formatInr(ref.amount)}</span>
                          {isApplied && (
                            <span className="text-[9px] text-white block font-bold">
                              Applied: {formatInr(ref.allocated_amount)}
                            </span>
                          )}
                          {isSuggested && (
                            <span className="text-[9px] text-[#AAAAAA] block">
                              Suggested: {formatInr(ref.suggested_amount)} (Unapplied)
                            </span>
                          )}
                          {isNotAllocated && (
                            <span className="text-[9px] text-[#777777] block">
                              Unallocated: {formatInr(ref.amount)}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Matching Evidence Tags */}
                      {ref.matching_evidence && ref.matching_evidence.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          <span className="text-[8px] text-[#8A8A8A] uppercase self-center mr-1">Evidence:</span>
                          {ref.matching_evidence.map((ev, eidx) => (
                            <span key={eidx} className="border border-[#333333] bg-[#0c0c0c] px-1.5 py-0.5 text-[8px] text-[#AAAAAA] font-mono">
                              {ev}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Matched original purchases trace */}
                      {ref.matched_purchases && ref.matched_purchases.length > 0 ? (
                        <div className="text-[10px] text-[#888888] bg-[#070707] p-2.5 space-y-1.5 border border-[#1a1a1a]">
                          <span className="text-[9px] uppercase tracking-wider text-[#AAAAAA] block font-bold">
                            {isApplied ? 'Applied Original Debit Attribution:' : 'Suggested Purchase Attribution (Review Recommended):'}
                          </span>
                          {ref.matched_purchases.map((alloc, aidx) => (
                            <div key={aidx} className="flex justify-between items-center text-[10px] border-b border-[#141414] pb-1 last:border-b-0 last:pb-0">
                              <div>
                                <span className="text-white font-medium">{safeCounterpartyName(alloc.merchant)}</span>
                                <span className="text-[#8A8A8A] ml-1.5">({alloc.purchase_date})</span>
                                <span className="text-[8px] text-[#888888] ml-1.5 uppercase">
                                  [{alloc.temporal_relation === 'SAME_PERIOD' ? 'Same Month' : 'Prior Month'}]
                                </span>
                                {alloc.matched_transaction_id && (
                                  <span className="text-[8px] text-[#555555] ml-1.5">
                                    [ID: {alloc.matched_transaction_id.slice(0, 8)}...]
                                  </span>
                                )}
                              </div>
                              <div className="text-right">
                                {alloc.allocation_status === 'APPLIED' ? (
                                  <span className="text-white font-bold">-{formatInr(alloc.allocated_amount)}</span>
                                ) : (
                                  <span className="text-[#AAAAAA]">Suggested: {formatInr(alloc.suggested_amount)}</span>
                                )}
                              </div>
                            </div>
                          ))}
                          {isSuggested && (
                            <p className="text-[8px] text-[#888888] italic m-0 pt-1">
                              Notice: Allocation status is SUGGESTED_NOT_APPLIED (allocated_amount=0). Confirmed net living expenses are not modified.
                            </p>
                          )}
                        </div>
                      ) : (
                        <div className="text-[9px] text-[#8A8A8A] italic bg-[#070707] p-2 border border-[#141414]">
                          {conf === 'WEAK'
                            ? 'Allocation status: NOT_ALLOCATED. Ambiguous purchase candidates detected or broad merchant token only. Kept unallocated to protect financial accuracy.'
                            : 'Allocation status: NOT_ALLOCATED. No matching debit purchase identified. Retained in total account cash movement without expense offset.'}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Category-wise spending breakdown */}
          <div className="space-y-3 pt-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">
                Category Spending Breakdown
              </span>
              <span className="text-[9px] text-[#888888] uppercase">
                {selectedCategory ? 'Click category to close inspector' : 'Click any category to inspect transactions'}
              </span>
            </div>
            {Object.keys(budget.category_spending || {}).length === 0 ? (
              <p className="text-xs text-[#8A8A8A]">No expense records found for this billing period.</p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {Object.entries(budget.category_spending).map(([cat, amt]) => {
                  const isSelected = selectedCategory === cat;
                  const isOther = cat.toLowerCase() === 'other';
                  const txList = budget.category_transactions?.[cat] || [];
                  const txCount = txList.length;
                  return (
                    <button
                      type="button"
                      key={cat}
                      onClick={() => setSelectedCategory(isSelected ? null : cat)}
                      className={`text-left p-3 border transition-all cursor-pointer font-mono ${
                        isSelected
                          ? 'border-white bg-[#161616] shadow-[0_0_15px_rgba(255,255,255,0.15)] ring-1 ring-white'
                          : isOther
                          ? 'border-[#404040] bg-[#0E0E0E] hover:border-white'
                          : 'border-[#202020] bg-[#0A0A0A] hover:border-white'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-[9px] uppercase text-[#AAAAAA] block truncate">
                          {cat === 'other' ? 'Other Discretionary' : cat.replace(/_/g, ' ')}
                        </span>
                        {txCount > 0 && (
                          <span className="text-[8px] text-[#777777] border border-[#252525] px-1 bg-black">
                            {txCount}
                          </span>
                        )}
                      </div>
                      <span className="text-sm font-bold text-white block mt-0.5">{formatInr(amt)}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {/* Category Transaction Inspector Drawer / Panel */}
            {selectedCategory && (
              <div className="border border-white/60 bg-[#070707] p-4 mt-3 space-y-3 font-mono">
                <div className="flex items-center justify-between border-b border-[#202020] pb-2">
                  <div className="flex items-center gap-2">
                    <span className="border border-white bg-black px-1.5 py-0.2 text-[8px] uppercase tracking-widest text-white font-bold">
                      INSPECTOR
                    </span>
                    <span className="text-xs font-bold text-white uppercase tracking-wider">
                      Transactions in {selectedCategory === 'other' ? 'Other Discretionary' : selectedCategory.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedCategory(null)}
                    className="text-[9px] text-[#888888] hover:text-white uppercase tracking-wider cursor-pointer"
                  >
                    Close [×]
                  </button>
                </div>

                {selectedCategory === 'other' && (
                  <p className="text-[10px] text-[#AAAAAA] bg-[#0F0F0F] p-2.5 border border-[#222222] m-0 leading-relaxed">
                    <strong>Audit Notice:</strong> Transactions in &quot;Other&quot; represent debits that did not match recognized merchant or utility patterns. They are verified actual outflows and are 100% reconciled in the budget. Use the Audit Ledger to reclassify them if necessary.
                  </p>
                )}

                {(() => {
                  const txs = budget.category_transactions?.[selectedCategory] || [];
                  if (txs.length === 0) {
                    return (
                      <p className="text-xs text-[#888888] py-2 m-0">
                        No individual transactions found in active statement period for this category.
                      </p>
                    );
                  }
                  return (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-[11px] font-mono">
                        <thead>
                          <tr className="border-b border-[#202020] text-[#777777] uppercase text-[8px] tracking-wider">
                            <th className="py-1.5 px-2">Date</th>
                            <th className="py-1.5 px-2">Merchant / Counterparty</th>
                            <th className="py-1.5 px-2">Category Label</th>
                            <th className="py-1.5 px-2 text-right">Amount</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#151515]">
                          {txs.map((t, tidx) => (
                            <tr key={t.id || tidx} className="hover:bg-[#121212]">
                              <td className="py-2 px-2 text-[#888888] whitespace-nowrap">{t.date}</td>
                              <td className="py-2 px-2 text-white font-medium">{t.merchant}</td>
                              <td className="py-2 px-2">
                                <span className="border border-[#2a2a2a] bg-[#111111] text-[#AAAAAA] px-1.5 py-0.2 text-[8px] uppercase">
                                  {t.category || selectedCategory}
                                </span>
                              </td>
                              <td className="py-2 px-2 text-right text-white font-bold whitespace-nowrap">
                                -{formatInr(t.amount)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                })()}
              </div>
            )}
          </div>

          {/* Single-Account Scope Limitation Notice */}
          <div className="border border-[#202020] bg-[#0A0A0A] p-3 text-[10px] text-[#888888] flex items-center space-x-2">
            <Radio className="w-3.5 h-3.5 text-white shrink-0" />
            <span>
              <strong>Scope Boundary:</strong> {budget.single_account_limitation_note || 'Single-account analysis: External transfers reflect unlinked inflows/outflows without visibility into counterparty balances.'}
            </span>
          </div>
        </Card>
      )}

      {/* 2-Column Grid: Subscriptions & Unusual Spending */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* 2. Subscription Detector */}
        <Card corners={8} cornerStroke={1.5} marker className="p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-[#202020] pb-3">
            <div className="flex items-center space-x-2">
              <Repeat className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                2. Subscription Traps ({subscriptions.length})
              </h3>
            </div>
            <span className="text-[9px] uppercase text-[#AAAAAA]">Auto-Debit Monitor</span>
          </div>

          {subscriptions.length === 0 ? (
            <div className="py-8 text-center text-[#8A8A8A] text-xs">
              Zero recurring subscriptions identified in session journal.
            </div>
          ) : (
            <div className="space-y-3">
              {subscriptions.map((sub, idx) => {
                const isExpanded = expandedSubIdx === idx;
                const conf = sub.confidence || 'PROBABLE';
                const cadence = sub.cadence || 'monthly';
                const pType = sub.payment_type ? sub.payment_type.replace(/_/g, ' ') : 'subscription';
                const variation = sub.amount_variation || 'fixed';
                const monthlyCost = sub.estimated_monthly_cost || sub.monthly_estimate;
                const annualCost = sub.estimated_annual_cost || sub.yearly_estimate;
                const occCount = sub.occurrence_count || (sub.candidates ? 2 : 1);

                return (
                  <div key={idx} className="border border-[#202020] bg-[#0A0A0A] p-3.5 space-y-2.5 hover:border-[#505050] transition-colors">
                    <div className="flex items-start justify-between">
                      <div className="space-y-1">
                        <div className="flex items-center space-x-2">
                          <span className="text-xs font-bold text-white uppercase tracking-wider block">
                            {safeCounterpartyName(sub.merchant || sub.identifier)}
                          </span>
                          {sub.canonical_label && sub.canonical_label !== safeCounterpartyName(sub.merchant || sub.identifier) && (
                            <span className="border border-[#333333] bg-[#141414] text-[8px] text-[#888888] px-1.5 py-0.2">
                              {safeCounterpartyName(sub.canonical_label)}
                            </span>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                          {/* Payment Classification Badge */}
                          <span className="border border-[#404040] bg-[#111111] text-zinc-300 text-[8px] uppercase px-1.5 py-0.5 tracking-wider">
                            {pType}
                          </span>

                          {/* Confidence Badge */}
                          {conf === 'CONFIRMED' ? (
                            <span className="border border-emerald-500/60 bg-emerald-950/40 text-emerald-300 text-[8px] uppercase px-1.5 py-0.5 font-bold tracking-wider">
                              CONFIRMED ({occCount} DEBITS)
                            </span>
                          ) : conf === 'PROBABLE' ? (
                            <span className="border border-amber-500/60 bg-amber-950/40 text-amber-300 text-[8px] uppercase px-1.5 py-0.5 font-bold tracking-wider">
                              PROBABLE ({occCount} DEBITS)
                            </span>
                          ) : (
                            <span className="border border-zinc-600 bg-zinc-900 text-zinc-300 text-[8px] uppercase px-1.5 py-0.5 font-bold tracking-wider">
                              POSSIBLE / NEEDS VERIFICATION ({occCount} DEBIT{occCount > 1 ? 'S' : ''})
                            </span>
                          )}

                          {/* Cadence Badge */}
                          <span className="border border-[#303030] bg-[#0E0E0E] text-[#888888] text-[8px] uppercase px-1.5 py-0.5">
                            {cadence}
                          </span>

                          {/* Variation Badge */}
                          <span className="border border-[#252525] text-[#777777] text-[8px] uppercase px-1.5 py-0.5">
                            {variation.replace('_', ' ')}
                          </span>
                        </div>
                      </div>

                      <div className="text-right shrink-0">
                        {monthlyCost !== null && monthlyCost !== undefined ? (
                          <>
                            <span className="text-sm font-bold text-white block">
                              {formatInr(monthlyCost)}
                            </span>
                            <span className="text-[9px] text-[#AAAAAA] uppercase block">
                              / Month
                            </span>
                            <span className="text-[8px] text-[#8A8A8A] block">
                              Annual: {formatInr(annualCost)}
                            </span>
                          </>
                        ) : (
                          <>
                            <span className="text-xs font-bold text-amber-300 block">
                              {formatInr(sub.observed_total_spend || 0)}
                            </span>
                            <span className="text-[9px] text-[#AAAAAA] uppercase block">
                              Observed Total
                            </span>
                            <span className="text-[8px] text-zinc-500 block italic">
                              Annual Withheld
                            </span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Occurrence count & estimated next date */}
                    <div className="flex items-center justify-between text-[8px] text-[#777777] border-t border-[#181818] pt-1.5">
                      <span>
                        History: <strong className="text-[#AAAAAA]">{occCount} debit{occCount > 1 ? 's' : ''}</strong>
                      </span>
                      {sub.estimated_next_date && (
                        <span className="flex items-center gap-1.5">
                          <span>Next est:</span>
                          <strong className="text-[#AAAAAA]">{sub.estimated_next_date}</strong>
                          {sub.is_past_projection && (
                            <span className="border border-zinc-600 bg-zinc-900 text-zinc-300 text-[7px] uppercase px-1 py-0.2 font-bold">
                              {sub.projection_status === 'STALE_HISTORY' ? 'STALE STATEMENT' : 'CYCLE ELAPSED (NEXT STATEMENT PENDING)'}
                            </span>
                          )}
                        </span>
                      )}
                    </div>

                    {/* Evidence & Transactions expandable section */}
                    {((sub.evidence && sub.evidence.length > 0) || (sub.transaction_dates && sub.transaction_dates.length > 0)) && (
                      <div className="pt-0.5">
                        <button
                          type="button"
                          onClick={() => setExpandedSubIdx(isExpanded ? null : idx)}
                          className="flex items-center space-x-1 text-[8px] uppercase tracking-wider text-[#777777] hover:text-white transition-colors"
                        >
                          <span>{isExpanded ? 'Hide Evidence Journal' : 'View Evidence & History'}</span>
                          {isExpanded ? <ChevronUp className="w-2.5 h-2.5" /> : <ChevronDown className="w-2.5 h-2.5" />}
                        </button>

                        {isExpanded && (
                          <div className="mt-2 p-2.5 border border-[#222222] bg-[#070707] space-y-2 text-[8px]">
                            {sub.evidence && sub.evidence.length > 0 && (
                              <div className="space-y-1">
                                <span className="text-white uppercase font-bold block">
                                  Evidence Rationale:
                                </span>
                                <ul className="list-disc pl-3.5 space-y-0.5 text-[#888888]">
                                  {sub.evidence.map((ev, ei) => (
                                    <li key={ei}>{ev}</li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {sub.transaction_dates && sub.transaction_dates.length > 0 && (
                              <div className="pt-1.5 border-t border-[#161616]">
                                <span className="text-white uppercase font-bold block mb-1">
                                  Historical Debits:
                                </span>
                                <div className="flex flex-wrap gap-1">
                                  {sub.transaction_dates.map((d, di) => (
                                    <span key={di} className="border border-[#252525] bg-black px-1.5 py-0.5 text-[#999999]">
                                      {d}: ₹{sub.transaction_amounts && sub.transaction_amounts[di] ? sub.transaction_amounts[di] : monthlyCost}
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
          )}
        </Card>

        {/* 3. Unusual Spending Detector with Warning Pulse on Threats */}
        <Card
          corners={8}
          cornerStroke={1.5}
          marker
          className={`p-6 space-y-4 ${
            unusual.length > 0 ? 'animate-warning-pulse' : ''
          }`}
        >
          <div className="flex items-center justify-between border-b border-[#202020] pb-3">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                3. Unusual Outlier Spikes ({unusual.length})
              </h3>
            </div>
            <span className="text-[9px] uppercase border border-[#404040] bg-[#111111] px-1.5 py-0.2 text-[#AAAAAA]">
              Median 3× Baseline
            </span>
          </div>

          {unusual.length === 0 ? (
            <div className="py-8 text-center text-[#8A8A8A] text-xs flex flex-col items-center justify-center space-y-2">
              <CheckCircle2 className="w-6 h-6 text-[#767676]" />
              <span>Zero unusual spikes or duplicate transactions detected.</span>
            </div>
          ) : (
            <div className="space-y-3">
              {unusual.map((item, idx) => (
                <div key={idx} className="border border-white/60 bg-[#0A0A0A] p-3.5 space-y-2 shadow-[0_0_15px_rgba(255,255,255,0.08)]">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 bg-white rounded-full animate-ping" />
                        <span className="text-xs font-bold text-white block uppercase">{safeCounterpartyName(item.merchant)}</span>
                      </div>
                      <span className="text-[9px] text-[#AAAAAA] block mt-0.5">{item.date}</span>
                    </div>
                    <div className="text-right">
                      <span className="text-sm font-bold text-white block">{formatInr(item.amount)}</span>
                      <span className="text-[8px] uppercase font-bold text-white border border-white bg-black px-1.5 py-0.2 tracking-wider">
                        {item.reason === 'large_amount' ? 'LARGE OUTLIER' : 'DUPLICATE ALERT'}
                      </span>
                    </div>
                  </div>
                  {item.baseline && item.threshold && (
                    <div className="text-[10px] text-[#AAAAAA] border-t border-[#202020] pt-1.5 flex justify-between">
                      <span>Peer Median: {formatInr(item.baseline)}</span>
                      <span>Trigger Threshold: {formatInr(item.threshold)}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

      </div>

      {/* 4. Spending Patterns & Category Trends */}
      {patterns && patterns.category_trends && (
        <Card corners={10} cornerStroke={1.5} marker className="p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-[#202020] pb-3">
            <div className="flex items-center space-x-2">
              <TrendingUp className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                4. Multi-Month Trend Radar (6 Months Trajectory)
              </h3>
            </div>
            <span className="text-[9px] uppercase text-[#AAAAAA]">Historical Drift</span>
          </div>

          {Object.keys(patterns.category_trends).length === 0 ? (
            <div className="py-6 text-center text-[#8A8A8A] text-xs">
              Insufficient historical multi-month statements to compute velocity trends.
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {Object.entries(patterns.category_trends).map(([cat, trend]) => (
                <div key={cat} className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1 hover:border-white transition-colors">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase text-white">{cat}</span>
                    {trend.trend === 'increase' ? (
                      <ArrowUpRight className="w-3.5 h-3.5 text-white" />
                    ) : (
                      <ArrowDownLeft className="w-3.5 h-3.5 text-[#AAAAAA]" />
                    )}
                  </div>
                  <div className="text-sm font-bold text-white">
                    {trend.pct_change > 0 ? `+${trend.pct_change}%` : `${trend.pct_change}%`}
                  </div>
                  <span className="text-[9px] uppercase text-[#AAAAAA] block">
                    {trend.trend === 'increase' ? 'Expense Acceleration' : 'Expense Contraction'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* 5. Scrubbed Categorized Transactions Summary */}
      <Card corners={10} cornerStroke={1.5} marker className="p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-[#202020] pb-3">
          <div className="flex items-center space-x-2">
            <Layers className="w-4 h-4 text-white" />
            <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
              5. Category Normalization Journal ({categorized.length} Records)
            </h3>
          </div>
          <span className="text-[9px] uppercase text-[#AAAAAA]">Rule-Based Classification</span>
        </div>

        {categorized.length === 0 ? (
          <div className="py-6 text-center text-[#8A8A8A] text-xs">
            No transactions currently in database for this session. Use Privacy Inspector to upload and persist a bank statement.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="border-b border-[#202020] text-[#AAAAAA] uppercase text-[9px] tracking-widest">
                  <th className="py-2.5 px-3">Date</th>
                  <th className="py-2.5 px-3">Merchant</th>
                  <th className="py-2.5 px-3">Category</th>
                  <th className="py-2.5 px-3">Type</th>
                  <th className="py-2.5 px-3 text-right">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#161616]">
                {categorized.slice(0, 10).map((tx, idx) => (
                  <tr key={tx.id} className={idx % 2 === 0 ? 'bg-black/60 hover:bg-[#111111]' : 'bg-[#0A0A0A]/60 hover:bg-[#111111]'}>
                    <td className="py-2.5 px-3 text-[#AAAAAA]">{tx.date}</td>
                    <td className="py-2.5 px-3 text-white font-bold">{safeCounterpartyName(tx.merchant)}</td>
                    <td className="py-2.5 px-3">
                      <span className="border border-[#404040] bg-[#111111] px-1.5 py-0.5 text-[8px] uppercase text-[#AAAAAA]">
                        {tx.category}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-[#AAAAAA]">{tx.type}</td>
                    <td className="py-2.5 px-3 text-right text-white font-bold">{formatInr(tx.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {categorized.length > 10 && (
              <div className="text-[9px] text-[#AAAAAA] text-center py-2.5 border-t border-[#202020] uppercase tracking-wider">
                Showing top 10 of {categorized.length} transactions
              </div>
            )}
          </div>
        )}
      </Card>

    </div>
  );
}
