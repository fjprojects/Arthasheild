import React, { useState } from 'react';
import { 
  ArrowDownLeft, 
  ArrowUpRight, 
  Flame, 
  Repeat, 
  Search, 
  Filter,
  ShieldCheck 
} from 'lucide-react';

export default function TransactionTable({ transactions = [] }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState('ALL');

  const filtered = transactions.filter((t) => {
    const matchesSearch = t.description?.toLowerCase().includes(searchTerm.toLowerCase()) ||
                          t.category?.toLowerCase().includes(searchTerm.toLowerCase());
    if (filterType === 'LEAKS') return matchesSearch && t.leak_flag;
    if (filterType === 'RECURRING') return matchesSearch && t.is_recurring;
    if (filterType === 'DEBIT') return matchesSearch && t.type === 'DEBIT';
    if (filterType === 'CREDIT') return matchesSearch && t.type === 'CREDIT';
    return matchesSearch;
  });

  return (
    <div className="border border-zinc-800 bg-black p-6 space-y-6">
      
      {/* Header & Filter Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-zinc-900 pb-4">
        <div>
          <div className="flex items-center space-x-2">
            <span className="border border-white px-1.5 py-0.2 text-[9px] font-mono uppercase text-white font-bold">
              LEDGER
            </span>
            <h3 className="text-xs font-mono font-bold uppercase tracking-widest text-white m-0">
              Scrubbed Transaction Journal
            </h3>
          </div>
          <p className="text-[11px] font-mono text-zinc-500 mt-1 m-0">
            Stored locally with pseudonymized identifiers. Zero personal account numbers retained.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Search Input */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-2.5" />
            <input
              type="text"
              placeholder="FILTER JOURNAL..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-zinc-950 border border-zinc-800 pl-8 pr-3 py-1.5 text-[11px] font-mono text-white placeholder-zinc-600 focus:outline-none focus:border-white w-52 transition-colors"
            />
          </div>

          {/* Filter Chips */}
          <div className="flex border border-zinc-800 bg-zinc-950 p-0.5">
            {[
              { id: 'ALL', label: 'ALL' },
              { id: 'LEAKS', label: 'LEAKS' },
              { id: 'RECURRING', label: 'RECURRING' },
            ].map((f) => (
              <button
                key={f.id}
                onClick={() => setFilterType(f.id)}
                className={`text-[10px] font-mono uppercase px-3 py-1 transition cursor-pointer ${
                  filterType === f.id
                    ? 'bg-white text-black font-bold'
                    : 'text-zinc-500 hover:text-white'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left font-mono text-xs">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500 uppercase text-[10px] tracking-widest">
              <th className="py-2.5 px-3">Timestamp</th>
              <th className="py-2.5 px-3">Scrubbed Entity</th>
              <th className="py-2.5 px-3">Classification</th>
              <th className="py-2.5 px-3">Audit Flags</th>
              <th className="py-2.5 px-3 text-right">Value (INR)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-900">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center text-zinc-600 font-mono text-xs">
                  NO ENTRIES MATCH FILTER CRITERIA
                </td>
              </tr>
            ) : (
              filtered.map((tx) => (
                <tr key={tx.id} className="hover:bg-zinc-950 transition-colors">
                  <td className="py-3 px-3 text-zinc-500 whitespace-nowrap text-[11px]">
                    {tx.date}
                  </td>
                  <td className="py-3 px-3 font-medium text-white">
                    {tx.description}
                  </td>
                  <td className="py-3 px-3">
                    <span className="text-[10px] border border-zinc-800 bg-zinc-950 text-zinc-400 px-2 py-0.5 uppercase tracking-wider">
                      {tx.category}
                    </span>
                  </td>
                  <td className="py-3 px-3 whitespace-nowrap">
                    <div className="flex items-center space-x-1.5">
                      {tx.leak_flag && (
                        <span className="text-[10px] flex items-center gap-1 font-bold border border-white bg-zinc-900 text-white px-2 py-0.5 uppercase">
                          <Flame className="w-3 h-3 text-white" /> Leak
                        </span>
                      )}
                      {tx.is_recurring && (
                        <span className="text-[10px] flex items-center gap-1 border border-zinc-800 bg-zinc-950 text-zinc-400 px-2 py-0.5 uppercase">
                          <Repeat className="w-3 h-3 text-zinc-500" /> Recurring
                        </span>
                      )}
                      {tx.hidden_fee && (
                        <span className="text-[10px] font-bold border border-zinc-700 bg-zinc-900 text-white px-1.5 py-0.5 uppercase">
                          +₹{tx.hidden_fee} Fee
                        </span>
                      )}
                    </div>
                  </td>
                  <td className={`py-3 px-3 text-right font-bold whitespace-nowrap text-sm ${
                    tx.type === 'CREDIT' ? 'text-white' : 'text-zinc-300'
                  }`}>
                    {tx.type === 'CREDIT' ? '+' : '-'}₹{tx.amount?.toLocaleString('en-IN')}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

    </div>
  );
}
