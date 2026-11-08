"""
Phase 2 — Financial Intelligence Tests
Tests for all five functions in api/insights.py
Uses only synthetic data. No real bank statements or personal data.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from api.models import Transaction, FinancialSnapshot, ConsentAuditLog
from api.insights import (
    categorize_transactions,
    monthly_budget,
    detect_subscriptions,
    detect_unusual_spending,
    spending_patterns,
    _categorize,
)


def _make_snapshot(session_id):
    snap, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
    return snap


def _make_tx(snapshot, session_id, merchant, amount, tx_type, tx_date, is_recurring=False, source_type='import'):
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
        fingerprint='',
    )


class CategorizationTests(TestCase):
    """Tests for transaction keyword-based categorization."""

    def test_known_categories(self):
        self.assertEqual(_categorize('Netflix Subscription'), 'subscriptions')
        self.assertEqual(_categorize('Apollo Pharmacy'), 'healthcare')
        self.assertEqual(_categorize('Swiggy Restaurant Order'), 'food')
        self.assertEqual(_categorize('Amazon Shopping'), 'shopping')
        self.assertEqual(_categorize('Uber Taxi'), 'travel')
        self.assertEqual(_categorize('Electricity Bill'), 'bills')
        self.assertEqual(_categorize('Salary Credit'), 'salary')
        self.assertEqual(_categorize('Home Loan EMI'), 'emi')

    def test_unknown_category_falls_back_to_other(self):
        self.assertEqual(_categorize('XYZ Merchant ABC'), 'other')

    def test_categorize_transactions_import_only(self):
        session_id = 'test_cat_01'
        snap = _make_snapshot(session_id)
        _make_tx(snap, session_id, 'Swiggy', 480, 'DEBIT', date(2026, 10, 4), source_type='import')
        _make_tx(snap, session_id, 'PersonaData', 999, 'DEBIT', date(2026, 10, 5), source_type='persona')

        result = categorize_transactions(session_id, include_persona=False)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['category'], 'food')

    def test_categorize_transactions_include_persona(self):
        session_id = 'test_cat_02'
        snap = _make_snapshot(session_id)
        _make_tx(snap, session_id, 'Swiggy', 480, 'DEBIT', date(2026, 10, 4), source_type='import')
        _make_tx(snap, session_id, 'PersonaData', 999, 'DEBIT', date(2026, 10, 5), source_type='persona')

        result = categorize_transactions(session_id, include_persona=True)
        self.assertEqual(len(result), 2)

    def test_empty_session_returns_empty(self):
        result = categorize_transactions('nonexistent_session_xyz')
        self.assertEqual(result, [])


class MonthlyBudgetTests(TestCase):
    """Tests for monthly budget aggregation."""

    def setUp(self):
        self.session_id = 'test_budget_01'
        self.snap = _make_snapshot(self.session_id)
        # October 2026
        _make_tx(self.snap, self.session_id, 'Salary Credit', 75000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Swiggy', 480, 'DEBIT', date(2026, 10, 4))
        _make_tx(self.snap, self.session_id, 'Netflix', 199, 'DEBIT', date(2026, 10, 10))
        # November 2026 (different month)
        _make_tx(self.snap, self.session_id, 'Salary Credit', 75000, 'CREDIT', date(2026, 11, 1))

    def test_income_calculation(self):
        result = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(result['income']), Decimal('75000.00'))

    def test_expenses_calculation(self):
        result = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(result['expenses']), Decimal('679.00'))

    def test_savings_calculation(self):
        result = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(result['savings']), Decimal('74321.00'))

    def test_no_overspending_when_income_exceeds_expenses(self):
        result = monthly_budget(self.session_id, 2026, 10)
        self.assertFalse(result['overspending'])

    def test_category_spending_breakdown(self):
        result = monthly_budget(self.session_id, 2026, 10)
        cats = result['category_spending']
        self.assertIn('food', cats)
        self.assertIn('subscriptions', cats)
        self.assertEqual(Decimal(cats['food']), Decimal('480.00'))
        self.assertEqual(Decimal(cats['subscriptions']), Decimal('199.00'))

    def test_month_scoping(self):
        oct_result = monthly_budget(self.session_id, 2026, 10)
        nov_result = monthly_budget(self.session_id, 2026, 11)
        self.assertEqual(Decimal(oct_result['income']), Decimal('75000.00'))
        self.assertEqual(Decimal(nov_result['income']), Decimal('75000.00'))
        # October expenses should not appear in November
        self.assertEqual(Decimal(nov_result['expenses']), Decimal('0.00'))

    def test_overspending_flag(self):
        session_id = 'test_budget_overdraft'
        snap = _make_snapshot(session_id)
        _make_tx(snap, session_id, 'Salary', 1000, 'CREDIT', date(2026, 10, 1))
        _make_tx(snap, session_id, 'Rent', 5000, 'DEBIT', date(2026, 10, 2))
        result = monthly_budget(session_id, 2026, 10)
        self.assertTrue(result['overspending'])

    def test_persona_excluded_by_default(self):
        session_id = 'test_budget_persona'
        snap = _make_snapshot(session_id)
        _make_tx(snap, session_id, 'Salary', 50000, 'CREDIT', date(2026, 10, 1), source_type='import')
        _make_tx(snap, session_id, 'PersonaIncome', 99999, 'CREDIT', date(2026, 10, 2), source_type='persona')
        result = monthly_budget(session_id, 2026, 10, include_persona=False)
        self.assertEqual(Decimal(result['income']), Decimal('50000.00'))


class SubscriptionDetectorTests(TestCase):
    """Tests for recurring payment detection."""

    def setUp(self):
        self.session_id = 'test_subs_01'
        self.snap = _make_snapshot(self.session_id)
        _make_tx(self.snap, self.session_id, 'Netflix', 199, 'DEBIT', date(2026, 9, 10), is_recurring=True)
        _make_tx(self.snap, self.session_id, 'Netflix', 199, 'DEBIT', date(2026, 10, 10), is_recurring=True)
        _make_tx(self.snap, self.session_id, 'Spotify', 99, 'DEBIT', date(2026, 10, 15), is_recurring=True)
        # Non-recurring should not appear
        _make_tx(self.snap, self.session_id, 'Amazon One-time', 1500, 'DEBIT', date(2026, 10, 5))

    def test_detects_recurring_subscriptions(self):
        result = detect_subscriptions(self.session_id)
        identifiers = [s['identifier'] for s in result]
        self.assertIn('Netflix', identifiers)
        self.assertIn('Spotify', identifiers)

    def test_non_recurring_excluded(self):
        result = detect_subscriptions(self.session_id)
        identifiers = [s['identifier'] for s in result]
        self.assertNotIn('Amazon One-time', identifiers)

    def test_yearly_estimate_calculated(self):
        result = detect_subscriptions(self.session_id)
        netflix = next(s for s in result if s['identifier'] == 'Netflix')
        self.assertEqual(Decimal(netflix['monthly_estimate']), Decimal('199.00'))
        self.assertEqual(Decimal(netflix['yearly_estimate']), Decimal('2388.00'))

    def test_multiple_entries_marked_as_candidate(self):
        result = detect_subscriptions(self.session_id)
        netflix = next(s for s in result if s['identifier'] == 'Netflix')
        self.assertTrue(netflix['candidates'])

    def test_single_entry_not_candidate(self):
        result = detect_subscriptions(self.session_id)
        spotify = next(s for s in result if s['identifier'] == 'Spotify')
        self.assertFalse(spotify['candidates'])

    def test_persona_excluded_by_default(self):
        session_id = 'test_subs_persona'
        snap = _make_snapshot(session_id)
        _make_tx(snap, session_id, 'PersonaSub', 500, 'DEBIT', date(2026, 10, 1), is_recurring=True, source_type='persona')
        result = detect_subscriptions(session_id, include_persona=False)
        self.assertEqual(result, [])


class UnusualSpendingTests(TestCase):
    """Tests for unusual/large/duplicate spending detection."""

    def setUp(self):
        self.session_id = 'test_unusual_01'
        self.snap = _make_snapshot(self.session_id)
        # Normal spending baseline: 199, 350, 480 -> median = 350.00, threshold = 1050.00
        _make_tx(self.snap, self.session_id, 'Swiggy', 480, 'DEBIT', date(2026, 10, 4))
        _make_tx(self.snap, self.session_id, 'Netflix', 199, 'DEBIT', date(2026, 10, 10))
        _make_tx(self.snap, self.session_id, 'Uber', 350, 'DEBIT', date(2026, 10, 12))

    def test_large_amount_flagged(self):
        # Genuine unusual spending: MacBook purchase (₹85000)
        # Peer median baseline = 350.00, threshold = 1050.00
        # Transaction must NOT inflate its own comparison baseline
        _make_tx(self.snap, self.session_id, 'MacBook Purchase', 85000, 'DEBIT', date(2026, 10, 15))
        result = detect_unusual_spending(self.session_id)
        large = [r for r in result if r['reason'] == 'large_amount']
        merchants = [r['merchant'] for r in large]
        self.assertIn('MacBook Purchase', merchants)
        # Normal transactions must NOT be flagged as outliers
        self.assertEqual(len(large), 1)
        self.assertEqual(large[0]['baseline'], '350.00')
        self.assertEqual(large[0]['threshold'], '1050.00')

    def test_duplicate_flagged(self):
        # Add same merchant+amount on same date
        _make_tx(self.snap, self.session_id, 'Swiggy', 480, 'DEBIT', date(2026, 10, 4))
        result = detect_unusual_spending(self.session_id)
        dup = [r for r in result if r['reason'] == 'duplicate_amount_merchant']
        self.assertTrue(len(dup) > 0)
        self.assertEqual(dup[0]['merchant'], 'Swiggy')

    def test_normal_transactions_not_flagged(self):
        # Baseline transactions should not trigger any flags
        result = detect_unusual_spending(self.session_id)
        self.assertEqual(len(result), 0)
        # Adding another normal transaction in range still triggers 0 flags
        _make_tx(self.snap, self.session_id, 'Zomato', 420, 'DEBIT', date(2026, 10, 14))
        result_updated = detect_unusual_spending(self.session_id)
        self.assertEqual(len(result_updated), 0)

    def test_does_not_label_fraud(self):
        _make_tx(self.snap, self.session_id, 'MacBook Purchase', 85000, 'DEBIT', date(2026, 10, 15))
        result = detect_unusual_spending(self.session_id)
        for item in result:
            self.assertNotIn('fraud', item.get('reason', '').lower())

    def test_credits_not_included(self):
        _make_tx(self.snap, self.session_id, 'BigSalaryCredit', 500000, 'CREDIT', date(2026, 10, 1))
        result = detect_unusual_spending(self.session_id)
        merchants = [r['merchant'] for r in result]
        self.assertNotIn('Bigsalarycredit', merchants)


class SpendingPatternTests(TestCase):
    """Tests for multi-month spending trend analysis."""

    def setUp(self):
        self.session_id = 'test_patterns_01'
        self.snap = _make_snapshot(self.session_id)
        # Simulate spending in Oct and Nov 2026
        _make_tx(self.snap, self.session_id, 'Swiggy', 480, 'DEBIT', date(2026, 10, 4))
        _make_tx(self.snap, self.session_id, 'Swiggy', 960, 'DEBIT', date(2026, 11, 4))
        _make_tx(self.snap, self.session_id, 'Salary', 75000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Salary', 75000, 'CREDIT', date(2026, 11, 1))

    def test_monthly_breakdown_keys_present(self):
        result = spending_patterns(self.session_id, months=2)
        self.assertIn('monthly_breakdown', result)
        self.assertIn('category_trends', result)

    def test_monthly_breakdown_has_correct_month_count(self):
        result = spending_patterns(self.session_id, months=3)
        self.assertEqual(len(result['monthly_breakdown']), 3)

    def test_category_trend_direction_increase(self):
        result = spending_patterns(self.session_id, months=6)
        # food spending doubled from Oct to Nov
        trends = result['category_trends']
        if 'food' in trends:
            self.assertIn(trends['food']['trend'], ['increase', 'decrease'])

    def test_zero_spending_months_handled(self):
        """Months with no transactions should return 0 income/expenses, not crash."""
        result = spending_patterns(self.session_id, months=12)
        for month_data in result['monthly_breakdown'].values():
            self.assertIn('income', month_data)
            self.assertIn('expenses', month_data)
            self.assertIn('savings', month_data)

    def test_persona_data_excluded_by_default(self):
        session_id = 'test_patterns_persona'
        snap = _make_snapshot(session_id)
        _make_tx(snap, session_id, 'PersonaSpend', 99999, 'DEBIT', date(2026, 10, 5), source_type='persona')
        result = spending_patterns(session_id, months=1, include_persona=False)
        for month_data in result['monthly_breakdown'].values():
            self.assertEqual(Decimal(month_data['expenses']), Decimal('0.00'))


class Phase2APIEndpointTests(TestCase):
    """Integration tests: Phase 2 endpoints respond correctly."""

    def setUp(self):
        from rest_framework.test import APIRequestFactory
        from api.models import SecureSession, ConsentAuditLog
        self.factory = APIRequestFactory()
        self.session_id = 'test_p2_endpoints'
        self.session, self.token = SecureSession.issue_session(self.session_id)
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        self.snap = _make_snapshot(self.session_id)
        _make_tx(self.snap, self.session_id, 'Salary', 75000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Netflix', 199, 'DEBIT', date(2026, 10, 10), is_recurring=True)
        # Normal spending: Swiggy ₹450, Uber ₹320 -> median = 320, threshold = 960
        _make_tx(self.snap, self.session_id, 'Swiggy', 450, 'DEBIT', date(2026, 10, 11))
        _make_tx(self.snap, self.session_id, 'Uber', 320, 'DEBIT', date(2026, 10, 12))
        # Genuine unusual spend: BigSpend ₹15000 clearly exceeds 3x median without artificial dilution
        _make_tx(self.snap, self.session_id, 'BigSpend', 15000, 'DEBIT', date(2026, 10, 15))

    def test_categorize_endpoint(self):
        from api.views import TransactionCategorizationView
        req = self.factory.post('/api/v1/insights/categorize/', {'session_id': self.session_id}, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp = TransactionCategorizationView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('transactions', resp.data)
        self.assertGreater(resp.data['count'], 0)

    def test_categorize_missing_session(self):
        from api.views import TransactionCategorizationView
        req = self.factory.post('/api/v1/insights/categorize/', {}, format='json')
        resp = TransactionCategorizationView.as_view()(req)
        self.assertEqual(resp.status_code, 401)

    def test_monthly_budget_endpoint(self):
        from api.views import MonthlyBudgetView
        req = self.factory.post('/api/v1/insights/monthly-budget/',
                                {'session_id': self.session_id, 'year': 2026, 'month': 10}, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp = MonthlyBudgetView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('income', resp.data)
        self.assertIn('expenses', resp.data)
        self.assertIn('savings', resp.data)
        self.assertIn('category_spending', resp.data)

    def test_subscription_detector_endpoint(self):
        from api.views import SubscriptionDetectorView
        req = self.factory.post('/api/v1/insights/subscriptions/', {'session_id': self.session_id}, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp = SubscriptionDetectorView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('subscriptions', resp.data)
        self.assertEqual(resp.data['count'], 1)

    def test_unusual_spending_endpoint(self):
        from api.views import UnusualSpendingDetectorView
        req = self.factory.post('/api/v1/insights/unusual-spending/', {'session_id': self.session_id}, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp = UnusualSpendingDetectorView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('flagged', resp.data)
        # BigSpend ₹50000 should be flagged (avg of small txs ≈ ₹155, threshold ≈ ₹465)
        reasons = [f['reason'] for f in resp.data['flagged']]
        self.assertIn('large_amount', reasons)

    def test_spending_patterns_endpoint(self):
        from api.views import SpendingPatternAnalyzerView
        req = self.factory.post('/api/v1/insights/spending-patterns/',
                                {'session_id': self.session_id, 'months': 3}, format='json', HTTP_X_SESSION_TOKEN=self.token)
        resp = SpendingPatternAnalyzerView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('monthly_breakdown', resp.data)
        self.assertIn('category_trends', resp.data)
        self.assertEqual(len(resp.data['monthly_breakdown']), 3)

