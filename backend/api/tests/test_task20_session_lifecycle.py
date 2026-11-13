"""
Task 20 — session lifecycle and bootstrap reliability regressions.

The frontend owns a single active session (one token, one session id). These
tests pin the backend contract that contract relies on:

* a bootstrap that presents a valid credential resumes the same session
  instead of forking a second one;
* an explicit rotation replaces the secret and invalidates the previous one;
* the cross-session substitution guard stays intact, and its error names the
  session the request's own token belongs to, so a client can repair its own
  bookkeeping;
* consent enforcement, expiry, revocation and cross-session isolation are
  unchanged.

All data here is synthetic.
"""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction

User = get_user_model()

INIT_URL = '/api/v1/auth/session/init/'
ROTATE_URL = '/api/v1/auth/session/rotate/'
STATUS_URL = '/api/v1/auth/session/me/'
STATEMENT_URL = '/api/v1/data/parse-statement/'

CSV_TEXT = (
    "Date,Description,Debit,Credit,Balance\n"
    "2026-10-04,UPI/SWIGGY/ORDER_9824219/swiggy@icici,480.00,,74520.00\n"
)


class SessionBootstrapTests(TestCase):
    """Bootstrap idempotency and credential handling."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='task20_user', password='pw')

    def test_01_fresh_bootstrap_creates_exactly_one_session(self):
        response = self.client.post(INIT_URL)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['session_id'].startswith('sec_'))
        self.assertTrue(response.data['session_token'])
        self.assertFalse(response.data.get('resumed'))
        self.assertEqual(SecureSession.objects.count(), 1)

    def test_02_bootstrap_with_a_valid_credential_resumes_the_same_session(self):
        first = self.client.post(INIT_URL)
        session_id = first.data['session_id']
        token = first.data['session_token']

        second = self.client.post(INIT_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data['resumed'])
        # The identity and the credential are preserved: no forked session.
        self.assertEqual(second.data['session_id'], session_id)
        self.assertEqual(second.data['session_token'], token)
        self.assertEqual(SecureSession.objects.count(), 1)

    def test_03_repeated_bootstrap_never_creates_competing_sessions(self):
        token = self.client.post(INIT_URL).data['session_token']
        for _ in range(5):
            response = self.client.post(INIT_URL, HTTP_X_SESSION_TOKEN=token)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data['resumed'])
        self.assertEqual(SecureSession.objects.count(), 1)

    def test_04_unauthenticated_bootstrap_still_creates_distinct_sessions(self):
        # The backend is explicit: without a credential it cannot know that two
        # callers want the same session, so it creates one each. The client
        # prevents this by making the bootstrap single-flight.
        first = self.client.post(INIT_URL)
        second = self.client.post(INIT_URL)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.data['session_id'], second.data['session_id'])
        self.assertEqual(SecureSession.objects.count(), 2)

    def test_05_bootstrap_with_an_invalid_credential_creates_a_new_session(self):
        response = self.client.post(INIT_URL, HTTP_X_SESSION_TOKEN='not-a-real-token')
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data.get('resumed'))
        self.assertEqual(SecureSession.objects.count(), 1)

    def test_06_rotation_replaces_the_secret_and_invalidates_the_old_one(self):
        created = self.client.post(INIT_URL)
        session_id = created.data['session_id']
        token = created.data['session_token']
        # Rotation is a consent-gated operation.
        ConsentAuditLog.objects.create(
            session_id=session_id,
            consent_version='v1.0-task20',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )

        rotated = self.client.post(ROTATE_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(rotated.status_code, 200)
        # Rotation keeps the session identity and replaces only the secret.
        self.assertEqual(rotated.data['session_id'], session_id)
        self.assertNotEqual(rotated.data['session_token'], token)

        # The previous secret is dead, the new one works.
        self.assertEqual(
            self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token).status_code, 401
        )
        self.assertEqual(
            self.client.get(
                STATUS_URL, HTTP_X_SESSION_TOKEN=rotated.data['session_token']
            ).status_code,
            200,
        )

    def test_07_revoked_and_expired_sessions_are_rejected(self):
        created = self.client.post(INIT_URL)
        token = created.data['session_token']
        session = SecureSession.objects.get(session_id=created.data['session_id'])

        session.is_revoked = True
        session.save(update_fields=['is_revoked'])
        self.assertEqual(
            self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token).status_code, 401
        )

        session.is_revoked = False
        session.expires_at = timezone.now() - timedelta(minutes=1)
        session.save(update_fields=['is_revoked', 'expires_at'])
        response = self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(response.status_code, 401)
        body = response.json()
        # The expired session is rejected by the authentication layer; the code
        # may come from the DRF authenticator or from the view guard.
        self.assertTrue(
            body.get('code') == 'EXPIRED_SESSION' or 'expired' in str(body).lower(),
            msg=str(body),
        )

    def test_08_status_endpoint_never_exposes_the_credential(self):
        created = self.client.post(INIT_URL)
        token = created.data['session_token']
        response = self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn(token, body)
        self.assertNotIn('token_hash', body)
        self.assertNotIn('session_token', body)


class SessionSubstitutionGuardTests(TestCase):
    """The cross-session IDOR guard must stay intact and stay actionable."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='task20_guard', password='pw')
        self.session_a, self.token_a = SecureSession.issue_session(
            f'task20_a_{uuid.uuid4().hex[:8]}'
        )
        self.session_b, self.token_b = SecureSession.issue_session(
            f'task20_b_{uuid.uuid4().hex[:8]}'
        )
        ConsentAuditLog.objects.create(
            session_id=self.session_a.session_id,
            consent_version='v1.0-task20',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )

    def test_01_another_session_id_is_rejected(self):
        response = self.client.post(
            STATEMENT_URL,
            {'raw_text': CSV_TEXT, 'format': 'csv', 'persist': 'true',
             'session_id': self.session_b.session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body.get('code'), 'SESSION_MISMATCH')
        # The error names the session the request's own token belongs to, so a
        # client can repair its own bookkeeping without gaining access.
        self.assertEqual(body.get('authenticated_session'), self.session_a.session_id)
        self.assertNotIn(self.session_b.session_id, str(body.get('authenticated_session')))

    def test_02_no_data_is_written_for_a_rejected_substitution(self):
        self.client.post(
            STATEMENT_URL,
            {'raw_text': CSV_TEXT, 'format': 'csv', 'persist': 'true',
             'session_id': self.session_b.session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_a.session_id).count(), 0
        )
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_b.session_id).count(), 0
        )

    def test_03_the_matching_session_id_is_accepted(self):
        response = self.client.post(
            STATEMENT_URL,
            {'raw_text': CSV_TEXT, 'format': 'csv', 'persist': 'true',
             'session_id': self.session_a.session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=self.token_a,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['persistence']['imported'], 1)
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_a.session_id).count(), 1
        )

    def test_04_one_session_cannot_read_another_session_data(self):
        snapshot, _ = FinancialSnapshot.objects.get_or_create(
            session_id=self.session_a.session_id
        )
        Transaction.objects.create(
            snapshot=snapshot,
            session_id=self.session_a.session_id,
            transaction_date=timezone.now().date(),
            amount=1500,
            transaction_type='DEBIT',
            normalized_merchant='CULTFIT',
            category='Uncategorized',
            source_type=Transaction.SOURCE_IMPORT,
        )
        # Session B's credential with session A's id is refused: the guard
        # compares the supplied id with the authenticated session. Session B has
        # its own consent, so the request reaches the substitution guard.
        ConsentAuditLog.objects.create(
            session_id=self.session_b.session_id,
            consent_version='v1.0-task20',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )
        response = self.client.post(
            f"/api/v1/insights/imported-overview/?session_id={self.session_a.session_id}",
            {},
            format='json',
            HTTP_X_SESSION_TOKEN=self.token_b,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get('code'), 'SESSION_MISMATCH')
        self.assertNotIn('CULTFIT', response.content.decode())


class ConsentAndSessionInteractionTests(TestCase):
    """Consent gating and withdrawal behaviour around the active session."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='task20_consent', password='pw')

    def test_01_persisting_a_statement_requires_consent(self):
        created = self.client.post(INIT_URL)
        response = self.client.post(
            STATEMENT_URL,
            {'raw_text': CSV_TEXT, 'format': 'csv', 'persist': 'true',
             'session_id': created.data['session_id']},
            format='json',
            HTTP_X_SESSION_TOKEN=created.data['session_token'],
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get('error'), 'CONSENT_REQUIRED')

    def test_02_consent_withdrawal_keeps_the_session_but_blocks_processing(self):
        created = self.client.post(INIT_URL)
        session_id = created.data['session_id']
        token = created.data['session_token']

        consent = self.client.post(
            '/api/v1/privacy/consent/',
            {'session_id': session_id, 'consent_version': 'v1.0-task20',
             'anonymized_processing_accepted': True,
             'no_credential_disclosure_acknowledged': True},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(consent.status_code, 200)

        imported = self.client.post(
            STATEMENT_URL,
            {'raw_text': CSV_TEXT, 'format': 'csv', 'persist': 'true',
             'session_id': session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(imported.status_code, 200)

        withdrawn = self.client.post(
            '/api/v1/privacy/consent/withdraw/',
            {'session_id': session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(withdrawn.status_code, 200)

        # The session itself is still valid (the user may consent again), but
        # persistent processing is blocked until consent is granted again.
        self.assertEqual(
            self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=token).status_code, 200
        )
        blocked = self.client.post(
            STATEMENT_URL,
            {'raw_text': CSV_TEXT, 'format': 'csv', 'persist': 'true',
             'session_id': session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json().get('error'), 'CONSENT_REQUIRED')

        # Re-consenting on the same session works and does not fork it.
        reconsent = self.client.post(
            '/api/v1/privacy/consent/',
            {'session_id': session_id, 'consent_version': 'v1.0-task20',
             'anonymized_processing_accepted': True,
             'no_credential_disclosure_acknowledged': True},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(reconsent.status_code, 200)
        again = self.client.post(
            STATEMENT_URL,
            {'raw_text': CSV_TEXT, 'format': 'csv', 'persist': 'true',
             'session_id': session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()['persistence']['imported'], 0)
        self.assertEqual(again.json()['persistence']['skipped_duplicates'], 1)
        self.assertEqual(SecureSession.objects.count(), 1)

    def test_03_stale_session_recovers_to_a_usable_new_session(self):
        created = self.client.post(INIT_URL)
        stale_token = created.data['session_token']
        session_id = created.data['session_id']

        # The session is revoked server-side (e.g. shredded elsewhere).
        SecureSession.objects.filter(session_id=session_id).update(is_revoked=True)
        self.assertEqual(
            self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=stale_token).status_code, 401
        )

        # A bootstrap with the stale credential cannot resume it: a new session
        # is issued instead, and the stale credential stays dead.
        recovered = self.client.post(INIT_URL, HTTP_X_SESSION_TOKEN=stale_token)
        self.assertEqual(recovered.status_code, 201)
        self.assertNotEqual(recovered.data['session_id'], session_id)
        self.assertNotEqual(recovered.data['session_token'], stale_token)
        self.assertEqual(
            self.client.get(
                STATUS_URL, HTTP_X_SESSION_TOKEN=recovered.data['session_token']
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(STATUS_URL, HTTP_X_SESSION_TOKEN=stale_token).status_code, 401
        )
