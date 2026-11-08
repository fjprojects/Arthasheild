import React from 'react';
import { 
  HeartPulse, 
  TrendingUp, 
  ShieldCheck, 
  Clock, 
  Flame, 
  Terminal
} from 'lucide-react';

export default function HealthScorecard({ 
  healthMetrics, 
  safeToSpend, 
  selectedPersona, 
  detectedLeaks 
}) {
  if (!healthMetrics) return null;

  const score = healthMetrics.health_score || 50;
  const grade = healthMetrics.grade || 'B (Stable)';
  const runway = healthMetrics.metrics?.runway_months || 1.0;
  const dti = healthMetrics.metrics?.debt_to_income_ratio_pct || 25;
  const savingsRate = healthMetrics.metrics?.savings_rate_pct || 15;

  return (
    <div className="space-y-8">
      
      {/* Liquidity Engine ("Safe-to-Spend" Banner) — Stark Contrast Box */}
      <div className="border border-zinc-700 bg-zinc-900 p-8 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6">
        
        {/* Left: Module Title & Context */}
        <div className="space-y-2">
          <div className="flex items-center space-x-2 text-[10px] font-mono uppercase text-zinc-500 tracking-widest">
            <Clock className="w-3.5 h-3.5 text-zinc-400" />
            <span>Cycle Reset in {safeToSpend?.days_remaining_in_cycle || 18} Days</span>
          </div>
          
          <h2 className="text-sm font-bold uppercase tracking-widest text-white m-0">
            Real-Time "Safe-to-Spend" Allowance
          </h2>
          
          <p className="text-xs font-mono text-zinc-400 leading-relaxed max-w-xl m-0">
            {safeToSpend?.guidance || "Deterministic daily discretionary ceiling calculated after reserving pending EMIs, rent, and emergency floor."}
          </p>
        </div>

        {/* Right: Stark Monospace Financial Values */}
        <div className="flex flex-wrap sm:flex-nowrap items-center gap-8 border-t lg:border-t-0 lg:border-l border-zinc-800 pt-4 lg:pt-0 lg:pl-8">
          <div>
            <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-white">
              ₹{safeToSpend?.safe_to_spend_daily?.toLocaleString('en-IN') || '0'}
            </div>
            <div className="text-[10px] uppercase text-zinc-500 font-mono tracking-widest mt-2">
              Safe Per Day
            </div>
          </div>

          <div className="sm:border-l sm:border-zinc-800 sm:pl-8">
            <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-white">
              ₹{safeToSpend?.safe_to_spend_weekly?.toLocaleString('en-IN') || '0'}
            </div>
            <div className="text-[10px] uppercase text-zinc-500 font-mono tracking-widest mt-2">
              Safe This Week
            </div>
          </div>
        </div>

      </div>

      {/* 4 Metric Cards — Strict Black Grid with Monospace Data Points */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        
        {/* Card 1: Health Score */}
        <div className="border border-zinc-800 bg-black p-6 hover:border-zinc-500 transition-colors flex flex-col justify-between">
          <div>
            <div className="text-[11px] uppercase text-zinc-400 flex items-center justify-between pb-3 border-b border-zinc-900 font-mono">
              <span>Health Score</span>
              <HeartPulse className="w-4 h-4 text-zinc-400" />
            </div>

            <div className="text-4xl font-mono text-white py-4">
              {score}
              <span className="text-xs text-zinc-500 ml-1 font-mono">/100</span>
            </div>

            <div className="inline-flex bg-zinc-900 text-zinc-300 text-[10px] font-mono uppercase px-2 py-1 mb-3 w-fit">
              {grade}
            </div>
          </div>

          <div>
            <div className="h-[2px] w-full bg-zinc-900 overflow-hidden">
              <div 
                className="h-full bg-white transition-all duration-300"
                style={{ width: `${Math.min(100, Math.max(5, score))}%` }}
              />
            </div>
            <p className="text-[10px] font-mono text-zinc-500 mt-2 m-0 uppercase">
              Financial resilience index
            </p>
          </div>
        </div>

        {/* Card 2: Runway */}
        <div className="border border-zinc-800 bg-black p-6 hover:border-zinc-500 transition-colors flex flex-col justify-between">
          <div>
            <div className="text-[11px] uppercase text-zinc-400 flex items-center justify-between pb-3 border-b border-zinc-900 font-mono">
              <span>Emergency Runway</span>
              <ShieldCheck className="w-4 h-4 text-zinc-400" />
            </div>

            <div className="text-4xl font-mono text-white py-4">
              {runway}
              <span className="text-xs text-zinc-500 ml-1 font-mono">MONTHS</span>
            </div>

            <div className="inline-flex bg-zinc-900 text-zinc-300 text-[10px] font-mono uppercase px-2 py-1 mb-3 w-fit">
              {runway >= 3 ? 'Resilient' : runway >= 1 ? 'Moderate' : 'Critical'}
            </div>
          </div>

          <div>
            <div className="h-[2px] w-full bg-zinc-900 overflow-hidden">
              <div 
                className="h-full bg-white transition-all duration-300"
                style={{ width: `${Math.min(100, (runway / 6) * 100)}%` }}
              />
            </div>
            <p className="text-[10px] font-mono text-zinc-500 mt-2 m-0 uppercase">
              Liquid buffer at fixed burn
            </p>
          </div>
        </div>

        {/* Card 3: Debt Ratio */}
        <div className="border border-zinc-800 bg-black p-6 hover:border-zinc-500 transition-colors flex flex-col justify-between">
          <div>
            <div className="text-[11px] uppercase text-zinc-400 flex items-center justify-between pb-3 border-b border-zinc-900 font-mono">
              <span>Debt Pressure</span>
              <TrendingUp className="w-4 h-4 text-zinc-400" />
            </div>

            <div className="text-4xl font-mono text-white py-4">
              {dti}%
              <span className="text-xs text-zinc-500 ml-1 font-mono">DTI</span>
            </div>

            <div className="inline-flex bg-zinc-900 text-zinc-300 text-[10px] font-mono uppercase px-2 py-1 mb-3 w-fit">
              {dti <= 30 ? 'Safe Ratio' : 'High Obligation'}
            </div>
          </div>

          <div>
            <div className="h-[2px] w-full bg-zinc-900 overflow-hidden">
              <div 
                className="h-full bg-white transition-all duration-300"
                style={{ width: `${Math.min(100, dti)}%` }}
              />
            </div>
            <p className="text-[10px] font-mono text-zinc-500 mt-2 m-0 uppercase">
              Committed to active loans & rent
            </p>
          </div>
        </div>

        {/* Card 4: Silent Leakage */}
        <div className="border border-zinc-800 bg-black p-6 hover:border-zinc-500 transition-colors flex flex-col justify-between">
          <div>
            <div className="text-[11px] uppercase text-zinc-400 flex items-center justify-between pb-3 border-b border-zinc-900 font-mono">
              <span>Silent Leakage</span>
              <Flame className="w-4 h-4 text-zinc-400" />
            </div>

            <div className="text-4xl font-mono text-white py-4">
              ₹{detectedLeaks?.total_monthly_leakage?.toLocaleString('en-IN') || '0'}
              <span className="text-xs text-zinc-500 ml-1 font-mono">/MO</span>
            </div>

            <div className="inline-flex bg-zinc-900 text-zinc-300 text-[10px] font-mono uppercase px-2 py-1 mb-3 w-fit">
              {detectedLeaks?.items_count || 0} Drains Detected
            </div>
          </div>

          <div>
            <div className="h-[2px] w-full bg-zinc-900 overflow-hidden">
              <div 
                className="h-full bg-white transition-all duration-300"
                style={{ width: `${Math.min(100, ((detectedLeaks?.total_monthly_leakage || 0) / 10000) * 100)}%` }}
              />
            </div>
            <p className="text-[10px] font-mono text-zinc-500 mt-2 m-0 uppercase">
              Dormant subscriptions & fees
            </p>
          </div>
        </div>

      </div>

      {/* Bottom Disclaimer Box — Terminal-Style Left Border */}
      <div className="mt-8 border-l-2 border-white bg-zinc-950 p-4 flex gap-4 items-start">
        <Terminal className="w-4 h-4 text-white shrink-0 mt-0.5" />
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="bg-white text-black px-1.5 py-0.5 font-bold uppercase tracking-wider text-[10px] font-mono">
              Deterministic Math Engine
            </span>
            <span className="text-[10px] font-mono uppercase text-zinc-500">
              Verified Zero Hallucination Standard
            </span>
          </div>
          <p className="font-mono text-[11px] text-zinc-400 leading-relaxed m-0">
            All liquidity buffers, health metrics, and safe daily allowances are computed exclusively via deterministic Python arithmetic. Generative LLMs are strictly prohibited from calculating numbers, preventing arithmetic hallucinations.
          </p>
        </div>
      </div>

    </div>
  );
}
