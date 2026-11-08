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
  const [aiAnalysis, setAiAnalysis] = useState(null);
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
      setAiAnalysis(null); // Reset previous AI run
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

  // Trigger zero-knowledge LLM analysis
  const handleRunAiAnalysis = async () => {
    if (!sanitizedData) return;
    setIsAnalyzing(true);
    try {
      const result = await api.analyzeDocument(sanitizedData.sanitized_text_preview);
      setAiAnalysis(result.advisor_insights);
    } catch (err) {
      console.error(err);
      alert('AI analysis failed. Please verify API configuration.');
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
      
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border border-zinc-800 bg-black p-6">
        <div>
          <div className="flex items-center space-x-2">
            <span className="border border-white px-1.5 py-0.2 text-[9px] font-mono uppercase text-white font-bold">
              GATEWAY
            </span>
            <h3 className="text-xs font-mono font-bold uppercase tracking-widest text-white m-0">
              Interactive Privacy Inspector
            </h3>
          </div>
          <p className="text-[11px] font-mono text-zinc-500 mt-1 m-0">
            Real-time verification of local PII scrubbing before any token departs to external inference engines.
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <label className="cursor-pointer text-[10px] font-mono uppercase tracking-wider px-3 py-2 bg-zinc-950 hover:bg-zinc-900 text-zinc-300 border border-zinc-800 transition flex items-center gap-1.5">
            <Upload className="w-3.5 h-3.5 text-zinc-400" />
            <span>Upload Raw File</span>
            <input 
              type="file" 
              accept=".csv,.txt" 
              className="hidden" 
              onChange={handleFileUpload} 
            />
          </label>

          <button
            onClick={() => {
              setSelectedFile(null);
              setRawText(SAMPLE_RAW_STATEMENT);
              setSanitizedData(null);
              setAiAnalysis(null);
            }}
            className="text-[10px] font-mono uppercase tracking-wider px-3 py-2 text-zinc-500 hover:text-white transition cursor-pointer"
          >
            Reset
          </button>

          <button
            onClick={handleSanitize}
            disabled={isSanitizing || !rawText.trim()}
            className="text-[10px] font-mono uppercase tracking-widest px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-white font-bold transition flex items-center gap-1.5 disabled:opacity-50 cursor-pointer"
          >
            <Lock className="w-3.5 h-3.5" />
            <span>{isSanitizing ? 'Scrubbing...' : 'Preview Scrub'}</span>
          </button>

          <button
            onClick={handleImportAndSave}
            disabled={isImporting || !rawText.trim()}
            className="text-[10px] font-mono uppercase tracking-widest px-4 py-2 bg-white hover:bg-zinc-200 text-black font-bold transition flex items-center gap-1.5 disabled:opacity-50 cursor-pointer"
          >
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>{isImporting ? 'Ingesting...' : 'Import With Consent'}</span>
          </button>
        </div>
      </div>

      {/* Import Status Feedback */}
      {importResult && (
        <div className="border border-zinc-700 bg-zinc-950 p-4 font-mono text-xs flex items-center justify-between text-white">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-white" />
            <span>
              Ingestion complete: {importResult.imported} transaction(s) stored securely. {importResult.skipped_duplicates} duplicate(s) prevented via SHA-256 fingerprint.
            </span>
          </div>
          <span className="text-[9px] uppercase border border-white px-2 py-0.5 font-bold">Encrypted DB Stored</span>
        </div>
      )}

      {importError && (
        <div className="border border-zinc-700 bg-zinc-950 p-4 font-mono text-xs flex items-center space-x-2 text-zinc-300">
          <AlertCircle className="w-4 h-4 text-white shrink-0" />
          <span>{importError}</span>
        </div>
      )}

      {/* Split Screen: Raw vs Sanitized */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Left Column: Raw Document */}
        <div className="space-y-3">
          <div className="flex items-center justify-between text-[11px] font-mono uppercase tracking-wider text-zinc-400 border-b border-zinc-900 pb-2">
            <span className="flex items-center gap-1.5 text-zinc-300">
              <AlertCircle className="w-3.5 h-3.5 text-white" />
              1. Raw Boundary (Sensitive Ingestion)
            </span>
            <span className="text-zinc-500">{rawText.length} Bytes</span>
          </div>
          
          <div className="relative">
            <textarea
              value={rawText}
              onChange={(e) => setRawText(e.target.value)}
              rows={16}
              placeholder="Paste raw bank statement or loan text here..."
              className="w-full bg-zinc-950 border border-zinc-800 p-4 font-mono text-xs text-zinc-300 leading-relaxed focus:outline-none focus:border-zinc-500 resize-none selection:bg-white selection:text-black"
            />
            <div className="absolute top-2 right-2 text-[9px] border border-zinc-700 bg-zinc-900 text-zinc-300 px-1.5 py-0.5 font-mono uppercase">
              Host Memory Only
            </div>
          </div>
        </div>

        {/* Right Column: Sanitized Stream */}
        <div className="space-y-3">
          <div className="flex items-center justify-between text-[11px] font-mono uppercase tracking-wider text-zinc-400 border-b border-zinc-900 pb-2">
            <span className="flex items-center gap-1.5 text-white">
              <ShieldCheck className="w-3.5 h-3.5 text-white" />
              2. Redacted Stream (Egress Payload)
            </span>
            <span className="text-zinc-500">
              {sanitizedData ? `${sanitizedData.sanitized_length} Bytes` : 'Awaiting Sanitization'}
            </span>
          </div>

          <div className="relative">
            <div className="w-full h-[335px] overflow-y-auto bg-zinc-950 border border-zinc-800 p-4 font-mono text-xs text-white leading-relaxed whitespace-pre-wrap select-all">
              {sanitizedData ? (
                sanitizedData.sanitized_text_preview
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-zinc-600 space-y-2">
                  <Lock className="w-8 h-8 text-zinc-700" />
                  <p className="text-[11px] font-mono uppercase text-zinc-600">
                    Awaiting deterministic scrubbing pass
                  </p>
                </div>
              )}
            </div>
            {sanitizedData && (
              <div className="absolute top-2 right-2 text-[9px] border border-white bg-black text-white px-2 py-0.5 font-mono uppercase tracking-wider font-bold">
                PII Redacted
              </div>
            )}
          </div>
        </div>

      </div>

      {/* Redactions Audit Strip */}
      {sanitizedData && (
        <div className="border border-zinc-800 bg-zinc-950 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Terminal className="w-4 h-4 text-white" />
              <span className="text-[10px] font-mono uppercase tracking-widest text-white font-bold">
                Redaction Log: {sanitizedData.total_redactions_count} Tokens Isolated
              </span>
            </div>
            
            <button
              onClick={handleRunAiAnalysis}
              disabled={isAnalyzing}
              className="text-[10px] font-mono uppercase tracking-widest px-3 py-1.5 bg-white text-black font-bold hover:bg-zinc-200 transition flex items-center gap-1.5 disabled:opacity-50 cursor-pointer"
            >
              <Sparkles className="w-3 h-3 text-black" />
              <span>{isAnalyzing ? 'Analyzing...' : '3. Zero-Knowledge AI Demystifier'}</span>
            </button>
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            {sanitizedData.redactions_audit?.map((item, idx) => (
              <div 
                key={idx}
                className="text-[10px] font-mono border border-zinc-800 bg-black px-2.5 py-1 flex items-center space-x-2"
              >
                <span className="text-white font-bold">{item.placeholder}</span>
                <span className="text-zinc-500">×{item.count}</span>
                <span className="text-[9px] text-zinc-600 uppercase">[{item.type}]</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* AI Plain-English Insights Panel */}
      {aiAnalysis && (
        <div className="border border-zinc-700 bg-zinc-900 p-6 space-y-6">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-4">
            <div className="flex items-center space-x-2">
              <Sparkles className="w-4 h-4 text-white" />
              <h4 className="text-xs font-mono font-bold uppercase tracking-widest text-white m-0">
                AI Statement Demystifier
              </h4>
            </div>
            <span className="text-[9px] font-mono uppercase border border-white px-2 py-0.5 text-white font-bold">
              Zero-PII Egress Confirmed
            </span>
          </div>

          {/* Plain English Summary */}
          <div className="border border-zinc-800 bg-black p-4">
            <span className="text-[10px] font-mono uppercase tracking-widest text-zinc-500 block mb-2">
              Executive Synthesis
            </span>
            <p className="text-xs font-mono text-zinc-300 leading-relaxed m-0">
              {aiAnalysis.plain_english_summary}
            </p>
          </div>

          {/* Actionable Wins and Predatory Risks */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            
            {/* Wins */}
            <div className="space-y-3">
              <span className="text-[10px] font-mono uppercase tracking-widest text-white font-bold block border-b border-zinc-800 pb-1">
                Identified Cashflow Recovery
              </span>
              <div className="space-y-2">
                {aiAnalysis.top_actionable_wins?.map((win, idx) => (
                  <div key={idx} className="border border-zinc-800 bg-black p-3 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-mono font-bold text-white">{win.title}</span>
                      <span className="text-xs font-mono text-zinc-300">{win.impact_amount}</span>
                    </div>
                    <p className="text-[11px] font-mono text-zinc-500 m-0">{win.action}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Predatory Risks */}
            <div className="space-y-3">
              <span className="text-[10px] font-mono uppercase tracking-widest text-white font-bold block border-b border-zinc-800 pb-1">
                Deceptive Terms & Fine Print
              </span>
              <div className="space-y-2">
                {aiAnalysis.hidden_risks_and_predatory_clauses?.map((risk, idx) => (
                  <div key={idx} className="border border-zinc-800 bg-black p-3 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-mono font-bold text-white">{risk.risk_name}</span>
                      <span className="text-[9px] font-mono uppercase border border-zinc-700 bg-zinc-950 px-1 py-0.2 text-zinc-300">
                        {risk.severity}
                      </span>
                    </div>
                    <p className="text-[11px] font-mono text-zinc-500 m-0">{risk.explanation}</p>
                  </div>
                ))}
              </div>
            </div>

          </div>

          <div className="text-[10px] font-mono text-zinc-600 border-t border-zinc-800 pt-3">
            {aiAnalysis.disclaimer}
          </div>
        </div>
      )}

    </div>
  );
}
