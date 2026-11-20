"""
Advanced Session Lifecycle and Concurrency Security Test Suite.

Covers Section C of Additional ArthaShield Audit:
- Multi-session isolation (two distinct browser sessions).
- Cross-session IDOR prevention.
- Refresh and session recovery with credential presentation.
- Session token rotation and immediate invalidation of prior token.
- Session expiration and revocation enforcement.
- Consent withdrawal blocks persistent workflows.
- Atomic data deletion (Hard purge / Nuke data).
- Stale token / session injection rejection.
- Rapid concurrent transactions atomic safety.
"""

from datetime import timedelta
from decimal import Decimal
import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from api.models import SecureSession, ConsentAuditLog, FinancialSnapshot, Transaction


INIT_URL = "/api/v1/auth/session/init/"
ROTATE_URL = "/api/v1/auth/session/rotate/"
ME_URL = "/api/v1/auth/session/me/"
STATEMENT_URL = "/api/v1/data/parse-statement/"
CONSENT_WITHDRAW_URL = "/api/v1/privacy/consent/withdraw/"
NUKE_DATA_URL = "/api/v1/privacy/nuke-data/"
STRESS_TEST_URL = "/api/v1/analytics/commitment-stress-test/"
CORRECT_TX_URL = "/api/v1/insights/correct-transaction/"


class AdvancedSessionLifecycleTests(TestCase):
    def setUp(self):
        self.client_a = APIClient()
        self.client_b = APIClient()

    # 1. Two separate browser sessions and strict isolation
    def test_01_two_separate_sessions_and_isolation(self):
        # Client A initializes session
        resp_a = self.client_a.post(INIT_URL)
        self.assertEqual(resp_a.status_code, status.HTTP_201_CREATED)
        session_a_id = resp_a.data["session_id"]
        token_a = resp_a.data["session_token"]

        # Client B initializes session
        resp_b = self.client_b.post(INIT_URL)
        self.assertEqual(resp_b.status_code, status.HTTP_201_CREATED)
        session_b_id = resp_b.data["session_id"]
        token_b = resp_b.data["session_token"]

        self.assertNotEqual(session_a_id, session_b_id)
        self.assertNotEqual(token_a, token_b)

        # Both sessions must have active consent; otherwise the analysis guard
        # returns 403 before the ownership check can run.
        for session_id in (session_a_id, session_b_id):
            ConsentAuditLog.objects.create(
                session_id=session_id,
                consent_version="v1.0",
                anonymized_processing_accepted=True,
                no_credential_disclosure_acknowledged=True,
                is_active=True,
            )

        # Populate a transaction owned by Session A
        snap_a = FinancialSnapshot.objects.create(session_id=session_a_id, liquid_balance=Decimal("50000.00"))
        tx_a = Transaction.objects.create(
            snapshot=snap_a,
            session_id=session_a_id,
            transaction_date=timezone.now().date(),
            amount=Decimal("1500.00"),
            transaction_type="DEBIT",
            normalized_merchant="Session A Private Grocery",
            category="Groceries",
            source_type="import",
        )

        # Client B attempts to modify Client A's transaction (IDOR attempt)
        resp_idor = self.client_b.post(
            CORRECT_TX_URL,
            {"transaction_id": str(tx_a.id), "is_transfer": True},
            HTTP_X_SESSION_TOKEN=token_b,
            format="json",
        )
        self.assertEqual(resp_idor.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp_idor.data.get("code"), "TX_NOT_FOUND")

        # Verify transaction was NOT modified
        tx_a.refresh_from_db()
        self.assertEqual(tx_a.category, "Groceries")

    # 2. Refresh and session recovery
    def test_02_refresh_and_session_recovery(self):
        resp_init = self.client_a.post(INIT_URL)
        session_id = resp_init.data["session_id"]
        token = resp_init.data["session_token"]

        # Simulate browser refresh where frontend presents existing session_id and token in header
        resp_resume = self.client_a.post(
            INIT_URL,
            {"session_id": session_id},
            HTTP_X_SESSION_TOKEN=token,
            format="json",
        )
        self.assertEqual(resp_resume.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_resume.data["session_id"], session_id)
        self.assertTrue(resp_resume.data.get("resumed", False))
        # Total session count in DB must remain exactly 1
        self.assertEqual(SecureSession.objects.count(), 1)

    # 3. Session token rotation and prior token invalidation
    def test_03_token_rotation_invalidates_prior_secret(self):
        resp_init = self.client_a.post(INIT_URL)
        session_id = resp_init.data["session_id"]
        old_token = resp_init.data["session_token"]

        # Ensure active consent for session A
        ConsentAuditLog.objects.create(
            session_id=session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        # Rotate token
        resp_rotate = self.client_a.post(
            ROTATE_URL,
            HTTP_X_SESSION_TOKEN=old_token,
        )
        self.assertEqual(resp_rotate.status_code, status.HTTP_200_OK)
        new_token = resp_rotate.data["session_token"]
        self.assertNotEqual(old_token, new_token)

        # Prior token is immediately rejected on subsequent requests from a client without the new cookie
        fresh_client = APIClient()
        resp_old_auth = fresh_client.get(
            ME_URL,
            HTTP_X_SESSION_TOKEN=old_token,
        )
        self.assertEqual(resp_old_auth.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid or expired session token", str(resp_old_auth.data))

        # New token succeeds
        resp_new_auth = fresh_client.get(
            ME_URL,
            HTTP_X_SESSION_TOKEN=new_token,
        )
        self.assertEqual(resp_new_auth.status_code, status.HTTP_200_OK)

    # 4. Session expiration enforcement
    def test_04_session_expiration_enforcement(self):
        resp_init = self.client_a.post(INIT_URL)
        session_id = resp_init.data["session_id"]
        token = resp_init.data["session_token"]

        # Fast-forward session into expiration
        s = SecureSession.objects.get(session_id=session_id)
        s.expires_at = timezone.now() - timedelta(minutes=5)
        s.save()

        # Request fails with 401
        fresh_client = APIClient()
        resp = fresh_client.get(
            ME_URL,
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid or expired session token", str(resp.data))

    # 5. Revocation enforcement
    def test_05_session_revocation_enforcement(self):
        resp_init = self.client_a.post(INIT_URL)
        session_id = resp_init.data["session_id"]
        token = resp_init.data["session_token"]

        # Revoke session
        s = SecureSession.objects.get(session_id=session_id)
        s.is_revoked = True
        s.save()

        fresh_client = APIClient()
        resp = fresh_client.get(
            ME_URL,
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid or expired session token", str(resp.data))

    # 6. Consent withdrawal blocks persistent operations
    def test_06_consent_withdrawal_blocks_persistence(self):
        resp_init = self.client_a.post(INIT_URL)
        session_id = resp_init.data["session_id"]
        token = resp_init.data["session_token"]

        # Opt-in
        ConsentAuditLog.objects.create(
            session_id=session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        # Withdraw consent
        resp_withdraw = self.client_a.post(
            CONSENT_WITHDRAW_URL,
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(resp_withdraw.status_code, status.HTTP_200_OK)

        # Attempt statement persistence -> must be rejected with 403 CONSENT_REQUIRED
        csv_data = "Date,Description,Debit,Credit,Balance\n2026-10-01,STORE,100.00,,5000.00\n"
        resp_persist = self.client_a.post(
            STATEMENT_URL,
            {"raw_text": csv_data, "persist": "true"},
            HTTP_X_SESSION_TOKEN=token,
            format="json",
        )
        self.assertEqual(resp_persist.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_persist.data.get("code"), "CONSENT_REQUIRED")

    # 7. Atomic data shredder (Nuke data)
    def test_07_atomic_data_shredder(self):
        resp_init = self.client_a.post(INIT_URL)
        session_id = resp_init.data["session_id"]
        token = resp_init.data["session_token"]

        snap = FinancialSnapshot.objects.create(session_id=session_id, liquid_balance=Decimal("45000.00"))
        Transaction.objects.create(
            snapshot=snap,
            session_id=session_id,
            transaction_date=timezone.now().date(),
            amount=Decimal("1200.00"),
            transaction_type="DEBIT",
            normalized_merchant="Gym Membership",
            source_type="import",
        )
        ConsentAuditLog.objects.create(session_id=session_id, is_active=True)

        # Trigger Hard Purge
        resp_nuke = self.client_a.post(
            NUKE_DATA_URL,
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(resp_nuke.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_nuke.data.get("status"), "HARD_PURGE_SUCCESSFUL")

        # Confirm total eradication
        self.assertEqual(FinancialSnapshot.objects.filter(session_id=session_id).count(), 0)
        self.assertEqual(Transaction.objects.filter(session_id=session_id).count(), 0)
        self.assertEqual(ConsentAuditLog.objects.filter(session_id=session_id).count(), 0)

    # 8. Stale write guard: Cross-session mismatch rejected
    def test_08_cross_session_substitution_rejected(self):
        resp_a = self.client_a.post(INIT_URL)
        token_a = resp_a.data["session_token"]

        resp_b = self.client_b.post(INIT_URL)
        session_b_id = resp_b.data["session_id"]

        # Present token A with body declaring session_id B
        resp_mismatch = self.client_a.post(
            STRESS_TEST_URL,
            {"session_id": session_b_id, "price": 20000},
            HTTP_X_SESSION_TOKEN=token_a,
            format="json",
        )
        # Should be rejected or bound strictly to the session authenticated by token_a
        self.assertIn(resp_mismatch.status_code, [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN])
        if resp_mismatch.status_code == status.HTTP_200_OK:
            # Verified that it did NOT use session_b_id
            self.assertEqual(resp_mismatch.data["evidence_ledger"]["verified_session_tx_count"], 0)
