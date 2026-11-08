import React, { useState, useEffect } from 'react';
import { 
  CheckCircle, 
  AlertTriangle,
  Lock
} from 'lucide-react';

import api from './services/api';
import Sidebar from './components/Sidebar';
import Navbar from './components/Navbar';
import HealthScorecard from './components/HealthScorecard';
import FinancialIntelligence from './components/FinancialIntelligence';
import PrivacyInspector from './components/PrivacyInspector';
import LeakageRadar from './components/LeakageRadar';
import EmiSimulator from './components/EmiSimulator';
import TransactionTable from './components/TransactionTable';
import ConsentModal from './components/ConsentModal';

const PAGE_TITLES = {
  OVERVIEW: 'Overview & Health',
  INTELLIGENCE: 'Financial Intelligence',
  PRIVACY_INSPECTOR: 'Privacy Inspector',
  LEAKAGE_RADAR: 'Leakage Radar',
  EMI_SIMULATOR: 'EMI Reality Check',
  AUDIT_LEDGER: 'Audit Ledger',
};

export default function App() {
  const [hasConsented, setHasConsented] = useState(() => {
    return sessionStorage.getItem('arthashield_consent') === 'true';
  });
  const [showConsentModal, setShowConsentModal] = useState(false);
  const [personas, setPersonas] = useState([]);
  const [selectedPersona, setSelectedPersona] = useState(null);
  const [healthMetrics, setHealthMetrics] = useState(null);
  const [safeToSpend, setSafeToSpend] = useState(null);
  const [activeTab, setActiveTab] = useState('OVERVIEW');
  const [loading, setLoading] = useState(true);
  const [isNuking, setIsNuking] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Load available synthetic personas on mount
  useEffect(() => {
    async function loadInitialData() {
      try {
        const data = await api.getPersonas();
        setPersonas(data.personas || []);
        if (data.personas && data.personas.length > 0) {
          await handleSelectPersona(data.personas[0].id);
        }
      } catch (err) {
        console.error('Failed to load personas:', err);
      } finally {
        setLoading(false);
      }
    }
    loadInitialData();
  }, []);

  const handleSelectPersona = async (personaId) => {
    try {
      const res = await api.selectPersona(personaId);
      setSelectedPersona(res.persona);
      setHealthMetrics(res.health_metrics);
      setSafeToSpend(res.safe_to_spend);
      showToast(`Loaded Persona: ${res.persona.name}`);
    } catch (err) {
      console.error('Failed to select persona:', err);
    }
  };

  const handleNukeData = async () => {
    if (!window.confirm("CONFIRM DATA SHREDDER: This will permanently delete all session records, transactions, and snapshots from the database.")) {
      return;
    }
    setIsNuking(true);
    try {
      const res = await api.nukeData();
      showToast(`Purged! ${res.records_shredded} database records permanently shredded.`);
      setTimeout(() => {
        if (personas.length > 0) {
          handleSelectPersona(personas[0].id);
        }
      }, 1500);
    } catch (err) {
      console.error('Purge failed:', err);
      alert('Data purge failed.');
    } finally {
      setIsNuking(false);
    }
  };

  const showToast = (msg) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleConsent = () => {
    sessionStorage.setItem('arthashield_consent', 'true');
    setHasConsented(true);
  };

  const handleWithdrawConsent = async () => {
    try {
      await api.withdrawConsent();
      sessionStorage.removeItem('arthashield_consent');
      setHasConsented(false);
      showToast('Consent revoked! Subsequent persistent processing blocked.');
    } catch (err) {
      console.error('Consent withdrawal failed:', err);
    }
  };

  const handleOpenConsentModal = () => {
    setShowConsentModal(true);
  };

  return (
    <div className="min-h-screen bg-black text-white font-sans antialiased selection:bg-white selection:text-black flex">
      
      {/* Explicit Consent Modal Gatekeeper */}
      {(!hasConsented || showConsentModal) && (
        <ConsentModal 
          onConsentGiven={() => {
            handleConsent();
            setShowConsentModal(false);
          }} 
        />
      )}

      {/* Global Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-zinc-950 border border-white text-white font-mono text-xs px-4 py-2.5 shadow-2xl flex items-center space-x-2 animate-in fade-in duration-150">
          <CheckCircle className="w-4 h-4 text-white" />
          <span>{toastMessage}</span>
        </div>
      )}

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
      <div className="flex-1 flex flex-col min-w-0 min-h-screen bg-black">
        
        {/* Streamlined Top App Bar */}
        <Navbar
          pageTitle={PAGE_TITLES[activeTab] || 'ArthaShield'}
          personas={personas}
          selectedPersona={selectedPersona}
          onSelectPersona={handleSelectPersona}
          onNukeData={handleNukeData}
          isNuking={isNuking}
          onOpenMobile={() => setMobileMenuOpen(true)}
          hasConsented={hasConsented}
          onWithdrawConsent={handleWithdrawConsent}
          onOpenConsentModal={handleOpenConsentModal}
        />

        {/* Content Area */}
        <main className="flex-1 max-w-7xl mx-auto px-6 sm:px-8 py-8 w-full space-y-8">
          
          {/* Header & Persona Card ("Rohit Verma") */}
          {selectedPersona && (
            <div className="flex justify-between items-end border-b border-zinc-800 pb-4 mb-8">
              <div>
                <div className="flex items-center space-x-3">
                  <h1 className="text-xl font-bold tracking-tight text-white m-0">
                    {selectedPersona.name}
                  </h1>
                  <span className="border border-white px-2 py-0.5 text-[10px] font-mono uppercase text-white">
                    Synthetic Persona
                  </span>
                </div>
                <p className="text-xs text-zinc-500 font-mono mt-1 m-0">
                  {selectedPersona.profile} • {selectedPersona.account_summary.bank_name} ({selectedPersona.account_summary.masked_account_number})
                </p>
              </div>

              <div className="flex items-center space-x-8 text-right font-mono">
                <div>
                  <div className="text-[10px] uppercase text-zinc-500 tracking-wider">
                    Monthly Inflow
                  </div>
                  <div className="text-base font-bold text-white mt-0.5">
                    ₹{selectedPersona.monthly_average_income?.toLocaleString('en-IN')}
                  </div>
                </div>

                <div className="border-l border-zinc-800 pl-8">
                  <div className="text-[10px] uppercase text-zinc-500 tracking-wider">
                    Liquid Balance
                  </div>
                  <div className="text-base font-bold text-white mt-0.5">
                    ₹{selectedPersona.account_summary.current_balance?.toLocaleString('en-IN')}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Module Views */}
          {activeTab === 'OVERVIEW' && (
            <div className="space-y-8 animate-in fade-in duration-150">
              <HealthScorecard
                healthMetrics={healthMetrics}
                safeToSpend={safeToSpend}
                selectedPersona={selectedPersona}
                detectedLeaks={selectedPersona?.detected_leaks_summary}
              />
              <TransactionTable transactions={selectedPersona?.transactions || []} />
            </div>
          )}

          {activeTab === 'INTELLIGENCE' && (
            <div className="animate-in fade-in duration-150">
              <FinancialIntelligence 
                sessionId="demo_session_01" 
                onRefreshParent={() => {
                  if (selectedPersona) handleSelectPersona(selectedPersona.id);
                }}
              />
            </div>
          )}

          {activeTab === 'PRIVACY_INSPECTOR' && (
            <div className="animate-in fade-in duration-150">
              <PrivacyInspector 
                sessionId="demo_session_01" 
                onImportSuccess={(data) => {
                  showToast(`Imported ${data.persistence?.imported || data.transactions?.length || 0} transactions!`);
                  if (selectedPersona) handleSelectPersona(selectedPersona.id);
                }}
              />
            </div>
          )}

          {activeTab === 'LEAKAGE_RADAR' && (
            <div className="animate-in fade-in duration-150">
              <LeakageRadar leaksSummary={selectedPersona?.detected_leaks_summary} />
            </div>
          )}

          {activeTab === 'EMI_SIMULATOR' && (
            <div className="animate-in fade-in duration-150">
              <EmiSimulator 
                discretionaryBuffer={
                  safeToSpend?.uncommitted_discretionary_buffer || 14000
                } 
              />
            </div>
          )}

          {activeTab === 'AUDIT_LEDGER' && (
            <div className="animate-in fade-in duration-150 space-y-4">
              <TransactionTable transactions={selectedPersona?.transactions || []} />
            </div>
          )}

        </main>

        {/* Minimal Stark Footer */}
        <footer className="border-t border-zinc-900 bg-black py-4 text-center text-[10px] font-mono uppercase text-zinc-600">
          <div className="max-w-7xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-2">
            <span>ArthaShield • Built for Arthaton 2026</span>
            <span>Zero Credentials • Local PII Redaction • Deterministic Math</span>
          </div>
        </footer>

      </div>

    </div>
  );
}
