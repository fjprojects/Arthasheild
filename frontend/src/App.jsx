import React, { useState, useEffect, useRef } from 'react';
import { 
  CheckCircle, 
  AlertTriangle,
  Lock,
  Terminal,
  Activity,
  Layers,
  ShieldCheck
} from 'lucide-react';

import api from './services/api';
import Sidebar from './components/Sidebar';
import Navbar from './components/Navbar';
import HealthScorecard from './components/HealthScorecard';
import FinancialIntelligence from './components/FinancialIntelligence';
import PrivacyInspector from './components/PrivacyInspector';
import LeakageRadar from './components/LeakageRadar';
import EmiSimulator from './components/EmiSimulator';
import CommitmentStressTest from './components/CommitmentStressTest';
import TransactionTable from './components/TransactionTable';
import InsightsBriefing from './components/InsightsBriefing';
import ConsentModal from './components/ConsentModal';
import { Card } from './components/ui/Card';

// Cinematic & Interactive Monochrome Engines
import MonochromeCinematicUniverse from './components/effects/MonochromeCinematicUniverse';
import AmbientBackground from './components/effects/AmbientBackground';
import VenomEffect from './components/effects/VenomEffect';
import CoinCursor from './components/effects/CoinCursor';
import CRTScreenBoot from './components/effects/CRTScreenBoot';
import CrypticText from './components/effects/CrypticText';

const PAGE_TITLES = {
  OVERVIEW: 'Overview & Health',
  INTELLIGENCE: 'Financial Intelligence',
  PRIVACY_INSPECTOR: 'Privacy Inspector',
  LEAKAGE_RADAR: 'Leakage Radar',
  STRESS_TEST: 'Commitment Stress Test',
  EMI_SIMULATOR: 'EMI Reality Check',
  AUDIT_LEDGER: 'Audit Ledger',
};

export default function App() {
  const [hasConsented, setHasConsented] = useState(() => {
    return sessionStorage.getItem('arthashield_consent') === 'true';
  });
  const [showConsentModal, setShowConsentModal] = useState(false);
  // After a confirmed withdrawal the gate is not forced over the page again:
  // the navbar must be able to show the real withdrawn state and offer
  // re-authorization. New/unconsented sessions still get the modal.
  const [consentGateDismissed, setConsentGateDismissed] = useState(false);
  const [isWithdrawingConsent, setIsWithdrawingConsent] = useState(false);
  const [personas, setPersonas] = useState([]);
  const [selectedPersona, setSelectedPersona] = useState(null);
  const [healthMetrics, setHealthMetrics] = useState(null);
  const [safeToSpend, setSafeToSpend] = useState(null);
  const [activeTab, setActiveTab] = useState('OVERVIEW');
  const [loading, setLoading] = useState(true);
  const [isNuking, setIsNuking] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);
  const [toastTone, setToastTone] = useState('success');
  // The sidebar rail preference is remembered across reloads. Storage can be
  // unavailable (private browsing, blocked cookies), so every access is
  // guarded and the app simply falls back to the expanded rail.
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem('arthashield_sidebar_collapsed') === 'true';
    } catch {
      return false;
    }
  });
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [sessionId, setSessionId] = useState(() => api.getSessionId() || null);
  // Task 20: the session is bootstrapped exactly once and its state is owned by
  // the API client. `sessionReady` gates every authenticated request, so no
  // financial call is ever fired with a partially initialised session.
  const [sessionReady, setSessionReady] = useState(() => api.getSessionState().ready);
  const [sessionError, setSessionError] = useState(null);
  // Task 17: snapshot/overview computed from imported statement transactions.
  // Cleared on consent withdrawal and hard purge alongside all other financial state.
  const [importedOverview, setImportedOverview] = useState(null);
  const [overviewMode, setOverviewMode] = useState('PERSONA'); // 'IMPORTED' | 'PERSONA'
  const [isFetchingOverview, setIsFetchingOverview] = useState(false);
  // Bumped after a confirmed consent withdrawal so in-flight persona loads can no
  // longer write the cleared financial state back, and so consent-dependent
  // children remount without their previously loaded data.
  const dataEpochRef = useRef(0);
  const [dataEpoch, setDataEpoch] = useState(0);

  // Load session & initial synthetic personas on mount.
  //
  // Task 20: the bootstrap runs exactly once per page load. React StrictMode
  // invokes a mount effect twice in development, and any other concurrent
  // bootstrap would do the same; the guard plus the API client's single-flight
  // session creation guarantee exactly one session and one data load.
  const bootstrapStartedRef = useRef(false);
  const recoveryAttemptsRef = useRef(0);
  const isSelectingPersonaRef = useRef(false);

  const runBootstrap = async () => {
    if (bootstrapStartedRef.current) return;
    bootstrapStartedRef.current = true;
    setSessionError(null);
    try {
      const sid = await api.ensureSession();
      setSessionId(sid);
      setSessionReady(true);

      // The server owns consent. Reconcile the browser hint against the active
      // consent audit row before rendering the dashboard or the gate.
      // Treat server-side consent as authoritative.
      let serverConsent = false;
      try {
        const status = await api.getSessionStatus();
        if (status?.has_active_consent === true) {
          serverConsent = true;
          setHasConsented(true);
          sessionStorage.setItem('arthashield_consent', 'true');
        } else {
          serverConsent = false;
          setHasConsented(false);
          sessionStorage.removeItem('arthashield_consent');
        }
      } catch (statusErr) {
        console.warn('Could not verify consent status with server:', statusErr);
        serverConsent = false;
        setHasConsented(false);
        sessionStorage.removeItem('arthashield_consent');
      }

      const data = await api.getPersonas();
      const loadedPersonas = data.personas || [];
      setPersonas(loadedPersonas);

      // Only select persona and load financial overview if server-side consent is verified active!
      if (serverConsent && loadedPersonas.length > 0) {
        if (!isSelectingPersonaRef.current) {
          isSelectingPersonaRef.current = true;
          try {
            await handleSelectPersona(loadedPersonas[0].id, sid, true);
          } finally {
            isSelectingPersonaRef.current = false;
          }
        }
        // Task 17: rehydrate the imported-statement overview for returning
        // sessions (imports persist server-side).
        const overview = await fetchImportedOverview(sid);
        if (overview?.has_imported_data) {
          setOverviewMode('IMPORTED');
        }
      }
    } catch (err) {
      console.error('Failed to initialise the session:', err);
      setSessionReady(false);
      setSessionError(
        err?.response?.data?.error ||
          err?.message ||
          'Unable to establish a secure session.',
      );
    } finally {
      setLoading(false);
    }
  };

  const scheduleRecovery = () => {
    if (recoveryAttemptsRef.current >= 3) return;
    recoveryAttemptsRef.current += 1;
    setTimeout(() => {
      bootstrapStartedRef.current = false;
      runBootstrap();
    }, 500);
  };

  useEffect(() => {
    runBootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist the sidebar rail preference so the choice survives a reload.
  useEffect(() => {
    try {
      window.localStorage.setItem(
        'arthashield_sidebar_collapsed',
        String(isSidebarCollapsed),
      );
    } catch {
      // Storage is unavailable - the preference simply is not remembered.
    }
  }, [isSidebarCollapsed]);

  // Keep the rendered session in lockstep with the API client's active
  // session: a session that is created, replaced or cleared is reflected
  // immediately, so a stale id can never be sent with a request.
  useEffect(() => {
    return api.subscribeToSession((session) => {
      setSessionId(session?.sessionId || null);
      setSessionReady(Boolean(session));
      if (!session) {
        // The session was invalidated (for example an expired credential):
        // recover with a fresh handshake instead of leaving the app dead.
        scheduleRecovery();
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const retryBootstrap = () => {
    bootstrapStartedRef.current = false;
    runBootstrap();
  };

  // Task 17: fetch the imported-session overview with the same consent-epoch
  // guard used for persona loads, so a withdrawal can never repopulate it.
  const fetchImportedOverview = async (overrideSessionId = null, showLoading = false) => {
    const epoch = dataEpochRef.current;
    if (showLoading) setIsFetchingOverview(true);
    try {
      const sid = overrideSessionId || sessionId || (await api.ensureSession());
      const res = await api.getImportedOverview(sid);
      if (epoch !== dataEpochRef.current) return null;
      if (res && res.has_imported_data) {
        setImportedOverview(res);
      } else {
        setImportedOverview(null);
      }
      return res;
    } catch (err) {
      // Consent not granted (403 CONSENT_REQUIRED) or overview unavailable:
      // silently keep the dashboard persona-only.
      if (epoch === dataEpochRef.current) setImportedOverview(null);
      return null;
    } finally {
      if (showLoading) setIsFetchingOverview(false);
    }
  };

  const handleSelectPersona = async (personaId, overrideSessionId = null, verifiedConsent = false) => {
    const epoch = dataEpochRef.current;
    if (!hasConsented && !verifiedConsent) {
      setShowConsentModal(true);
      showToast('Consent required before accessing persona financial data.', 'error');
      return;
    }
    try {
      const sid = overrideSessionId || sessionId || (await api.ensureSession());
      setSessionId(sid);
      const res = await api.selectPersona(personaId, sid);
      // Consent was withdrawn while this response was in flight: never restore
      // the financial data it carries.
      if (epoch !== dataEpochRef.current) return;
      setSelectedPersona(res.persona);
      setHealthMetrics(res.health_metrics);
      setSafeToSpend(res.safe_to_spend);
      showToast(`Loaded Persona: ${res.persona.name}`);
    } catch (err) {
      if (err?.response?.status === 403) {
        setHasConsented(false);
        sessionStorage.removeItem('arthashield_consent');
        setShowConsentModal(true);
        console.warn('Persona selection blocked: active consent required.');
      } else {
        console.error('Failed to select persona:', err);
      }
    }
  };

  const handleNukeData = async () => {
    setIsNuking(true);
    try {
      const res = await api.nukeData();
      if (res?.status !== 'HARD_PURGE_SUCCESSFUL') {
        throw new Error('The backend did not confirm the purge.');
      }
      const shredded = Number(res?.records_shredded ?? 0);
      // The backend also deletes the consent audit records, so the UI must stop
      // claiming consent is active. Invalidate in-flight loads and clear every
      // session-derived financial value. Leave the gate closed so the withdrawn
      // status and re-authorization action remain visible in the navbar.
      dataEpochRef.current += 1;
      sessionStorage.removeItem('arthashield_consent');
      setHasConsented(false);
      setConsentGateDismissed(true);
      setShowConsentModal(false);
      setSelectedPersona(null);
      setHealthMetrics(null);
      setSafeToSpend(null);
      setImportedOverview(null);
      setOverviewMode('PERSONA');
      setDataEpoch((prev) => prev + 1);
      showToast(
        `Deleted ${shredded} database record${shredded === 1 ? '' : 's'}. Consent was removed; re-authorize to continue.`,
      );
    } catch (err) {
      console.error('Purge failed:', err);
      const message =
        err?.response?.data?.error || err?.message || 'The backend did not confirm deletion.';
      showToast(`Shred failed: ${message}`, 'error');
    } finally {
      setIsNuking(false);
    }
  };

  const showToast = (msg, tone = 'success') => {
    setToastTone(tone);
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4500);
  };

  const handleConsent = async () => {
    sessionStorage.setItem('arthashield_consent', 'true');
    setConsentGateDismissed(false);
    setHasConsented(true);
    // Re-hydrate the dashboard if state was cleared by a withdrawal or on first consent
    if (!selectedPersona && personas.length > 0 && !isSelectingPersonaRef.current) {
      isSelectingPersonaRef.current = true;
      try {
        await handleSelectPersona(personas[0].id, sessionId, true);
      } finally {
        isSelectingPersonaRef.current = false;
      }
    }
    // Task 17: the imported-statement overview was cleared by the withdrawal
    // but its transactions persist server-side. Re-hydrate it the same way.
    fetchImportedOverview(sessionId, true).then((overview) => {
      if (overview?.has_imported_data) {
        setOverviewMode('IMPORTED');
      }
    });
  };

  const handleWithdrawConsent = async () => {
    setIsWithdrawingConsent(true);
    try {
      // The active state changes only after the backend confirms the withdrawal.
      const res = await api.withdrawConsent();
      const confirmed =
        res?.status === 'CONSENT_WITHDRAWN' ||
        res?.status === 'ALREADY_WITHDRAWN_OR_NEVER_CONSENTED';
      if (!confirmed) {
        throw new Error('The backend did not confirm consent withdrawal.');
      }

      // Invalidate every in-flight dashboard load, then clear all session-derived
      // financial state so nothing previously loaded stays on screen.
      dataEpochRef.current += 1;
      sessionStorage.removeItem('arthashield_consent');
      setHasConsented(false);
      setConsentGateDismissed(true);
      setShowConsentModal(false);
      setSelectedPersona(null);
      setHealthMetrics(null);
      setSafeToSpend(null);
      setImportedOverview(null);
      setOverviewMode('PERSONA');
      setDataEpoch((prev) => prev + 1);
      showToast(
        res.status === 'CONSENT_WITHDRAWN'
          ? 'Consent withdrawn. Persistent processing is blocked.'
          : 'Consent was already inactive for this session.',
      );
    } catch (err) {
      console.error('Consent withdrawal failed:', err);
      const message =
        err?.response?.data?.error ||
        err?.response?.data?.detail ||
        err?.message ||
        'The backend did not confirm withdrawal.';
      showToast(`Consent withdrawal failed: ${message}`, 'error');
    } finally {
      setIsWithdrawingConsent(false);
    }
  };

  const handleOpenConsentModal = () => {
    setShowConsentModal(true);
  };

  // Task 17: resolve the OVERVIEW data source. Real imported statements take
  // precedence over the synthetic persona unless the user explicitly switched
  // back (mirrors the LeakageRadar live/demo resolution).
  const hasImportedOverview = Boolean(importedOverview?.has_imported_data);
  const currentOverviewMode =
    (overviewMode === 'PERSONA' && selectedPersona) || !hasImportedOverview
      ? 'PERSONA'
      : 'IMPORTED';

  // One resolved dataset for the whole app. Every screen reads these values so
  // an imported statement can never be mixed with persona transactions or a
  // persona-created financial snapshot.
  const activeDatasetMode = currentOverviewMode;
  const includePersona = activeDatasetMode === 'PERSONA';
  const activeDatasetLabel = includePersona
    ? 'DEMO PERSONA · SCENARIO'
    : 'IMPORTED STATEMENT · OBSERVED';
  const activeDatasetPeriod = includePersona
    ? 'SCENARIO PERIOD'
    : importedOverview?.statement_period?.label || 'STATEMENT PERIOD';
  const activeDatasetBasis = includePersona
    ? 'INFERRED / SCENARIO ESTIMATE'
    : 'OBSERVED FROM IMPORTED TRANSACTIONS';

  const handleDatasetModeChange = (nextIncludePersona) => {
    if (nextIncludePersona) {
      setOverviewMode('PERSONA');
      return;
    }
    if (hasImportedOverview) {
      setOverviewMode('IMPORTED');
    } else {
      showToast('Import a statement before switching to imported data.', 'error');
    }
  };

  return (
    <div className="relative min-h-screen bg-black text-white font-sans antialiased selection:bg-white selection:text-black overflow-x-hidden">
      
      {/* CRT Screen Power-On & Tab Switch Sequence */}
      <CRTScreenBoot triggerKey={activeTab} />

      {/* 6-Layer Animated Monochrome Cinematic Background */}
      <MonochromeCinematicUniverse />

      {/* Persistent organic sand-texture atmosphere. Mounted at the application
          root so it survives every view change and is never recreated on
          navigation. Sits above the technical overlay and below all content. */}
      <AmbientBackground />

      {/* Global Venom Ink Burst & Button Compression Reactor */}
      <VenomEffect />

      {/* Silver Financial Coin Custom Cursor with Trailing Wake */}
      <CoinCursor />

      {/* Explicit Consent Modal Gatekeeper */}
      {(showConsentModal || (!hasConsented && !consentGateDismissed)) && (
        <ConsentModal 
          onConsentGiven={() => {
            handleConsent();
            setShowConsentModal(false);
          }} 
        />
      )}

      {/* Global Toast Notification */}
      {toastMessage && (
        <div
          role="status"
          className={`fixed bottom-6 right-6 z-50 bg-[#0A0A0A]/95 border text-white font-mono text-xs px-4 py-2.5 flex items-center gap-2 view-enter backdrop-blur-md ${
            toastTone === 'error'
              ? 'border-[#AAAAAA] shadow-[0_0_25px_rgba(255,255,255,0.14)]'
              : 'border-white shadow-[0_0_25px_rgba(255,255,255,0.2)]'
          }`}
        >
          {toastTone === 'error' ? (
            <AlertTriangle className="w-4 h-4 shrink-0 text-white" />
          ) : (
            <CheckCircle className="w-4 h-4 shrink-0 text-white" />
          )}
          <span>{toastMessage}</span>
        </div>
      )}

      {/* App Foreground Layout with High-Contrast Glass Framing */}
      <div className="relative z-10 flex min-h-screen bg-black/60 backdrop-blur-[1px]">
        
        {/* Desktop & Mobile Responsive Sidebar */}
        <Sidebar
          activeTab={activeTab}
          onSelectTab={setActiveTab}
          isCollapsed={isSidebarCollapsed}
          onToggleCollapse={() => setIsSidebarCollapsed((prev) => !prev)}
          mobileOpen={mobileMenuOpen}
          onCloseMobile={() => setMobileMenuOpen(false)}
        />

        {/* Main Application Container */}
        <div className="flex-1 flex flex-col min-w-0 min-h-screen">
          
          {/* Top App Bar — Boot Sequence Stage 1 */}
          <div className="boot-stage-1">
            <Navbar
              pageTitle={PAGE_TITLES[activeTab] || 'ArthaShield'}
              personas={personas}
              selectedPersona={selectedPersona}
              onSelectPersona={handleSelectPersona}
              onNukeData={handleNukeData}
              isNuking={isNuking}
              onOpenMobile={() => setMobileMenuOpen(true)}
              hasConsented={hasConsented}
              isWithdrawingConsent={isWithdrawingConsent}
              onWithdrawConsent={handleWithdrawConsent}
              onOpenConsentModal={handleOpenConsentModal}
            />
          </div>

          {/* Content Area */}
          <main className="flex-1 max-w-7xl mx-auto px-6 sm:px-8 py-8 w-full space-y-8">

            {/* Task 20: session bootstrap state. No authenticated request is
                fired until the active session exists; a failure is recoverable
                without a page reload. */}
            {sessionError ? (
              <div className="border border-[#404040] bg-[#0A0A0A] p-6 font-mono space-y-3">
                <div className="text-xs font-bold uppercase tracking-widest text-white">
                  SESSION HANDSHAKE FAILED
                </div>
                <p className="text-[11px] text-[#AAAAAA] m-0">{sessionError}</p>
                <button
                  type="button"
                  onClick={retryBootstrap}
                  className="border border-white bg-black px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-white hover:bg-white hover:text-black transition-colors cursor-pointer"
                >
                  Retry Session Handshake
                </button>
              </div>
            ) : !sessionReady ? (
              <div className="border border-[#202020] bg-[#0A0A0A] p-6 font-mono text-[11px] uppercase tracking-widest text-[#AAAAAA]">
                Establishing secure session…
              </div>
            ) : null}

            {/* Header & Persona Card ("Rohit Verma") — Boot Sequence Stage 2 */}
            {selectedPersona && (
              <Card
                corners={12}
                cornerStroke={2}
                className="boot-stage-2 backdrop-blur-md p-6 mb-8"
              >
                <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6">
                  <div>
                    <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                      <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-white m-0 font-mono">
                        <CrypticText text={selectedPersona.name} triggerKey={selectedPersona.id} />
                      </h2>
                      <span className="border border-white bg-black px-2 py-0.5 text-[9px] font-mono uppercase text-white font-bold tracking-widest shrink-0">
                        {includePersona ? 'SYNTHETIC PERSONA' : 'PERSONA PROFILE · INACTIVE'}
                      </span>
                      <span className="hidden sm:inline-block text-[10px] font-mono text-[#AAAAAA]">
                        [SYS: OK]
                      </span>
                    </div>
                    <p className="text-xs text-[#AAAAAA] font-mono mt-1.5 m-0 flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span>{selectedPersona.profile}</span>
                      {includePersona && (
                        <>
                          <span className="text-[#767676]">◈</span>
                          <span>{selectedPersona.account_summary.bank_name}</span>
                          <span className="text-[#767676]">◈</span>
                          <span className="text-white font-bold">{selectedPersona.account_summary.masked_account_number}</span>
                        </>
                      )}
                    </p>
                  </div>

                  <div className="flex items-center space-x-8 text-right font-mono border-t md:border-t-0 border-[#202020] pt-4 md:pt-0 w-full md:w-auto justify-between md:justify-end">
                    <div>
                      <div className="text-[10px] uppercase text-[#AAAAAA] tracking-wider">
                        Monthly Inflow
                      </div>
                      <div className="text-lg sm:text-xl font-bold text-white mt-0.5 tracking-tight">
                        {includePersona ? (
                          <CrypticText 
                            text={`₹${selectedPersona.monthly_average_income?.toLocaleString('en-IN')}`} 
                            triggerKey={selectedPersona.id} 
                          />
                        ) : (
                          <span className="text-[#888888]">NOT ACTIVE</span>
                        )}
                      </div>
                    </div>

                    <div className="border-l border-[#202020] pl-8">
                      <div className="text-[10px] uppercase text-[#AAAAAA] tracking-wider">
                        Liquid Balance
                      </div>
                      <div className="text-lg sm:text-xl font-bold text-white mt-0.5 tracking-tight">
                        {includePersona ? (
                          <CrypticText 
                            text={`₹${selectedPersona.account_summary.current_balance?.toLocaleString('en-IN')}`} 
                            triggerKey={selectedPersona.id} 
                          />
                        ) : (
                          <span className="text-[#888888]">NOT ACTIVE</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Sub-strip telemetry with Typewriter log */}
                <div className="mt-4 pt-3 border-t border-[#1a1a1a] flex flex-wrap items-center justify-between text-[9px] font-mono text-[#8A8A8A] uppercase tracking-wider">
                  <span>
                    SESSION REF: <CrypticText text={sessionId ? `${sessionId.slice(0, 16)}...` : 'DISCONNECTED'} duration={300} triggerKey={sessionId} />
                  </span>
                  <span className="hidden sm:inline">DATA COVENANT: CLIENT-FIRST DPDP 2026</span>
                  <span>ENCRYPTION: AES-256 / SHA-256 IDENTIFIER</span>
                </div>
              </Card>
            )}

            {/* Single active dataset banner — shown on every screen */}
            {sessionReady && (
              <div className="flex flex-wrap items-center justify-between gap-3 border border-[#202020] bg-black/90 px-3 py-2 font-mono text-[9px] uppercase tracking-widest text-[#AAAAAA]">
                <div className="flex flex-wrap items-center gap-2">
                  <Layers className="w-3.5 h-3.5 text-white" />
                  <span className="text-white font-bold">ACTIVE DATASET</span>
                  <span className="border border-white bg-black px-2 py-0.5 text-white font-bold">
                    {activeDatasetLabel}
                  </span>
                  <span>{activeDatasetPeriod}</span>
                </div>
                <span className="text-[#888888]">BASIS: {activeDatasetBasis}</span>
              </div>
            )}

            {/* Module Views — Boot Sequence Stage 3 */}
            <div className="boot-stage-3" key={dataEpoch}>
              {activeTab === 'OVERVIEW' && (
                <div className="space-y-8 view-enter">
                  {/* Task 17: Data-source toggle — imported statement vs synthetic persona */}
                  {hasImportedOverview && selectedPersona && (
                    <div className="flex flex-wrap items-center justify-between gap-3 border border-[#202020] bg-black/90 p-3">
                      <div className="flex items-center gap-2 text-[9px] font-mono uppercase text-[#AAAAAA] tracking-widest">
                        <Layers className="w-3.5 h-3.5 text-white" />
                        <span>OVERVIEW DATA SOURCE</span>
                      </div>
                      <div className="flex items-center gap-1 border border-[#333333] p-0.5 bg-black">
                        <button
                          type="button"
                          onClick={() => setOverviewMode('IMPORTED')}
                          className={`interactive-control px-2 py-0.5 text-[8px] uppercase tracking-wider font-bold ${
                            currentOverviewMode === 'IMPORTED'
                              ? 'bg-white text-black'
                              : 'text-[#888888] hover:text-white'
                          }`}
                        >
                          Imported Statement
                        </button>
                        <button
                          type="button"
                          onClick={() => setOverviewMode('PERSONA')}
                          className={`interactive-control px-2 py-0.5 text-[8px] uppercase tracking-wider font-bold ${
                            currentOverviewMode === 'PERSONA'
                              ? 'bg-white text-black'
                              : 'text-[#888888] hover:text-white'
                          }`}
                        >
                          Demo Persona
                        </button>
                      </div>
                    </div>
                  )}

                  {currentOverviewMode === 'IMPORTED' && importedOverview ? (
                    <>
                      {/* Imported statement period & coverage banner */}
                      <Card corners={10} cornerStroke={1.5} className="p-5 font-mono">
                        <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
                          <div className="space-y-1.5">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="border border-white bg-black px-2 py-0.5 text-[9px] uppercase text-white font-bold tracking-widest">
                                IMPORTED STATEMENT SNAPSHOT
                              </span>
                              <span className="text-[10px] uppercase text-[#AAAAAA] tracking-widest flex items-center gap-1.5">
                                <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse" />
                                {importedOverview.statement_period?.label || 'STATEMENT PERIOD'}
                              </span>
                              {importedOverview.data_coverage?.is_partial_month_likely && (
                                <span className="border border-[#404040] bg-[#111111] text-[#AAAAAA] text-[8px] uppercase px-1.5 py-0.5 tracking-widest">
                                  PARTIAL-MONTH COVERAGE
                                </span>
                              )}
                            </div>
                            <p className="text-[11px] text-[#AAAAAA] leading-relaxed m-0">
                              {importedOverview.data_coverage?.note ||
                                'Metrics are calculated from imported transactions in the statement period only.'}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-6 text-right border-t lg:border-t-0 lg:border-l border-[#202020] pt-3 lg:pt-0 lg:pl-6">
                            <div>
                              <div className="text-[9px] uppercase text-[#AAAAAA] tracking-wider">Period</div>
                              <div className="text-xs text-white font-bold mt-0.5">
                                {importedOverview.data_coverage?.days_covered ?? 0} Days
                              </div>
                            </div>
                            <div>
                              <div className="text-[9px] uppercase text-[#AAAAAA] tracking-wider">Transactions</div>
                              <div className="text-xs text-white font-bold mt-0.5">
                                {importedOverview.transaction_count ?? 0}
                              </div>
                            </div>
                            <div>
                              <div className="text-[9px] uppercase text-[#AAAAAA] tracking-wider">Months Covered</div>
                              <div className="text-xs text-white font-bold mt-0.5">
                                {importedOverview.data_coverage?.distinct_months ?? 0}
                              </div>
                            </div>
                          </div>
                        </div>
                      </Card>

                      <HealthScorecard
                        healthMetrics={importedOverview.health_metrics}
                        safeToSpend={importedOverview.safe_to_spend}
                        selectedPersona={null}
                        detectedLeaks={{
                          total_monthly_leakage: parseFloat(importedOverview.summary?.monthly_leakage || '0'),
                          items_count: importedOverview.summary?.confirmed_recurring_count || 0,
                        }}
                        datasetSourceLabel={activeDatasetLabel}
                        reportingPeriod={activeDatasetPeriod}
                        metricBasis={importedOverview.health_metrics?.metric_basis || {}}
                        leakageStatus="EVIDENCE_REVIEW"
                      />
                      <InsightsBriefing
                        sessionId={sessionId}
                        includePersona={false}
                        datasetSourceLabel={activeDatasetLabel}
                      />
                      <TransactionTable transactions={importedOverview.transactions || []} />
                    </>
                  ) : (
                    <>
                      <HealthScorecard
                        healthMetrics={healthMetrics}
                        safeToSpend={safeToSpend}
                        selectedPersona={selectedPersona}
                        detectedLeaks={selectedPersona?.detected_leaks_summary}
                        datasetSourceLabel={activeDatasetLabel}
                        reportingPeriod={activeDatasetPeriod}
                        metricBasis={{ health_score: 'PERSONA_SCENARIO_ESTIMATE', runway: 'PERSONA_SCENARIO_ESTIMATE' }}
                        leakageStatus="SCENARIO_UNVERIFIED"
                      />
                      <InsightsBriefing
                        sessionId={sessionId}
                        includePersona={true}
                        datasetSourceLabel={activeDatasetLabel}
                      />
                      <TransactionTable transactions={selectedPersona?.transactions || []} />
                    </>
                  )}
                </div>
              )}

              {activeTab === 'INTELLIGENCE' && sessionReady && (
                <div className="view-enter">
                  <FinancialIntelligence
                    sessionId={sessionId}
                    includePersona={includePersona}
                    onIncludePersonaChange={handleDatasetModeChange}
                    datasetSourceLabel={activeDatasetLabel}
                    onRefreshParent={() => {
                      if (includePersona && selectedPersona) {
                        handleSelectPersona(selectedPersona.id, sessionId);
                      } else {
                        fetchImportedOverview(sessionId, true);
                      }
                    }}
                  />
                </div>
              )}

              {activeTab === 'PRIVACY_INSPECTOR' && sessionReady && (
                <div className="view-enter">
                  <PrivacyInspector
                    sessionId={sessionId}
                    includePersona={includePersona}
                    datasetSourceLabel={activeDatasetLabel}
                    onImportSuccess={async (data) => {
                      showToast(`Imported ${data.persistence?.imported || data.transactions?.length || 0} transactions!`);
                      if (selectedPersona) handleSelectPersona(selectedPersona.id, sessionId);
                      // Task 17: recompute the imported-statement overview from the
                      // freshly persisted transactions and surface it immediately.
                      const overview = await fetchImportedOverview(sessionId, true);
                      if (overview?.has_imported_data) {
                        setOverviewMode('IMPORTED');
                      }
                    }}
                  />
                </div>
              )}

              {activeTab === 'LEAKAGE_RADAR' && sessionReady && (
                <div className="view-enter">
                  <LeakageRadar
                    leaksSummary={selectedPersona?.detected_leaks_summary}
                    sessionId={sessionId}
                    includePersona={includePersona}
                    datasetSourceLabel={activeDatasetLabel}
                    reportingPeriod={activeDatasetPeriod}
                  />
                </div>
              )}

              {activeTab === 'STRESS_TEST' && sessionReady && (
                <div className="view-enter">
                  <CommitmentStressTest
                    sessionId={sessionId}
                    discretionaryBuffer={safeToSpend?.uncommitted_discretionary_buffer || 14000}
                    currentBalance={
                      includePersona && selectedPersona
                        ? selectedPersona?.account_summary?.current_balance
                        : null
                    }
                    includePersona={includePersona}
                    onNavigateToLedger={() => setActiveTab('AUDIT_LEDGER')}
                  />
                </div>
              )}

              {activeTab === 'EMI_SIMULATOR' && (
                <div className="view-enter">
                  <EmiSimulator 
                    discretionaryBuffer={
                      safeToSpend?.uncommitted_discretionary_buffer || 14000
                    } 
                  />
                </div>
              )}

              {activeTab === 'AUDIT_LEDGER' && (
                <div className="view-enter space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 border border-[#202020] bg-black/90 p-3 font-mono text-[9px] uppercase tracking-widest text-[#AAAAAA]">
                    <div className="flex items-center gap-2">
                      <Layers className="w-3.5 h-3.5 text-white" />
                      <span className="text-white font-bold">LEDGER DATA SOURCE</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="border border-white bg-black px-2 py-0.5 text-white font-bold">
                        {activeDatasetLabel}
                      </span>
                      <span>{activeDatasetPeriod}</span>
                      <span>
                        {includePersona ? 'Scenario rows' : 'Imported statement rows'}:{' '}
                        {(includePersona
                          ? selectedPersona?.transactions
                          : importedOverview?.transactions
                        )?.length || 0}
                      </span>
                    </div>
                  </div>
                  <TransactionTable
                    transactions={
                      includePersona
                        ? selectedPersona?.transactions || []
                        : importedOverview?.transactions || []
                    }
                  />
                </div>
              )}
            </div>

          </main>

          {/* Minimal Stark Technical Footer */}
          <footer className="border-t border-[#202020] bg-black/90 backdrop-blur-md py-4 text-center text-[10px] font-mono uppercase text-[#AAAAAA]">
            <div className="max-w-7xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse" />
            <span>ArthaShield • Built for Arthaton 2026</span>
              </div>
              <div className="flex items-center gap-4 text-[#8A8A8A]">
                <span>Zero Credentials</span>
                <span>◈</span>
                <span>Local PII Redaction</span>
                <span>◈</span>
                <span>Deterministic Math</span>
              </div>
            </div>
          </footer>

        </div>

      </div>

    </div>
  );
}
