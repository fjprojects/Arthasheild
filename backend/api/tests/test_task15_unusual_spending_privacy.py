"""
Task 15 — unusual-spending API privacy regressions.

The detector uses stored narration, but the HTTP response must expose only safe
merchant labels. Detection rules, amounts, dates and reason codes stay unchanged.
All data here is synthetic.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model
User = get_user_model()
from django.utils import timezone
from rest_framework.test import APIClient
from api.models import SecureSession, ConsentAuditLog

from api.insights import detect_unusual_spending
from api.models import FinancialSnapshot, SecureSession, Transaction
from api.tests.privacy_scan import response_leaks as _response_leaks

CASES = [
    ('Payment to Rahul 9876543210', 'Unidentified Counterparty'),
    ('Rahul Sharma', 'Unidentified Counterparty'),
    ('Payment to Ananya PAN ABCDE1234F', 'Personal Transfer'),
    ('UPI 1234 5678 9012', 'Unidentified Counterparty'),
    ('Flipkart ORD-5555 Electronics', 'Flipkart Electronics'),
    ('Chai Point', 'Chai Point'),
    ('Croma Electronics Store', 'Croma Electronics Store'),
    ('Unknown Trader A/C 998877665544', 'Unidentified Counterparty'),
]

FORBIDDEN = (
    '9876543210', 'ABCDE1234F', '1234 5678 9012', 'Rahul', 'Sharma', 'Ananya',
    'ORD-5555', 'ORD5555', '998877665544', 'A/C ',
)

# Recursive response scan: identifier shapes, narration, references and markers.
# Shared with the Task 17 suite; it runs the production sanitizer patterns
# alongside the narrative/marker shapes (see api.tests.privacy_scan).


def _consent(client, session_id, token):
    consent = client.post(
        '/api/v1/privacy/consent/',
        {
            'session_id': session_id,
            'consent_version': 'v1.0-task15',
            'anonymized_processing_accepted': True,
            'no_credential_disclosure_acknowledged': True,
        },
        format='json',
        HTTP_X_SESSION_TOKEN=token,
    )
    return consent


class UnusualSpendingApiPrivacyTests(TestCase):
    """Only safe labels are serialized; detection results are otherwise identical."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='task15_user', password='pw')
        self.session_user, _ = SecureSession.issue_session()
        _cal = ConsentAuditLog.objects.create(
            session_id=self.session_user.session_id,
            user=self.user,
            consent_version='v1.0-task15',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )

    def _make_session(self, merchant, amount=Decimal('10000')):
        session_id = f'task15_{uuid.uuid4().hex[:8]}'
        snap, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
        for i in range(5):
            Transaction.objects.create(
                snapshot=snap,
                session_id=session_id,
                transaction_date=date(2026, 10, 1 + i),
                amount=Decimal('100'),
                transaction_type='DEBIT',
                normalized_merchant=f'Baseline Shop {i}',
                category='Uncategorized',
                source_type='import',
            )
        large = Transaction.objects.create(
            snapshot=snap,
            session_id=session_id,
            transaction_date=date(2026, 10, 15),
            amount=amount,
            transaction_type='DEBIT',
            normalized_merchant=merchant,
            category='Uncategorized',
            source_type='import',
        )
        client = APIClient()
        _client, _tok = SecureSession.issue_session(session_id)
        _cal = ConsentAuditLog.objects.create(
            session_id=session_id,
            user=None,
            consent_version='v1.0-task15',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )
        self.assertIsNotNone(_cal.id)
        return session_id, large, client, _tok

    def _flagged(self, session_id, client, token):
        response = client.post(
            '/api/v1/insights/unusual-spending/',
            {'session_id': session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_01_api_labels_are_safe_for_every_case(self):
        for merchant, expected in CASES:
            session_id, large, client, token = self._make_session(merchant)
            _consent(client, session_id, token)
            body = self._flagged(session_id, client, token).json()
            row = next(f for f in body['flagged'] if f['id'] == str(large.id))
            self.assertEqual(row['merchant'], expected, msg=merchant)
            self.assertEqual(row['reason'], 'large_amount')

    def test_02_no_sensitive_narration_reaches_the_client(self):
        for merchant, _expected in CASES:
            session_id, _large, client, token = self._make_session(merchant)
            blob = json.dumps(self._flagged(session_id, client, token).json())
            for sensitive in FORBIDDEN:
                self.assertNotIn(sensitive, blob, msg=f'{merchant} leaked {sensitive}')

    def test_03_detection_fields_are_unchanged(self):
        session_id, large, client, token = self._make_session('Rahul Sharma')
        public = next(
            f for f in self._flagged(session_id, client, token).json()['flagged']
            if f['id'] == str(large.id)
        )
        internal = next(
            f for f in detect_unusual_spending(session_id) if f['id'] == str(large.id)
        )
        for field in ('reason', 'amount', 'date', 'source_type', 'baseline', 'threshold'):
            self.assertEqual(public[field], internal[field], msg=field)
        self.assertEqual(public['merchant'], 'Unidentified Counterparty')
        self.assertEqual(internal['merchant'], 'Rahul Sharma')

    def test_04_duplicate_detection_and_clean_names_are_preserved(self):
        session_id = f'task15_dup_{uuid.uuid4().hex[:8]}'
        snap, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
        flagged_ids = []
        for day in (date(2026, 10, 5), date(2026, 10, 6)):
            tx = Transaction.objects.create(
                snapshot=snap,
                session_id=session_id,
                transaction_date=day,
                amount=Decimal('50'),
                transaction_type='DEBIT',
                normalized_merchant='Chai Point',
                category='Uncategorized',
                source_type='import',
            )
            flagged_ids.append(str(tx.id))

        client = APIClient()
        _session, token = SecureSession.issue_session(session_id)
        _consent(client, session_id, token)
        body = self._flagged(session_id, client, token).json()

        dup_rows = [f for f in body['flagged'] if f['id'] in flagged_ids]
        self.assertEqual(len(dup_rows), 2)
        for row in dup_rows:
            self.assertEqual(row['reason'], 'duplicate_amount_merchant')
            self.assertEqual(row['merchant'], 'Chai Point')

    def test_05_stored_narration_and_session_isolation_are_untouched(self):
        session_a, large_a, client, token = self._make_session(
            'Payment to Ananya PAN ABCDE1234F'
        )
        session_b, large_b, _client_b, _token_b = self._make_session(
            'Rahul Sharma', amount=Decimal('20000')
        )
        body = self._flagged(session_a, client, token).json()
        ids = {row['id'] for row in body['flagged']}
        self.assertIn(str(large_a.id), ids)
        self.assertNotIn(str(large_b.id), ids)

        stored = list(
            Transaction.objects.filter(session_id=session_a).values_list(
                'normalized_merchant', flat=True
            )
        )
        self.assertIn('Payment to Ananya PAN ABCDE1234F', stored)

    def test_06_recursive_scan_finds_no_sensitive_value_anywhere(self):
        for merchant, _expected in CASES:
            session_id, _large, client, token = self._make_session(merchant)
            body = self._flagged(session_id, client, token).json()
            leaks = _response_leaks(body)
            self.assertEqual(leaks, [], msg=f'{merchant} leaked {leaks}')
            self.assertNotIn('canonical_merchant', json.dumps(body))

    def test_07_consent_is_required(self):
        session_id = f'task15_noconsent_{uuid.uuid4().hex[:8]}'
        snap, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
        Transaction.objects.create(
            snapshot=snap,
            session_id=session_id,
            transaction_date=date(2026, 10, 5),
            amount=Decimal('10000'),
            transaction_type='DEBIT',
            normalized_merchant='Rahul Sharma',
            category='Uncategorized',
            source_type='import',
        )
        client = APIClient()
        _session, token = SecureSession.issue_session(session_id)
        response = client.post(
            '/api/v1/insights/unusual-spending/',
            {'session_id': session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get('code'), 'CONSENT_REQUIRED')

    def test_08_sessions_cannot_see_each_others_flagged_rows(self):
        session_a, large_a, client_a, token_a = self._make_session('Rahul Sharma')
        _consent(client_a, session_a, token_a)
        session_b, large_b, client_b, token_b = self._make_session(
            'Chai Point', amount=Decimal('20000')
        )
        _consent(client_b, session_b, token_b)
        ids_a = {r['id'] for r in self._flagged(session_a, client_a, token_a).json()['flagged']}
        ids_b = {r['id'] for r in self._flagged(session_b, client_b, token_b).json()['flagged']}
        self.assertIn(str(large_a.id), ids_a)
        self.assertNotIn(str(large_b.id), ids_a)
        self.assertIn(str(large_b.id), ids_b)
        self.assertNotIn(str(large_a.id), ids_b)
