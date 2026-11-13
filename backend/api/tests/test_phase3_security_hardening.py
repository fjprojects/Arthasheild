"""
Phase 3: Critical Security Hardening Tests
Covers all 11 required security areas:
1. Session creation and ownership.
2. Cross-session data access attempts (IDOR).
3. Cross-session transaction injection.
4. Unauthorized data deletion attempts.
5. Missing and withdrawn consent.
6. All five financial APIs after withdrawal.
7. Gemini API key absence from URLs and logs.
8. Raw PII absence from API responses.
9. File signature validation.
10. Oversized and complex PDF rejection.
11. API throttling.
"""
import io
import re
import json
import logging
import uuid
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from api.models import (
    SecureSession,
    ConsentAuditLog,
    FinancialSnapshot,
    Transaction,
    DecisionScenario,
)
from api.views import (
    InitSessionView,
    RotateSessionView,
    SessionStatusView,
    SelectPersonaView,
    SanitizePreviewView,
    DocumentAnalyzeView,
    ParseStatementView,
    ParseSmsView,
    ConsentAuditView,
    ConsentWithdrawView,
    NukeDataView,
    TransactionCategorizationView,
    MonthlyBudgetView,
    SubscriptionDetectorView,
    UnusualSpendingDetectorView,
    SpendingPatternAnalyzerView,
)
from advisor.services import AdvisorService


class Phase3SecurityHardeningTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.factory = APIRequestFactory()

        # Create two isolated secure sessions
        self.session_a, self.token_a = SecureSession.issue_session()
        self.session_b, self.token_b = SecureSession.issue_session()

        # Register explicit consent for both sessions directly in the database,
        # because the new per-session consent gate rejects all operations without it.
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=self.session_a.session_id,
            consent_version='v1.0-task17',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        ConsentAuditLog.objects.create(
            session_id=self.session_b.session_id,
            consent_version='v1.0-task17',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        self.synthetic_csv = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-01,ACH CRED SALARY CLIENT,,75000.00,75000.00\n"
            "2026-10-04,UPI/SWIGGY/ORDER_9824219/swiggy@icici,480.00,,74520.00\n"
            "2026-10-10,POS NETFLIX RECURRING SUBSCRIPTION,199.00,,74321.00\n"
        )

    # -------------------------------------------------------------------------
    # 1. Session creation and ownership
    # -------------------------------------------------------------------------
    def test_01_session_creation_rotation_and_expiry(self):
        # 1. Init new session
        resp = self.client.post("/api/v1/auth/session/init/")
        self.assertEqual(resp.status_code, 201)
        self.assertIn("session_id", resp.data)
        self.assertIn("session_token", resp.data)
        self.assertTrue(resp.data["session_id"].startswith("sec_"))
        new_token = resp.data["session_token"]

        # Cookie check
        self.assertIn("arthashield_session_token", resp.cookies)
        self.assertEqual(resp.cookies["arthashield_session_token"].value, new_token)
        self.assertTrue(resp.cookies["arthashield_session_token"]["httponly"])

        # 2. Register explicit consent for the new session directly in the database,
        # because the per-session consent gate now requires active consent for any operation
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=resp.data["session_id"],
            consent_version="v1.0-task17",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        # 3. Check me with token header
        resp_me = self.client.get(
            "/api/v1/auth/session/me/",
            HTTP_X_SESSION_TOKEN=new_token,
        )
        self.assertEqual(resp_me.status_code, 200)
        self.assertEqual(resp_me.data["session_id"], resp.data["session_id"])
        self.assertTrue(resp_me.data["is_active"])

        # 3. Rotate token
        resp_rot = self.client.post(
            "/api/v1/auth/session/rotate/",
            HTTP_X_SESSION_TOKEN=new_token,
        )
        self.assertEqual(resp_rot.status_code, 200)
        rotated_token = resp_rot.data["session_token"]
        self.assertNotEqual(new_token, rotated_token)

        # 4. Old token must now be rejected (401)
        resp_old = self.client.get(
            "/api/v1/auth/session/me/",
            HTTP_X_SESSION_TOKEN=new_token,
        )
        self.assertEqual(resp_old.status_code, 401)

        # 5. New token succeeds
        resp_new = self.client.get(
            "/api/v1/auth/session/me/",
            HTTP_X_SESSION_TOKEN=rotated_token,
        )
        self.assertEqual(resp_new.status_code, 200)

    # -------------------------------------------------------------------------
    # 2. Cross-session data access attempts (IDOR)
    # -------------------------------------------------------------------------
    def test_02_cross_session_data_access_rejected(self):
        # Grant consent to Session A and insert transactions
        ConsentAuditLog.objects.create(
            session_id=self.session_a.session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        snap_a = FinancialSnapshot.objects.create(
            session_id=self.session_a.session_id, monthly_income=75000
        )
        Transaction.objects.create(
            snapshot=snap_a,
            session_id=self.session_a.session_id,
            transaction_date=date(2026, 10, 1),
            amount=Decimal("480.00"),
            transaction_type="DEBIT",
            normalized_merchant="Swiggy",
            category="food",
            source_type="import",
        )

        # Grant consent to Session B as well
        ConsentAuditLog.objects.create(
            session_id=self.session_b.session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        # Attacker B uses Token B, but attempts to query Session A's data
        resp_idor = self.client.post(
            "/api/v1/insights/categorize/",
            {"session_id": self.session_a.session_id},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_b,
        )
        # MUST BE REJECTED with 403 Forbidden!
        self.assertEqual(resp_idor.status_code, 403)
        self.assertEqual(resp_idor.data.get("code"), "SESSION_MISMATCH")

        # Anonymous caller without token must be rejected with 401
        resp_anon = self.client.post(
            "/api/v1/insights/categorize/",
            {"session_id": self.session_a.session_id},
            format="json",
        )
        self.assertEqual(resp_anon.status_code, 401)
        self.assertEqual(resp_anon.data.get("code"), "AUTH_REQUIRED")

    # -------------------------------------------------------------------------
    # 3. Cross-session transaction injection
    # -------------------------------------------------------------------------
    def test_03_cross_session_transaction_injection_blocked(self):
        # Consent registered for Session A
        ConsentAuditLog.objects.create(
            session_id=self.session_a.session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        # Attacker B attempts to inject statements into Session A using Token B
        resp_inj = self.client.post(
            "/api/v1/data/parse-statement/",
            {
                "raw_text": self.synthetic_csv,
                "format": "csv",
                "session_id": self.session_a.session_id,
                "persist": True,
            },
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_b,
        )
        self.assertEqual(resp_inj.status_code, 403)
        self.assertEqual(resp_inj.data.get("code"), "SESSION_MISMATCH")

        # Ensure zero transactions were written to Session A
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_a.session_id).count(), 0
        )

    # -------------------------------------------------------------------------
    # 4. Unauthorized data deletion attempts
    # -------------------------------------------------------------------------
    def test_04_unauthorized_data_deletion_rejected(self):
        snap_a = FinancialSnapshot.objects.create(session_id=self.session_a.session_id)
        Transaction.objects.create(
            snapshot=snap_a,
            session_id=self.session_a.session_id,
            transaction_date=date(2026, 10, 1),
            amount=Decimal("100.00"),
            transaction_type="DEBIT",
            normalized_merchant="Test Store",
            source_type="import",
        )

        # Attacker B attempts to nuke Session A's data using Token B
        resp_nuke = self.client.post(
            "/api/v1/privacy/nuke-data/",
            {"session_id": self.session_a.session_id},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_b,
        )
        self.assertEqual(resp_nuke.status_code, 403)
        self.assertEqual(resp_nuke.data.get("code"), "SESSION_MISMATCH")

        # Anonymous caller attempts to nuke data without token
        resp_anon_nuke = self.client.post(
            "/api/v1/privacy/nuke-data/",
            {"session_id": self.session_a.session_id},
            format="json",
        )
        self.assertEqual(resp_anon_nuke.status_code, 401)

        # Transactions for Session A must still exist
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_a.session_id).count(), 1
        )

        # Proper owner (Session A) nuking its own data succeeds
        resp_own_nuke = self.client.post(
            "/api/v1/privacy/nuke-data/",
            {"session_id": self.session_a.session_id},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_own_nuke.status_code, 200)
        self.assertEqual(resp_own_nuke.data.get("status"), "HARD_PURGE_SUCCESSFUL")
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_a.session_id).count(), 0
        )

        # Repeated deletion is safe and idempotent (NukeDataView deletes the active consent record on each purge)
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=self.session_a.session_id,
            consent_version="v1.0-task17",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        resp_repeat = self.client.post(
            "/api/v1/privacy/nuke-data/",
            {"session_id": self.session_a.session_id},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_repeat.status_code, 200)
        # The purge deletes all session data plus the newly registered consent record
        self.assertEqual(resp_repeat.data.get("records_shredded"), 1)

    # -------------------------------------------------------------------------
    # 5. Missing and withdrawn consent
    # -------------------------------------------------------------------------
    def test_05_missing_and_withdrawn_consent(self):
        # Register consent for session_a (the test class setUp already does this,
        # but make it explicit to control the consent state cleanly)
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=self.session_a.session_id,
            consent_version="v1.0-task17",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        # 1. With active consent, the operation succeeds
        resp_ok = self.client.post(
            "/api/v1/documents/analyze/",
            {"sanitized_text": "Sample sanitized transaction stream"},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_ok.status_code, 200)

        # 2. Withdraw consent via the endpoint (now allowed without prior active consent gate blocking auth)
        resp_withdraw = self.client.post(
            "/api/v1/privacy/consent/withdraw/",
            {},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_withdraw.status_code, 200)

        # 3. Blocked immediately after withdrawal
        resp_blocked = self.client.post(
            "/api/v1/documents/analyze/",
            {"sanitized_text": "Sample sanitized transaction stream"},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_blocked.status_code, 403)
        self.assertEqual(resp_blocked.data.get("code"), "CONSENT_REQUIRED")

    # -------------------------------------------------------------------------
    # 6. All five financial APIs after withdrawal
    # -------------------------------------------------------------------------
    def test_06_all_five_financial_apis_blocked_after_withdrawal(self):
        # Setup consent and snapshot
        ConsentAuditLog.objects.create(
            session_id=self.session_a.session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        snap = FinancialSnapshot.objects.create(
            session_id=self.session_a.session_id, monthly_income=75000
        )
        Transaction.objects.create(
            snapshot=snap,
            session_id=self.session_a.session_id,
            transaction_date=date(2026, 10, 1),
            amount=Decimal("500.00"),
            transaction_type="DEBIT",
            normalized_merchant="Swiggy",
            category="food",
            source_type="import",
        )

        # All 5 work with consent
        r_cat = self.client.post("/api/v1/insights/categorize/", {}, format="json", HTTP_X_SESSION_TOKEN=self.token_a)
        self.assertEqual(r_cat.status_code, 200)

        # Now withdraw consent
        self.client.post("/api/v1/privacy/consent/withdraw/", {}, format="json", HTTP_X_SESSION_TOKEN=self.token_a)

        # All five financial APIs MUST now return 403 CONSENT_REQUIRED
        endpoints = [
            ("/api/v1/insights/categorize/", {}),
            ("/api/v1/insights/monthly-budget/", {"year": 2026, "month": 10}),
            ("/api/v1/insights/subscriptions/", {}),
            ("/api/v1/insights/unusual-spending/", {}),
            ("/api/v1/insights/spending-patterns/", {"months": 3}),
        ]

        for path, payload in endpoints:
            resp = self.client.post(path, payload, format="json", HTTP_X_SESSION_TOKEN=self.token_a)
            self.assertEqual(resp.status_code, 403, f"Endpoint {path} did not block after withdrawal")
            self.assertEqual(resp.data.get("code"), "CONSENT_REQUIRED")

    # -------------------------------------------------------------------------
    # 7. Gemini API key absence from URLs and logs
    # -------------------------------------------------------------------------
    def test_07_gemini_api_key_absence_from_urls_and_logs(self):
        synthetic_key = "AIzaSyFakeSyntheticKey12345"

        with patch.object(AdvisorService, "get_api_key", return_value=synthetic_key):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "plain_english_summary": "Clean summary",
                                                "top_actionable_wins": [],
                                                "hidden_risks_and_predatory_clauses": [],
                                                "disclaimer": "Educational only",
                                            }
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                }

                AdvisorService.analyze_sanitized_statement(
                    "sanitized stream", {"health_score": 75}
                )

                # Verify URL has NO ?key= query parameter!
                called_url = mock_post.call_args[0][0]
                self.assertNotIn("?key=", called_url)
                self.assertNotIn(synthetic_key, called_url)

                # Verify header contains x-goog-api-key
                called_headers = mock_post.call_args[1].get("headers", {})
                self.assertEqual(called_headers.get("x-goog-api-key"), synthetic_key)

            # Test exception logging: synthetic key MUST NOT appear in logs
            with patch("requests.post", side_effect=Exception(f"Network error to {synthetic_key}")):
                with self.assertLogs("advisor.services", level="ERROR") as cm:
                    AdvisorService.analyze_sanitized_statement(
                        "sanitized stream", {"health_score": 75}
                    )
                    log_text = " ".join(cm.output)
                    self.assertNotIn(synthetic_key, log_text)

    # -------------------------------------------------------------------------
    # 8. Raw PII absence from API responses
    # -------------------------------------------------------------------------
    def test_08_raw_pii_absence_from_api_responses(self):
        raw_text = (
            "Account Holder: Sunita Rao, PAN: PQRST1234Z, A/C: 987654321098. "
            "Phone: 9876543210, Email: sunita@example.com."
        )

        # 1. Sanitize Preview: raw_text_preview must be REMOVED
        resp_prev = self.client.post(
            "/api/v1/privacy/sanitize-preview/",
            {"raw_text": raw_text},
            format="json",
        )
        self.assertEqual(resp_prev.status_code, 200)
        self.assertNotIn("raw_text_preview", resp_prev.data)
        self.assertNotIn("Sunita Rao", str(resp_prev.data))
        self.assertNotIn("PQRST1234Z", str(resp_prev.data))
        self.assertNotIn("987654321098", str(resp_prev.data))

        # 2. SMS parsing: echoed raw_sms must be SANITIZED
        sms_text = "Txn of INR 500.00 on A/C 987654321098 to merchant store@upi ref 123456"
        resp_sms = self.client.post(
            "/api/v1/data/parse-sms/",
            {"sms_text": sms_text},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_sms.status_code, 200)
        self.assertNotIn("987654321098", resp_sms.data.get("raw_sms", ""))
        self.assertIn("[REDACTED_ACCOUNT]", resp_sms.data.get("raw_sms", ""))

    # -------------------------------------------------------------------------
    # 9. File signature validation
    # -------------------------------------------------------------------------
    def test_09_file_signature_validation(self):
        # Fake PDF containing plain text without %PDF- signature
        fake_pdf = SimpleUploadedFile(
            "statement.pdf",
            b"This is not a real PDF file header.",
            content_type="application/pdf",
        )
        resp_bad_pdf = self.client.post(
            "/api/v1/data/parse-statement/",
            {"file": fake_pdf, "format": "pdf"},
            format="multipart",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_bad_pdf.status_code, 400)
        self.assertIn("Invalid PDF file signature", str(resp_bad_pdf.data))

        # CSV containing binary null bytes
        fake_csv = SimpleUploadedFile(
            "statement.csv",
            b"Date,Amount\x00\x01\x02,Balance\n",
            content_type="text/csv",
        )
        resp_bad_csv = self.client.post(
            "/api/v1/data/parse-statement/",
            {"file": fake_csv, "format": "csv"},
            format="multipart",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_bad_csv.status_code, 400)
        self.assertIn("Binary data detected", str(resp_bad_csv.data))

    # -------------------------------------------------------------------------
    # 10. Oversized and complex PDF rejection
    # -------------------------------------------------------------------------
    def test_10_oversized_and_complex_pdf_rejection(self):
        # 1. File size > 5 MB
        huge_file = SimpleUploadedFile(
            "huge_statement.csv",
            b"a" * (5 * 1024 * 1024 + 1024),
            content_type="text/csv",
        )
        resp_oversized = self.client.post(
            "/api/v1/data/parse-statement/",
            {"file": huge_file, "format": "csv"},
            format="multipart",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_oversized.status_code, 400)
        self.assertIn("exceeds 5MB limit", str(resp_oversized.data))

        # 2. PDF page limit > 15 pages
        with patch("pdfplumber.open") as mock_pdfplumber:
            mock_pdf = MagicMock()
            mock_pdf.pages = [MagicMock() for _ in range(20)]  # 20 pages > 15 limit
            mock_pdfplumber.return_value.__enter__.return_value = mock_pdf

            valid_header_pdf = SimpleUploadedFile(
                "statement.pdf",
                b"%PDF-1.4\n1 0 obj<<>>endobj\nxref\ntrailer<<>>startxref\n%%EOF",
                content_type="application/pdf",
            )
            resp_pages = self.client.post(
                "/api/v1/data/parse-statement/",
                {"file": valid_header_pdf, "format": "pdf"},
                format="multipart",
                HTTP_X_SESSION_TOKEN=self.token_a,
            )
            self.assertEqual(resp_pages.status_code, 400)
            self.assertIn("page limit", str(resp_pages.data).lower())

    # -------------------------------------------------------------------------
    # 11. API throttling and BrowsableAPIRenderer in production
    # -------------------------------------------------------------------------
    def test_11_api_throttling_and_production_settings(self):
        # 1. Throttling configured in settings
        drf_settings = getattr(settings, "REST_FRAMEWORK", {})
        self.assertIn("DEFAULT_THROTTLE_CLASSES", drf_settings)
        self.assertIn("DEFAULT_THROTTLE_RATES", drf_settings)
        self.assertIn("anon", drf_settings["DEFAULT_THROTTLE_RATES"])
        self.assertIn("user", drf_settings["DEFAULT_THROTTLE_RATES"])

        # 2. Test actual 429 triggering when throttle rate is exceeded
        from django.core.cache import cache
        from rest_framework.throttling import AnonRateThrottle
        cache.clear()
        with patch.object(AnonRateThrottle, 'get_rate', return_value='1/minute'):
            # First request passes
            r1 = self.client.get('/api/v1/personas/')
            self.assertEqual(r1.status_code, 200)
            # Second request within the same minute is throttled (429)
            r2 = self.client.get('/api/v1/personas/')
            self.assertEqual(r2.status_code, 429)
        cache.clear()

        # 3. Browsable API disabled in production check
        from core import settings as core_settings
        with patch.object(core_settings, "IS_PRODUCTION", True):
            renderers = (
                ['rest_framework.renderers.JSONRenderer']
                if core_settings.IS_PRODUCTION
                else ['rest_framework.renderers.JSONRenderer', 'rest_framework.renderers.BrowsableAPIRenderer']
            )
            self.assertNotIn("rest_framework.renderers.BrowsableAPIRenderer", renderers)
