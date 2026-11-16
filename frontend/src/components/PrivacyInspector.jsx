import React, { useState } from 'react';
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

export default function PrivacyInspector({ sessionId = null, onImportSuccess }) {
  const [rawText, setRawText] = useState(SAMPLE_RAW_STATEMENT);
  const [sanitizedData, setSanitizedData] = useState(null);
  const [analysisInsights, setAnalysisInsights] = useState(null);
  const [analysisMeta, setAnalysisMeta] = useState(null);
  const [isSanitizing, setIsSanitizing] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [importError, setImportError] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);

  // Trigger live sanitization
  const handleSanitize = async () => {
    setIsSanitizing(true);
    try {
      const data = await api.sanitizePreview(rawText, selectedFile);
      setSanitizedData(data);
      setAnalysisInsights(null); // Reset previous analysis run
      setAnalysisMeta(null);
    } catch (err) {
      console.error(err);
      alert('Sanitization failed. Check backend connection.');
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
      const result = await api.analyzeDocument(sanitizedData.sanitized_text_preview);
      setAnalysisInsights(result.advisor_insights);
      setAnalysisMeta({
        source: result.analysis_source || result.advisor_insights?.source || 'OFFLINE_RULE_BASED',
        isAiGenerated: result.is_ai_generated || false,
        engineLabel: result.engine_label || (result.is_ai_generated ? 'Live Gemini AI Analysis' : 'Offline Rule-Based Financial Insights'),
        geminiAvailable: result.gemini_available || false,
        model: result.advisor_insights?.model || null,
        privacyGuarantee: result.privacy_guarantee,
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
              Real-time verification of local PII scrubbing before any token departs to external inference engines.
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

      {/* Split Screen: Raw vs Sanitized */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Left Column: Raw Document */}
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

        {/* Right Column: Sanitized Stream */}
        <div className="space-y-3">
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
            <div className="w-full h-[335px] overflow-y-auto bg-[#050505] border border-[#202020] p-4 font-mono text-xs text-white leading-relaxed whitespace-pre-wrap select-all">
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
                Identified Cashflow Recovery
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
