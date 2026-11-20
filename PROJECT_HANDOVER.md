# ArthaShield (FinGuard AI) — Archived Project Handover Snapshot

**Handover Timestamp:** 2026-11-10T12:00:00+05:30  
**Project Path:** `C:\Users\francis\.gemini\antigravity\scratch\arthashield`  
**Current Test Status:** `690 backend tests passing in the latest GitHub Actions run on 2026-11-20` (Django Test Runner) | `Vite Build: CLEAN (1.26s)`  
**Target Event:** Arthaton 2026 Hackathon  
**Current reference:** [README.md](README.md)  
**Current implementation note (2026-11-20):** This file is retained as project history, not as the authoritative product/security specification. It contains earlier build notes that have since changed. Use the root README and current CI results for the current architecture, model, privacy boundaries, and test status.  

---

## 1. Project Overview and Objectives

ArthaShield is a privacy-first financial intelligence companion designed for everyday citizens facing financial information asymmetry, hidden fee leakage, and predatory debt mechanics. The backend processes uploaded statements; this is not a zero-knowledge or client-only processing system.

### Primary Objectives:
1. **Eliminate Silent Cashflow Drains:** Detect recurring subscriptions, dormant micro-debits, bill creep, and unlinked auto-debits without requiring bank credentials or SMS scraping.
2. **Deterministic-Math Integrity:** Compute emergency runway, debt-to-income (DTI), safe-to-spend allowances, and effective APR strictly in deterministic Python. Zero hallucinated numbers.
3. **Server-Side PII Boundary:** Tokenize recognizable account numbers, personal names, phone numbers, UPI identifiers, PAN, and Aadhaar before provider-bound AI payloads. Detection is defense in depth, not a guarantee that every free-text name is found.
4. **Transparent Decision Simulators:** Demystify disguised 0% "No-Cost" EMI schemes, revealing hidden processing fees, GST on interest subvention, and true annual percentage rates.
5. **Consent and Deletion Controls:** Session-scoped storage, consent auditing, and a single-click hard purge for records held by the application. This is not a claim of certified DPDP or GDPR compliance.

---

## 2. Technology Stack and Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Browser Client: React 19 + TailwindCSS                │
│       Vite 8.3 | Lucide Icons | CRT & Corner Brackets Visual Theme     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTPS + Bearer Session Token
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Backend: Django 6.0 + Django REST Framework              │
├───────────────────────────────┬────────────────────────────────────────┤
│ Sanitizer Engine              │ Deterministic Analytics Engine         │
│ (Regex + Tokenizer)           │ (Decimal math, ROUND_HALF_UP)          │
├───────────────────────────────┼────────────────────────────────────────┤
│ Financial Insights Engine     │ Session & Consent Security Layer       │
│ (Refund, Recurrence, Budget)  │ (HTTP-Only tokens, SHA-256 consent)    │
├───────────────────────────────┴────────────────────────────────────────┤
│ Database: SQLite (Dev) / Managed PostgreSQL (Prod)                     │
│ Ephemeral transaction records, deterministic deduplication fingerprints│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Scrubbed Tokens Only (No PII)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│            Optional Advisor Layer: Google Gemini 3.8 Flash                 │
│      Strict offline rule-based fallback when API key is unavailable    │
└────────────────────────────────────────────────────────────────────────┘
```

- **Backend:** Python 3.12, Django 6.0, Django REST Framework, and `pdfplumber`.
- **Frontend:** React 19, Vite 8, Tailwind CSS, and Lucide React.
- **Data Stores:** SQLite (`backend/db.sqlite3`) for local development; PostgreSQL-ready via `DATABASE_URL` (`backend/core/settings.py`).
- **AI/LLM Provider:** Optional Google Gemini Developer API (`gemini-3.8-flash`) over HTTPS, with deterministic rule-based fallback.

---

## 3. Complete Implemented Feature Inventory

| Feature | Description | Status |
|---|---|---|
| **Session Initiation & Token Auth** | Cryptographic bearer tokens, SHA-256 session identification, zero credential persistence. | `VERIFIED` |
| **Interactive Consent Modal** | Consent capture, audit logging, revocation and server-side status checks; not a legal compliance certification. | `VERIFIED` |
| **Document PII Sanitizer** | Server-side preview and provider-boundary redaction for recognizable PAN, Aadhaar, account and contact patterns; free-text name detection remains heuristic. | `VERIFIED` |
| **Statement Parser (PDF/CSV/TXT)** | Multi-format bank statement parsing, transaction normalization, and fingerprint deduplication. | `VERIFIED` |
| **Safe-to-Spend & Health Score** | Deterministic liquidity runway, debt service ratio, and uncommitted discretionary cash. | `VERIFIED` |
| **"No-Cost" EMI Simulator** | Unmasks hidden processing fees, GST on subvention, the effective annual borrowing cost from dated cash flows (XIRR), and runway impact. | `VERIFIED` |
| **1-Click Hard Purge (Data Shredder)** | Cascading deletion of transactions, audit logs, and snapshots for the session. | `VERIFIED` |
| **Transaction Categorization** | Deterministic keyword-based merchant classification into 8 primary categories. | `VERIFIED` |
| **Evidence-Aware Credit Classification** | Separates earned income, investment yield, capital liquidation, transfers, and refunds. | `VERIFIED` |
| **Orthogonal Refund Allocation Engine** | Confidence-labelled matching (`CONFIRMED`, `PROBABLE`, `WEAK`), cross-month tracking, net expense adjustment. | `VERIFIED` |
| **Evidence-Based Recurring Detector** | Multi-cadence debit cadence engine (`CONFIRMED`, `PROBABLE`, `WEAK`), payment type tagging. | `VERIFIED` |
| **Leakage Radar UI** | Visual dashboard for recurring auto-debits, prune protocols, and runway recovery metrics. | `VERIFIED` |
| **Financial Intelligence UI** | Five-tab intelligence dashboard: Categorization, Budget, Recurrence, Outliers, Trends. | `VERIFIED` |
| **Synthetic Personas (x3)** | Rohit Verma (Freelancer), Priya Sharma (Corporate), Aman Joshi (Student). | `VERIFIED` |

---

## 4. Backend Modules, Endpoints, and Important Files

### Core Structure:
- [`backend/core/settings.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/core/settings.py): Application configuration, CORS, DRF, security headers.
- [`backend/core/urls.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/core/urls.py): Root URL dispatcher routing `/api/v1/` to `api.urls`.

### API Application (`backend/api/`):
- [`models.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/models.py): `SecureSession`, `ConsentAuditLog`, `FinancialSnapshot`, `Transaction`, `DecisionScenario`. `DecisionScenario.true_effective_apr` is **nullable** and its meaning is qualified by `DecisionScenario.apr_status` (`OK` / `NOT_APPLICABLE` / `UNAVAILABLE` / `LEGACY_SUPERSEDED` / `LEGACY_AMBIGUOUS_ZERO`): a NULL APR never means "a 0% loan", and a stored `0.0` always means a genuine zero-cost result (migration `api.0004_decisionscenario_apr_status`).
- [`views.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/views.py): REST API endpoints with session authentication and consent validation.
- [`response_safety.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/response_safety.py): Task 19 ingestion **response boundary**. Converts parsed statements, SMS bodies, parser warnings and account metadata into a form that is safe to serialize: safe counterparty labels instead of raw narration, no transaction references, no account digits, masked personal names / credentials in free text, and content-free parser errors. Stored data is never modified by it.
- [`urls.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/urls.py): 17 operational API endpoints.
- [`insights.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/insights.py): Credit classifier, refund allocation engine, recurring payment detector, anomaly detector, spending pattern analyzer.
- [`security.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/security.py): Bearer token hashing, session verification, credential rejection guards. `extract_explicit_session_token` (header/Authorization only, no cookie) is used by the session bootstrap so that resuming a session always requires the client to name it.

### Data Processing & Sanitization:
- [`backend/sanitizer/services.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/sanitizer/services.py): Regex patterns for PAN, Aadhaar, account numbers, cards, phone numbers.
- [`backend/api/tests/privacy_scan.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/tests/privacy_scan.py): Shared response leak scanner for the Task 15 / Task 17 privacy suites. It runs the **production** `SanitizerService.PATTERNS` verbatim plus narrative/marker shapes, and skips opaque UUID identifiers (a random UUID can contain a 10-digit run that mimics a phone number, ~0.33% of UUIDs).
- [`backend/data_processor/statement_parser.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/data_processor/statement_parser.py): PDFPlumber and regex-based bank statement parsing.
- [`backend/data_processor/normalizer.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/data_processor/normalizer.py): Standard transaction shape normalization.
- [`backend/data_processor/transfers.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/data_processor/transfers.py): Task 21 deterministic own-account transfer recognition (evidence-based, no LLM).

### Analytics & Advisor:
- [`backend/analytics/services.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/analytics/services.py): `AnalyticsEngine` (Safe-to-Spend, runway, savings rate, health score) and the EMI engine with the `calculate_xirr` dated-rate solver behind the effective annual borrowing cost.
- [`backend/advisor/services.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/advisor/services.py): `AdvisorService` (Gemini API bridge + offline rule-based fallback).

### Complete Endpoint Registry:
| Method | Endpoint | Description | Auth/Consent |
|---|---|---|---|
| `POST` | `/api/v1/auth/session/init/` | Issues secure session token | Open |
| `POST` | `/api/v1/auth/session/rotate/` | Rotates bearer token | Bearer Token |
| `GET` | `/api/v1/auth/session/me/` | Session verification status | Bearer Token |
| `GET` | `/api/v1/personas/` | List 3 synthetic personas | Open |
| `POST` | `/api/v1/personas/select/` | Loads persona transactions into session | Bearer Token |
| `POST` | `/api/v1/privacy/consent/` | Record/audit consent | Bearer Token |
| `POST` | `/api/v1/privacy/consent/withdraw/` | Revoke consent | Bearer Token |
| `POST` | `/api/v1/privacy/sanitize-preview/` | Preview PII redaction | Bearer Token |
| `POST` | `/api/v1/privacy/nuke-data/` | 1-Click hard purge of session data | Bearer Token |
| `POST` | `/api/v1/documents/analyze/` | AI / offline document analysis | Bearer + Consent |
| `POST` | `/api/v1/data/parse-statement/` | Upload & parse PDF/CSV/TXT statement | Bearer + Consent |
| `POST` | `/api/v1/data/parse-sms/` | Parse transactional SMS dump | Bearer + Consent |
| `POST` | `/api/v1/analytics/simulate-emi/` | Evaluate "No-Cost" EMI effective annual cost (XIRR) | Bearer Token |
| `POST` | `/api/v1/insights/categorize/` | Keyword categorization of debits | Bearer + Consent |
| `POST` | `/api/v1/insights/monthly-budget/` | Credit classification & refund allocation | Bearer + Consent |
| `POST` | `/api/v1/insights/subscriptions/` | Evidence-based recurring debit detection | Bearer + Consent |
| `POST` | `/api/v1/insights/unusual-spending/` | Anomaly spending detector (3x median) | Bearer + Consent |
| `POST` | `/api/v1/insights/spending-patterns/`| Multi-month trend analyzer | Bearer + Consent |

---

## 5. Frontend Components and Navigation

### Main Shell:
- [`frontend/src/App.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/App.jsx): Top-level orchestrator. Manages `sessionId`, active persona, consent modal, and active tab switching.
- [`frontend/src/services/api.js`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/services/api.js): The single owner of the active session (Task 20). The token and the session id are stored as a pair, session creation is single-flight, a valid credential resumes the same session, every request carries the active session id, and an invalidated session is recovered without a page reload.
- [`frontend/src/components/Navbar.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/components/Navbar.jsx): Session identity badge, consent indicator, hard purge trigger, and persona selector.
- [`frontend/src/components/Sidebar.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/components/Sidebar.jsx): Collapsible dark terminal navigation bar.
- [`frontend/src/components/ConsentModal.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/components/ConsentModal.jsx): Two-checkbox consent gate.

### View Components (Tabs):
1. `OVERVIEW`:
   - [`HealthScorecard.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/components/HealthScorecard.jsx): Displays Safe-to-Spend daily allowance, Emergency Runway (months), Fixed Cost Ratio, and Health Score.
   - [`TransactionTable.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/components/TransactionTable.jsx): Filterable, searchable data grid of parsed transactions.
2. `INTELLIGENCE`:
   - [`FinancialIntelligence.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/components/FinancialIntelligence.jsx): Section 1 (Categorization), Section 2 (Subscription Traps), Section 3 (Unusual Spending), Section 4 (Category Trends), Section 5 (Cash Movement & Operating Surplus).
3. `PRIVACY_INSPECTOR`:
   - [`PrivacyInspector.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/components/PrivacyInspector.jsx): Interactive live PII redaction comparison. Statement upload trigger.
4. `LEAKAGE_RADAR`:
   - [`LeakageRadar.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/components/LeakageRadar.jsx): Recurring drain scanner, monthly commitment totals, prune protocol suggestions, and evidence journal.
5. `EMI_SIMULATOR`:
   - [`EmiSimulator.jsx`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/frontend/src/components/EmiSimulator.jsx): Interactive loan/EMI reality check simulator.
6. `AUDIT_LEDGER`:
   - Inline audit log inspector, DPDP verification, cryptographic session log viewer.

---

## 6. Financial Calculation Definitions and Rules

All financial calculations are defined in [`backend/api/insights.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/insights.py) and [`backend/analytics/services.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/analytics/services.py) using `Decimal` with `ROUND_HALF_UP`:

1. **Credit Categorization**:
   - `earned_income`: Salary, professional compensation, business invoices.
   - `investment_yield`: FD interest, dividends, bond coupon credits.
   - `operating_income` = `earned_income + investment_yield`.
   - `capital_liquidation`: MF redemptions, stock sale proceeds. Liquidation of existing wealth; **strictly excluded from income metrics**.
   - `investment_transfers`: Broker wallet sweeps (Zerodha, Groww). Excluded from income.
   - `refunds`: Reversals and merchant refunds. Excluded from income.
   - `transfers`: Internal own-account movements. Excluded from income.
   - `reimbursements`: Medical and corporate expense claims. Excluded from income.
2. **Debits and Living Expenses**:
   - `gross_debits`: Total sum of all debit records.
   - `debit_transfers`: Identified own-account outgoing transfers (`classify_debit(merchant)['is_transfer']`).
   - `gross_living_expenses` = `gross_debits - debit_transfers`.
   - `net_living_expenses` = $\max(0, \text{gross\_living\_expenses} - \text{confirmed\_same\_period\_applied\_refunds})$.
3. **Surplus and Cash Movement**:
   - `operating_surplus` = $\text{operating\_income} - \text{net\_living\_expenses}$. (Economic sustainability indicator).
   - `total_account_cash_movement` = $\text{total\_credits} - \text{gross\_debits}$. (Statement period bank balance movement).
   - *Audit Rule:* The two metrics are displayed separately with mandatory single-account limitation notices.

### 3.1 Own-Account Transfer Recognition (Task 21, hardened in Task 22)

Implemented in [`backend/data_processor/transfers.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/data_processor/transfers.py) and used by `classify_debit` / `classify_credit`.

- A narration is a **confirmed own-account transfer** only when it carries an own-account marker (`SELF`, `SELF AC`, `OWN ACCOUNT`, ...) **together with** transfer evidence (`TRANSFER`, `TFR`, `FUND TRANSFER`, `SWEEP ...`), either as an explicit phrase ("transfer to self") or as two adjacent narration segments ("UPI/SELF/TRANSFER").
- The bare word "transfer" is never sufficient, and **a bare own-account marker is never sufficient either** ("SELF" alone stays uncertain).
- A further segment that is neither evidence nor structural (a beneficiary name, for example) makes the reading **uncertain**: the transaction keeps its conservative treatment (an ordinary outflow) instead of being silently removed from the expenses.
- Contradicting evidence (a counterparty VPA, a transfer fee, a loan/EMI/reimbursement/refund/salary marker) also downgrades the result to `uncertain`: the transaction keeps its conservative classification and is explicitly flagged, rather than presented as a certain internal movement.
- The normalizer preserves the evidence: `UPI/SELF/TRANSFER` becomes the stored label `Self Transfer` (and `UPI/SELF AC/TRANSFER` becomes `Self Ac Transfer`), and the response boundary renders it as the fixed, content-free label `Internal Transfer`.
- Financial effect: the debit is excluded from living expenses, the credit is excluded from earned income, the row stays in the ledger with its original amount, and the movement is never counted as recoverable leakage. No LLM is involved.
- *Backward compatibility (Task 22):* the import fingerprint carries the sanitized merchant, so a statement imported by an older build (which stored `Self`) would not match the current build (`Self Transfer`). The import therefore compares own-account transfers through their **transfer identity** - the own-account marker the narration carried - so `Self` and `Self Transfer` resolve to the same identity (`SELF`), `Self Ac` / `Self Ac Transfer` to `SELF_AC`, and `Own Account` / `Own Account Transfer` to `OWN_ACCOUNT`. The compatibility path only applies to a confirmed own-account transfer and to stored rows with the same session, date, amount and direction; merchant identity is never globally ignored, and different own-account movements keep different identities.
- *Documented limitation:* personal-name detection is heuristic. A name that is not attached to an explicit person context can survive inside free text; structured fields do not rely on it.



---

### 3.2 Recurring Pattern vs. Financial Commitment (Task 23)

A repeated transaction is not automatically a subscription or a financial commitment. `detect_subscriptions` now reports two independent dimensions:

| Field | Meaning |
|---|---|
| `recurrence_confidence` | Strength of the *pattern* (cadence + occurrence count): `CONFIRMED` / `PROBABLE` / `WEAK`. |
| `commitment_class` | What the repetition means financially: `subscription_commitment`, `fixed_obligation`, `recurring_discretionary`, `recurring_pattern`. |
| `confidence` | The **commitment** confidence: a recurrence without commitment evidence is never `CONFIRMED`. |
| `is_financial_commitment` | A confirmed subscription commitment or fixed obligation. Only these reserve money for an upcoming bill. |
| `is_potential_leakage` | A confirmed subscription commitment - the only class that can represent a *potentially avoidable* recurring charge. |
| `observed_amount_min` / `_max` / `_range` | The observed charge range, so a variable subscription is never shown as one fixed amount. |

Rules:
- A confirmed commitment requires a consistent cadence with at least three occurrences **and** commitment evidence: a known subscription/billing service, a rent/EMI/insurance/utility obligation, or an explicit subscription narration.
- Three matching monthly purchases at an ordinary merchant (a cafe, a supermarket, a pharmacy) are recognised as a recurring *pattern* and reported as `recurring_discretionary` - never as a confirmed commitment and never as recoverable savings.
- An unknown merchant that merely repeats is `recurring_pattern` and never becomes a commitment.
- Rent, loan instalments, insurance and utilities are `fixed_obligation`: a commitment, but not a subscription and not avoidable money.
- A subscription is never described as wasted money - usage is not observable from a statement, so the recommendation is a review, not an established saving.
- The `confirmed_commitments` total (which reserves money for Safe-to-Spend) is built only from confirmed commitments; `monthly_leakage` only from confirmed subscription commitments.
- Merchant keyword classification matches short keywords on word boundaries, so "Premium" is not read as an EMI ("emi") and "Application" is not read as an insurer ("lic").

## 7. Refund Matching Architecture and Confidence Levels

Implemented in [`backend/api/insights.py:350-758`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/insights.py#L350-L758). Operates on three orthogonal dimensions:

```
Refund Matching Dimensions:
├── 1. Match Confidence:  [CONFIRMED | PROBABLE | WEAK | UNMATCHED]
├── 2. Allocation Status: [APPLIED | SUGGESTED_NOT_APPLIED | NOT_ALLOCATED]
└── 3. Temporal Relation: [SAME_PERIOD | CROSS_MONTH | None]
```

### Matching Rules:
- **`CONFIRMED`**: Requires a reliable shared reference ID (e.g., `ORD-12345`, `REF-999`), chronologically valid date (refund on or after purchase), within 180-day lookback, and amount $\le$ original purchase amount.
  - Same-period confirmed: `allocation_status = APPLIED`. Automatically reduces net living expenses.
  - Cross-month confirmed: `allocation_status = APPLIED`. Attributed to original debit without rewriting past statements or reducing unrelated current expenses.
- **`PROBABLE`**: Normalized merchant token match, compatible amount, chronological validity, and unique candidate purchase.
  - `allocation_status = SUGGESTED_NOT_APPLIED`.
  - `allocated_amount = 0.00`. Suggested amount displayed in UI as a suggested attribution; **never silently deducted from net living expenses**.
- **`WEAK` / `UNMATCHED`**: Ambiguous token matches or no matching debit. `allocation_status = NOT_ALLOCATED`.

---

## 8. Recurring-Payment Detection Architecture

Implemented in [`backend/api/insights.py:1136-1576`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/insights.py#L1136-L1576).

### Mechanics:
1. **Scope:** Analyzes the complete session's historical debits (`transaction_type='DEBIT'`). Excludes credits, refunds, internal transfers, and recognized peer UPI transactions via VPA and commercial term analysis (`is_peer_upi`).
2. **Merchant Identity & Sub-Service Clustering:**
   - Uses `get_recurring_merchant_key` to strictly isolate sub-brands (e.g. `amazon_prime` vs `amazon_shopping`, `airtel_broadband` vs `airtel_recharge`, `jio_fiber` vs `jio_recharge`, `swiggy_instamart` vs `swiggy_dineout`).
   - Strips dynamic terminal, POS, branch, and reference noise while retaining core counterparty identity.
   - Counterparty privacy scrubbing redacts phone numbers, VPAs, and bank account numbers from UI titles and evidence strings (`_sanitize_counterparty_name`).
3. **Deduplication vs Preservation:**
   - Preserves legitimate same-day identical debits when unique reference IDs or fingerprints are present.
   - Collapses genuine duplicate re-imports (`_is_duplicate_import`).
4. **Cadence Intervals & Delay Tolerance:**
   - `weekly`: 5–9 days median interval.
   - `fortnightly`: 12–17 days median interval.
   - `monthly`: 25–38 days median interval (robustly tolerates real-world processing/holiday delays up to 38 days without dropping confidence).
   - `quarterly`: 75–105 days median interval.
   - `annual`: 330–400 days median interval.
   - `irregular`: Non-matching or erratic intervals.
5. **Confidence Levels:**
   - `CONFIRMED`: $\ge 3$ consistent occurrences with matching cadence.
   - `PROBABLE`: Exactly 2 occurrences with matching cadence, or legacy statement flag.
   - `WEAK`: $\ge 3$ occurrences with irregular cadence intervals.
   - `NOT_RECURRING`: $< 2$ occurrences or 2 non-matching arbitrary debits (discarded).
6. **Classifications:** `subscription`, `rent`, `emi_or_loan`, `insurance`, `utility`, `other_recurring_payment`, `unknown_recurring_payment`.
7. **Cost Projection & Cost Withholding:**
   - Irregular cadence debits withhold projected monthly/annual costs (`estimated_monthly_cost = None`, `estimated_annual_cost = None`), reporting historical `observed_total_spend` and `observed_period_average` to prevent financial distortion.
   - Calendar-aware next payment projection (`_project_calendar_next_date`) handles variable month lengths and leap years (e.g. Jan 31 in leap year -> Feb 29; in non-leap year -> Feb 28). Historical statements evaluate against deterministic `as_of_date`, labeling past projections as `OVERDUE` or `STALE_HISTORY`.
8. **Segregated Commitment Metrics:**
   - `confirmed_monthly_commitment` includes only `CONFIRMED` outflows.
   - `probable_monthly_commitment` reported separately for user review.
   - `discretionary_leakage_monthly` isolated from `essential_commitments_monthly` (Rent, EMI, Utilities, Insurance). Essential commitments are preserved and explicitly excluded from cancellation runway extension claims.

---

## 9. Privacy, Consent, Session Security, and Sanitisation

1. **Session-Bound Identity:** Every user session receives an ephemeral UUIDv4 session identifier and cryptographic bearer token (`HTTP_X_SESSION_TOKEN`).
2. **Explicit Consent Gate:** Financial intelligence and parsing endpoints strictly reject unconsented requests with HTTP 403 `CONSENT_REQUIRED`. Revocation endpoint (`/privacy/consent/withdraw/`) terminates access immediately.
3. **Regex PII Stripping:** [`backend/sanitizer/services.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/sanitizer/services.py) strips:
   - Indian mobile numbers (`+91`, `9xxxxxxxxx`).
   - PAN card patterns (`[A-Z]{5}[0-9]{4}[A-Z]`).
   - Aadhaar numbers (`\d{4}\s\d{4}\s\d{4}`).
   - Bank account numbers and credit/debit card numbers.
   - High-entropy reference tokens replaced by deterministic placeholders (`[USER_PRIMARY]`, `[REDACTED_ACCOUNT]`).
4. **Data Shredder:** [`backend/api/views.py:NukeDataView`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/views.py#L421) executes atomic cascading deletion of all transactions, snapshots, decision scenarios, and consent audit logs for the session.

---

## 10. Gemini Integration Status and Offline Fallback

Implemented in [`backend/advisor/services.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/advisor/services.py).

- **Mode A: Live Gemini API (`LIVE_GEMINI`)**:
  - Activated when `GEMINI_API_KEY` is present in the environment.
  - Model: `gemini-2.0-flash`.
  - Sent payload: **Sanitized financial summary metrics and anonymized text ONLY**. Zero PII or bank credentials.
- **Mode B: Offline Deterministic Fallback (`OFFLINE_RULE_BASED`)**:
  - Automatically activated if `GEMINI_API_KEY` is empty, unset, invalid, or encounters rate limits / network timeouts.
  - Synthesizes findings using local deterministic rule engines (discretionary buffer thresholds, emergency runway assessment, fee leak identification).
  - UI displays engine label: *"Offline Rule-Based Financial Insights"* with zero privacy compromise.

---

## 11. Existing Test Commands and Latest Verified Results

### Backend Automated Test Suite:
Run from project root:
```powershell
python backend/manage.py test api advisor analytics sanitizer
```
**Latest Test Execution Result (2026-11-10):**
```
Ran 440 tests
OK (failures=0, errors=0)
```

Test Breakdown (verified per package):
- `api` tests: 395 tests, including the 24 Task 09 reliability regressions, the 15 Task 11 privacy-boundary regressions, the 8 Task 12 merchant-identity/data-minimisation regressions, the 7 Task 14 categorization-privacy regressions, the 8 Task 15 unusual-spending privacy regressions, the 9 Task 17 imported-session overview regressions, the 9 Task 18.1 privacy-scanner positive controls, the 23 Task 19 ingestion-privacy regressions, the 15 Task 20 session-lifecycle regressions, the 21 Task 21 own-account transfer regressions, the 22 Task 22 transfer edge-case and legacy-deduplication regressions, and the 26 Task 23 recurring-intelligence regressions.
- `advisor` tests: 4 tests (Gemini integration, offline rule-based fallback).
- `analytics` tests: 41 tests (Safe-to-Spend, EMI calculations, runway metrics) including the 34 Task 18 effective-annual-cost (XIRR) and APR-persistence regressions.
- `sanitizer` tests: 0 tests discovered (sanitizer coverage lives in the `api` security-hardening suites).

**Automated vs manual verification:** the backend suite exercises API responses, label helpers,
refund attribution and subscription serialization. Frontend display behaviour is covered by a
Node execution matrix against `frontend/src/utils/display.js` and by inspection; there is no
automated frontend test runner, so rendered badges, responsive layout and toast behaviour are
checked manually in the browser and are not unit-test verified.

### Frontend Production Build:
Run from project root:
```powershell
npm --prefix frontend run build
```
**Latest Build Result (2026-11-10):**
```
vite v8.3.5 building client environment for production...
✓ 2127 modules transformed.
dist/index.html                   0.45 kB │ gzip:   0.29 kB
dist/assets/index-50PEcSFR.css   55.80 kB │ gzip:   9.94 kB
dist/assets/index-xJgHqFNC.js   431.81 kB │ gzip: 126.22 kB
✓ built in 703ms
```

---

## 12. Known Bugs, Risks, and Unfinished Features

### 1. Adversarial Audit Items — Resolution Status
- **Same-Day Legitimate Multi-Subscription Collapse (`RESOLVED`)**: Dedup now preserves distinct transactions on the same date with different references or non-colliding fingerprints (`_is_duplicate_import`).
- **P2P UPI False Positives Without Phone Numbers (`RESOLVED`)**: Regex handles personal VPAs with names while distinguishing commercial keywords (`is_peer_upi`).
- **Rigid Cadence Invalidation on Single Delay (`RESOLVED`)**: Bounded delays (e.g. 37-day interval) are tolerated using tolerance threshold logic (`_detect_cadence_and_intervals`).
- **Irregular Cadence Cost Inflation (`RESOLVED`)**: Projected annual costs are withheld (`None`) for irregular cadences, reporting observed totals instead.
- **LeakageRadar Aggregation of Weak Detections (`RESOLVED`)**: Only `CONFIRMED` included in confirmed totals; `PROBABLE` and `WEAK` displayed in separated tiers; discretionary leakage isolated from essential fixed commitments (Rent, EMI, Utilities, Insurance).
- **Live Subscriptions Preempt Persona Demonstration Cards (`RESOLVED`)**: Dual-mode toggle pill buttons (`Live Statement` vs `Demo Persona`) allow instant switching.

### 2. Remaining Architectural Considerations
- **Multi-Currency Normalization**: Engine assumes INR currency amounts. Multi-currency statements require exchange rate conversion before running cadence checks.
- **Bi-Monthly or Semi-Annual Cadence**: Currently weekly, fortnightly, monthly, quarterly, and annual are standard. Bimonthly (every 2 months) defaults to irregular or quarterly buckets.
- **Ingestion Display Boundary Is Heuristic For Names (Task 19)**: Structured ingestion fields (merchant, description) always resolve to a safe counterparty label, so no personal name can reach a response there. Inside echoed free text (SMS body, sanitization preview) a name is masked only when it follows an explicit person context ("paid to", "from", "dear", "UPI/...", "POS/...") and is written in title case. A name in an unusual position or in another writing style can survive in that free text. No claim is made that every possible personal name is removed from arbitrary free text.
- **Dev-Mode Session Race On A Fresh Browser Profile (`RESOLVED` in Task 20)**: React StrictMode double-invokes the mount effect, so a brand-new browser profile used to create several sessions in the same second; the app could then hold an older session id than the token, and the statement import (which posts `session_id`) was rejected with `403 SESSION_MISMATCH`. The API client now owns a single active session: the token and the session id are stored as a pair, session creation is single-flight, the bootstrap resumes a valid session instead of forking it, and an invalidated session is recovered without a reload. The backend substitution guard is unchanged.

---

## 13. Current Development Priorities

### Adversarial-Review Corrections — Reconciled Status (Task 09)
All ten corrections are implemented and covered by automated tests; none remain pending.

| # | Correction | Status | Verification |
|---|---|---|---|
| 1 | Transaction narration privacy | `IMPLEMENTED` + `VERIFIED` | `_sanitize_counterparty_name` / `_display_counterparty`; display tests in `test_task09_reliability.py` |
| 2 | Same-day deduplication | `IMPLEMENTED` + `VERIFIED` | `_is_duplicate_import` requires a reference or fingerprint; 5 synthetic dedup tests plus documented limitation |
| 3 | Merchant identity handling | `IMPLEMENTED` + `VERIFIED` | `get_recurring_merchant_key` sub-brand isolation (`amazon_prime` vs `amazon_shopping`) |
| 4 | P2P UPI filtering | `IMPLEMENTED` + `VERIFIED` | `classify_upi_counterparty` three-way verdict; 6 conservative-UPI tests |
| 5 | Cadence tolerance | `IMPLEMENTED` + `VERIFIED` | `_detect_cadence_and_intervals` tolerates bounded 37-42 day monthly delays |
| 6 | Irregular cost estimation | `IMPLEMENTED` (projection withheld) | Projected monthly/annual cost is `None` for irregular cadence; observed totals reported instead of annualizing |
| 7 | Calendar-aware next-date projections | `IMPLEMENTED` + `VERIFIED` | `_project_calendar_next_date` with `OVERDUE` / `STALE_HISTORY` labelling |
| 8 | Confidence separation in UI | `IMPLEMENTED` + `VERIFIED` | LeakageRadar keeps `CONFIRMED`, `PROBABLE` and `WEAK` in separate tiers |
| 9 | Stale session state reset | `IMPLEMENTED` | FinancialIntelligence request-sequence guard + App consent-epoch reset |
| 10 | Persona demo vs live separation | `IMPLEMENTED` + `VERIFIED` | Live Statement / Demo Persona mode toggle |

### Remaining Manual Browser Verification (PENDING)
Automated suites and the production build pass, but these runtime behaviours still require a manual pass:
1. Withdraw consent with the Intelligence tab open: confirm the consent gate returns, no persona/health/intelligence data remains on screen, and re-consent re-hydrates cleanly.
2. Rapid persona or persona-toggle switches plus repeated "Sync Intelligence": confirm only the newest response renders and the loading state always resolves.
3. Import a CSV containing two identical reference-less payments (expect 2 imported), then re-import it (expect 0 imported, 2 skipped duplicates).
4. Recurring series narrated with a personal VPA: confirm Leakage Radar and Intelligence titles show a clean merchant name with no `@`, digits or `[REDACTED_*]`.
5. Ambiguous payee (e.g. `UPI/rahulkumar@paytm`, three monthly debits): confirm `WEAK` / unknown classification with projected costs withheld.
6. Category journal, outlier panel and transaction ledger with a VPA-only merchant: confirm the displayed name is "Unidentified Counterparty" rather than `[REDACTED_UPI_ID]`.

---

## 14. Arthaton 2026 Submission Requirements

- **Track:** Privacy-First AI & Financial Engineering.
- **Key Demo Moments:**
  1. Split-screen Privacy Inspector showing instant PII redaction of raw bank statement.
  2. One-click Data Shredder demonstrating complete DPDP-compliant session deletion.
  3. "No-Cost" EMI Reality Check Simulator exposing the effective annual borrowing cost (XIRR over dated cash flows) and GST on subvention.
  4. Evidence-based recurring payment scanner identifying hidden auto-debit leaks without requiring net-banking passwords.
- **Constraints:**
  - Zero external egress of unredacted credentials or personal identity numbers.
  - No synthetic data fabrication during real statement analysis.
  - Complete deterministic fallback operational when offline.

---

## 15. Instructions for Future AI Coding Agents

1. **Preserve Determinism:** Never replace deterministic calculations in [`insights.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/api/insights.py) or [`services.py`](file:///C:/Users/francis/.gemini/antigravity/scratch/arthashield/backend/analytics/services.py) with speculative LLM completions.
2. **Never Bypass Consent:** All financial analysis endpoints must check `_get_active_consent(session_id)`.
3. **Execution Conventions:**
   - Windows PowerShell environment: Use `;` instead of `&&` for command chaining.
   - Run backend tests from root with: `python backend/manage.py test api advisor analytics sanitizer`.
   - Run frontend build with: `npm --prefix frontend run build`.
4. **Verification Requirement:** Always execute the complete 280-test suite and frontend build before completing any task.
5. **Preserve Status Integrity:** Distinguish `IMPLEMENTED`, `VERIFIED`, `REPORTED`, `PENDING`, and `UNKNOWN`. Never mark pending adversarial review corrections as implemented until code changes and unit tests are complete.

