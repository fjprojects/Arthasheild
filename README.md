# ArthaShield (FinGuard AI)
### Privacy-First AI Financial Companion for Arthaton 2026

[![Hackathon](https://img.shields.io/badge/Arthaton-2026-emerald.svg)](https://arthaton2026.dev)
[![Architecture](https://img.shields.io/badge/Privacy-Zero--Knowledge-blue.svg)]()
[![Stack](https://img.shields.io/badge/Stack-React%20%7C%20Django%20%7C%20Postgres-indigo.svg)]()

> **Mission:** Empower everyday individuals to demystify complex financial documents, eliminate silent financial leaks, and simulate major spending decisions—**without ever handing over bank passwords, UPI PINs, or raw personal identifiers to external AI models.**

---

## 🌟 The Core Problem

Most ordinary people face severe **financial information asymmetry and silent cashflow leakage**:
1. **The "Death by a Thousand Debits" Effect:** Micro-transactions, forgotten app subscriptions, and automated UPI mandates silently drain ₹3,000–₹15,000 every month.
2. **Document Incomprehensibility:** Bank statements and loan letters are written in deliberate legalese with buried penal charges, foreclosure fees, and hidden maintenance penalties.
3. **The Privacy Breach of Existing Aggregators:** Mainstream finance apps scrape SMS inboxes, demand net-banking credentials, and sell anonymized user spending data to credit bureaus and advertisers.

---

## 🛡️ The ArthaShield Winning Solution

ArthaShield introduces a **Deterministic-Math + Semantic-AI Hybrid Architecture**:

1. **Deterministic Python Engine:** All balance sums, interest calculations, EMI breakdowns, and burn rates are computed strictly using deterministic Python code. **Zero hallucinated numbers.**
2. **Client/Server Zero-Knowledge PII Pipeline:** Real names, account numbers, IFSC codes, PAN/Aadhaar/SSN numbers, and phone numbers are scrubbed and replaced with synthetic tokens (`[USER_PRIMARY]`, `[REDACTED_ACCOUNT]`) *before* any payload leaves the server.
3. **The "Privacy Inspector" (Live Demo Showstopper):** An interactive split-view showing:
   - Raw Financial Statement with sensitive data.
   - Live Sanitization Audit (counts of masked PII elements).
   - Sanitized Stream sent to AI.
   - Plain-English demystification of predatory clauses and fees.
4. **"What-If" EMI Reality Check Simulator:** Exposes disguised 0% "No-Cost" EMI traps, revealing hidden processing charges, GST on subvention, and the true effective APR.
5. **One-Click Data Shredder:** A DPDP/GDPR-compliant cascading delete button that purges all stored transactions and database records with a single click.

---

## 🏗️ System Architecture

```
[User Browser (React + Tailwind)]
        │
        ▼ (HTTPS REST)
[Django Backend API (Render)]
   ├── PII Sanitization Engine (Regex + Tokenizer)
   │      └── Replaces PII with [REDACTED_ACCOUNT], [USER_PRIMARY]
   ├── Deterministic Finance Engine
   │      └── Safe-to-Spend, Runway, DTI, Effective APR
   ├── Structured Semantic LLM Layer
   │      └── Gemini 2.0 Flash (receives ONLY sanitized tokens & pre-calculated numbers)
   └── Managed PostgreSQL / SQLite DB
          └── Ephemeral storage, zero credential retention, 1-click purge
```

---

## 🚀 Quick Start Guide (Local Development)

### Prerequisites
- Python 3.12+
- Node.js v20+

### 1. Backend Setup (Django REST Framework)
```bash
cd backend
# Create virtual environment
python -m venv ../venv
# Activate virtual environment
# Windows: ..\venv\Scripts\activate
# Linux/Mac: source ../venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# (Optional) Set your Gemini API key for live AI demystification
# Windows: set GEMINI_API_KEY=your_key_here
# Linux/Mac: export GEMINI_API_KEY=your_key_here

# Start backend server
python manage.py runserver 8000
```
Backend will be live at `http://127.0.0.1:8000/`.

### 2. Frontend Setup (React + Vite + Tailwind CSS)
```bash
cd frontend
# Install dependencies
npm install

# Start Vite development server
npm run dev
```
Frontend will be live at `http://localhost:5173/`.

---

## 🧪 Testing the APIs

Run the automated test suite verifying PII scrubbing, deterministic math, and the 1-click data shredder:
```bash
cd backend
python test_api.py
```

---

## 🎭 Synthetic Demo Personas Included

ArthaShield includes 3 pre-seeded realistic personas for instant hackathon evaluation:
- 👨‍💻 **Rohit Verma (Freelance UI/UX Designer):** ₹82,000/mo variable income, 5 hidden subscription leaks (Adobe CC, unused AWS EC2, Figma duplicate, ChatGPT), vulnerable to a disguised "No-Cost" EMI.
- 👩‍💼 **Priya Sharma (Corporate Associate):** ₹75,000/mo fixed salary, auto-loan commitment, penalized by hidden credit card late fees and minimum balance fines.
- 🎓 **Aman Joshi (College Senior / Intern):** ₹18,000/mo stipend, high micro-UPI transaction sprawl (canteen/tea), predatory 36% APR BNPL micro-credit trap.

---

## 🔒 Privacy & Regulatory Integrity Checklist

- [x] **No Bank Credentials Required:** Zero bank logins, passwords, or UPI PINs.
- [x] **Client & Server PII Masking:** High-entropy numbers and names scrubbed prior to AI transmission.
- [x] **Zero External Retention:** Files processed ephemerally; documents are self-destructed immediately after tokenization.
- [x] **1-Click Hard Purge:** Dedicated `/api/v1/privacy/nuke-data/` endpoint.
- [x] **Non-Advisory Disclaimer:** Persistent warnings indicating insights are educational and not certified SEBI/FINRA financial advice.

---

## 🌐 Deployment to Render & Vercel

- **Backend (Render):** Uses the provided `render.yaml`. Connect your GitHub repository to Render, configure PostgreSQL, and add `GEMINI_API_KEY`.
- **Frontend (Vercel):** Connect the `frontend/` directory to Vercel with the provided `frontend/vercel.json`. Set environment variable `VITE_API_BASE_URL` to your Render backend URL.

