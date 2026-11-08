import React from 'react';
import {
  LayoutDashboard,
  ShieldCheck,
  Flame,
  Calculator,
  ReceiptText,
  ChevronLeft,
  ChevronRight,
  Shield,
  Lock,
  Zap,
  X
} from 'lucide-react';

export default function Sidebar({
  activeTab,
  onSelectTab,
  isCollapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}) {
  const navItems = [
    {
      id: 'OVERVIEW',
      label: 'Overview & Health',
      icon: LayoutDashboard,
    },
    {
      id: 'INTELLIGENCE',
      label: 'Financial Intelligence',
      icon: Zap,
    },
    {
      id: 'PRIVACY_INSPECTOR',
      label: 'Privacy Inspector',
      icon: ShieldCheck,
    },
    {
      id: 'LEAKAGE_RADAR',
      label: 'Leakage Radar',
      icon: Flame,
    },
    {
      id: 'EMI_SIMULATOR',
      label: 'EMI Reality Check',
      icon: Calculator,
    },
    {
      id: 'AUDIT_LEDGER',
      label: 'Audit Ledger',
      icon: ReceiptText,
    },
  ];

  const handleNavClick = (tabId) => {
    onSelectTab(tabId);
    if (mobileOpen) onCloseMobile();
  };

  const sidebarContent = (
    <aside
      className={`h-full border-r border-zinc-800 bg-black flex flex-col justify-between transition-all duration-200 z-40 select-none ${
        isCollapsed ? 'w-20' : 'w-64'
      }`}
    >
      {/* Brand Header */}
      <div>
        <div className="h-16 flex items-center justify-between px-6 border-b border-zinc-800">
          <div className="flex items-center space-x-3 overflow-hidden">
            <div className="w-8 h-8 bg-white text-black flex items-center justify-center shrink-0 font-bold">
              <Shield className="w-4 h-4 fill-black stroke-black" />
            </div>
            {!isCollapsed && (
              <div className="min-w-0">
                <div className="flex items-center space-x-2">
                  <span className="text-sm font-bold tracking-tight text-white uppercase font-mono">
                    ArthaShield
                  </span>
                  <span className="border border-white px-1.5 py-0.2 text-[9px] font-mono uppercase text-white">
                    2026
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Desktop Collapse Toggle */}
          <button
            onClick={onToggleCollapse}
            aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="hidden md:flex p-1.5 text-zinc-500 hover:text-white transition cursor-pointer"
          >
            {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>

          {/* Mobile Close Button */}
          <button
            onClick={onCloseMobile}
            className="md:hidden p-1.5 text-zinc-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Section Header */}
        {!isCollapsed && (
          <div className="px-6 pt-6 pb-2">
            <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-zinc-600">
              Navigation
            </span>
          </div>
        )}

        {/* Navigation Items — Strict Inverted Active State */}
        <nav className="py-2 flex flex-col">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;

            return (
              <button
                key={item.id}
                onClick={() => handleNavClick(item.id)}
                title={isCollapsed ? item.label : undefined}
                className={`w-full cursor-pointer select-none text-left ${
                  isActive
                    ? 'bg-white text-black font-bold uppercase tracking-[0.2em] text-[10px] px-6 py-3 flex items-center gap-3'
                    : 'text-zinc-500 hover:text-white uppercase tracking-[0.2em] text-[10px] px-6 py-3 flex items-center gap-3 transition-colors'
                } ${isCollapsed ? 'justify-center !px-0' : ''}`}
              >
                <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-black' : 'text-zinc-500'}`} />
                {!isCollapsed && <span className="truncate">{item.label}</span>}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Security Gateway Footer Card */}
      <div className="p-4 border-t border-zinc-800">
        {!isCollapsed ? (
          <div className="border border-zinc-800 bg-zinc-950 p-3.5 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono uppercase tracking-wider text-white flex items-center gap-1.5 font-bold">
                <Lock className="w-3 h-3 text-white" />
                Security Gateway
              </span>
              <span className="border border-zinc-600 px-1 py-0.2 text-[9px] font-mono uppercase text-zinc-300">
                ACTIVE
              </span>
            </div>
            <p className="text-[10px] font-mono text-zinc-500 leading-relaxed m-0">
              Zero banking credentials collected. Local PII redaction pipeline enforced.
            </p>
          </div>
        ) : (
          <div className="flex justify-center" title="Security Gateway Active">
            <Lock className="w-4 h-4 text-white" />
          </div>
        )}
      </div>
    </aside>
  );

  return (
    <>
      {/* Desktop Sidebar */}
      <div className="hidden md:block shrink-0 h-screen sticky top-0">
        {sidebarContent}
      </div>

      {/* Mobile Slide-Out Drawer & Backdrop */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden flex">
          <div
            className="fixed inset-0 bg-black/80 backdrop-blur-sm transition-opacity"
            onClick={onCloseMobile}
          />
          <div className="relative flex-1 max-w-xs w-full bg-black z-10">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
}
