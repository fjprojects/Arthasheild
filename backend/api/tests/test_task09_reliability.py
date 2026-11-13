"""
Task 09 — Targeted reliability corrections.

Synthetic regression tests for:
  1. Ambiguous deduplication (five cases)
  2. Counterparty display / privacy placeholder sanitization
  3. Conservative personal-UPI classification

Uses only synthetic data. No real bank statements or personal information.
"""
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction
from api.views import ConsentAuditView, ParseStatementView, _compute_fingerprint
from api.insights import (
    COUNTERPARTY_COMMERCIAL,
    COUNTERPARTY_NOT_A_VPA,
    COUNTERPARTY_PERSONAL,
    COUNTERPARTY_UNCERTAIN,
    DEDUPLICATION_POLICY,
    PAYMENT_TYPE_SUBSCRIPTION,
    PAYMENT_TYPE_UNKNOWN,
    PAYMENT_TYPE_UTILITY,
    RECURRING_CONFIRMED,
    RECURRING_WEAK,
    _display_counterparty,
    _is_duplicate_import,
    _sanitize_counterparty_name,
    categorize_transactions,
    classify_upi_counterparty,
    detect_subscriptions,
    detect_unusual_spending,
    is_peer_upi,
)
from data_processor.models import NormalizedTransaction
from data_processor.normalizer import TransactionNormalizer


def _make_snapshot(session_id):
    snap, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
    return snap


def _make_tx(
    snapshot,
    session_id,
    merchant,
    amount,
    tx_type,
    tx_date,
    is_recurring=False,
    fingerprint='',
    source_type='import',
):
    return Transaction.objects.create(
        snapshot=snapshot,
        session_id=session_id,
        transaction_date=tx_date,
        amount=Decimal(str(amount)),
        transaction_type=tx_type,
        normalized_merchant=merchant,
        category='Uncategorized',
        is_recurring=is_recurring,
        source_type=source_type,
        fingerprint=fingerprint,
    )


class _FingerprintSubject:
    """Minimal stand-in for the fields _compute_fingerprint reads."""

    def __init__(self, date_, amount, tx_type, merchant, reference_id=''):
        self.transaction_date = date_
        self.amount = Decimal(str(amount))
        self.transaction_type = tx_type
        self.normalized_merchant = merchant
        self.reference_id = reference_id


# ---------------------------------------------------------------------------
# Priority 1 — ambiguous deduplication
# ---------------------------------------------------------------------------
class DeduplicationReliabilityTests(TestCase):
    """
    Five synthetic cases for the corrected deduplication policy:

    1. Distinct reliable references  -> both preserved
    2. Matching reliable references  -> collapsed as a duplicate import
    3. Matching import fingerprints  -> collapsed
    4. No reference and no fingerprint -> both preserved, totals stay accurate
    5. Re-importing the same statement -> skipped, while two legitimate identical
       payments inside one statement are both kept
    """

    def setUp(self):
        self.session_id = f'task09_dedup_{uuid.uuid4().hex[:8]}'
        self.snap = _make_snapshot(self.session_id)

    def test_01_distinct_reliable_references_are_preserved(self):
        tx_a = NormalizedTransaction(
            '', date(2026, 10, 4), 'UPI/CHAI POINT REF-A100', Decimal('480.00'),
            'DEBIT', 'SMS', reference_id='A100',
        )
        tx_b = NormalizedTransaction(
            '', date(2026, 10, 4), 'UPI/CHAI POINT REF-B200', Decimal('480.00'),
            'DEBIT', 'SMS', reference_id='B200',
        )

        uniques, dup_count = TransactionNormalizer.deduplicate_transactions([tx_a, tx_b])
        self.assertEqual(len(uniques), 2)
        self.assertEqual(dup_count, 0)

        stored_a = _make_tx(
            self.snap, self.session_id, 'CHAI POINT CHAI POINT REF A100', 480,
            'DEBIT', date(2026, 10, 4),
        )
        stored_b = _make_tx(
            self.snap, self.session_id, 'CHAI POINT CHAI POINT REF B200', 480,
            'DEBIT', date(2026, 10, 4),
        )
        self.assertFalse(_is_duplicate_import(stored_a, stored_b))

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['occurrence_count'], 2)
        self.assertEqual(result[0]['observed_total_spend'], '960.00')

    def test_02_matching_reliable_references_are_duplicates(self):
        tx_a = NormalizedTransaction(
            '', date(2026, 10, 4), 'UPI/CHAI POINT REF-982421', Decimal('480.00'),
            'DEBIT', 'SMS', reference_id='982421',
        )
        tx_b = NormalizedTransaction(
            '', date(2026, 10, 4), 'CHAI POINT DUPLICATE ROW REF-982421', Decimal('480.00'),
            'DEBIT', 'SMS', reference_id='982421',
        )

        uniques, dup_count = TransactionNormalizer.deduplicate_transactions([tx_a, tx_b])
        self.assertEqual(len(uniques), 1)
        self.assertEqual(dup_count, 1)

        stored_a = _make_tx(
            self.snap, self.session_id, 'CHAI POINT REF-982421', 480,
            'DEBIT', date(2026, 10, 4),
        )
        stored_b = _make_tx(
            self.snap, self.session_id, 'CHAI POINT REF-982421', 480,
            'DEBIT', date(2026, 10, 4),
        )
        self.assertTrue(_is_duplicate_import(stored_a, stored_b))

    def test_03_matching_import_fingerprints_are_duplicates(self):
        subject = _FingerprintSubject(
            date(2026, 10, 4), 480, 'DEBIT', 'CHAI POINT', reference_id='982421'
        )
        fp_with_ref = _compute_fingerprint(self.session_id, subject)
        self.assertEqual(fp_with_ref, _compute_fingerprint(self.session_id, subject))

        # The DB uniqueness constraint already rejects identical non-empty
        # fingerprints, so compare unsaved model instances here.
        unsaved_a = Transaction(
            session_id=self.session_id, transaction_date=date(2026, 10, 4),
            amount=Decimal('480.00'), transaction_type='DEBIT',
            normalized_merchant='CHAI POINT', fingerprint=fp_with_ref,
        )
        unsaved_b = Transaction(
            session_id=self.session_id, transaction_date=date(2026, 10, 4),
            amount=Decimal('480.00'), transaction_type='DEBIT',
            normalized_merchant='CHAI POINT', fingerprint=fp_with_ref,
        )
        self.assertTrue(_is_duplicate_import(unsaved_a, unsaved_b))

        # Different occurrence ordinals of otherwise identical content never collide.
        no_ref = _FingerprintSubject(date(2026, 10, 4), 480, 'DEBIT', 'CHAI POINT')
        fp_first = _compute_fingerprint(self.session_id, no_ref, occurrence_index=0)
        fp_second = _compute_fingerprint(self.session_id, no_ref, occurrence_index=1)
        self.assertNotEqual(fp_first, fp_second)
        self.assertEqual(fp_first, _compute_fingerprint(self.session_id, no_ref))

    def test_04_missing_identity_evidence_preserves_legitimate_payment(self):
        # Same merchant, same date, same amount, no reference and no fingerprint.
        stored_a = _make_tx(
            self.snap, self.session_id, 'CHAI POINT', 480, 'DEBIT', date(2026, 10, 4)
        )
        stored_b = _make_tx(
            self.snap, self.session_id, 'CHAI POINT', 480, 'DEBIT', date(2026, 10, 4)
        )
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id).count(), 2
        )
        self.assertFalse(_is_duplicate_import(stored_a, stored_b))

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['occurrence_count'], 2)
        self.assertEqual(result[0]['observed_total_spend'], '960.00')

    def test_05_reimport_is_skipped_but_identical_payments_are_kept(self):
        csv_text = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-04,UPI/CHAI POINT/OUTLET,480.00,,74520.00\n"
            "2026-10-04,UPI/CHAI POINT/OUTLET,480.00,,74040.00\n"
        )
        session, token = SecureSession.issue_session(self.session_id)
        factory = APIRequestFactory()

        from api.models import ConsentAuditLog
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version='v1.0-test',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )


        preview = ParseStatementView.as_view()(factory.post(
            '/api/v1/data/parse-statement/',
            {
                'raw_text': csv_text,
                'format': 'csv',
                'session_id': self.session_id,
                'persist': True,
            },
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        ))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data['persistence']['imported'], 2)
        self.assertEqual(preview.data['persistence']['skipped_duplicates'], 0)
        self.assertEqual(Decimal(preview.data['total_debits']), Decimal('960.00'))

        stored = Transaction.objects.filter(session_id=self.session_id)
        self.assertEqual(stored.count(), 2)
        fingerprints = {tx.fingerprint for tx in stored}
        self.assertEqual(len(fingerprints), 2)

        reimport = ParseStatementView.as_view()(factory.post(
            '/api/v1/data/parse-statement/',
            {
                'raw_text': csv_text,
                'format': 'csv',
                'session_id': self.session_id,
                'persist': True,
            },
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        ))
        self.assertEqual(reimport.status_code, 200)
        self.assertEqual(reimport.data['persistence']['imported'], 0)
        self.assertEqual(reimport.data['persistence']['skipped_duplicates'], 2)
        self.assertEqual(Transaction.objects.filter(session_id=self.session_id).count(), 2)

    def test_06_ambiguity_is_documented_not_claimed_solved(self):
        self.assertIn('Known limitation', DEDUPLICATION_POLICY)
        self.assertIn('cannot prove', DEDUPLICATION_POLICY)


# ---------------------------------------------------------------------------
# Priority 2 — counterparty display and privacy placeholders
# ---------------------------------------------------------------------------
class CounterpartyDisplaySanitizationTests(TestCase):
    """Display titles must never echo placeholders, references or raw PII."""

    def setUp(self):
        self.session_id = f'task09_privacy_{uuid.uuid4().hex[:8]}'
        self.snap = _make_snapshot(self.session_id)

    def test_01_chai_point_with_transaction_references(self):
        self.assertEqual(
            _sanitize_counterparty_name('CHAI POINT REF-752'), 'Chai Point'
        )
        self.assertEqual(
            _sanitize_counterparty_name('CHAI POINT ORD-9900'), 'Chai Point'
        )
        self.assertEqual(
            _sanitize_counterparty_name(
                'CHAI POINT INV-123 Invoice No. INV-2026-7781'
            ),
            'Chai Point',
        )

    def test_02_cultfit_with_vpa_in_narration(self):
        display = _sanitize_counterparty_name(
            'UPI/CULTFIT/rahul.sharma@okaxis'
        )
        self.assertEqual(display, 'Cultfit')
        self.assertNotIn('@', display)
        self.assertNotIn('okaxis', display.lower())

    def test_03_merchant_with_bank_account_reference(self):
        display = _sanitize_counterparty_name('ACME STORE A/C 123456789012')
        self.assertEqual(display, 'Acme Store')
        self.assertNotIn('123456789012', display)

        refreshed = _sanitize_counterparty_name('ACME STORE [REDACTED_ACCOUNT]')
        self.assertEqual(refreshed, 'Acme Store')

    def test_04_phone_numbers_and_personal_names(self):
        display = _sanitize_counterparty_name('UPI/ROHIT VERMA/9876543210')
        self.assertNotIn('9876543210', display)
        self.assertNotIn('@', display)
        self.assertNotEqual(display, 'UPI/ROHIT VERMA/9876543210')
        self.assertFalse(any(ch.isdigit() for ch in display))

    def test_05_fully_unidentified_counterparty(self):
        self.assertEqual(
            _sanitize_counterparty_name('UPI/123456789012'), 'Unidentified Counterparty'
        )
        self.assertEqual(
            _sanitize_counterparty_name('[REDACTED_VPA] [REDACTED_ACCOUNT]'),
            'Unidentified Counterparty',
        )
        self.assertEqual(
            _sanitize_counterparty_name(''), 'Unidentified Counterparty'
        )

    def test_06_redaction_placeholders_never_reach_display(self):
        self.assertEqual(
            _sanitize_counterparty_name('Chai Point [REDACTED_VPA]'),
            'Chai Point',
        )
        self.assertEqual(
            _sanitize_counterparty_name('[REDACTED_VPA] Chai Point [REDACTED_ACCOUNT]'),
            'Chai Point',
        )

    def test_07_evidence_descriptions_do_not_expose_narration(self):
        for day in (date(2026, 8, 10), date(2026, 9, 10), date(2026, 10, 10)):
            _make_tx(
                self.snap, self.session_id,
                'UPI/CULTFIT/rahul.sharma@okaxis', 1499, 'DEBIT', day,
            )

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        sub = result[0]
        self.assertNotIn('okaxis', sub['merchant'].lower())
        self.assertNotIn('rahul.sharma', sub['merchant'].lower())

        evidence_text = ' '.join(sub['evidence'])
        self.assertNotIn('okaxis', evidence_text.lower())
        self.assertNotIn('rahul.sharma', evidence_text.lower())
        self.assertNotIn('UPI/CULTFIT', evidence_text)


# ---------------------------------------------------------------------------
# Priority 5 — conservative personal UPI handling
# ---------------------------------------------------------------------------
class ConservativeUpiClassificationTests(TestCase):
    """Personal, commercial and ambiguous VPAs must be separated conservatively."""

    def setUp(self):
        self.session_id = f'task09_upi_{uuid.uuid4().hex[:8]}'
        self.snap = _make_snapshot(self.session_id)

    def _debit(self, merchant, day, amount=1499):
        return _make_tx(
            self.snap, self.session_id, merchant, amount, 'DEBIT', day,
        )

    def test_01_personal_vpas_are_recognized(self):
        for narration in (
            'UPI/rahul.sharma@okaxis',
            'UPI/ananya_sen@okhdfcbank',
            'UPI/pooja-patel@paytm',
            'UPI/9876543210@upi',
        ):
            self.assertEqual(
                classify_upi_counterparty(narration), COUNTERPARTY_PERSONAL,
                msg=f'expected personal classification for {narration}',
            )
            self.assertTrue(is_peer_upi(narration))

        # No VPA, but an explicit name + mobile-number narration is still a peer payment.
        self.assertTrue(is_peer_upi('UPI/SOMEONE/9876543210'))

    def test_02_known_commercial_billers_are_preserved(self):
        for narration in (
            'UPI/bescom.bill@hdfcbank',
            'UPI/netflix@icici',
            'UPI/cultfit@axisbank',
            'UPI/starhealth.renew@okaxis',
        ):
            self.assertEqual(
                classify_upi_counterparty(narration), COUNTERPARTY_COMMERCIAL,
                msg=f'expected commercial classification for {narration}',
            )
            self.assertFalse(is_peer_upi(narration))

        # A known biller repeated monthly stays a real commitment, not a peer transfer.
        for day in (date(2026, 8, 5), date(2026, 9, 5), date(2026, 10, 5)):
            self._debit('UPI/bescom.bill@hdfcbank', day, amount=1400)
        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['payment_type'], PAYMENT_TYPE_UTILITY)
        self.assertEqual(result[0]['confidence'], RECURRING_CONFIRMED)

    def test_03_ambiguous_vpa_handles_are_uncertain(self):
        for narration in (
            'UPI/rahul1234@okaxis',
            'UPI/rahulkumar@paytm',
            'UPI/shop@ybl',
            'UPI/a1b2c3@okicici',
        ):
            self.assertEqual(
                classify_upi_counterparty(narration), COUNTERPARTY_UNCERTAIN,
                msg=f'expected uncertain classification for {narration}',
            )
            # Ambiguous handles are not treated as peers, but they are also not
            # presented as confident commercial recurring commitments.
            self.assertFalse(is_peer_upi(narration))

    def test_04_uncertain_payee_is_not_a_confirmed_subscription(self):
        for day in (date(2026, 8, 12), date(2026, 9, 12), date(2026, 10, 12)):
            self._debit('UPI/rahulkumar@paytm', day)

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        sub = result[0]
        self.assertEqual(sub['payment_type'], PAYMENT_TYPE_UNKNOWN)
        self.assertEqual(sub['confidence'], RECURRING_WEAK)
        self.assertIsNone(sub['estimated_monthly_cost'])
        self.assertIsNone(sub['estimated_annual_cost'])
        self.assertTrue(
            any('ambiguous' in ev.lower() for ev in sub['evidence'])
        )

    def test_05_non_vpa_narration_is_not_classified(self):
        self.assertEqual(
            classify_upi_counterparty('POS NETFLIX SUBSCRIPTION'),
            COUNTERPARTY_NOT_A_VPA,
        )

    def test_06_single_token_name_vpa_is_not_assumed_personal(self):
        # A bare name-like token on a personal PSP handle carries insufficient
        # evidence and must remain uncertain rather than assumed personal.
        self.assertEqual(
            classify_upi_counterparty('UPI/rahul@okaxis'), COUNTERPARTY_UNCERTAIN
        )


# ---------------------------------------------------------------------------
# Priority 2 follow-up — display fallbacks for stored sanitizer markers
# ---------------------------------------------------------------------------
class IntelligenceDisplayFallbackTests(TestCase):
    """
    Ingestion stores sanitizer output, so a narration can hold [REDACTED_*] markers.
    Those markers are internal state: every user-facing surface must replace them with
    "Unidentified Counterparty" and must never restore the redacted original value.
    """

    def setUp(self):
        self.session_id = f'task09_display_{uuid.uuid4().hex[:8]}'
        self.snap = _make_snapshot(self.session_id)

    def test_01_display_helper_never_returns_internal_markers(self):
        self.assertEqual(
            _display_counterparty('[REDACTED_UPI_ID]'), 'Unidentified Counterparty'
        )
        self.assertEqual(
            _display_counterparty('UPI/[REDACTED_UPI_ID]'), 'Unidentified Counterparty'
        )
        self.assertEqual(
            _display_counterparty('[USER_PRIMARY] [REDACTED_ACCOUNT]'),
            'Unidentified Counterparty',
        )
        self.assertEqual(
            _display_counterparty('Chai Point [REDACTED_VPA]'), 'Chai Point'
        )
        self.assertEqual(_display_counterparty(''), 'Unidentified Counterparty')

    def test_02_categorization_journal_hides_placeholders(self):
        _make_tx(
            self.snap, self.session_id, '[REDACTED_UPI_ID]', 480,
            'DEBIT', date(2026, 10, 4),
        )
        _make_tx(
            self.snap, self.session_id, 'UPI/[REDACTED_UPI_ID]', 250,
            'DEBIT', date(2026, 10, 5),
        )
        _make_tx(
            self.snap, self.session_id, 'Chai Point', 120,
            'DEBIT', date(2026, 10, 6),
        )

        result = categorize_transactions(self.session_id)
        merchants = [row['merchant'] for row in result]
        self.assertEqual(len(result), 3)
        for name in merchants:
            self.assertNotIn('[', name)
            self.assertNotIn(']', name)
            self.assertNotIn('REDACTED', name.upper())
            self.assertNotIn('USER_PRIMARY', name.upper())
        self.assertEqual(merchants.count('Unidentified Counterparty'), 2)
        self.assertIn('Chai Point', merchants)

    def test_03_clean_identity_is_still_displayed(self):
        _make_tx(
            self.snap, self.session_id, 'CULTFIT', 1499,
            'DEBIT', date(2026, 10, 4),
        )
        result = categorize_transactions(self.session_id)
        # A clean name is shown exactly as stored, so casing is never rewritten.
        self.assertEqual(result[0]['merchant'], 'CULTFIT')
        stored = Transaction.objects.get(id=result[0]['id'])
        self.assertEqual(stored.normalized_merchant, 'CULTFIT')

    def test_04_unusual_spending_hides_placeholders(self):
        for day in (date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)):
            _make_tx(
                self.snap, self.session_id, 'Corner Shop', 100, 'DEBIT', day
            )
        flagged_tx = _make_tx(
            self.snap, self.session_id, '[REDACTED_UPI_ID]', 5000,
            'DEBIT', date(2026, 10, 4),
        )

        flagged = detect_unusual_spending(self.session_id)
        entry = next(f for f in flagged if f['id'] == str(flagged_tx.id))
        self.assertEqual(entry['merchant'], 'Unidentified Counterparty')
        self.assertNotIn('REDACTED', entry['merchant'].upper())
        for item in flagged:
            self.assertNotIn('[', item['merchant'])
            self.assertNotIn('REDACTED', item['merchant'].upper())

    def test_05_redacted_values_are_never_restored(self):
        _make_tx(
            self.snap, self.session_id, '[REDACTED_UPI_ID]', 480,
            'DEBIT', date(2026, 10, 4),
        )
        payload = str(categorize_transactions(self.session_id))
        for leaked_value in ('9876543210', '@okaxis', 'rahul.sharma'):
            self.assertNotIn(leaked_value, payload)
        self.assertIn('Unidentified Counterparty', payload)
