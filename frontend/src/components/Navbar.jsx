import React from 'react';
import { Menu } from 'lucide-react';
import CrypticText from './effects/CrypticText';
import PersonaOrb from './ui/PersonaOrb';
import SecurityCommandCenter from './SecurityCommandCenter';

export default function Navbar({
  pageTitle = 'Overview & Health',
  personas = [],
  selectedPersona,
  onSelectPersona,
  onNukeData,
  isNuking,
  onOpenMobile,
  hasConsented = false,
  isWithdrawingConsent = false,
  onWithdrawConsent,
  onOpenConsentModal,
}) {
  return (
    <header className="h-16 border-b border-[#202020] bg-black/85 backdrop-blur-md sticky top-0 z-30 px-2.5 sm:px-4 lg:px-6 flex items-center justify-between gap-2 sm:gap-3 select-none">
      
      {/* Left: Mobile Menu Toggle & Title with Typewriter effect */}
      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        <button
          onClick={onOpenMobile}
          aria-label="Open navigation menu"
          className="interactive-control shrink-0 md:hidden p-1.5 text-[#AAAAAA] hover:text-white border border-[#202020] hover:border-white"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* The title yields to the persona module on narrow screens rather
            than forcing the navbar to overflow. It returns at md. */}
        <div className="hidden min-w-0 items-center gap-2 md:flex">
          <div className="hidden items-center gap-1.5 text-[9px] font-mono text-[#8A8A8A] uppercase lg:flex">
            <span>TERMINAL</span>
            <span>::</span>
          </div>
          {/* The page title is an h2, not an h1: the panels below it start at
              h3, and an h1 here would skip a level for every one of them
              (WCAG "heading order"). The persona card is an h2 for the same
              reason. */}
          <h2 className="m-0 max-w-[130px] truncate text-xs font-bold uppercase tracking-[0.2em] text-white font-mono lg:max-w-[220px] xl:max-w-none">
            <CrypticText text={pageTitle} mode="typewriter" speed={20} triggerKey={pageTitle} />
          </h2>
        </div>
      </div>

      {/* Right: Persona Switcher + the coordinated security command strip */}
      <div className="flex min-w-0 shrink-0 items-center gap-1.5 sm:gap-2 lg:gap-3">
        <PersonaOrb
          personas={personas}
          selectedId={selectedPersona?.id}
          onSelect={onSelectPersona}
          hasConsented={hasConsented}
        />

        <SecurityCommandCenter
          hasConsented={hasConsented}
          isWithdrawing={isWithdrawingConsent}
          onWithdrawConsent={onWithdrawConsent}
          onOpenConsentModal={onOpenConsentModal}
          onNukeData={onNukeData}
          isNuking={isNuking}
        />
      </div>
    </header>
  );
}
