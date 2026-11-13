import uuid
from decimal import Decimal
from datetime import date
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from api.models import ConsentAuditLog, FinancialSnapshot, Transaction, SecureSession
from api.views import (
    ConsentAuditView,
    ConsentWithdrawView,
    DocumentAnalyzeView,
    ParseStatementView,
    SelectPersonaView,
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


class ConsentEnforcementAndWithdrawalTests(TestCase):
    """Phase 1.1, 1.2, 1.2.1: Consent registration, strict validation, withdrawal, and audit history."""

    def setUp(self):
        self.session_id = f"test_consent_sess_{uuid.uuid4().hex[:8]}"
        self.session, self.token = SecureSession.issue_session(self.session_id)
        self.factory = AuthRequestFactory(lambda: getattr(self, 'token', None))

    def test_01_consent_requires_both_explicit_flags(self):
        # Missing or False flags must be rejected with 400
        req = self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "consent_version": "v1.0",
            "anonymized_processing_accepted": False,
            "no_credential_disclosure_acknowledged": True
        }, format='json')
        resp = ConsentAuditView.as_view()(req)
        self.assertEqual(resp.status_code, 400)

        # Both True accepted
        req_valid = self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "consent_version": "v1.0",
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json')
        resp_valid = ConsentAuditView.as_view()(req_valid)
        self.assertEqual(resp_valid.status_code, 200)
        self.assertIn("consent_id", resp_valid.data)

    def test_02_consent_withdrawal_deactivates_latest_consent(self):
        # Register consent
        req_reg = self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "consent_version": "v1.0",
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json')
        ConsentAuditView.as_view()(req_reg)

        # Withdraw consent
        req_wd = self.factory.post('/api/v1/privacy/consent/withdraw/', {
            "session_id": self.session_id
        }, format='json')
        resp_wd = ConsentWithdrawView.as_view()(req_wd)
        self.assertEqual(resp_wd.status_code, 200)
        self.assertEqual(resp_wd.data.get("status"), "CONSENT_WITHDRAWN")

        # Verify DB status
        log = ConsentAuditLog.objects.filter(session_id=self.session_id).order_by('-consented_at').first()
        self.assertFalse(log.is_active)
        self.assertIsNotNone(log.withdrawn_at)

    def test_03_withdrawn_consent_blocks_document_analysis(self):
        # Register consent
        self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json')
        ConsentAuditView.as_view()(self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json'))

        # Withdraw consent
        ConsentWithdrawView.as_view()(self.factory.post('/api/v1/privacy/consent/withdraw/', {
            "session_id": self.session_id
        }, format='json'))

        # Analysis with enforce_consent should return 403
        req = self.factory.post('/api/v1/documents/analyze/', {
            "sanitized_text": "Sample text",
            "session_id": self.session_id,
            "enforce_consent": True
        }, format='json')
        resp = DocumentAnalyzeView.as_view()(req)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data.get("code"), "CONSENT_REQUIRED")

    def test_04_historical_consent_preserved_after_withdrawal(self):
        # Create 2 consent records then withdraw
        for v in ["v1.0", "v1.1"]:
            ConsentAuditView.as_view()(self.factory.post('/api/v1/privacy/consent/', {
                "session_id": self.session_id,
                "consent_version": v,
                "anonymized_processing_accepted": True,
                "no_credential_disclosure_acknowledged": True
            }, format='json'))

        ConsentWithdrawView.as_view()(self.factory.post('/api/v1/privacy/consent/withdraw/', {
            "session_id": self.session_id
        }, format='json'))

        # Audit trail must be preserved
        logs = ConsentAuditLog.objects.filter(session_id=self.session_id)
        self.assertEqual(logs.count(), 2)

    def test_05_re_consent_restores_authorized_processing(self):
        # Consent -> Withdraw -> Re-consent
        self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json')
        ConsentAuditView.as_view()(self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json'))
        ConsentWithdrawView.as_view()(self.factory.post('/api/v1/privacy/consent/withdraw/', {
            "session_id": self.session_id
        }, format='json'))

        # Re-consent
        ConsentAuditView.as_view()(self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "consent_version": "v2.0",
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json'))

        # Analysis now succeeds
        req = self.factory.post('/api/v1/documents/analyze/', {
            "sanitized_text": "Clean transaction text",
            "session_id": self.session_id,
            "enforce_consent": True
        }, format='json')
        resp = DocumentAnalyzeView.as_view()(req)
        self.assertEqual(resp.status_code, 200)


class TransactionPersistenceAndIntegrityTests(TestCase):
    """Phase 1.1, 1.2: Transaction persistence, fingerprint deduplication, and persona isolation."""

    def setUp(self):
        self.session_id = f"test_tx_sess_{uuid.uuid4().hex[:8]}"
        self.session, self.token = SecureSession.issue_session(self.session_id)
        self.factory = AuthRequestFactory(lambda: getattr(self, 'token', None))

    def test_06_persist_false_by_default(self):
        csv_text = "Date,Description,Debit,Credit,Balance\n2026-10-04,UPI/SWIGGY,480.00,,40320.00\n"
        req = self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": csv_text,
            "format": "csv",
            "session_id": self.session_id
        }, format='json')
        resp = ParseStatementView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("persistence", resp.data)
        # Verify 0 DB records written
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id).count(), 0)

    def test_07_persist_true_requires_consent(self):
        csv_text = "Date,Description,Debit,Credit,Balance\n2026-10-04,UPI/SWIGGY,480.00,,40320.00\n"
        req = self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": csv_text,
            "format": "csv",
            "session_id": self.session_id,
            "persist": True
        }, format='json')
        resp = ParseStatementView.as_view()(req)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data.get("error"), "CONSENT_REQUIRED")

    def test_08_persist_true_stores_with_active_consent(self):
        # Register consent directly in the database (the consent endpoint is now gated)
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version="v1.0-task17",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        csv_text = "Date,Description,Debit,Credit,Balance\n2026-10-04,UPI/SWIGGY,480.00,,40320.00\n"
        req = self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": csv_text,
            "format": "csv",
            "session_id": self.session_id,
            "persist": True
        }, format='json')
        resp = ParseStatementView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("persistence", resp.data)
        self.assertEqual(resp.data["persistence"]["imported"], 1)
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id, source_type='import').count(), 1)

    def test_09_fingerprint_prevents_duplicate_import(self):
        # Register consent directly in the database (consent endpoint is gated by session auth flow)
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version="v1.0-task17",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        csv_text = "Date,Description,Debit,Credit,Balance\n2026-10-04,UPI/SWIGGY,480.00,,40320.00\n"
        # First import
        ParseStatementView.as_view()(self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": csv_text, "format": "csv", "session_id": self.session_id, "persist": True
        }, format='json'))

        # Second import with identical statement
        resp2 = ParseStatementView.as_view()(self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": csv_text, "format": "csv", "session_id": self.session_id, "persist": True
        }, format='json'))

        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.data["persistence"]["imported"], 0)
        self.assertEqual(resp2.data["persistence"]["skipped_duplicates"], 1)
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id).count(), 1)

    def test_10_persona_selection_preserves_imported_transactions(self):
        # Register consent directly in the database (the consent endpoint is now gated)
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version="v1.0-task17",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        csv_text = "Date,Description,Debit,Credit,Balance\n2026-10-04,UPI/SWIGGY,480.00,,40320.00\n"
        ParseStatementView.as_view()(self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": csv_text, "format": "csv", "session_id": self.session_id, "persist": True
        }, format='json'))

        # Select synthetic persona Rohit
        req_persona = self.factory.post('/api/v1/personas/select/', {
            "persona_id": "persona_freelancer_rohit",
            "session_id": self.session_id
        }, format='json')
        resp_persona = SelectPersonaView.as_view()(req_persona)
        self.assertEqual(resp_persona.status_code, 200)

        # Real imported transaction must NOT have been deleted
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id, source_type='import').count(), 1)
        # Persona transactions loaded separately
        self.assertGreater(Transaction.objects.filter(session_id=self.session_id, source_type='persona').count(), 0)

    def test_11_string_boolean_persist_parsing(self):
        # String 'false' must evaluate strictly to False
        req = self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": "Date,Description,Debit\n2026-10-04,SWIGGY,480.00\n",
            "format": "csv",
            "session_id": self.session_id,
            "persist": "false"
        }, format='json')
        resp = ParseStatementView.as_view()(req)
        self.assertNotIn("persistence", resp.data)
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id).count(), 0)

    def test_12_nuke_data_session_isolation(self):
        other_session = f"other_sess_{uuid.uuid4().hex[:8]}"
        snap1 = FinancialSnapshot.objects.create(session_id=self.session_id)
        snap2 = FinancialSnapshot.objects.create(session_id=other_session)
        Transaction.objects.create(snapshot=snap1, session_id=self.session_id, normalized_merchant='Test1', amount=Decimal('100.00'), transaction_type='DEBIT', transaction_date=date(2026, 10, 1))
        Transaction.objects.create(snapshot=snap2, session_id=other_session, normalized_merchant='Test2', amount=Decimal('200.00'), transaction_type='DEBIT', transaction_date=date(2026, 10, 1))

        # Register consent for the session directly in the database
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version="v1.0-task17",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        # Nuke session 1
        req = self.factory.post('/api/v1/privacy/nuke-data/', {"session_id": self.session_id}, format='json')
        # Authenticate the request as the current session so the consent gate passes
        req.auth_session = self.session
        req.auth_session_id = self.session_id
        NukeDataView.as_view()(req)

        # Session 1 wiped, Session 2 untouched
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id).count(), 0)
        self.assertEqual(Transaction.objects.filter(session_id=other_session).count(), 1)

    def test_13_stored_merchant_sanitized(self):
        # Register consent directly in the database
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version="v1.0-task17",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        # Import transaction with raw account number in description
        csv_text = "Date,Description,Debit,Credit,Balance\n2026-10-04,UPI/SWIGGY/ORDER_rohit@okaxis,480.00,,40320.00\n"
        ParseStatementView.as_view()(self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": csv_text, "format": "csv", "session_id": self.session_id, "persist": True
        }, format='json'))

        tx = Transaction.objects.filter(session_id=self.session_id, source_type='import').first()
        self.assertNotIn("rohit@okaxis", tx.normalized_merchant)
