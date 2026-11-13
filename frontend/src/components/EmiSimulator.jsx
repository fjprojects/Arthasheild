import React, { useState, useEffect, useMemo, useRef } from 'react';
import api from '../services/api';
import CrypticText from './effects/CrypticText';
import OdometerNumber from './effects/OdometerNumber';
import TargetLock from './effects/TargetLock';
import { Card } from './ui/Card';

/**
 * Local display-only engine for non-APR metrics (EMI, fee totals, affordability).
 *
 * This function deliberately does NOT compute an effective annual borrowing
 * cost. That value is authoritative only on the backend, where it is derived
 * from dated borrower cash flows via XIRR (actual days / 365). Keeping a second
 * APR formula here would risk the UI disagreeing with the verified backend.
 */
function computeEmiMetrics({
  price = 65000,
  downPayment = 0,
  tenure = 12,
  nominalApr = 0.0,
  monthlyFee = 199.0,
  upfrontFee = 0.0,
  discretionaryBuffer = 14000
}) {
  const p = Math.max(0, Number(price) || 0);
  const dp = Math.max(0, Math.min(Number(downPayment) || 0, p));
  const principal = Math.max(0, p - dp);
  const n = Math.max(1, parseInt(tenure, 10) || 12);
  const nominalRate = Math.max(0, Number(nominalApr) || 0);
  const convFee = Math.max(0, Number(monthlyFee) || 0);
  const upFee = Math.max(0, Number(upfrontFee) || 0);
  const discBuffer = Math.max(1, Number(discretionaryBuffer) || 14000);

  let baseMonthlyEmi = 0;
  let totalInterest = 0;

  if (nominalRate <= 0 || principal <= 0) {
    baseMonthlyEmi = principal / n;
    totalInterest = 0;
  } else {
    const r = (nominalRate / 100.0) / 12.0;
    const factor = Math.pow(1 + r, n);
    baseMonthlyEmi = factor === 1 ? (principal / n) : (principal * r * factor) / (factor - 1);
    totalInterest = Math.max(0, (baseMonthlyEmi * n) - principal);
  }

  const gstRate = 0.18;
  const monthlyFeeWithGst = convFee * (1.0 + gstRate);
  const upfrontFeeWithGst = upFee * (1.0 + gstRate);
  const totalHiddenFees = (monthlyFeeWithGst * n) + upfrontFeeWithGst;

  const effectiveMonthlyCost = baseMonthlyEmi + monthlyFeeWithGst;
  const totalRepayment = (baseMonthlyEmi * n) + (monthlyFeeWithGst * n);
  const totalOutflow = dp + totalRepayment + upfrontFeeWithGst;

  const pctOfDiscretionaryUsed = Math.round(((effectiveMonthlyCost / discBuffer) * 100) * 10) / 10;

  let status = 'LOW RISK';
  let explanation = 'LOW RISK: Easily fits within your current discretionary cashflow.';
  let isViable = true;

  if (pctOfDiscretionaryUsed > 40) {
    status = 'HIGH RISK';
    explanation = 'HIGH RISK: Would consume over 40% of your free monthly cash buffer.';
    isViable = false;
  } else if (pctOfDiscretionaryUsed > 25) {
    status = 'MODERATE';
    explanation = 'MODERATE: Manageable, but substantially reduces your buffer for emergency spending.';
    isViable = true;
  }

  return {
    price: p,
    downPayment: dp,
    principal: Math.round(principal * 100) / 100,
    tenureMonths: n,
    nominalApr: Math.round(nominalRate * 100) / 100,
    monthlyProcessingFee: Math.round(convFee * 100) / 100,
    monthlyFeeWithGst: Math.round(monthlyFeeWithGst * 100) / 100,
    upfrontFeeWithGst: Math.round(upfrontFeeWithGst * 100) / 100,
    baseMonthlyEmi: Math.round(baseMonthlyEmi * 100) / 100,
    monthlyCommitment: Math.round(effectiveMonthlyCost * 100) / 100,
    totalInterest: Math.round(totalInterest * 100) / 100,
    totalHiddenFees: Math.round(totalHiddenFees * 100) / 100,
    totalRepayment: Math.round(totalRepayment * 100) / 100,
    totalOutflow: Math.round(totalOutflow * 100) / 100,
    bufferConsumedPct: pctOfDiscretionaryUsed,
    status,
    explanation,
    isViable
  };
}

export default function EmiSimulator({ discretionaryBuffer = 14000 }) {
  const [itemName, setItemName] = useState('Flagship Smartphone');
  const [price, setPrice] = useState(65000);
  const [tenure, setTenure] = useState(12);
  const [downPayment, setDownPayment] = useState(0);
  const [nominalApr, setNominalApr] = useState(0.0);
  const [monthlyFee, setMonthlyFee] = useState(199.0);
  const [upfrontFee, setUpfrontFee] = useState(0);
  const [simulation, setSimulation] = useState(null);
  const [simulationSignature, setSimulationSignature] = useState(null);
  const [loading, setLoading] = useState(false);
  const requestSeq = useRef(0);

  // Synchronous fallback for non-APR display values only.
  const localCalc = useMemo(() => {
    return computeEmiMetrics({
      price,
      downPayment,
      tenure,
      nominalApr,
      monthlyFee,
      upfrontFee,
      discretionaryBuffer
    });
  }, [price, downPayment, tenure, nominalApr, monthlyFee, upfrontFee, discretionaryBuffer]);

  // Signature ties an async backend response to the exact inputs that produced
  // it, so a stale APR is never displayed while the user is still typing.
  const inputSignature = useMemo(() => JSON.stringify({
    itemName,
    price: Number(price) || 0,
    tenure: Number(tenure) || 12,
    downPayment: Number(downPayment) || 0,
    nominalApr: Number(nominalApr) || 0,
    monthlyFee: Number(monthlyFee) || 0,
    upfrontFee: Number(upfrontFee) || 0,
    discretionaryBuffer: Number(discretionaryBuffer) || 14000,
  }), [itemName, price, tenure, downPayment, nominalApr, monthlyFee, upfrontFee, discretionaryBuffer]);

  // Debounced authoritative calculation (backend XIRR).
  useEffect(() => {
    const signature = inputSignature;
    const seq = ++requestSeq.current;
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const result = await api.simulateEmi({
          item_name: itemName,
          price: Number(price) || 0,
          tenure_months: Number(tenure) || 12,
          down_payment: Number(downPayment) || 0,
          nominal_apr: Number(nominalApr) || 0,
          monthly_processing_fee: Number(monthlyFee) || 0,
          upfront_processing_fee: Number(upfrontFee) || 0,
          gst_rate_pct: 18.0,
          discretionary_buffer: Number(discretionaryBuffer) || 14000,
        });
        if (seq === requestSeq.current && result && typeof result === 'object') {
          setSimulation(result);
          setSimulationSignature(signature);
        }
      } catch (err) {
        console.error('Backend EMI XIRR calculation failed (effective cost unavailable):', err);
        if (seq === requestSeq.current) {
          setSimulation(null);
          setSimulationSignature(null);
        }
      } finally {
        if (seq === requestSeq.current) setLoading(false);
      }
    }, 200);

    return () => clearTimeout(timer);
    // inputSignature changes whenever any input changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputSignature]);

  // Safe formatting helpers that prevent NaN, Infinity, and undefined
  const formatInr = (val) => {
    const num = Number(val);
    if (isNaN(num) || !isFinite(num)) return '₹0';
    return `₹${num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatNumber = (val) => {
    const num = Number(val);
    if (isNaN(num) || !isFinite(num)) return '0';
    return num.toLocaleString('en-IN', { maximumFractionDigits: 2 });
  };

  const backendFresh = Boolean(simulation && simulationSignature === inputSignature);
  const activeSimulation = backendFresh ? simulation : null;

  // APR is only ever sourced from the backend. No local fee-load formula.
  const effectiveApr = (
    activeSimulation &&
    activeSimulation.effective_annual_cost_pct !== null &&
    activeSimulation.effective_annual_cost_pct !== undefined
  ) ? Number(activeSimulation.effective_annual_cost_pct) : null;

  const aprAvailable = Boolean(
    backendFresh &&
    activeSimulation?.is_effective_cost_available &&
    effectiveApr !== null &&
    Number.isFinite(effectiveApr)
  );

  const aprStatus = backendFresh
    ? String(activeSimulation?.apr_calculation?.status || 'UNAVAILABLE')
    : 'PENDING';
  const aprReason = backendFresh ? activeSimulation?.apr_calculation?.reason : null;
  const materialized = aprStatus === 'OK' || aprStatus === 'NOT_APPLICABLE' || aprStatus === 'UNAVAILABLE';

  const monthlyCommitment = Number(
    activeSimulation?.monthly_emi ??
    activeSimulation?.effective_monthly_outflow ??
    localCalc.monthlyCommitment
  );

  const principalFinanced = Number(
    activeSimulation?.cost_breakdown?.principal_financed ??
    activeSimulation?.principal ??
    localCalc.principal
  );

  const hiddenFees = Number(
    activeSimulation?.cost_breakdown?.total_fees_and_gst ??
    activeSimulation?.total_hidden_fees_and_gst ??
    localCalc.totalHiddenFees
  );

  const totalRepayment = Number(
    activeSimulation?.cost_breakdown?.total_repayment ??
    activeSimulation?.total_repayment ??
    localCalc.totalRepayment
  );

  const totalOutflow = Number(
    activeSimulation?.cost_breakdown?.total_cash_outflow ??
    activeSimulation?.total_overall_cost ??
    localCalc.totalOutflow
  );

  const verdictStatus = String(
    activeSimulation?.affordability_verdict?.status ??
    localCalc.status
  );

  const bufferConsumedPct = Number(
    activeSimulation?.affordability_verdict?.buffer_consumed_pct ??
    localCalc.bufferConsumedPct
  );

  const verdictExplanation = String(
    activeSimulation?.affordability_verdict?.explanation ??
    localCalc.explanation
  );

  const feeAssumptions = activeSimulation?.fee_assumptions ?? null;
  const aprCalculation = activeSimulation?.apr_calculation ?? null;

  return (
    <div className="space-y-6">
      
      {/* Header with Corner Accents */}
      <Card className="p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <span className="border border-white bg-black px-2 py-0.5 text-[9px] font-mono uppercase text-white font-bold tracking-widest">
              SIMULATOR
            </span>
            <h3 className="text-xs font-mono font-bold uppercase tracking-widest text-white m-0">
              "What-If" EMI & Affordability Reality Check
            </h3>
          </div>
          <p className="text-[11px] font-mono text-[#AAAAAA] mt-1 m-0">
            Expose deceptive 0% No-Cost EMI fine print, hidden charges, and the effective annual borrowing cost derived from actual cash flows.
          </p>
        </div>

        <div className="text-[10px] font-mono uppercase px-3 py-1.5 border border-[#202020] bg-[#0A0A0A] text-white">
          Discretionary Floor: ₹{Number(discretionaryBuffer).toLocaleString('en-IN')}/MO
        </div>
      </Card>

      {/* Simulator Inputs & Output Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* Input Controls (5 Cols) */}
        <Card className="lg:col-span-5 p-6 space-y-5 font-mono">
          <span className="text-[10px] font-bold uppercase tracking-widest text-[#AAAAAA] block border-b border-[#202020] pb-2">
            Loan & Purchase Parameters
          </span>

          {/* Item Name */}
          <div className="space-y-1.5">
            <label className="text-[10px] uppercase text-[#AAAAAA]">Target Purchase</label>
            <input
              type="text"
              value={itemName}
              onChange={(e) => setItemName(e.target.value)}
              className="w-full bg-[#050505] border border-[#202020] px-3 py-2 text-xs text-white focus:outline-none focus:border-white transition-colors"
            />
          </div>

          {/* Price Slider & Down Payment */}
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-[10px] uppercase text-[#AAAAAA]">Purchase Value</span>
              <span className="font-bold text-white">₹{formatNumber(price)}</span>
            </div>
            <input
              type="range"
              min={5000}
              max={250000}
              step={1000}
              value={price}
              onChange={(e) => setPrice(Math.max(0, Number(e.target.value) || 0))}
              className="w-full accent-white cursor-pointer"
            />
          </div>

          {/* Down Payment Field */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs">
              <label className="text-[10px] uppercase text-[#AAAAAA]">Down Payment (₹)</label>
              <span className="text-zinc-400 text-[10px]">Principal: {formatInr(principalFinanced)}</span>
            </div>
            <input
              type="number"
              min="0"
              max={price}
              step="1000"
              value={downPayment}
              onChange={(e) => setDownPayment(Math.max(0, Math.min(Number(price) || 0, Number(e.target.value) || 0)))}
              className="w-full bg-[#050505] border border-[#202020] px-3 py-1.5 text-xs text-white focus:outline-none focus:border-white font-mono"
            />
          </div>

          {/* Tenure Buttons */}
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-[10px] uppercase text-[#AAAAAA]">Tenure</span>
              <span className="font-bold text-white">{tenure} Months</span>
            </div>
            <div className="grid grid-cols-6 gap-1.5 pt-1">
              {[3, 6, 9, 12, 18, 24].map((m) => (
                <TargetLock key={m}>
                  <button
                    type="button"
                    onClick={() => setTenure(m)}
                    className={`w-full text-[10px] uppercase py-1 border transition cursor-pointer text-center ${
                      tenure === m
                        ? 'border-white bg-white text-black font-bold shadow-[0_0_10px_rgba(255,255,255,0.3)]'
                        : 'border-[#202020] bg-[#0A0A0A] text-[#AAAAAA] hover:text-white hover:border-[#404040]'
                    }`}
                  >
                    {m}M
                  </button>
                </TargetLock>
              ))}
            </div>
          </div>

          {/* Nominal Rate, Recurring Fee, Upfront Fee, GST */}
          <div className="grid grid-cols-2 gap-4 pt-2 border-t border-[#202020]">
            <div className="space-y-1">
              <label className="text-[10px] uppercase text-[#AAAAAA]">Stated Nominal Rate (%)</label>
              <input
                type="number"
                min="0"
                max="48"
                step="0.5"
                value={nominalApr}
                onChange={(e) => setNominalApr(Math.max(0, Number(e.target.value) || 0))}
                className="w-full bg-[#050505] border border-[#202020] px-3 py-1.5 text-xs text-white focus:outline-none focus:border-white font-mono"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] uppercase text-[#AAAAAA]">Fee / Mo (₹)</label>
              <input
                type="number"
                min="0"
                max="5000"
                step="10"
                value={monthlyFee}
                onChange={(e) => setMonthlyFee(Math.max(0, Number(e.target.value) || 0))}
                className="w-full bg-[#050505] border border-[#202020] px-3 py-1.5 text-xs text-white focus:outline-none focus:border-white font-mono"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] uppercase text-[#AAAAAA]">Upfront Fee (₹)</label>
              <input
                type="number"
                min="0"
                max="100000"
                step="100"
                value={upfrontFee}
                onChange={(e) => setUpfrontFee(Math.max(0, Number(e.target.value) || 0))}
                className="w-full bg-[#050505] border border-[#202020] px-3 py-1.5 text-xs text-white focus:outline-none focus:border-white font-mono"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] uppercase text-[#AAAAAA]">GST on Fees</label>
              <div className="w-full bg-[#050505] border border-[#202020] px-3 py-1.5 text-xs text-[#AAAAAA] font-mono">
                18% · upfront & monthly
              </div>
            </div>
          </div>
        </Card>

        {/* Results & Truth Engine (7 Cols) */}
        <div className="lg:col-span-7 space-y-6">
          <Card corners={12} cornerStroke={2} className="p-8 space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-6 border-b border-[#202020] gap-4">
              <div>
                <span className="text-[9px] font-mono uppercase text-[#AAAAAA] tracking-widest block">
                  Effective Annual Borrowing Cost
                </span>
                {aprAvailable ? (
                  <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-white font-bold mt-1">
                    <OdometerNumber value={effectiveApr} suffix="%" />
                  </div>
                ) : (
                  <div className="text-3xl sm:text-4xl font-mono tracking-tighter text-[#AAAAAA] font-bold mt-1">
                    {materialized && backendFresh ? 'UNAVAILABLE' : 'CALCULATING…'}
                  </div>
                )}
                <div className="text-[10px] font-mono text-[#AAAAAA] uppercase mt-1">
                  {aprAvailable
                    ? 'XIRR from actual dated cash flows · actual days / 365'
                    : backendFresh && aprStatus === 'NOT_APPLICABLE'
                      ? 'No principal financed — cost is not defined'
                      : backendFresh
                        ? `Unavailable: ${aprReason || 'CALCULATION_UNAVAILABLE'}`
                        : 'Waiting for authoritative backend calculation'}
                </div>
                <div className="text-[10px] font-mono text-[#8A8A8A] uppercase mt-1">
                  Nominal annual rate: {formatNumber(nominalApr)}%
                </div>
              </div>

              <div className="text-right sm:border-l sm:border-[#202020] sm:pl-8">
                <span className="text-[9px] font-mono uppercase text-[#AAAAAA] tracking-widest block">
                  True Monthly Commitment
                </span>
                <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-white font-bold mt-1">
                  <CrypticText text={formatInr(monthlyCommitment)} triggerKey={monthlyCommitment} />
                </div>
                <div className="text-[10px] font-mono text-[#AAAAAA] uppercase mt-1">
                  Includes GST, recurring & upfront levies
                </div>
              </div>
            </div>

            {/* Cost Decomposition Grid: Principal, Fees, Total Repayment, Total Outflow */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-xs">
              <div className="border border-[#202020] bg-black p-3 space-y-1">
                <span className="text-[9px] uppercase text-[#AAAAAA]">Principal</span>
                <div className="text-sm sm:text-base font-bold text-white">
                  {formatInr(principalFinanced)}
                </div>
              </div>

              <div className="border border-[#202020] bg-black p-3 space-y-1">
                <span className="text-[9px] uppercase text-[#AAAAAA]">Fees & GST</span>
                <div className="text-sm sm:text-base font-bold text-white">
                  {formatInr(hiddenFees)}
                </div>
              </div>

              <div className="border border-[#202020] bg-black p-3 space-y-1">
                <span className="text-[9px] uppercase text-[#AAAAAA]">Total Repayment</span>
                <div className="text-sm sm:text-base font-bold text-white">
                  {formatInr(totalRepayment)}
                </div>
              </div>

              <div className="border border-[#202020] bg-black p-3 space-y-1">
                <span className="text-[9px] uppercase text-[#AAAAAA]">Total Outflow</span>
                <div className="text-sm sm:text-base font-bold text-white">
                  {formatInr(totalOutflow)}
                </div>
              </div>
            </div>

            {/* APR Assumptions & Fee Components */}
            <div className="border border-[#202020] bg-black p-4 space-y-1.5 font-mono text-[10px]">
              <div className="flex items-center justify-between border-b border-[#1a1a1a] pb-1.5">
                <span className="text-[#AAAAAA] uppercase tracking-widest">Calculation Assumptions</span>
                <span className="text-white uppercase">{backendFresh ? aprStatus : 'PENDING'}</span>
              </div>
              {backendFresh && feeAssumptions ? (
                <>
                  <div className="flex justify-between"><span className="text-[#AAAAAA]">Method</span><span className="text-white">XIRR · actual days / 365</span></div>
                  <div className="flex justify-between"><span className="text-[#AAAAAA]">Nominal annual rate</span><span className="text-white">{formatNumber(nominalApr)}%</span></div>
                  <div className="flex justify-between"><span className="text-[#AAAAAA]">Upfront fee + GST</span><span className="text-white">{formatInr(feeAssumptions.upfront_fee_with_gst)}</span></div>
                  <div className="flex justify-between"><span className="text-[#AAAAAA]">Recurring fee + GST / mo</span><span className="text-white">{formatInr(feeAssumptions.recurring_fee_with_gst_per_month)}</span></div>
                  <div className="flex justify-between"><span className="text-[#AAAAAA]">GST rate on fees</span><span className="text-white">{formatNumber(feeAssumptions.recurring_fee_gst_rate_pct)}%</span></div>
                  <div className="flex justify-between"><span className="text-[#AAAAAA]">Net disbursement</span><span className="text-white">{formatInr(aprCalculation?.net_disbursement)}</span></div>
                  <div className="flex justify-between"><span className="text-[#AAAAAA]">Solver</span><span className="text-white">{aprCalculation?.converged ? `Converged (${aprCalculation.iterations} it.)` : aprStatus}</span></div>
                </>
              ) : (
                <p className="text-[#AAAAAA] m-0">Awaiting backend cash-flow calculation…</p>
              )}
            </div>

            {/* Affordability & Stress Test Verdict */}
            <div className="border-l-2 border-white bg-black border border-[#202020] p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="bg-white text-black px-1.5 py-0.5 font-bold uppercase tracking-wider text-[9px] font-mono">
                  Affordability Verdict: {verdictStatus}
                </span>
                <span className="text-[10px] font-mono uppercase text-[#AAAAAA]">
                  {bufferConsumedPct}% of Free Buffer
                </span>
              </div>
              <p className="text-xs font-mono text-[#AAAAAA] leading-relaxed m-0">
                {verdictExplanation}
              </p>
            </div>

            {/* Disclaimer */}
            <div className="text-[9px] font-mono text-[#8A8A8A] leading-relaxed">
              {activeSimulation?.apr_disclaimer ?? 'Model estimate from user-supplied inputs. Not a lender offer and not a regulatory APR disclosure.'}
            </div>

            {/* Hidden Trap Fine Print Warning */}
            <div className="text-[10px] font-mono text-[#8A8A8A] border-t border-[#1a1a1a] pt-3 flex items-center justify-between">
              <span>TRUTH ENGINE :: BACKEND XIRR · ACTUAL/365 · DETERMINISTIC ARITHMETIC</span>
              <span>{loading ? 'RECALCULATING...' : aprAvailable ? 'VERIFIED' : backendFresh ? 'UNAVAILABLE' : 'PENDING'}</span>
            </div>

          </Card>
        </div>

      </div>

    </div>
  );
}
