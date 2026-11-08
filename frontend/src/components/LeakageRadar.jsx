import React from 'react';
import { 
  Flame, 
  AlertTriangle, 
  CheckCircle, 
  Zap, 
  Scissors, 
  HelpCircle,
  TrendingDown,
  DollarSign,
  Terminal
} from 'lucide-react';

export default function LeakageRadar({ leaksSummary }) {
  if (!leaksSummary) return null;

  const totalMonthly = leaksSummary.total_monthly_leakage || 0;
  const totalAnnual = totalMonthly * 12;
  const subscriptions = leaksSummary.dormant_subscriptions || [];

  return (
    <div className="space-y-6">
      
      {/* Leakage Header Banner — Stark Contrast Box */}
      <div className="border border-zinc-700 bg-zinc-900 p-8 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6">
        <div className="space-y-2">
          <div className="flex items-center space-x-2">
            <span className="border border-white px-1.5 py-0.2 text-[9px] font-mono uppercase text-white font-bold">
              RADAR
            </span>
            <span className="text-[10px] font-mono uppercase text-zinc-500 tracking-widest">
              {subscriptions.length} RECURRING DRAINS DETECTED
            </span>
          </div>
          <h3 className="text-sm font-bold uppercase tracking-widest text-white m-0">
            Silent Cashflow Drain & Subscription Traps
          </h3>
          <p className="text-xs font-mono text-zinc-400 max-w-xl leading-relaxed m-0">
            Micro-debits and forgotten auto-renewals quietly erode emergency runway without triggering bank notification thresholds.
          </p>
        </div>

        {/* Financial metrics */}
        <div className="flex flex-wrap sm:flex-nowrap items-center gap-8 border-t lg:border-t-0 lg:border-l border-zinc-800 pt-4 lg:pt-0 lg:pl-8">
          <div>
            <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-white">
              ₹{totalMonthly.toLocaleString('en-IN')}
            </div>
            <div className="text-[10px] uppercase text-zinc-500 font-mono tracking-widest mt-2">
              Monthly Leakage
            </div>
          </div>

          <div className="sm:border-l sm:border-zinc-800 sm:pl-8">
            <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-white">
              ₹{totalAnnual.toLocaleString('en-IN')}
            </div>
            <div className="text-[10px] uppercase text-zinc-500 font-mono tracking-widest mt-2">
              Annualized Loss
            </div>
          </div>
        </div>
      </div>

      {/* Subscriptions Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {subscriptions.map((sub, idx) => (
          <div 
            key={idx}
            className="border border-zinc-800 bg-black p-6 hover:border-zinc-500 transition-colors flex flex-col justify-between space-y-4"
          >
            <div className="flex items-start justify-between border-b border-zinc-900 pb-3">
              <div>
                <h4 className="text-xs font-mono font-bold uppercase tracking-wider text-white m-0">
                  {sub.service}
                </h4>
                <span className="inline-flex bg-zinc-900 text-zinc-300 text-[9px] font-mono uppercase px-2 py-0.5 mt-2">
                  {sub.status.replace(/_/g, ' ')}
                </span>
              </div>
              <div className="text-right">
                <span className="text-2xl font-mono font-bold text-white">
                  ₹{sub.monthly_cost?.toLocaleString('en-IN')}
                </span>
                <span className="text-[10px] font-mono text-zinc-500 block uppercase">
                  / Month
                </span>
              </div>
            </div>

            <div className="border-l-2 border-zinc-700 bg-zinc-950 p-3 space-y-1">
              <span className="text-[9px] font-mono uppercase text-zinc-500 tracking-wider block">
                Prune Protocol
              </span>
              <p className="text-xs font-mono text-zinc-300 m-0">
                {sub.recommendation}
              </p>
            </div>
          </div>
        ))}
      </div>

      {/* Impact Calculation Callout */}
      <div className="border border-zinc-800 bg-zinc-950 p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 font-mono text-xs text-zinc-400">
        <div className="flex items-center space-x-2">
          <Terminal className="w-4 h-4 text-white" />
          <span>
            <strong className="text-white uppercase font-bold">Runway Recovery: </strong> 
            Cancelling these {subscriptions.length} dormant debits restores immediate buffer for critical fixed obligations.
          </span>
        </div>
        <span className="border border-white px-2 py-0.5 text-[10px] uppercase font-bold text-white">
          +₹{totalMonthly.toLocaleString('en-IN')}/MO SAVINGS
        </span>
      </div>

    </div>
  );
}
