import React from 'react';
import { Menu, Lock, Trash2, User, ShieldCheck, ShieldAlert } from 'lucide-react';

export default function Navbar({
  pageTitle = 'Overview & Health',
  personas = [],
  selectedPersona,
  onSelectPersona,
  onNukeData,
  isNuking,
  onOpenMobile,
  hasConsented = false,
  onWithdrawConsent,
  onOpenConsentModal,
}) {
  return (
    <header className="h-16 border-b border-zinc-800 bg-black sticky top-0 z-30 px-6 flex items-center justify-between select-none">
      
      {/* Left: Mobile Menu Toggle & Title */}
      <div className="flex items-center space-x-3">
        <button
          onClick={onOpenMobile}
          aria-label="Open navigation menu"
          className="md:hidden p-1.5 text-zinc-400 hover:text-white border border-zinc-800"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div className="flex items-center space-x-3">
          <h2 className="text-xs sm:text-sm font-bold uppercase tracking-[0.15em] text-white font-mono m-0">
            {pageTitle}
          </h2>
        </div>
      </div>

      {/* Right: Persona Switcher, Consent Toggle & Data Shredder */}
      <div className="flex items-center space-x-3">
        
        {/* Synthetic Persona Selector */}
        <div className="flex items-center border border-zinc-800 p-0.5">
          <span className="hidden lg:flex items-center gap-1.5 text-[10px] font-mono uppercase text-zinc-500 px-2.5">
            Persona:
          </span>
          <div className="flex space-x-0.5">
            {personas.map((p) => {
              const isSelected = selectedPersona?.id === p.id;
              return (
                <button
                  key={p.id}
                  onClick={() => onSelectPersona(p.id)}
                  className={`text-[10px] font-mono uppercase px-2.5 py-1 transition-colors cursor-pointer ${
                    isSelected
                      ? 'bg-white text-black font-bold'
                      : 'text-zinc-500 hover:text-white'
                  }`}
                >
                  {p.name.split(' ')[0]}
                </button>
              );
            })}
          </div>
        </div>

        {/* Consent Status & Toggle */}
        <div className="hidden sm:flex items-center border border-zinc-800 px-2 py-1 space-x-2 text-[10px] font-mono uppercase">
          {hasConsented ? (
            <>
              <span className="flex items-center gap-1 text-white font-bold">
                <ShieldCheck className="w-3 h-3 text-white" />
                Consent Active
              </span>
              <button
                onClick={onWithdrawConsent}
                className="text-zinc-500 hover:text-white border-l border-zinc-800 pl-2 cursor-pointer uppercase transition-colors"
                title="Revoke active consent under DPDP standards"
              >
                Withdraw
              </button>
            </>
          ) : (
            <>
              <span className="flex items-center gap-1 text-zinc-500">
                <ShieldAlert className="w-3 h-3 text-zinc-500" />
                Unconsented
              </span>
              <button
                onClick={onOpenConsentModal}
                className="text-white hover:underline border-l border-zinc-800 pl-2 cursor-pointer font-bold uppercase transition-colors"
              >
                Grant
              </button>
            </>
          )}
        </div>

        {/* Zero Credentials Badge */}
        <div className="hidden xl:flex items-center space-x-1.5 text-[10px] font-mono uppercase text-zinc-400 border border-zinc-800 px-2 py-1">
          <Lock className="w-3 h-3 text-white" />
          <span>Zero Credentials</span>
        </div>

        {/* Nuke Data Button */}
        <button
          onClick={onNukeData}
          disabled={isNuking}
          title="Permanently erase all session data and records"
          className="flex items-center space-x-1.5 text-[10px] font-mono font-bold uppercase px-3 py-1.5 bg-black hover:bg-white text-zinc-300 hover:text-black border border-zinc-700 hover:border-white transition-colors disabled:opacity-50 cursor-pointer"
        >
          <Trash2 className="w-3 h-3" />
          <span>{isNuking ? 'SHREDDING...' : 'NUKE DATA'}</span>
        </button>

      </div>
    </header>
  );
}
