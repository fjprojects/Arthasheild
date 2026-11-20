"""
Regression tests: recurring payment detection boundaries and false-positive elimination.

Phase 4 requirements:
- Similar merchant names and fluctuating amounts alone must not establish a confirmed recurring commitment.
- Distinguish fixed subscriptions from variable everyday spending.
- Use PROBABLE or UNVERIFIED where evidence is insufficient.
- Preserve correctly detected subscriptions such as Netflix.
- Avoid merchant-specific hardcoded exceptions.
Synthetic data only.
"""
from datetime import date
from decimal import Decimal
import uuid

from django.test import TestCase

from api.models import FinancialSnapshot, Transaction
from api.insights import (
    detect_subscriptions,
    RECURRING_CONFIRMED,
    RECURRING_PROBABLE,
    RECURRING_WEAK,
    PAYMENT_TYPE_SUBSCRIPTION,
    PAYMENT_TYPE_UTILITY,
    COMMITMENT_SUBSCRIPTION,
    COMMITMENT_DISCRETIONARY,
)


class RecurringSpendingBoundariesTests(TestCase):
    def setUp(self):
        self.session_id = f"test_recur_bound_{uuid.uuid4().hex[:8]}"
        self.snap, _ = FinancialSnapshot.objects.get_or_create(session_id=self.session_id)

    def _debit(self, tx_date, merchant, amount, category="Uncategorized"):
        return Transaction.objects.create(
            snapshot=self.snap,
            session_id=self.session_id,
            transaction_date=tx_date,
            amount=Decimal(str(amount)),
            transaction_type="DEBIT",
            normalized_merchant=merchant,
            category=category,
            source_type="import",
            fingerprint="",
        )

    def test_variable_food_orders_are_probable_not_confirmed(self):
        """Variable Swiggy orders (Rs 400, 401, 402) must be PROBABLE, never CONFIRMED."""
        self._debit(date(2026, 9, 5), "Swiggy Restaurant", 400, "Food & Dining")
        self._debit(date(2026, 10, 5), "Swiggy Restaurant", 401, "Food & Dining")
        self._debit(date(2026, 11, 5), "Swiggy Restaurant", 402, "Food & Dining")

        results = detect_subscriptions(self.session_id)
        self.assertEqual(len(results), 1)
        entry = results[0]
        self.assertNotEqual(entry["confidence"], RECURRING_CONFIRMED)
        self.assertEqual(entry["confidence"], RECURRING_PROBABLE)
        self.assertEqual(entry["recurrence_confidence"], RECURRING_PROBABLE)
        self.assertFalse(entry["is_financial_commitment"])
        self.assertEqual(entry["commitment_class"], COMMITMENT_DISCRETIONARY)

    def test_fixed_subscription_is_confirmed(self):
        """Fixed subscriptions like Netflix (Rs 199 fixed) remain CONFIRMED."""
        self._debit(date(2026, 9, 10), "Netflix Subscription", 199, "Subscriptions")
        self._debit(date(2026, 10, 10), "Netflix Subscription", 199, "Subscriptions")
        self._debit(date(2026, 11, 10), "Netflix Subscription", 199, "Subscriptions")

        results = detect_subscriptions(self.session_id)
        self.assertEqual(len(results), 1)
        entry = results[0]
        self.assertEqual(entry["confidence"], RECURRING_CONFIRMED)
        self.assertEqual(entry["recurrence_confidence"], RECURRING_CONFIRMED)
        self.assertTrue(entry["is_financial_commitment"])
        self.assertEqual(entry["commitment_class"], COMMITMENT_SUBSCRIPTION)
        self.assertEqual(entry["payment_type"], PAYMENT_TYPE_SUBSCRIPTION)

    def test_variable_utility_bills_remain_confirmed_with_metered_note(self):
        """Utility bills (e.g. BESCOM Electricity) with monthly usage variations remain CONFIRMED."""
        self._debit(date(2026, 9, 18), "BESCOM Electricity", 310, "Bills & Utilities")
        self._debit(date(2026, 10, 18), "BESCOM Electricity", 345, "Bills & Utilities")
        self._debit(date(2026, 11, 18), "BESCOM Electricity", 328, "Bills & Utilities")

        results = detect_subscriptions(self.session_id)
        self.assertEqual(len(results), 1)
        entry = results[0]
        self.assertEqual(entry["confidence"], RECURRING_CONFIRMED)
        self.assertEqual(entry["payment_type"], PAYMENT_TYPE_UTILITY)

    def test_irregular_everyday_spending_is_weak_or_not_projected(self):
        """Transactions on non-standard intervals are flagged irregular and costs withheld."""
        self._debit(date(2026, 9, 1), "Coffee Stall", 150)
        self._debit(date(2026, 9, 4), "Coffee Stall", 150)
        self._debit(date(2026, 9, 28), "Coffee Stall", 150)

        results = detect_subscriptions(self.session_id)
        if results:
            entry = results[0]
            self.assertEqual(entry["confidence"], RECURRING_WEAK)
            self.assertIsNone(entry["estimated_annual_cost"])

    def test_insufficient_history_is_not_confirmed(self):
        """Two transactions cannot establish a CONFIRMED recurring commitment."""
        self._debit(date(2026, 10, 1), "Generic Store", 500)
        self._debit(date(2026, 11, 1), "Generic Store", 500)

        results = detect_subscriptions(self.session_id)
        for entry in results:
            self.assertNotEqual(entry["confidence"], RECURRING_CONFIRMED)
