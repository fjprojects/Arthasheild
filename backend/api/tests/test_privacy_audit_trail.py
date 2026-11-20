"""
Tests for PrivacyAuditTrailView: session-scoped DPDP audit trail endpoint.

Phase 5 requirements:
- Strictly session-scoped, read-only.
- Authorization: requires authenticated session.
- Session isolation: Session A cannot access Session B events.
- Genuine events only: session init, consent granted, consent withdrawn, statement imported.
- Safe serialization: No raw transaction narration, no personal identifiers.
Synthetic data only.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction


class PrivacyAuditTrailTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Session A
        self.session_a, self.token_a = SecureSession.issue_session("test_audit_session_a")
        # Session B
        self.session_b, self.token_b = SecureSession.issue_session("test_audit_session_b")

    def test_unauthenticated_request_is_rejected(self):
        resp = self.client.get("/api/v1/privacy/audit-trail/")
        self.assertEqual(resp.status_code, 401)

    def test_session_isolation(self):
        """Events recorded in session A are invisible to session B."""
        ConsentAuditLog.objects.create(
            session_id=self.session_a.session_id,
            consent_version="v1.0-alpha",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        resp_b = self.client.get(
            "/api/v1/privacy/audit-trail/",
            HTTP_X_SESSION_TOKEN=self.token_b,
        )
        self.assertEqual(resp_b.status_code, 200)
        self.assertEqual(resp_b.data["session_id"], self.session_b.session_id)
        # Session B only has its own SESSION_INITIALIZED event
        event_types = [ev["event_type"] for ev in resp_b.data["events"]]
        self.assertNotIn("CONSENT_REGISTERED", event_types)
        self.assertFalse(resp_b.data["active_consent"])

        resp_a = self.client.get(
            "/api/v1/privacy/audit-trail/",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp_a.status_code, 200)
        self.assertTrue(resp_a.data["active_consent"])
        a_event_types = [ev["event_type"] for ev in resp_a.data["events"]]
        self.assertIn("SESSION_INITIALIZED", a_event_types)
        self.assertIn("CONSENT_REGISTERED", a_event_types)

    def test_consent_withdrawal_event_reflected(self):
        log = ConsentAuditLog.objects.create(
            session_id=self.session_a.session_id,
            consent_version="v1.0-alpha",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        # Withdraw consent
        self.client.post(
            "/api/v1/privacy/consent/withdraw/",
            {},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )

        resp = self.client.get(
            "/api/v1/privacy/audit-trail/",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp.status_code, 200)
        event_types = [ev["event_type"] for ev in resp.data["events"]]
        self.assertIn("CONSENT_WITHDRAWN", event_types)
        self.assertFalse(resp.data["active_consent"])

    def test_statement_imported_event_reflected_safely(self):
        """Imported statement appears as a structured event without raw narration."""
        snap, _ = FinancialSnapshot.objects.get_or_create(session_id=self.session_a.session_id)
        Transaction.objects.create(
            snapshot=snap,
            session_id=self.session_a.session_id,
            transaction_date=date(2026, 11, 1),
            amount=Decimal("1200"),
            transaction_type="DEBIT",
            normalized_merchant="Amazon Shopping",
            category="Shopping",
            source_type="import",
            fingerprint="abc123hash",
        )

        resp = self.client.get(
            "/api/v1/privacy/audit-trail/",
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(resp.status_code, 200)
        import_events = [ev for ev in resp.data["events"] if ev["event_type"] == "STATEMENT_IMPORTED"]
        self.assertEqual(len(import_events), 1)
        # Verify safe serialization: metadata contains count, not raw narration
        self.assertEqual(import_events[0]["metadata"]["transaction_count"], 1)
        self.assertNotIn("raw_text", str(resp.data))
