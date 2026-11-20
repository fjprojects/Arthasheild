import React, { useState, useEffect } from 'react';
import { 
  ArrowDownLeft, 
  ArrowUpRight, 
  Flame, 
  Repeat, 
  Search, 
  Filter,
  ShieldCheck,
  Edit2,
  Check,
  X,
  ChevronLeft,
  ChevronRight,
  Loader2
} from 'lucide-react';
import { safeCounterpartyName } from '../utils/display';
import { Card } from './ui/Card';
import api from '../services/api';

const CREDIT_CATEGORIES = [
  'Freelance Income',
  'Salary',
  'Allowance',
  'Internal Transfer',
  'Reimbursement',
  'Refund / Reversal',
  'Unclassified Inflow',
  'Other Discretionary',
  'General',
];

const DEBIT_CATEGORIES = [
  'Food & Dining',
  'Shopping',
  'Bills & Utilities',
  'Travel & Commute',
  'Rent & Housing',
  'Subscriptions',
  'Healthcare',
  'EMI / Loan',
  'Entertainment',
  'Education & Learning',
  'Internal Transfer',
  'Other Discretionary',
  'General',
];

const VALID_CATEGORIES = Array.from(new Set([...DEBIT_CATEGORIES, ...CREDIT_CATEGORIES]));

export default function TransactionTable({ 
  transactions = [], 
  onTransactionUpdated = null,
  dataSourceLabel = null
}) {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState('ALL');
  const [selectedId, setSelectedId] = useState(null);

  // Pagination state
  const [pageSize, setPageSize] = useState(10); // 10, 25, 50, or 'ALL'
  const [currentPage, setCurrentPage] = useState(1);

  // Inline editing state
  const [editingTxId, setEditingTxId] = useState(null);
  const [editCategory, setEditCategory] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [feedback, setFeedback] = useState(null); // { id, type: 'success' | 'error' | 'info', message }

  // Filter transactions
  const filtered = transactions.filter((t) => {
    const matchesSearch = 
      t.description?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.category?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      String(t.amount).includes(searchTerm);
    if (filterType === 'LEAKS') return matchesSearch && t.leak_flag;
    if (filterType === 'RECURRING') return matchesSearch && t.is_recurring;
    if (filterType === 'DEBIT') return matchesSearch && t.type === 'DEBIT';
    if (filterType === 'CREDIT') return matchesSearch && t.type === 'CREDIT';
    return matchesSearch;
  });

  // Reset to page 1 whenever search, filter, or page size changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchTerm, filterType, pageSize]);

  // Clear feedback after 4 seconds
  useEffect(() => {
    if (feedback) {
      const timer = setTimeout(() => setFeedback(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [feedback]);

  // Compute pagination bounds
  const totalCount = filtered.length;
  const effectivePageSize = pageSize === 'ALL' ? (totalCount || 1) : Number(pageSize);
  const totalPages = Math.max(1, Math.ceil(totalCount / effectivePageSize));
  const safeCurrentPage = Math.min(Math.max(1, currentPage), totalPages);

  const startIndex = pageSize === 'ALL' ? 0 : (safeCurrentPage - 1) * effectivePageSize;
  const endIndex = pageSize === 'ALL' ? totalCount : Math.min(startIndex + effectivePageSize, totalCount);
  const displayedTransactions = filtered.slice(startIndex, endIndex);

  const startEdit = (tx, e) => {
    e.stopPropagation();
    setEditingTxId(tx.id);
    setEditCategory(tx.category || 'General');
  };

  const cancelEdit = (e) => {
    if (e) e.stopPropagation();
    setEditingTxId(null);
    setEditCategory('');
  };

  const saveEdit = async (tx, e) => {
    if (e) e.stopPropagation();
    if (!editCategory) return;

    if (editCategory.toLowerCase() === (tx.category || '').toLowerCase()) {
      setFeedback({
        id: tx.id,
        type: 'info',
        message: 'Category unchanged'
      });
      setEditingTxId(null);
      return;
    }

    setIsSaving(true);
    try {
      const isTransfer = editCategory === 'Internal Transfer' || editCategory.toLowerCase() === 'transfer';
      const res = await api.correctTransaction(tx.id, {
        new_category: editCategory,
        is_transfer: isTransfer
      });

      if (res.status === 'CORRECTION_SAVED' || res.status === 'NO_CHANGE') {
        setFeedback({
          id: tx.id,
          type: 'success',
          message: `Category updated to ${editCategory}`
        });
        setEditingTxId(null);
        if (onTransactionUpdated) {
          onTransactionUpdated(tx.id, editCategory);
        }
      } else {
        setFeedback({
          id: tx.id,
          type: 'error',
          message: res.error || 'Failed to update category'
        });
      }
    } catch (err) {
      setFeedback({
        id: tx.id,
        type: 'error',
        message: err.response?.data?.error || err.message || 'Correction failed'
      });
    } finally {
      setIsSaving(false);
    }
  };

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
            {dataSourceLabel && (
              <span className="border border-[#404040] bg-[#111111] px-2 py-0.5 text-[9px] font-mono uppercase text-[#AAAAAA]">
                {dataSourceLabel}
              </span>
            )}
          </div>
          <p className="text-[11px] font-mono text-[#AAAAAA] mt-1 m-0">
            Stored server-side in this session's ledger with sanitized labels. Inline editing supports human categorization corrections.
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
              aria-label="Filter transaction journal"
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-[#050505] border border-[#202020] pl-8 pr-3 py-1.5 text-[11px] font-mono text-white placeholder-[#666666] focus:outline-none focus:border-white w-52 transition-colors"
            />
          </div>

          {/* Filter Chips */}
          <div className="flex border border-[#202020] bg-[#0A0A0A] p-0.5" role="toolbar" aria-label="Transaction filters">
            {[
              { id: 'ALL', label: 'ALL' },
              { id: 'LEAKS', label: 'LEAKS' },
              { id: 'RECURRING', label: 'RECURRING' },
              { id: 'DEBIT', label: 'DEBIT' },
              { id: 'CREDIT', label: 'CREDIT' },
            ].map((f) => (
              <button
                key={f.id}
                onClick={() => setFilterType(f.id)}
                className={`interactive-control text-[9px] font-mono uppercase px-2.5 py-1 cursor-pointer transition-colors ${
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

      {/* Range and Page Size Indicator Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-[11px] font-mono text-[#AAAAAA] pb-1">
        <div className="flex items-center gap-2">
          <span>
            {totalCount === 0 ? (
              'Showing 0 of 0 transactions'
            ) : (
              <>
                Showing <strong className="text-white">{startIndex + 1}–{endIndex}</strong> of{' '}
                <strong className="text-white">{totalCount}</strong> transactions
                {totalCount !== transactions.length && (
                  <span className="text-[#666666] ml-1">
                    (filtered from {transactions.length} total)
                  </span>
                )}
              </>
            )}
          </span>
        </div>

        {/* Page Size Selector */}
        <div className="flex items-center gap-2">
          <span className="text-[9px] uppercase tracking-wider text-[#888888]">Rows per page:</span>
          <div className="flex border border-[#202020] bg-black">
            {[10, 25, 50, 'ALL'].map((size) => (
              <button
                key={size}
                onClick={() => setPageSize(size)}
                className={`px-2 py-0.5 text-[9px] font-mono cursor-pointer transition-colors ${
                  pageSize === size
                    ? 'bg-white text-black font-bold'
                    : 'text-[#AAAAAA] hover:text-white'
                }`}
                aria-label={`Show ${size} transactions per page`}
              >
                {size}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Global Feedback Banner */}
      {feedback && (
        <div
          role="status"
          aria-live="polite"
          className={`px-3 py-2 border font-mono text-xs flex items-center justify-between ${
            feedback.type === 'success'
              ? 'border-white bg-[#0A0A0A] text-white'
              : feedback.type === 'error'
              ? 'border-white bg-black text-white'
              : 'border-[#404040] bg-[#111111] text-[#AAAAAA]'
          }`}
        >
          <span>{feedback.message}</span>
          <button
            onClick={() => setFeedback(null)}
            className="text-[#AAAAAA] hover:text-white p-0.5"
            aria-label="Dismiss feedback"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left font-mono text-xs">
          <thead>
            <tr className="border-b border-[#202020] text-[#AAAAAA] uppercase text-[9px] tracking-widest">
              <th className="py-2.5 px-3">Timestamp</th>
              <th className="py-2.5 px-3">Scrubbed Entity</th>
              <th className="py-2.5 px-3">Classification & Edit</th>
              <th className="py-2.5 px-3">Audit Flags</th>
              <th className="py-2.5 px-3 text-right">Value (INR)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#161616]">
            {displayedTransactions.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center text-[#8A8A8A] font-mono text-xs">
                  NO ENTRIES MATCH FILTER CRITERIA
                </td>
              </tr>
            ) : (
              displayedTransactions.map((tx, idx) => {
                const isEditingThis = editingTxId === tx.id;

                return (
                  <tr
                    key={tx.id}
                    tabIndex={0}
                    data-selected={selectedId === tx.id ? 'true' : 'false'}
                    onClick={() => setSelectedId((current) => (current === tx.id ? null : tx.id))}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        if (!isEditingThis) {
                          event.preventDefault();
                          setSelectedId((current) => (current === tx.id ? null : tx.id));
                        }
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
                      {isEditingThis ? (
                        <div
                          className="flex items-center gap-1.5"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <select
                            value={editCategory}
                            onChange={(e) => setEditCategory(e.target.value)}
                            disabled={isSaving}
                            aria-label={`Select new category for ${tx.description}`}
                            className="bg-[#050505] border border-white text-white text-[11px] font-mono px-2 py-1 focus:outline-none focus:ring-1 focus:ring-white"
                          >
                            {(tx.type === 'CREDIT' ? CREDIT_CATEGORIES : DEBIT_CATEGORIES).map((cat) => (
                              <option key={cat} value={cat} className="bg-black text-white">
                                {cat}
                              </option>
                            ))}
                          </select>
                          <button
                            onClick={(e) => saveEdit(tx, e)}
                            disabled={isSaving}
                            aria-label="Confirm category change"
                            className="border border-white bg-white text-black p-1 hover:bg-[#E0E0E0] disabled:opacity-50 transition-colors"
                            title="Confirm"
                          >
                            {isSaving ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Check className="w-3.5 h-3.5 font-bold" />
                            )}
                          </button>
                          <button
                            onClick={cancelEdit}
                            disabled={isSaving}
                            aria-label="Cancel category change"
                            className="border border-[#404040] bg-black text-[#AAAAAA] p-1 hover:text-white hover:border-white transition-colors"
                            title="Cancel"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <span className="text-[9px] border border-[#303030] bg-[#111111] text-[#CCCCCC] px-2 py-0.5 uppercase tracking-wider">
                            {tx.category || 'General'}
                          </span>
                          <button
                            onClick={(e) => startEdit(tx, e)}
                            aria-label={`Edit category for ${safeCounterpartyName(tx.description)}`}
                            className="opacity-40 group-hover/row:opacity-100 group-focus-within/row:opacity-100 hover:text-white text-[#AAAAAA] border border-[#202020] hover:border-white p-1 transition-all"
                            title="Edit Category"
                          >
                            <Edit2 className="w-3 h-3" />
                          </button>
                        </div>
                      )}
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
                        {(tx.is_internal_transfer || tx.category?.toLowerCase() === 'transfer') && (
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
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer Controls */}
      {totalPages > 1 && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-4 border-t border-[#202020] text-xs font-mono">
          <div className="text-[11px] text-[#888888]">
            Page <strong className="text-white">{safeCurrentPage}</strong> of{' '}
            <strong className="text-white">{totalPages}</strong>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={safeCurrentPage <= 1}
              aria-label="Previous page"
              className="px-2.5 py-1.5 border border-[#202020] bg-black text-[#AAAAAA] hover:text-white hover:border-white disabled:opacity-30 disabled:pointer-events-none transition-colors flex items-center gap-1 text-[11px]"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>PREV</span>
            </button>

            {/* Numeric page buttons */}
            {Array.from({ length: totalPages }, (_, i) => i + 1)
              .filter((page) => {
                // Show first, last, and pages close to current page
                return (
                  page === 1 ||
                  page === totalPages ||
                  Math.abs(page - safeCurrentPage) <= 1
                );
              })
              .map((page, idx, arr) => {
                const prevPage = arr[idx - 1];
                const showEllipsis = prevPage && page - prevPage > 1;

                return (
                  <React.Fragment key={page}>
                    {showEllipsis && (
                      <span className="px-1 text-[#666666] text-xs select-none">…</span>
                    )}
                    <button
                      onClick={() => setCurrentPage(page)}
                      aria-label={`Go to page ${page}`}
                      aria-current={page === safeCurrentPage ? 'page' : undefined}
                      className={`min-w-[28px] h-7 px-2 text-[11px] font-mono border transition-colors ${
                        page === safeCurrentPage
                          ? 'border-white bg-white text-black font-bold'
                          : 'border-[#202020] bg-black text-[#AAAAAA] hover:text-white hover:border-[#404040]'
                      }`}
                    >
                      {page}
                    </button>
                  </React.Fragment>
                );
              })}

            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={safeCurrentPage >= totalPages}
              aria-label="Next page"
              className="px-2.5 py-1.5 border border-[#202020] bg-black text-[#AAAAAA] hover:text-white hover:border-white disabled:opacity-30 disabled:pointer-events-none transition-colors flex items-center gap-1 text-[11px]"
            >
              <span>NEXT</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
