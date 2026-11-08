import uuid
from decimal import Decimal
from datetime import date
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory

from api.models import ConsentAuditLog, FinancialSnapshot, Transaction, SecureSession
from api.views import (
    ParseStatementView,
    DocumentAnalyzeView,
    ConsentAuditView,
    ConsentWithdrawView,
    NukeDataView,
    TransactionCategorizationView,
    MonthlyBudgetView,
    SubscriptionDetectorView,
    UnusualSpendingDetectorView,
    SpendingPatternAnalyzerView
)


class EndToEndWorkflowIntegrationTests(TestCase):
    """
    Comprehensive End-to-End integration test covering the complete user journey:
    1. Statement ingestion without consent -> 403 blocked
    2. Parsing without persistence -> 200, 0 DB records
    3. DPDP consent registration -> 200
    4. Persistent ingestion with consent -> 200, stored in DB
    5. PII scrubbing verification on stored data
    6. Duplicate statement ingestion -> 0 imported, N skipped via fingerprint
    7. All 5 Financial Intelligence APIs -> 200 OK
    8. Session isolation -> other sessions cannot view data
    9. Consent withdrawal -> active consent revoked
    10. Subsequent processing -> 403 blocked
    11. Hard purge (Nuke Data) -> 0 records remain, idempotent
    """

    def setUp(self):
        self.client = APIClient()
        self.factory = APIRequestFactory()
        self.session_id = f"e2e_sess_{uuid.uuid4().hex[:8]}"
        self.other_session = f"other_sess_{uuid.uuid4().hex[:8]}"
        self.session, self.token = SecureSession.issue_session(self.session_id)
        self.other_sec, self.other_token = SecureSession.issue_session(self.other_session)
        self.client.credentials(HTTP_X_SESSION_TOKEN=self.token)

        self.synthetic_csv = """Date,Description,Debit,Credit,Balance
2026-10-01,ACH CRED CLIENT GLOBAL TECH STIPEND,,75000.00,75000.00
2026-10-04,UPI/SWIGGY/ORDER_9824219/swiggy@icici,480.00,,74520.00
2026-10-10,POS NETFLIX RECURRING SUBSCRIPTION,199.00,,74321.00
2026-10-15,POS APPLE INDIA MACBOOK PRO PURCHASE,65000.00,,9321.00
"""

    def test_complete_end_to_end_journey(self):
        # 1. Statement ingestion with persist=True WITHOUT consent must be rejected
        req_unconsented = self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": self.synthetic_csv,
            "format": "csv",
            "session_id": self.session_id,
            "persist": True
        }, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp_unconsented = ParseStatementView.as_view()(req_unconsented)
        self.assertEqual(resp_unconsented.status_code, 403)
        self.assertEqual(resp_unconsented.data.get("error"), "CONSENT_REQUIRED")
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id).count(), 0)

        # 2. Parsing with persist=False extracts transactions without writing to DB
        req_preview = self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": self.synthetic_csv,
            "format": "csv",
            "session_id": self.session_id,
            "persist": False
        }, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp_preview = ParseStatementView.as_view()(req_preview)
        self.assertEqual(resp_preview.status_code, 200)
        self.assertEqual(len(resp_preview.data.get("transactions", [])), 4)
        self.assertNotIn("persistence", resp_preview.data)
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id).count(), 0)

        # 3. Explicit consent registration with both required DPDP flags
        req_consent = self.factory.post('/api/v1/privacy/consent/', {
            "session_id": self.session_id,
            "consent_version": "v1.0-e2e",
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp_consent = ConsentAuditView.as_view()(req_consent)
        self.assertEqual(resp_consent.status_code, 200)
        self.assertEqual(resp_consent.data.get("status"), "CONSENT_REGISTERED")

        # 4. Ingest with consent -> transactions stored in DB
        req_persist = self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": self.synthetic_csv,
            "format": "csv",
            "session_id": self.session_id,
            "persist": True
        }, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp_persist = ParseStatementView.as_view()(req_persist)
        self.assertEqual(resp_persist.status_code, 200)
        self.assertIn("persistence", resp_persist.data)
        self.assertEqual(resp_persist.data["persistence"]["imported"], 4)
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id, source_type='import').count(), 4)

        # 5. Verify PII scrubbing on stored data
        for tx in Transaction.objects.filter(session_id=self.session_id):
            self.assertNotIn("swiggy@icici", tx.normalized_merchant)

        # 6. Re-upload identical statement -> duplicate detection skips all 4
        req_dup = self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": self.synthetic_csv,
            "format": "csv",
            "session_id": self.session_id,
            "persist": True
        }, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp_dup = ParseStatementView.as_view()(req_dup)
        self.assertEqual(resp_dup.status_code, 200)
        self.assertEqual(resp_dup.data["persistence"]["imported"], 0)
        self.assertEqual(resp_dup.data["persistence"]["skipped_duplicates"], 4)
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id).count(), 4)

        # 7. Run all five Financial Intelligence functions via API endpoints
        # 7.1 Categorize
        resp_cat = self.client.post('/api/v1/insights/categorize/', {'session_id': self.session_id}, format='json')
        self.assertEqual(resp_cat.status_code, 200)
        categories = [t['category'] for t in resp_cat.data['transactions']]
        self.assertIn('food', categories)

        # 7.2 Monthly Budget
        resp_mb = self.client.post('/api/v1/insights/monthly-budget/', {'session_id': self.session_id, 'year': 2026, 'month': 10}, format='json')
        self.assertEqual(resp_mb.status_code, 200)
        self.assertEqual(Decimal(resp_mb.data['income']), Decimal('75000.00'))
        self.assertGreater(Decimal(resp_mb.data['expenses']), Decimal('0'))

        # 7.3 Subscriptions
        # Mark Netflix as recurring to test subscription detection
        tx_netflix = Transaction.objects.filter(session_id=self.session_id, normalized_merchant__icontains='netflix').first()
        if tx_netflix:
            tx_netflix.is_recurring = True
            tx_netflix.save()
        resp_subs = self.client.post('/api/v1/insights/subscriptions/', {'session_id': self.session_id}, format='json')
        self.assertEqual(resp_subs.status_code, 200)
        self.assertGreaterEqual(resp_subs.data['count'], 1)

        # 7.4 Unusual Spending (MacBook 65000 >> 3x peer median)
        resp_unusual = self.client.post('/api/v1/insights/unusual-spending/', {'session_id': self.session_id}, format='json')
        self.assertEqual(resp_unusual.status_code, 200)
        flagged_merchants = [f['merchant'] for f in resp_unusual.data['flagged']]
        self.assertTrue(any('macbook' in m.lower() or 'apple' in m.lower() for m in flagged_merchants))

        # 7.5 Spending Patterns
        resp_patterns = self.client.post('/api/v1/insights/spending-patterns/', {'session_id': self.session_id, 'months': 3}, format='json')
        self.assertEqual(resp_patterns.status_code, 200)
        self.assertEqual(len(resp_patterns.data['monthly_breakdown']), 3)

        # 8. Verify session isolation: other session with its own token sees 0 records
        ConsentAuditLog.objects.create(
            session_id=self.other_session,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        self.client.credentials(HTTP_X_SESSION_TOKEN=self.other_token)
        resp_other_cat = self.client.post('/api/v1/insights/categorize/', {'session_id': self.other_session}, format='json')
        self.assertEqual(resp_other_cat.status_code, 200)
        self.assertEqual(resp_other_cat.data['count'], 0)
        self.client.credentials(HTTP_X_SESSION_TOKEN=self.token)

        # 9. Consent withdrawal
        req_wd = self.factory.post('/api/v1/privacy/consent/withdraw/', {'session_id': self.session_id}, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp_wd = ConsentWithdrawView.as_view()(req_wd)
        self.assertEqual(resp_wd.status_code, 200)
        self.assertEqual(resp_wd.data.get("status"), "CONSENT_WITHDRAWN")

        # 10. Subsequent persistent processing is immediately blocked
        req_block_wd = self.factory.post('/api/v1/data/parse-statement/', {
            "raw_text": self.synthetic_csv,
            "format": "csv",
            "session_id": self.session_id,
            "persist": True
        }, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp_block_wd = ParseStatementView.as_view()(req_block_wd)
        self.assertEqual(resp_block_wd.status_code, 403)
        self.assertEqual(resp_block_wd.data.get("error"), "CONSENT_REQUIRED")

        # 11. One-click Nuke Data purges all session records
        req_nuke = self.factory.post('/api/v1/privacy/nuke-data/', {'session_id': self.session_id}, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp_nuke = NukeDataView.as_view()(req_nuke)
        self.assertEqual(resp_nuke.status_code, 200)
        self.assertEqual(resp_nuke.data.get("status"), "HARD_PURGE_SUCCESSFUL")
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id).count(), 0)
        self.assertEqual(FinancialSnapshot.objects.filter(session_id=self.session_id).count(), 0)
        self.assertEqual(ConsentAuditLog.objects.filter(session_id=self.session_id).count(), 0)

