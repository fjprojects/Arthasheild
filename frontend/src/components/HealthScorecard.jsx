import React from 'react';
import { 
  HeartPulse, 
  TrendingUp, 
  ShieldCheck, 
  Clock, 
  Flame, 
  Terminal,
  Activity,
  Layers,
  ArrowUpRight,
  AlertTriangle
} from 'lucide-react';
import CrypticText from './effects/CrypticText';
import OdometerNumber from './effects/OdometerNumber';
import { Card } from './ui/Card';
import ProgressBar from './ui/ProgressBar';

const LIMITATION_LABELS = {
  LIQUID_BALANCE_UNAVAILABLE:
    'No verified liquid balance is available for this dataset.',
  EMERGENCY_RUNWAY_WITHHELD:
    'Emergency runway is withheld because the liquid balance is unverified.',
  SAFE_TO_SPEND_UNAVAILABLE:
    'Safe-to-Spend is unavailable because the current balance or in-period coverage is missing.',
  STATEMENT_PERIOD_ENDED:
    'The statement period has ended, so a forward-looking daily allowance is unavailable.',
  INSUFFICIENT_TRANSACTION_DATA:
    'The statement does not contain enough income or expense rows for a complete assessment.',
  HEALTH_SCORE_ESTIMATED:
    'The Health Index is an estimate and is not presented as a verified grade.',
  PERSONA_SCENARIO_ESTIMATE:
    'These values are a synthetic persona scenario, not observed customer data.',
  BALANCE_UNAVAILABLE_FOR_SELECTED_DATASET:
    'The selected dataset has no verified balance available.',
};

export default function HealthScorecard({
  healthMetrics,
  safeToSpend,
  selectedPersona,
  detectedLeaks,
  datasetSourceLabel = 'UNSPECIFIED',
  reportingPeriod = 'PERIOD NOT AVAILABLE',
  metricBasis = {},
  coverageLimitations = [],
  healthStatus = null,
  leakageStatus = 'REVIEW',
}) {
  if (!healthMetrics) return null;

  const score = healthMetrics.health_score;
  const scoreUnavailable = score === null || score === undefined;
  const grade = healthMetrics.grade || 'STATUS UNAVAILABLE';
  const rawRunway = healthMetrics.metrics?.runway_months;
  const runwayUnavailable =
    healthMetrics.liquid_balance_known === false ||
    rawRunway === null ||
    rawRunway === undefined;
  const runway = runwayUnavailable ? null : rawRunway;
  const dti = healthMetrics.metrics?.debt_to_income_ratio_pct ?? null;
  const hasActiveLeaks = (detectedLeaks?.items_count || 0) > 0;
  const sourceCaption = `SOURCE: ${datasetSourceLabel} · PERIOD: ${reportingPeriod}`;
  const runwayCaption = runwayUnavailable
    ? 'WITHHELD — NO VERIFIED BALANCE FOR THIS DATASET'
    : metricBasis?.runway === 'PERSONA_SCENARIO_ESTIMATE'
      ? 'ESTIMATED — DEMO PERSONA SCENARIO BALANCE'
      : 'OBSERVED — VERIFIED BALANCE';
  // Imported statements carry no verified liquid balance, so Safe-to-Spend is
  // withheld server-side (INSUFFICIENT_DATA). Display that honestly instead of
  // implying a ₹0 allowance.
  const safeToSpendUnavailable =
    !safeToSpend ||
    safeToSpend.status === 'INSUFFICIENT_DATA' ||
    safeToSpend.safe_to_spend_daily === null ||
    safeToSpend.safe_to_spend_daily === undefined;

  // A score derived without a verified liquid balance is an estimate, not an
  // observed grade. Persona scenario scores are also explicitly estimates.
  const healthBasis = metricBasis?.health_score || healthMetrics.health_status || null;
  const healthEstimated =
    !scoreUnavailable &&
    (healthBasis === 'ESTIMATED_BALANCE_UNAVAILABLE' ||
      healthBasis === 'PERSONA_SCENARIO_ESTIMATE' ||
      healthStatus === 'ESTIMATED');
  const healthInsufficient = healthStatus === 'INSUFFICIENT_DATA' || scoreUnavailable;
  const gradeIsProvisional = healthBasis === 'ESTIMATED_BALANCE_UNAVAILABLE';
  const displayGrade = healthInsufficient
    ? 'STATUS UNAVAILABLE'
    : gradeIsProvisional
      ? (String(grade).toUpperCase().startsWith('ESTIMATED')
          ? grade
          : `PROVISIONAL · ${grade}`)
      : healthEstimated
        ? `ESTIMATED · ${grade}`
        : grade;

  const derivedLimitations = [];
  if (runwayUnavailable) {
    derivedLimitations.push(
      'Emergency runway withheld: no verified liquid balance for this dataset.',
    );
  }
  if (safeToSpendUnavailable) {
    derivedLimitations.push(
      safeToSpend?.insufficient_reason
        ? `Safe-to-Spend unavailable: ${safeToSpend.insufficient_reason.replace(/_/g, ' ').toLowerCase()}.`
        : 'Safe-to-Spend unavailable: current balance or in-period coverage is missing.',
    );
  }
  if (healthBasis === 'ESTIMATED_BALANCE_UNAVAILABLE') {
    derivedLimitations.push(
      'Health Index is estimated from observed income and expenses without a verified liquid balance; it is not a verified grade.',
    );
  } else if (healthBasis === 'PERSONA_SCENARIO_ESTIMATE') {
    derivedLimitations.push(
      'Health Index is a synthetic persona scenario estimate, not observed customer data.',
    );
  }
  if (healthInsufficient) {
    derivedLimitations.push(
      'Essential income or balance data is missing, so no health grade is asserted.',
    );
  }
  const limitations = Array.from(
    new Set([
      ...(coverageLimitations || []).map(
        (item) => LIMITATION_LABELS[item] || item,
      ),
      ...derivedLimitations,
    ]),
  );

  return (
    <div className="space-y-6">
      
      {/* Liquidity Engine ("Safe-to-Spend" Banner) — Stark Contrast Box with SVG Path-Traced Corner Brackets */}
      <Card
        corners={12}
        cornerStroke={2}
        className="p-8 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6 animate-scanline"
      >
        
        {/* Left: Module Title & Context */}
        <div className="space-y-2">
          <div className="flex items-center space-x-2 text-[9px] font-mono uppercase text-[#AAAAAA] tracking-widest">
            <Clock className="w-3.5 h-3.5 text-white" />
            <span>
              Cycle Reset in{' '}
              {safeToSpend?.days_remaining_in_cycle !== null &&
              safeToSpend?.days_remaining_in_cycle !== undefined
                ? `${safeToSpend.days_remaining_in_cycle} Days`
                : '— (period unavailable)'}
            </span>
            <span className="text-[#767676]">◈</span>
            <span className="text-white font-bold">DETERMINISTIC LIQUIDITY</span>
          </div>
          
          <h2 className="text-sm font-bold uppercase tracking-[0.18em] text-white m-0 font-mono">
            Real-Time "Safe-to-Spend" Allowance
          </h2>
          
          <p className="text-xs font-mono text-[#AAAAAA] leading-relaxed max-w-xl m-0">
            {safeToSpend?.guidance || "Deterministic daily discretionary ceiling calculated after reserving pending EMIs, rent, and emergency floor."}
          </p>
          <p className="text-[9px] font-mono uppercase tracking-wider text-[#888888] m-0">
            {sourceCaption} · STATUS: {safeToSpendUnavailable ? 'INSUFFICIENT DATA' : 'OBSERVED + DERIVED'}
          </p>
        </div>

        {/* Right: Stark Monospace Financial Values with Cryptographic Scramble */}
        <div className="flex flex-wrap items-center gap-8 min-w-0 border-t lg:border-t-0 lg:border-l border-[#202020] pt-4 lg:pt-0 lg:pl-8">
          <div className="min-w-0">
            <div className="text-3xl sm:text-4xl lg:text-5xl font-mono tracking-tighter text-white font-bold whitespace-nowrap">
              {safeToSpendUnavailable ? (
                <span className="text-xl sm:text-2xl">UNAVAILABLE</span>
              ) : (
                <CrypticText
                  text={`₹${safeToSpend?.safe_to_spend_daily?.toLocaleString('en-IN') || '0'}`}
                  triggerKey={safeToSpend?.safe_to_spend_daily}
                />
              )}
            </div>
            <div className="text-[9px] uppercase text-[#AAAAAA] font-mono tracking-widest mt-2 flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${safeToSpendUnavailable ? 'bg-[#888888]' : 'bg-white'}`} />
              <span>{safeToSpendUnavailable ? 'Awaiting Verified Balance' : 'Safe Per Day'}</span>
            </div>
          </div>

          <div className="sm:border-l sm:border-[#202020] sm:pl-8 min-w-0">
            <div className="text-3xl sm:text-4xl lg:text-5xl font-mono tracking-tighter text-white font-bold whitespace-nowrap">
              {safeToSpendUnavailable ? (
                <span className="text-xl sm:text-2xl">UNAVAILABLE</span>
              ) : (
                <CrypticText
                  text={`₹${safeToSpend?.safe_to_spend_weekly?.toLocaleString('en-IN') || '0'}`}
                  triggerKey={safeToSpend?.safe_to_spend_weekly}
                />
              )}
            </div>
            <div className="text-[9px] uppercase text-[#AAAAAA] font-mono tracking-widest mt-2 flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${safeToSpendUnavailable ? 'bg-[#888888]' : 'bg-[#AAAAAA]'}`} />
              <span>{safeToSpendUnavailable ? 'No Balance On Statement' : 'Safe This Week'}</span>
            </div>
          </div>
        </div>

      </Card>

      {/* 4 Metric Cards — Sequential Staggered Boot Sequence.
          The four-across layout starts at the xl breakpoint: at 1024px a
          270px rail leaves each card too narrow for its own figure, which
          clipped the DTI and /MO suffixes. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        
        {/* Card 1: Health Score with Rolling Odometer */}
        <Card
          corners={8}
          cornerStroke={1.5}
          marker
          tilt
          className="boot-stage-1 p-6 flex flex-col justify-between min-w-0"
        >
          <div>
            <div className="text-[10px] uppercase text-[#AAAAAA] flex items-center justify-between pb-3 border-b border-[#202020] font-mono">
              <span className="tracking-wider">Health Index</span>
              <HeartPulse className="w-4 h-4 text-white" />
            </div>

            <div className="text-3xl sm:text-4xl xl:text-5xl font-mono font-bold text-white py-4 tracking-tight flex items-baseline min-w-0 whitespace-nowrap">
              {scoreUnavailable ? (
                <span className="text-xl">UNAVAILABLE</span>
              ) : (
                <>
                  <OdometerNumber value={score} />
                  <span className="text-xs text-[#AAAAAA] ml-1 font-mono font-normal">/100</span>
                </>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-1.5 mb-3">
              <div className="inline-flex border border-white bg-black text-white text-[9px] font-mono uppercase px-2 py-0.5 w-fit font-bold tracking-widest">
                {displayGrade}
              </div>
              {healthEstimated && (
                <span className="inline-flex border border-amber-500/50 bg-amber-950/30 text-amber-300 text-[8px] font-mono uppercase px-1.5 py-0.5 w-fit font-bold tracking-widest">
                  ESTIMATED
                </span>
              )}
            </div>
          </div>

          <div>
            <ProgressBar value={scoreUnavailable ? 0 : Math.min(100, Math.max(5, score))} />
            <p className="text-[9px] font-mono text-[#AAAAAA] mt-2 m-0 uppercase tracking-wider">
              Financial resilience index ·{' '}
              {healthInsufficient
                ? 'INSUFFICIENT DATA'
                : healthEstimated
                  ? 'ESTIMATE — NOT A VERIFIED GRADE'
                  : 'DERIVED FROM OBSERVED DATA'}
            </p>
            <p className="text-[8px] font-mono text-[#777777] mt-1 m-0 uppercase tracking-wider break-words">
              {sourceCaption}
            </p>
          </div>
          </Card>

        {/* Card 2: Runway */}
        <Card
          corners={8}
          cornerStroke={1.5}
          marker
          tilt
          className="boot-stage-2 p-6 flex flex-col justify-between min-w-0"
        >
          <div>
            <div className="text-[10px] uppercase text-[#AAAAAA] flex items-center justify-between pb-3 border-b border-[#202020] font-mono">
              <span className="tracking-wider">Emergency Runway</span>
              <ShieldCheck className="w-4 h-4 text-white" />
            </div>

            <div className="text-3xl sm:text-4xl xl:text-5xl font-mono font-bold text-white py-4 tracking-tight flex items-baseline min-w-0 whitespace-nowrap">
              {runwayUnavailable ? (
                <span className="text-xl">UNAVAILABLE</span>
              ) : (
                <>
                  <CrypticText text={String(runway)} triggerKey={runway} />
                  <span className="text-xs text-[#AAAAAA] ml-1 font-mono font-normal">MO</span>
                </>
              )}
            </div>

            <div className="inline-flex border border-[#404040] bg-[#111111] text-[#AAAAAA] text-[9px] font-mono uppercase px-2 py-0.5 mb-3 w-fit tracking-wider">
              {runwayUnavailable
                ? 'INSUFFICIENT DATA'
                : runway >= 3
                  ? 'Resilient'
                  : runway >= 1
                    ? 'Moderate Buffer'
                    : 'Critical Depletion'}
            </div>
          </div>

          <div>
            <ProgressBar value={runwayUnavailable ? 0 : Math.min(100, (runway / 6) * 100)} />
            <p className="text-[9px] font-mono text-[#AAAAAA] mt-2 m-0 uppercase tracking-wider">
              Liquid buffer at fixed burn
            </p>
            <p className="text-[8px] font-mono text-[#777777] mt-1 m-0 uppercase tracking-wider break-words">
              {runwayCaption}
            </p>
          </div>
          </Card>

        {/* Card 3: Debt Pressure with Rolling Odometer */}
        <Card
          corners={8}
          cornerStroke={1.5}
          marker
          tilt
          className="boot-stage-3 p-6 flex flex-col justify-between min-w-0"
        >
          <div>
            <div className="text-[10px] uppercase text-[#AAAAAA] flex items-center justify-between pb-3 border-b border-[#202020] font-mono">
              <span className="tracking-wider">Debt Pressure</span>
              <TrendingUp className="w-4 h-4 text-white" />
            </div>

            <div className="text-3xl sm:text-4xl xl:text-5xl font-mono font-bold text-white py-4 tracking-tight flex items-baseline min-w-0 whitespace-nowrap">
              {dti === null ? (
                <span className="text-xl">UNAVAILABLE</span>
              ) : (
                <>
                  <OdometerNumber value={dti} suffix="%" />
                  <span className="text-xs text-[#AAAAAA] ml-1 font-mono font-normal">DTI</span>
                </>
              )}
            </div>

            <div className="inline-flex border border-[#404040] bg-[#111111] text-[#AAAAAA] text-[9px] font-mono uppercase px-2 py-0.5 mb-3 w-fit tracking-wider">
              {dti === null ? 'INSUFFICIENT DATA' : dti <= 30 ? 'Safe Ratio' : 'High Obligation'}
            </div>
          </div>

          <div>
            <ProgressBar value={dti === null ? 0 : Math.min(100, dti)} />
            <p className="text-[9px] font-mono text-[#AAAAAA] mt-2 m-0 uppercase tracking-wider">
              Committed to active loans & rent
            </p>
            <p className="text-[8px] font-mono text-[#777777] mt-1 m-0 uppercase tracking-wider break-words">
              {sourceCaption}
            </p>
          </div>
          </Card>

        {/* Card 4: Silent Leakage with Monochrome Warning Breathing Glow */}
        <Card
          corners={8}
          cornerStroke={1.5}
          marker
          className={`boot-stage-4 p-6 flex flex-col justify-between min-w-0 ${
            hasActiveLeaks ? 'animate-warning-pulse' : ''
          }`}
        >
          <div>
            <div className="text-[10px] uppercase text-[#AAAAAA] flex items-center justify-between pb-3 border-b border-[#202020] font-mono">
              <span className="tracking-wider">Recurring Review Amount</span>
              <Flame className="w-4 h-4 text-white" />
            </div>

            <div className="text-3xl sm:text-4xl xl:text-5xl font-mono font-bold text-white py-4 tracking-tight flex items-baseline min-w-0 whitespace-nowrap">
              <CrypticText
                text={`₹${detectedLeaks?.total_monthly_leakage?.toLocaleString('en-IN') || '0'}`}
                triggerKey={detectedLeaks?.total_monthly_leakage}
              />
              <span className="text-xs text-[#AAAAAA] ml-1 font-mono font-normal">/MO</span>
            </div>

            <div className="inline-flex border border-white bg-black text-white text-[9px] font-mono uppercase px-2 py-0.5 mb-3 w-fit font-bold tracking-widest">
              {detectedLeaks?.items_count || 0} {leakageStatus === 'SCENARIO_UNVERIFIED' ? 'Scenario Items' : 'Payments to Review'}
            </div>
          </div>

          <div>
            <ProgressBar value={Math.min(100, ((detectedLeaks?.total_monthly_leakage || 0) / 10000) * 100)} />
            <p className="text-[9px] font-mono text-[#AAAAAA] mt-2 m-0 uppercase tracking-wider">
              {leakageStatus === 'SCENARIO_UNVERIFIED'
                ? 'Static scenario reference — unverified, not savings'
                : 'Evidence-based recurring payments — review before treating as savings'}
            </p>
            <p className="text-[8px] font-mono text-[#777777] mt-1 m-0 uppercase tracking-wider break-words">
              {sourceCaption} · STATUS: {leakageStatus === 'SCENARIO_UNVERIFIED' ? 'UNVERIFIED SCENARIO' : 'REVIEW CANDIDATES'}
            </p>
          </div>
          </Card>

      </div>

      {/* Data-coverage transparency. Missing essential inputs are stated
          plainly rather than being hidden behind a reassuring grade. */}
      {limitations.length > 0 && (
        <div className="border border-amber-500/30 bg-amber-950/10 p-4 flex gap-4 items-start">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="border border-amber-500/50 bg-amber-950/30 text-amber-300 px-1.5 py-0.5 font-bold uppercase tracking-wider text-[9px] font-mono">
                Data Coverage Limitations
              </span>
              <span className="text-[9px] font-mono uppercase text-[#AAAAAA]">
                Read before treating any metric as complete
              </span>
            </div>
            <ul className="list-disc pl-4 space-y-1 text-[10px] font-mono text-[#BBBBBB] m-0">
              {limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Bottom Disclaimer Box — Terminal-Style Left Border */}
      <div className="border-l-2 border-white bg-[#0A0A0A] border border-[#202020] p-4 flex gap-4 items-start shadow-sm">
        <Terminal className="w-4 h-4 text-white shrink-0 mt-0.5" />
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="bg-white text-black px-1.5 py-0.5 font-bold uppercase tracking-wider text-[9px] font-mono">
              Deterministic Math Standard
            </span>
            <span className="text-[9px] font-mono uppercase text-[#AAAAAA]">
              Zero Generative Hallucination Verification
            </span>
          </div>
          <p className="font-mono text-[11px] text-[#AAAAAA] leading-relaxed m-0">
            All liquidity buffers, health metrics, and safe daily allowances are computed exclusively via deterministic Python arithmetic. Generative LLMs are strictly prohibited from calculating numbers, preventing arithmetic hallucinations.
          </p>
        </div>
      </div>

    </div>
  );
}
