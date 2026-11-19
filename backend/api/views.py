"""
ArthaShield API Views
Phase 1 + 1.1 + 1.2 + 1.2.1 + Phase 2 (Financial Intelligence) + Phase 3 (Security Hardening)
"""
import json
import math
import os
import hashlib
import tempfile
import logging
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
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
from .security import (
    authenticate_request_session,
    extract_explicit_session_token,
)
from sanitizer.services import SanitizerService
from analytics.services import AnalyticsEngine, _parse_date
from analytics.stress_test import run_commitment_stress_test
from advisor.services import AdvisorService
from data_processor.statement_parser import (
    BankStatementParser,
    MAX_FILE_SIZE_BYTES,
    MAX_PDF_PAGES,
)
from data_processor.sms_parser import BankSmsParser
from data_processor.normalizer import TransactionNormalizer
from data_processor.transfers import transfer_identity
from .insights import (
    _safe_counterparty_label,
    categorize_transactions,
    classify_credit,
    classify_debit,
    monthly_budget,
    detect_subscriptions,
    detect_unusual_spending,
    spending_patterns,
    compute_imported_session_overview,
    compute_dataset_financial_metrics,
    generate_evidence_briefing,
)
from .response_safety import (
    PERSON_PLACEHOLDER,
    display_mask_breakdown,
    safe_error_message,
    safe_free_text,
    safe_statement_payload,
    safe_transaction_payload,
)

logger = logging.getLogger(__name__)

SYNTHETIC_DATA_PATH = Path(settings.BASE_DIR).parent / "synthetic_data" / "personas.json"
MAX_UPLOAD_SIZE_BYTES = MAX_FILE_SIZE_BYTES  # 5 MB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_request_bool(value) -> bool:
    """Parse a client-provided boolean without treating "false" as True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "persona", "demo"}
    return False


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


def _compute_fingerprint(session_id: str, tx, occurrence_index: int = 0) -> str:
    """
    Deterministic SHA-256 fingerprint for cross-import duplicate detection.
    Uses sanitized canonical fields only. Never stores raw PII.

    Reliability rules:
    - When a transaction reference (UTR / order / reference id) is present, it is part
      of the hash, so the fingerprint identifies that specific imported transaction.
    - When no reference exists, the fingerprint is content-based only and therefore
      CANNOT distinguish a re-import from a second legitimate identical payment.
      ``occurrence_index`` is the row's ordinal among identical content rows inside the
      same imported statement. Two identical payments in one statement receive
      ordinals 0 and 1 (both preserved), while re-importing that same statement
      reproduces the same ordinals (both skipped as duplicates).

    See api.insights.DEDUPLICATION_POLICY for the documented residual ambiguity across
    different statements.
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
    if occurrence_index:
        # Appending only for later occurrences keeps every pre-existing fingerprint
        # (all of which used ordinal 0) stable across this correction.
        source = f"{source}|occ={occurrence_index}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _is_duplicate_import(session_id: str, tx, fingerprint: str, occurrence_index: int = 0) -> bool:
    """
    True when the incoming transaction is already stored for this session.

    Ordinary transactions are matched by their fingerprint alone. The fingerprint
    carries the sanitized merchant, the date, the amount, the direction and the
    reference, plus an occurrence ordinal for identical rows, so merchant
    identity is never globally ignored.

    Task 22 - backward compatibility for own-account transfers: a statement
    imported by an older build stored the transfer merchant in its legacy form
    (``Self``), while the current build stores the canonical label
    (``Self Transfer``). Both denote the same movement, so the legacy row is
    matched through the transfer identity instead of creating a duplicate.

    The compatibility path is deliberately narrow: it only applies to a
    confirmed own-account transfer, and only to stored rows with the same
    session, date, amount and direction. Two different own-account movements
    (``Self`` versus ``Self Ac``) keep different identities and are therefore
    never collapsed, and identical rows stay distinct through the occurrence
    ordinal.
    """
    if Transaction.objects.filter(
        session_id=session_id, fingerprint=fingerprint
    ).exists():
        return True

    identity = transfer_identity(
        str(getattr(tx, "normalized_merchant", "") or getattr(tx, "merchant", "") or "")
    )
    if not identity:
        return False

    candidates = Transaction.objects.filter(
        session_id=session_id,
        transaction_date=tx.transaction_date,
        amount=tx.amount,
        transaction_type=tx.transaction_type,
    )
    identical = sum(
        1
        for candidate in candidates
        if transfer_identity(candidate.normalized_merchant) == identity
    )
    # The occurrence ordinal keeps identical rows of the same statement apart.
    return identical > occurrence_index


# ---------------------------------------------------------------------------
# Phase 3: Secure Session Identity Views
# ---------------------------------------------------------------------------

class InitSessionView(APIView):
    """
    Issues a cryptographically unpredictable session identity and secret token.
    Binds all subsequent financial operations to this verified session.

    Idempotent bootstrap: when the request already presents a valid, unexpired
    session credential, that session is resumed - the same identity and the same
    secret are returned - instead of creating a competing session. A client
    that retries its bootstrap therefore cannot fork its session, and the
    session keeps its data. An unauthenticated request still creates a brand new
    session.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        presented_token = extract_explicit_session_token(request)
        session = None
        if presented_token:
            candidate = SecureSession.objects.filter(
                token_hash=SecureSession.hash_token(presented_token),
                is_revoked=False,
            ).first()
            if candidate and not candidate.is_expired:
                session = candidate

        if session is not None:
            # Resume: the identity (and its data) are preserved and the client
            # keeps the credential it already presented.
            raw_token = presented_token
            response_status = status.HTTP_200_OK
        else:
            session, raw_token = SecureSession.issue_session()
            response_status = status.HTTP_201_CREATED

        response = Response(
            {
                "status": "SESSION_INITIALIZED",
                "session_id": session.session_id,
                "session_token": raw_token,
                "expires_at": session.expires_at.isoformat(),
                "resumed": session is not None and response_status == status.HTTP_200_OK,
            },
            status=response_status,
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
        auth_session, err = authenticate_request_session(request, required=True, require_consent=False)
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
# Only the fields the dashboard renders are exposed. Persona transactions carry safe
# display labels instead of their raw synthetic narration, so phone-bearing UPI
# descriptions never leave the server.

def _persona_account_summary(account):
    account = account or {}
    return {
        "bank_name": account.get("bank_name"),
        "masked_account_number": account.get("masked_account_number"),
        "current_balance": account.get("current_balance"),
        "calculated_runway_months": account.get("calculated_runway_months"),
    }


def _persona_leaks_summary(summary):
    summary = summary or {}
    subscriptions = []
    for item in summary.get("dormant_subscriptions") or []:
        subscriptions.append(
            {
                "service": item.get("service"),
                "monthly_cost": item.get("monthly_cost"),
                "status": item.get("status"),
                "recommendation": item.get("recommendation"),
            }
        )
    return {
        "total_monthly_leakage": summary.get("total_monthly_leakage"),
        "items_count": summary.get("items_count"),
        "dormant_subscriptions": subscriptions,
    }


def _persona_summary(persona):
    return {
        "id": persona.get("id"),
        "name": persona.get("name"),
        "profile": persona.get("profile"),
        "currency": persona.get("currency"),
        "currency_symbol": persona.get("currency_symbol"),
        "monthly_average_income": persona.get("monthly_average_income"),
        "account_summary": _persona_account_summary(persona.get("account_summary")),
        "detected_leaks_summary": _persona_leaks_summary(
            persona.get("detected_leaks_summary")
        ),
    }


def _persona_transaction(tx):
    tx = tx or {}
    return {
        "id": tx.get("id"),
        "date": tx.get("date"),
        "description": _safe_counterparty_label(tx.get("description", "")),
        "amount": tx.get("amount"),
        "type": tx.get("type"),
        "category": tx.get("category", "General"),
        "is_recurring": bool(tx.get("is_recurring", False)),
        "leak_flag": bool(tx.get("leak_flag", False)),
        "hidden_fee": tx.get("hidden_fee", 0),
    }


def _persona_detail(persona):
    payload = _persona_summary(persona)
    payload["transactions"] = [
        _persona_transaction(tx) for tx in (persona.get("transactions") or [])
    ]
    return payload


class PersonaListView(APIView):
    """Returns available synthetic personas for instant judging/testing."""
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        if not SYNTHETIC_DATA_PATH.exists():
            return Response(
                {"error": "Synthetic data not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        with open(SYNTHETIC_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Response(
            {"personas": [_persona_summary(p) for p in data.get("personas", [])]}
        )


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
                "persona": _persona_detail(target),
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
    authentication_classes = []
    permission_classes = []

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
        # The preview keeps the sanitizer placeholders (so the redaction audit
        # stays readable), but a personal name in a person context, a
        # transaction reference and a masked account token are masked as well:
        # the preview is echoed back to the client and is forwarded to the
        # advisor, so it must carry no personal identifier.
        preview = safe_free_text(result["sanitized_text"])
        breakdown = display_mask_breakdown(result["sanitized_text"], preview)
        redactions = list(result["redactions"])
        for entry in (
            {
                "type": "PERSON_NAME",
                "placeholder": PERSON_PLACEHOLDER,
                "count": breakdown["person_names"],
                "description": "Masked personal names in the response preview",
            },
            {
                "type": "TRANSACTION_REFERENCE",
                "placeholder": "[REDACTED_REFERENCE]",
                "count": breakdown["references"],
                "description": "Masked transaction/order references in the response preview",
            },
            {
                "type": "MASKED_ACCOUNT_TOKEN",
                "placeholder": "[REDACTED_ACCOUNT]",
                "count": breakdown["masked_account_tokens"],
                "description": "Masked account number tokens in the response preview",
            },
            {
                "type": "ONE_TIME_PASSWORD",
                "placeholder": "[REDACTED_OTP]",
                "count": breakdown["credentials"],
                "description": "Masked one-time passwords / PINs in the response preview",
            },
        ):
            if entry["count"]:
                redactions.append(entry)
        return Response(
            {
                "sanitized_text_preview": preview[:3000],
                "redactions_audit": redactions,
                "total_redactions_count": result["total_redactions_count"]
                + sum(breakdown.values()),
                "sanitized_length": len(preview),
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

        # Defense-in-depth: re-sanitize on server side. The response boundary
        # additionally masks personal names and transaction references, so a
        # personal identifier cannot leave the host towards the advisor.
        server_sanitized = safe_free_text(
            SanitizerService.sanitize(sanitized_text)["sanitized_text"]
        )

        # Dataset provenance: the caller declares the active dataset. It is
        # validated against the session ledger, and metrics are derived from
        # that dataset only. A persona-created snapshot is never substituted
        # for an imported-statement analysis.
        include_persona = _parse_request_bool(request.data.get("include_persona", False))
        dataset_metrics = compute_dataset_financial_metrics(session_id, include_persona)
        has_persona_rows = Transaction.objects.filter(
            session_id=session_id, source_type=Transaction.SOURCE_PERSONA
        ).exists()
        has_imported_rows = Transaction.objects.filter(
            session_id=session_id, source_type=Transaction.SOURCE_IMPORT
        ).exists()
        requested_dataset_has_rows = (
            has_persona_rows if include_persona else has_imported_rows
        )
        snapshot = (
            FinancialSnapshot.objects.filter(session_id=session_id)
            .order_by('-created_at')
            .first()
        )

        use_dataset_metrics = (
            dataset_metrics.get('status') == 'AVAILABLE' and requested_dataset_has_rows
        )
        # Legacy snapshots remain readable only for import-mode sessions that
        # have never loaded persona data. Once persona rows exist, their
        # snapshot values are scenario estimates and must not be presented as
        # real imported-statement metrics.
        use_legacy_snapshot = (
            not include_persona
            and not has_persona_rows
            and has_imported_rows
            and snapshot is not None
        )

        metrics = {}
        if use_legacy_snapshot:
            recurring = detect_subscriptions(session_id, include_persona=False)
            metrics = {
                "data_source": "IMPORTED_STATEMENT",
                "dataset_status": "IMPORTED_LEGACY_SNAPSHOT",
                "reporting_period": None,
                "health_score": snapshot.health_score,
                "health_grade": snapshot.health_grade,
                "emergency_runway_months": snapshot.emergency_runway_months,
                "runway_status": "LEGACY_SNAPSHOT_ESTIMATE",
                "balance_source": "LEGACY_SNAPSHOT",
                "monthly_income": float(snapshot.monthly_income),
                "monthly_expenses": float(snapshot.monthly_expenses),
                "monthly_leakage": float(snapshot.monthly_leakage_detected),
                "safe_to_spend_daily": float(snapshot.safe_to_spend_daily),
                "metric_basis": {
                    "income": "SESSION_SNAPSHOT",
                    "expenses": "SESSION_SNAPSHOT",
                    "recurring": "EVIDENCE_BASED_DETECTION",
                    "runway": "SESSION_SNAPSHOT_ESTIMATE",
                },
                "recurring_commitments": {
                    "monthly_commitments": float(sum(
                        Decimal(str(entry.get("estimated_monthly_cost") or 0))
                        for entry in recurring
                        if entry.get("is_financial_commitment")
                    )),
                    "monthly_leakage": float(sum(
                        Decimal(str(entry.get("estimated_monthly_cost") or 0))
                        for entry in recurring
                        if entry.get("is_potential_leakage")
                    )),
                    "confirmed_commitment_count": sum(
                        1 for entry in recurring if entry.get("is_financial_commitment")
                    ),
                    "recurring_pattern_count": sum(
                        1 for entry in recurring if not entry.get("is_financial_commitment")
                    ),
                },
                "dataset_metrics": dataset_metrics,
            }
        elif use_dataset_metrics:
            metrics = {
                "data_source": dataset_metrics['data_source'],
                "dataset_status": dataset_metrics['status'],
                "reporting_period": dataset_metrics.get('reporting_period'),
                "monthly_income": dataset_metrics['monthly_income'],
                "monthly_expenses": dataset_metrics['monthly_expenses'],
                "health_score": dataset_metrics.get('health_score'),
                "health_grade": dataset_metrics.get('health_grade'),
                "emergency_runway_months": dataset_metrics.get('emergency_runway_months'),
                "runway_status": dataset_metrics.get('runway_status'),
                "balance_source": dataset_metrics.get('balance_source'),
                "metric_basis": dataset_metrics.get('metric_basis'),
                "recurring_commitments": dataset_metrics['recurring_commitments'],
                "dataset_metrics": dataset_metrics,
            }
        else:
            metrics = {
                "data_source": dataset_metrics['data_source'],
                "dataset_status": "INSUFFICIENT_DATA",
                "insufficient_reason": dataset_metrics.get('insufficient_reason', 'SELECTED_DATASET_UNAVAILABLE'),
                "requested_dataset_has_rows": requested_dataset_has_rows,
                "recurring_commitments": dataset_metrics['recurring_commitments'],
                "metric_basis": dataset_metrics.get('metric_basis'),
                "dataset_metrics": dataset_metrics,
            }

        advisor_insights = AdvisorService.analyze_sanitized_statement(
            server_sanitized, metrics
        )
        is_live = advisor_insights.get("source") == "LIVE_GEMINI"
        analysis_source = advisor_insights.get("source", "OFFLINE_RULE_BASED")
        engine_label = advisor_insights.get(
            "engine_label",
            "Live Gemini AI Analysis" if is_live else "Offline Rule-Based Financial Insights",
        )
        return Response(
            {
                "metrics": metrics,
                "advisor_insights": advisor_insights,
                "analysis_source": analysis_source,
                "is_ai_generated": is_live,
                "engine_label": engine_label,
                "gemini_available": is_live,
                "privacy_guarantee": (
                    "Sanitized payload processed via Gemini API over TLS. Zero credentials stored."
                    if is_live
                    else "Sanitized financial payload analyzed strictly offline via local deterministic logic. Zero external egress."
                ),
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
        auth_session, err = authenticate_request_session(request, required=True, require_consent=False)
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
                # Controlled validation message: no row content, no traceback.
                return Response(
                    {"error": safe_error_message(ve, "Unable to parse the statement file.")},
                    status=status.HTTP_400_BAD_REQUEST,
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
                # Controlled validation message: no row content, no traceback.
                return Response(
                    {"error": safe_error_message(ve, "Unable to parse the statement text.")},
                    status=status.HTTP_400_BAD_REQUEST,
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

        # Build the safe response payload from the raw parse result, before the
        # in-place sanitization below replaces the narration. The payload keeps
        # every financial fact but never carries the original narration, a
        # personal name or a transaction reference.
        response_payload = safe_statement_payload(result)

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
                # Ordinal of each reference-less content identity inside this statement.
                # Lets two legitimate identical payments coexist while a re-import of
                # the same statement still produces matching fingerprints.
                occurrence_counts = {}
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

                    occurrence_index = 0
                    if not str(getattr(tx, "reference_id", "") or "").strip():
                        identity_key = (
                            tx.transaction_date,
                            tx.amount,
                            tx.transaction_type,
                            tx.normalized_merchant,
                        )
                        occurrence_index = occurrence_counts.get(identity_key, 0)
                        occurrence_counts[identity_key] = occurrence_index + 1

                    fp = _compute_fingerprint(session_id, tx, occurrence_index)

                    if _is_duplicate_import(session_id, tx, fp, occurrence_index):
                        skipped_dups += 1
                        continue

                    # Auto-categorize using the classification engine
                    _tx_cat = getattr(tx, "category", "Uncategorized") or "Uncategorized"
                    if _tx_cat.lower() in ("uncategorized", "general", ""):
                        if tx.transaction_type == "CREDIT":
                            _tx_cat = classify_credit(tx.normalized_merchant)["category"]
                        else:
                            _tx_cat = classify_debit(tx.normalized_merchant)["category"]

                    Transaction.objects.create(
                        snapshot=snapshot,
                        session_id=session_id,
                        transaction_date=tx.transaction_date,
                        amount=tx.amount,
                        transaction_type=tx.transaction_type,
                        normalized_merchant=tx.normalized_merchant,
                        category=_tx_cat,
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

                response_data = response_payload
                response_data["persistence"] = {
                    "imported": imported,
                    "skipped_duplicates": skipped_dups,
                    "session_id": session_id,
                }
                return Response(response_data, status=status.HTTP_200_OK)

        return Response(response_payload, status=status.HTTP_200_OK)


class ParseSmsView(APIView):
    """
    Parses bank & UPI SMS alerts into normalized transactions.
    Rejects OTPs, promotional alerts, and non-transaction messages.
    Priority 6: Always sanitizes echoed SMS text before returning.
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True, require_consent=False)
        if err:
            return err
        session_id = auth_session.session_id

        sms_text = request.data.get("sms_text")
        sms_list = request.data.get("sms_list")

        if sms_text and isinstance(sms_text, str):
            try:
                res = BankSmsParser.parse_sms(sms_text)
            except Exception as exc:
                # An unexpected parser failure must never surface its message:
                # the exception text can quote the message content. Only the
                # exception type is logged.
                logger.warning('SMS parsing failed (%s).', type(exc).__name__)
                return Response(
                    {"error": "Unable to parse the SMS message."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            sanitized_sms = safe_free_text(res.raw_sms)

            if not res.is_valid:
                return Response(
                    {
                        "status": "REJECTED_NON_TRANSACTION",
                        "is_ambiguous": res.is_ambiguous,
                        "reason": safe_error_message(
                            res.rejection_reason,
                            "The message was not recognized as a transaction.",
                        ),
                        "raw_sms": sanitized_sms,
                        "sanitized_sms": sanitized_sms,
                    },
                    status=status.HTTP_200_OK,
                )

            tx = res.transaction
            return Response(
                {
                    "status": "PARSED",
                    "transaction": safe_transaction_payload(tx),
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

            unique_txs, all_results, dups = None, None, 0
            try:
                unique_txs, all_results, dups = BankSmsParser.parse_batch(sms_list)
            except Exception as exc:
                logger.warning('SMS batch parsing failed (%s).', type(exc).__name__)
                return Response(
                    {"error": "Unable to parse the SMS messages."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            ambiguous = [
                {
                    "sms": safe_free_text(r.raw_sms),
                    "reason": safe_error_message(
                        r.rejection_reason,
                        "The message was not recognized as a transaction.",
                    ),
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
                    "transactions": [safe_transaction_payload(t) for t in unique_txs],
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
    """Deterministic EMI reality check using dated borrower cash flows (XIRR)."""
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
            upfront_fee = float(request.data.get("upfront_processing_fee", 0.0))
            gst_rate_pct = float(request.data.get("gst_rate_pct", 18.0))
        except (ValueError, TypeError) as e:
            return Response(
                {"error": "Invalid numerical parameters.", "details": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        numeric_inputs = {
            "price": price,
            "tenure_months": tenure,
            "down_payment": down_payment,
            "nominal_apr": nominal_apr,
            "monthly_processing_fee": monthly_fee,
            "discretionary_buffer": discretionary_buffer,
            "upfront_processing_fee": upfront_fee,
            "gst_rate_pct": gst_rate_pct,
        }
        non_finite = [
            name for name, value in numeric_inputs.items() if not math.isfinite(value)
        ]
        if non_finite:
            return Response(
                {
                    "error": "Non-finite numerical parameters are not allowed.",
                    "fields": non_finite,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        start_date = _parse_date(request.data.get("start_date"))
        first_payment_date = _parse_date(request.data.get("first_payment_date"))
        if request.data.get("start_date") and start_date is None:
            return Response(
                {"error": "Invalid 'start_date'. Expected an ISO date (YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if request.data.get("first_payment_date") and first_payment_date is None:
            return Response(
                {"error": "Invalid 'first_payment_date'. Expected an ISO date (YYYY-MM-DD)."},
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
            upfront_processing_fee=upfront_fee,
            gst_rate_pct=gst_rate_pct,
            start_date=start_date,
            first_payment_date=first_payment_date,
        )

        auth_session, _ = authenticate_request_session(request, required=False)
        target_session = (
            auth_session.session_id if auth_session else "anonymous_simulation"
        )

        # The persisted APR mirrors the API exactly: a genuine computed value
        # (including a genuine 0.0 for a zero-cost loan) is stored as-is, while
        # an unavailable / not-applicable calculation is stored as NULL with
        # the matching status label, so NULL can never be read as "0%".
        recorded_apr = simulation["true_effective_apr_pct"]
        recorded_status = simulation["apr_calculation"]["status"]
        DecisionScenario.objects.create(
            session_id=target_session,
            item_name=item_name,
            price=price,
            tenure_months=tenure,
            down_payment=down_payment,
            nominal_apr=nominal_apr,
            true_effective_apr=recorded_apr,
            apr_status=recorded_status,
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
        auth_session, err = authenticate_request_session(request, required=True, require_consent=False)
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
        auth_session, err = authenticate_request_session(request, required=True, require_consent=False)
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
        auth_session, err = authenticate_request_session(request, required=True, require_consent=False)
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

        # The stored narration is required by categorization and classification, but it
        # is not a display value. Serialize a safe label at the response boundary while
        # keeping raw narration and every classification field untouched internally.
        public_transactions = [
            {**row, "merchant": _safe_counterparty_label(row.get("merchant", ""))}
            for row in data
        ]
        return Response(
            {
                "session_id": session_id,
                "transactions": public_transactions,
                "count": len(public_transactions),
            }
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

        as_of_date_raw = request.data.get("as_of_date")
        as_of_date = None
        if as_of_date_raw:
            try:
                as_of_date = datetime.strptime(str(as_of_date_raw)[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                as_of_date = None

        include_persona = bool(request.data.get("include_persona", False))
        data = detect_subscriptions(session_id, include_persona=include_persona, as_of_date=as_of_date)

        confirmed_monthly = Decimal("0")
        confirmed_annual = Decimal("0")
        probable_monthly = Decimal("0")
        probable_annual = Decimal("0")
        discretionary_leakage_monthly = Decimal("0")
        essential_commitments_monthly = Decimal("0")
        weak_count = 0

        for s in data:
            conf = s.get("confidence")
            ptype = s.get("payment_type", "")
            m_cost = Decimal(s["estimated_monthly_cost"]) if s.get("estimated_monthly_cost") is not None else Decimal("0")
            a_cost = Decimal(s["estimated_annual_cost"]) if s.get("estimated_annual_cost") is not None else Decimal("0")

            if conf == "CONFIRMED":
                confirmed_monthly += m_cost
                confirmed_annual += a_cost
                if ptype in ("subscription", "other_recurring_payment"):
                    discretionary_leakage_monthly += m_cost
                elif ptype in ("rent", "emi_or_loan", "utility", "insurance"):
                    essential_commitments_monthly += m_cost
            elif conf == "PROBABLE":
                probable_monthly += m_cost
                probable_annual += a_cost
            elif conf == "WEAK":
                weak_count += 1

        confirmed_monthly_str = str(confirmed_monthly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        confirmed_annual_str = str(confirmed_annual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        probable_monthly_str = str(probable_monthly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        probable_annual_str = str(probable_annual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        discretionary_str = str(discretionary_leakage_monthly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        essential_str = str(essential_commitments_monthly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        # Internal clustering keys are used only to group recurring merchants on the
        # server. The browser consumes the safe display label, so the raw key is not
        # serialized.
        public_subscriptions = [
            {key: value for key, value in sub.items() if key != "canonical_merchant"}
            for sub in data
        ]

        return Response(
            {
                "session_id": session_id,
                "subscriptions": public_subscriptions,
                "count": len(data),
                "total_monthly_commitment": confirmed_monthly_str,
                "total_annual_commitment": confirmed_annual_str,
                "confirmed_monthly_commitment": confirmed_monthly_str,
                "confirmed_annual_commitment": confirmed_annual_str,
                "probable_monthly_commitment": probable_monthly_str,
                "probable_annual_commitment": probable_annual_str,
                "discretionary_leakage_monthly": discretionary_str,
                "essential_commitments_monthly": essential_str,
                "weak_under_observation_count": weak_count,
            }
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

        # Detection uses the stored narration, but the response is display data. Apply
        # the shared safe-label boundary so arbitrary narration never reaches a client.
        public_flagged = [
            {**row, "merchant": _safe_counterparty_label(row.get("merchant", ""))}
            for row in data
        ]
        return Response(
            {
                "session_id": session_id,
                "flagged": public_flagged,
                "count": len(public_flagged),
            }
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


class ImportedSessionOverviewView(APIView):
    """
    Task 17: Snapshot/overview computed strictly from imported statement
    transactions (source_type='import') for the authenticated session.

    Deterministic math only: statement period, busiest reporting month,
    monthly budget, health metrics and safe-to-spend status. Safe-to-spend
    is withheld (INSUFFICIENT_DATA) unless a liquid balance is known,
    because parsed statements carry no verified current balance. Persona
    transactions are never merged into this overview.
    """
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

        data = compute_imported_session_overview(session_id)

        # Same safe-label boundary as the categorization and unusual-spending
        # views: internal rows carry display labels, but the response boundary
        # re-applies the strict counterparty label so narration-derived names
        # are never serialized.
        public_transactions = [
            {
                **row,
                "merchant": _safe_counterparty_label(row.get("merchant", "")),
                "description": _safe_counterparty_label(row.get("description", "")),
            }
            for row in data.get("transactions", [])
        ]
        data["transactions"] = public_transactions
        return Response(data)


class EvidenceBriefingView(APIView):
    """
    Evidence-Based Financial Insights Briefing.

    Synthesises all existing financial intelligence into a structured briefing
    where every insight is backed by deterministic calculations. The AI layer
    may explain results but never invents financial figures.

    POST /api/v1/insights/evidence-briefing/
    Body: { "session_id": "...", "include_persona": false }
    """
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

        include_persona = request.data.get('include_persona', False)
        data = generate_evidence_briefing(session_id, include_persona)

        # Apply safe counterparty labels to any merchant names in insight evidence
        for insight in data.get('insights', []):
            evidence = insight.get('evidence', {})
            if 'merchant' in evidence:
                evidence['merchant'] = _safe_counterparty_label(evidence['merchant'])
            # Sanitise nested commitment/leak details
            for key in ('top_commitments', 'flagged_payments', 'examples'):
                for item in evidence.get(key, []):
                    if 'merchant' in item:
                        item['merchant'] = _safe_counterparty_label(item['merchant'])

        return Response(data)

class CommitmentStressTestView(APIView):
    """
    Commitment Stress Test & Judgment Flip Engine Endpoint.
    Deterministic multi-scenario evaluation (Buy Now vs EMI vs Wait).
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True, require_consent=False)
        if err:
            return err
        session_id = auth_session.session_id

        item_name = str(request.data.get("item_name", "Proposed Purchase")).strip()
        try:
            price = float(request.data.get("price", 65000.0))
            down_payment = float(request.data.get("down_payment", 0.0))
            tenure_months = int(request.data.get("tenure_months", 12))
            nominal_apr = float(request.data.get("nominal_apr", 0.0))
            monthly_fee = float(request.data.get("monthly_processing_fee", 199.0))
            upfront_fee = float(request.data.get("upfront_processing_fee", 0.0))
            gst_rate_pct = float(request.data.get("gst_rate_pct", 18.0))
            delay_days = int(request.data.get("delay_days", 0))
            discretionary_reduction_pct = float(request.data.get("discretionary_reduction_pct", 0.0))
            custom_liquid_balance = (
                float(request.data["custom_liquid_balance"])
                if "custom_liquid_balance" in request.data and request.data["custom_liquid_balance"] is not None
                else None
            )
        except (ValueError, TypeError) as e:
            return Response(
                {"error": "Invalid numerical parameters.", "details": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        commitment_type = str(request.data.get("commitment_type", "no_cost_emi")).strip().lower()
        include_persona = bool(request.data.get("include_persona", False))

        try:
            result = run_commitment_stress_test(
                session_id=session_id,
                item_name=item_name,
                price=price,
                commitment_type=commitment_type,
                down_payment=down_payment,
                tenure_months=tenure_months,
                nominal_apr=nominal_apr,
                monthly_processing_fee=monthly_fee,
                upfront_processing_fee=upfront_fee,
                gst_rate_pct=gst_rate_pct,
                delay_days=delay_days,
                discretionary_reduction_pct=discretionary_reduction_pct,
                custom_liquid_balance=custom_liquid_balance,
                include_persona=include_persona,
            )
        except Exception:
            # An internal failure is a computation error, never a SAFE verdict.
            logger.exception("Commitment stress test computation failed for session %s", session_id)
            return Response(
                {
                    "error": "The stress test could not be computed for this session.",
                    "code": "STRESS_TEST_COMPUTATION_ERROR",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(result, status=status.HTTP_200_OK)


class CommitmentStressTestExplainView(APIView):
    """
    AI Semantic Explanation for Commitment Stress Test & Judgment Flip.
    Strictly verifies that all cited evidence transaction IDs exist in the active session.
    Falls back gracefully to deterministic rule-based output when Gemini is unavailable.
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True, require_consent=False)
        if err:
            return err
        session_id = auth_session.session_id

        decision_packet = request.data.get("decision_packet")
        if not isinstance(decision_packet, dict):
            return Response(
                {"error": "decision_packet must be a valid JSON object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Gather authentic session transaction IDs for strict validation
        valid_session_tx_ids = set(
            str(t.id) for t in Transaction.objects.filter(session_id=session_id)
        )

        explanation = AdvisorService.explain_commitment_stress_test(
            decision_packet=decision_packet,
            valid_session_tx_ids=valid_session_tx_ids,
        )

        return Response(explanation, status=status.HTTP_200_OK)


class TransactionCorrectionView(APIView):
    """
    Human Correction of Uncertain Transactions.
    Allows user to reclassify an expense as an internal account transfer or adjust category.
    Strictly verifies session ownership to prevent cross-session tamper.
    """
    def post(self, request):
        auth_session, err = authenticate_request_session(request, required=True, require_consent=False)
        if err:
            return err
        session_id = auth_session.session_id

        tx_id = request.data.get("transaction_id")
        if not tx_id:
            return Response(
                {"error": "transaction_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cross-session isolation check
        try:
            tx = Transaction.objects.get(id=tx_id, session_id=session_id)
        except (Transaction.DoesNotExist, ValueError):
            return Response(
                {"error": "Transaction not found or not owned by active session.", "code": "TX_NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_transfer = request.data.get("is_transfer")
        new_category = request.data.get("new_category")
        user_note = request.data.get("notes", "").strip()

        old_category = tx.category
        updated = False

        if is_transfer is True:
            tx.category = "transfer"
            tx.is_recurring = False
            tx.risk_note = f"[USER_CORRECTION] Marked as internal own-account transfer. {user_note}".strip()
            updated = True
        elif new_category and isinstance(new_category, str):
            clean_cat = new_category.strip().title()
            tx.category = clean_cat
            tx.risk_note = f"[USER_CORRECTION] Category updated from {old_category} to {clean_cat}. {user_note}".strip()
            updated = True

        if updated:
            tx.save()

        return Response(
            {
                "status": "CORRECTION_SAVED",
                "transaction_id": str(tx.id),
                "previous_category": old_category,
                "current_category": tx.category,
                "is_transfer": tx.category.lower() == "transfer",
                "risk_note": tx.risk_note,
            },
            status=status.HTTP_200_OK,
        )
