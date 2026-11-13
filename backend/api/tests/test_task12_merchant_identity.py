"""
Task 12 — merchant identity classification and API data minimisation regressions.

All data here is synthetic. These tests cover the three display outcomes
(recognized merchant, identified personal transfer, ambiguous counterparty),
refund attribution privacy, and the subscriptions payload contract.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from api.insights import (
    ALLOC_SUGGESTED_NOT_APPLIED,
    MATCH_PROBABLE,
    PERSONAL_TRANSFER_LABEL,
    UNIDENTIFIED_COUNTERPARTY_LABEL,
    _extract_canonical_merchant,
    _safe_counterparty_label,
    detect_subscriptions,
    monthly_budget,
)
from api.models import FinancialSnapshot, SecureSession, Transaction

GENERIC_LABELS = {PERSONAL_TRANSFER_LABEL, UNIDENTIFIED_COUNTERPARTY_LABEL}


def _make_snapshot(session_id):
    snapshot, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
    return snapshot


def _make_tx(snapshot, session_id, merchant, amount, tx_type, tx_date):
    return Transaction.objects.create(
        snapshot=snapshot,
        session_id=session_id,
        transaction_date=tx_date,
        amount=Decimal(str(amount)),
        transaction_type=tx_type,
        normalized_merchant=merchant,
        category='Uncategorized',
        source_type='import',
    )


class MerchantIdentityDisplayTests(TestCase):
    """The labeler distinguishes merchant, personal transfer and ambiguity."""

    def test_01_bare_personal_name_is_ambiguous_not_echoed(self):
        label = _safe_counterparty_label('Rahul Sharma')
        self.assertEqual(label, UNIDENTIFIED_COUNTERPARTY_LABEL)
        self.assertNotIn('Rahul', label)
        self.assertNotIn('Sharma', label)

    def test_02_recognized_merchants_keep_readable_names(self):
        self.assertEqual(_safe_counterparty_label('Chai Point'), 'Chai Point')
        self.assertEqual(
            _safe_counterparty_label('Croma Electronics Store'),
            'Croma Electronics Store',
        )
        self.assertEqual(
            _safe_counterparty_label('MacBook Purchase'), 'MacBook Purchase'
        )
        self.assertEqual(
            _safe_counterparty_label('MakeMyTrip Flight Booking'),
            'MakeMyTrip Flight Booking',
        )

    def test_03_personal_upi_transfer_is_strongly_identified(self):
        for narration in (
            'UPI/rahul.sharma@okaxis',
            'UPI/9811234567@upi',
            'Payment to Rahul Sharma',
            'Paid to Ananya Sen',
        ):
            label = _safe_counterparty_label(narration)
            self.assertEqual(label, PERSONAL_TRANSFER_LABEL)
            for leaked in ('Rahul', 'rahul', 'Ananya', 'Sharma', '9811234567'):
                self.assertNotIn(leaked, label)

    def test_04_identifiers_and_markers_stay_generic(self):
        self.assertEqual(
            _safe_counterparty_label('NEFT Rahul A/C 123456789012'),
            UNIDENTIFIED_COUNTERPARTY_LABEL,
        )
        self.assertEqual(
            _safe_counterparty_label('UPI/[REDACTED_UPI_ID]'),
            UNIDENTIFIED_COUNTERPARTY_LABEL,
        )
        self.assertEqual(
            _safe_counterparty_label('Chai Point [REDACTED_VPA]'), 'Chai Point'
        )

    def test_05_single_bare_token_is_ambiguous(self):
        self.assertEqual(
            _safe_counterparty_label('Rahul'), UNIDENTIFIED_COUNTERPARTY_LABEL
        )
        # A recognized brand is still a merchant.
        self.assertEqual(_safe_counterparty_label('Croma'), 'Croma')


class AmbiguousRefundNarrationTests(TestCase):
    """A refund from an ambiguous name must not leak the name or change allocation."""

    def setUp(self):
        self.session_id = f'task12_refund_{uuid.uuid4().hex[:8]}'
        self.snap = _make_snapshot(self.session_id)

    def _tx(self, merchant, amount, tx_type, tx_date):
        return _make_tx(self.snap, self.session_id, merchant, amount, tx_type, tx_date)

    def test_06_ambiguous_refund_attributes_without_raw_names(self):
        self._tx('Rahul Sharma', 700, 'DEBIT', date(2026, 10, 1))
        self._tx('REFUND Rahul Sharma', 700, 'CREDIT', date(2026, 10, 5))

        result = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(len(result['refund_details']), 1)
        refund = result['refund_details'][0]

        # Matching and allocation behaviour is unchanged (canonical match -> PROBABLE).
        self.assertEqual(refund['match_confidence'], MATCH_PROBABLE)
        self.assertEqual(refund['allocation_status'], ALLOC_SUGGESTED_NOT_APPLIED)
        self.assertEqual(refund['allocated_amount'], '0.00')
        self.assertEqual(refund['suggested_amount'], '700.00')

        self.assertEqual(refund['merchant'], UNIDENTIFIED_COUNTERPARTY_LABEL)
        self.assertEqual(
            refund['matched_purchases'][0]['merchant'],
            UNIDENTIFIED_COUNTERPARTY_LABEL,
        )
        blob = json.dumps(result['refund_details'])
        for leaked in ('Rahul', 'Sharma'):
            self.assertNotIn(leaked, blob)


class SubscriptionPayloadMinimisationTests(TestCase):
    """The subscriptions endpoint stops serializing the internal clustering key."""

    def setUp(self):
        self.session_id = f'task12_subs_{uuid.uuid4().hex[:8]}'
        self.snap = _make_snapshot(self.session_id)
        for day in (date(2026, 8, 5), date(2026, 9, 5), date(2026, 10, 5)):
            _make_tx(
                self.snap, self.session_id, 'Cult Fit Gym Membership', 1500, 'DEBIT', day
            )

    def _client_with_consent(self):
        from api.models import ConsentAuditLog
        client = APIClient()
        _session, token = SecureSession.issue_session(self.session_id)
        # Register explicit consent directly in the database to satisfy the new
        # per-session consent gate for tests.
        ConsentAuditLog.objects.create(
            session_id=_session.session_id,
            consent_version='v1.0-task12',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        return client, token

    def test_07_api_omits_canonical_merchant_but_keeps_safe_label(self):
        client, token = self._client_with_consent()
        response = client.post(
            '/api/v1/insights/subscriptions/',
            {'as_of_date': '2026-10-20'},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(len(body['subscriptions']), 1)
        self.assertEqual(body['count'], len(body['subscriptions']))

        for sub in body['subscriptions']:
            self.assertNotIn('canonical_merchant', sub)
            self.assertIn('canonical_label', sub)
            self.assertIn('merchant', sub)
        self.assertNotIn('cult_fit', json.dumps(body))

    def test_08_backend_clustering_is_preserved(self):
        result = detect_subscriptions(self.session_id, as_of_date=date(2026, 10, 20))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['canonical_merchant'], 'cult_fit')
        self.assertEqual(result[0]['occurrence_count'], 3)
        self.assertEqual(result[0]['confidence'], 'CONFIRMED')
        self.assertEqual(
            _extract_canonical_merchant('Swiggy Instamart Grocery Order'),
            'swiggy_instamart',
        )
