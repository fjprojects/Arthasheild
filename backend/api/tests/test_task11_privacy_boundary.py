"""
Task 11 — Privacy boundary hardening regressions.

Covers the API payloads and label helpers that keep raw personal narration,
phone numbers, account references, PAN/Aadhaar-like identifiers and internal
redaction markers out of user-facing fields.

All data here is synthetic.
"""
import json
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from api.insights import (
    ALLOC_APPLIED,
    MATCH_CONFIRMED,
    MATCH_WEAK,
    PERSONAL_TRANSFER_LABEL,
    UNIDENTIFIED_COUNTERPARTY_LABEL,
    _safe_counterparty_label,
    detect_subscriptions,
    monthly_budget,
)
from api.models import FinancialSnapshot, SecureSession, Transaction

PHONE_RE = re.compile(r'\b[6-9]\d{9}\b')
PAN_RE = re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b')
AADHAAR_RE = re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b')
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


class PersonaPayloadPrivacyTests(TestCase):
    """The persona API must ship display labels, not raw narration."""

    def setUp(self):
        self.client = APIClient()
        source_path = Path(settings.BASE_DIR).parent / 'synthetic_data' / 'personas.json'
        with open(source_path, 'r', encoding='utf-8') as handle:
            self.source_personas = json.load(handle)['personas']

    def _token(self):
        _session, token = SecureSession.issue_session(
            f'task11_persona_{uuid.uuid4().hex[:8]}'
        )
        # Register explicit consent for this session in the database before any gated operation.
        # The consent endpoint itself is gated, so we create the record directly for tests.
        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=_session.session_id,
            consent_version='v1.0-task14',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        return token

    def test_01_persona_list_omits_narration_and_transactions(self):
        response = self.client.get('/api/v1/personas/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload['personas']), 3)

        blob = json.dumps(payload)
        for sensitive in ('9811234567', '9988112233', '@upi', '@paytm', '@sbi'):
            self.assertNotIn(sensitive, blob)

        expected_keys = {
            'id', 'name', 'profile', 'currency', 'currency_symbol',
            'monthly_average_income', 'account_summary', 'detected_leaks_summary',
        }
        for persona in payload['personas']:
            self.assertEqual(set(persona.keys()), expected_keys)
            self.assertNotIn('transactions', persona)

    def test_02_select_persona_returns_display_labels_and_keeps_history(self):
        token = self._token()
        response = self.client.post(
            '/api/v1/personas/select/',
            {'persona_id': 'persona_freelancer_rohit'},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        returned = response.json()['persona']
        source = next(p for p in self.source_personas if p['id'] == 'persona_freelancer_rohit')

        self.assertEqual(len(returned['transactions']), len(source['transactions']))
        self.assertEqual(
            sum(Decimal(str(t['amount'])) for t in returned['transactions']),
            sum(Decimal(str(t['amount'])) for t in source['transactions']),
        )

        for tx in returned['transactions']:
            label = tx['description']
            self.assertTrue(label)
            self.assertNotIn('@', label)
            self.assertNotIn('REDACTED', label.upper())
            self.assertIsNone(PHONE_RE.search(label))
            self.assertIsNone(PAN_RE.search(label))
            self.assertIsNone(AADHAAR_RE.search(label))
            self.assertNotIn('A/C', label)
            for field in ('id', 'date', 'amount', 'type', 'category'):
                self.assertIn(field, tx)

    def test_03_every_persona_ledger_label_is_generic_for_phone_vpas(self):
        labels_for_personal_rows = []
        for source in self.source_personas:
            token = self._token()
            response = self.client.post(
                '/api/v1/personas/select/',
                {'persona_id': source['id']},
                format='json',
                HTTP_X_SESSION_TOKEN=token,
            )
            self.assertEqual(response.status_code, 200)
            returned = response.json()['persona']
            by_id = {tx['id']: tx['description'] for tx in returned['transactions']}

            for tx in source['transactions']:
                raw = tx.get('description', '')
                label = by_id[tx['id']]
                if PHONE_RE.search(raw):
                    self.assertIn(label, GENERIC_LABELS)
                elif '@' in raw:
                    self.assertNotIn('@', label)
                    self.assertIsNone(PHONE_RE.search(label))
                    self.assertNotIn('REDACTED', label.upper())
                    labels_for_personal_rows.append(label)

        self.assertTrue(labels_for_personal_rows)


class RefundAttributionPrivacyTests(TestCase):
    """Refund attribution keeps its maths but never exposes personal narration."""

    def setUp(self):
        self.session_id = f'task11_refund_{uuid.uuid4().hex[:8]}'
        self.snap = _make_snapshot(self.session_id)

    def _debit(self, merchant, amount, day):
        return _make_tx(self.snap, self.session_id, merchant, amount, 'DEBIT', day)

    def _credit(self, merchant, amount, day):
        return _make_tx(self.snap, self.session_id, merchant, amount, 'CREDIT', day)

    def test_04_personal_refund_label_is_generic_and_attribution_preserved(self):
        self._debit('UPI/Rahul/REF-777', 500, date(2026, 10, 1))
        self._credit('REFUND UPI/Rahul/REF-777', 500, date(2026, 10, 5))

        result = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(len(result['refund_details']), 1)
        refund = result['refund_details'][0]

        self.assertEqual(refund['match_confidence'], MATCH_CONFIRMED)
        self.assertEqual(refund['allocation_status'], ALLOC_APPLIED)
        self.assertEqual(refund['allocated_amount'], '500.00')
        self.assertIn(refund['merchant'], GENERIC_LABELS)
        self.assertNotIn('Rahul', refund['merchant'])
        self.assertNotIn('REF-777', refund['merchant'])

        purchase = refund['matched_purchases'][0]
        self.assertIn(purchase['merchant'], GENERIC_LABELS)
        self.assertNotIn('Rahul', purchase['merchant'])

        evidence = ' '.join(refund['matching_evidence'])
        self.assertNotIn('Rahul', evidence)
        self.assertNotIn('REF-777', evidence)
        self.assertNotIn('REF777', evidence)

    def test_04b_weak_personal_evidence_does_not_leak_name_tokens(self):
        self._debit('UPI/Rahul Kumar/PAY-111', 400, date(2026, 10, 2))
        self._credit('REFUND UPI/Rahul Sharma/PAY-999', 400, date(2026, 10, 6))

        result = monthly_budget(self.session_id, 2026, 10)
        refund = result['refund_details'][0]

        self.assertEqual(refund['match_confidence'], MATCH_WEAK)
        self.assertIn(refund['merchant'], GENERIC_LABELS)
        evidence = ' '.join(refund['matching_evidence'])
        for leaked in ('Rahul', 'rahul', 'Kumar', 'Sharma', 'PAY-111', 'PAY-999'):
            self.assertNotIn(leaked, evidence)

    def test_05_genuine_business_refund_label_stays_readable(self):
        self._debit('MakeMyTrip Flight Booking REF-888', 5000, date(2026, 10, 1))
        self._credit('REFUND MakeMyTrip REF-888', 5000, date(2026, 10, 5))

        result = monthly_budget(self.session_id, 2026, 10)
        refund = result['refund_details'][0]

        self.assertEqual(refund['match_confidence'], MATCH_CONFIRMED)
        self.assertEqual(refund['allocation_status'], ALLOC_APPLIED)
        self.assertEqual(refund['merchant'], 'MakeMyTrip Flight Booking')
        self.assertEqual(
            refund['matched_purchases'][0]['merchant'], 'MakeMyTrip Flight Booking'
        )


class CanonicalLabelPrivacyTests(TestCase):
    """Recurring-payment badges use a safe label, never the internal key."""

    def setUp(self):
        self.session_id = f'task11_canonical_{uuid.uuid4().hex[:8]}'
        self.snap = _make_snapshot(self.session_id)

    def _series(self, merchant, amounts=(1400, 1400, 1400)):
        for month, amount in zip((8, 9, 10), amounts):
            _make_tx(
                self.snap, self.session_id, merchant, amount, 'DEBIT',
                date(2026, month, 10),
            )

    def test_06_canonical_label_is_safe_for_numeric_narration(self):
        self._series('NEFT 123456789012')
        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        sub = result[0]
        self.assertEqual(sub['canonical_merchant'], 'neft')
        self.assertEqual(sub['canonical_label'], UNIDENTIFIED_COUNTERPARTY_LABEL)
        self.assertNotIn('123456789012', sub['canonical_label'])

    def test_07_canonical_label_keeps_recognized_brand_readable(self):
        self._series('CULTFIT')
        result = detect_subscriptions(self.session_id)
        sub = result[0]
        self.assertEqual(sub['canonical_merchant'], 'cult_fit')
        self.assertEqual(sub['canonical_label'], 'Cult Fit')
        self.assertEqual(sub['confidence'], 'CONFIRMED')

    def test_08_subscriptions_endpoint_never_returns_raw_narration(self):
        self._series('UPI/APARTMENT RENT/LANDLORD/9811234567@upi')
        token = self._subscribe_token()
        response = self.client.post(
            '/api/v1/insights/subscriptions/',
            {},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        blob = json.dumps(response.json())
        self.assertNotIn('9811234567', blob)
        self.assertNotIn('LANDLORD', blob)

    def _subscribe_token(self):
        from api.models import ConsentAuditLog
        client = APIClient()
        _session, token = SecureSession.issue_session(self.session_id)
        # Register explicit consent directly in the database to satisfy the
        # per-session consent gate for tests.
        ConsentAuditLog.objects.create(
            session_id=_session.session_id,
            consent_version='v1.0-task11',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        self.client = client
        return token


class CounterpartyLabelHelperTests(TestCase):
    """Direct coverage of the shared safe-label helper."""

    def test_09_phone_number_is_not_displayed(self):
        label = _safe_counterparty_label('Payment to Rahul 9876543210')
        self.assertEqual(label, PERSONAL_TRANSFER_LABEL)
        self.assertNotIn('9876543210', label)
        self.assertNotIn('Rahul', label)

    def test_10_account_reference_is_not_displayed(self):
        label = _safe_counterparty_label('NEFT Rahul A/C 123456789012')
        self.assertEqual(label, UNIDENTIFIED_COUNTERPARTY_LABEL)
        self.assertNotIn('123456789012', label)

    def test_11_pan_and_aadhaar_like_values_are_not_displayed(self):
        pan_label = _safe_counterparty_label('Payment to Rahul PAN ABCDE1234F')
        self.assertNotIn('ABCDE1234F', pan_label)
        self.assertIn(pan_label, GENERIC_LABELS)

        aadhaar_label = _safe_counterparty_label('UPI 1234 5678 9012')
        self.assertNotIn('1234', aadhaar_label)
        self.assertIn(aadhaar_label, GENERIC_LABELS)

    def test_12_redaction_placeholders_are_not_displayed(self):
        self.assertEqual(
            _safe_counterparty_label('[REDACTED_UPI_ID]'),
            UNIDENTIFIED_COUNTERPARTY_LABEL,
        )
        self.assertEqual(
            _safe_counterparty_label('Chai Point [REDACTED_VPA]'), 'Chai Point'
        )
        for value in ('[REDACTED_PAN]', '[USER_PRIMARY]', 'UPI/[REDACTED_UPI_ID]'):
            label = _safe_counterparty_label(value)
            self.assertNotIn('REDACTED', label.upper())
            self.assertNotIn('[', label)

    def test_13_clean_merchant_names_remain_readable(self):
        self.assertEqual(_safe_counterparty_label('MacBook Purchase'), 'MacBook Purchase')
        self.assertEqual(_safe_counterparty_label('Chai Point'), 'Chai Point')
        self.assertEqual(
            _safe_counterparty_label('MakeMyTrip Flight Booking'),
            'MakeMyTrip Flight Booking',
        )

    def test_14_personal_payment_narration_falls_back(self):
        for narration in (
            'Payment to Rahul',
            'Paid to Ananya Sen',
            'Transfer from Rohit Verma',
        ):
            label = _safe_counterparty_label(narration)
            self.assertEqual(label, PERSONAL_TRANSFER_LABEL)
            self.assertNotIn('Rahul', label)
            self.assertNotIn('Ananya', label)
            self.assertNotIn('Rohit', label)
