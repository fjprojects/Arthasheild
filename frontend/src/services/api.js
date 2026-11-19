import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

const SESSION_TOKEN_KEY = 'arthashield_session_token';
const SESSION_ID_KEY = 'arthashield_session_id';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

/**
 * Active session store.
 *
 * The token and the session id are always read and written as a pair, so the
 * id can never drift away from the token that authenticates it. The module
 * mirror is the source of truth for the running application; sessionStorage is
 * only the persistence layer between page loads.
 *
 * `initPromise` makes session creation single-flight: concurrent callers share
 * one request, so a double-invoked mount effect (React StrictMode) or any
 * other concurrent bootstrap can never create competing sessions.
 */
const readStoredSession = () => {
  try {
    const token = sessionStorage.getItem(SESSION_TOKEN_KEY);
    const sessionId = sessionStorage.getItem(SESSION_ID_KEY);
    if (token && sessionId) return { token, sessionId };
  } catch {
    console.warn('Session storage is unavailable; the session is kept in memory only.');
  }
  return null;
};

let activeSession = readStoredSession();
let initPromise = null;
const sessionListeners = new Set();

const notifySession = () => {
  sessionListeners.forEach((listener) => {
    try {
      listener(activeSession);
    } catch (err) {
      console.error('Session listener failed:', err);
    }
  });
};

const writeSession = (token, sessionId) => {
  if (!token || !sessionId) return activeSession;
  activeSession = { token, sessionId };
  try {
    sessionStorage.setItem(SESSION_TOKEN_KEY, token);
    sessionStorage.setItem(SESSION_ID_KEY, sessionId);
  } catch {
    // A private-mode browser can refuse storage: the in-memory session still works.
  }
  notifySession();
  return activeSession;
};

const clearSession = () => {
  activeSession = null;
  try {
    sessionStorage.removeItem(SESSION_TOKEN_KEY);
    sessionStorage.removeItem(SESSION_ID_KEY);
  } catch {
    // ignore
  }
  notifySession();
};

// Priority 1: Attach cryptographically secure session token to all requests
apiClient.interceptors.request.use((config) => {
  const token = activeSession?.token;
  if (token && !config.headers['X-Session-Token']) {
    config.headers['X-Session-Token'] = token;
  }
  return config;
});

// Automatic recovery on expired/invalid session
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const response = error.response;
    const config = error.config;

    // Session-id drift recovery. The server reports which session the
    // request's own token belongs to; the client corrects its own bookkeeping
    // and retries. The token stays the authority, so no other session can be
    // reached through this path.
    if (
      response &&
      response.status === 403 &&
      response.data?.code === 'SESSION_MISMATCH' &&
      config &&
      !config.__sessionIdRetry
    ) {
      const authenticated = response.data.authenticated_session;
      if (authenticated && activeSession && authenticated !== activeSession.sessionId) {
        config.__sessionIdRetry = true;
        writeSession(activeSession.token, authenticated);
        const payload = config.data;
        if (typeof FormData !== 'undefined' && payload instanceof FormData) {
          payload.set('session_id', authenticated);
        } else if (payload && typeof payload === 'object') {
          payload.session_id = authenticated;
        }
        return apiClient(config);
      }
    }

    if (response && response.status === 401) {
      clearSession();
    }
    return Promise.reject(error);
  }
);

/**
 * Resolves the session id a request must carry.
 *
 * The active session - the one whose token is attached to the request - is the
 * only valid choice, because the server rejects any body id that does not
 * match the authenticated session. A stale id supplied by a caller is ignored.
 */
const resolveActiveSession = async (requestedId) => {
  const activeId = await api.ensureSession();
  if (requestedId && requestedId !== activeId) {
    console.warn('A stale session id was supplied; the active session is used instead.');
  }
  return activeId;
};

export const api = {
  // Phase 3: Session Identity Handshake
  /**
   * Establishes the active session.
   *
   * Single-flight: concurrent callers share one request, so a double-invoked
   * mount effect can never create competing sessions. When a valid token is
   * already held, the server resumes that session instead of creating a new
   * one, so a retried bootstrap cannot fork the session either.
   */
  initSession: async () => {
    if (initPromise) return initPromise;
    const request = (async () => {
      const resumeToken = activeSession?.token;
      const res = await apiClient.post('/auth/session/init/', {}, {
        headers: resumeToken
          ? { 'X-Session-Token': resumeToken }
          : { 'X-Session-Token': '' },
      });
      const { session_token: token, session_id: sessionId } = res.data || {};
      if (!token || !sessionId) {
        throw new Error('Session initialization did not return a session.');
      }
      writeSession(token, sessionId);
      return res.data;
    })();
    initPromise = request;
    try {
      return await request;
    } finally {
      initPromise = null;
    }
  },

  getSessionId: () => {
    return activeSession?.sessionId || null;
  },

  /**
   * The active session state. `ready` is false while no session is established,
   * so callers can avoid firing authenticated requests too early.
   */
  getSessionState: () => ({
    sessionId: activeSession?.sessionId || null,
    token: activeSession?.token || null,
    ready: Boolean(activeSession),
  }),

  /**
   * Subscribes to session changes (creation, replacement, clearing).
   * Returns an unsubscribe function.
   */
  subscribeToSession: (listener) => {
    sessionListeners.add(listener);
    return () => {
      sessionListeners.delete(listener);
    };
  },

  /**
   * Explicitly forgets the active session (used when a session must not be
   * restored, e.g. after an unrecoverable authentication failure).
   */
  clearSession: () => clearSession(),

  ensureSession: async () => {
    if (activeSession) return activeSession.sessionId;
    await api.initSession();
    if (!activeSession) {
      throw new Error('Unable to establish a secure session.');
    }
    // Re-read the store: the returned id must belong to the token that is
    // actually attached to the request.
    return activeSession.sessionId;
  },

  rotateSession: async () => {
    const res = await apiClient.post('/auth/session/rotate/');
    if (res.data?.session_token) {
      // Rotation keeps the session identity and replaces only the secret.
      writeSession(
        res.data.session_token,
        res.data.session_id || activeSession?.sessionId,
      );
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
    const sid = await resolveActiveSession(sessionId);
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
  // include_persona tells the backend which active dataset owns the metrics.
  analyzeDocument: async (sanitizedText, sessionId = null, includePersona = false) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/documents/analyze/', {
      sanitized_text: sanitizedText,
      session_id: sid,
      include_persona: includePersona,
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
    let sid = await resolveActiveSession(sessionId);
    try {
      const res = await apiClient.post('/privacy/consent/', {
        session_id: sid,
        consent_version: version,
        anonymized_processing_accepted: true,
        no_credential_disclosure_acknowledged: true,
      });
      return res.data;
    } catch (err) {
      if (err.response?.status === 401) {
        // Recover from expired session: init fresh session and retry once
        const fresh = await api.initSession();
        sid = fresh.session_id;
        const retryRes = await apiClient.post('/privacy/consent/', {
          session_id: sid,
          consent_version: version,
          anonymized_processing_accepted: true,
          no_credential_disclosure_acknowledged: true,
        });
        return retryRes.data;
      }
      throw err;
    }
  },

  // Withdraw active consent
  withdrawConsent: async (sessionId = null) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/privacy/consent/withdraw/', {
      session_id: sid,
    });
    return res.data;
  },

  // Parse bank statement (CSV, PDF, TXT) with optional persistence
  parseStatement: async ({ rawText = '', file = null, format = 'csv', sessionId = null, persist = false }) => {
    const sid = await resolveActiveSession(sessionId);
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
    const sid = await resolveActiveSession(sessionId);
    const payload = { session_id: sid, persist };
    if (smsText) payload.sms_text = smsText;
    if (smsList) payload.sms_list = smsList;
    const res = await apiClient.post('/data/parse-sms/', payload);
    return res.data;
  },

  // Phase 2 Financial Intelligence: 1. Categorization
  getCategorization: async (sessionId = null, includePersona = false) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/insights/categorize/', {
      session_id: sid,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Phase 2 Financial Intelligence: 2. Monthly Budget Analyzer
  getMonthlyBudget: async (sessionId = null, year = 2026, month = 10, includePersona = false) => {
    const sid = await resolveActiveSession(sessionId);
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
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/insights/subscriptions/', {
      session_id: sid,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Phase 2 Financial Intelligence: 4. Unusual Spending Detector
  getUnusualSpending: async (sessionId = null, includePersona = false) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/insights/unusual-spending/', {
      session_id: sid,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Phase 2 Financial Intelligence: 5. Spending Pattern Analyzer
  getSpendingPatterns: async (sessionId = null, months = 6, includePersona = false) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/insights/spending-patterns/', {
      session_id: sid,
      months,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Task 17: Imported-statement snapshot/overview (live imports only; persona data excluded)
  getImportedOverview: async (sessionId = null) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/insights/imported-overview/', {
      session_id: sid,
    });
    return res.data;
  },

  // Evidence-Based Financial Insights Briefing
  getEvidenceBriefing: async (sessionId = null, includePersona = false) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/insights/evidence-briefing/', {
      session_id: sid,
      include_persona: includePersona,
    });
    return res.data;
  },

  // Commitment Stress Test & Judgment Flip
  runCommitmentStressTest: async (params = {}, sessionId = null) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/analytics/commitment-stress-test/', {
      session_id: sid,
      ...params,
    });
    return res.data;
  },

  // Explain Commitment Stress Test with verified AI
  explainCommitmentStressTest: async (decisionPacket, sessionId = null) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/analytics/commitment-stress-test/explain/', {
      session_id: sid,
      decision_packet: decisionPacket,
    });
    return res.data;
  },

  // Human Correction of Uncertain Transactions
  correctTransaction: async (transactionId, correctionParams = {}, sessionId = null) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/insights/correct-transaction/', {
      session_id: sid,
      transaction_id: transactionId,
      ...correctionParams,
    });
    return res.data;
  },

  // Nuke all session data (Cascading purge for authenticated session)
  nukeData: async (sessionId = null) => {
    const sid = await resolveActiveSession(sessionId);
    const res = await apiClient.post('/privacy/nuke-data/', {
      session_id: sid,
    });
    return res.data;
  },
};

export default api;
