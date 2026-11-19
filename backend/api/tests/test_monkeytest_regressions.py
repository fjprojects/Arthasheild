"""
MonkeyTest Regression Suite — Consent-Aware Session Bootstrap & Protected Financial Operations.

Verifies:
1. New session without consent: status reports has_active_consent=False; protected
   persona selection is blocked (HTTP 403).
2. New session with consent: consent registration enables exactly one successful persona selection.
3. Returning session with active consent: status reports has_active_consent=True and allows
   seamless restoration of financial data.
4. Consent withdrawal: subsequent persona selection and financial operations are immediately blocked (HTTP 403).
5. Unverified / expired session: rejects protected operations without leakage.
6. In-place consent grant: unconsented session can grant consent and subsequently load persona
   without page reload or session forfeiture.
"""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from api.models import SecureSession, ConsentAuditLog

INIT_URL = "/api/v1/auth/session/init/"
STATUS_URL = "/api/v1/auth/session/me/"
PERSONAS_URL = "/api/v1/personas/"
SELECT_PERSONA_URL = "/api/v1/personas/select/"
CONSENT_LOG_URL = "/api/v1/privacy/consent/"
CONSENT_WITHDRAW_URL = "/api/v1/privacy/consent/withdraw/"
OVERVIEW_URL = "/api/v1/insights/imported-overview/"


class MonkeyTestConsentBootstrapTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _init_session(self):
        resp = self.client.post(INIT_URL)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        return resp.data["session_id"], resp.data["session_token"]

    def _grant_consent(self, token, version="v1.1-2026-11"):
        return self.client.post(
            CONSENT_LOG_URL,
            {
                "consent_version": version,
                "anonymized_processing_accepted": True,
                "no_credential_disclosure_acknowledged": True,
            },
            HTTP_X_SESSION_TOKEN=token,
            format="json",
        )

    # 1. New session without consent: zero persona-selection allowed
    def test_01_new_session_without_consent_blocks_persona_selection(self):
        session_id, token = self._init_session()

        # Check server-side status
        status_resp = self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(status_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(status_resp.data["has_active_consent"])
        self.assertIsNone(status_resp.data["consent_version"])

        # Persona metadata list is public/unprotected
        personas_resp = self.client.get(PERSONAS_URL)
        self.assertEqual(personas_resp.status_code, status.HTTP_200_OK)
        personas = personas_resp.data.get("personas", [])
        self.assertGreater(len(personas), 0)

        # Attempting to select a persona without consent MUST return 403
        select_resp = self.client.post(
            SELECT_PERSONA_URL,
            {"persona_id": personas[0]["id"]},
            HTTP_X_SESSION_TOKEN=token,
            format="json",
        )
        self.assertEqual(select_resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("consent", str(select_resp.data).lower())

    # 2. New session with consent: exactly one successful persona selection
    def test_02_new_session_with_consent_allows_persona_selection(self):
        session_id, token = self._init_session()

        # Grant consent
        consent_resp = self._grant_consent(token)
        self.assertEqual(consent_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(consent_resp.data["status"], "CONSENT_REGISTERED")

        # Verify status endpoint reflects active consent
        status_resp = self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(status_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(status_resp.data["has_active_consent"])
        self.assertEqual(status_resp.data["consent_version"], "v1.1-2026-11")

        # Persona selection now succeeds
        personas_resp = self.client.get(PERSONAS_URL)
        personas = personas_resp.data.get("personas", [])
        first_persona_id = personas[0]["id"]

        select_resp = self.client.post(
            SELECT_PERSONA_URL,
            {"persona_id": first_persona_id},
            HTTP_X_SESSION_TOKEN=token,
            format="json",
        )
        self.assertEqual(select_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(select_resp.data["status"], "LOADED")
        self.assertEqual(select_resp.data["persona"]["id"], first_persona_id)
        self.assertIn("health_metrics", select_resp.data)
        self.assertIn("safe_to_spend", select_resp.data)

    # 3. Returning session with active consent: successful restoration
    def test_03_returning_session_with_active_consent_restores_data(self):
        session_id, token = self._init_session()
        self._grant_consent(token)

        # Simulate returning visit: client presents existing token to resume session
        resume_resp = self.client.post(
            INIT_URL,
            {"session_id": session_id},
            HTTP_X_SESSION_TOKEN=token,
            format="json",
        )
        self.assertEqual(resume_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resume_resp.data.get("resumed"))

        # Verify consent remains active on returned session
        status_resp = self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(status_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(status_resp.data["has_active_consent"])

        # Protected persona selection succeeds immediately
        select_resp = self.client.post(
            SELECT_PERSONA_URL,
            {"persona_id": "persona_freelancer_rohit"},
            HTTP_X_SESSION_TOKEN=token,
            format="json",
        )
        self.assertEqual(select_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(select_resp.data["persona"]["id"], "persona_freelancer_rohit")

    # 4. Consent withdrawal: financial operations remain blocked
    def test_04_consent_withdrawal_blocks_financial_operations(self):
        session_id, token = self._init_session()
        self._grant_consent(token)

        # Withdraw consent
        withdraw_resp = self.client.post(
            CONSENT_WITHDRAW_URL,
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(withdraw_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(withdraw_resp.data["status"], "CONSENT_WITHDRAWN")

        # Verify status endpoint reflects inactive consent
        status_resp = self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(status_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(status_resp.data["has_active_consent"])

        # Protected operations must now be blocked with HTTP 403
        select_resp = self.client.post(
            SELECT_PERSONA_URL,
            {"persona_id": "persona_freelancer_rohit"},
            HTTP_X_SESSION_TOKEN=token,
            format="json",
        )
        self.assertEqual(select_resp.status_code, status.HTTP_403_FORBIDDEN)

        overview_resp = self.client.post(
            OVERVIEW_URL,
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(overview_resp.status_code, status.HTTP_403_FORBIDDEN)

    # 5. Session-status verification failure: no protected financial request succeeds
    def test_05_session_status_unverified_or_expired_blocks_protected_operations(self):
        # Invalid / non-existent token
        bogus_token = "sec_tok_bogus1234567890abcdef1234567890abcdef"
        status_resp = self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=bogus_token)
        self.assertEqual(status_resp.status_code, status.HTTP_401_UNAUTHORIZED)

        # Protected request with invalid credentials is denied
        select_resp = self.client.post(
            SELECT_PERSONA_URL,
            {"persona_id": "persona_freelancer_rohit"},
            HTTP_X_SESSION_TOKEN=bogus_token,
            format="json",
        )
        self.assertEqual(select_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # 6. User grants consent after initial loading: persona loads successfully without refresh
    def test_06_user_grants_consent_after_initial_loading_succeeds_without_refresh(self):
        session_id, token = self._init_session()

        # Initial state: unconsented
        status_resp_1 = self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertFalse(status_resp_1.data["has_active_consent"])

        # Frontend shows modal, user clicks accept
        consent_resp = self._grant_consent(token, version="v1.1-2026-11")
        self.assertEqual(consent_resp.status_code, status.HTTP_200_OK)

        # Subsequent check verifies consent
        status_resp_2 = self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertTrue(status_resp_2.data["has_active_consent"])

        # Immediately load persona in the same session without reload
        select_resp = self.client.post(
            SELECT_PERSONA_URL,
            {"persona_id": "persona_salaried_priya"},
            HTTP_X_SESSION_TOKEN=token,
            format="json",
        )
        self.assertEqual(select_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(select_resp.data["persona"]["id"], "persona_salaried_priya")
