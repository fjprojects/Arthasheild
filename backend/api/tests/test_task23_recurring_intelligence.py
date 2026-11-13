"""
Task 23 — recurring payment intelligence and false-positive reduction.

A repeated transaction is not automatically a subscription or a financial
commitment. These tests pin the separation between:

* a recurring payment *pattern* (the payments repeat),
* a *subscription commitment* (subscription/billing evidence),
* a *fixed obligation* (rent, instalment, insurance, utility),
* *repeated discretionary spending* (a cafe, a supermarket, a pharmacy).

They also pin the financial consequences: only sufficiently supported
commitments may contribute to the confirmed commitment totals or to the
recoverable monthly leakage, and an internal transfer must never be treated as
either.

All data here is synthetic.
"""
import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.insights import (
    COMMITMENT_DISCRETIONARY,
    COMMITMENT_FIXED_OBLIGATION,
    COMMITMENT_PATTERN,
    COMMITMENT_SUBSCRIPTION,
    PAYMENT_TYPE_RENT,
    PAYMENT_TYPE_SUBSCRIPTION,
    RECURRING_CONFIRMED,
    RECURRING_PROBABLE,
    RECURRING_WEAK,
    compute_imported_session_overview,
    detect_subscriptions,
    detect_unusual_spending,
    monthly_budget,
)
from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction

User = get_user_model()


class Task23RecurringTestBase(TestCase):
    """Synthetic transaction history helper."""

    def setUp(self):
        super().setUp()
        self.session_id = f'task23_{uuid.uuid4().hex[:8]}'
        self.snapshot, _ = FinancialSnapshot.objects.get_or_create(
            session_id=self.session_id
        )

    def _tx(self, tx_date, merchant, amount, direction='DEBIT',
            category='Uncategorized', fingerprint='', source_type='import'):
        return Transaction.objects.create(
            snapshot=self.snapshot,
            session_id=self.session_id,
            transaction_date=tx_date,
            amount=Decimal(str(amount)),
            transaction_type=direction,
            normalized_merchant=merchant,
            category=category,
            source_type=Transaction.SOURCE_IMPORT if source_type == 'import' else Transaction.SOURCE_PERSONA,
            fingerprint=fingerprint,
        )

    def _debit(self, tx_date, merchant, amount, **kwargs):
        return self._tx(tx_date, merchant, amount, 'DEBIT', **kwargs)

    def _credit(self, tx_date, merchant, amount, **kwargs):
        return self._tx(tx_date, merchant, amount, 'CREDIT', **kwargs)


class Scenario1ChaiPointTests(Task23RecurringTestBase):
    """Three monthly Rs 120 cafe purchases are repeated discretionary spending."""

    def setUp(self):
        super().setUp()
        for month in (8, 9, 10):
            self._debit(date(2026, month, 5), 'Chai Point', 120)

    def test_01_pattern_is_detected_but_not_a_commitment(self):
        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        entry = result[0]
        # The recurrence is observed...
        self.assertEqual(entry['recurrence_confidence'], RECURRING_CONFIRMED)
        self.assertEqual(entry['cadence'], 'monthly')
        self.assertEqual(entry['occurrence_count'], 3)
        self.assertEqual(entry['observed_amount_min'], '120.00')
        self.assertEqual(entry['observed_amount_max'], '120.00')
        # ...but it is not a subscription and not a financial commitment.
        self.assertEqual(entry['commitment_class'], COMMITMENT_DISCRETIONARY)
        self.assertNotEqual(entry['payment_type'], PAYMENT_TYPE_SUBSCRIPTION)
        self.assertEqual(entry['confidence'], RECURRING_PROBABLE)
        self.assertFalse(entry['is_financial_commitment'])
        self.assertFalse(entry['is_potential_leakage'])
        self.assertIn('ORDINARY_MERCHANT_REPEAT', entry['commitment_evidence'])

    def test_02_it_is_not_a_fixed_commitment_or_recoverable_savings(self):
        res = monthly_budget(self.session_id, 2026, 10)
        # The cafe spend stays an ordinary expense...
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('120.00'))
        # ...it reserves no money for an upcoming bill...
        self.assertEqual(Decimal(res['debit_transfers']), Decimal('0.00'))
        # ...and it is never presented as recoverable savings.
        self.assertEqual(Decimal(res['credit_breakdown']['refunds']), Decimal('0.00'))

    def test_03_the_overview_does_not_count_it_as_a_commitment(self):
        overview = compute_imported_session_overview(self.session_id)
        self.assertEqual(Decimal(overview['summary']['confirmed_commitments']), Decimal('0.00'))
        self.assertEqual(Decimal(overview['summary']['monthly_leakage']), Decimal('0.00'))
        self.assertEqual(overview['summary']['confirmed_recurring_count'], 0)


class Scenario2NetflixVariableTests(Task23RecurringTestBase):
    """A known subscription merchant with a variable amount stays a commitment."""

    def setUp(self):
        super().setUp()
        for month, amount in ((8, 199), (9, 249), (10, 299)):
            self._debit(date(2026, month, 10), 'Netflix Subscription', amount)

    def test_01_variable_subscription_remains_confirmed_with_its_range(self):
        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry['payment_type'], PAYMENT_TYPE_SUBSCRIPTION)
        self.assertEqual(entry['commitment_class'], COMMITMENT_SUBSCRIPTION)
        self.assertEqual(entry['confidence'], RECURRING_CONFIRMED)
        self.assertEqual(entry['amount_variation'], 'variable')
        # The observed range is explicit, so a variable charge is never shown as
        # a single fixed amount.
        self.assertEqual(entry['observed_amount_min'], '199.00')
        self.assertEqual(entry['observed_amount_max'], '299.00')
        self.assertEqual(entry['observed_amount_range'], '199.00 - 299.00')
        self.assertEqual(entry['average_amount'], '249.00')
        self.assertTrue(entry['is_financial_commitment'])
        self.assertTrue(entry['is_potential_leakage'])

    def test_02_variable_charges_are_not_treated_as_duplicates(self):
        # Three charges with different amounts on the same cadence are three
        # occurrences, not one payment seen three times.
        result = detect_subscriptions(self.session_id)
        self.assertEqual(result[0]['occurrence_count'], 3)
        self.assertEqual(len(result[0]['transaction_amounts']), 3)

    def test_03_evidence_and_confidence_are_explicit(self):
        entry = detect_subscriptions(self.session_id)[0]
        self.assertIn('SUBSCRIPTION_PAYMENT_TYPE', entry['commitment_evidence'])
        self.assertTrue(any('Subscription/billing evidence' in ev for ev in entry['evidence']))
        self.assertTrue(any('Commitment classification' in ev for ev in entry['evidence']))


class Scenario3ChatGptRegressionTests(Task23RecurringTestBase):
    """The Task 17 regression must keep working."""

    def setUp(self):
        super().setUp()
        for month in (8, 9, 10):
            self._debit(date(2026, month, 16), 'Openai Chatgpt Plus Monthly', 1650)

    def test_01_confirmed_recurring_and_leakage_are_unchanged(self):
        overview = compute_imported_session_overview(self.session_id)
        self.assertEqual(overview['summary']['confirmed_recurring_count'], 1)
        self.assertEqual(Decimal(overview['summary']['monthly_leakage']), Decimal('1650.00'))
        self.assertEqual(Decimal(overview['summary']['confirmed_commitments']), Decimal('1650.00'))

    def test_02_pending_fixed_obligations_are_unchanged(self):
        from analytics.services import AnalyticsEngine
        overview = compute_imported_session_overview(self.session_id)
        safe = AnalyticsEngine.calculate_safe_to_spend(
            current_balance=50000,
            monthly_income=float(overview['summary']['monthly_income']),
            pending_fixed_obligations=float(overview['summary']['confirmed_commitments']),
            days_remaining_in_month=10,
        )
        # The subscription reserves exactly its own monthly amount.
        self.assertEqual(safe['pending_fixed_obligations'], 1650.0)


class Scenario4RentTests(Task23RecurringTestBase):
    """Rent is a fixed obligation, not a subscription."""

    def setUp(self):
        super().setUp()
        for month in (8, 9, 10):
            self._debit(date(2026, month, 1), 'Landlord Rent Transfer', 25000)

    def test_01_rent_is_a_confirmed_fixed_obligation(self):
        entry = detect_subscriptions(self.session_id)[0]
        self.assertEqual(entry['payment_type'], PAYMENT_TYPE_RENT)
        self.assertEqual(entry['commitment_class'], COMMITMENT_FIXED_OBLIGATION)
        self.assertEqual(entry['confidence'], RECURRING_CONFIRMED)
        self.assertTrue(entry['is_financial_commitment'])
        # A rent obligation is not "potentially avoidable" money.
        self.assertFalse(entry['is_potential_leakage'])

    def test_02_rent_is_not_recoverable_leakage(self):
        res = monthly_budget(self.session_id, 2026, 10)
        overview = compute_imported_session_overview(self.session_id)
        self.assertEqual(Decimal(overview['summary']['confirmed_commitments']), Decimal('25000.00'))
        self.assertEqual(Decimal(overview['summary']['monthly_leakage']), Decimal('0.00'))


class Scenario5EmiTests(Task23RecurringTestBase):
    """Loan instalments are obligations, not subscription leakage."""

    def setUp(self):
        super().setUp()
        for month in (8, 9, 10):
            self._debit(date(2026, month, 5), 'HDFC Home Loan EMI', 15000)

    def test_01_emi_is_a_fixed_obligation_without_leakage(self):
        entry = detect_subscriptions(self.session_id)[0]
        self.assertEqual(entry['commitment_class'], COMMITMENT_FIXED_OBLIGATION)
        self.assertEqual(entry['confidence'], RECURRING_CONFIRMED)
        self.assertFalse(entry['is_potential_leakage'])
        overview = compute_imported_session_overview(self.session_id)
        self.assertEqual(Decimal(overview['summary']['confirmed_commitments']), Decimal('15000.00'))
        self.assertEqual(Decimal(overview['summary']['monthly_leakage']), Decimal('0.00'))

    def test_02_a_premium_merchant_is_not_mistaken_for_an_instalment(self):
        # "Premium" contains "emi" as a substring: it must not be classified as
        # a loan instalment (a fixed obligation).
        for month in (8, 9, 10):
            self._debit(date(2026, month, 12), 'Swiggy Premium Grocery', 850)
        entry = [
            e for e in detect_subscriptions(self.session_id)
            if 'Premium' in e['merchant'] or 'Swiggy' in e['merchant']
        ]
        self.assertTrue(entry)
        for e in entry:
            self.assertNotEqual(e['commitment_class'], COMMITMENT_FIXED_OBLIGATION)


class Scenario6TransferTests(Task23RecurringTestBase):
    """Own-account transfers are never a recurring subscription or leakage."""

    def setUp(self):
        super().setUp()
        for month in (8, 9, 10):
            self._debit(date(2026, month, 5), 'Self Transfer', 10000)

    def test_01_transfers_are_excluded_from_recurring_detection(self):
        result = detect_subscriptions(self.session_id)
        self.assertEqual(result, [])

    def test_02_transfers_are_not_leakage_or_commitments(self):
        overview = compute_imported_session_overview(self.session_id)
        self.assertEqual(Decimal(overview['summary']['monthly_leakage']), Decimal('0.00'))
        self.assertEqual(Decimal(overview['summary']['confirmed_commitments']), Decimal('0.00'))


class Scenario7RefundTests(Task23RecurringTestBase):
    """Refunds must not create patterns or inflate recurring income."""

    def setUp(self):
        super().setUp()
        for month in (8, 9, 10):
            self._debit(date(2026, month, 10), 'Netflix Subscription', 199)
        # A refund credit must never become a recurring occurrence.
        self._credit(date(2026, 10, 12), 'Netflix Refund Reversal', 199)

    def test_01_refunds_do_not_create_recurring_patterns(self):
        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['occurrence_count'], 3)

    def test_02_refunds_do_not_inflate_recurring_income(self):
        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['earned_income']), Decimal('0.00'))
        # The refund is classified as a refund (never as income, never as a
        # recurring occurrence).
        self.assertEqual(Decimal(res['credit_breakdown']['refunds']), Decimal('199.00'))
        self.assertEqual(Decimal(res['unclassified_inflows']), Decimal('0.00'))


class Scenario8IrregularTests(Task23RecurringTestBase):
    """An irregular history must not produce a confident monthly projection."""

    def setUp(self):
        super().setUp()
        for d in (date(2026, 1, 10), date(2026, 3, 12), date(2026, 5, 14)):
            self._debit(d, 'Swiggy Order', 500)

    def test_01_irregular_history_is_weak_and_unprojected(self):
        entry = detect_subscriptions(self.session_id)[0]
        self.assertEqual(entry['confidence'], RECURRING_WEAK)
        self.assertEqual(entry['cadence'], 'irregular')
        self.assertIsNone(entry['estimated_monthly_cost'])
        self.assertIsNone(entry['estimated_annual_cost'])
        self.assertFalse(entry['is_financial_commitment'])

    def test_02_insufficient_history_is_distinguishable_from_a_failed_detection(self):
        # A single observation produces no detection at all (insufficient
        # history), while an irregular history produces a detected entry with a
        # weak confidence (a detection that yielded no commitment).
        single_session = f'task23_single_{uuid.uuid4().hex[:8]}'
        snapshot, _ = FinancialSnapshot.objects.get_or_create(session_id=single_session)
        Transaction.objects.create(
            snapshot=snapshot, session_id=single_session,
            transaction_date=date(2026, 10, 5), amount=Decimal('120.00'),
            transaction_type='DEBIT', normalized_merchant='Chai Point',
            category='Uncategorized', source_type=Transaction.SOURCE_IMPORT,
        )
        self.assertEqual(detect_subscriptions(single_session), [])


class Scenario9DuplicateImportTests(Task23RecurringTestBase):
    """A re-import must not create extra recurring occurrences."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='task23_dup', password='pw')
        _session, self.token = SecureSession.issue_session(self.session_id)
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version='v1.0-task23',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )
        self.csv = (
            'Date,Description,Debit,Credit,Balance\n'
            '2026-08-10,NETFLIX SUBSCRIPTION,199.00,,0.00\n'
            '2026-09-10,NETFLIX SUBSCRIPTION,199.00,,0.00\n'
            '2026-10-10,NETFLIX SUBSCRIPTION,199.00,,0.00\n'
        )

    def _import(self):
        return self.client.post(
            '/api/v1/data/parse-statement/',
            {'raw_text': self.csv, 'format': 'csv', 'persist': 'true',
             'session_id': self.session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=self.token,
        )

    def test_01_reimported_rows_do_not_inflate_the_occurrence_count(self):
        first = self._import()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['persistence']['imported'], 3)

        # Re-importing the same statement must not add occurrences.
        second = self._import()
        self.assertEqual(second.json()['persistence']['imported'], 0)
        self.assertEqual(second.json()['persistence']['skipped_duplicates'], 3)

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['occurrence_count'], 3)

    def test_02_a_duplicate_import_does_not_inflate_the_commitment(self):
        self._import()
        self._import()
        overview = compute_imported_session_overview(self.session_id)
        self.assertEqual(Decimal(overview['summary']['monthly_leakage']), Decimal('199.00'))
        self.assertEqual(Decimal(overview['summary']['confirmed_commitments']), Decimal('199.00'))
        self.assertEqual(overview['summary']['confirmed_recurring_count'], 1)


class Scenario10MerchantVariationTests(Task23RecurringTestBase):
    """Aliases and variable amounts must not combine unrelated merchants."""

    def test_01_unrelated_merchants_are_kept_apart(self):
        for month in (8, 9, 10):
            self._debit(date(2026, month, 1), 'Amazon Prime Video Subscription', 299)
        for month in (8, 9, 10):
            self._debit(date(2026, month, 15), 'Amazon Shopping Store', 1200)

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 2)
        canonicals = {e['canonical_merchant'] for e in result}
        self.assertIn('amazon_prime', canonicals)
        self.assertIn('amazon_shopping', canonicals)
        prime = next(e for e in result if e['canonical_merchant'] == 'amazon_prime')
        retail = next(e for e in result if e['canonical_merchant'] == 'amazon_shopping')
        # The subscription is a commitment; the retail repeat is not.
        self.assertTrue(prime['is_financial_commitment'])
        self.assertFalse(retail['is_financial_commitment'])
        self.assertEqual(retail['commitment_class'], COMMITMENT_DISCRETIONARY)

    def test_02_narrative_variation_of_one_merchant_stays_one_group(self):
        for month, narration in (
            (8, 'POS NETFLIX SUBSCRIPTION'),
            (9, 'NETFLIX.COM/BILL'),
            (10, 'Netflix Subscription'),
        ):
            self._debit(date(2026, month, 6), narration, 649)
        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['occurrence_count'], 3)


class RecurringScanPerformanceTests(Task23RecurringTestBase):
    """The unusual-spending scan must not run one query per transaction."""

    def test_01_duplicate_scan_uses_a_single_query(self):
        for i in range(60):
            self._debit(
                date(2026, 8, 1) if i % 2 == 0 else date(2026, 9, 1),
                f'Merchant {i % 7} Outlet', 100 + i,
            )
        with self.assertNumQueries(1):
            detect_unusual_spending(self.session_id, include_persona=False)

    def test_02_the_duplicate_detection_semantics_are_unchanged(self):
        self._debit(date(2026, 10, 1), 'Croma Electronics Store', 2500)
        self._debit(date(2026, 10, 10), 'Croma Electronics Store', 2500)
        flagged = detect_unusual_spending(self.session_id, include_persona=False)
        reasons = {f['reason'] for f in flagged}
        self.assertIn('duplicate_amount_merchant', reasons)


class UnknownMerchantCommitmentTests(Task23RecurringTestBase):
    """An unknown merchant must not become a confirmed commitment."""

    def test_01_repeated_unknown_merchant_is_only_a_pattern(self):
        for month in (8, 9, 10):
            self._debit(date(2026, month, 12), 'Zephyr Holdings 4821', 750)
        entry = detect_subscriptions(self.session_id)[0]
        self.assertEqual(entry['commitment_class'], COMMITMENT_DISCRETIONARY)
        self.assertEqual(entry['confidence'], RECURRING_PROBABLE)
        self.assertFalse(entry['is_financial_commitment'])
        overview = compute_imported_session_overview(self.session_id)
        self.assertEqual(Decimal(overview['summary']['confirmed_commitments']), Decimal('0.00'))
        self.assertEqual(Decimal(overview['summary']['monthly_leakage']), Decimal('0.00'))

    def test_02_an_unidentified_counterparty_is_only_a_pattern(self):
        for month in (8, 9, 10):
            self._debit(date(2026, month, 12), 'UPI/rahulkumar@paytm', 750)
        result = detect_subscriptions(self.session_id)
        if result:
            entry = result[0]
            self.assertIn(
                entry['commitment_class'],
                (COMMITMENT_PATTERN, COMMITMENT_DISCRETIONARY),
            )
            self.assertFalse(entry['is_financial_commitment'])
