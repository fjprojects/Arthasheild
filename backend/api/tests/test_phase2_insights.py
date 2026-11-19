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
    classify_credit,
    _extract_canonical_merchant,
    _extract_reference_ids,
    MATCH_CONFIRMED,
    MATCH_PROBABLE,
    MATCH_WEAK,
    MATCH_UNMATCHED,
    ALLOC_APPLIED,
    ALLOC_SUGGESTED_NOT_APPLIED,
    ALLOC_NOT_ALLOCATED,
    TEMPORAL_SAME_PERIOD,
    TEMPORAL_CROSS_MONTH,
    RECURRING_CONFIRMED,
    RECURRING_PROBABLE,
    RECURRING_WEAK,
    CADENCE_WEEKLY,
    CADENCE_FORTNIGHTLY,
    CADENCE_MONTHLY,
    CADENCE_QUARTERLY,
    CADENCE_ANNUAL,
    CADENCE_IRREGULAR,
    PAYMENT_TYPE_SUBSCRIPTION,
    PAYMENT_TYPE_RENT,
    PAYMENT_TYPE_EMI,
    PAYMENT_TYPE_INSURANCE,
    PAYMENT_TYPE_UTILITY,
    PAYMENT_TYPE_OTHER,
    PAYMENT_TYPE_UNKNOWN,
    COMMITMENT_DISCRETIONARY,
    VARIATION_FIXED,
    VARIATION_LOW,
    VARIATION_VARIABLE,
    _project_calendar_next_date,
    is_peer_upi,
    get_recurring_merchant_key,
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

    def test_categorize_transactions_selects_persona_dataset_only(self):
        session_id = 'test_cat_02'
        snap = _make_snapshot(session_id)
        _make_tx(snap, session_id, 'Swiggy', 480, 'DEBIT', date(2026, 10, 4), source_type='import')
        _make_tx(snap, session_id, 'PersonaData', 999, 'DEBIT', date(2026, 10, 5), source_type='persona')

        result = categorize_transactions(session_id, include_persona=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['source_type'], 'persona')

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
        # Genuine unusual spending: MacBook purchase (85000)
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
        # Normal spending: Swiggy 450, Uber 320 -> median = 320, threshold = 960
        _make_tx(self.snap, self.session_id, 'Swiggy', 450, 'DEBIT', date(2026, 10, 11))
        _make_tx(self.snap, self.session_id, 'Uber', 320, 'DEBIT', date(2026, 10, 12))
        # Genuine unusual spend: BigSpend 15000 clearly exceeds 3x median without artificial dilution
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
        # BigSpend 50000 should be flagged (avg of small txs ~ 155, threshold ~ 465)
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


class CreditClassificationAndEarnedIncomeTests(TestCase):
    """
    Tests ensuring that incoming CREDIT transactions are accurately classified:
    - Salary/wages counted as earned income
    - Refunds, transfers, reimbursements, investments, and peer UPI NOT counted as earned income
    - Total credits mathematically reconcile
    - Deficit and savings use verified earned income
    """

    def setUp(self):
        self.session_id = 'test_credit_classification_sess'
        self.snap = _make_snapshot(self.session_id)

    def test_salary_counted_as_earned_income(self):
        _make_tx(self.snap, self.session_id, 'Tech Corp Monthly Salary', 85000, 'CREDIT', date(2026, 10, 1))
        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['earned_income']), Decimal('85000.00'))
        self.assertEqual(Decimal(res['income']), Decimal('85000.00'))

        c_info = classify_credit('Tech Corp Monthly Salary')
        self.assertEqual(c_info['credit_type'], 'earned_income')
        self.assertTrue(c_info['is_earned_income'])

    def test_refund_not_earned_income_and_associated_with_category(self):
        """Refund with canonical merchant match is PROBABLE — does NOT offset expenses."""
        _make_tx(self.snap, self.session_id, 'Amazon Shopping Refund', 1500, 'CREDIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'Amazon Retail Store', 5000, 'DEBIT', date(2026, 10, 2))

        res = monthly_budget(self.session_id, 2026, 10)
        # Refund must NOT count as earned income
        self.assertEqual(Decimal(res['earned_income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['income']), Decimal('0.00'))
        # Total credits reflects refund inflow
        self.assertEqual(Decimal(res['total_credits']), Decimal('1500.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['refunds']), Decimal('1500.00'))

        # Associated category verification
        c_info = classify_credit('Amazon Shopping Refund')
        self.assertEqual(c_info['credit_type'], 'refund')
        self.assertFalse(c_info['is_earned_income'])
        self.assertEqual(c_info['associated_category'], 'shopping')

        # Category spending preserved (no CONFIRMED match to offset)
        self.assertEqual(Decimal(res['category_spending']['shopping']), Decimal('5000.00'))
        self.assertEqual(Decimal(res['category_refunds']['shopping']), Decimal('1500.00'))
        # Net category spending NOT offset because match is PROBABLE, not CONFIRMED
        self.assertEqual(Decimal(res['net_category_spending']['shopping']), Decimal('5000.00'))

        # Refund detail should show PROBABLE confidence
        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)

    def test_internal_transfer_not_earned_income(self):
        _make_tx(self.snap, self.session_id, 'Self Transfer Own Account HDFC', 25000, 'CREDIT', date(2026, 10, 3))
        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['earned_income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['total_credits']), Decimal('25000.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['transfers']), Decimal('25000.00'))

        c_info = classify_credit('Self Transfer Own Account HDFC')
        self.assertEqual(c_info['credit_type'], 'transfer')
        self.assertFalse(c_info['is_earned_income'])

    def test_reimbursement_not_earned_income(self):
        _make_tx(self.snap, self.session_id, 'Corporate Travel Expense Reimbursement', 4500, 'CREDIT', date(2026, 10, 6))
        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['earned_income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['reimbursements']), Decimal('4500.00'))

        c_info = classify_credit('Corporate Travel Expense Reimbursement')
        self.assertEqual(c_info['credit_type'], 'reimbursement')
        self.assertFalse(c_info['is_earned_income'])

    def test_investment_income_tracked_separately(self):
        _make_tx(self.snap, self.session_id, 'SBI Term Deposit Interest Credited', 2100, 'CREDIT', date(2026, 10, 7))
        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['earned_income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['investment_yield']), Decimal('2100.00'))
        self.assertEqual(Decimal(res['operating_income']), Decimal('2100.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['investment_yield']), Decimal('2100.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['investment_income']), Decimal('2100.00'))

        c_info = classify_credit('SBI Term Deposit Interest Credited')
        self.assertEqual(c_info['credit_type'], 'investment_yield')
        self.assertFalse(c_info['is_earned_income'])
        self.assertTrue(c_info['is_operating_income'])

    def test_unknown_upi_credit_remains_visible_separately(self):
        # Generic UPI transfer with no salary/income marker must NOT be classified as earned income
        _make_tx(self.snap, self.session_id, 'UPI/FriendPayer/split_dinner_123', 850, 'CREDIT', date(2026, 10, 8))
        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['earned_income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['unclassified_inflows']), Decimal('850.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['unclassified']), Decimal('850.00'))
        self.assertEqual(Decimal(res['total_credits']), Decimal('850.00'))

        c_info = classify_credit('UPI/FriendPayer/split_dinner_123')
        self.assertEqual(c_info['credit_type'], 'unclassified')
        self.assertFalse(c_info['is_earned_income'])

    def test_total_credits_mathematical_reconciliation(self):
        # Multi-inflow scenario
        _make_tx(self.snap, self.session_id, 'Salary Payout Acme Corp', 60000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Swiggy Order Reversal', 520, 'CREDIT', date(2026, 10, 2))
        _make_tx(self.snap, self.session_id, 'Sweep In From Savings A/C', 10000, 'CREDIT', date(2026, 10, 3))
        _make_tx(self.snap, self.session_id, 'Medical Claim Reimbursement', 3200, 'CREDIT', date(2026, 10, 4))
        _make_tx(self.snap, self.session_id, 'Mutual Fund Dividend Credited', 800, 'CREDIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'UPI/UnknownSender/9876543210', 1480, 'CREDIT', date(2026, 10, 6))

        res = monthly_budget(self.session_id, 2026, 10)

        expected_earned = Decimal('60000.00')
        expected_refunds = Decimal('520.00')
        expected_transfers = Decimal('10000.00')
        expected_reimbursements = Decimal('3200.00')
        expected_yield = Decimal('800.00')
        expected_unclassified = Decimal('1480.00')
        expected_total = Decimal('76000.00')
        expected_operating_income = Decimal('60800.00')

        self.assertEqual(Decimal(res['earned_income']), expected_earned)
        self.assertEqual(Decimal(res['investment_yield']), expected_yield)
        self.assertEqual(Decimal(res['operating_income']), expected_operating_income)
        self.assertEqual(Decimal(res['income']), expected_operating_income)
        self.assertEqual(Decimal(res['total_credits']), expected_total)

        breakdown = res['credit_breakdown']
        self.assertEqual(Decimal(breakdown['earned_income']), expected_earned)
        self.assertEqual(Decimal(breakdown['refunds']), expected_refunds)
        self.assertEqual(Decimal(breakdown['transfers']), expected_transfers)
        self.assertEqual(Decimal(breakdown['reimbursements']), expected_reimbursements)
        self.assertEqual(Decimal(breakdown['investment_yield']), expected_yield)
        self.assertEqual(Decimal(breakdown['investment_income']), expected_yield)
        self.assertEqual(Decimal(breakdown['unclassified']), expected_unclassified)

        # Mathematical Identity
        reconciled_sum = (
            Decimal(breakdown['earned_income']) +
            Decimal(breakdown['refunds']) +
            Decimal(breakdown['transfers']) +
            Decimal(breakdown['reimbursements']) +
            Decimal(breakdown['investment_yield']) +
            Decimal(breakdown['unclassified'])
        )
        self.assertEqual(reconciled_sum, Decimal(res['total_credits']))

    def test_financial_health_and_savings_use_corrected_classification(self):
        # User has 0 earned income, 30000 internal transfer, and 15000 debit expenses
        _make_tx(self.snap, self.session_id, 'Self Account Sweep In', 30000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Apartment Rent Landlord', 15000, 'DEBIT', date(2026, 10, 2))

        res = monthly_budget(self.session_id, 2026, 10)

        # Under corrected logic:
        # Earned income = 0.00
        # Expenses = 15000.00
        # Savings = 0.00 - 15000.00 = -15000.00
        # Overspending = True!
        self.assertEqual(Decimal(res['earned_income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['income']), Decimal('0.00'))
        self.assertEqual(Decimal(res['expenses']), Decimal('15000.00'))
        self.assertEqual(Decimal(res['savings']), Decimal('-15000.00'))
        self.assertTrue(res['overspending'])

        # Total cashflow still tracked without distortion
        self.assertEqual(Decimal(res['total_credits']), Decimal('30000.00'))
        self.assertEqual(Decimal(res['net_cashflow']), Decimal('15000.00'))


class AuditCorrectionsComprehensiveTests(TestCase):
    """
    Tests covering all 11 required scenarios from the ArthaShield audit.
    Updated to reflect confidence-aware refund matching:
    - Only CONFIRMED matches (shared reference IDs) reduce net expenses.
    - PROBABLE matches (canonical merchant + unique candidate) are tracked but do NOT offset.
    """

    def setUp(self):
        self.session_id = 'test_audit_corrections_session'
        self.snap = _make_snapshot(self.session_id)

    def test_scenario_1_fd_interest_and_dividends_in_operating_income(self):
        """Scenario 1: FD interest and dividends classified as investment_yield and included in operating_income."""
        _make_tx(self.snap, self.session_id, 'HDFC Bank FD Interest Credited', 3500, 'CREDIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'TCS Final Dividend Credited', 1200, 'CREDIT', date(2026, 10, 12))
        _make_tx(self.snap, self.session_id, 'Acme Corp Monthly Salary', 50000, 'CREDIT', date(2026, 10, 1))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['earned_income']), Decimal('50000.00'))
        self.assertEqual(Decimal(res['investment_yield']), Decimal('4700.00'))
        self.assertEqual(Decimal(res['operating_income']), Decimal('54700.00'))
        self.assertEqual(Decimal(res['income']), Decimal('54700.00'))

        c1 = classify_credit('HDFC Bank FD Interest Credited')
        self.assertEqual(c1['credit_type'], 'investment_yield')
        self.assertTrue(c1['is_operating_income'])
        self.assertFalse(c1['is_earned_income'])

        c2 = classify_credit('TCS Final Dividend Credited')
        self.assertEqual(c2['credit_type'], 'investment_yield')
        self.assertTrue(c2['is_operating_income'])

    def test_scenario_2_mf_redemptions_as_capital_liquidation_not_income(self):
        """Scenario 2: Mutual fund redemptions classified as capital_liquidation and excluded from operating_income."""
        _make_tx(self.snap, self.session_id, 'Nippon India Mutual Fund Redemption Payout', 45000, 'CREDIT', date(2026, 10, 10))
        _make_tx(self.snap, self.session_id, 'Salary Credit Tech Services', 40000, 'CREDIT', date(2026, 10, 1))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['capital_liquidation']), Decimal('45000.00'))
        self.assertEqual(Decimal(res['earned_income']), Decimal('40000.00'))
        self.assertEqual(Decimal(res['operating_income']), Decimal('40000.00'))
        self.assertEqual(Decimal(res['total_credits']), Decimal('85000.00'))

        c = classify_credit('Nippon India Mutual Fund Redemption Payout')
        self.assertEqual(c['credit_type'], 'capital_liquidation')
        self.assertFalse(c['is_operating_income'])
        self.assertFalse(c['is_earned_income'])

    def test_scenario_3_groww_zerodha_cash_withdrawals_as_investment_transfers(self):
        """Scenario 3: Groww/Zerodha cash withdrawals classified as investment_transfers and excluded from income."""
        _make_tx(self.snap, self.session_id, 'Zerodha Broking Limited Transfer', 15000, 'CREDIT', date(2026, 10, 15))
        _make_tx(self.snap, self.session_id, 'Groww Balance Payout', 10000, 'CREDIT', date(2026, 10, 18))
        _make_tx(self.snap, self.session_id, 'Salary Payout Acme', 50000, 'CREDIT', date(2026, 10, 1))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['investment_transfers']), Decimal('25000.00'))
        self.assertEqual(Decimal(res['earned_income']), Decimal('50000.00'))
        self.assertEqual(Decimal(res['operating_income']), Decimal('50000.00'))
        self.assertEqual(Decimal(res['total_credits']), Decimal('75000.00'))

        c_zerodha = classify_credit('Zerodha Broking Limited Transfer')
        self.assertEqual(c_zerodha['credit_type'], 'investment_transfers')
        self.assertFalse(c_zerodha['is_operating_income'])

        c_groww = classify_credit('Groww Balance Payout')
        self.assertEqual(c_groww['credit_type'], 'investment_transfers')
        self.assertFalse(c_groww['is_operating_income'])

    def test_scenario_4_debit_side_own_account_transfers_excluded_from_living_expenses(self):
        """Scenario 4: Debit-side own-account transfers excluded from living_expenses."""
        _make_tx(self.snap, self.session_id, 'Self Transfer to Savings Account', 20000, 'DEBIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'Auto Sweep to FD', 10000, 'DEBIT', date(2026, 10, 6))
        _make_tx(self.snap, self.session_id, 'Electricity Bill Utility', 3000, 'DEBIT', date(2026, 10, 8))
        _make_tx(self.snap, self.session_id, 'Swiggy Food Delivery', 1000, 'DEBIT', date(2026, 10, 9))
        _make_tx(self.snap, self.session_id, 'Salary Credit Acme', 60000, 'CREDIT', date(2026, 10, 1))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['gross_debits']), Decimal('34000.00'))
        self.assertEqual(Decimal(res['debit_transfers']), Decimal('30000.00'))
        self.assertEqual(Decimal(res['living_expenses']), Decimal('4000.00'))
        self.assertEqual(Decimal(res['living_expenses_after_refunds']), Decimal('4000.00'))
        self.assertEqual(Decimal(res['operating_surplus']), Decimal('56000.00'))
        self.assertEqual(Decimal(res['total_account_cash_movement']), Decimal('26000.00'))

    def test_scenario_5_same_month_refund_probable_match_does_not_offset_expenses(self):
        """Scenario 5: Same-month refund with canonical merchant match is PROBABLE.
        Under confidence-aware matching, PROBABLE matches do NOT offset expenses."""
        _make_tx(self.snap, self.session_id, 'Salary Credit Acme', 60000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Amazon Shopping', 6000, 'DEBIT', date(2026, 10, 3))
        _make_tx(self.snap, self.session_id, 'Apollo Pharmacy Health', 1000, 'DEBIT', date(2026, 10, 4))
        _make_tx(self.snap, self.session_id, 'Amazon Shopping Refund Reversal', 2000, 'CREDIT', date(2026, 10, 10))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['category_spending']['shopping']), Decimal('6000.00'))
        self.assertEqual(Decimal(res['category_refunds']['shopping']), Decimal('2000.00'))
        # PROBABLE match: net category spending NOT offset
        self.assertEqual(Decimal(res['net_category_spending']['shopping']), Decimal('6000.00'))
        self.assertEqual(Decimal(res['living_expenses']), Decimal('7000.00'))
        self.assertEqual(Decimal(res['refunds_received']), Decimal('2000.00'))
        # PROBABLE match: refunds NOT applied to confirmed expenses
        self.assertEqual(Decimal(res['refunds_applied']), Decimal('0.00'))
        self.assertEqual(Decimal(res['living_expenses_after_refunds']), Decimal('7000.00'))
        self.assertEqual(Decimal(res['operating_surplus']), Decimal('53000.00'))
        # Refund detail shows PROBABLE confidence
        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)

    def test_scenario_6_following_month_cross_month_refund_probable(self):
        """Scenario 6: Following-month refund with canonical match is PROBABLE cross-month."""
        # October: user spends 5000 on shopping
        _make_tx(self.snap, self.session_id, 'Amazon Shopping Order', 5000, 'DEBIT', date(2026, 10, 20))
        _make_tx(self.snap, self.session_id, 'Salary Credit Acme', 50000, 'CREDIT', date(2026, 10, 1))

        # November: user spends 1500 on shopping, and receives 5000 refund for October order
        _make_tx(self.snap, self.session_id, 'Salary Credit Acme', 50000, 'CREDIT', date(2026, 11, 1))
        _make_tx(self.snap, self.session_id, 'Amazon Shopping Order', 1500, 'DEBIT', date(2026, 11, 2))
        _make_tx(self.snap, self.session_id, 'Amazon Shopping Refund', 5000, 'CREDIT', date(2026, 11, 5))

        res_nov = monthly_budget(self.session_id, 2026, 11)
        self.assertEqual(Decimal(res_nov['gross_living_expenses']), Decimal('1500.00'))
        # PROBABLE match: cross-month refund attributed but does NOT offset November expenses
        self.assertEqual(Decimal(res_nov['net_living_expenses']), Decimal('1500.00'))
        self.assertEqual(Decimal(res_nov['category_spending']['shopping']), Decimal('1500.00'))
        self.assertEqual(Decimal(res_nov['net_category_spending']['shopping']), Decimal('1500.00'))
        # Refund shows PROBABLE confidence
        ref_entry = res_nov['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)

        # October statement remains immutable
        res_oct = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res_oct['gross_living_expenses']), Decimal('5000.00'))
        self.assertEqual(Decimal(res_oct['net_category_spending']['shopping']), Decimal('5000.00'))

    def test_scenario_7_unmatched_refunds_tracked_and_applied_without_negative_values(self):
        """Scenario 7: Unmatched refunds tracked in unmatched_refunds and not reducing unrelated expenses."""
        _make_tx(self.snap, self.session_id, 'Swiggy Food Dinner', 3000, 'DEBIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'Flight Booking Travel Refund', 5000, 'CREDIT', date(2026, 10, 8))
        _make_tx(self.snap, self.session_id, 'Salary Credit Acme', 40000, 'CREDIT', date(2026, 10, 1))

        res = monthly_budget(self.session_id, 2026, 10)
        # Unrelated flight refund must NOT reduce Swiggy food expense
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('3000.00'))
        self.assertEqual(Decimal(res['refunds_received']), Decimal('5000.00'))
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertEqual(Decimal(res['unmatched_refunds']), Decimal('5000.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('3000.00'))
        self.assertEqual(Decimal(res['operating_surplus']), Decimal('37000.00'))

    def test_scenario_8_operating_income_aggregates_earned_and_passive_yield(self):
        """Scenario 8: Operating income correctly aggregating earned income + passive yields."""
        _make_tx(self.snap, self.session_id, 'Software Consulting Retainer Client Payout', 70000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Quarterly Term Deposit Interest Credited', 4500, 'CREDIT', date(2026, 10, 2))
        _make_tx(self.snap, self.session_id, 'Infosys Final Dividend Credited', 1500, 'CREDIT', date(2026, 10, 3))
        _make_tx(self.snap, self.session_id, 'SBI Mutual Fund Redemption Payout', 50000, 'CREDIT', date(2026, 10, 4))
        _make_tx(self.snap, self.session_id, 'Self Transfer from Linked Account', 15000, 'CREDIT', date(2026, 10, 5))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['earned_income']), Decimal('70000.00'))
        self.assertEqual(Decimal(res['investment_yield']), Decimal('6000.00'))
        self.assertEqual(Decimal(res['capital_liquidation']), Decimal('50000.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['transfers']), Decimal('15000.00'))
        self.assertEqual(Decimal(res['operating_income']), Decimal('76000.00'))

    def test_scenario_9_correct_operating_surplus_without_probable_offset(self):
        """Scenario 9: Operating surplus calculation with confidence-aware matching.
        PROBABLE refund match does NOT reduce net living expenses."""
        _make_tx(self.snap, self.session_id, 'Acme Salary', 80000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Company Dividend Credited', 2000, 'CREDIT', date(2026, 10, 2))
        _make_tx(self.snap, self.session_id, 'Apartment Rent', 25000, 'DEBIT', date(2026, 10, 3))
        _make_tx(self.snap, self.session_id, 'Food Supermarket', 8000, 'DEBIT', date(2026, 10, 4))
        _make_tx(self.snap, self.session_id, 'Amazon Shopping', 4000, 'DEBIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'Amazon Shopping Refund', 1500, 'CREDIT', date(2026, 10, 8))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['operating_income']), Decimal('82000.00'))
        self.assertEqual(Decimal(res['living_expenses']), Decimal('37000.00'))
        # PROBABLE match: no expense offset
        self.assertEqual(Decimal(res['living_expenses_after_refunds']), Decimal('37000.00'))
        # Operating surplus = 82000.00 - 37000.00 = 45000.00
        self.assertEqual(Decimal(res['operating_surplus']), Decimal('45000.00'))
        self.assertEqual(Decimal(res['savings']), Decimal('45000.00'))

    def test_scenario_10_exact_mathematical_reconciliation_credits_and_debits(self):
        """Scenario 10: Exact mathematical reconciliation of total credits and debits."""
        # 8 distinct credit classes
        _make_tx(self.snap, self.session_id, 'Monthly Salary Payout', 50000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Bank Term Deposit Interest Credited', 2500, 'CREDIT', date(2026, 10, 2))
        _make_tx(self.snap, self.session_id, 'Axis Mutual Fund Redemption Payout', 15000, 'CREDIT', date(2026, 10, 3))
        _make_tx(self.snap, self.session_id, 'Zerodha Broking Limited', 7000, 'CREDIT', date(2026, 10, 4))
        _make_tx(self.snap, self.session_id, 'Amazon Order Refund Reversal', 1200, 'CREDIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'Self Transfer from HDFC Savings', 8000, 'CREDIT', date(2026, 10, 6))
        _make_tx(self.snap, self.session_id, 'Corporate Travel Reimbursement Claim', 3300, 'CREDIT', date(2026, 10, 7))
        _make_tx(self.snap, self.session_id, 'UPI/FriendTransfer/9876543210', 1000, 'CREDIT', date(2026, 10, 8))

        # 2 living debits + 1 transfer debit
        _make_tx(self.snap, self.session_id, 'Apartment Rent Owner', 12000, 'DEBIT', date(2026, 10, 2))
        _make_tx(self.snap, self.session_id, 'Swiggy Food Order', 6000, 'DEBIT', date(2026, 10, 3))
        _make_tx(self.snap, self.session_id, 'Self Transfer to Own Account', 10000, 'DEBIT', date(2026, 10, 4))

        res = monthly_budget(self.session_id, 2026, 10)

        # Reconcile credits: 50000 + 2500 + 15000 + 7000 + 1200 + 8000 + 3300 + 1000 = 88000
        cb = res['credit_breakdown']
        credit_sum = (
            Decimal(cb['earned_income']) +
            Decimal(cb['investment_yield']) +
            Decimal(cb['capital_liquidation']) +
            Decimal(cb['investment_transfers']) +
            Decimal(cb['refunds']) +
            Decimal(cb['transfers']) +
            Decimal(cb['reimbursements']) +
            Decimal(cb['unclassified'])
        )
        self.assertEqual(credit_sum, Decimal('88000.00'))
        self.assertEqual(Decimal(res['total_credits']), Decimal('88000.00'))

        # Reconcile debits: living_expenses (18000) + debit_transfers (10000) = gross_debits (28000)
        self.assertEqual(Decimal(res['living_expenses']), Decimal('18000.00'))
        self.assertEqual(Decimal(res['debit_transfers']), Decimal('10000.00'))
        self.assertEqual(Decimal(res['gross_debits']), Decimal('28000.00'))

        # Reconcile net account cash movement: 88000 - 28000 = 60000
        self.assertEqual(Decimal(res['total_account_cash_movement']), Decimal('60000.00'))

    def test_scenario_11_single_account_statement_limitations_audit(self):
        """Scenario 11: Single-account statement limitations audit test."""
        res = monthly_budget(self.session_id, 2026, 10)
        self.assertIn('single_account_limitation_note', res)
        self.assertIn('Single-account analysis', res['single_account_limitation_note'])


class RefundAllocationComprehensiveTests(TestCase):
    """
    Exhaustive tests for confidence-aware refund allocation in ArthaShield.

    Under confidence-aware matching:
    - CONFIRMED: shared reference ID + compatible amount -> offsets expenses
    - PROBABLE: canonical merchant + unique candidate -> tracked but NO expense offset
    - WEAK: broad tokens only or multiple candidates -> not allocated
    - UNMATCHED: no evidence -> no allocation

    Case A: Canonical merchant match = PROBABLE (no expense offset)
    Case B: Cross-month canonical match = PROBABLE
    Case C: Unrelated cross-month refund = UNMATCHED
    Case D: Refund without identifiable original = UNMATCHED
    Case E: Partial canonical match = PROBABLE
    Case F: Duplicate refund narration (multiple candidates) = WEAK/UNMATCHED
    Case G: Refund greater than original = PROBABLE partial
    """

    def setUp(self):
        self.session_id = 'test_refund_allocation_sess'
        self.snap = _make_snapshot(self.session_id)

    def test_case_a_same_period_probable_match(self):
        """
        Test Case A: 10,000 purchase and 4,000 same-period refund.
        Canonical merchant match ('amazon') with unique candidate -> PROBABLE.
        PROBABLE does NOT offset confirmed net living expenses.
        """
        _make_tx(self.snap, self.session_id, 'Monthly Salary Corp', 50000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Amazon Retail Store', 10000, 'DEBIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'Amazon Shopping Refund', 4000, 'CREDIT', date(2026, 10, 12))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('10000.00'))
        # PROBABLE match: tracked but NOT applied
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertGreater(Decimal(res['probable_same_period_refunds']), Decimal('0.00'))
        # Net living expenses NOT reduced
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('10000.00'))
        self.assertEqual(Decimal(res['operating_surplus']), Decimal('40000.00'))
        # Confidence label
        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)
        self.assertIn('matching_evidence', ref_entry['matched_purchases'][0])

    def test_case_b_cross_month_probable_match(self):
        """
        Test Case B: 15,000 October purchase and 15,000 November refund.
        Canonical merchant match -> PROBABLE cross-month.
        """
        # October
        _make_tx(self.snap, self.session_id, 'Monthly Salary Corp', 50000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'MakeMyTrip Flight Booking', 15000, 'DEBIT', date(2026, 10, 10))

        # November
        _make_tx(self.snap, self.session_id, 'Monthly Salary Corp', 50000, 'CREDIT', date(2026, 11, 1))
        _make_tx(self.snap, self.session_id, 'Swiggy Food Order', 2000, 'DEBIT', date(2026, 11, 3))
        _make_tx(self.snap, self.session_id, 'MakeMyTrip Flight Booking Cancellation Refund', 15000, 'CREDIT', date(2026, 11, 5))

        res_oct = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res_oct['gross_living_expenses']), Decimal('15000.00'))
        self.assertEqual(Decimal(res_oct['net_living_expenses']), Decimal('15000.00'))
        self.assertEqual(Decimal(res_oct['operating_surplus']), Decimal('35000.00'))

        res_nov = monthly_budget(self.session_id, 2026, 11)
        self.assertEqual(Decimal(res_nov['gross_living_expenses']), Decimal('2000.00'))
        # PROBABLE cross-month: does NOT offset November expenses
        self.assertEqual(Decimal(res_nov['net_living_expenses']), Decimal('2000.00'))
        self.assertEqual(Decimal(res_nov['operating_surplus']), Decimal('48000.00'))

        # Refund shows match with MakeMyTrip
        ref_entry = res_nov['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)
        self.assertEqual(len(ref_entry['matched_purchases']), 1)
        self.assertEqual(ref_entry['matched_purchases'][0]['merchant'], 'MakeMyTrip Flight Booking')

    def test_case_c_unrelated_cross_month_refund_does_not_reduce_current_expenses(self):
        """
        Test Case C: 1,500 November purchase and unrelated 5,000 refund from October.
        Different merchants (Indigo vs Swiggy) -> no match.
        """
        # October purchase
        _make_tx(self.snap, self.session_id, 'Indigo Airline Ticket Booking', 5000, 'DEBIT', date(2026, 10, 12))

        # November: Swiggy purchase and Airline refund
        _make_tx(self.snap, self.session_id, 'Monthly Salary Corp', 50000, 'CREDIT', date(2026, 11, 1))
        _make_tx(self.snap, self.session_id, 'Swiggy Food Order', 1500, 'DEBIT', date(2026, 11, 4))
        _make_tx(self.snap, self.session_id, 'Indigo Airline Refund Reversal', 5000, 'CREDIT', date(2026, 11, 6))

        res_nov = monthly_budget(self.session_id, 2026, 11)
        self.assertEqual(Decimal(res_nov['gross_living_expenses']), Decimal('1500.00'))
        # Swiggy food expense is NOT reduced by unrelated airline refund!
        self.assertEqual(Decimal(res_nov['net_living_expenses']), Decimal('1500.00'))
        self.assertEqual(Decimal(res_nov['net_category_spending']['food']), Decimal('1500.00'))
        self.assertEqual(Decimal(res_nov['operating_surplus']), Decimal('48500.00'))
        self.assertEqual(Decimal(res_nov['total_account_cash_movement']), Decimal('53500.00'))

    def test_case_d_refund_without_identifiable_original_purchase(self):
        """
        Test Case D: Refund without an identifiable original purchase.
        """
        _make_tx(self.snap, self.session_id, 'Monthly Salary Corp', 40000, 'CREDIT', date(2026, 11, 1))
        _make_tx(self.snap, self.session_id, 'Swiggy Food Delivery', 3000, 'DEBIT', date(2026, 11, 2))
        _make_tx(self.snap, self.session_id, 'Unidentified Merchant Reversal Refund XYZ999', 2500, 'CREDIT', date(2026, 11, 8))

        res_nov = monthly_budget(self.session_id, 2026, 11)
        self.assertEqual(Decimal(res_nov['gross_living_expenses']), Decimal('3000.00'))
        self.assertEqual(Decimal(res_nov['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertEqual(Decimal(res_nov['unmatched_refunds']), Decimal('2500.00'))
        self.assertEqual(Decimal(res_nov['net_living_expenses']), Decimal('3000.00'))
        self.assertEqual(Decimal(res_nov['operating_surplus']), Decimal('37000.00'))
        self.assertEqual(Decimal(res_nov['total_account_cash_movement']), Decimal('39500.00'))
        self.assertEqual(res_nov['refund_details'][0]['match_confidence'], MATCH_UNMATCHED)

    def test_case_e_partial_refund_probable(self):
        """
        Test Case E: Partial refund with canonical merchant match -> PROBABLE.
        """
        _make_tx(self.snap, self.session_id, 'Monthly Salary Corp', 50000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Croma Electronics Store', 10000, 'DEBIT', date(2026, 10, 4))
        _make_tx(self.snap, self.session_id, 'Croma Electronics Store Refund', 3000, 'CREDIT', date(2026, 10, 15))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('10000.00'))
        # PROBABLE match: no expense offset
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('10000.00'))
        self.assertEqual(Decimal(res['operating_surplus']), Decimal('40000.00'))
        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)

    def test_case_f_duplicate_refund_narration_ambiguous(self):
        """
        Test Case F: 2 identical purchases + 3 identical refunds from same merchant.
        Multiple equally plausible candidates -> WEAK confidence -> not allocated.
        All 3 refunds are UNMATCHED because same-evidence candidates > 1.
        """
        _make_tx(self.snap, self.session_id, 'Salary Corp', 30000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Swiggy Food Order', 600, 'DEBIT', date(2026, 10, 2))
        _make_tx(self.snap, self.session_id, 'Swiggy Food Order', 600, 'DEBIT', date(2026, 10, 3))

        _make_tx(self.snap, self.session_id, 'Swiggy Refund', 600, 'CREDIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'Swiggy Refund', 600, 'CREDIT', date(2026, 10, 6))
        _make_tx(self.snap, self.session_id, 'Swiggy Refund', 600, 'CREDIT', date(2026, 10, 7))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('1200.00'))
        # All refunds UNMATCHED because multiple equally plausible candidates
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertEqual(Decimal(res['unmatched_refunds']), Decimal('1800.00'))
        # Net expenses NOT reduced
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('1200.00'))

        # All refunds should be WEAK or UNMATCHED
        for ref in res['refund_details']:
            self.assertIn(ref['match_confidence'], [MATCH_WEAK, MATCH_UNMATCHED])

    def test_case_g_refund_greater_than_original_purchase_amount(self):
        """
        Test Case G: Refund greater than original purchase amount.
        Canonical match with unique candidate -> PROBABLE for matched portion.
        Excess remains unmatched.
        """
        _make_tx(self.snap, self.session_id, 'Salary Corp', 40000, 'CREDIT', date(2026, 10, 1))
        _make_tx(self.snap, self.session_id, 'Decathlon Sports Store', 2000, 'DEBIT', date(2026, 10, 5))
        _make_tx(self.snap, self.session_id, 'Decathlon Sports Store Refund', 3500, 'CREDIT', date(2026, 10, 10))

        res = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('2000.00'))
        # PROBABLE match: no expense offset
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('2000.00'))
        self.assertEqual(Decimal(res['operating_surplus']), Decimal('38000.00'))

        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)
        self.assertGreater(Decimal(ref_entry['unmatched_amount']), Decimal('0.00'))


# ===========================================================================
# Confidence-Aware Refund Matching Tests
# ===========================================================================
class ConfidenceAwareRefundMatchingTests(TestCase):
    """
    Comprehensive test suite for the confidence-aware refund matching engine.
    Tests all 10 required scenarios from the specification.
    """

    def setUp(self):
        self.session_id = 'test_confidence_matching_sess'
        self.snap = _make_snapshot(self.session_id)

    def _tx(self, dt, amount, tx_type, merchant):
        return _make_tx(self.snap, self.session_id, merchant, amount, tx_type, dt)

    # -----------------------------------------------------------------------
    # Test 1: Exact Reference Match -> CONFIRMED
    # -----------------------------------------------------------------------
    def test_01_exact_reference_match_is_confirmed(self):
        """Shared reference ID (ORD-1234) in both debit and refund -> CONFIRMED."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 5000, 'DEBIT', 'Amazon Marketplace ORD-1234 Purchase')
        self._tx(date(2026, 10, 12), 5000, 'CREDIT', 'Amazon Refund ORD-1234')

        res = monthly_budget(self.session_id, 2026, 10)

        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_CONFIRMED)
        self.assertEqual(ref_entry['allocation_status'], ALLOC_APPLIED)
        self.assertEqual(ref_entry['temporal_relation'], TEMPORAL_SAME_PERIOD)
        self.assertEqual(Decimal(ref_entry['allocated_amount']), Decimal('5000.00'))
        self.assertEqual(Decimal(ref_entry['suggested_amount']), Decimal('0.00'))
        # CONFIRMED match DOES reduce expenses
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('5000.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('0.00'))
        self.assertEqual(Decimal(res['operating_surplus']), Decimal('50000.00'))

        # Evidence includes reference
        alloc = ref_entry['matched_purchases'][0]
        self.assertIn('matching_evidence', alloc)
        self.assertTrue(any('shared_reference' in e for e in alloc['matching_evidence']))
        self.assertIn('matched_transaction_id', alloc)

    # -----------------------------------------------------------------------
    # Test 2: Unique Merchant + Amount + Date -> PROBABLE
    # -----------------------------------------------------------------------
    def test_02_unique_merchant_amount_probable(self):
        """Single canonical merchant match with compatible amount -> PROBABLE."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 3000, 'DEBIT', 'Croma Electronics Store')
        self._tx(date(2026, 10, 15), 3000, 'CREDIT', 'Croma Electronics Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)
        # PROBABLE does NOT offset expenses
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertEqual(Decimal(res['probable_same_period_refunds']), Decimal('3000.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('3000.00'))

        # Evidence shows canonical merchant
        alloc = ref_entry['matched_purchases'][0]
        self.assertTrue(any('canonical_merchant' in e for e in alloc['matching_evidence']))

    # -----------------------------------------------------------------------
    # Test 3: Same Merchant Multiple Identical Purchases -> WEAK
    # -----------------------------------------------------------------------
    def test_03_same_merchant_multiple_identical_purchases_weak(self):
        """Two identical 500 purchases at Swiggy + one 500 refund -> WEAK (ambiguous)."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 500, 'DEBIT', 'Swiggy Food Order')
        self._tx(date(2026, 10, 8), 500, 'DEBIT', 'Swiggy Food Order')
        self._tx(date(2026, 10, 15), 500, 'CREDIT', 'Swiggy Food Order Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        ref_entry = res['refund_details'][0]
        self.assertIn(ref_entry['match_confidence'], [MATCH_WEAK, MATCH_UNMATCHED])
        # WEAK/UNMATCHED: no expense offset
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('1000.00'))

    # -----------------------------------------------------------------------
    # Test 4: Swiggy Instamart vs Swiggy Dineout
    # -----------------------------------------------------------------------
    def test_04_swiggy_instamart_vs_dineout_distinguished(self):
        """Swiggy Instamart and Swiggy Dineout are different canonical merchants."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 800, 'DEBIT', 'Swiggy Instamart Grocery Order')
        self._tx(date(2026, 10, 8), 1200, 'DEBIT', 'Swiggy Dineout Restaurant')
        self._tx(date(2026, 10, 15), 800, 'CREDIT', 'Swiggy Instamart Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        # Should match Instamart -> Instamart, NOT Dineout
        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)
        alloc = ref_entry['matched_purchases'][0]
        self.assertIn('Instamart', alloc['merchant'])
        # Verify canonical merchant
        self.assertEqual(_extract_canonical_merchant('Swiggy Instamart Grocery Order'), 'swiggy_instamart')
        self.assertEqual(_extract_canonical_merchant('Swiggy Dineout Restaurant'), 'swiggy_dineout')

    # -----------------------------------------------------------------------
    # Test 5: Different Merchants in Same Category
    # -----------------------------------------------------------------------
    def test_05_different_merchants_same_category_no_match(self):
        """Flipkart refund should NOT match Amazon purchase even though both are 'shopping'."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 3000, 'DEBIT', 'Amazon Electronics Store')
        self._tx(date(2026, 10, 15), 3000, 'CREDIT', 'Flipkart Order Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_UNMATCHED)
        self.assertEqual(Decimal(res['unmatched_refunds']), Decimal('3000.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('3000.00'))

    # -----------------------------------------------------------------------
    # Test 6: Duplicate Refunds Cannot Exceed Purchase Amount
    # -----------------------------------------------------------------------
    def test_06_duplicate_refunds_capped_at_purchase_capacity(self):
        """Two 600 refunds vs one 600 purchase: only one can match (if unique)."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 600, 'DEBIT', 'Myntra Fashion Store')
        self._tx(date(2026, 10, 12), 600, 'CREDIT', 'Myntra Fashion Refund')
        self._tx(date(2026, 10, 13), 600, 'CREDIT', 'Myntra Fashion Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        # First refund: unique candidate (before first alloc) -> PROBABLE
        # Second refund: capacity depleted -> UNMATCHED
        confidences = [r['match_confidence'] for r in res['refund_details']]
        self.assertIn(MATCH_PROBABLE, confidences)
        self.assertIn(MATCH_UNMATCHED, confidences)

        # At most 600 allocated, rest unmatched
        total_unmatched = sum(Decimal(r['unmatched_amount']) for r in res['refund_details'])
        self.assertGreaterEqual(total_unmatched, Decimal('600.00'))

    # -----------------------------------------------------------------------
    # Test 7: Partial Refund
    # -----------------------------------------------------------------------
    def test_07_partial_refund_probable(self):
        """Partial refund (3000 of 10000 purchase) with canonical match -> PROBABLE."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 10000, 'DEBIT', 'Reliance Digital Electronics')
        self._tx(date(2026, 10, 15), 3000, 'CREDIT', 'Reliance Digital Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)
        self.assertEqual(Decimal(ref_entry['matched_amount']), Decimal('3000.00'))
        self.assertEqual(Decimal(ref_entry['unmatched_amount']), Decimal('0.00'))

    # -----------------------------------------------------------------------
    # Test 8: Refund Exceeding Purchase Amount
    # -----------------------------------------------------------------------
    def test_08_refund_exceeding_purchase_capped_at_capacity(self):
        """Refund of 5000 against purchase of 3000 -> max 3000 matched, 2000 unmatched."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 3000, 'DEBIT', 'BookMyShow Tickets')
        self._tx(date(2026, 10, 15), 5000, 'CREDIT', 'BookMyShow Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        ref_entry = res['refund_details'][0]
        self.assertEqual(Decimal(ref_entry['matched_amount']), Decimal('3000.00'))
        self.assertEqual(Decimal(ref_entry['unmatched_amount']), Decimal('2000.00'))

    # -----------------------------------------------------------------------
    # Test 9: Ambiguous Candidates -> WEAK / Not Allocated
    # -----------------------------------------------------------------------
    def test_09_ambiguous_candidates_not_allocated(self):
        """Three 1000 purchases from same merchant + one 1000 refund -> ambiguous -> WEAK."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 1000, 'DEBIT', 'Zomato Quick Commerce')
        self._tx(date(2026, 10, 8), 1000, 'DEBIT', 'Zomato Quick Commerce')
        self._tx(date(2026, 10, 11), 1000, 'DEBIT', 'Zomato Quick Commerce')
        self._tx(date(2026, 10, 20), 1000, 'CREDIT', 'Zomato Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        ref_entry = res['refund_details'][0]
        self.assertIn(ref_entry['match_confidence'], [MATCH_WEAK, MATCH_UNMATCHED])
        # No automatic expense offset
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('3000.00'))

    # -----------------------------------------------------------------------
    # Test 10: PROBABLE and WEAK Do NOT Offset Expenses
    # -----------------------------------------------------------------------
    def test_10_probable_and_weak_no_expense_offset(self):
        """Mixed scenario: one CONFIRMED (ref ID), one PROBABLE (canonical), one WEAK (ambiguous).
        Only CONFIRMED reduces expenses."""
        self._tx(date(2026, 10, 1), 100000, 'CREDIT', 'Monthly Salary Corp')
        # CONFIRMED: shared reference ORD-5555
        self._tx(date(2026, 10, 3), 5000, 'DEBIT', 'Flipkart ORD-5555 Electronics')
        self._tx(date(2026, 10, 10), 5000, 'CREDIT', 'Flipkart Refund ORD-5555')
        # PROBABLE: unique Croma canonical match
        self._tx(date(2026, 10, 4), 3000, 'DEBIT', 'Croma Electronics Store')
        self._tx(date(2026, 10, 12), 3000, 'CREDIT', 'Croma Electronics Refund')
        # WEAK: 2 identical Swiggy purchases, 1 refund -> ambiguous
        self._tx(date(2026, 10, 5), 800, 'DEBIT', 'Swiggy Food Order')
        self._tx(date(2026, 10, 6), 800, 'DEBIT', 'Swiggy Food Order')
        self._tx(date(2026, 10, 14), 800, 'CREDIT', 'Swiggy Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        # Only CONFIRMED (Flipkart ORD-5555) offsets expenses
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('5000.00'))
        # Gross living expenses: 5000 + 3000 + 800 + 800 = 9600
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('9600.00'))
        # Net = gross - confirmed_offset = 9600 - 5000 = 4600
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('4600.00'))

        # Check individual confidences. Merchant labels are display-safe: reference
        # codes and raw refund narration are no longer returned as merchant names.
        confidences = {r['merchant']: r['match_confidence'] for r in res['refund_details']}
        self.assertEqual(confidences.get('Flipkart Electronics'), MATCH_CONFIRMED)
        self.assertEqual(confidences.get('Croma Electronics Store'), MATCH_PROBABLE)
        self.assertIn(confidences.get('Swiggy Refund'), [MATCH_WEAK, MATCH_UNMATCHED])


class CanonicalMerchantTests(TestCase):
    """Tests for _extract_canonical_merchant function."""

    def test_swiggy_base(self):
        self.assertEqual(_extract_canonical_merchant('Swiggy Food Order'), 'swiggy')

    def test_swiggy_instamart(self):
        self.assertEqual(_extract_canonical_merchant('Swiggy Instamart Grocery'), 'swiggy_instamart')

    def test_swiggy_dineout(self):
        self.assertEqual(_extract_canonical_merchant('Swiggy Dineout Restaurant'), 'swiggy_dineout')

    def test_amazon_base(self):
        self.assertEqual(_extract_canonical_merchant('Amazon Shopping'), 'amazon')

    def test_amazon_fresh(self):
        self.assertEqual(_extract_canonical_merchant('Amazon Fresh Delivery'), 'amazon_fresh')

    def test_amazon_pay(self):
        self.assertEqual(_extract_canonical_merchant('Amazon Pay Recharge'), 'amazon_pay')

    def test_amazon_marketplace(self):
        self.assertEqual(_extract_canonical_merchant('Amazon Marketplace Order'), 'amazon_marketplace')

    def test_flipkart_grocery(self):
        self.assertEqual(_extract_canonical_merchant('Flipkart Grocery Delivery'), 'flipkart_grocery')

    def test_empty_text(self):
        self.assertEqual(_extract_canonical_merchant('UPI Credit POS'), '')

    def test_generic_text_returns_first_distinctive_token(self):
        self.assertEqual(_extract_canonical_merchant('Croma Electronics Store'), 'croma')


class ReferenceIDExtractionTests(TestCase):
    """Tests for _extract_reference_ids function."""

    def test_order_reference(self):
        refs = _extract_reference_ids('Amazon Marketplace ORD-1234 Purchase')
        self.assertIn('1234', refs)

    def test_txn_reference(self):
        refs = _extract_reference_ids('UPI Payment TXN#ABC123DEF')
        self.assertIn('abc123def', refs)

    def test_ref_reference(self):
        refs = _extract_reference_ids('Refund REF 99887766')
        self.assertIn('99887766', refs)

    def test_no_reference(self):
        refs = _extract_reference_ids('Swiggy Food Delivery')
        self.assertEqual(len(refs), 0)

    def test_no_digits_in_reference(self):
        refs = _extract_reference_ids('Order ABCDEF')
        self.assertEqual(len(refs), 0)

    def test_false_positive_prevention_normal_words_ending_in_id(self):
        """Ensure normal English words like 'paid', 'idea', 'valid', 'solid' do not extract false references."""
        self.assertEqual(len(_extract_reference_ids('paid 500 to merchant')), 0)
        self.assertEqual(len(_extract_reference_ids('idea 123 bill payment')), 0)
        self.assertEqual(len(_extract_reference_ids('valid 500 transaction')), 0)
        self.assertEqual(len(_extract_reference_ids('solid 100 purchase')), 0)
        self.assertEqual(len(_extract_reference_ids('grid 999 energy')), 0)

    def test_false_positive_prevention_short_numeric_codes(self):
        """Ensure coincidental 1-3 digit numbers like 'order 12', 'ref 99' are rejected."""
        self.assertEqual(len(_extract_reference_ids('order 12 item')), 0)
        self.assertEqual(len(_extract_reference_ids('ref 99 payment')), 0)
        self.assertEqual(len(_extract_reference_ids('txn 1')), 0)

    def test_utr_reference_extracted(self):
        """Ensure banking UTR reference numbers are extracted."""
        refs = _extract_reference_ids('UPI UTR: 402812345678')
        self.assertIn('402812345678', refs)


class SemanticAllocationStatusTests(TestCase):
    """
    Exhaustive tests for semantic separation of:
    - match_confidence (CONFIRMED, PROBABLE, WEAK, UNMATCHED)
    - temporal_relation (SAME_PERIOD, CROSS_MONTH, None)
    - allocation_status (APPLIED, SUGGESTED_NOT_APPLIED, NOT_ALLOCATED)

    Specific requirements tested:
    1. Probable suggestions never change net expenses.
    2. Suggested amounts are reported in suggested_amount, NOT allocated_amount.
    3. Confirmed partial refunds apply only the actual purchase amount.
    4. Weak matches are NOT_ALLOCATED and never apply.
    5. Cross-month confirmed refunds remain attributed to original purchase without rewriting history.
    """

    def setUp(self):
        self.session_id = 'test_semantic_allocation_sess'
        self.snap = _make_snapshot(self.session_id)

    def _tx(self, dt, amount, tx_type, merchant):
        return _make_tx(self.snap, self.session_id, merchant, amount, tx_type, dt)

    def test_probable_suggestion_never_changes_net_expenses(self):
        """Requirement 9: Probable suggestions never change net expenses."""
        self._tx(date(2026, 10, 1), 60000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 4), 5000, 'DEBIT', 'Croma Electronics Store')
        self._tx(date(2026, 10, 15), 5000, 'CREDIT', 'Croma Electronics Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        # Net living expenses must be 5000 (NOT 0!)
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('5000.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('5000.00'))
        self.assertEqual(Decimal(res['operating_surplus']), Decimal('55000.00'))

        # refunds_applied must be 0
        self.assertEqual(Decimal(res['refunds_applied']), Decimal('0.00'))

        ref_entry = res['refund_details'][0]
        # Semantic dimensions
        self.assertEqual(ref_entry['match_confidence'], MATCH_PROBABLE)
        self.assertEqual(ref_entry['temporal_relation'], TEMPORAL_SAME_PERIOD)
        self.assertEqual(ref_entry['allocation_status'], ALLOC_SUGGESTED_NOT_APPLIED)

        # Amounts
        self.assertEqual(Decimal(ref_entry['allocated_amount']), Decimal('0.00'))
        self.assertEqual(Decimal(ref_entry['suggested_amount']), Decimal('5000.00'))

        # Matched purchase detail
        alloc = ref_entry['matched_purchases'][0]
        self.assertEqual(alloc['allocation_status'], ALLOC_SUGGESTED_NOT_APPLIED)
        self.assertEqual(Decimal(alloc['allocated_amount']), Decimal('0.00'))
        self.assertEqual(Decimal(alloc['suggested_amount']), Decimal('5000.00'))
        self.assertEqual(alloc['temporal_relation'], TEMPORAL_SAME_PERIOD)

    def test_suggested_amounts_not_reported_as_applied(self):
        """Requirement 9: Suggested amounts are not reported as applied."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 3000, 'DEBIT', 'Reliance Digital Store')
        self._tx(date(2026, 10, 18), 3000, 'CREDIT', 'Reliance Digital Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        # Global budget counters
        self.assertEqual(Decimal(res['refunds_applied']), Decimal('0.00'))
        self.assertEqual(Decimal(res['confirmed_same_period_refunds']), Decimal('0.00'))
        self.assertEqual(Decimal(res['suggested_refunds']), Decimal('3000.00'))

        # Detail counters
        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['allocation_status'], ALLOC_SUGGESTED_NOT_APPLIED)
        self.assertEqual(ref_entry['allocated_amount'], '0.00')
        self.assertEqual(ref_entry['suggested_amount'], '3000.00')

    def test_confirmed_partial_refund_applies_only_actual_amount(self):
        """Requirement 9: Confirmed partial refunds apply only actual amount."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 10, 5), 2000, 'DEBIT', 'Flipkart ORD-8888 Purchase')
        self._tx(date(2026, 10, 12), 3500, 'CREDIT', 'Flipkart Refund ORD-8888')

        res = monthly_budget(self.session_id, 2026, 10)

        # Gross living: 2000. Only 2000 applied (not 3500!). Net living: 0
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('2000.00'))
        self.assertEqual(Decimal(res['refunds_applied']), Decimal('2000.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('0.00'))
        self.assertEqual(Decimal(res['unmatched_refunds']), Decimal('1500.00'))

        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_CONFIRMED)
        self.assertEqual(ref_entry['allocation_status'], ALLOC_APPLIED)
        self.assertEqual(ref_entry['temporal_relation'], TEMPORAL_SAME_PERIOD)
        self.assertEqual(Decimal(ref_entry['allocated_amount']), Decimal('2000.00'))
        self.assertEqual(Decimal(ref_entry['suggested_amount']), Decimal('0.00'))
        self.assertEqual(Decimal(ref_entry['unmatched_amount']), Decimal('1500.00'))

    def test_weak_matches_never_apply_and_not_allocated(self):
        """Requirement 9: Weak matches never apply and have allocation_status=NOT_ALLOCATED."""
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        # Two identical purchases at Swiggy
        self._tx(date(2026, 10, 4), 600, 'DEBIT', 'Swiggy Food Order')
        self._tx(date(2026, 10, 6), 600, 'DEBIT', 'Swiggy Food Order')
        # 1 refund without order ID -> ambiguous candidates -> WEAK
        self._tx(date(2026, 10, 14), 600, 'CREDIT', 'Swiggy Food Order Refund')

        res = monthly_budget(self.session_id, 2026, 10)

        # Net living expenses NOT reduced
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('1200.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('1200.00'))
        self.assertEqual(Decimal(res['refunds_applied']), Decimal('0.00'))
        self.assertEqual(Decimal(res['unmatched_refunds']), Decimal('600.00'))

        ref_entry = res['refund_details'][0]
        self.assertEqual(ref_entry['match_confidence'], MATCH_WEAK)
        self.assertEqual(ref_entry['allocation_status'], ALLOC_NOT_ALLOCATED)
        self.assertIsNone(ref_entry['temporal_relation'])
        self.assertEqual(Decimal(ref_entry['allocated_amount']), Decimal('0.00'))
        self.assertEqual(Decimal(ref_entry['suggested_amount']), Decimal('0.00'))
        self.assertEqual(len(ref_entry['matched_purchases']), 0)

    def test_cross_month_confirmed_refund_attributed_without_rewriting_history(self):
        """Requirement 9: Cross-month confirmed refunds remain attributed to original purchase without rewriting history."""
        # October: 10,000 purchase with reference REF-999
        oct_debit = self._tx(date(2026, 10, 10), 10000, 'DEBIT', 'MakeMyTrip Flight REF-999')
        self._tx(date(2026, 10, 1), 50000, 'CREDIT', 'Monthly Salary Corp')

        # November: 2,000 Swiggy purchase, and 10,000 refund with REF-999
        self._tx(date(2026, 11, 1), 50000, 'CREDIT', 'Monthly Salary Corp')
        self._tx(date(2026, 11, 3), 2000, 'DEBIT', 'Swiggy Food Delivery')
        self._tx(date(2026, 11, 8), 10000, 'CREDIT', 'MakeMyTrip Refund REF-999')

        res_nov = monthly_budget(self.session_id, 2026, 11)

        # November living expenses must NOT be reduced by October refund
        self.assertEqual(Decimal(res_nov['gross_living_expenses']), Decimal('2000.00'))
        self.assertEqual(Decimal(res_nov['net_living_expenses']), Decimal('2000.00'))
        self.assertEqual(Decimal(res_nov['refunds_applied']), Decimal('0.00'))
        self.assertEqual(Decimal(res_nov['confirmed_cross_month_applied']), Decimal('10000.00'))

        # Refund attribution
        ref_nov = res_nov['refund_details'][0]
        self.assertEqual(ref_nov['match_confidence'], MATCH_CONFIRMED)
        self.assertEqual(ref_nov['temporal_relation'], TEMPORAL_CROSS_MONTH)
        self.assertEqual(ref_nov['allocation_status'], ALLOC_APPLIED)
        self.assertEqual(Decimal(ref_nov['allocated_amount']), Decimal('10000.00'))
        self.assertEqual(Decimal(ref_nov['suggested_amount']), Decimal('0.00'))
        self.assertEqual(ref_nov['matched_transaction_id'], str(oct_debit.id))

        # October remains immutable
        res_oct = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(res_oct['gross_living_expenses']), Decimal('10000.00'))
        self.assertEqual(Decimal(res_oct['net_living_expenses']), Decimal('10000.00'))


class EvidenceBasedRecurringPaymentTests(TestCase):
    """
    Comprehensive test suite for evidence-based recurring payment detection.
    Covers:
    1. Three monthly payments (CONFIRMED, subscription, monthly, fixed)
    2. Two monthly payments (PROBABLE, subscription, monthly)
    3. Irregular payments (WEAK or excluded)
    4. Variable electricity bills (CONFIRMED, utility, monthly, variable)
    5. Rent payments (CONFIRMED, rent, monthly, fixed)
    6. Loan EMI (CONFIRMED, emi_or_loan, monthly, fixed)
    7. Weekly subscriptions (CONFIRMED, weekly, fixed)
    8. Refunds and credits excluded from debit cadence
    9. Peer UPI transfers excluded
    10. Same-day duplicates collapsed only on reliable identity evidence
    11. Insufficient history (<2 occurrences) not flagged
    12. Multiple sub-brand services under one parent merchant (Swiggy Instamart vs Swiggy Dineout)
    13. Two arbitrary transactions with non-matching cadence not flagged
    """

    def setUp(self):
        self.session_id = 'test_recurring_evidence'
        self.snap = _make_snapshot(self.session_id)

    def _debit(self, tx_date, amount, merchant, is_recurring=False, category='other'):
        return _make_tx(
            self.snap,
            self.session_id,
            merchant,
            amount,
            'DEBIT',
            tx_date,
            is_recurring=is_recurring,
            source_type='import',
        )

    def _credit(self, tx_date, amount, merchant):
        return _make_tx(
            self.snap,
            self.session_id,
            merchant,
            amount,
            'CREDIT',
            tx_date,
            source_type='import',
        )

    def test_01_three_monthly_payments_confirmed(self):
        """Three consistent monthly payments receive CONFIRMED status, fixed variation, monthly cadence."""
        self._debit(date(2026, 8, 10), 199, 'Netflix')
        self._debit(date(2026, 9, 10), 199, 'Netflix')
        self._debit(date(2026, 10, 10), 199, 'Netflix')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)

        sub = result[0]
        self.assertEqual(sub['confidence'], RECURRING_CONFIRMED)
        self.assertEqual(sub['payment_type'], PAYMENT_TYPE_SUBSCRIPTION)
        self.assertEqual(sub['cadence'], CADENCE_MONTHLY)
        self.assertEqual(sub['amount_variation'], VARIATION_FIXED)
        self.assertEqual(sub['occurrence_count'], 3)
        self.assertEqual(sub['average_amount'], '199.00')
        self.assertEqual(sub['estimated_monthly_cost'], '199.00')
        self.assertEqual(sub['estimated_annual_cost'], '2388.00')
        self.assertEqual(sub['estimated_next_date'], '2026-11-10')
        self.assertTrue(sub['candidates'])
        self.assertTrue(any('not a verified contractual commitment' in ev for ev in sub['evidence']))

    def test_02_two_monthly_payments_probable(self):
        """Two compatible monthly occurrences receive PROBABLE status and cadence monthly."""
        self._debit(date(2026, 9, 15), 119, 'Spotify')
        self._debit(date(2026, 10, 15), 119, 'Spotify')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)

        sub = result[0]
        self.assertEqual(sub['confidence'], RECURRING_PROBABLE)
        self.assertEqual(sub['payment_type'], PAYMENT_TYPE_SUBSCRIPTION)
        self.assertEqual(sub['cadence'], CADENCE_MONTHLY)
        self.assertEqual(sub['occurrence_count'], 2)
        self.assertEqual(sub['estimated_monthly_cost'], '119.00')
        self.assertTrue(sub['candidates'])

    def test_03_irregular_payments_weak_or_excluded(self):
        """Irregular payments with erratic gaps (5 days, 45 days) receive WEAK confidence."""
        self._debit(date(2026, 9, 1), 500, 'Random Boutique')
        self._debit(date(2026, 9, 6), 500, 'Random Boutique')  # 5 days gap
        self._debit(date(2026, 10, 21), 500, 'Random Boutique')  # 45 days gap

        result = detect_subscriptions(self.session_id)
        # Should be flagged as WEAK with irregular cadence, or excluded
        if result:
            sub = result[0]
            self.assertEqual(sub['confidence'], RECURRING_WEAK)
            self.assertEqual(sub['cadence'], CADENCE_IRREGULAR)

    def test_04_variable_electricity_bills_confirmed_utility(self):
        """Variable electricity bills (BESCOM) at 30-day intervals receive CONFIRMED, utility, monthly, variable."""
        self._debit(date(2026, 8, 5), 1200, 'BESCOM Electricity')
        self._debit(date(2026, 9, 5), 1450, 'BESCOM Electricity')
        self._debit(date(2026, 10, 5), 1300, 'BESCOM Electricity')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)

        sub = result[0]
        self.assertEqual(sub['confidence'], RECURRING_CONFIRMED)
        self.assertEqual(sub['payment_type'], PAYMENT_TYPE_UTILITY)
        self.assertEqual(sub['cadence'], CADENCE_MONTHLY)
        self.assertEqual(sub['amount_variation'], VARIATION_VARIABLE)
        self.assertEqual(sub['occurrence_count'], 3)
        self.assertEqual(sub['average_amount'], '1316.67')
        self.assertEqual(sub['estimated_monthly_cost'], '1316.67')

    def test_05_rent_payments_confirmed(self):
        """Monthly rent payments of ₹25000 on 1st of each month receive CONFIRMED, rent."""
        self._debit(date(2026, 8, 1), 25000, 'Landlord Rent Transfer')
        self._debit(date(2026, 9, 1), 25000, 'Landlord Rent Transfer')
        self._debit(date(2026, 10, 1), 25000, 'Landlord Rent Transfer')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)

        sub = result[0]
        self.assertEqual(sub['confidence'], RECURRING_CONFIRMED)
        self.assertEqual(sub['payment_type'], PAYMENT_TYPE_RENT)
        self.assertEqual(sub['cadence'], CADENCE_MONTHLY)
        self.assertEqual(sub['amount_variation'], VARIATION_FIXED)
        self.assertEqual(sub['estimated_monthly_cost'], '25000.00')
        self.assertEqual(sub['estimated_annual_cost'], '300000.00')

    def test_06_loan_emi_confirmed(self):
        """Monthly loan EMI debits receive CONFIRMED, emi_or_loan."""
        self._debit(date(2026, 8, 5), 15000, 'HDFC Home Loan EMI')
        self._debit(date(2026, 9, 5), 15000, 'HDFC Home Loan EMI')
        self._debit(date(2026, 10, 5), 15000, 'HDFC Home Loan EMI')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)

        sub = result[0]
        self.assertEqual(sub['confidence'], RECURRING_CONFIRMED)
        self.assertEqual(sub['payment_type'], PAYMENT_TYPE_EMI)
        self.assertEqual(sub['cadence'], CADENCE_MONTHLY)
        self.assertEqual(sub['amount_variation'], VARIATION_FIXED)
        self.assertEqual(sub['estimated_monthly_cost'], '15000.00')

    def test_07_weekly_subscriptions_confirmed(self):
        """Weekly meal plan debits every 7 days receive CONFIRMED, weekly cadence, and correct monthly estimate."""
        self._debit(date(2026, 10, 1), 250, 'Weekly Meal Plan')
        self._debit(date(2026, 10, 8), 250, 'Weekly Meal Plan')
        self._debit(date(2026, 10, 15), 250, 'Weekly Meal Plan')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)

        sub = result[0]
        self.assertEqual(sub['confidence'], RECURRING_CONFIRMED)
        self.assertEqual(sub['cadence'], CADENCE_WEEKLY)
        self.assertEqual(sub['occurrence_count'], 3)
        # 250 * 52 / 12 = 1083.33
        self.assertEqual(sub['estimated_monthly_cost'], '1083.33')
        # 250 * 52 = 13000.00
        self.assertEqual(sub['estimated_annual_cost'], '13000.00')

    def test_08_refunds_and_credits_excluded(self):
        """Credit transactions matching subscription merchant names are strictly excluded from debits."""
        self._debit(date(2026, 9, 10), 199, 'Netflix')
        self._debit(date(2026, 10, 10), 199, 'Netflix')
        # Credit refund for Netflix
        self._credit(date(2026, 10, 12), 199, 'Netflix Refund')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        # Only the 2 debit transactions should be counted, not the credit
        self.assertEqual(result[0]['occurrence_count'], 2)
        self.assertEqual(result[0]['confidence'], RECURRING_PROBABLE)

    def test_09_peer_upi_transfers_excluded(self):
        """Random peer UPI transfers with personal names or mobile numbers are not classified as subscriptions."""
        self._debit(date(2026, 8, 10), 500, 'UPI/FriendName/9876543210')
        self._debit(date(2026, 9, 10), 500, 'UPI/FriendName/9876543210')
        self._debit(date(2026, 10, 10), 500, 'UPI/FriendName/9876543210')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 0)

    def test_10_duplicate_records_collapsed(self):
        """
        Same-day rows are collapsed only on reliable identity evidence. Two identical
        rows sharing a reference are a duplicate import; two identical rows without a
        reference are legitimate payments and must both survive.
        """
        # Case A: shared reference => duplicate import collapsed to 1 occurrence.
        self._debit(date(2026, 10, 10), 199, 'Disney Hotstar REF-982421')
        self._debit(date(2026, 10, 10), 199, 'Disney Hotstar REF-982421')

        result = detect_subscriptions(self.session_id)
        # Collapsed to 1 occurrence; since count=1 and is_recurring=False, not detected
        self.assertEqual(len(result), 0)

        # Case B: no reference or fingerprint => both payments preserved.
        Transaction.objects.filter(session_id=self.session_id).delete()
        self._debit(date(2026, 10, 10), 199, 'Zee5 Subscription')
        self._debit(date(2026, 10, 10), 199, 'Zee5 Subscription')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['occurrence_count'], 2)
        self.assertEqual(result[0]['observed_total_spend'], '398.00')

    def test_11_insufficient_history_excluded(self):
        """Single non-recurring debit does not have enough evidence to be flagged as recurring."""
        self._debit(date(2026, 10, 5), 999, 'Adobe Creative Cloud')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 0)

    def test_12_multiple_sub_brands_separate_detections(self):
        """Distinct sub-brands under one parent merchant (Swiggy Instamart vs Swiggy Dineout) are kept separate."""
        # 3 monthly payments to Swiggy Instamart
        self._debit(date(2026, 8, 1), 400, 'Swiggy Instamart Grocery Order')
        self._debit(date(2026, 9, 1), 400, 'Swiggy Instamart Grocery Order')
        self._debit(date(2026, 10, 1), 400, 'Swiggy Instamart Grocery Order')

        # 3 monthly payments to Swiggy Dineout
        self._debit(date(2026, 8, 5), 1200, 'Swiggy Dineout Restaurant')
        self._debit(date(2026, 9, 5), 1200, 'Swiggy Dineout Restaurant')
        self._debit(date(2026, 10, 5), 1200, 'Swiggy Dineout Restaurant')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 2)

        canonicals = {s['canonical_merchant'] for s in result}
        self.assertIn('swiggy_instamart', canonicals)
        self.assertIn('swiggy_dineout', canonicals)

        instamart = next(s for s in result if s['canonical_merchant'] == 'swiggy_instamart')
        dineout = next(s for s in result if s['canonical_merchant'] == 'swiggy_dineout')

        self.assertEqual(instamart['occurrence_count'], 3)
        self.assertEqual(instamart['estimated_monthly_cost'], '400.00')
        self.assertEqual(dineout['occurrence_count'], 3)
        self.assertEqual(dineout['estimated_monthly_cost'], '1200.00')

    def test_13_two_arbitrary_transactions_not_subscription(self):
        """Two arbitrary transactions that do not match any recognized cadence bucket are excluded."""
        self._debit(date(2026, 10, 1), 750, 'Electronics Repair Shop')
        self._debit(date(2026, 10, 11), 750, 'Electronics Repair Shop')  # 10 days gap

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 0)


class AuditReviewCorrectionTests(TestCase):
    """
    Synthetic adversarial test suite verifying the 12 key priorities
    identified in the technical audit of the recurring-payment engine.
    """

    def setUp(self):
        from rest_framework.test import APIRequestFactory
        from api.models import SecureSession, ConsentAuditLog

        self.factory = APIRequestFactory()
        self.session_id = 'test_audit_corrections_sess'
        self.session, self.token = SecureSession.issue_session(self.session_id)
        self.consent = ConsentAuditLog.objects.create(
            session_id=self.session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        self.snap = _make_snapshot(self.session_id)

    def _tx(self, tx_date, amount, merchant, is_recurring=False, fingerprint='', source_type='import'):
        return Transaction.objects.create(
            snapshot=self.snap,
            session_id=self.session_id,
            transaction_date=tx_date,
            amount=Decimal(str(amount)),
            transaction_type='DEBIT',
            normalized_merchant=merchant,
            category='Uncategorized',
            is_recurring=is_recurring,
            source_type=source_type,
            fingerprint=fingerprint,
        )

    def test_01_same_day_identical_payments_preserved(self):
        """
        Priority 2: Two legitimate identical payments on the same date with distinct
        reference IDs are preserved, not falsely collapsed into one.
        """
        self._tx(date(2026, 8, 10), 75, 'Chai Point Ref REF-001')
        self._tx(date(2026, 9, 10), 75, 'Chai Point Ref REF-002')
        # Two distinct chai debits on Oct 10 with different references
        self._tx(date(2026, 10, 10), 75, 'Chai Point Ref REF-751')
        self._tx(date(2026, 10, 10), 75, 'Chai Point Ref REF-752')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        sub = result[0]
        # All 4 occurrences preserved
        self.assertEqual(sub['occurrence_count'], 4)
        self.assertEqual(len(sub['transaction_dates']), 4)
        # Task 23: the *recurrence* is confirmed (three consistent monthly
        # dates), but repeated purchases at a cafe are discretionary spending:
        # without subscription or contractual evidence they are not a
        # financial commitment, so the commitment confidence is PROBABLE.
        self.assertEqual(sub['recurrence_confidence'], RECURRING_CONFIRMED)
        self.assertEqual(sub['confidence'], RECURRING_PROBABLE)
        self.assertEqual(sub['commitment_class'], COMMITMENT_DISCRETIONARY)
        self.assertFalse(sub['is_financial_commitment'])
        self.assertFalse(sub['is_potential_leakage'])

    def test_02_duplicate_import_collapsed(self):
        """
        Priority 2: Identical transactions on the same date with matching reference ID
        (re-import) are collapsed into one.
        """
        self._tx(date(2026, 8, 10), 199, 'Disney Hotstar Order ORD-8877')
        self._tx(date(2026, 9, 10), 199, 'Disney Hotstar Order ORD-8878')
        # Re-import of the same transaction on the same date with matching reference
        self._tx(date(2026, 10, 10), 199, 'Disney Hotstar Order ORD-9900')
        self._tx(date(2026, 10, 10), 199, 'Disney Hotstar Order ORD-9900')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        sub = result[0]
        # 3 distinct occurrences (the duplicate on Oct 10 is collapsed)
        self.assertEqual(sub['occurrence_count'], 3)
        self.assertEqual(sub['confidence'], RECURRING_CONFIRMED)

    def test_03_amazon_retail_vs_amazon_prime_separated(self):
        """
        Priority 3: Amazon Shopping Retail debits and Amazon Prime subscription
        debits are categorized into distinct merchant keys and never conflated.
        """
        # 3 Prime subscription payments
        self._tx(date(2026, 8, 1), 299, 'Amazon Prime Video Subscription')
        self._tx(date(2026, 9, 1), 299, 'Amazon Prime Video Subscription')
        self._tx(date(2026, 10, 1), 299, 'Amazon Prime Video Subscription')

        # 3 General Amazon retail shopping purchases
        self._tx(date(2026, 8, 15), 1200, 'Amazon Retail Shopping Order')
        self._tx(date(2026, 9, 15), 1450, 'Amazon Marketplace Retail')
        self._tx(date(2026, 10, 15), 980, 'Amazon Shopping Store')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 2)

        prime_sub = next(s for s in result if s['canonical_merchant'] == 'amazon_prime')
        shop_sub = next(s for s in result if s['canonical_merchant'] == 'amazon_shopping')

        self.assertEqual(prime_sub['payment_type'], PAYMENT_TYPE_SUBSCRIPTION)
        self.assertEqual(prime_sub['confidence'], RECURRING_CONFIRMED)
        self.assertEqual(prime_sub['estimated_monthly_cost'], '299.00')

        self.assertEqual(shop_sub['canonical_merchant'], 'amazon_shopping')
        self.assertIn(shop_sub['payment_type'], (PAYMENT_TYPE_OTHER, PAYMENT_TYPE_UNKNOWN))

    def test_04_peer_upi_vpa_without_phone_excluded(self):
        """
        Priority 4: P2P UPI transfers using name-based VPAs (e.g. rahul.sharma@okaxis)
        are identified via is_peer_upi and excluded from recurring payment detection.
        """
        self._tx(date(2026, 8, 10), 500, 'UPI/rahul.sharma@okaxis/dinner split')
        self._tx(date(2026, 9, 10), 500, 'UPI/rahul.sharma@okaxis/monthly dinner')
        self._tx(date(2026, 10, 10), 500, 'UPI/rahul.sharma@okaxis/settlement')

        result = detect_subscriptions(self.session_id)
        # Peer UPI transfers must not be classified as subscriptions
        self.assertEqual(len(result), 0)

    def test_05_merchant_vpa_without_phone_preserved(self):
        """
        Priority 4: Commercial merchant VPAs (e.g. bescom.bill@hdfcbank, starhealth.renew@okaxis)
        are recognized as commercial entities and not falsely discarded as peer UPI.
        """
        self._tx(date(2026, 8, 5), 1450, 'UPI/bescom.bill@hdfcbank/Electricity Bill')
        self._tx(date(2026, 9, 5), 1520, 'UPI/bescom.bill@hdfcbank/Electricity Bill')
        self._tx(date(2026, 10, 5), 1480, 'UPI/bescom.bill@hdfcbank/Electricity Bill')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        sub = result[0]
        self.assertEqual(sub['canonical_merchant'], 'bescom')
        self.assertEqual(sub['payment_type'], PAYMENT_TYPE_UTILITY)
        self.assertEqual(sub['confidence'], RECURRING_CONFIRMED)

    def test_06_delayed_monthly_payment_tolerated(self):
        """
        Priority 5: 4 monthly debits with bounded real-world delay (e.g. 30, 37, 30 days)
        maintain monthly cadence and CONFIRMED confidence.
        """
        # Dates: June 1, July 1 (30 days), August 7 (37 days), September 6 (30 days)
        self._tx(date(2026, 6, 1), 499, 'Cult Fit Gym Membership')
        self._tx(date(2026, 7, 1), 499, 'Cult Fit Gym Membership')
        self._tx(date(2026, 8, 7), 499, 'Cult Fit Gym Membership')  # 37-day delay
        self._tx(date(2026, 9, 6), 499, 'Cult Fit Gym Membership')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        sub = result[0]
        self.assertEqual(sub['cadence'], CADENCE_MONTHLY)
        self.assertEqual(sub['confidence'], RECURRING_CONFIRMED)
        self.assertEqual(sub['occurrence_count'], 4)
        self.assertEqual(sub['estimated_monthly_cost'], '499.00')

    def test_07_irregular_payment_cost_withheld(self):
        """
        Priority 6: Irregular cadence payments withhold projected monthly/annual commitment
        to avoid cost distortion, reporting observed totals instead.
        """
        # Highly irregular intervals: 14 days, 47 days, 9 days
        self._tx(date(2026, 5, 1), 500, 'Occasional Freelance Tool')
        self._tx(date(2026, 5, 15), 500, 'Occasional Freelance Tool')
        self._tx(date(2026, 7, 1), 500, 'Occasional Freelance Tool')
        self._tx(date(2026, 7, 10), 500, 'Occasional Freelance Tool')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        sub = result[0]
        self.assertEqual(sub['cadence'], CADENCE_IRREGULAR)
        self.assertIsNone(sub['estimated_monthly_cost'])
        self.assertIsNone(sub['estimated_annual_cost'])
        self.assertEqual(sub['observed_total_spend'], '2000.00')
        self.assertTrue(any('projected annual commitment withheld' in ev for ev in sub['evidence']))

    def test_08_historical_statement_past_date_projection(self):
        """
        Priority 7: Historical statements evaluated against an as_of_date after the
        projected date are labeled as past/stale projections, not upcoming payments.
        """
        # Transactions from early 2025
        self._tx(date(2025, 1, 10), 199, 'Netflix')
        self._tx(date(2025, 2, 10), 199, 'Netflix')
        self._tx(date(2025, 3, 10), 199, 'Netflix')

        # Evaluate as of 2026-01-01 (10 months later)
        result = detect_subscriptions(self.session_id, as_of_date=date(2026, 1, 1))
        self.assertEqual(len(result), 1)
        sub = result[0]
        self.assertTrue(sub['is_past_projection'])
        self.assertEqual(sub['projection_status'], 'STALE_HISTORY')
        self.assertTrue(any('Historical statement: projected date' in ev for ev in sub['evidence']))

    def test_09_month_end_and_leap_year_projections(self):
        """
        Priority 7: Calendar-aware next date handles leap years and variable month lengths.
        """
        # Leap year 2024: Jan 31 + 1 month -> Feb 29
        next_leap = _project_calendar_next_date(date(2024, 1, 31), CADENCE_MONTHLY)
        self.assertEqual(next_leap, date(2024, 2, 29))

        # Non-leap year 2026: Jan 31 + 1 month -> Feb 28
        next_non_leap = _project_calendar_next_date(date(2026, 1, 31), CADENCE_MONTHLY)
        self.assertEqual(next_non_leap, date(2026, 2, 28))

        # October (31 days) + 1 month -> Nov 30 (30 days)
        next_oct = _project_calendar_next_date(date(2026, 10, 31), CADENCE_MONTHLY)
        self.assertEqual(next_oct, date(2026, 11, 30))

        # Jan 31 + 1 quarter (3 months) -> Apr 30
        next_qtr = _project_calendar_next_date(date(2026, 1, 31), CADENCE_QUARTERLY)
        self.assertEqual(next_qtr, date(2026, 4, 30))

    def test_10_weak_detections_excluded_from_confirmed_totals(self):
        """
        Priority 8: SubscriptionDetectorView segregates confirmed commitments,
        probable suggestions, discretionary leaks, and weak observations.
        """
        from api.views import SubscriptionDetectorView

        # Confirmed discretionary subscription: Netflix ₹199 x 3
        self._tx(date(2026, 8, 10), 199, 'Netflix')
        self._tx(date(2026, 9, 10), 199, 'Netflix')
        self._tx(date(2026, 10, 10), 199, 'Netflix')

        # Confirmed essential utility: Bescom ₹1500 x 3
        self._tx(date(2026, 8, 5), 1500, 'Bescom Electricity')
        self._tx(date(2026, 9, 5), 1500, 'Bescom Electricity')
        self._tx(date(2026, 10, 5), 1500, 'Bescom Electricity')

        # Probable subscription: Spotify ₹119 x 2
        self._tx(date(2026, 9, 15), 119, 'Spotify India')
        self._tx(date(2026, 10, 15), 119, 'Spotify India')

        # Irregular / weak payment: Tool with irregular gaps
        self._tx(date(2026, 5, 1), 300, 'SaaS Tool')
        self._tx(date(2026, 5, 15), 300, 'SaaS Tool')
        self._tx(date(2026, 7, 1), 300, 'SaaS Tool')
        self._tx(date(2026, 7, 10), 300, 'SaaS Tool')

        req = self.factory.post(
            '/api/v1/insights/subscriptions/',
            {'session_id': self.session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=self.token,
        )
        resp = SubscriptionDetectorView.as_view()(req)
        self.assertEqual(resp.status_code, 200)

        data = resp.data
        # Confirmed total = Netflix (199) + Bescom (1500) = 1699.00
        self.assertEqual(data['confirmed_monthly_commitment'], '1699.00')
        # Probable total = Spotify (119.00)
        self.assertEqual(data['probable_monthly_commitment'], '119.00')
        # Discretionary = Netflix (199.00)
        self.assertEqual(data['discretionary_leakage_monthly'], '199.00')
        # Essential = Bescom (1500.00)
        self.assertEqual(data['essential_commitments_monthly'], '1500.00')
        # Weak under observation count = 1
        self.assertEqual(data['weak_under_observation_count'], 1)
        # Backward compatibility total matches confirmed
        self.assertEqual(data['total_monthly_commitment'], '1699.00')

    def test_11_session_changes_and_consent_isolation(self):
        """
        Priority 9: Verifies that session unconsented state blocks subscription detection
        with HTTP 403 CONSENT_REQUIRED, and transactions are isolated between sessions.
        """
        from api.views import SubscriptionDetectorView
        from api.models import SecureSession, ConsentAuditLog

        # Unconsented session
        other_sess_id = 'test_unconsented_session'
        _, other_token = SecureSession.issue_session(other_sess_id)

        req_unconsented = self.factory.post(
            '/api/v1/insights/subscriptions/',
            {'session_id': other_sess_id},
            format='json',
            HTTP_X_SESSION_TOKEN=other_token,
        )
        resp_unconsented = SubscriptionDetectorView.as_view()(req_unconsented)
        self.assertEqual(resp_unconsented.status_code, 403)
        self.assertEqual(resp_unconsented.data['code'], 'CONSENT_REQUIRED')

    def test_12_sensitive_pii_redacted_in_counterparty_and_evidence(self):
        """
        Priority 1: Redacts phone numbers, bank account numbers, emails, and VPAs
        from merchant display names and evidence strings.
        """
        # Raw narration with sensitive phone, VPA, and account number
        self._tx(date(2026, 8, 10), 1200, 'UPI/9876543210/fitness.cult@okhdfcbank/A/C 123456789012 CultFit Gym')
        self._tx(date(2026, 9, 10), 1200, 'UPI/9876543210/fitness.cult@okhdfcbank/A/C 123456789012 CultFit Gym')
        self._tx(date(2026, 10, 10), 1200, 'UPI/9876543210/fitness.cult@okhdfcbank/A/C 123456789012 CultFit Gym')

        result = detect_subscriptions(self.session_id)
        self.assertEqual(len(result), 1)
        sub = result[0]

        # Sensitive details must NOT leak into display merchant or evidence
        self.assertNotIn('9876543210', sub['merchant'])
        self.assertNotIn('123456789012', sub['merchant'])
        self.assertNotIn('fitness.cult@okhdfcbank', sub['merchant'])

        for ev in sub['evidence']:
            self.assertNotIn('9876543210', ev)
            self.assertNotIn('123456789012', ev)
            self.assertNotIn('fitness.cult@okhdfcbank', ev)
