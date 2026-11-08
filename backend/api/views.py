"""
ArthaShield API Views
Phase 1 + 1.1 + 1.2 + 1.2.1 + Phase 2 (Financial Intelligence) + Phase 3 (Security Hardening)
"""
import json
import os
import hashlib
import tempfile
import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

import pdfplumber

from .models import (
    ConsentAuditLog,
    FinancialSnapshot,
    Transaction,
    DecisionScenario,
    SecureSession,
)
from .security import authenticate_request_session
from sanitizer.services import SanitizerService
from analytics.services import AnalyticsEngine
from advisor.services import AdvisorService
from data_processor.statement_parser import (
    BankStatementParser,
    MAX_FILE_SIZE_BYTES,
    MAX_PDF_PAGES,
)
from data_processor.sms_parser import BankSmsParser
from data_processor.normalizer import TransactionNormalizer
from .insights import (
    categorize_transactions,
    monthly_budget,
    detect_subscriptions,
    detect_unusual_spending,
    spending_patterns,
)

logger = logging.getLogger(__name__)

SYNTHETIC_DATA_PATH = Path(settings.BASE_DIR).parent / "synthetic_data" / "personas.json"
MAX_UPLOAD_SIZE_BYTES = MAX_FILE_SIZE_BYTES  # 5 MB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_active_consent(session_id: str):
    """
    Return the latest applicable consent record for a session, or None.
    If the latest consent record was withdrawn (is_active=False), returns None immediately.
    """
    latest = (
        ConsentAuditLog.objects.filter(session_id=session_id)
        .order_by("-consented_at")
        .first()
    )
    if not latest or not latest.is_active:
        return None
    if not (
        latest.anonymized_processing_accepted
        and latest.no_credential_disclosure_acknowledged
    ):
        return None
    return latest


def _compute_fingerprint(session_id: str, tx) -> str:
    """
    Deterministic SHA-256 fingerprint for cross-import duplicate detection.
    Uses sanitized canonical fields only. Never stores raw PII.
    """
    merchant = SanitizerService.sanitize(
        str(
            getattr(tx, "normalized_merchant", "")
            or getattr(tx, "merchant", "")
            or ""
        )
    )["sanitized_text"]
    ref = SanitizerService.sanitize(str(getattr(tx, "reference_id", "") or ""))[
        "sanitized_text"
    ]
    source = f"{session_id}|{tx.transaction_date}|{tx.amount}|{tx.transaction_type}|{merchant}|{ref}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Phase 3: Secure Session Identity Views
# ---------------------------------------------------------------------------

class InitSessionView(APIView):
    """
    Issues a cryptographically unpredictable session identity and secret token.
    Binds all subsequent financial operations to this verified session.
    """
    def post(self, request):
        session, raw_token = SecureSession.issue_session()
        response = Response(
            {
                "status": "SESSION_INITIALIZED",
                "session_id": session.session_id,
                "session_token": raw_token,
                "expires_at": session.expires_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )

        is_secure = getattr(settings, "IS_PRODUCTION", False)
        response.set_cookie(
            key="arthashield_session_token",
            value=raw_token,
            httponly=True,
            secure=is_secure,
            samesite="Lax",
            max_age=86400,
            path="/",
        )
        return response


class RotateSessionView(APIView):
    """
    Rotates session credential, invalidating previous secret token.
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err

        new_token = auth_session.rotate_token()
        response = Response(
            {
                "status": "SESSION_ROTATED",
                "session_id": auth_session.session_id,
                "session_token": new_token,
                "expires_at": auth_session.expires_at.isoformat(),
            }
        )
        is_secure = getattr(settings, "IS_PRODUCTION", False)
        response.set_cookie(
            key="arthashield_session_token",
            value=new_token,
            httponly=True,
            secure=is_secure,
            samesite="Lax",
            max_age=86400,
            path="/",
        )
        return response


class SessionStatusView(APIView):
    """
    Returns verified session status and active consent information.
    """
    def get(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err

        active_consent = _get_active_consent(auth_session.session_id)
        return Response(
            {
                "session_id": auth_session.session_id,
                "is_active": not auth_session.is_expired and not auth_session.is_revoked,
                "expires_at": auth_session.expires_at.isoformat(),
                "has_active_consent": active_consent is not None,
                "consent_version": (
                    active_consent.consent_version if active_consent else None
                ),
            }
        )


# ---------------------------------------------------------------------------
# Persona Views
# ---------------------------------------------------------------------------

class PersonaListView(APIView):
    """Returns available synthetic personas for instant judging/testing."""
    def get(self, request):
        if not SYNTHETIC_DATA_PATH.exists():
            return Response(
                {"error": "Synthetic data not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        with open(SYNTHETIC_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Response(data)


class SelectPersonaView(APIView):
    """
    Loads a synthetic persona into the active session.
    Persona transactions are stored with source_type='persona' and do NOT
    delete previously imported real transactions.
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        persona_id = request.data.get("persona_id", "persona_freelancer_rohit")

        if not SYNTHETIC_DATA_PATH.exists():
            return Response(
                {"error": "Synthetic data file missing"},
                status=status.HTTP_404_NOT_FOUND,
            )

        with open(SYNTHETIC_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        target = next((p for p in data["personas"] if p["id"] == persona_id), None)
        if not target:
            return Response(
                {"error": f"Persona '{persona_id}' not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        income = float(target["monthly_average_income"])
        balance = float(target["account_summary"]["current_balance"])
        leaks = float(target["detected_leaks_summary"]["total_monthly_leakage"])

        commitments = sum(
            float(c.get("monthly_amount", 0))
            for c in target.get("active_commitments", [])
        )
        for t in target.get("transactions", []):
            if t.get("is_recurring") and "Rent" in t.get("category", ""):
                commitments += float(t.get("amount", 0))

        expenses = commitments + leaks + (income * 0.35)

        health_metrics = AnalyticsEngine.calculate_health_score(
            monthly_income=income,
            monthly_expenses=expenses,
            liquid_balance=balance,
            fixed_commitments=commitments,
        )
        safe_to_spend = AnalyticsEngine.calculate_safe_to_spend(
            current_balance=balance,
            monthly_income=income,
            pending_fixed_obligations=commitments,
            days_remaining_in_month=18,
        )

        snapshot, _ = FinancialSnapshot.objects.update_or_create(
            session_id=session_id,
            defaults={
                "liquid_balance": balance,
                "monthly_income": income,
                "monthly_expenses": expenses,
                "fixed_commitments": commitments,
                "monthly_leakage_detected": leaks,
                "health_score": health_metrics["health_score"],
                "health_grade": health_metrics["grade"],
                "emergency_runway_months": health_metrics["metrics"]["runway_months"],
                "safe_to_spend_daily": safe_to_spend["safe_to_spend_daily"],
                "safe_to_spend_weekly": safe_to_spend["safe_to_spend_weekly"],
            },
        )

        tx_objects = []
        for t in target.get("transactions", []):
            tx_objects.append(
                Transaction(
                    snapshot=snapshot,
                    session_id=session_id,
                    transaction_date=t["date"],
                    amount=t["amount"],
                    transaction_type=t["type"],
                    normalized_merchant=t["description"],
                    category=t.get("category", "General"),
                    is_recurring=t.get("is_recurring", False),
                    is_leak=t.get("leak_flag", False),
                    hidden_fee_estimate=t.get("hidden_fee_estimate", 0.0),
                    risk_note=t.get("risk_note", ""),
                    source_type=Transaction.SOURCE_PERSONA,
                )
            )

        with db_transaction.atomic():
            Transaction.objects.filter(
                session_id=session_id, source_type=Transaction.SOURCE_PERSONA
            ).delete()
            Transaction.objects.bulk_create(tx_objects)

        return Response(
            {
                "status": "LOADED",
                "persona": target,
                "session_id": session_id,
                "health_metrics": health_metrics,
                "safe_to_spend": safe_to_spend,
            }
        )


# ---------------------------------------------------------------------------
# Privacy & Sanitization Views
# ---------------------------------------------------------------------------

class SanitizePreviewView(APIView):
    """
    Public live Sanitization Inspector preview.
    Processes uploaded file or raw text and outputs the scrubbed result and audit trail.
    Priority 6 Hardening: Never echoes raw_text_preview back over the wire.
    """
    def post(self, request):
        raw_text = request.data.get("raw_text", "")
        file_obj = request.FILES.get("file")

        if file_obj:
            if file_obj.size > MAX_UPLOAD_SIZE_BYTES:
                return Response(
                    {"error": "File exceeds 5MB limit"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            filename = file_obj.name.lower()
            try:
                content_bytes = file_obj.read()
                if filename.endswith(".pdf"):
                    # Check PDF signature
                    if not (content_bytes.startswith(b"%PDF-") or b"%PDF-" in content_bytes[:1024]):
                        return Response(
                            {"error": "Invalid PDF file signature"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                    try:
                        tmp.write(content_bytes)
                        tmp.flush()
                        tmp.close()
                        with pdfplumber.open(tmp.name) as pdf:
                            if len(pdf.pages) > MAX_PDF_PAGES:
                                return Response(
                                    {"error": f"PDF exceeds maximum allowed limit of {MAX_PDF_PAGES} pages."},
                                    status=status.HTTP_400_BAD_REQUEST,
                                )
                            raw_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
                    finally:
                        if os.path.exists(tmp.name):
                            try:
                                os.unlink(tmp.name)
                            except OSError:
                                pass
                else:
                    if b"\x00" in content_bytes:
                        return Response(
                            {"error": "Binary data detected in text file"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    raw_text = content_bytes.decode("utf-8", errors="replace")
            except Exception:
                return Response(
                    {"error": "Failed to read uploaded file"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if not raw_text or not raw_text.strip():
            return Response(
                {"error": "No text or file provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = SanitizerService.sanitize(raw_text)
        return Response(
            {
                "sanitized_text_preview": result["sanitized_text"][:3000],
                "redactions_audit": result["redactions"],
                "total_redactions_count": result["total_redactions_count"],
                "sanitized_length": len(result["sanitized_text"]),
                "privacy_status": "PII_STRIPPED_LOCAL_BOUNDARY_ENFORCED",
            }
        )


class DocumentAnalyzeView(APIView):
    """
    Runs deterministic analytics + LLM advisor.
    Enforces unconditional consent and server-side PII sanitization (defense-in-depth).
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        sanitized_text = request.data.get("sanitized_text", "")
        if not sanitized_text.strip():
            return Response(
                {"error": "No sanitized text provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Priority 3: Consent check for AI processing is unconditional
        consent = _get_active_consent(session_id)
        if not consent:
            return Response(
                {
                    "error": "Explicit user consent is required before AI analysis.",
                    "code": "CONSENT_REQUIRED",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Defense-in-depth: re-sanitize on server side
        server_sanitized = SanitizerService.sanitize(sanitized_text)[
            "sanitized_text"
        ]

        snapshot = FinancialSnapshot.objects.filter(session_id=session_id).first()
        if snapshot:
            metrics = {
                "health_score": snapshot.health_score,
                "health_grade": snapshot.health_grade,
                "emergency_runway_months": snapshot.emergency_runway_months,
                "monthly_income": float(snapshot.monthly_income),
                "monthly_expenses": float(snapshot.monthly_expenses),
                "monthly_leakage": float(snapshot.monthly_leakage_detected),
                "safe_to_spend_daily": float(snapshot.safe_to_spend_daily),
            }
        else:
            metrics = {
                "health_score": 68,
                "health_grade": "B (Stable)",
                "emergency_runway_months": 1.4,
                "monthly_income": 75000,
                "monthly_expenses": 58000,
                "monthly_leakage": 4200,
                "safe_to_spend_daily": 850,
            }

        advisor_insights = AdvisorService.analyze_sanitized_statement(
            server_sanitized, metrics
        )
        return Response(
            {
                "metrics": metrics,
                "advisor_insights": advisor_insights,
                "privacy_guarantee": "LLM processed anonymized payload only. Zero credentials stored.",
            }
        )


# ---------------------------------------------------------------------------
# Statement & SMS Parsing Views
# ---------------------------------------------------------------------------

class ParseStatementView(APIView):
    """
    Parses bank statements (CSV, PDF, TXT) into normalized transactions.
    Optional persist=true saves sanitized transactions to DB (requires active consent).
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        file_obj = request.FILES.get("file")
        raw_text = request.data.get("raw_text", "")
        format_hint = request.data.get("format", "csv").lower()
        filename = getattr(file_obj, "name", f"statement.{format_hint}")

        # Parse the statement safely
        if file_obj:
            if file_obj.size > MAX_UPLOAD_SIZE_BYTES:
                return Response(
                    {"error": "File exceeds 5MB limit"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                result = BankStatementParser.parse_file(file_obj, filename=filename)
            except ValueError as ve:
                return Response(
                    {"error": str(ve)}, status=status.HTTP_400_BAD_REQUEST
                )
            except Exception:
                return Response(
                    {"error": "Failed to parse statement file"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif raw_text.strip():
            try:
                if format_hint == "csv" or "," in raw_text:
                    result = BankStatementParser.parse_csv_text(raw_text)
                else:
                    result = BankStatementParser.parse_txt_bytes(
                        raw_text.encode("utf-8")
                    )
            except ValueError as ve:
                return Response(
                    {"error": str(ve)}, status=status.HTTP_400_BAD_REQUEST
                )
            except Exception:
                return Response(
                    {"error": "Failed to parse statement text"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            return Response(
                {"error": "No statement file or raw_text provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Sanitize descriptions before returning (non-persist path)
        for tx in result.transactions:
            tx.description = SanitizerService.sanitize(tx.description)[
                "sanitized_text"
            ]
        if result.account_info.get("bank_name"):
            result.account_info["bank_name"] = SanitizerService.sanitize(
                result.account_info["bank_name"]
            )["sanitized_text"]

        # Optional persistence
        persist = request.data.get("persist", False)
        if isinstance(persist, str):
            persist = persist.lower() in ("true", "1", "yes")

        if persist:
            consent = _get_active_consent(session_id)
            if not consent:
                return Response(
                    {"error": "CONSENT_REQUIRED", "code": "CONSENT_REQUIRED"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            with db_transaction.atomic():
                snapshot, _ = (
                    FinancialSnapshot.objects.select_for_update().get_or_create(
                        session_id=session_id
                    )
                )

                imported = 0
                skipped_dups = 0
                for tx in result.transactions:
                    tx.normalized_merchant = SanitizerService.sanitize(
                        getattr(tx, "normalized_merchant", "")
                        or getattr(tx, "merchant", "")
                        or ""
                    )["sanitized_text"]
                    if getattr(tx, "reference_id", None):
                        tx.reference_id = SanitizerService.sanitize(
                            tx.reference_id
                        )["sanitized_text"]

                    fp = _compute_fingerprint(session_id, tx)

                    if Transaction.objects.filter(
                        session_id=session_id, fingerprint=fp
                    ).exists():
                        skipped_dups += 1
                        continue

                    Transaction.objects.create(
                        snapshot=snapshot,
                        session_id=session_id,
                        transaction_date=tx.transaction_date,
                        amount=tx.amount,
                        transaction_type=tx.transaction_type,
                        normalized_merchant=tx.normalized_merchant,
                        category=getattr(tx, "category", "Uncategorized")
                        or "Uncategorized",
                        is_recurring=getattr(tx, "is_recurring", False),
                        is_leak=getattr(tx, "is_leak", False),
                        hidden_fee_estimate=getattr(
                            tx, "hidden_fee_estimate", 0.0
                        ),
                        risk_note=getattr(tx, "risk_note", ""),
                        fingerprint=fp,
                        source_type=Transaction.SOURCE_IMPORT,
                    )
                    imported += 1

                response_data = result.to_dict()
                response_data["persistence"] = {
                    "imported": imported,
                    "skipped_duplicates": skipped_dups,
                    "session_id": session_id,
                }
                return Response(response_data, status=status.HTTP_200_OK)

        return Response(result.to_dict(), status=status.HTTP_200_OK)


class ParseSmsView(APIView):
    """
    Parses bank & UPI SMS alerts into normalized transactions.
    Rejects OTPs, promotional alerts, and non-transaction messages.
    Priority 6: Always sanitizes echoed SMS text before returning.
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        sms_text = request.data.get("sms_text")
        sms_list = request.data.get("sms_list")

        if sms_text and isinstance(sms_text, str):
            res = BankSmsParser.parse_sms(sms_text)
            sanitized_sms = SanitizerService.sanitize(res.raw_sms)["sanitized_text"]

            if not res.is_valid:
                return Response(
                    {
                        "status": "REJECTED_NON_TRANSACTION",
                        "is_ambiguous": res.is_ambiguous,
                        "reason": res.rejection_reason,
                        "raw_sms": sanitized_sms,
                        "sanitized_sms": sanitized_sms,
                    },
                    status=status.HTTP_200_OK,
                )

            tx = res.transaction
            tx.description = SanitizerService.sanitize(tx.description)[
                "sanitized_text"
            ]
            if getattr(tx, "merchant", None):
                tx.merchant = SanitizerService.sanitize(tx.merchant)[
                    "sanitized_text"
                ]
            if getattr(tx, "reference_id", None):
                tx.reference_id = SanitizerService.sanitize(tx.reference_id)[
                    "sanitized_text"
                ]

            return Response(
                {
                    "status": "PARSED",
                    "transaction": tx.to_dict(),
                    "raw_sms": sanitized_sms,
                    "sanitized_sms": sanitized_sms,
                },
                status=status.HTTP_200_OK,
            )

        elif sms_list and isinstance(sms_list, list):
            if not sms_list:
                return Response(
                    {"error": "sms_list is empty"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            unique_txs, all_results, dups = BankSmsParser.parse_batch(sms_list)
            for tx in unique_txs:
                tx.description = SanitizerService.sanitize(tx.description)[
                    "sanitized_text"
                ]
                if getattr(tx, "merchant", None):
                    tx.merchant = SanitizerService.sanitize(tx.merchant)[
                        "sanitized_text"
                    ]
                if getattr(tx, "reference_id", None):
                    tx.reference_id = SanitizerService.sanitize(tx.reference_id)[
                        "sanitized_text"
                    ]

            ambiguous = [
                {
                    "sms": SanitizerService.sanitize(r.raw_sms)["sanitized_text"],
                    "reason": r.rejection_reason,
                }
                for r in all_results
                if not r.is_valid
            ]
            return Response(
                {
                    "status": "BATCH_PARSED",
                    "total_received": len(sms_list),
                    "valid_transactions_count": len(unique_txs),
                    "duplicates_detected": dups,
                    "transactions": [t.to_dict() for t in unique_txs],
                    "ambiguous_or_rejected": ambiguous,
                },
                status=status.HTTP_200_OK,
            )

        else:
            return Response(
                {
                    "error": "Either 'sms_text' (string) or 'sms_list' (array of strings) is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


# ---------------------------------------------------------------------------
# EMI Simulator
# ---------------------------------------------------------------------------

class SimulateEmiView(APIView):
    """Deterministic EMI reality check: hidden charges and true APR."""
    def post(self, request):
        item_name = str(request.data.get("item_name", "Flagship Smartphone")).strip()
        try:
            price = float(request.data.get("price", 60000))
            tenure = int(request.data.get("tenure_months", 12))
            down_payment = float(request.data.get("down_payment", 0))
            nominal_apr = float(request.data.get("nominal_apr", 0.0))
            monthly_fee = float(request.data.get("monthly_processing_fee", 199.0))
            discretionary_buffer = float(
                request.data.get("discretionary_buffer", 14000.0)
            )
        except (ValueError, TypeError) as e:
            return Response(
                {"error": "Invalid numerical parameters.", "details": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        simulation = AnalyticsEngine.simulate_emi_decision(
            item_name=item_name,
            price=price,
            tenure_months=tenure,
            down_payment=down_payment,
            nominal_annual_interest_rate_pct=nominal_apr,
            monthly_processing_or_conv_fee=monthly_fee,
            user_monthly_discretionary_buffer=discretionary_buffer,
        )

        auth_session, _ = authenticate_request_session(request, required=False)
        target_session = (
            auth_session.session_id if auth_session else "anonymous_simulation"
        )

        DecisionScenario.objects.create(
            session_id=target_session,
            item_name=item_name,
            price=price,
            tenure_months=tenure,
            down_payment=down_payment,
            nominal_apr=nominal_apr,
            true_effective_apr=simulation["true_effective_apr_pct"],
            monthly_outflow=simulation["effective_monthly_outflow"],
            total_hidden_fees=simulation["total_hidden_fees_and_gst"],
            is_viable=simulation["is_viable"],
            verdict=simulation["verdict"],
        )
        return Response(simulation)


# ---------------------------------------------------------------------------
# Consent Management (Phase 1.2 + Phase 3 Hardening)
# ---------------------------------------------------------------------------

class ConsentAuditView(APIView):
    """Logs explicit user consent under DPDP / GDPR standards."""
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        version = request.data.get("consent_version", "v1.0")
        anonymized = request.data.get("anonymized_processing_accepted")
        no_credential = request.data.get("no_credential_disclosure_acknowledged")

        if anonymized is not True or no_credential is not True:
            return Response(
                {"error": "Both consent flags must be explicitly set to true."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        log = ConsentAuditLog.objects.create(
            session_id=session_id,
            consent_version=version,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        return Response(
            {
                "consent_id": str(log.id),
                "status": "CONSENT_REGISTERED",
                "session_id": session_id,
                "timestamp": log.consented_at.isoformat(),
            }
        )


class ConsentWithdrawView(APIView):
    """
    Withdraws the latest active consent for a session.
    Idempotent: safe to call when already withdrawn.
    Historical records are preserved for audit trail.
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        consent = (
            ConsentAuditLog.objects.filter(session_id=session_id, is_active=True)
            .order_by("-consented_at")
            .first()
        )
        if not consent:
            return Response(
                {
                    "status": "ALREADY_WITHDRAWN_OR_NEVER_CONSENTED",
                    "session_id": session_id,
                }
            )

        consent.is_active = False
        consent.withdrawn_at = timezone.now()
        consent.save(update_fields=["is_active", "withdrawn_at"])

        return Response(
            {
                "status": "CONSENT_WITHDRAWN",
                "consent_id": str(consent.id),
                "session_id": session_id,
                "withdrawn_at": consent.withdrawn_at.isoformat(),
            }
        )


class NukeDataView(APIView):
    """
    1-Click Data Shredder: permanently deletes authenticated session data.
    Priority 4 Hardening: Verifies session ownership, removes default session fallback,
    and ensures idempotent safe deletion.
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        deleted_tx, _ = Transaction.objects.filter(session_id=session_id).delete()
        deleted_snap, _ = FinancialSnapshot.objects.filter(session_id=session_id).delete()
        deleted_scen, _ = DecisionScenario.objects.filter(session_id=session_id).delete()
        deleted_cons, _ = ConsentAuditLog.objects.filter(session_id=session_id).delete()

        return Response(
            {
                "status": "HARD_PURGE_SUCCESSFUL",
                "session_id": session_id,
                "records_shredded": deleted_tx + deleted_snap + deleted_scen + deleted_cons,
                "retained_records": "All financial transactions, snapshots, and decision scenarios permanently erased.",
                "message": "All session data permanently erased.",
            }
        )


# ---------------------------------------------------------------------------
# Phase 2: Financial Intelligence Views (Hardened with Auth & Consent)
# ---------------------------------------------------------------------------

class TransactionCategorizationView(APIView):
    """Categorize all normalized transactions for a session into spending categories."""
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        if not _get_active_consent(session_id):
            return Response(
                {
                    "error": "Active user consent is required for financial intelligence analysis.",
                    "code": "CONSENT_REQUIRED",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        include_persona = bool(request.data.get("include_persona", False))
        data = categorize_transactions(session_id, include_persona)
        return Response(
            {"session_id": session_id, "transactions": data, "count": len(data)}
        )


class MonthlyBudgetView(APIView):
    """Monthly income, expenses, savings and category breakdown for a session."""
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        if not _get_active_consent(session_id):
            return Response(
                {
                    "error": "Active user consent is required for financial intelligence analysis.",
                    "code": "CONSENT_REQUIRED",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        year = request.data.get("year")
        month = request.data.get("month")
        include_persona = bool(request.data.get("include_persona", False))
        if not (year and month):
            return Response(
                {"error": "year and month are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            year, month = int(year), int(month)
        except (ValueError, TypeError):
            return Response(
                {"error": "year and month must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = monthly_budget(session_id, year, month, include_persona)
        return Response(data)


class SubscriptionDetectorView(APIView):
    """Identify recurring payments and estimate monthly/yearly subscription costs."""
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        if not _get_active_consent(session_id):
            return Response(
                {
                    "error": "Active user consent is required for financial intelligence analysis.",
                    "code": "CONSENT_REQUIRED",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        include_persona = bool(request.data.get("include_persona", False))
        data = detect_subscriptions(session_id, include_persona)
        return Response(
            {"session_id": session_id, "subscriptions": data, "count": len(data)}
        )


class UnusualSpendingDetectorView(APIView):
    """Flag unusual or duplicate spending. Does NOT label transactions as fraud."""
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        if not _get_active_consent(session_id):
            return Response(
                {
                    "error": "Active user consent is required for financial intelligence analysis.",
                    "code": "CONSENT_REQUIRED",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        include_persona = bool(request.data.get("include_persona", False))
        data = detect_unusual_spending(session_id, include_persona)
        return Response(
            {"session_id": session_id, "flagged": data, "count": len(data)}
        )


class SpendingPatternAnalyzerView(APIView):
    """Month-over-month spending comparison and trend detection."""
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True)
        if err:
            return err
        session_id = auth_session.session_id

        if not _get_active_consent(session_id):
            return Response(
                {
                    "error": "Active user consent is required for financial intelligence analysis.",
                    "code": "CONSENT_REQUIRED",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        months = request.data.get("months", 6)
        include_persona = bool(request.data.get("include_persona", False))
        try:
            months = int(months)
        except (ValueError, TypeError):
            return Response(
                {"error": "months must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = spending_patterns(session_id, months, include_persona)
        return Response(data)
