"""
Consent validation regression tests (synthetic data only).
Ported from reference audit suite.

Backend contract under test:
- ``anonymized_processing_accepted`` must be the JSON boolean ``true``.
- ``no_credential_disclosure_acknowledged`` must be the JSON boolean ``true``.
- Any other combination (false / missing / null / "true" string) is rejected.
- Consent is bound to the authenticated session, cannot be registered for
  another session, and withdrawal deactivates the latest record.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from api.models import ConsentAuditLog


class ConsentValidationMatrixTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        resp = self.client.post("/api/v1/auth/session/init/", {}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.token = resp.data["session_token"]
        self.session_id = resp.data["session_id"]

    def _register(self, payload):
        return self.client.post(
            "/api/v1/privacy/consent/",
            payload,
            format="json",
            HTTP_X_SESSION_TOKEN=self.token,
        )

    def _base(self, **overrides):
        payload = {
            "session_id": self.session_id,
            "consent_version": "v1.0-test",
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True,
        }
        payload.update(overrides)
        return payload

    # --- Explicit boolean matrix ---------------------------------------------

    def test_false_false_is_rejected(self):
        resp = self._register(
            self._base(
                anonymized_processing_accepted=False,
                no_credential_disclosure_acknowledged=False,
            )
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ConsentAuditLog.objects.count(), 0)

    def test_true_false_is_rejected(self):
        resp = self._register(
            self._base(no_credential_disclosure_acknowledged=False)
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ConsentAuditLog.objects.count(), 0)

    def test_false_true_is_rejected(self):
        resp = self._register(
            self._base(anonymized_processing_accepted=False)
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ConsentAuditLog.objects.count(), 0)

    def test_true_true_is_accepted_and_persisted(self):
        resp = self._register(self._base())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "CONSENT_REGISTERED")

        log = ConsentAuditLog.objects.get(session_id=self.session_id)
        self.assertTrue(log.anonymized_processing_accepted)
        self.assertTrue(log.no_credential_disclosure_acknowledged)
        self.assertTrue(log.is_active)

    # --- Malformed / missing values ------------------------------------------

    def test_missing_second_flag_is_rejected(self):
        payload = self._base()
        payload.pop("no_credential_disclosure_acknowledged")
        resp = self._register(payload)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ConsentAuditLog.objects.count(), 0)

    def test_missing_first_flag_is_rejected(self):
        payload = self._base()
        payload.pop("anonymized_processing_accepted")
        resp = self._register(payload)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ConsentAuditLog.objects.count(), 0)

    def test_null_flags_are_rejected(self):
        resp = self._register(
            self._base(
                anonymized_processing_accepted=None,
                no_credential_disclosure_acknowledged=None,
            )
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ConsentAuditLog.objects.count(), 0)

    def test_string_true_is_rejected(self):
        resp = self._register(
            self._base(
                anonymized_processing_accepted="true",
                no_credential_disclosure_acknowledged="true",
            )
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ConsentAuditLog.objects.count(), 0)

    # --- Session binding ------------------------------------------------------

    def test_session_mismatch_is_rejected(self):
        resp = self._register(self._base(session_id="sec_someone_elses_session"))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data.get("code"), "SESSION_MISMATCH")
        self.assertEqual(ConsentAuditLog.objects.count(), 0)

    def test_consent_is_bound_to_authenticated_session(self):
        resp = self._register(self._base())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["session_id"], self.session_id)
        self.assertFalse(
            ConsentAuditLog.objects.filter(session_id="sec_someone_elses_session").exists()
        )

    # --- Repeated initialization and withdrawal ------------------------------

    def test_repeated_initialization_records_each_consent(self):
        first = self._register(self._base())
        second = self._register(self._base())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            ConsentAuditLog.objects.filter(session_id=self.session_id).count(), 2
        )
        latest = (
            ConsentAuditLog.objects.filter(session_id=self.session_id)
            .order_by("-consented_at")
            .first()
        )
        self.assertTrue(latest.is_active)
        self.assertTrue(latest.anonymized_processing_accepted)
        self.assertTrue(latest.no_credential_disclosure_acknowledged)

    def test_withdrawal_deactivates_and_reconsent_restores(self):
        self.assertEqual(self._register(self._base()).status_code, 200)

        withdraw = self.client.post(
            "/api/v1/privacy/consent/withdraw/",
            {},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token,
        )
        self.assertEqual(withdraw.status_code, 200)
        self.assertFalse(
            ConsentAuditLog.objects.filter(
                session_id=self.session_id, is_active=True
            ).exists()
        )

        # Re-consent requires both flags again.
        rejected = self._register(
            self._base(no_credential_disclosure_acknowledged=False)
        )
        self.assertEqual(rejected.status_code, 400)

        restored = self._register(self._base())
        self.assertEqual(restored.status_code, 200)
        active = ConsentAuditLog.objects.filter(
            session_id=self.session_id, is_active=True
        )
        self.assertEqual(active.count(), 1)
        self.assertTrue(active.first().anonymized_processing_accepted)
