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
import { safeCounterpartyName } from '../utils/display';
import { Card } from './ui/Card';

export default function TransactionTable({ transactions = [] }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState('ALL');
  // The selected row is a purely visual state: it marks one entry so the
  // selected, hovered and focused rows can be told apart.
  const [selectedId, setSelectedId] = useState(null);

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
    <Card marker className="p-6 space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-[#202020] pb-4">
        <div>
          <div className="flex items-center space-x-2">
            <span className="border border-white bg-black px-2 py-0.5 text-[9px] font-mono uppercase text-white font-bold tracking-widest">
              LEDGER
            </span>
            <h3 className="text-xs font-mono font-bold uppercase tracking-widest text-white m-0">
              Scrubbed Transaction Journal
            </h3>
          </div>
          <p className="text-[11px] font-mono text-[#AAAAAA] mt-1 m-0">
            Stored locally with pseudonymized identifiers. Zero personal account numbers retained.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Search Input */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-[#AAAAAA] absolute left-2.5 top-2.5" />
            <input
              type="text"
              placeholder="FILTER JOURNAL..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-[#050505] border border-[#202020] pl-8 pr-3 py-1.5 text-[11px] font-mono text-white placeholder-[#666666] focus:outline-none focus:border-white w-52 transition-colors"
            />
          </div>

          {/* Filter Chips */}
          <div className="flex border border-[#202020] bg-[#0A0A0A] p-0.5">
            {[
              { id: 'ALL', label: 'ALL' },
              { id: 'LEAKS', label: 'LEAKS' },
              { id: 'RECURRING', label: 'RECURRING' },
            ].map((f) => (
              <button
                key={f.id}
                onClick={() => setFilterType(f.id)}
                className={`interactive-control text-[9px] font-mono uppercase px-3 py-1 cursor-pointer ${
                  filterType === f.id
                    ? 'bg-white text-black font-bold shadow-[0_0_10px_rgba(255,255,255,0.3)]'
                    : 'text-[#AAAAAA] hover:text-white'
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
        <table className="w-full min-w-[580px] text-left font-mono text-xs">
          <thead>
            <tr className="border-b border-[#202020] text-[#AAAAAA] uppercase text-[9px] tracking-widest">
              <th className="py-2.5 px-3">Timestamp</th>
              <th className="py-2.5 px-3">Scrubbed Entity</th>
              <th className="py-2.5 px-3">Classification</th>
              <th className="py-2.5 px-3">Audit Flags</th>
              <th className="py-2.5 px-3 text-right">Value (INR)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#161616]">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center text-[#8A8A8A] font-mono text-xs">
                  NO ENTRIES MATCH FILTER CRITERIA
                </td>
              </tr>
            ) : (
              filtered.map((tx, idx) => (
                <tr
                  key={tx.id}
                  tabIndex={0}
                  data-selected={selectedId === tx.id ? 'true' : 'false'}
                  onClick={() => setSelectedId((current) => (current === tx.id ? null : tx.id))}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      setSelectedId((current) => (current === tx.id ? null : tx.id));
                    }
                  }}
                  aria-selected={selectedId === tx.id}
                  className={`ledger-row group/row cursor-pointer ${idx % 2 === 0 ? 'bg-black/60' : 'bg-[#0A0A0A]/60'} ${
                    selectedId === tx.id ? 'bg-[#111111]' : 'hover:bg-[#111111]'
                  }`}
                >
                  <td className="py-3 px-3 text-[#AAAAAA] whitespace-nowrap text-[11px]">
                    {tx.date}
                  </td>
                  <td className="py-3 px-3 font-medium text-white">
                    {safeCounterpartyName(tx.description)}
                  </td>
                  <td className="py-3 px-3">
                    <span className="text-[9px] border border-[#303030] bg-[#111111] text-[#AAAAAA] px-2 py-0.5 uppercase tracking-wider">
                      {tx.category}
                    </span>
                  </td>
                  <td className="py-3 px-3 whitespace-nowrap">
                    {/* Audit flags ease into view on hover / focus */}
                    <div className="ledger-flags flex items-center space-x-1.5 opacity-60 group-hover/row:opacity-100 group-focus-within/row:opacity-100">
                      {tx.leak_flag && (
                        <span className="text-[9px] flex items-center gap-1 font-bold border border-white bg-black text-white px-2 py-0.5 uppercase shadow-sm">
                          <Flame className="w-3 h-3 text-white" /> Leak
                        </span>
                      )}
                      {tx.is_recurring && (
                        <span className="text-[9px] flex items-center gap-1 border border-[#404040] bg-[#0A0A0A] text-[#AAAAAA] px-2 py-0.5 uppercase">
                          <Repeat className="w-3 h-3 text-[#AAAAAA]" /> Recurring
                        </span>
                      )}
                      {tx.is_internal_transfer && (
                        <span className="text-[9px] flex items-center gap-1 border border-[#404040] bg-[#0A0A0A] text-[#AAAAAA] px-2 py-0.5 uppercase">
                          <Repeat className="w-3 h-3 text-[#AAAAAA]" /> Internal
                        </span>
                      )}
                      {tx.hidden_fee && (
                        <span className="text-[9px] font-bold border border-[#AAAAAA] bg-[#111111] text-white px-1.5 py-0.5 uppercase">
                          +₹{tx.hidden_fee} Fee
                        </span>
                      )}
                    </div>
                  </td>
                  <td className={`py-3 px-3 text-right font-bold whitespace-nowrap text-sm ${
                    tx.type === 'CREDIT' ? 'text-white' : 'text-[#AAAAAA]'
                  }`}>
                    {tx.type === 'CREDIT' ? '+' : '-'}₹{Number(tx.amount ?? 0).toLocaleString('en-IN')}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

    </Card>
  );
}
