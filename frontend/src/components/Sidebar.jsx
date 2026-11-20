import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
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
  X,
  Scale
} from 'lucide-react';
import { Tooltip } from './ui/Tooltip';

/**
 * ArthaShield Sidebar
 *
 * Two states on desktop - a full "expanded" rail (270px) and a compact
 * "collapsed" rail (76px) - plus a slide-in drawer on mobile.
 *
 * How the transition is built
 * --------------------------
 * Every animated property shares one duration and one easing curve, so the
 * whole rail moves as a single gesture instead of several independent
 * animations:
 *
 *   - the rail width animates, and the content column is a flex sibling, so
 *     the dashboard resizes with it - no layout jump anywhere;
 *   - text is never unmounted. Labels, system codes, the brand block and the
 *     section heading keep their place in the DOM and are animated with
 *     `max-width` + `opacity` + a small translate. That is what makes them
 *     fade and slide away rather than blink out;
 *   - the icon column keeps a fixed size, so the icons never drift while the
 *     rail is moving;
 *   - the SECURITY GATEWAY card collapses with a `max-height` transition and
 *     the compact lock cross-fades in over the same space, so the footer does
 *     not jump.
 */

const EXPANDED_WIDTH = 300;
const COLLAPSED_WIDTH = 76;

/**
 * The rail's own geometry animates over 280ms; the text inside it fades over
 * 180ms, so the words are already gone by the time the rail reaches its new
 * width and nothing ever appears to "tear". One easing curve is used for
 * both - a decelerating curve that settles without overshoot.
 */
const RAIL_TRANSITION = 'transition-all duration-[280ms] ease-rail';
const TEXT_TRANSITION = 'transition-all duration-[180ms] ease-rail';

const NAV_ITEMS = [
  {
    id: 'OVERVIEW',
    label: 'Overview & Health',
    icon: LayoutDashboard,
    code: 'SYS_01',
  },
  {
    id: 'INTELLIGENCE',
    label: 'Financial Intelligence',
    icon: Zap,
    code: 'SYS_02',
  },
  {
    id: 'PRIVACY_INSPECTOR',
    label: 'Privacy Inspector',
    icon: ShieldCheck,
    code: 'SYS_03',
  },
  {
    id: 'LEAKAGE_RADAR',
    label: 'Leakage Radar',
    icon: Flame,
    code: 'SYS_04',
  },
  {
    id: 'STRESS_TEST',
    label: 'Commitment Stress Test',
    icon: Scale,
    code: 'SYS_05',
  },
  {
    id: 'EMI_SIMULATOR',
    label: 'EMI Reality Check',
    icon: Calculator,
    code: 'SYS_06',
  },
  {
    id: 'AUDIT_LEDGER',
    label: 'Audit & Transaction Ledger',
    icon: ReceiptText,
    code: 'SYS_07',
  },
];

/**
 * The rail itself. Rendered twice: once for the desktop column and once
 * inside the mobile drawer.
 */
function SidebarPanel({
  activeTab,
  onSelectTab,
  collapsed,
  onToggleCollapse,
  onCloseMobile,
  isMobile,
}) {
  const handleNavClick = (tabId) => {
    onSelectTab(tabId);
    if (isMobile && onCloseMobile) onCloseMobile();
  };

  const textHidden = collapsed
    ? 'opacity-0 -translate-x-2 pointer-events-none'
    : 'opacity-100 translate-x-0';

  // The sliding indicator is measured from the live DOM, so it stays correct
  // when the rail collapses, the window resizes or the fonts settle. It is
  // only shown once it has been measured, so it can never sit on the wrong
  // item while the layout is still settling.
  const navRef = useRef(null);
  const buttonRefs = useRef([]);
  const [indicator, setIndicator] = useState({ top: 0, height: 0, ready: false });

  const measureIndicator = useCallback(() => {
    const nav = navRef.current;
    const index = NAV_ITEMS.findIndex((item) => item.id === activeTab);
    const button = buttonRefs.current[index];
    if (!nav || !button) return;
    const navRect = nav.getBoundingClientRect();
    const buttonRect = button.getBoundingClientRect();
    if (!navRect.height || !buttonRect.height) return;
    setIndicator({
      top: buttonRect.top - navRect.top + (nav.scrollTop || 0),
      height: buttonRect.height,
      ready: true,
    });
  }, [activeTab]);

  useLayoutEffect(() => {
    measureIndicator();
  }, [measureIndicator, collapsed]);

  useEffect(() => {
    window.addEventListener('resize', measureIndicator);
    const nav = navRef.current;
    let observer = null;
    if (nav && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(measureIndicator);
      observer.observe(nav);
    }
    return () => {
      window.removeEventListener('resize', measureIndicator);
      if (observer) observer.disconnect();
    };
  }, [measureIndicator]);

  return (
    <aside
      className={`sidebar-rail h-full border-r border-[#202020] bg-[rgba(0,0,0,0.72)] backdrop-blur-md flex flex-col justify-between z-40 select-none ${RAIL_TRANSITION}`}
      style={{ width: collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH }}
      aria-label="Primary navigation"
    >
      {/* Top Section: Brand Header & Independently Scrollable Navigation */}
      <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
        {/* Brand Header */}
        <div
          className={`h-16 flex items-center border-b border-[#202020] shrink-0 ${RAIL_TRANSITION}`}
          style={{
            paddingLeft: collapsed ? 8 : 20,
            paddingRight: collapsed ? 8 : 16,
            gap: collapsed ? 0 : 12,
          }}
        >
          <div className="w-8 h-8 bg-white text-black flex items-center justify-center shrink-0 font-bold shadow-[0_0_12px_rgba(255,255,255,0.3)]">
            <Shield className="w-4 h-4 fill-black stroke-black" />
          </div>

          {/* Brand text - fades and slides out, never unmounted */}
          <div
            className={`min-w-0 overflow-hidden ${TEXT_TRANSITION} ${textHidden}`}
            style={{ maxWidth: collapsed ? 0 : 160 }}
            aria-hidden={collapsed}
          >
            <div className="flex items-center space-x-2 whitespace-nowrap">
              <span className="text-sm font-bold tracking-tight text-white uppercase font-mono">
                ArthaShield
              </span>
              <span className="border border-white bg-black px-1.5 py-0.2 text-[8px] font-mono uppercase text-white font-bold">
                2.0
              </span>
            </div>
          </div>

          {/* Desktop Collapse Toggle - always visible, the chevron flips */}
          {!isMobile && (
            <button
              type="button"
              onClick={onToggleCollapse}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-expanded={!collapsed}
              title={collapsed ? 'Expand sidebar (Ctrl+B)' : 'Collapse sidebar (Ctrl+B)'}
              className="ml-auto p-1 text-[#AAAAAA] hover:text-white transition-colors cursor-pointer shrink-0"
            >
              {collapsed ? (
                <ChevronRight className="w-4 h-4" />
              ) : (
                <ChevronLeft className="w-4 h-4" />
              )}
            </button>
          )}

          {/* Mobile Close Button */}
          {isMobile && (
            <button
              type="button"
              onClick={onCloseMobile}
              aria-label="Close navigation menu"
              className="ml-auto p-1.5 text-[#AAAAAA] hover:text-white cursor-pointer shrink-0"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Section Header */}
        <div
          className={`pt-5 pb-2 flex items-center justify-between overflow-hidden shrink-0 ${TEXT_TRANSITION} ${textHidden}`}
          style={{ paddingLeft: collapsed ? 0 : 20, paddingRight: collapsed ? 0 : 20, maxWidth: collapsed ? 0 : EXPANDED_WIDTH }}
          aria-hidden={collapsed}
        >
          <span className="text-[9px] font-mono uppercase tracking-[0.25em] text-[#8A8A8A] whitespace-nowrap">
            Subsystems
          </span>
          <span className="text-[9px] font-mono text-[#767676] whitespace-nowrap">
            [ONLINE]
          </span>
        </div>

        {/* Navigation Items - Independently Scrollable Container */}
        <nav
          ref={navRef}
          onScroll={measureIndicator}
          className="relative py-2 flex flex-col space-y-1 flex-1 overflow-y-auto overflow-x-hidden min-h-0"
        >
          {/* Sliding active indicator */}
          <span
            aria-hidden="true"
            className="nav-indicator pointer-events-none absolute left-0 z-20 w-1 bg-black"
            style={{
              top: indicator.top,
              height: indicator.height,
              opacity: indicator.ready ? 1 : 0,
            }}
          />
          {NAV_ITEMS.map((item, index) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;

            const button = (
              <button
                ref={(element) => {
                  buttonRefs.current[index] = element;
                }}
                type="button"
                onClick={() => handleNavClick(item.id)}
                title={item.label}
                aria-label={collapsed ? `${item.label} (${item.code})` : undefined}
                aria-current={isActive ? 'page' : undefined}
                className={`relative w-full cursor-pointer select-none text-left transition-all group flex items-center py-3 ${RAIL_TRANSITION} ${
                  isActive
                    ? 'bg-white text-black font-bold uppercase tracking-wider text-[10px] shadow-[0_0_15px_rgba(255,255,255,0.15)]'
                    : 'text-[#AAAAAA] hover:text-white hover:bg-[rgba(17,17,17,0.85)] uppercase tracking-wider text-[10px]'
                }`}
                style={{
                  paddingLeft: collapsed ? 0 : 20,
                  paddingRight: collapsed ? 0 : 16,
                  gap: collapsed ? 0 : 12,
                  justifyContent: collapsed ? 'center' : 'flex-start',
                }}
              >
                <Icon
                  className={`w-4 h-4 shrink-0 transition-transform group-hover:scale-110 ${
                    isActive ? 'text-black' : 'text-[#AAAAAA]'
                  }`}
                />

                {/* Label + system code - full readable labels */}
                <span
                  className={`flex items-center justify-between min-w-0 overflow-hidden flex-1 ${TEXT_TRANSITION} ${textHidden}`}
                  style={{ maxWidth: collapsed ? 0 : 240 }}
                  aria-hidden={collapsed}
                >
                  <span className="truncate whitespace-nowrap font-mono text-[10.5px] leading-tight" title={item.label}>
                    {item.label}
                  </span>
                  <span
                    className={`text-[8px] font-mono font-normal opacity-60 ml-2 whitespace-nowrap shrink-0 ${
                      isActive ? 'text-black' : 'text-[#8A8A8A]'
                    }`}
                  >
                    {item.code}
                  </span>
                </span>
              </button>
            );

            return (
              <Tooltip key={item.id} label={collapsed ? item.label : null}>
                {button}
              </Tooltip>
            );
          })}
        </nav>
      </div>

      {/* Security Gateway Footer Card — Permanently Anchored at Bottom */}
      <div className="border-t border-[#202020] relative overflow-hidden shrink-0">
        {/* Full card - collapses away */}
        <div
          className={`p-4 overflow-hidden ${RAIL_TRANSITION} ${textHidden}`}
          style={{ maxHeight: collapsed ? 0 : 140 }}
          aria-hidden={collapsed}
        >
          <div className="relative border border-[#202020] bg-[rgba(10,10,10,0.72)] p-3.5 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[9px] font-mono uppercase tracking-wider text-white flex items-center gap-1.5 font-bold">
                <Lock className="w-3 h-3 text-white" />
                Security Gateway
              </span>
              <span className="border border-[#404040] bg-black px-1.5 py-0.2 text-[8px] font-mono uppercase text-[#AAAAAA]">
                DPDP 2026
              </span>
            </div>
            <p className="text-[9px] font-mono text-[#AAAAAA] leading-relaxed m-0">
              Zero banking credentials collected. Client-side pseudonymization enforced.
            </p>
          </div>
        </div>

        {/* Compact lock - fades in over the same space */}
        <div
          className={`absolute inset-0 flex items-center justify-center ${TEXT_TRANSITION}`}
          style={{ opacity: collapsed ? 1 : 0, pointerEvents: collapsed ? 'auto' : 'none' }}
          title="Security Gateway Active"
          aria-hidden={!collapsed}
        >
          <Lock className="w-4 h-4 text-white" />
        </div>
      </div>
    </aside>
  );
}

export default function Sidebar({
  activeTab,
  onSelectTab,
  isCollapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}) {
  // Keep the latest callback without re-subscribing the global listener on
  // every render.
  const toggleRef = useRef(onToggleCollapse);
  const closeRef = useRef(onCloseMobile);
  useEffect(() => {
    toggleRef.current = onToggleCollapse;
    closeRef.current = onCloseMobile;
  });

  // Ctrl+B / Cmd+B toggles the rail, exactly like the reference. The
  // shortcut is ignored while the user is typing, so it never steals a key
  // from a form field.
  useEffect(() => {
    const handleKeyDown = (event) => {
      const key = typeof event.key === 'string' ? event.key.toLowerCase() : '';
      if (key !== 'b' || !(event.ctrlKey || event.metaKey)) return;

      const target = event.target;
      const tag =
        target && target.tagName ? target.tagName.toLowerCase() : '';
      const isEditable =
        tag === 'input' ||
        tag === 'textarea' ||
        tag === 'select' ||
        (target && target.isContentEditable);
      if (isEditable) return;

      event.preventDefault();
      toggleRef.current();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Escape closes the mobile drawer.
  useEffect(() => {
    if (!mobileOpen) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') closeRef.current();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [mobileOpen]);

  return (
    <>
      {/* Desktop Persistent Sidebar */}
      <div className="hidden lg:block shrink-0 h-full">
        <SidebarPanel
          activeTab={activeTab}
          onSelectTab={onSelectTab}
          collapsed={isCollapsed}
          onToggleCollapse={onToggleCollapse}
          onCloseMobile={onCloseMobile}
          isMobile={false}
        />
      </div>

      {/* Tablet & Mobile Slide-Out Drawer & Backdrop */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/80 backdrop-blur-sm"
            onClick={onCloseMobile}
            aria-hidden="true"
          />
          <div
            className="absolute inset-y-0 left-0 w-[300px] sm:w-[320px] max-w-[85vw] h-full z-10 animate-sidebar-drawer-in shadow-[0_0_60px_rgba(0,0,0,0.9)]"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
          >
            <SidebarPanel
              activeTab={activeTab}
              onSelectTab={onSelectTab}
              collapsed={false}
              onToggleCollapse={onToggleCollapse}
              onCloseMobile={onCloseMobile}
              isMobile
            />
          </div>
        </div>
      )}
    </>
  );
}
