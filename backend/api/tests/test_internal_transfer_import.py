"""Regression tests: own-account transfers must survive merchant extraction.

Defect: "SELF TRANSFER TO SAVINGS" was normalised to "Savings", so
classify_debit() no longer saw transfer evidence. The Rs 1,000 movement was
counted as a living expense, inflating expenses to Rs 28,178 and understating
the operating position. Synthetic data only.
"""
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase

from api.insights import classify_debit, monthly_budget
from api.models import FinancialSnapshot, Transaction
from data_processor.statement_parser import BankStatementParser
from data_processor.normalizer import TransactionNormalizer

NOV_11_ROWS = [
    ('NORTHSTAR SERVICES ACH CREDIT 55000', 55000, 'CREDIT', date(2026, 11, 3)),
    ('APARTMENT RENT LANDLORD', 15000, 'DEBIT', date(2026, 11, 5)),
    ('UPI/SWIGGY RESTAURANT', 480, 'DEBIT', date(2026, 11, 6)),
    ('NETFLIX SUBSCRIPTION', 199, 'DEBIT', date(2026, 11, 7)),
    ('BIGBASKET GROCERY', 1250, 'DEBIT', date(2026, 11, 8)),
    ('AMAZON SHOPPING', 1200, 'DEBIT', date(2026, 11, 9)),
    ('UBER TAXI', 350, 'DEBIT', date(2026, 11, 10)),
    ('APOLLO PHARMACY', 890, 'DEBIT', date(2026, 11, 12)),
    ('BESCOM ELECTRICITY', 7809, 'DEBIT', date(2026, 11, 18)),
    ('SELF TRANSFER TO SAVINGS', 1000, 'DEBIT', date(2026, 11, 20)),
    ('ORBIT DESIGN NEFT CREDIT 12500', 12500, 'CREDIT', date(2026, 11, 25)),
]


class TransferMerchantExtractionTests(TestCase):
    def test_self_transfer_narration_keeps_transfer_identity(self):
        self.assertEqual(
            TransactionNormalizer.extract_merchant('SELF TRANSFER TO SAVINGS'),
            'Self Transfer',
        )
        info = classify_debit('Self Transfer')
        self.assertTrue(info['is_transfer'])
        self.assertEqual(info['category'], 'transfer')

    def test_other_own_account_phrasings_are_preserved(self):
        for narration in (
            'Transfer to own account HDFC',
            'AUTO SWEEP TO FD',
            'Inter account movement',
        ):
            m = TransactionNormalizer.extract_merchant(narration)
            info = classify_debit(m)
            self.assertTrue(info['is_transfer'], msg=f"Expected transfer for {narration}, got {m}: {info}")

    def test_ordinary_transfer_to_merchant_is_not_rewritten(self):
        self.assertEqual(
            TransactionNormalizer.extract_merchant('UPI/MERCHANT STORE/123'),
            'Merchant Store',
        )

    def test_csv_parse_preserves_transfer_merchant(self):
        csv = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-11-20,SELF TRANSFER TO SAVINGS,1000.00,,41822.00\n"
        )
        result = BankStatementParser.parse_csv_text(csv)
        self.assertEqual(len(result.transactions), 1)
        self.assertEqual(result.transactions[0].merchant, 'Self Transfer')


class NovemberReconciliationTests(TestCase):
    def setUp(self):
        self.session_id = 'test_transfer_%s' % uuid.uuid4().hex[:8]
        self.snap, _ = FinancialSnapshot.objects.get_or_create(session_id=self.session_id)
        for merchant, amount, tx_type, tx_date in NOV_11_ROWS:
            Transaction.objects.create(
                snapshot=self.snap,
                session_id=self.session_id,
                transaction_date=tx_date,
                amount=Decimal(str(amount)),
                transaction_type=tx_type,
                normalized_merchant=merchant,
                category='Uncategorized',
                source_type='import',
                fingerprint='',
            )

    def test_transfer_is_excluded_from_living_expenses(self):
        res = monthly_budget(self.session_id)
        self.assertEqual(res['reporting_period']['year'], 2026)
        self.assertEqual(res['reporting_period']['month'], 11)
        self.assertEqual(Decimal(res['total_credits']), Decimal('67500.00'))
        self.assertEqual(Decimal(res['gross_debits']), Decimal('28178.00'))
        self.assertEqual(Decimal(res['debit_transfers']), Decimal('1000.00'))
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('27178.00'))
        self.assertEqual(Decimal(res['total_account_cash_movement']), Decimal('39322.00'))

    def test_probable_income_does_not_create_fake_surplus(self):
        res = monthly_budget(self.session_id)
        self.assertEqual(Decimal(res['earned_income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['probable_income']), Decimal('67500.00'))
        self.assertEqual(Decimal(res['confirmed_operating_income']), Decimal('0.00'))
        self.assertEqual(res['operating_income_status'], 'PROBABLE')
        self.assertTrue(res['operating_income_includes_probable'])
