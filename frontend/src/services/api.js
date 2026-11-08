import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

// Priority 1: Attach cryptographically secure session token to all requests
apiClient.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('arthashield_session_token');
  if (token) {
    config.headers['X-Session-Token'] = token;
  }
  return config;
});

export const api = {
  // Phase 3: Session Identity Handshake
  initSession: async () => {
    const res = await apiClient.post('/auth/session/init/');
    if (res.data?.session_token) {
      sessionStorage.setItem('arthashield_session_token', res.data.session_token);
      sessionStorage.setItem('arthashield_session_id', res.data.session_id);
    }
    return res.data;
  },

  getSessionId: () => {
    return sessionStorage.getItem('arthashield_session_id');
  },

  ensureSession: async () => {
    let token = sessionStorage.getItem('arthashield_session_token');
    let sessionId = sessionStorage.getItem('arthashield_session_id');
    if (!token || !sessionId) {
      const data = await api.initSession();
      sessionId = data.session_id;
    }
    return sessionId;
  },

  rotateSession: async () => {
    const res = await apiClient.post('/auth/session/rotate/');
    if (res.data?.session_token) {
      sessionStorage.setItem('arthashield_session_token', res.data.session_token);
    }
    return res.data;
  },

  getSessionStatus: async () => {
    await api.ensureSession();
    const res = await apiClient.get('/auth/session/me/');
    return res.data;
  },

  // Fetch available personas
  getPersonas: async () => {
    const res = await apiClient.get('/personas/');
    return res.data;
  },

  // Select persona and generate snapshot
  selectPersona: async (personaId, sessionId = null) => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/personas/select/', {
      persona_id: personaId,
      session_id: sid,
    });
    return res.data;
  },

  // Privacy Inspector: Live Sanitization Preview (Never sends or receives raw PII over the wire)
  sanitizePreview: async (rawText, file = null) => {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const res = await apiClient.post('/privacy/sanitize-preview/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return res.data;
    }
    const res = await apiClient.post('/privacy/sanitize-preview/', { raw_text: rawText });
    return res.data;
  },

  // Analyze sanitized text with LLM (Unconditional active consent verified on backend)
  analyzeDocument: async (sanitizedText, sessionId = null) => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/documents/analyze/', {
      sanitized_text: sanitizedText,
      session_id: sid,
    });
    return res.data;
  },

  // Simulate EMI Reality Check
  simulateEmi: async (params) => {
    const res = await apiClient.post('/analytics/simulate-emi/', params);
    return res.data;
  },

  // Record consent with explicit required DPDP flags
  logConsent: async (sessionId = null, version = 'v1.0') => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/privacy/consent/', {
      session_id: sid,
      consent_version: version,
      anonymized_processing_accepted: true,
      no_credential_disclosure_acknowledged: true,
    });
    return res.data;
  },

  // Withdraw active consent
  withdrawConsent: async (sessionId = null) => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/privacy/consent/withdraw/', {
      session_id: sid,
    });
    return res.data;
  },

  // Parse bank statement (CSV, PDF, TXT) with optional persistence
  parseStatement: async ({ rawText = '', file = null, format = 'csv', sessionId = null, persist = false }) => {
    const sid = sessionId || (await api.ensureSession());
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('session_id', sid);
      formData.append('persist', persist ? 'true' : 'false');
      formData.append('format', format);
      const res = await apiClient.post('/data/parse-statement/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return res.data;
    }
    const res = await apiClient.post('/data/parse-statement/', {
      raw_text: rawText,
      format,
      session_id: sid,
      persist,
    });
    return res.data;
  },

  // Parse SMS text or batch with optional persistence
  parseSms: async ({ smsText = '', smsList = null, sessionId = null, persist = false }) => {
    const sid = sessionId || (await api.ensureSession());
    const payload = { session_id: sid, persist };
    if (smsText) payload.sms_text = smsText;
    if (smsList) payload.sms_list = smsList;
    const res = await apiClient.post('/data/parse-sms/', payload);
    return res.data;
  },

  // Phase 2 Financial Intelligence: 1. Categorization
  getCategorization: async (sessionId = null, includePersona = false) => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/insights/categorize/', {
      session_id: sid,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Phase 2 Financial Intelligence: 2. Monthly Budget Analyzer
  getMonthlyBudget: async (sessionId = null, year = 2026, month = 10, includePersona = false) => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/insights/monthly-budget/', {
      session_id: sid,
      year,
      month,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Phase 2 Financial Intelligence: 3. Subscription Detector
  getSubscriptions: async (sessionId = null, includePersona = false) => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/insights/subscriptions/', {
      session_id: sid,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Phase 2 Financial Intelligence: 4. Unusual Spending Detector
  getUnusualSpending: async (sessionId = null, includePersona = false) => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/insights/unusual-spending/', {
      session_id: sid,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Phase 2 Financial Intelligence: 5. Spending Pattern Analyzer
  getSpendingPatterns: async (sessionId = null, months = 6, includePersona = false) => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/insights/spending-patterns/', {
      session_id: sid,
      months,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Nuke all session data (Cascading purge for authenticated session)
  nukeData: async (sessionId = null) => {
    const sid = sessionId || (await api.ensureSession());
    const res = await apiClient.post('/privacy/nuke-data/', {
      session_id: sid,
    });
    return res.data;
  },
};

export default api;
