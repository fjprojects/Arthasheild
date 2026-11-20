"""Regression tests: ACH/NEFT credits without salary evidence.
Ported from reference audit suite and adapted to canonical classification engine.

A corporate ACH/NEFT credit (for example the November statement's
Rs 55,000 Northstar and Rs 12,500 Orbit Design credits) must not be counted as
confirmed earned income, and must not silently fall into UNCLASSIFIED either.
It is reported as PROBABLE income with per-transaction evidence.
Synthetic data only.
"""
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase

from api.insights import classify_credit, monthly_budget
from api.models import FinancialSnapshot, Transaction


def _snap(session_id):
    snap, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
    return snap


def _tx(snap, session_id, merchant, amount, tx_type, tx_date):
    return Transaction.objects.create(
        snapshot=snap,
        session_id=session_id,
        transaction_date=tx_date,
        amount=Decimal(str(amount)),
        transaction_type=tx_type,
        normalized_merchant=merchant,
        category='Uncategorized',
        is_recurring=False,
        source_type='import',
        fingerprint='',
    )


class CreditClassificationEvidenceTests(TestCase):
    def test_ach_corporate_credit_is_probable_not_confirmed(self):
        info = classify_credit('NORTHSTAR SERVICES ACH CREDIT 55000')
        self.assertEqual(info['credit_type'], 'business_income')
        self.assertEqual(info['classification_status'], 'PROBABLE')
        self.assertTrue(info['requires_review'])
        self.assertNotEqual(info['credit_type'], 'earned_income')

    def test_neft_design_credit_is_probable_not_confirmed(self):
        info = classify_credit('ORBIT DESIGN NEFT CREDIT 12500')
        self.assertEqual(info['credit_type'], 'business_income')
        self.assertEqual(info['classification_status'], 'PROBABLE')
        self.assertTrue(info['requires_review'])
        self.assertNotEqual(info['credit_type'], 'earned_income')

    def test_salary_narration_still_confirms_earned_income(self):
        info = classify_credit('NORTHSTAR SERVICES PVT LTD ACH CREDIT SALARY')
        self.assertEqual(info['credit_type'], 'earned_income')
        self.assertTrue(info['is_earned_income'])
        self.assertTrue(info['is_operating_income'])

    def test_peer_upi_credit_stays_unclassified(self):
        info = classify_credit('UPI/FriendPayer/split_dinner_123')
        self.assertEqual(info['credit_type'], 'unclassified')
        self.assertFalse(info['is_earned_income'])

    def test_refund_over_neft_still_classifies_as_refund(self):
        info = classify_credit('NEFT CREDIT AMAZON REFUND')
        self.assertEqual(info['credit_type'], 'refund')


class ProbableIncomeBudgetTests(TestCase):
    def setUp(self):
        self.session_id = 'test_probable_%s' % uuid.uuid4().hex[:8]
        self.snap = _snap(self.session_id)
        _tx(self.snap, self.session_id, 'NORTHSTAR SERVICES ACH CREDIT 55000',
            55000, 'CREDIT', date(2026, 11, 3))
        _tx(self.snap, self.session_id, 'ORBIT DESIGN NEFT CREDIT 12500',
            12500, 'CREDIT', date(2026, 11, 18))
        _tx(self.snap, self.session_id, 'Apartment Rent Landlord',
            20000, 'DEBIT', date(2026, 11, 5))
        _tx(self.snap, self.session_id, 'UPI/UnknownSender/9876543210',
            800, 'CREDIT', date(2026, 11, 20))

    def test_probable_income_separated_from_confirmed_earned_income(self):
        res = monthly_budget(self.session_id, 2026, 11)
        self.assertEqual(Decimal(res['earned_income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['confirmed_operating_income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['probable_income']), Decimal('67500.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['probable_income']), Decimal('67500.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['unclassified']), Decimal('800.00'))

    def test_probable_income_is_surfaced_for_review_with_evidence(self):
        res = monthly_budget(self.session_id, 2026, 11)
        review = res['income_classification']
        self.assertTrue(review['requires_review'])
        self.assertEqual(Decimal(review['probable_operating_income']), Decimal('67500.00'))
        self.assertEqual(Decimal(review['confirmed_operating_income']), Decimal('0.00'))
        self.assertEqual(review['status'], 'PROBABLE')

    def test_credit_breakdown_reconciles_with_total_credits(self):
        res = monthly_budget(self.session_id, 2026, 11)
        breakdown = res['credit_breakdown']
        reconciled = sum(
            Decimal(breakdown[key])
            for key in (
                'earned_income', 'investment_yield', 'capital_liquidation',
                'investment_transfers', 'refunds', 'transfers',
                'reimbursements', 'unclassified', 'business_income',
            )
        )
        self.assertEqual(reconciled, Decimal(res['total_credits']))
        self.assertEqual(reconciled, Decimal('68300.00'))
