import React, { useState, useEffect } from 'react';
import { 
  Calculator, 
  AlertTriangle, 
  ShieldAlert, 
  CheckCircle, 
  HelpCircle, 
  Info,
  TrendingDown,
  Sparkles,
  Terminal
} from 'lucide-react';
import api from '../services/api';

export default function EmiSimulator({ discretionaryBuffer = 14000 }) {
  const [itemName, setItemName] = useState('Flagship Smartphone');
  const [price, setPrice] = useState(65000);
  const [tenure, setTenure] = useState(12);
  const [downPayment, setDownPayment] = useState(0);
  const [nominalApr, setNominalApr] = useState(0.0);
  const [monthlyFee, setMonthlyFee] = useState(199.0);
  const [simulation, setSimulation] = useState(null);
  const [loading, setLoading] = useState(false);

  // Debounced auto-simulation on parameter change
  useEffect(() => {
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const result = await api.simulateEmi({
          item_name: itemName,
          price: Number(price),
          tenure_months: Number(tenure),
          down_payment: Number(downPayment),
          nominal_apr: Number(nominalApr),
          monthly_processing_fee: Number(monthlyFee),
          discretionary_buffer: Number(discretionaryBuffer),
        });
        setSimulation(result);
      } catch (err) {
        console.error('Simulation failed:', err);
      } finally {
        setLoading(false);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [itemName, price, tenure, downPayment, nominalApr, monthlyFee, discretionaryBuffer]);

  return (
    <div className="space-y-6">
      
      {/* Header */}
      <div className="border border-zinc-800 bg-black p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <span className="border border-white px-1.5 py-0.2 text-[9px] font-mono uppercase text-white font-bold">
              SIMULATOR
            </span>
            <h3 className="text-xs font-mono font-bold uppercase tracking-widest text-white m-0">
              "What-If" EMI & Affordability Reality Check
            </h3>
          </div>
          <p className="text-[11px] font-mono text-zinc-500 mt-1 m-0">
            Expose deceptive 0% No-Cost EMI fine print, hidden processing charges, and true effective APR before purchase.
          </p>
        </div>

        <div className="text-[10px] font-mono uppercase px-3 py-1.5 border border-zinc-700 bg-zinc-900 text-white">
          Discretionary Floor: ₹{discretionaryBuffer.toLocaleString('en-IN')}/MO
        </div>
      </div>

      {/* Simulator Inputs & Output Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* Input Controls (5 Cols) */}
        <div className="lg:col-span-5 border border-zinc-800 bg-black p-6 space-y-5 font-mono">
          <span className="text-[10px] font-bold uppercase tracking-widest text-zinc-400 block border-b border-zinc-900 pb-2">
            Loan & Purchase Parameters
          </span>

          {/* Item Name */}
          <div className="space-y-1.5">
            <label className="text-[10px] uppercase text-zinc-400">Target Purchase</label>
            <input
              type="text"
              value={itemName}
              onChange={(e) => setItemName(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 px-3 py-2 text-xs text-white focus:outline-none focus:border-white transition-colors"
            />
          </div>

          {/* Price Slider */}
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-[10px] uppercase text-zinc-400">Purchase Value</span>
              <span className="font-bold text-white">₹{Number(price).toLocaleString('en-IN')}</span>
            </div>
            <input
              type="range"
              min={5000}
              max={250000}
              step={1000}
              value={price}
              onChange={(e) => setPrice(Number(e.target.value))}
              className="w-full accent-white cursor-pointer"
            />
          </div>

          {/* Tenure Slider */}
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-[10px] uppercase text-zinc-400">Tenure</span>
              <span className="font-bold text-white">{tenure} Months</span>
            </div>
            <div className="grid grid-cols-4 gap-2 pt-1">
              {[3, 6, 9, 12, 18, 24].map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setTenure(m)}
                  className={`text-[10px] uppercase py-1 border transition cursor-pointer ${
                    tenure === m
                      ? 'border-white bg-white text-black font-bold'
                      : 'border-zinc-800 bg-zinc-950 text-zinc-400 hover:text-white'
                  }`}
                >
                  {m}M
                </button>
              ))}
            </div>
          </div>

          {/* Stated APR vs Monthly Fee */}
          <div className="grid grid-cols-2 gap-4 pt-2 border-t border-zinc-900">
            <div className="space-y-1">
              <label className="text-[10px] uppercase text-zinc-400">Stated APR (%)</label>
              <input
                type="number"
                step="0.5"
                value={nominalApr}
                onChange={(e) => setNominalApr(Number(e.target.value))}
                className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 text-xs text-white focus:outline-none focus:border-white"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] uppercase text-zinc-400">Processing Fee / Mo</label>
              <input
                type="number"
                step="10"
                value={monthlyFee}
                onChange={(e) => setMonthlyFee(Number(e.target.value))}
                className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 text-xs text-white focus:outline-none focus:border-white"
              />
            </div>
          </div>
        </div>

        {/* Results & Truth Engine (7 Cols) */}
        <div className="lg:col-span-7 space-y-6">
          {simulation ? (
            <div className="border border-zinc-700 bg-zinc-900 p-8 space-y-6">
              
              {/* Top Banner: True APR vs Advertised */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-6 border-b border-zinc-800 gap-4">
                <div>
                  <span className="text-[10px] font-mono uppercase text-zinc-500 tracking-widest block">
                    Effective Borrowing Cost
                  </span>
                  <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-white mt-1">
                    {simulation.effective_apr_pct}%
                  </div>
                  <div className="text-[10px] font-mono text-zinc-400 uppercase mt-1">
                    Versus {nominalApr}% Advertised "No-Cost" APR
                  </div>
                </div>

                <div className="text-right sm:border-l sm:border-zinc-800 sm:pl-8">
                  <span className="text-[10px] font-mono uppercase text-zinc-500 tracking-widest block">
                    True Monthly Commitment
                  </span>
                  <div className="text-4xl sm:text-5xl font-mono tracking-tighter text-white mt-1">
                    ₹{simulation.monthly_emi?.toLocaleString('en-IN')}
                  </div>
                  <div className="text-[10px] font-mono text-zinc-400 uppercase mt-1">
                    Includes GST & recurring levies
                  </div>
                </div>
              </div>

              {/* Cost Decomposition Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 font-mono text-xs">
                <div className="border border-zinc-800 bg-black p-3 space-y-1">
                  <span className="text-[10px] uppercase text-zinc-500">Principal</span>
                  <div className="text-base font-bold text-white">
                    ₹{simulation.cost_breakdown?.principal_financed?.toLocaleString('en-IN')}
                  </div>
                </div>

                <div className="border border-zinc-800 bg-black p-3 space-y-1">
                  <span className="text-[10px] uppercase text-zinc-500">Hidden Fees & Tax</span>
                  <div className="text-base font-bold text-white">
                    ₹{simulation.cost_breakdown?.total_fees_and_gst?.toLocaleString('en-IN')}
                  </div>
                </div>

                <div className="border border-zinc-800 bg-black p-3 space-y-1 col-span-2 sm:col-span-1">
                  <span className="text-[10px] uppercase text-zinc-500">Total Outflow</span>
                  <div className="text-base font-bold text-white">
                    ₹{simulation.cost_breakdown?.total_cash_outflow?.toLocaleString('en-IN')}
                  </div>
                </div>
              </div>

              {/* Affordability & Stress Test Verdict */}
              <div className="border-l-2 border-white bg-zinc-950 p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="bg-white text-black px-1.5 py-0.5 font-bold uppercase tracking-wider text-[10px] font-mono">
                    Affordability Verdict: {simulation.affordability_verdict?.status}
                  </span>
                  <span className="text-[10px] font-mono uppercase text-zinc-400">
                    {simulation.affordability_verdict?.buffer_consumed_pct}% of Free Buffer
                  </span>
                </div>
                <p className="text-xs font-mono text-zinc-300 leading-relaxed m-0">
                  {simulation.affordability_verdict?.explanation}
                </p>
              </div>

            </div>
          ) : (
            <div className="border border-zinc-800 bg-black p-12 flex flex-col items-center justify-center text-zinc-600 font-mono text-xs space-y-2">
              <Terminal className="w-6 h-6 text-zinc-700" />
              <span>AWAITING SIMULATION PARAMETERS</span>
            </div>
          )}
        </div>

      </div>

    </div>
  );
}
