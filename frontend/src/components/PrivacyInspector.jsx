import React, { useState, useRef } from 'react';
import { 
  ShieldCheck, 
  Eye, 
  FileText, 
  ArrowRight, 
  Lock, 
  Cpu, 
  Upload, 
  AlertCircle,
  Sparkles,
  CheckCircle2,
  FileCheck2,
  Terminal
} from 'lucide-react';
import api from '../services/api';
import TargetLock from './effects/TargetLock';
import CrypticText from './effects/CrypticText';
import { Card } from './ui/Card';

const SAMPLE_RAW_STATEMENT = `Account Statement - Apex National Bank
Account Holder: Rohit Ramesh Verma
Account Number: 4821-9988-1200-5541
Customer ID: CUST-884920
Registered Phone: +91-9876543210
Registered Email: rohit.verma.freelance@gmail.com
IFSC Code: APEX0001234
Branch: Indiranagar, Bengaluru, Karnataka 560038
Statement Period: 01-Oct-2026 to 31-Oct-2026

Date,Description,Debit,Credit,Balance
2026-10-02,ACH CRED CLIENT GLOBAL TECH STIPEND,,45000.00,45000.00
2026-10-03,POS ADOBE SYSTEMS RENEWAL INT US-882194,4200.00,,40800.00
2026-10-04,UPI/SWIGGY/ORDER_9824219/swiggy@icici,480.00,,40320.00
2026-10-05,ACH DEBIT APEX BANK PHONE EMI NO-COST-882,5735.00,,34585.00
2026-10-08,POS AMAZON WEB SERVICES CLOUD EC2-US-EAST,1500.00,,33085.00
2026-10-12,POS FIGMA SUBSCRIPTION CA US-4491,1250.00,,31835.00
2026-10-15,NEFT CRED APEX STUDIOS DESIGN RET,,40000.00,71835.00
2026-10-16,POS OPENAI CHATGPT PLUS MONTHLY US-1182,1650.00,,70185.00
2026-10-25,UPI/APARTMENT RENT/LANDLORD/9811234567@upi,22000.00,,48185.00`;

export default function PrivacyInspector({ sessionId = null, onImportSuccess, includePersona = false, datasetSourceLabel }) {
  const [rawText, setRawText] = useState(SAMPLE_RAW_STATEMENT);
  const [sanitizedData, setSanitizedData] = useState(null);
  const [analysisInsights, setAnalysisInsights] = useState(null);
  const [analysisMeta, setAnalysisMeta] = useState(null);
  const [isSanitizing, setIsSanitizing] = useState(false);
  const [sanitizeSuccessMessage, setSanitizeSuccessMessage] = useState(null);
  const [sanitizeError, setSanitizeError] = useState(null);
  const [activeViewTab, setActiveViewTab] = useState('ALL'); // 'ALL' (split), 'RAW', 'SANITIZED'
  const [highlightPulse, setHighlightPulse] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [importError, setImportError] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);

  const sanitizedContainerRef = useRef(null);

  // Trigger live sanitization
  const handleSanitize = async () => {
    if (!rawText.trim() && !selectedFile) {
      setSanitizeError('Statement input is empty. Paste raw statement text or upload a statement file.');
      return;
    }
    setIsSanitizing(true);
    setSanitizeError(null);
    setSanitizeSuccessMessage(null);
    try {
      const data = await api.sanitizePreview(rawText, selectedFile);
      setSanitizedData(data);
      setAnalysisInsights(null); // Reset previous analysis run
      setAnalysisMeta(null);
      const count = data.total_redactions_count || 0;
      setSanitizeSuccessMessage(`Scrub Complete: ${count} sensitive token${count === 1 ? '' : 's'} masked.`);
      setHighlightPulse(true);
      setActiveViewTab('ALL'); // Ensure sanitized panel is shown
      setTimeout(() => setHighlightPulse(false), 2200);
      // Auto-scroll sanitized preview into view without searching
      setTimeout(() => {
        sanitizedContainerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 100);
    } catch (err) {
      console.error('Sanitization failed:', err);
      const msg = err?.response?.data?.error || err?.message || 'Sanitization failed. Check backend connection.';
      setSanitizeError(`Scrubbing Failed: ${msg}`);
    } finally {
      setIsSanitizing(false);
    }
  };

  // Trigger persistent parsing with consent
  const handleImportAndSave = async () => {
    setIsImporting(true);
    setImportResult(null);
    setImportError(null);
    try {
      const isTxt = selectedFile?.name?.toLowerCase().endsWith('.txt');
      const data = await api.parseStatement({
        rawText,
        file: selectedFile,
        format: isTxt ? 'txt' : 'csv',
        sessionId,
        persist: true,
      });
      const persistence = data.persistence || { imported: data.transactions?.length || 0, skipped_duplicates: 0 };
      setImportResult(persistence);
      if (onImportSuccess) onImportSuccess(data);
    } catch (err) {
      console.error('Import failed:', err);
      const errMsg = err.response?.data?.error || err.message;
      if (err.response?.status === 403 || errMsg === 'CONSENT_REQUIRED') {
        setImportError('CONSENT REQUIRED: Please grant explicit processing consent before saving financial data.');
      } else {
        setImportError(`Import failed: ${errMsg}`);
      }
    } finally {
      setIsImporting(false);
    }
  };

  // Trigger statement analysis (live Gemini if available, or offline rule-based insights)
  const handleRunAnalysis = async () => {
    if (!sanitizedData) return;
    setIsAnalyzing(true);
    try {
      // The backend derives every quoted figure from the active dataset only.
      // Pass that selection through so an imported statement can never be
      // explained with persona snapshot numbers (or vice versa).
      const result = await api.analyzeDocument(sanitizedData.sanitized_text_preview, sessionId, includePersona);
      setAnalysisInsights(result.advisor_insights);
      const metrics = result.metrics || {};
      setAnalysisMeta({
        source: result.analysis_source || result.advisor_insights?.source || 'OFFLINE_RULE_BASED',
        isAiGenerated: result.is_ai_generated || false,
        engineLabel: result.engine_label || (result.is_ai_generated ? 'Live Gemini AI Analysis' : 'Offline Rule-Based Financial Insights'),
        geminiAvailable: result.gemini_available || false,
        model: result.advisor_insights?.model || null,
        privacyGuarantee: result.privacy_guarantee,
        datasetSource: datasetSourceLabel || metrics.data_source || 'UNSPECIFIED',
        datasetStatus: metrics.dataset_status || 'UNSPECIFIED',
        reportingPeriod: metrics.reporting_period?.label || 'PERIOD NOT AVAILABLE',
        runwayStatus: metrics.runway_status || 'NOT PROVIDED',
        metricBasis: metrics.metric_basis || null,
      });
    } catch (err) {
      console.error(err);
      alert('Statement analysis failed. Please verify API configuration.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (file) {
      setSelectedFile(file);
      const reader = new FileReader();
      reader.onload = (event) => {
        setRawText(event.target.result);
      };
      reader.readAsText(file);
    }
  };

  return (
    <div className="space-y-6">
      
      {/* Header bar with Corner Accents */}
      <Card corners={12} cornerStroke={2} className="p-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center space-x-2">
              <span className="border border-white bg-black px-2 py-0.5 text-[9px] font-mono uppercase text-white font-bold tracking-widest">
                GATEWAY
              </span>
              <h3 className="text-xs font-mono font-bold uppercase tracking-widest text-white m-0">
                Interactive Privacy Inspector
              </h3>
            </div>
            <p className="text-[11px] font-mono text-[#AAAAAA] mt-1 m-0">
              Preview server-side identifier redaction and inspect the sanitized text before optional external AI analysis.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <TargetLock>
              <label className="cursor-pointer text-[10px] font-mono uppercase tracking-wider px-3 py-2 bg-[#0A0A0A] hover:bg-[#111111] text-[#AAAAAA] hover:text-white border border-[#202020] hover:border-white transition-all flex items-center gap-1.5">
                <Upload className="w-3.5 h-3.5 text-[#AAAAAA]" />
                <span>Upload Raw File</span>
                <input 
                  type="file" 
                  accept=".csv,.txt" 
                  className="hidden" 
                  onChange={handleFileUpload} 
                />
              </label>
            </TargetLock>

            <TargetLock>
              <button
                onClick={() => {
                  setSelectedFile(null);
                  setRawText(SAMPLE_RAW_STATEMENT);
                  setSanitizedData(null);
                  setAnalysisInsights(null);
                  setAnalysisMeta(null);
                }}
                className="text-[10px] font-mono uppercase tracking-wider px-3 py-2 text-[#AAAAAA] hover:text-white transition cursor-pointer"
              >
                Reset
              </button>
            </TargetLock>

            <TargetLock>
              <button
                onClick={handleSanitize}
                disabled={isSanitizing || !rawText.trim()}
                className="text-[10px] font-mono uppercase tracking-widest px-3 py-2 bg-[#111111] hover:bg-[#202020] text-white border border-[#202020] hover:border-white font-bold transition flex items-center gap-1.5 disabled:opacity-50 cursor-pointer"
              >
                <Lock className="w-3.5 h-3.5" />
                <span>{isSanitizing ? 'Scrubbing...' : 'Preview Scrub'}</span>
              </button>
            </TargetLock>

            {sanitizeSuccessMessage && (
              <span className="text-[9px] font-mono border border-emerald-500/60 bg-emerald-950/40 text-emerald-300 px-2.5 py-1.5 flex items-center gap-1.5 font-bold">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                {sanitizeSuccessMessage}
              </span>
            )}

            <TargetLock>
              <button
                onClick={handleImportAndSave}
                disabled={isImporting || !rawText.trim()}
                className="text-[10px] font-mono uppercase tracking-widest px-4 py-2 bg-white hover:bg-[#AAAAAA] text-black font-bold transition flex items-center gap-1.5 disabled:opacity-50 cursor-pointer shadow-sm"
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>{isImporting ? 'Ingesting...' : 'Import With Consent'}</span>
              </button>
            </TargetLock>
          </div>
        </div>
      </Card>

      {/* Immediate Sanitization Error Feedback */}
      {sanitizeError && (
        <div className="border border-[#662222] bg-[#140808] p-4 font-mono text-xs flex items-center justify-between text-[#FF8888]">
          <div className="flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
            <span>{sanitizeError}</span>
          </div>
          <button
            type="button"
            onClick={() => setSanitizeError(null)}
            className="text-[9px] uppercase border border-[#662222] px-2 py-0.5 hover:bg-white hover:text-black cursor-pointer text-[#AAAAAA]"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Import Status Feedback */}
      {importResult && (
        <div className="border border-white bg-[#0A0A0A] p-4 font-mono text-xs flex items-center justify-between text-white shadow-[0_0_15px_rgba(255,255,255,0.1)]">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-white" />
            <span>
              Ingestion complete: {importResult.imported} transaction(s) stored securely. {importResult.skipped_duplicates} duplicate(s) prevented via SHA-256 fingerprint.
            </span>
          </div>
          <span className="text-[9px] uppercase border border-white bg-black px-2 py-0.5 font-bold">Encrypted DB Stored</span>
        </div>
      )}

      {importError && (
        <div className="border border-[#404040] bg-[#0A0A0A] p-4 font-mono text-xs flex items-center space-x-2 text-[#AAAAAA]">
          <AlertCircle className="w-4 h-4 text-white shrink-0" />
          <span>{importError}</span>
        </div>
      )}

      {/* View Switcher Tabs: Toggle between Raw, Sanitized, or Side-by-Side */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#202020] pb-2 font-mono">
        <div className="flex items-center gap-1 border border-[#202020] bg-[#0A0A0A] p-0.5">
          <button
            type="button"
            onClick={() => setActiveViewTab('ALL')}
            className={`px-2.5 py-1 text-[9px] uppercase tracking-wider font-bold cursor-pointer transition-colors ${
              activeViewTab === 'ALL' ? 'bg-white text-black' : 'text-[#888888] hover:text-white'
            }`}
          >
            Side-by-Side
          </button>
          <button
            type="button"
            onClick={() => setActiveViewTab('RAW')}
            className={`px-2.5 py-1 text-[9px] uppercase tracking-wider font-bold cursor-pointer transition-colors ${
              activeViewTab === 'RAW' ? 'bg-white text-black' : 'text-[#888888] hover:text-white'
            }`}
          >
            1. Raw Input ({rawText.length} B)
          </button>
          <button
            type="button"
            onClick={() => setActiveViewTab('SANITIZED')}
            className={`px-2.5 py-1 text-[9px] uppercase tracking-wider font-bold cursor-pointer transition-colors ${
              activeViewTab === 'SANITIZED' ? 'bg-white text-black' : 'text-[#888888] hover:text-white'
            }`}
          >
            2. Scrubbed Preview ({sanitizedData ? `${sanitizedData.sanitized_length} B` : 'Awaiting'})
          </button>
        </div>

        <div className="flex items-center gap-2 text-[9px] text-[#888888]">
          {sanitizedData ? (
            <span className="border border-white/40 bg-black text-white px-2 py-0.5 font-bold">
              ✓ {sanitizedData.total_redactions_count} Tokens Isolated
            </span>
          ) : (
            <span>Awaiting preview scrub pass</span>
          )}
        </div>
      </div>

      {/* Split Screen: Raw vs Sanitized */}
      <div className={`grid gap-6 ${activeViewTab === 'ALL' ? 'grid-cols-1 lg:grid-cols-2' : 'grid-cols-1'}`}>
        
        {/* Left Column: Raw Document */}
        {(activeViewTab === 'ALL' || activeViewTab === 'RAW') && (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-[11px] font-mono uppercase tracking-wider text-[#AAAAAA] border-b border-[#202020] pb-2">
              <span className="flex items-center gap-1.5 text-white">
                <AlertCircle className="w-3.5 h-3.5 text-white" />
                1. Raw Boundary (Sensitive Ingestion)
              </span>
              <span className="flex items-center gap-2">
                <span className="border border-[#404040] bg-[#111111] text-[#AAAAAA] px-1.5 py-0.5 text-[8px] font-bold tracking-wider">
                  SYNTHETIC DEMO DATA
                </span>
                <span className="text-[#8A8A8A]">{rawText.length} Bytes</span>
              </span>
            </div>
            
            <div className="relative">
              <textarea
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                rows={16}
                placeholder="Paste raw bank statement or loan text here..."
                className="w-full bg-[#050505] border border-[#202020] p-4 font-mono text-xs text-[#AAAAAA] leading-relaxed focus:outline-none focus:border-white resize-none selection:bg-white selection:text-black transition-colors"
              />
              <div className="absolute top-2 right-2 text-[9px] border border-[#404040] bg-black text-[#AAAAAA] px-1.5 py-0.5 font-mono uppercase">
                Host Memory Only
              </div>
            </div>
            <p className="text-[9px] text-[#8A8A8A] font-mono m-0 leading-relaxed">
              The preloaded sample is hard-coded synthetic demonstration data. It contains no
              real customer information. Pasted text is sent to the sanitizer for this request
              only and is not stored by this demonstration.
            </p>
          </div>
        )}

        {/* Right Column: Sanitized Stream */}
        {(activeViewTab === 'ALL' || activeViewTab === 'SANITIZED') && (
          <div ref={sanitizedContainerRef} className="space-y-3">
            <div className="flex items-center justify-between text-[11px] font-mono uppercase tracking-wider text-[#AAAAAA] border-b border-[#202020] pb-2">
              <span className="flex items-center gap-1.5 text-white">
                <ShieldCheck className="w-3.5 h-3.5 text-white" />
                2. Scrubbed Transaction Stream (Sanitized Payload)
              </span>
              <span className="text-[#8A8A8A]">
                {sanitizedData ? `${sanitizedData.sanitized_length} Bytes` : 'Awaiting Sanitization'}
              </span>
            </div>

            <div className="relative">
              <div className={`w-full h-[335px] overflow-y-auto bg-[#050505] border p-4 font-mono text-xs text-white leading-relaxed whitespace-pre-wrap select-all transition-all duration-300 ${
                highlightPulse ? 'border-white ring-1 ring-white bg-[#0A0A0A]' : 'border-[#202020]'
              }`}>
                {sanitizedData ? (
                  sanitizedData.sanitized_text_preview
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-[#8A8A8A] space-y-2">
                    <Lock className="w-8 h-8 text-[#767676]" />
                    <p className="text-[11px] font-mono uppercase text-[#8A8A8A]">
                      Awaiting deterministic scrubbing pass
                    </p>
                  </div>
                )}
              </div>
              {sanitizedData && (
                <div className="absolute top-2 right-2 text-[9px] border border-white bg-black text-white px-2 py-0.5 font-mono uppercase tracking-wider font-bold shadow-sm">
                  PII Redacted
                </div>
              )}
            </div>
          </div>
        )}

      </div>

      {/* Live Gemini Integration Status Indicator */}
      <Card
        interactive={false}
        className="p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 font-mono text-xs"
      >
        <div className="flex items-center space-x-2.5">
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${
              analysisMeta?.isAiGenerated
                ? 'bg-[#4ADE80]'
                : analysisMeta
                  ? 'bg-[#D6A44A]'
                  : 'bg-[#666666]'
            }`}
          />
          <span className="text-[#AAAAAA]">
            Gemini Status:{' '}
            <strong className="text-white">
              {analysisMeta?.isAiGenerated
                ? `LIVE — ${analysisMeta.model || 'configured model'}`
                : analysisMeta
                  ? 'OFFLINE FALLBACK — CHECK PROVIDER CONFIGURATION'
                  : 'NOT CHECKED — RUN FINANCIAL ANALYSIS'}
            </strong>
          </span>
        </div>
        <span className="text-[10px] uppercase text-[#888888] border border-[#333333] px-2.5 py-1 bg-[#0A0A0A] font-bold">
          Active Mode:{' '}
          {analysisMeta?.isAiGenerated
            ? 'Live Gemini'
            : analysisMeta
              ? 'Offline Rule-Based Analysis'
              : 'Awaiting Analysis'}
        </span>
      </Card>

      {/* Redactions Audit Strip */}
      {sanitizedData && (
        <Card className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Terminal className="w-4 h-4 text-white" />
              <span className="text-[10px] font-mono uppercase tracking-widest text-white font-bold">
                Redaction Log: {sanitizedData.total_redactions_count} Tokens Isolated
              </span>
            </div>
            
            <button
              onClick={handleRunAnalysis}
              disabled={isAnalyzing}
              className="text-[10px] font-mono uppercase tracking-widest px-3 py-1.5 bg-white text-black font-bold hover:bg-[#AAAAAA] transition flex items-center gap-1.5 disabled:opacity-50 cursor-pointer shadow-sm"
            >
              <Sparkles className="w-3 h-3 text-black" />
              <span>{isAnalyzing ? 'Analyzing...' : '3. Run Financial Statement Analysis'}</span>
            </button>
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            {sanitizedData.redactions_audit?.map((item, idx) => (
              <div 
                key={idx}
                className="text-[10px] font-mono border border-[#202020] bg-black px-2.5 py-1 flex items-center space-x-2 hover:border-white transition-colors"
              >
                <span className="text-white font-bold">{item.placeholder}</span>
                <span className="text-[#AAAAAA]">×{item.count}</span>
                <span className="text-[9px] text-[#8A8A8A] uppercase">[{item.type}]</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Financial Insights Panel (Strictly Labeled: Offline Rule-Based or Gemini) */}
      {analysisInsights && (
        <Card className="p-6 space-y-6">
          <div className="flex items-center justify-between border-b border-[#202020] pb-4">
            <div className="flex items-center space-x-2">
              <Sparkles className="w-4 h-4 text-white" />
              <h4 className="text-xs font-mono font-bold uppercase tracking-widest text-white m-0">
                {analysisMeta?.isAiGenerated ? 'Gemini AI Financial Analysis' : 'Offline Rule-Based Financial Insights'}
              </h4>
            </div>
            {analysisMeta?.isAiGenerated ? (
              <span className="text-[9px] font-mono uppercase border border-white bg-black px-2 py-0.5 text-white font-bold">
                Live {analysisMeta?.model || analysisInsights?.model || 'Gemini'}
              </span>
            ) : (
              <span className="text-[9px] font-mono uppercase border border-[#404040] bg-[#111111] px-2 py-0.5 text-[#AAAAAA] font-bold">
                Offline Rule Engine
              </span>
            )}
          </div>

          {/* Dataset provenance: value source, period and observed/estimated status */}
          {analysisMeta && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 text-[9px] font-mono uppercase tracking-wider">
              <div className="border border-[#202020] bg-black p-2.5">
                <span className="block text-[#777777]">Dataset source</span>
                <span className="block text-white font-bold mt-1">{analysisMeta.datasetSource}</span>
              </div>
              <div className="border border-[#202020] bg-black p-2.5">
                <span className="block text-[#777777]">Reporting period</span>
                <span className="block text-white font-bold mt-1">{analysisMeta.reportingPeriod}</span>
              </div>
              <div className="border border-[#202020] bg-black p-2.5">
                <span className="block text-[#777777]">Metric status</span>
                <span className="block text-white font-bold mt-1">{analysisMeta.datasetStatus}</span>
              </div>
              <div className="border border-[#202020] bg-black p-2.5">
                <span className="block text-[#777777]">Runway status</span>
                <span className="block text-white font-bold mt-1">{analysisMeta.runwayStatus}</span>
              </div>
            </div>
          )}

          {/* Offline Fallback Clarification Banner */}
          {!analysisMeta?.isAiGenerated && (
            <div className="border border-[#333333] bg-black p-3.5 text-xs font-mono text-[#AAAAAA] flex items-start space-x-3">
              <Terminal className="w-4 h-4 text-white shrink-0 mt-0.5" />
              <div className="space-y-1">
                <div className="text-white font-bold uppercase tracking-wider text-[11px]">
                  Offline Rule-Based Financial Insights
                </div>
                <p className="text-[11px] text-[#888888] m-0 leading-relaxed">
                  The backend did not return a validated live Gemini response for this analysis. The insights below were generated by the offline rule engine. This can happen when the API key is missing or the provider request fails; check the backend configuration and logs before describing this run as live AI.
                </p>
              </div>
            </div>
          )}

          {/* Plain English Summary */}
          <div className="border border-[#202020] bg-black p-4">
            <span className="text-[10px] font-mono uppercase tracking-widest text-[#AAAAAA] block mb-2">
              {analysisMeta?.isAiGenerated ? 'AI Executive Synthesis' : 'Deterministic Financial Synthesis'}
            </span>
            <p className="text-xs font-mono text-[#AAAAAA] leading-relaxed m-0">
              {analysisInsights.plain_english_summary}
            </p>
          </div>

          {/* Actionable Wins and Predatory Risks */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            
            {/* Wins */}
            <div className="space-y-3">
              <span className="text-[10px] font-mono uppercase tracking-widest text-white font-bold block border-b border-[#202020] pb-1">
                Review Candidates &amp; Confirmed Commitments
              </span>
              <div className="space-y-2">
                {analysisInsights.top_actionable_wins?.map((win, idx) => (
                  <div key={idx} className="border border-[#202020] bg-black p-3 space-y-1 hover:border-white transition-colors">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-mono font-bold text-white">{win.title}</span>
                      <span className="text-xs font-mono text-[#AAAAAA]">{win.impact_amount}</span>
                    </div>
                    <p className="text-[11px] font-mono text-[#8A8A8A] m-0">{win.action}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Predatory Risks */}
            <div className="space-y-3">
              <span className="text-[10px] font-mono uppercase tracking-widest text-white font-bold block border-b border-[#202020] pb-1">
                Deceptive Terms & Fine Print
              </span>
              <div className="space-y-2">
                {analysisInsights.hidden_risks_and_predatory_clauses?.map((risk, idx) => (
                  <div key={idx} className="border border-[#202020] bg-black p-3 space-y-1 hover:border-white transition-colors">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-mono font-bold text-white">{risk.risk_name}</span>
                      <span className="text-[9px] font-mono uppercase border border-[#404040] bg-[#111111] px-1 py-0.2 text-[#AAAAAA]">
                        {risk.severity}
                      </span>
                    </div>
                    <p className="text-[11px] font-mono text-[#8A8A8A] m-0">{risk.explanation}</p>
                  </div>
                ))}
              </div>
            </div>

          </div>

          <div className="text-[10px] font-mono text-[#8A8A8A] border-t border-[#202020] pt-3">
            {analysisInsights.disclaimer}
          </div>
        </Card>
      )}

    </div>
  );
}
