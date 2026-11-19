import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Scale,
  Calendar,
  Clock,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Receipt,
  CheckCircle2,
  XCircle,
  HelpCircle,
  ArrowRight,
  Sliders,
  DollarSign,
  Activity,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  RefreshCw,
  ExternalLink,
  Flame,
  Layers,
  FileText
} from 'lucide-react';
import { Card } from './ui/Card';
import CrypticText from './effects/CrypticText';
import OdometerNumber from './effects/OdometerNumber';
import api from '../services/api';
import { safeCounterpartyName } from '../utils/display';

const COMMITMENT_TYPES = [
  { id: 'no_cost_emi', label: 'No-Cost EMI (0% Nominal)' },
  { id: 'large_purchase', label: 'Lump Sum Purchase' },
  { id: 'regular_emi', label: 'Standard Loan / EMI' },
  { id: 'subscription', label: 'Recurring Subscription' },
];

export default function CommitmentStressTest({
  sessionId,
  discretionaryBuffer = 14000,
  currentBalance = null,
  includePersona = false,
  onNavigateToLedger,
}) {
  // --- Form State ---
  const [itemName, setItemName] = useState('Flagship Smartphone');
  const [commitmentType, setCommitmentType] = useState('no_cost_emi');
  const [price, setPrice] = useState(65000);
  const [downPayment, setDownPayment] = useState(0);
  const [tenure, setTenure] = useState(6);
  const [nominalApr, setNominalApr] = useState(0.0);
  const [monthlyFee, setMonthlyFee] = useState(199.0);
  const [upfrontFee, setUpfrontFee] = useState(0.0);
  const [delayDays, setDelayDays] = useState(30); // Judgment flip delay
  const [discretionaryReductionPct, setDiscretionaryReductionPct] = useState(0);

  // --- Engine Results ---
  const [loading, setLoading] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [error, setError] = useState(null);

  // --- Evidence Drawer State ---
  const [showEvidence, setShowEvidence] = useState(false);
  const [activeEvidenceTab, setActiveEvidenceTab] = useState('ALL');

  // --- AI Explanation State ---
  const [aiLoading, setAiLoading] = useState(false);
  const [aiExplanation, setAiExplanation] = useState(null);

  // --- Human Correction State ---
  const [correctingTxId, setCorrectingTxId] = useState(null);
  const [correctionSuccessMsg, setCorrectionSuccessMsg] = useState(null);

  // --- Fetch Stress Test Results ---
  const fetchStressTest = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.runCommitmentStressTest(
        {
          item_name: itemName,
          price: Number(price) || 0,
          commitment_type: commitmentType,
          down_payment: Number(downPayment) || 0,
          tenure_months: Number(tenure) || 6,
          nominal_apr: Number(nominalApr) || 0.0,
          monthly_processing_fee: commitmentType === 'large_purchase' ? 0.0 : Number(monthlyFee) || 0.0,
          upfront_processing_fee: Number(upfrontFee) || 0.0,
          delay_days: Number(delayDays) || 0,
          discretionary_reduction_pct: Number(discretionaryReductionPct) || 0,
          custom_liquid_balance: currentBalance !== null ? Number(currentBalance) : null,
          include_persona: includePersona,
        },
        sessionId
      );
      setTestResult(res);
      // Reset AI explanation when inputs change
      setAiExplanation(null);
    } catch (err) {
      console.error('Commitment Stress Test failed:', err);
      setError(err?.response?.data?.error || err?.message || 'Calculation engine unreachable.');
    } finally {
      setLoading(false);
    }
  }, [
    sessionId,
    itemName,
    price,
    commitmentType,
    downPayment,
    tenure,
    nominalApr,
    monthlyFee,
    upfrontFee,
    delayDays,
    discretionaryReductionPct,
    currentBalance,
    includePersona,
  ]);

  // Initial and reactive calculation
  useEffect(() => {
    fetchStressTest();
  }, [fetchStressTest]);

  // --- Request AI Explanation ---
  const handleRequestAiExplanation = async () => {
    if (!testResult || !sessionId) return;
    setAiLoading(true);
    try {
      const res = await api.explainCommitmentStressTest(testResult, sessionId);
      setAiExplanation(res);
    } catch (err) {
      console.error('Failed to generate AI explanation:', err);
    } finally {
      setAiLoading(false);
    }
  };

  // --- Human Correction Handler ---
  const handleCorrectTransaction = async (txId, isTransfer = true, newCategory = null) => {
    setCorrectingTxId(txId);
    setCorrectionSuccessMsg(null);
    try {
      const res = await api.correctTransaction(
        txId,
        {
          is_transfer: isTransfer,
          new_category: newCategory,
          notes: 'Corrected via Commitment Stress Test Evidence Panel',
        },
        sessionId
      );
      setCorrectionSuccessMsg(`Transaction updated: ${res.current_category}`);
      // Re-run stress test with updated records
      fetchStressTest();
      setTimeout(() => setCorrectionSuccessMsg(null), 4000);
    } catch (err) {
      console.error('Correction failed:', err);
    } finally {
      setCorrectingTxId(null);
    }
  };

  // Safe fallbacks for data rendering
  const verdict = testResult?.overall_verdict || 'INSUFFICIENT DATA';
  const scenA = testResult?.scenario_a_buy_now || {};
  const scenB = testResult?.scenario_b_emi || {};
  const scenC = testResult?.scenario_c_wait || {};
  const baseline = testResult?.baseline || {};
  const flip = testResult?.judgment_flip || {};
  const alternatives = testResult?.what_would_make_this_safe || [];

  // Determine badge styling
  const getVerdictStyle = (v) => {
    switch (v) {
      case 'SAFE':
        return 'border-white bg-white text-black font-bold';
      case 'CONDITIONAL':
        return 'border-[#D4AF37] bg-black text-[#D4AF37] font-bold';
      case 'NOT SAFE':
        return 'border-white bg-black text-white underline decoration-white font-bold';
      default:
        return 'border-[#555555] bg-black text-[#AAAAAA]';
    }
  };

  return (
    <div className="space-y-8 font-mono">
      {/* 1. Header & Architectural Manifesto */}
      <Card corners={12} cornerStroke={2} marker className="p-6">
        <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4 border-b border-[#202020] pb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="border border-white bg-black px-2 py-0.5 text-[9px] uppercase text-white font-bold tracking-widest">
                SYS_05 • STRESS TEST
              </span>
              <h2 className="text-lg font-bold uppercase tracking-wider text-white m-0">
                Commitment Stress Test & Judgment Flip
              </h2>
            </div>
            <p className="text-xs text-[#AAAAAA] mt-1.5 m-0 leading-relaxed max-w-3xl">
              <strong className="text-white">"ArthaShield doesn't just tell you whether you can afford something. It shows you what could go wrong, when it could happen, and exactly what would change the decision."</strong>
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[10px] text-[#888888] uppercase">Engine Status:</span>
            <span className="border border-[#333333] bg-[#0A0A0A] px-2 py-0.5 text-[9px] text-white flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse motion-reduce:animate-none" />
              Deterministic Verified
            </span>
          </div>
        </div>

        {/* Central User Question */}
        <div className="mt-4 p-3 bg-[#0A0A0A] border border-[#202020] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Scale className="w-4 h-4 text-white shrink-0" />
            <span className="text-xs text-white">
              Evaluating: <span className="font-bold underline decoration-white">{itemName}</span> (₹{Number(price).toLocaleString('en-IN')})
            </span>
          </div>
          <span className="text-[10px] text-[#AAAAAA] uppercase tracking-wider hidden sm:inline">
            What happens to my finances if I commit?
          </span>
        </div>
      </Card>

      {/* 2. Interactive Inputs & Judgment Flip Slider */}
      <Card corners={10} cornerStroke={1.5} className="p-6 space-y-6">
        <div className="flex items-center justify-between border-b border-[#202020] pb-3">
          <div className="flex items-center gap-2">
            <Sliders className="w-4 h-4 text-white" />
            <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
              1. Commitment Parameters & Assumptions
            </h3>
          </div>
          <button
            type="button"
            onClick={fetchStressTest}
            disabled={loading}
            className="text-[10px] text-[#AAAAAA] hover:text-white flex items-center gap-1 transition-colors cursor-pointer"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            Recalculate
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
          {/* Item Name */}
          <div className="space-y-1.5">
            <label className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Commitment / Item Name</label>
            <input
              type="text"
              value={itemName}
              onChange={(e) => setItemName(e.target.value)}
              className="w-full bg-[#050505] border border-[#202020] px-3 py-2 text-white text-xs focus:border-white focus:outline-none transition-colors"
              placeholder="e.g. MacBook Pro, Phone, Rent"
            />
          </div>

          {/* Commitment Type */}
          <div className="space-y-1.5">
            <label className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Structure</label>
            <select
              value={commitmentType}
              onChange={(e) => setCommitmentType(e.target.value)}
              className="w-full bg-[#050505] border border-[#202020] px-3 py-2 text-white text-xs focus:border-white focus:outline-none transition-colors"
            >
              {COMMITMENT_TYPES.map((t) => (
                <option key={t.id} value={t.id} className="bg-black text-white">
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          {/* Price */}
          <div className="space-y-1.5">
            <label className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">
              Total Amount (₹{Number(price).toLocaleString('en-IN')})
            </label>
            <input
              type="number"
              value={price}
              onChange={(e) => setPrice(Math.max(0, Number(e.target.value)))}
              className="w-full bg-[#050505] border border-[#202020] px-3 py-2 text-white text-xs focus:border-white focus:outline-none transition-colors"
              min="0"
              step="1000"
            />
          </div>

          {/* Down Payment */}
          <div className="space-y-1.5">
            <label className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Down Payment (₹)</label>
            <input
              type="number"
              value={downPayment}
              onChange={(e) => setDownPayment(Math.max(0, Number(e.target.value)))}
              className="w-full bg-[#050505] border border-[#202020] px-3 py-2 text-white text-xs focus:border-white focus:outline-none transition-colors"
              min="0"
              step="1000"
            />
          </div>

          {/* Tenure */}
          {commitmentType !== 'large_purchase' && (
            <div className="space-y-1.5">
              <label className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Tenure (Months)</label>
              <select
                value={tenure}
                onChange={(e) => setTenure(Number(e.target.value))}
                className="w-full bg-[#050505] border border-[#202020] px-3 py-2 text-white text-xs focus:border-white focus:outline-none transition-colors"
              >
                {[3, 6, 9, 12, 18, 24, 36].map((m) => (
                  <option key={m} value={m} className="bg-black text-white">
                    {m} Months
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Monthly Processing / Convenience Fee */}
          {commitmentType === 'no_cost_emi' && (
            <div className="space-y-1.5">
              <label className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">
                Monthly Conv. Fee + GST (₹)
              </label>
              <input
                type="number"
                value={monthlyFee}
                onChange={(e) => setMonthlyFee(Math.max(0, Number(e.target.value)))}
                className="w-full bg-[#050505] border border-[#202020] px-3 py-2 text-white text-xs focus:border-white focus:outline-none transition-colors"
                step="50"
              />
            </div>
          )}

          {/* Nominal APR for Standard Loan */}
          {commitmentType === 'regular_emi' && (
            <div className="space-y-1.5">
              <label className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Advertised APR (%)</label>
              <input
                type="number"
                value={nominalApr}
                onChange={(e) => setNominalApr(Math.max(0, Number(e.target.value)))}
                className="w-full bg-[#050505] border border-[#202020] px-3 py-2 text-white text-xs focus:border-white focus:outline-none transition-colors"
                step="0.5"
              />
            </div>
          )}
        </div>

        {/* --- THE SIGNATURE EXPERIENCE: JUDGMENT FLIP SLIDER --- */}
        <div className="border border-white/40 bg-[#050505] p-5 space-y-4">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
            <div>
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-white" />
                <span className="text-xs font-bold uppercase tracking-widest text-white">
                  Judgment Flip Delay Controller: <span className="underline">{delayDays} Days</span>
                </span>
              </div>
              <p className="text-[11px] text-[#AAAAAA] mt-1 m-0">
                Drag slider to test when waiting accumulates enough net cash-flow to safely absorb the commitment.
              </p>
            </div>

            {flip?.safe_flip_days && (
              <span className="border border-white bg-black px-2.5 py-1 text-[10px] text-white font-bold uppercase tracking-wider">
                Safe Threshold: {flip.safe_flip_days} Days
              </span>
            )}
          </div>

          <div className="space-y-2">
            <input
              type="range"
              min="0"
              max="90"
              step="5"
              value={delayDays}
              onChange={(e) => setDelayDays(Number(e.target.value))}
              aria-label="Judgment flip delay in days"
              className="w-full accent-white cursor-pointer"
            />
            <div className="flex justify-between text-[9px] text-[#666666] uppercase">
              <span>0 Days (Immediate)</span>
              <span>15 Days</span>
              <span>30 Days (1 Month)</span>
              <span>45 Days</span>
              <span>60 Days (2 Months)</span>
              <span>90 Days (Quarter)</span>
            </div>
          </div>

          {/* Real-time Judgment Flip Alert Banner */}
          {flip?.flips_to_safe && (
            <div className="border border-white bg-black p-3.5 flex items-start sm:items-center justify-between gap-3 animate-pulse motion-reduce:animate-none">
              <div className="flex items-center gap-2.5 text-xs text-white">
                <Sparkles className="w-4 h-4 text-white shrink-0" />
                <span>
                  <strong>JUDGMENT FLIP ACTIVATED:</strong> Waiting {delayDays} days accumulates ₹{Number(scenC.accumulated_savings || 0).toLocaleString('en-IN')} in savings, flipping your verdict from <strong>{testResult?.overall_verdict}</strong> to <strong className="bg-white text-black px-1.5 py-0.2">SAFE</strong>!
                </span>
              </div>
              <span className="text-[9px] uppercase border border-white px-2 py-0.5 text-white font-bold shrink-0">
                FLIP DETECTED
              </span>
            </div>
          )}
        </div>
      </Card>

      {/* 3. The Central Decision Card (Commitment Safety Card) */}
      <Card corners={12} cornerStroke={2} marker className="p-6 space-y-6">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 border-b border-[#202020] pb-4">
          <div>
            <span className="text-[9px] uppercase tracking-widest text-[#AAAAAA] block">
              DETERMINISTIC VERDICT
            </span>
            <div className="flex items-center gap-3 mt-1">
              <span className={`text-sm sm:text-base px-3 py-1 uppercase tracking-widest ${getVerdictStyle(verdict)}`}>
                {verdict}
              </span>
              <span className="text-xs text-[#AAAAAA] font-mono">
                {testResult?.primary_reason}
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setShowEvidence((prev) => !prev)}
            className="border border-white bg-black hover:bg-white hover:text-black px-4 py-2 text-[10px] font-bold uppercase tracking-widest transition-colors flex items-center gap-2 cursor-pointer shrink-0"
          >
            <Receipt className="w-3.5 h-3.5" />
            {showEvidence ? 'Hide Supporting Evidence' : 'Show Me The Evidence'}
          </button>
        </div>

        {/* 10 Required Metric Indicators */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 text-xs">
          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">1. Proposed Purchase</span>
            <span className="text-sm font-bold text-white block">₹{Number(price).toLocaleString('en-IN')}</span>
          </div>

          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">2. Payment Method</span>
            <span className="text-xs font-bold text-white block capitalize">
              {commitmentType.replace(/_/g, ' ')}
            </span>
          </div>

          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">3. Monthly Outflow</span>
            <span className="text-sm font-bold text-white block">
              ₹{Number(scenB.effective_monthly_commitment || 0).toLocaleString('en-IN')}
            </span>
          </div>

          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">4. Liquid Balance</span>
            <span className="text-sm font-bold text-white block">
              ₹{Number(baseline.current_liquid_balance || 0).toLocaleString('en-IN')}
            </span>
          </div>

          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">5. Existing Commitments</span>
            <span className="text-sm font-bold text-white block">
              ₹{Number(baseline.existing_fixed_obligations || 0).toLocaleString('en-IN')}/mo
            </span>
          </div>

          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">6. Post-Commitment Buffer</span>
            <span className="text-sm font-bold text-white block">
              ₹{Number(scenB.remaining_safety_buffer || 0).toLocaleString('en-IN')}
            </span>
          </div>

          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">7. Runway (Before → After)</span>
            <span className="text-xs font-bold text-white block">
              {baseline.baseline_runway_months || 0}m → {scenB.emergency_runway_months || 0}m
            </span>
          </div>

          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">8. Projected Breach Day</span>
            <span className="text-xs font-bold text-white block">
              {scenB.first_breach_day ? `Day ${scenB.first_breach_day}` : 'None in 90 Days'}
            </span>
          </div>

          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">9. Effective XIRR Cost</span>
            <span className="text-sm font-bold text-white block">
              {scenB.effective_annual_cost_pct ? `${scenB.effective_annual_cost_pct}%` : '0.00%'}
            </span>
          </div>

          <div className="border border-[#202020] bg-[#0A0A0A] p-3 space-y-1">
            <span className="text-[9px] uppercase text-[#888888] block">10. Buffer Eaten</span>
            <span className="text-sm font-bold text-white block">
              {scenB.buffer_consumed_pct || 0}%
            </span>
          </div>
        </div>
      </Card>

      {/* 4. Scenario Comparison Matrix (Scenario A vs B vs C) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* SCENARIO A: BUY NOW */}
        <Card corners={8} cornerStroke={1} className={`p-5 space-y-4 ${verdict === scenA.verdict ? 'border-white' : ''}`}>
          <div className="flex items-center justify-between border-b border-[#202020] pb-2.5">
            <div>
              <span className="text-[9px] text-[#888888] uppercase tracking-wider block">Scenario A</span>
              <h4 className="text-xs font-bold uppercase text-white m-0">Buy Now (Lump Sum)</h4>
            </div>
            <span className={`text-[9px] px-2 py-0.5 uppercase tracking-wider ${getVerdictStyle(scenA.verdict)}`}>
              {scenA.verdict || 'PENDING'}
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Immediate Outflow:</span>
              <span className="font-bold text-white">₹{Number(scenA.immediate_outflow || 0).toLocaleString('en-IN')}</span>
            </div>
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Remaining Balance:</span>
              <span className={`font-bold ${scenA.projected_remaining_balance < 0 ? 'text-red-400' : 'text-white'}`}>
                ₹{Number(scenA.projected_remaining_balance || 0).toLocaleString('en-IN')}
              </span>
            </div>
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Emergency Runway:</span>
              <span className="font-bold text-white">{scenA.emergency_runway_months || 0} Months</span>
            </div>
          </div>

          <div className="pt-2 border-t border-[#1a1a1a] text-[10px] text-[#888888]">
            {scenA.reason}
          </div>
        </Card>

        {/* SCENARIO B: BUY WITH EMI */}
        <Card corners={8} cornerStroke={1} className={`p-5 space-y-4 ${verdict === scenB.verdict ? 'border-white' : ''}`}>
          <div className="flex items-center justify-between border-b border-[#202020] pb-2.5">
            <div>
              <span className="text-[9px] text-[#888888] uppercase tracking-wider block">Scenario B</span>
              <h4 className="text-xs font-bold uppercase text-white m-0">Buy with Financing</h4>
            </div>
            <span className={`text-[9px] px-2 py-0.5 uppercase tracking-wider ${getVerdictStyle(scenB.verdict)}`}>
              {scenB.verdict || 'PENDING'}
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Monthly Commitment:</span>
              <span className="font-bold text-white">₹{Number(scenB.effective_monthly_commitment || 0).toLocaleString('en-IN')}</span>
            </div>
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Total Hidden Fees & GST:</span>
              <span className="font-bold text-white">₹{Number(scenB.total_hidden_fees || 0).toLocaleString('en-IN')}</span>
            </div>
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Effective XIRR Rate:</span>
              <span className="font-bold text-white">{scenB.effective_annual_cost_pct ? `${scenB.effective_annual_cost_pct}%` : '0%'}</span>
            </div>
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Emergency Runway:</span>
              <span className="font-bold text-white">{scenB.emergency_runway_months || 0} Months</span>
            </div>
          </div>

          <div className="pt-2 border-t border-[#1a1a1a] text-[10px] text-[#888888]">
            {scenB.reason}
          </div>
        </Card>

        {/* SCENARIO C: WAIT (JUDGMENT FLIP) */}
        <Card corners={8} cornerStroke={1} className={`p-5 space-y-4 border-white/60 bg-[#0A0A0A]`}>
          <div className="flex items-center justify-between border-b border-[#202020] pb-2.5">
            <div>
              <span className="text-[9px] text-white uppercase tracking-wider block">Scenario C • Signature Flip</span>
              <h4 className="text-xs font-bold uppercase text-white m-0">Wait {delayDays} Days</h4>
            </div>
            <span className={`text-[9px] px-2 py-0.5 uppercase tracking-wider ${getVerdictStyle(scenC.verdict)}`}>
              {scenC.verdict || 'PENDING'}
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Accumulated Savings:</span>
              <span className="font-bold text-white">+₹{Number(scenC.accumulated_savings || 0).toLocaleString('en-IN')}</span>
            </div>
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Balance at Purchase:</span>
              <span className="font-bold text-white">₹{Number(scenC.projected_balance_at_purchase || 0).toLocaleString('en-IN')}</span>
            </div>
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Remaining Balance:</span>
              <span className="font-bold text-white">₹{Number(scenC.projected_remaining_balance || 0).toLocaleString('en-IN')}</span>
            </div>
            <div className="flex justify-between text-[#AAAAAA]">
              <span>Post-Purchase Runway:</span>
              <span className="font-bold text-white">{scenC.emergency_runway_months || 0} Months</span>
            </div>
          </div>

          <div className="pt-2 border-t border-[#1a1a1a] text-[10px] text-white">
            {scenC.reason}
          </div>
        </Card>
      </div>

      {/* 5. 90-Day Cash-Flow Projection Timeline */}
      <Card corners={10} cornerStroke={1.5} className="p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-[#202020] pb-3">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-white" />
            <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
              90-Day Cash Flow Projection & Safety Buffer Floor
            </h3>
          </div>
          <span className="text-[10px] text-[#AAAAAA] uppercase">
            Reserved Floor: ₹{Number(baseline.safety_buffer_floor || 0).toLocaleString('en-IN')}
          </span>
        </div>

        {/* Timeline checkpoints visualization */}
        {scenB.cash_flow_timeline && scenB.cash_flow_timeline.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 pt-2">
            {scenB.cash_flow_timeline.map((point) => (
              <div
                key={point.day}
                className={`border p-2.5 text-center space-y-1 transition-colors ${
                  point.is_deficit
                    ? 'border-red-500 bg-red-950/20'
                    : point.is_breach
                    ? 'border-[#D4AF37] bg-[#D4AF37]/10'
                    : 'border-[#202020] bg-[#0A0A0A]'
                }`}
              >
                <span className="text-[9px] uppercase text-[#888888] block">Day {point.day}</span>
                <span className={`text-xs font-bold block ${point.is_deficit ? 'text-red-400' : point.is_breach ? 'text-[#D4AF37]' : 'text-white'}`}>
                  ₹{Number(point.balance).toLocaleString('en-IN')}
                </span>
                <span className="text-[8px] uppercase tracking-wider block text-[#666666]">
                  {point.is_deficit ? 'DEFICIT' : point.is_breach ? 'FLOOR BREACH' : 'OK'}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-[#888888]">No projection timeline available.</p>
        )}
      </Card>

      {/* 6. "WHAT WOULD MAKE THIS SAFE?" Scenario Explorer */}
      {alternatives.length > 0 && (
        <Card corners={10} cornerStroke={1.5} className="p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-[#202020] pb-3">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                What Would Make This Safe? (Deterministic Alternatives)
              </h3>
            </div>
            <span className="text-[9px] uppercase text-[#AAAAAA]">Evidence-Checked</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {alternatives.map((alt, idx) => (
              <div key={alt.id || idx} className="border border-[#303030] bg-[#0A0A0A] p-4 space-y-2 hover:border-white transition-colors">
                <span className="border border-white bg-black px-1.5 py-0.5 text-[8px] uppercase text-white font-bold tracking-widest">
                  OPTION {idx + 1}
                </span>
                <h5 className="text-xs font-bold text-white m-0">{alt.title}</h5>
                <p className="text-[11px] text-[#AAAAAA] m-0 leading-relaxed">{alt.action}</p>

                {alt.type === 'DELAY_PURCHASE' && alt.required_delay_days && (
                  <button
                    type="button"
                    onClick={() => setDelayDays(alt.required_delay_days)}
                    className="mt-2 text-[10px] text-white border border-white px-2 py-1 uppercase font-bold hover:bg-white hover:text-black transition-colors cursor-pointer block"
                  >
                    Apply {alt.required_delay_days}d Delay to Slider →
                  </button>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 7. Gemini AI Explanation Layer (Verified against Session) */}
      <Card corners={10} cornerStroke={1.5} className="p-6 space-y-4">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 border-b border-[#202020] pb-3">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-white" />
            <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
              AI Copilot Trade-off Explanation
            </h3>
          </div>

          <div className="flex items-center gap-3">
            {aiExplanation && (
              <span className={`text-[9px] px-2 py-0.5 uppercase tracking-wider border ${
                aiExplanation.engine_status === 'GEMINI_LIVE'
                  ? 'border-white bg-white text-black font-bold'
                  : 'border-[#555555] bg-black text-[#AAAAAA]'
              }`}>
                {aiExplanation.engine_status === 'GEMINI_LIVE' ? 'Gemini Live' : 'Deterministic Offline Fallback'}
              </span>
            )}
            <button
              type="button"
              onClick={handleRequestAiExplanation}
              disabled={aiLoading}
              className="border border-white bg-black hover:bg-white hover:text-black px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest transition-colors cursor-pointer flex items-center gap-1.5"
            >
              {aiLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
              {aiExplanation ? 'Regenerate Advice' : 'Explain Trade-offs'}
            </button>
          </div>
        </div>

        {aiExplanation ? (
          <div className="space-y-4 text-xs">
            <p className="text-white leading-relaxed text-xs m-0">
              {aiExplanation.explanation}
            </p>

            {aiExplanation.financial_constraints && aiExplanation.financial_constraints.length > 0 && (
              <div className="space-y-1.5 border-t border-[#1a1a1a] pt-3">
                <span className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Key Constraints Identified:</span>
                <ul className="space-y-1 m-0 pl-4 list-disc text-[11px] text-[#888888]">
                  {aiExplanation.financial_constraints.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            )}

            {aiExplanation.scenario_suggestions && aiExplanation.scenario_suggestions.length > 0 && (
              <div className="space-y-1.5 border-t border-[#1a1a1a] pt-3">
                <span className="text-[10px] text-[#AAAAAA] uppercase tracking-wider block">Practical Actions:</span>
                <ul className="space-y-1 m-0 pl-4 list-disc text-[11px] text-white">
                  {aiExplanation.scenario_suggestions.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between text-[9px] text-[#666666] border-t border-[#1a1a1a] pt-2">
              <span>Evidence-Checked & Deterministic: Verified against Python math</span>
              <span>{aiExplanation.evidence_transaction_ids?.length || 0} session ledger citations verified</span>
            </div>
          </div>
        ) : (
          <div className="text-xs text-[#888888] py-2 flex items-center justify-between">
            <span>Click 'Explain Trade-offs' to generate an explanation from pre-computed metrics.</span>
            <span className="text-[10px] uppercase text-[#555555]">Zero raw PII transmitted</span>
          </div>
        )}
      </Card>

      {/* 8. "SHOW ME THE EVIDENCE" Modal Drawer */}
      {showEvidence && (
        <Card corners={10} cornerStroke={2} marker className="p-6 space-y-4 border-white">
          <div className="flex items-center justify-between border-b border-[#202020] pb-3">
            <div className="flex items-center gap-2">
              <Receipt className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                Verified Supporting Evidence (Session Ledger)
              </h3>
            </div>
            <button
              type="button"
              onClick={() => setShowEvidence(false)}
              className="text-xs text-[#AAAAAA] hover:text-white cursor-pointer"
            >
              ✕ Close
            </button>
          </div>

          <p className="text-[11px] text-[#AAAAAA] m-0">
            Every figure in this decision is derived from transactions in your authenticated session.
            No data is simulated or assumed without explicit disclosure.
          </p>

          {correctionSuccessMsg && (
            <div className="border border-white bg-black p-2.5 text-xs text-white">
              ✓ {correctionSuccessMsg}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs pt-2">
            {/* Income Evidence */}
            <div className="border border-[#202020] bg-[#0A0A0A] p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase text-[#AAAAAA] font-bold">1. Verified Operating Income</span>
                <span className="text-xs font-bold text-white">₹{Number(baseline.predictable_monthly_income || 0).toLocaleString('en-IN')}</span>
              </div>
              <p className="text-[10px] text-[#888888] m-0">
                Only earned salary, wages or confirmed contract credits are recognized.
                Unclassified credits (₹{Number(baseline.unclassified_credits_withheld || 0).toLocaleString('en-IN')}) are withheld from operating income.
              </p>
            </div>

            {/* Existing Obligations Evidence */}
            <div className="border border-[#202020] bg-[#0A0A0A] p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase text-[#AAAAAA] font-bold">2. Fixed Commitments & Subscriptions</span>
                <span className="text-xs font-bold text-white">₹{Number(baseline.existing_fixed_obligations || 0).toLocaleString('en-IN')}/mo</span>
              </div>
              <p className="text-[10px] text-[#888888] m-0">
                Derived from verified recurring debits for rent, loans, and subscriptions.
              </p>
            </div>
          </div>

          {/* Quick Transaction Correction Tool */}
          <div className="border border-[#202020] bg-[#050505] p-4 space-y-3">
            <span className="text-[10px] uppercase text-white font-bold tracking-wider block">
              Human Correction of Uncertain Records
            </span>
            <p className="text-[11px] text-[#AAAAAA] m-0">
              Notice a transaction misclassified as an expense instead of an own-account transfer?
              Correcting it immediately updates your living expenses and recalculates your runway.
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}
