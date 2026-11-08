import React, { useState, useEffect } from 'react';
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
  Clock
} from 'lucide-react';
import api from '../services/api';

export default function FinancialIntelligence({ sessionId = null, onRefreshParent }) {
  const [includePersona, setIncludePersona] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Phase 2 Datasets
  const [categorized, setCategorized] = useState([]);
  const [budget, setBudget] = useState(null);
  const [subscriptions, setSubscriptions] = useState([]);
  const [unusual, setUnusual] = useState([]);
  const [patterns, setPatterns] = useState(null);

  // Fetch all 5 intelligence APIs
  const fetchAllInsights = async () => {
    setLoading(true);
    setError(null);
    try {
      const [catRes, budgetRes, subsRes, unusualRes, patternsRes] = await Promise.all([
        api.getCategorization(sessionId, includePersona),
        api.getMonthlyBudget(sessionId, 2026, 10, includePersona),
        api.getSubscriptions(sessionId, includePersona),
        api.getUnusualSpending(sessionId, includePersona),
        api.getSpendingPatterns(sessionId, 6, includePersona),
      ]);

      setCategorized(catRes.transactions || []);
      setBudget(budgetRes);
      setSubscriptions(subsRes.subscriptions || []);
      setUnusual(unusualRes.flagged || []);
      setPatterns(patternsRes);
    } catch (err) {
      console.error('Failed to load financial intelligence:', err);
      setError(err.response?.data?.error || 'Failed to fetch financial intelligence from backend.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAllInsights();
  }, [sessionId, includePersona]);

  const formatInr = (val) => {
    const num = parseFloat(val) || 0;
    return `₹${num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-150 font-mono">
      
      {/* Top Banner & Controls */}
      <div className="border border-zinc-700 bg-zinc-900 p-8 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6">
        <div className="space-y-2">
          <div className="flex items-center space-x-2">
            <span className="border border-white px-1.5 py-0.2 text-[9px] uppercase text-white font-bold">
              PHASE 2 ENGINE
            </span>
            <span className="text-[10px] uppercase text-zinc-500 tracking-widest">
              FINANCIAL INTELLIGENCE COGNITION
            </span>
          </div>
          <h2 className="text-sm font-bold uppercase tracking-widest text-white m-0">
            Automated Cashflow & Anomaly Intelligence
          </h2>
          <p className="text-xs text-zinc-400 max-w-xl leading-relaxed m-0">
            Real-time deterministic analysis: category categorization, monthly budget reconciliation, recurring subscription detection, explainable median outlier modeling, and 6-month trend trajectory.
          </p>
        </div>

        {/* Toggle & Refresh Actions */}
        <div className="flex flex-wrap items-center gap-4 border-t lg:border-t-0 lg:border-l border-zinc-800 pt-4 lg:pt-0 lg:pl-8">
          <label className="flex items-center space-x-2 cursor-pointer select-none text-[10px] text-zinc-400 uppercase">
            <input 
              type="checkbox"
              checked={includePersona}
              onChange={(e) => setIncludePersona(e.target.checked)}
              className="rounded-none border-zinc-700 bg-black accent-white cursor-pointer"
            />
            <span>Include Synthetic Persona</span>
          </label>

          <button
            onClick={() => {
              fetchAllInsights();
              if (onRefreshParent) onRefreshParent();
            }}
            disabled={loading}
            className="text-[10px] uppercase tracking-wider px-4 py-2 bg-white text-black font-bold hover:bg-zinc-200 transition flex items-center gap-2 disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>{loading ? 'Reconciling...' : 'Sync Intelligence'}</span>
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="border border-zinc-700 bg-zinc-950 p-4 text-xs text-zinc-300 flex items-center gap-3">
          <AlertTriangle className="w-4 h-4 text-white shrink-0" />
          <span>Error loading intelligence: {error}</span>
        </div>
      )}

      {/* 1. Monthly Budget Analyzer Panel */}
      {budget && (
        <div className="border border-zinc-800 bg-black p-6 space-y-6">
          <div className="flex items-center justify-between border-b border-zinc-900 pb-4">
            <div className="flex items-center space-x-2">
              <Calendar className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                1. Monthly Budget Analyzer ({budget.year}-{String(budget.month).padStart(2, '0')})
              </h3>
            </div>
            {budget.overspending ? (
              <span className="border border-white bg-black px-2 py-0.5 text-[9px] uppercase font-bold text-white flex items-center gap-1">
                <AlertTriangle className="w-3 h-3 text-white" />
                Deficit Detected
              </span>
            ) : (
              <span className="border border-zinc-700 bg-zinc-950 px-2 py-0.5 text-[9px] uppercase text-zinc-400">
                Surplus Inflow
              </span>
            )}
          </div>

          {/* 3 Metric Summary */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="border border-zinc-800 bg-zinc-950 p-4">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wider block">Total Inflow (Income)</span>
              <div className="text-2xl font-bold text-white mt-1">{formatInr(budget.income)}</div>
            </div>
            <div className="border border-zinc-800 bg-zinc-950 p-4">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wider block">Total Outflow (Expenses)</span>
              <div className="text-2xl font-bold text-white mt-1">{formatInr(budget.expenses)}</div>
            </div>
            <div className="border border-zinc-800 bg-zinc-950 p-4">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wider block">Net Savings Margin</span>
              <div className={`text-2xl font-bold mt-1 ${parseFloat(budget.savings) < 0 ? 'text-zinc-400' : 'text-white'}`}>
                {formatInr(budget.savings)}
              </div>
            </div>
          </div>

          {/* Category-wise spending breakdown */}
          <div className="space-y-3 pt-2">
            <span className="text-[10px] text-zinc-500 uppercase tracking-wider block">Category Spending Breakdown</span>
            {Object.keys(budget.category_spending || {}).length === 0 ? (
              <p className="text-xs text-zinc-600">No expense records found for this billing period.</p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {Object.entries(budget.category_spending).map(([cat, amt]) => (
                  <div key={cat} className="border border-zinc-800 bg-zinc-950 p-3">
                    <span className="text-[9px] uppercase text-zinc-500 block">{cat}</span>
                    <span className="text-sm font-bold text-white block mt-0.5">{formatInr(amt)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 2-Column Grid: Subscriptions & Unusual Spending */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* 2. Subscription Detector */}
        <div className="border border-zinc-800 bg-black p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
            <div className="flex items-center space-x-2">
              <Repeat className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                2. Subscription Traps ({subscriptions.length})
              </h3>
            </div>
            <span className="text-[9px] uppercase text-zinc-500">Auto-Debit Monitor</span>
          </div>

          {subscriptions.length === 0 ? (
            <div className="py-8 text-center text-zinc-600 text-xs">
              Zero recurring subscriptions identified in session journal.
            </div>
          ) : (
            <div className="space-y-3">
              {subscriptions.map((sub, idx) => (
                <div key={idx} className="border border-zinc-800 bg-zinc-950 p-3 flex items-center justify-between">
                  <div>
                    <span className="text-xs font-bold text-white block uppercase">{sub.identifier}</span>
                    <span className="text-[9px] text-zinc-500 block mt-0.5">
                      Annualized: {formatInr(sub.yearly_estimate)}
                      {sub.candidates && ' • Multiple hits'}
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="text-sm font-bold text-white block">{formatInr(sub.monthly_estimate)}</span>
                    <span className="text-[9px] text-zinc-500 uppercase">/ Month</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 3. Unusual Spending Detector */}
        <div className="border border-zinc-800 bg-black p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                3. Unusual Outlier Spikes ({unusual.length})
              </h3>
            </div>
            <span className="text-[9px] uppercase border border-zinc-700 bg-zinc-950 px-1.5 py-0.2 text-zinc-400">
              Median 3× Baseline
            </span>
          </div>

          {unusual.length === 0 ? (
            <div className="py-8 text-center text-zinc-600 text-xs flex flex-col items-center justify-center space-y-2">
              <CheckCircle2 className="w-6 h-6 text-zinc-700" />
              <span>Zero unusual spikes or duplicate transactions detected.</span>
            </div>
          ) : (
            <div className="space-y-3">
              {unusual.map((item, idx) => (
                <div key={idx} className="border border-zinc-800 bg-zinc-950 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold text-white block uppercase">{item.merchant}</span>
                      <span className="text-[9px] text-zinc-500 block">{item.date}</span>
                    </div>
                    <div className="text-right">
                      <span className="text-sm font-bold text-white block">{formatInr(item.amount)}</span>
                      <span className="text-[9px] uppercase font-bold text-zinc-400 border border-zinc-800 bg-black px-1.5 py-0.2">
                        {item.reason === 'large_amount' ? 'Large Outlier' : 'Duplicate Alert'}
                      </span>
                    </div>
                  </div>
                  {item.baseline && item.threshold && (
                    <div className="text-[10px] text-zinc-500 border-t border-zinc-900 pt-1 flex justify-between">
                      <span>Peer Median: {formatInr(item.baseline)}</span>
                      <span>Trigger Threshold: {formatInr(item.threshold)}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

      </div>

      {/* 4. Spending Patterns & Category Trends */}
      {patterns && patterns.category_trends && (
        <div className="border border-zinc-800 bg-black p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
            <div className="flex items-center space-x-2">
              <TrendingUp className="w-4 h-4 text-white" />
              <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
                4. Multi-Month Trend Radar (6 Months Trajectory)
              </h3>
            </div>
            <span className="text-[9px] uppercase text-zinc-500">Historical Drift</span>
          </div>

          {Object.keys(patterns.category_trends).length === 0 ? (
            <div className="py-6 text-center text-zinc-600 text-xs">
              Insufficient historical multi-month statements to compute velocity trends.
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {Object.entries(patterns.category_trends).map(([cat, trend]) => (
                <div key={cat} className="border border-zinc-800 bg-zinc-950 p-3 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase text-white">{cat}</span>
                    {trend.trend === 'increase' ? (
                      <ArrowUpRight className="w-3.5 h-3.5 text-white" />
                    ) : (
                      <ArrowDownLeft className="w-3.5 h-3.5 text-zinc-500" />
                    )}
                  </div>
                  <div className="text-sm font-bold text-white">
                    {trend.pct_change > 0 ? `+${trend.pct_change}%` : `${trend.pct_change}%`}
                  </div>
                  <span className="text-[9px] uppercase text-zinc-500 block">
                    {trend.trend === 'increase' ? 'Expense Acceleration' : 'Expense Contraction'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 5. Scrubbed Categorized Transactions Summary */}
      <div className="border border-zinc-800 bg-black p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
          <div className="flex items-center space-x-2">
            <Layers className="w-4 h-4 text-white" />
            <h3 className="text-xs font-bold uppercase tracking-widest text-white m-0">
              5. Category Normalization Journal ({categorized.length} Records)
            </h3>
          </div>
          <span className="text-[9px] uppercase text-zinc-500">Rule-Based Classification</span>
        </div>

        {categorized.length === 0 ? (
          <div className="py-6 text-center text-zinc-600 text-xs">
            No transactions currently in database for this session. Use Privacy Inspector to upload and persist a bank statement.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500 uppercase text-[10px] tracking-widest">
                  <th className="py-2 px-3">Date</th>
                  <th className="py-2 px-3">Merchant</th>
                  <th className="py-2 px-3">Category</th>
                  <th className="py-2 px-3">Type</th>
                  <th className="py-2 px-3 text-right">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-900">
                {categorized.slice(0, 10).map((tx) => (
                  <tr key={tx.id} className="hover:bg-zinc-950">
                    <td className="py-2 px-3 text-zinc-400">{tx.date}</td>
                    <td className="py-2 px-3 text-white font-bold">{tx.merchant}</td>
                    <td className="py-2 px-3">
                      <span className="border border-zinc-700 bg-zinc-950 px-1.5 py-0.5 text-[9px] uppercase text-zinc-300">
                        {tx.category}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-zinc-400">{tx.type}</td>
                    <td className="py-2 px-3 text-right text-white font-bold">{formatInr(tx.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {categorized.length > 10 && (
              <div className="text-[10px] text-zinc-500 text-center py-2 border-t border-zinc-900 uppercase">
                Showing top 10 of {categorized.length} transactions
              </div>
            )}
          </div>
        )}
      </div>

    </div>
  );
}

