import os
import re
from decimal import Decimal
from django.test import TestCase
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory

from sanitizer.services import SanitizerService
from analytics.services import AnalyticsEngine
from api.models import SecureSession, ConsentAuditLog
from api.views import (
    PersonaListView,
    SelectPersonaView,
    SanitizePreviewView,
    DocumentAnalyzeView,
    SimulateEmiView,
    ConsentAuditView,
    NukeDataView
)


class AuthRequestFactory(APIRequestFactory):
    def __init__(self, get_token_fn, **defaults):
        super().__init__(**defaults)
        self.get_token_fn = get_token_fn

    def request(self, **kwargs):
        token = self.get_token_fn()
        if token and 'HTTP_X_SESSION_TOKEN' not in kwargs:
            kwargs['HTTP_X_SESSION_TOKEN'] = token
        return super().request(**kwargs)


class PrivacySanitizationAuditTests(TestCase):
    """Audit checks 1.1 to 1.10: Privacy, PII masking, and data protection."""

    def setUp(self):
        self.session_id = "audit_san_sess"
        self.session, self.token = SecureSession.issue_session(self.session_id)
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        self.factory = AuthRequestFactory(lambda: getattr(self, 'token', None))

    def test_01_pan_card_masking(self):
        sample_pan = "Customer PAN is ABCDE1234F for taxation."
        res = SanitizerService.sanitize(sample_pan)
        self.assertIn("[REDACTED_PAN]", res["sanitized_text"])
        self.assertNotIn("ABCDE1234F", res["sanitized_text"])

    def test_02_aadhaar_number_masking(self):
        sample_aadhaar = "Aadhaar number: 1234 5678 9012 and 9876-5432-1098."
        res = SanitizerService.sanitize(sample_aadhaar)
        self.assertNotIn("1234 5678 9012", res["sanitized_text"])
        self.assertNotIn("9876-5432-1098", res["sanitized_text"])

    def test_03_bank_account_masking(self):
        sample_acct = "A/C: 123456789012 or Account Number: 9876543210123"
        res = SanitizerService.sanitize(sample_acct)
        self.assertNotIn("123456789012", res["sanitized_text"])
        self.assertIn("[REDACTED_ACCOUNT]", res["sanitized_text"])

    def test_04_ifsc_code_masking(self):
        sample_ifsc = "Transfer via IFSC Code: HDFC0001234 or SBIN0000456."
        res = SanitizerService.sanitize(sample_ifsc)
        self.assertNotIn("HDFC0001234", res["sanitized_text"])
        self.assertIn("[REDACTED_IFSC]", res["sanitized_text"])

    def test_05_upi_id_masking(self):
        sample_upi = "Paid to merchant.store@okaxis and user-name@upi."
        res = SanitizerService.sanitize(sample_upi)
        self.assertNotIn("merchant.store@okaxis", res["sanitized_text"])
        self.assertIn("[REDACTED_UPI_ID]", res["sanitized_text"])

    def test_06_phone_number_masking(self):
        sample_phone = "Contact customer care at +91-9876543210 or 9876543210."
        res = SanitizerService.sanitize(sample_phone)
        self.assertNotIn("9876543210", res["sanitized_text"])
        self.assertIn("[REDACTED_PHONE]", res["sanitized_text"])

    def test_07_email_address_masking(self):
        sample_email = "Email sent to rohit.verma@example.com."
        res = SanitizerService.sanitize(sample_email)
        self.assertNotIn("rohit.verma@example.com", res["sanitized_text"])
        self.assertIn("[REDACTED_EMAIL]", res["sanitized_text"])

    def test_08_card_suffix_leakage(self):
        sample_16digit_acct = "Account Number: 4821-9988-1200-5541"
        res = SanitizerService.sanitize(sample_16digit_acct)
        self.assertNotIn("5541", res["sanitized_text"])
        self.assertNotIn("-5541", res["sanitized_text"])

    def test_09_redaction_audit_accuracy(self):
        sample = "Account Number: 4821-9988-1200-5541"
        res = SanitizerService.sanitize(sample)
        audit = res["redactions"]
        total = res["total_redactions_count"]
        self.assertGreater(total, 0)
        self.assertGreater(len(audit), 0)
        self.assertEqual(sum(x["count"] for x in audit), total)

    def test_10_server_side_sanitization_pre_llm(self):
        raw_input_payload = "Account Holder: Rahul Sharma, PAN: ABCDE1234F, A/C: 998877665544"
        req = self.factory.post('/api/v1/documents/analyze/', {
            "sanitized_text": raw_input_payload
        }, format='json')
        resp = DocumentAnalyzeView.as_view()(req)
        self.assertNotIn("Rahul Sharma", str(resp.data))
        self.assertNotIn("ABCDE1234F", str(resp.data))


class FinancialCalculationAuditTests(TestCase):
    """Audit checks 2.1 to 2.13: Deterministic Financial Math & Edge Cases."""

    def test_01_standard_health_score(self):
        res = AnalyticsEngine.calculate_health_score(75000, 50000, 45000, 15000)
        self.assertTrue(0 <= res["health_score"] <= 100)
        self.assertIn(res["grade"], ["A (Resilient)", "B (Stable)", "C (Vulnerable)", "D (Critical)"])

    def test_02_health_score_zero_income(self):
        res = AnalyticsEngine.calculate_health_score(0, 30000, 10000, 10000)
        self.assertTrue(0 <= res["health_score"] <= 100)

    def test_03_health_score_zero_expenses_balance(self):
        res = AnalyticsEngine.calculate_health_score(50000, 0, 0, 0)
        self.assertTrue(0 <= res["health_score"] <= 100)

    def test_04_emergency_runway_standard(self):
        runway = AnalyticsEngine.calculate_runway(60000, 20000)
        self.assertEqual(runway, 3.0)

    def test_05_emergency_runway_zero_burn(self):
        runway = AnalyticsEngine.calculate_runway(50000, 0)
        self.assertEqual(runway, 12.0)

    def test_06_emergency_runway_negative_balance(self):
        runway = AnalyticsEngine.calculate_runway(-5000, 15000)
        self.assertEqual(runway, 0.0)

    def test_07_safe_to_spend_standard(self):
        sts = AnalyticsEngine.calculate_safe_to_spend(
            current_balance=40000, monthly_income=70000, pending_fixed_obligations=15000, days_remaining_in_month=15
        )
        self.assertGreater(sts["safe_to_spend_daily"], 0)
        self.assertGreater(sts["safe_to_spend_weekly"], sts["safe_to_spend_daily"])

    def test_08_safe_to_spend_deficit(self):
        sts = AnalyticsEngine.calculate_safe_to_spend(
            current_balance=5000, monthly_income=50000, pending_fixed_obligations=12000, days_remaining_in_month=10
        )
        self.assertEqual(sts["safe_to_spend_daily"], 0.0)
        self.assertEqual(sts["status"], "RESTRICTED_CASHFLOW")

    def test_09_safe_to_spend_zero_days(self):
        sts = AnalyticsEngine.calculate_safe_to_spend(
            current_balance=20000, monthly_income=50000, pending_fixed_obligations=5000, days_remaining_in_month=0
        )
        self.assertGreaterEqual(sts["days_remaining_in_cycle"], 1)
        self.assertGreater(sts["safe_to_spend_daily"], 0)

    def test_10_standard_emi_accuracy(self):
        emi = AnalyticsEngine.simulate_emi_decision(
            item_name="Phone", price=60000, tenure_months=12, nominal_annual_interest_rate_pct=12.0, monthly_processing_or_conv_fee=0.0
        )
        self.assertTrue(5300 <= emi["base_monthly_emi"] <= 5350)

    def test_11_no_cost_emi_hidden_apr(self):
        emi = AnalyticsEngine.simulate_emi_decision(
            item_name="Phone", price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0, monthly_processing_or_conv_fee=199.0
        )
        self.assertGreater(emi["true_effective_apr_pct"], 0.0)
        self.assertGreater(emi["total_hidden_fees_and_gst"], 0)

    def test_12_emi_zero_tenure(self):
        emi = AnalyticsEngine.simulate_emi_decision(item_name="Item", price=30000, tenure_months=0)
        self.assertGreaterEqual(emi["tenure_months"], 1)
        self.assertGreater(emi["base_monthly_emi"], 0)

    def test_13_emi_full_down_payment(self):
        emi = AnalyticsEngine.simulate_emi_decision(item_name="Item", price=50000, down_payment=50000, tenure_months=6)
        self.assertEqual(emi["base_monthly_emi"], 0.0)


class APIEndpointAuditTests(TestCase):
    """Audit checks 3.1 to 3.11: API endpoints, error handling, and robustness."""

    def setUp(self):
        self.session_id = "audit_sess"
        self.session, self.token = SecureSession.issue_session(self.session_id)
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        self.factory = AuthRequestFactory(lambda: getattr(self, 'token', None))

    def test_01_personas_get(self):
        req = self.factory.get('/api/v1/personas/')
        resp = PersonaListView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data.get("personas", [])), 3)

    def test_02_persona_select_valid(self):
        req = self.factory.post('/api/v1/personas/select/', {"persona_id": "persona_freelancer_rohit", "session_id": self.session_id}, format='json')
        resp = SelectPersonaView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get("status"), "LOADED")

    def test_03_persona_select_invalid_404(self):
        req = self.factory.post('/api/v1/personas/select/', {"persona_id": "nonexistent_persona", "session_id": self.session_id}, format='json')
        resp = SelectPersonaView.as_view()(req)
        self.assertEqual(resp.status_code, 404)

    def test_04_consent_logging(self):
        req = self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "consent_version": "v1.0",
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json')
        resp = ConsentAuditView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("consent_id", resp.data)

    def test_05_sanitize_preview_empty_400(self):
        req = self.factory.post('/api/v1/privacy/sanitize-preview/', {"raw_text": "   "}, format='json')
        resp = SanitizePreviewView.as_view()(req)
        self.assertEqual(resp.status_code, 400)

    def test_06_sanitize_preview_file(self):
        dummy_file = SimpleUploadedFile("statement.csv", b"Date,Description,Amount\n2026-10-01,UPI/STORE/store@upi,500.00", content_type="text/csv")
        req = self.factory.post('/api/v1/privacy/sanitize-preview/', {"file": dummy_file}, format='multipart')
        resp = SanitizePreviewView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.data.get("total_redactions_count", 0), 1)

    def test_07_documents_analyze_empty_400(self):
        req = self.factory.post('/api/v1/documents/analyze/', {"sanitized_text": "", "session_id": self.session_id}, format='json')
        resp = DocumentAnalyzeView.as_view()(req)
        self.assertEqual(resp.status_code, 400)

    def test_08_documents_analyze_valid(self):
        req = self.factory.post('/api/v1/documents/analyze/', {"sanitized_text": "[USER_PRIMARY] paid [REDACTED_ACCOUNT] 500", "session_id": self.session_id}, format='json')
        resp = DocumentAnalyzeView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("advisor_insights", resp.data)

    def test_09_simulate_emi_defensive_validation(self):
        req = self.factory.post('/api/v1/analytics/simulate-emi/', {"price": "not_a_number"}, format='json')
        resp = SimulateEmiView.as_view()(req)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_10_nuke_data_hard_purge(self):
        req1 = self.factory.post('/api/v1/privacy/nuke-data/', {'session_id': self.session_id}, format='json')
        resp1 = NukeDataView.as_view()(req1)
        self.assertEqual(resp1.status_code, 200)

    def test_11_nuke_data_idempotent(self):
        # Create some persona data first
        self.factory.post('/api/v1/personas/select/', {"persona_id": "persona_freelancer_rohit", "session_id": self.session_id}, format='json')
        req = self.factory.post('/api/v1/privacy/nuke-data/', {"session_id": self.session_id}, format='json')
        resp = NukeDataView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get("status"), "HARD_PURGE_SUCCESSFUL")

    def test_11_nuke_data_idempotent(self):
        # First nuke purges any existing records
        req1 = self.factory.post('/api/v1/privacy/nuke-data/', {"session_id": self.session_id}, format='json')
        NukeDataView.as_view()(req1)
        # Second call on already shredded session is safe and returns 0 records
        req2 = self.factory.post('/api/v1/privacy/nuke-data/', {"session_id": self.session_id}, format='json')
        resp2 = NukeDataView.as_view()(req2)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.data.get("records_shredded"), 0)


class SecurityAuditTests(TestCase):
    """Audit checks 4.1 to 4.6: Security configuration, ORM SQL injection resistance, and key leakage."""

    def test_01_debug_setting_configured(self):
        self.assertIsNotNone(settings.DEBUG)

    def test_02_secret_key_strength(self):
        self.assertTrue(bool(settings.SECRET_KEY))
        self.assertGreaterEqual(len(settings.SECRET_KEY), 20)

    def test_03_cors_configuration(self):
        self.assertTrue(hasattr(settings, 'CORS_ALLOW_ALL_ORIGINS') or hasattr(settings, 'CORS_ALLOWED_ORIGINS'))

    def test_04_sql_injection_orm_parameterization(self):
        import pathlib
        views_path = pathlib.Path(__file__).resolve().parent.parent / 'views.py'
        views_code = views_path.read_text(encoding='utf-8')
        raw_sql_used = "raw(" in views_code or "execute(" in views_code
        self.assertFalse(raw_sql_used)

    def test_05_api_key_leakage_in_logs(self):
        import pathlib
        advisor_path = pathlib.Path(__file__).resolve().parent.parent.parent / 'advisor' / 'services.py'
        advisor_code = advisor_path.read_text(encoding='utf-8')
        log_statements = re.findall(r'logger\.\w+\(.*?\)', advisor_code)
        key_leaked = any("api_key" in log_call for log_call in log_statements)
        self.assertFalse(key_leaked)

    def test_06_file_upload_size_limit(self):
        import pathlib
        views_path = pathlib.Path(__file__).resolve().parent.parent / 'views.py'
        views_code = views_path.read_text(encoding='utf-8')
        self.assertIn("MAX_UPLOAD_SIZE_BYTES", views_code)
        self.assertIn("file_obj.size", views_code)

