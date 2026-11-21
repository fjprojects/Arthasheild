# ArthaShield (FinGuard AI)
### Privacy-first financial companion for Arthaton 2026

## Demo

[Watch the ArthaShield demo on YouTube](https://youtu.be/oXG0cLqUp08)

## Live Application

[Open ArthaShield](https://arthasheild.vercel.app/)

## Evaluator quick start

ArthaShield is a working financial decision-support prototype. The fastest way to review it is:

1. **Open the live app** and review the consent screen. No bank login, password, OTP or UPI PIN is requested.
2. **Explore with synthetic data.** Use a built-in synthetic persona or the Privacy Inspector's preloaded synthetic statement. Do not upload a real bank statement for this public demonstration.
3. **Follow the financial workflow.** Review the imported-session overview, evidence-based classifications, Leakage Radar, Commitment Stress Test, EMI Reality Check and session audit trail.
4. **Inspect the privacy boundary.** In Privacy Inspector, select **Preview Scrub** to compare the synthetic raw sample with the server-returned sanitized preview before optional AI analysis.

**What to look for:** ArthaShield separates observed cash movement from verified income, treats recurrence as an evidence question, and calculates financial figures in Python. Optional Gemini commentary explains sanitized information; it does not calculate or replace the financial results.


[![Hackathon](https://img.shields.io/badge/Arthaton-2026-emerald.svg)](https://arthaton2026.dev)
[![Architecture](https://img.shields.io/badge/Architecture-Tokenized%20PII%20%2B%20Deterministic%20Math-blue.svg)]()
[![Stack](https://img.shields.io/badge/Stack-React%20%7C%20Django%20%7C%20Python-indigo.svg)]()

> **Mission:** let an ordinary person understand a bank statement, see where the money actually goes, and test a "no-cost" EMI offer — **without handing over bank credentials, UPI PINs, or raw personal identifiers.**

---

## 1. The problem

Three things make personal finance analysis hard:

1. **Silent, recurring outflows.** Forgotten subscriptions, convenience fees on "0% No-Cost" EMIs and rent/EMI obligations drain an account quietly. The damage is in the *pattern*, not in any single transaction.
2. **Documents written in legalese.** A statement or loan letter buries an 18% GST line, a processing fee and a reference number inside prose.
3. **Aggregators that demand the keys to your money.** Most finance apps ask for net-banking credentials or scrape an SMS inbox, then retain what they read.

ArthaShield takes a different route: the user's statement is uploaded to the ArthaShield Django backend for parsing; identifiers are **tokenized on the server before any optional external AI processing**, and every number on the dashboard is produced by **deterministic Python** — never by a language model.

---

## 2. What ArthaShield actually does

| Capability | What it does | Where the numbers come from |
|---|---|---|
| **Statement ingestion** | Parses uploaded CSV / PDF / TXT statements and pasted SMS alerts into normalised transactions, with duplicate-import protection. | Deterministic |
| **Evidence-based transaction intelligence** | Categorises debits/credits, attributes refunds to the purchase they reverse, separates income from reimbursements, redemptions and transfers. | Deterministic |
| **Imported-session financial overview** | A dashboard computed over *your* imported statement: income, net living expenses, savings, runways, safe-to-spend and a scrubbed transaction ledger. | Deterministic |
| **Commitment vs. pattern** | Distinguishes a **subscription commitment**, a **fixed obligation** (rent/EMI/utility/insurance) and **repeated discretionary spending** (a café, a supermarket) — a repeat is not automatically a commitment. | Deterministic |
| **Own-account transfer detection** | Recognises `UPI/SELF/TRANSFER` and friends as movements between your own accounts, so they never inflate income or expenses. | Deterministic |
| **Commitment Stress Test & Judgment Flip** | Evaluates a purchase/EMI across 3 scenarios (Buy Now vs. EMI vs. Wait), models 90-day cash flow trajectories, detects safety floor breaches, and calculates the exact day a decision flips to SAFE. | Deterministic Python math |
| **"What-If" EMI reality check** | Simulates a purchase with fees and GST and reports the **effective annual borrowing cost (XIRR)** from the real cash flows. | Deterministic |
| **Evidence-Linked Decision Support** | "Show Me The Evidence" connects every verdict directly to verified session ledger transactions; supports human correction of misclassified records. | Deterministic Ledger |
| **Privacy Inspector** | Live split view: what was masked, how many tokens, and what the sanitized stream looks like before it is used. | Deterministic |
| **Optional AI statement commentary** | Gemini may explain the *sanitized* transaction stream alongside pre-computed metrics. It never calculates or changes financial figures. | Model (advisory only) |
| **Optional AI commitment explanation** | Gemini may explain the deterministic Buy Now / EMI / Wait decision packet. Returned transaction references are checked against the active session ledger; the model cannot change the Python verdict. | Model (advisory only) |
| **Ambient atmosphere** | A continuously morphing organic sand texture behind every screen, drawn on two lightweight canvases. It carries no data and never intercepts a click. | Visual only |

---

## 2.1 Interface design

The application uses a monochrome interface with a subtle animated background. The effect is decorative: it does not control data processing or financial calculations. It respects `prefers-reduced-motion` and pauses while the browser tab is hidden.

The rendering and motion checks live in `frontend/src/components/effects/ambientSand.js` and can be run with:

```bash
cd frontend
node scripts/verify-ambient-background.mjs
```

---

## 2.2 The signature experience: Commitment Stress Test & Judgment Flip

ArthaShield evolves from a retrospective financial dashboard into an active **financial commitment decision-support system**.

Central user question:
> **"What happens to my financial situation if I make this commitment?"**

New central positioning:
> **"ArthaShield doesn't just tell you whether you can afford something. It shows you what could go wrong, when it could happen, and exactly what would change the decision."**

### Three-Scenario Reality Check

| Scenario | What is evaluated | Key calculations |
|---|---|---|
| **Scenario A: Buy Now** | Immediate lump-sum cash outflow. | Immediate liquidity drain, remaining balance, post-purchase runway, 90-day cash flow trajectory. |
| **Scenario B: Buy with EMI** | Financed instalment plan with hidden fees and GST. | Base EMI, monthly convenience fee, upfront disbursement fee, 18% GST load, XIRR true borrowing cost, buffer consumption %. |
| **Scenario C: Wait (The Flip)** | Delaying the purchase by a selectable number of days (0 to 90d slider). | Accumulated savings during wait: net daily cash flow (`income - burn`) × `delay_days`. If expenses exceed income, capital burning is accurately modeled (reducing balance over time). Safe flip is identified as unattainable when cash flow is negative. |

### The Judgment Flip
When a proposed commitment is `NOT SAFE` or `CONDITIONAL` today, the engine calculates the **Safe Flip Threshold**:
* Identifies how many days of net savings accumulation are required to elevate the financial cushion.
* Moving the delay slider dynamically recalculates the 90-day cash flow.
* When the accumulated buffer is sufficient, the system triggers the **Judgment Flip Banner**:
  `⚡ JUDGMENT FLIP ACTIVATED: Waiting 30 days accumulates ₹18,400 in net savings, flipping your verdict from NOT SAFE to SAFE!`

### Commitment Safety Card & Decision Verdicts
Labels are strictly deterministic and rule-based (never hallucinated):
* **SAFE**: Post-purchase emergency runway >= 3.0 months, safety buffer intact, no cash-flow deficit in 90 days.
* **CONDITIONAL**: Emergency buffer breached, runway between 1.0 and 3.0 months, or commitment consumes 25-45% of discretionary buffer.
* **NOT SAFE**: Immediate liquidity deficit (balance < 0), projected account deficit within 90 days, runway < 1.0 month, or commitment consumes > 45% of discretionary buffer.
* **INSUFFICIENT DATA**: Missing verified liquid balance or unverified/irregular income. Never displays a false green verdict.

### "Show Me The Evidence"
Every verdict is backed by genuine session transactions from the authenticated ledger:
* Operating Income: Verified payroll/contract credits (unclassified peer transfers withheld).
* Fixed Obligations: Confirmed rent and loan EMIs.
* Subscriptions: Confirmed recurring charges.
* Human Correction: Users can mark an expense as an internal own-account transfer or adjust categories, triggering instant recalculation with a persistent audit trail.

### "What Would Make This Safe?" Scenario Explorer
Provides up to three actionable deterministic alternatives:
1. **Delay Purchase**: Exact days required to build a sufficient safety cushion.
2. **Discretionary Spending Reduction**: Trimming flexible dining/shopping to free up buffer.
3. **Restructure Tenure**: Extending instalment months to lower monthly outflow below critical thresholds.

## 3. System architecture

```
[Browser: React + Vite + Tailwind]
        │  X-Session-Token (bearer token cached in sessionStorage; backend also sets HttpOnly cookie)
        ▼  HTTPS / JSON
[Django REST API]
   ├── PII sanitization engine        regex + tokenization
   │      names → [USER_PRIMARY], accounts → [REDACTED_ACCOUNT], …
   ├── Deterministic finance engine   categorisation, refund matching,
   │      │                            transfer detection, commitment classes,
   │      │                            XIRR effective borrowing cost
   │      └── writes only sanitized labels to the database
   ├── Response boundary              every ingestion response passes through
   │                                  api/response_safety.py
   └── Optional advisor layer         receives ONLY sanitized text and
                                      pre-computed metrics; schema-validated
[Database]  SQLite fallback; PostgreSQL when DATABASE_URL and a compatible driver are configured
```

**What is stored:** imported transaction records use normalized merchant labels, financial fields and derived classifications, together with per-session snapshots. The transaction model has no raw-statement narration field; original input is handled in memory during parsing and sanitized before imported records are saved. A session can be purged with one action.

---

## 4. Quick start (local development)

**Prerequisites:** Python **3.12+**, Node.js **20+**.

### 4.1 Backend

```bash
cd backend
python -m venv ../venv
# Windows:            ..\venv\Scripts\activate
# Linux / macOS:      source ../venv/bin/activate

pip install -r requirements.txt

# Optional: copy the example environment file and edit it.
#   Windows:           Copy-Item .env.example .env
#   Linux / macOS:     cp .env.example .env

python manage.py migrate
python manage.py runserver 8000
```

The API is then available at `http://127.0.0.1:8000/api/v1/`.
Without `GEMINI_API_KEY` the advisor runs its deterministic offline fallback
and labels the result *"Offline Rule-Based Financial Insights"*.

### 4.2 Frontend

```bash
cd frontend
npm install
npm run dev
```

The UI is then available at `http://localhost:5173/`.

### 4.3 Tests and production build

```bash
# Backend: the full automated suite
cd backend
python manage.py test api advisor analytics sanitizer

# Frontend: lint + production build
cd frontend
npm run lint
npm run build

# Frontend: the ambient background's motion model, measured without a browser
node scripts/verify-ambient-background.mjs
```

The backend suite is the authoritative verification: it covers authentication,
session isolation, consent enforcement, PII masking, refund matching, transfer
detection, recurring classification, the XIRR borrowing-cost maths and the
persistence of every figure shown on the dashboard. It also asserts that imported
statements and synthetic personas are never mixed: dataset selection is strict,
unverified balances produce `INSUFFICIENT DATA` rather than a reassuring grade,
and a single observed debit is reported as a probable recurring-payment candidate
instead of a confirmed subscription.

`scripts/verify-ambient-background.mjs` rasterises the background's motion
model with the same maths the canvas uses and checks that the texture is
populated and structured, that the grains never blow out to pure white, that
the motion is continuous with no visible restart, that the static
reduced-motion frame is deterministic, that a viewport change is handled, and
that a frame stays inside the performance budget. `scripts/ambient-harness.html`
is a development-only page that exercises the component itself (reduced
motion, pause-when-hidden, resume) in a browser.

---

## 5. The financial engine, in detail

### 5.1 Income is not everything that arrives

A credit is only *earned income* when the evidence says so. A reimbursement, a
mutual-fund redemption, a broker transfer, a refund and an own-account transfer
are each classified separately, so savings and runways are not inflated by
money that was already yours.

### 5.2 Refunds are matched with evidence

A refund is tied back to the purchase it reverses using a shared reference ID
(matches are **CONFIRMED**) or a normalised merchant/amount match (**PROBABLE**).
Only a confirmed same-period match reduces the net living expenses; a probable
match is reported but never applied. An over-sized refund is reported as
unmatched rather than silently cancelling spending.

### 5.3 A repeat is not a commitment

`detect_subscriptions` reports two independent dimensions:

* `recurrence_confidence` — how regular the payments are (cadence + count);
* `commitment_class` — what the repetition means:
  * `subscription_commitment` (Netflix, ChatGPT Plus, a gym seat),
  * `fixed_obligation` (rent, loan instalment, insurance, utility),
  * `recurring_discretionary` (a café, a supermarket, a pharmacy),
  * `recurring_pattern` (a repeat with no identifiable counterparty).

Only confirmed commitments reserve money for an upcoming bill; only confirmed
subscription commitments count as *potentially avoidable* expenditure — and even
those are never described as wasted money, because a statement cannot show
whether a subscription is still used.

### 5.4 Effective borrowing cost is computed from cash flows

The EMI simulator prices a purchase with its processing fee, GST and instalment
schedule, then solves the annualised IRR of the borrower's actual dated cash
flows:

```
NPV(r) = Σ CF(i) / (1 + r)^(days(i)/365) = 0
```

A ₹60,000 purchase over 12 months with a ₹199/month convenience fee and 18% GST
has a nominal rate of 0% and an **effective annual borrowing cost of 8.94%**.
The old fee-load approximation reported 4.70% for the same purchase.

### 5.5 Safe-to-Spend refuses to guess

The allowance is only produced when the statement period, the income and the
outstanding commitments are known; otherwise the response says exactly which
input is missing instead of inventing a number.

---

## 6. Privacy and security posture

**What is true**

* ArthaShield never asks for a bank login, password, UPI PIN or an OTP, and
  never stores one.
* Uploaded statements are processed by the Django backend. Before an optional
  Gemini request, the advisor re-sanitizes the text and checks for recognizable
  residual identifier patterns. Only the sanitized payload is sent to the model.
  These protections are heuristic and cannot guarantee detection of every name
  or identifier in arbitrary free text.
* The model receives **no** raw narration and performs **no** arithmetic.
* Statement and SMS ingestion responses use safe-serialization helpers in
  `api/response_safety.py` so raw narration and transaction references are not
  echoed back as ordinary client-facing fields.
* Requests are bound to a session; a request that presents another session's id
  is refused with `403 SESSION_MISMATCH`.
* Consent is enforced server-side for every persistent operation.
* One click (`/api/v1/privacy/nuke-data/`) deletes the session's records.
* The frontend caches the current bearer token in `sessionStorage` and sends it
  in the `X-Session-Token` header. The backend also issues an HttpOnly session
  cookie; only the token's SHA-256 hash is stored in the `SecureSession` row.

**What is not claimed**

* This is **not** a zero-knowledge or client-only system: the server receives
  and parses the uploaded statement. The application never requests bank
  credentials. Recognizable identifiers are redacted and checked before optional
  provider calls, but heuristic detection is not perfect anonymization.
* This is **not** a certified DPDP/GDPR compliance product. It implements
  data-minimising defaults and a deletion path; it is not legal advice and
  carries no regulatory certification.
* Deletion is scoped to the data this application holds for the session. It
  cannot reach copies a user exported elsewhere.
* Heuristic safeguards (name detection, merchant classification) are
  conservative but not provably complete. Free-text echoes can still contain a
  personal name that no pattern recognises.

---

## 7. The AI layer, precisely

* **Model:** configured through `GEMINI_MODEL`; the repository's example
  configuration defaults to Google's current stable Flash model,
  `gemini-3.8-flash`, which supports the structured JSON response path used here.
  The model can be changed without a code change through the environment variable.
* **Key:** read from `GEMINI_API_KEY` at request time. It is never stored,
  logged or returned.
* **Input:** sanitized text plus the deterministic metrics. Nothing else.
* **Output:** schema-validated before it is shown. A malformed answer is
  discarded and the deterministic response is used instead. Reasoning ("thinking")
  parts are stripped, and a blocked or truncated answer is treated as a failure.
* **Separation of responsibilities:** Python computes all financial figures and verdicts. Gemini provides optional explanations for sanitized statement analysis and the Commitment Stress Test; it never writes to or replaces the deterministic metrics.
* **Instruction/data separation:** trusted model instructions use Gemini's dedicated system-instruction field. Statement text and the minimized stress-test decision packet are sent separately as untrusted user data.
* **Privacy gate:** the advisor re-sanitizes provider-bound text and the stress-test decision packet, then checks for recognizable residual identifiers such as email addresses, UPI VPAs, phone numbers, account/card patterns, PAN, Aadhaar and common banking IDs. If a recognizable identifier remains, the provider request is skipped and the offline rules are used. This is defense in depth, not a guarantee of perfect free-text name detection.
* **Output validation:** every field consumed by the UI is type-checked and length-bounded. Stress-test explanation arrays are validated, and returned evidence IDs are filtered against the active session.
* **Numbers:** monetary claims that do not match a monetary value produced by the deterministic engine are rejected and the offline response is used. Percentages, counts, health scores and durations cannot authorize rupee amounts.
* **Offline:** without a key (or on any failure — timeout, network error, non-200 status, blocked prompt, malformed output, residual PII or unsupported monetary claim) the advisor returns a clearly labelled deterministic response whose amounts come from the engine. The dashboard is unaffected either way.
* **Transport:** the current stable API route (`v1`) is used, with `v1beta` as a
  fallback for accounts not yet served by it. Request configuration is derived
  from the pinned model, so a model that does not accept a field is never sent
  one.
* **Defence in depth:** the advisor repeats sanitization at the provider boundary and
  checks recognizable residual identifiers before sending. This is a heuristic
  safeguard, not a claim that every personal name in free text can be detected.

If the live path is unavailable in your environment, the product is still fully
functional: every financial figure on the dashboard is computed by Python.

### 7.1 Verifying the live path yourself

`backend/verify_live_ai.py` exercises the real provider path with synthetic
data and reports exactly what happened. It never prints, stores or logs the key.

```bash
cd backend
export GEMINI_API_KEY=<your key>      # Windows PowerShell: $env:GEMINI_API_KEY = "<your key>"
python verify_live_ai.py
```

It prints the model it used, the live or offline outcome, and fails loudly if
any personal identifier or the key appears in the response. Exit code `0` means
a genuine live request succeeded and passed every check; `1` means it did not
(the deterministic fallback was used instead, which is the designed behaviour).

**Release status:** the live path was exercised against the real provider
endpoint during release preparation and the request reached Google's API
correctly, but it could not be completed because no valid API key was available
in that environment. The offline path, the schema validation, the numeric-claim
verification and the privacy boundary are covered by the automated suite
(`backend/advisor/test_ai_integration.py`).

---

## 8. Synthetic demo data

`synthetic_data/personas.json` contains three fully synthetic personas
(Rohit Verma, Priya Sharma, Aman Joshi) for instant evaluation. All names,
balances and merchants are invented. `synthetic_data/sample_statement_rohit_raw.csv`
is a *raw-looking* statement used for the privacy demo; it is excluded from the
repository by `.gitignore` because it deliberately contains identity-shaped
strings.

---

## 9. Deployment

### 9.1 Backend on Render

`render.yaml` is included. Connect the repository to Render, and set:

Render terminates public TLS at its edge and forwards requests to the service
over its internal network. In production, Django trusts Render's
`X-Forwarded-Proto: https` signal so request security checks recognise the
original HTTPS connection. The backend also emits a one-day HSTS policy as a
cautious initial setting; subdomain coverage and browser preload are deliberately
not enabled. Render itself handles the public HTTP-to-HTTPS redirect, so the
application does not add a second redirect at the proxy hop.

| Variable | Required | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | yes | Generate a random value. |
| `DATABASE_URL` | optional | Set only when a PostgreSQL database has been provisioned and a compatible PostgreSQL driver is included. The supplied `render.yaml` creates the web service only; it does not create a database. |
| `ALLOWED_HOSTS` | yes | Your Render hostname. |
| `FRONTEND_URL` | recommended | Your Vercel URL (CORS). |
| `GEMINI_API_KEY` | optional | Enables live analysis; omit it for the offline mode. |
| `GEMINI_MODEL` | optional | Only if you must pin a different model. Do not pin a deprecated one. |
| `ENVIRONMENT` | yes | `production`. |

The build command runs `pip install -r requirements.txt && python manage.py migrate`;
the start command is `gunicorn core.wsgi:application --bind 0.0.0.0:$PORT`.

### 9.2 Frontend on Vercel

`frontend/vercel.json` is included. Set `VITE_API_BASE_URL` to your backend URL
(e.g. `https://<your-backend>.onrender.com/api/v1`).

### 9.3 Other platforms

Any host that can run `gunicorn core.wsgi:application` and serve a static
Vite build works. The backend needs `DATABASE_URL` (or falls back to SQLite)
and `DJANGO_SECRET_KEY` in production.

---

## 10. Known limitations

* **One session per browser tab.** The session secret lives in `sessionStorage`,
  so two tabs are two independent sessions with two independent datasets. The
  intended workflow is a single tab; use the "Import With Consent" flow there.
* **Single-account analysis.** Transfers to accounts outside the imported
  statement appear as unlinked inflows/outflows; counterparty balances are not
  visible.
* **Heuristic merchant and name classification.** Subscription, obligation and
  discretionary decisions use deterministic keyword and pattern evidence. A
  merchant outside the known set is treated conservatively (as a pattern, not a
  commitment).
* **Variable amounts are summarised by their observed mean**, with the observed
  range reported alongside.
* **The AI path needs a credential and a supported model.** Without them the
  application runs its deterministic offline mode, which is fully verified. The
  live path was verified against the real provider endpoint, but a complete live
  exchange could not be performed in the release environment because no valid
  API key was available there — run `backend/verify_live_ai.py` with a key to
  confirm it on your own machine (§7.1).
* **PDF parsing is best-effort.** Table-structured PDFs parse well;
  free-form layouts fall back to line parsing.
* **Demo data:** use synthetic personas or synthetic statements for public review;
  do not upload real confidential bank statements into the hosted demonstration.
* **Render persistence:** the included `render.yaml` provisions a web service,
  not a database or persistent disk. Unless a PostgreSQL URL and compatible
  driver are configured separately, Django uses its SQLite fallback. On an
  ephemeral service filesystem, stored session data may be lost after a restart.
* **Regulatory boundary:** ArthaShield is educational decision support. It is not
  certified financial advice, credit underwriting or a DPDP/GDPR certification.

---

## 11. Repository layout

```
backend/            Django project (api, analytics, advisor, data_processor, sanitizer)
  core/             settings and URL configuration
  api/              views, models, insights engine, response boundary, tests
  analytics/        deterministic health / safe-to-spend / XIRR engine
  advisor/          optional AI layer (schema-validated, offline fallback)
  verify_live_ai.py utility that exercises the real provider path
  data_processor/   statement + SMS parsers, normalizer, transfer classifier
  sanitizer/        PII tokenization patterns
frontend/           React + Vite application
  src/components/ui/ shared primitives: Button, Card, Tooltip, SpotlightCard,
                   ProgressBar, PersonaOrb and the motion hooks
  src/components/effects/ ambient background + ambient effect components
  scripts/         verification utilities (see 4.3)
synthetic_data/     synthetic personas (and the excluded raw demo statement)
render.yaml         backend deployment blueprint
```

---

## 11.1 The interaction layer

The interface uses one monochrome motion vocabulary, defined once in
`frontend/src/index.css` and shared by every surface:

| Surface | Behaviour |
|---|---|
| **Persona selector** | A metallic orb rolls along the track between the three personas. Hovering previews a persona, leaving returns the orb to the selected one, and clicking performs the real selection. |
| **Sidebar** | The rail expands/collapses (270px ↔ 76px, 280ms) and a slim indicator slides between the six navigation items while the active item keeps its solid-white design. |
| **Metric cards** | Health Index, Emergency Runway, Debt Pressure and Silent Leakage lift 3px, illuminate their border to silver and carry a very soft spotlight that follows the pointer. On pointer devices they also take an almost imperceptible 3D tilt. |
| **Progress indicators** | The four health bars grow from empty the first time their data is available and the bar is on screen. The value itself is never altered - only the rendered width animates. |
| **Transaction journal** | Rows highlight on hover and focus, the audit flags ease into view, and a selected row keeps its own marker. Filtering and every existing column are unchanged. |
| **Sections** | Changing dashboard section fades the new panel in over 8px, without remounting the shell or interrupting any request. |
| **Buttons** | A 1px lift on hover, a slight press, and one consistent keyboard focus ring for the whole application. |

Everything is CSS-transition driven; JavaScript only publishes pointer
coordinates and visibility flags. Touch devices get no tilt, and
`prefers-reduced-motion` collapses the entire layer to instant state changes.

---

## 12. Contributing and verification

Every change is expected to keep the suite green:

```bash
cd backend && python manage.py test api advisor analytics sanitizer
cd frontend && npm run lint && npm run build
```

The suite is the contract: it asserts the financial arithmetic, the privacy
boundary and the session/consent rules rather than the shape of the UI.

---
