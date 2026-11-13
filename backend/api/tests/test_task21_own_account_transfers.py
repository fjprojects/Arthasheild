"""
Task 21 — own-account transfer detection and financial accuracy regressions.

An own-account transfer (a UPI transfer to the user's own account, an internal
sweep, a savings top-up) must never inflate earned income, ordinary living
expenses, savings or recoverable leakage - while the transaction itself stays
visible in the ledger and keeps its original amount.

The reference scenario is the synthetic audit case: a ₹10,000 own-account
transfer inside a statement whose other rows reconcile to the audited figures
(gross living expenses ₹98,179, net expenses ₹93,179 after the confirmed
refund, savings -₹18,179). The expected values are recomputed here from the
raw rows rather than being taken on faith.

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
    INTERNAL_TRANSFER_LABEL,
    classify_credit,
    classify_debit,
    detect_subscriptions,
    monthly_budget,
)
from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction
from data_processor.normalizer import TransactionNormalizer
from data_processor.transfers import (
    CONFIDENCE_CONFIRMED,
    CONFIDENCE_NONE,
    CONFIDENCE_UNCERTAIN,
    classify_own_account_transfer,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# The synthetic audit scenario: (date, narration, debit, credit)
# ---------------------------------------------------------------------------
AUDIT_ROWS = [
    (date(2026, 10, 1), 'ACH CRED CLIENT GLOBAL TECH STIPEND', None, '75000.00'),
    (date(2026, 10, 2), 'POS ADOBE SYSTEMS RENEWAL INT US-882194', '4200.00', None),
    (date(2026, 10, 3), 'SWIGGY ORDER-5551234', '5000.00', None),
    (date(2026, 10, 4), 'UPI/SWIGGY/ORDER_9824219/swiggy@icici', '480.00', None),
    (date(2026, 10, 5), 'UPI/SELF/TRANSFER', '10000.00', None),
    (date(2026, 10, 6), 'POS NETFLIX SUBSCRIPTION', '649.00', None),
    (date(2026, 10, 7), 'NEFT DEBIT APEX BANK PHONE EMI NO-COST-882', '5735.00', None),
    (date(2026, 10, 8), 'POS FIGMA SUBSCRIPTION CA US-4491', '1250.00', None),
    (date(2026, 10, 9), 'POS APOLLO PHARMACY HEALTH', '2365.00', None),
    (date(2026, 10, 10), 'POS INDIAN OIL PETROL FUEL', '3500.00', None),
    (date(2026, 10, 11), 'ACH DEBIT APEX BANK INSURANCE PREMIUM', '12000.00', None),
    (date(2026, 10, 12), 'POS BESCOM ELECTRICITY BILL', '4500.00', None),
    (date(2026, 10, 13), 'POS AIRTEL MOBILE RECHARGE', '799.00', None),
    (date(2026, 10, 14), 'POS BIG BAZAAR GROCERIES', '6701.00', None),
    (date(2026, 10, 15), 'ACH DEBIT APEX BANK RENT PAYMENT', '25000.00', None),
    (date(2026, 10, 16), 'POS APPLE INDIA MACBOOK PRO PURCHASE', '26000.00', None),
    (date(2026, 10, 17), 'UPI/SELF AC/TRANSFER', None, '10000.00'),
    (date(2026, 10, 18), 'REFUND SWIGGY ORDER-5551234', None, '5000.00'),
]

TRANSFER_DEBIT = Decimal('10000.00')
TRANSFER_CREDIT = Decimal('10000.00')
SALARY = Decimal('75000.00')
REFUND = Decimal('5000.00')

# The audited reference figures (independently recomputed in the test below).
AUDIT_GROSS_LIVING_EXPENSES = Decimal('98179.00')
AUDIT_NET_EXPENSES = Decimal('93179.00')
AUDIT_SAVINGS = Decimal('-18179.00')


def _expected_scenario_totals():
    """Recomputes the scenario totals from the raw rows (no hardcoded totals)."""
    debit_total = sum(Decimal(r[2]) for r in AUDIT_ROWS if r[2])
    transfer_debit = sum(
        Decimal(r[2]) for r in AUDIT_ROWS
        if r[2] and classify_own_account_transfer(r[1])['is_own_account_transfer']
    )
    earned = sum(
        Decimal(r[3]) for r in AUDIT_ROWS
        if r[3] and classify_credit(TransactionNormalizer.extract_merchant(r[1]))['is_earned_income']
    )
    # The refund carries a shared order reference, so it is a CONFIRMED match and
    # is applied against the same-period purchase.
    applied_refunds = sum(
        Decimal(r[3]) for r in AUDIT_ROWS
        if r[3] and classify_credit(TransactionNormalizer.extract_merchant(r[1]))['credit_type'] == 'refund'
    )
    gross_living = debit_total - transfer_debit
    net_expenses = gross_living - applied_refunds
    savings = earned - net_expenses
    return {
        'debit_total': debit_total,
        'transfer_debit': transfer_debit,
        'earned_income': earned,
        'applied_refunds': applied_refunds,
        'gross_living_expenses': gross_living,
        'net_expenses': net_expenses,
        'savings': savings,
    }


class OwnAccountTransferDetectionTests(TestCase):
    """The detector recognises own-account transfers and nothing else."""

    def test_01_upi_self_transfer_is_detected(self):
        result = classify_own_account_transfer('UPI/SELF/TRANSFER')
        self.assertTrue(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_CONFIRMED)

    def test_02_self_ac_transfer_is_detected(self):
        for narration in ('UPI/SELF AC/TRANSFER', 'SELF AC', 'UPI/SELF-AC/TRANSFER'):
            result = classify_own_account_transfer(narration)
            self.assertTrue(result['is_own_account_transfer'], msg=narration)
            self.assertEqual(result['confidence'], CONFIDENCE_CONFIRMED, msg=narration)

    def test_03_explicit_own_account_formats_are_detected(self):
        variants = [
            'UPI/SELF/TRANSFER',
            'UPI/SELF AC/TRANSFER',
            'SELF TRANSFER',
            'TRANSFER TO SELF',
            'TRANSFER FROM SELF',
            'TFR TO SELF',
            'OWN ACCOUNT TRANSFER',
            'UPI/OWN ACCOUNT/TRANSFER',
            'UPI/TRANSFER/SELF',
            'upi/self/transfer',
            'NEFT/SELF/TRANSFER',
            'FUND TRANSFER SELF',
            'INTRA-BANK TRANSFER',
            'AUTO SWEEP OUT',
            'SWEEP IN CR',
            'UPI/SELF/TRANSFER/421234567890',
            'UPI/SELF TRANSFER A/C XX..4821',
        ]
        for narration in variants:
            result = classify_own_account_transfer(narration)
            self.assertTrue(result['is_own_account_transfer'], msg=narration)
            self.assertEqual(result['confidence'], CONFIDENCE_CONFIRMED, msg=narration)

    def test_04_transfer_to_another_person_is_not_internal(self):
        for narration in (
            'UPI/TRANSFER/RAHUL SHARMA/rahul@okhdfcbank',
            'TRANSFER TO RAHUL SHARMA',
            'TRANSFER TO MERCHANT',
            'SELF TRANSFER TO RAHUL/rahul@okaxis',
        ):
            result = classify_own_account_transfer(narration)
            self.assertFalse(result['is_own_account_transfer'], msg=narration)

    def test_05_ordinary_merchant_payment_is_not_internal(self):
        result = classify_own_account_transfer('POS SWIGGY/ORDER_9824219/swiggy@icici')
        self.assertFalse(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_NONE)

    def test_06_salary_reimbursement_refund_and_loan_are_not_internal(self):
        cases = {
            'ACH CRED CLIENT GLOBAL TECH STIPEND': 'earned_income',
            'REIMBURSEMENT EXPENSE CLAIM': 'reimbursement',
            'REFUND SWIGGY ORDER-5551234': 'refund',
            'EMI LOAN DISBURSEMENT': None,
            'MUTUAL FUND REDEMPTION PAYOUT': 'capital_liquidation',
            'INTEREST CREDITED FD': 'investment_yield',
        }
        for narration, expected_credit_type in cases.items():
            merchant = TransactionNormalizer.extract_merchant(narration)
            self.assertFalse(
                classify_own_account_transfer(merchant)['is_own_account_transfer'],
                msg=narration,
            )
            if expected_credit_type is not None:
                self.assertEqual(
                    classify_credit(merchant)['credit_type'], expected_credit_type, msg=narration
                )

    def test_07_ambiguous_transfer_narration_stays_uncertain(self):
        result = classify_own_account_transfer('TRANSFER TO RAHUL SHARMA')
        self.assertFalse(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_UNCERTAIN)
        # The conservative classification keeps it an ordinary outflow.
        self.assertFalse(classify_debit('Rahul Sharma')['is_transfer'])

    def test_08_contradicted_evidence_is_uncertain(self):
        # A fee charged on a transfer is a real expense, not an internal movement.
        result = classify_own_account_transfer('UPI/SELF TRANSFER FEE')
        self.assertFalse(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_UNCERTAIN)

    def test_09_normalizer_preserves_the_evidence(self):
        self.assertEqual(
            TransactionNormalizer.extract_merchant('UPI/SELF/TRANSFER'), 'Self Transfer'
        )
        self.assertEqual(
            TransactionNormalizer.extract_merchant('UPI/SELF AC/TRANSFER'), 'Self Ac Transfer'
        )
        self.assertEqual(
            TransactionNormalizer.extract_merchant('UPI/OWN ACCOUNT/TRANSFER'),
            'Own Account Transfer',
        )
        # Ordinary merchants are untouched.
        self.assertEqual(
            TransactionNormalizer.extract_merchant('POS SWIGGY/ORDER_9824219/swiggy@icici'),
            'Swiggy',
        )

    def test_10_classification_is_deterministic_and_llm_free(self):
        for _ in range(3):
            first = classify_own_account_transfer('UPI/SELF/TRANSFER')
            second = classify_own_account_transfer('UPI/SELF/TRANSFER')
            self.assertEqual(first, second)


class TransferFinancialImpactTests(TestCase):
    """A confirmed own-account transfer must not move any financial aggregate."""

    def setUp(self):
        self.session_id = f'task21_{uuid.uuid4().hex[:8]}'
        self.snapshot, _ = FinancialSnapshot.objects.get_or_create(
            session_id=self.session_id
        )
        for d, narration, debit, credit in AUDIT_ROWS:
            Transaction.objects.create(
                snapshot=self.snapshot,
                session_id=self.session_id,
                transaction_date=d,
                amount=Decimal(debit or credit),
                transaction_type='DEBIT' if debit else 'CREDIT',
                normalized_merchant=TransactionNormalizer.extract_merchant(narration),
                category='Uncategorized',
                source_type=Transaction.SOURCE_IMPORT,
            )

    def test_01_monthly_expense_and_savings_reconciliation(self):
        expected = _expected_scenario_totals()
        # The independent recomputation must reproduce the audited reference.
        self.assertEqual(expected['transfer_debit'], TRANSFER_DEBIT)
        self.assertEqual(expected['gross_living_expenses'], AUDIT_GROSS_LIVING_EXPENSES)
        self.assertEqual(expected['net_expenses'], AUDIT_NET_EXPENSES)
        self.assertEqual(expected['savings'], AUDIT_SAVINGS)

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['gross_debits']), expected['debit_total'])
        self.assertEqual(Decimal(res['debit_transfers']), expected['transfer_debit'])
        self.assertEqual(Decimal(res['gross_living_expenses']), expected['gross_living_expenses'])
        self.assertEqual(Decimal(res['net_living_expenses']), expected['net_expenses'])
        self.assertEqual(Decimal(res['savings']), expected['savings'])
        self.assertEqual(Decimal(res['earned_income']), expected['earned_income'])

        # The audited reference figures.
        self.assertEqual(Decimal(res['gross_living_expenses']), AUDIT_GROSS_LIVING_EXPENSES)
        self.assertEqual(Decimal(res['net_living_expenses']), AUDIT_NET_EXPENSES)
        self.assertEqual(Decimal(res['savings']), AUDIT_SAVINGS)

    def test_02_the_transfer_is_not_an_expense_nor_an_income(self):
        res = monthly_budget(self.session_id, 2026, 10)
        # The debit side is an internal movement, not living expense.
        self.assertEqual(Decimal(res['debit_transfers']), TRANSFER_DEBIT)
        self.assertEqual(Decimal(res['category_spending']['transfer']), TRANSFER_DEBIT)
        self.assertNotIn('transfer', res['net_category_spending'])
        # The credit side is not earned income.
        self.assertEqual(Decimal(res['credit_breakdown']['transfers']), TRANSFER_CREDIT)
        self.assertEqual(Decimal(res['earned_income']), SALARY)
        self.assertEqual(Decimal(res['operating_income']), SALARY)
        # No double counting: the transfer appears once, as a transfer.
        self.assertEqual(Decimal(res['total_credits']), SALARY + TRANSFER_CREDIT + REFUND)

    def test_03_the_transaction_is_preserved_in_the_ledger(self):
        rows = Transaction.objects.filter(session_id=self.session_id)
        self.assertEqual(rows.count(), len(AUDIT_ROWS))
        transfer_rows = [
            r for r in rows
            if r.amount == TRANSFER_DEBIT and r.transaction_type == 'DEBIT'
        ]
        self.assertEqual(len(transfer_rows), 1)
        self.assertEqual(transfer_rows[0].transaction_type, 'DEBIT')
        self.assertEqual(transfer_rows[0].amount, TRANSFER_DEBIT)
        self.assertEqual(
            Transaction.objects.filter(
                session_id=self.session_id,
                amount=TRANSFER_CREDIT,
                transaction_type='CREDIT',
            ).count(),
            1,
        )

    def test_04_the_transfer_is_not_recoverable_leakage(self):
        subs = detect_subscriptions(self.session_id, include_persona=False)
        for s in subs:
            self.assertNotIn('Transfer', str(s.get('merchant', '')))
        res = monthly_budget(self.session_id, 2026, 10)
        # The transfer never reaches the recurring/leakage aggregates.
        self.assertNotIn('transfer', res['net_category_spending'])

    def test_05_safe_to_spend_does_not_treat_the_transfer_as_an_expense(self):
        res = monthly_budget(self.session_id, 2026, 10)
        # Safe-to-Spend is derived from the income and the net living expenses,
        # so the transfer cannot inflate the allowance.
        self.assertNotIn(Decimal(res['net_living_expenses']), [Decimal('108179.00')])
        self.assertEqual(Decimal(res['net_living_expenses']), AUDIT_NET_EXPENSES)
        from analytics.services import AnalyticsEngine
        with_transfer = AnalyticsEngine.calculate_safe_to_spend(
            current_balance=50000,
            monthly_income=float(res['operating_income']),
            pending_fixed_obligations=0,
            days_remaining_in_month=10,
        )
        without_transfer = AnalyticsEngine.calculate_safe_to_spend(
            current_balance=50000,
            monthly_income=float(res['operating_income']),
            pending_fixed_obligations=0,
            days_remaining_in_month=10,
        )
        self.assertEqual(with_transfer, without_transfer)


class ImportedOverviewConsistencyTests(TestCase):
    """The imported dashboard must agree with the corrected budget."""

    def setUp(self):
        self.session_id = f'task21_view_{uuid.uuid4().hex[:8]}'
        self.snapshot, _ = FinancialSnapshot.objects.get_or_create(
            session_id=self.session_id
        )
        for d, narration, debit, credit in AUDIT_ROWS:
            Transaction.objects.create(
                snapshot=self.snapshot,
                session_id=self.session_id,
                transaction_date=d,
                amount=Decimal(debit or credit),
                transaction_type='DEBIT' if debit else 'CREDIT',
                normalized_merchant=TransactionNormalizer.extract_merchant(narration),
                category='Uncategorized',
                source_type=Transaction.SOURCE_IMPORT,
            )

    def test_01_overview_matches_the_budget(self):
        from api.insights import compute_imported_session_overview
        overview = compute_imported_session_overview(self.session_id)
        budget = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(overview['summary']['monthly_expenses']), Decimal(budget['net_living_expenses']))
        self.assertEqual(Decimal(overview['summary']['monthly_income']), Decimal(budget['operating_income']))
        self.assertEqual(Decimal(overview['summary']['monthly_expenses']), AUDIT_NET_EXPENSES)
        self.assertEqual(Decimal(overview['summary']['monthly_income']), SALARY)

    def test_02_the_transfer_row_is_visible_and_clearly_labelled(self):
        from api.insights import compute_imported_session_overview
        overview = compute_imported_session_overview(self.session_id)
        transfer_rows = [
            row for row in overview['transactions']
            if row['amount'] == str(TRANSFER_DEBIT) and row['type'] == 'DEBIT'
        ]
        self.assertEqual(len(transfer_rows), 1)
        row = transfer_rows[0]
        self.assertTrue(row['is_internal_transfer'])
        self.assertEqual(row['merchant'], INTERNAL_TRANSFER_LABEL)
        self.assertEqual(row['description'], INTERNAL_TRANSFER_LABEL)
        # The safe display-label boundary still holds: no name, no marker.
        self.assertNotIn('[', row['merchant'])
        self.assertNotIn('REDACTED', row['merchant'].upper())

    def test_03_ordinary_expenses_keep_their_label(self):
        from api.insights import compute_imported_session_overview
        overview = compute_imported_session_overview(self.session_id)
        labels = {row['merchant'] for row in overview['transactions']}
        self.assertIn('Swiggy', labels)
        self.assertNotIn(INTERNAL_TRANSFER_LABEL, labels - {INTERNAL_TRANSFER_LABEL})

    def test_04_the_response_boundary_keeps_the_transfer_label(self):
        # The overview view re-applies the strict counterparty label; the fixed
        # internal-transfer label must survive it.
        from api.views import ImportedSessionOverviewView
        client = APIClient()
        _session, token = SecureSession.issue_session(self.session_id)
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version='v1.0-task21',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )
        response = client.post(
            '/api/v1/insights/imported-overview/',
            {'session_id': self.session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        rows = [
            row for row in response.json()['transactions']
            if row['amount'] == str(TRANSFER_DEBIT) and row['type'] == 'DEBIT'
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['merchant'], INTERNAL_TRANSFER_LABEL)
        self.assertEqual(rows[0]['description'], INTERNAL_TRANSFER_LABEL)
        self.assertTrue(rows[0]['is_internal_transfer'])
        # The safe display-label boundary is otherwise untouched.
        self.assertNotIn('Self', rows[0]['merchant'])


class TransferImportReliabilityTests(TestCase):
    """A re-imported statement must not duplicate the transfer."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='task21_import', password='pw')
        self.session_id = f'task21_import_{uuid.uuid4().hex[:8]}'
        _session, self.token = SecureSession.issue_session(self.session_id)
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version='v1.0-task21',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )
        self.csv = (
            'Date,Description,Debit,Credit,Balance\n'
            '2026-10-01,ACH CRED CLIENT GLOBAL TECH STIPEND,,75000.00,75000.00\n'
            '2026-10-05,UPI/SELF/TRANSFER,10000.00,,65000.00\n'
            '2026-10-06,POS SWIGGY ORDER-9824219,480.00,,64520.00\n'
            '2026-10-07,UPI/SELF AC/TRANSFER,,10000.00,74520.00\n'
        )

    def _import(self):
        return self.client.post(
            '/api/v1/data/parse-statement/',
            {'raw_text': self.csv, 'format': 'csv', 'persist': 'true',
             'session_id': self.session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=self.token,
        )

    def test_01_transfer_is_imported_once_and_not_duplicated(self):
        first = self._import()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['persistence']['imported'], 4)
        self.assertEqual(first.json()['persistence']['skipped_duplicates'], 0)

        second = self._import()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['persistence']['imported'], 0)
        self.assertEqual(second.json()['persistence']['skipped_duplicates'], 4)

        stored = Transaction.objects.filter(session_id=self.session_id)
        self.assertEqual(stored.count(), 4)
        transfers = [
            t for t in stored
            if t.amount == TRANSFER_DEBIT and t.transaction_type == 'DEBIT'
        ]
        self.assertEqual(len(transfers), 1)

    def test_02_imported_statement_reports_the_transfer_as_a_transfer(self):
        self._import()
        res = monthly_budget(self.session_id, 2026, 10)
        # Only the internal transfer is an outflow - no living expense at all.
        self.assertEqual(Decimal(res['debit_transfers']), TRANSFER_DEBIT)
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('480.00'))
        self.assertEqual(Decimal(res['earned_income']), SALARY)
