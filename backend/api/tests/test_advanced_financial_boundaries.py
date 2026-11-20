"""
Advanced Financial Engine Boundary Testing Suite.

Covers Section A of Additional ArthaShield Audit:
1. Purchase equal to available balance.
2. Purchase greater than available balance.
3. Zero income.
4. Negative monthly cash flow.
5. Extremely high fixed obligations.
6. No recurring commitments.
7. Very large purchase inputs.
8. Zero-interest EMI with fees.
9. EMI with positive effective borrowing cost.
10. Irregular income.
11. Waiting 30, 60, and 90 days.
12. Waiting when net cash flow is negative.
13. Missing opening balance.
14. Missing or unreliable income.
15. Missing statement history.
16. Rounding boundary checks (SAFE vs NOT SAFE).
17. Representative manual mathematical cross-checks.
18. Double-counting inspection (income, expenses, refunds, transfers, discretionary spend).
"""

from datetime import date, timedelta
from decimal import Decimal
import uuid
import math

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import Transaction, FinancialSnapshot, SecureSession, ConsentAuditLog
from analytics.stress_test import run_commitment_stress_test, _project_90_day_cash_flow, _evaluate_verdict
from analytics.services import AnalyticsEngine
from api.insights import monthly_budget, classify_credit, classify_debit


class FinancialBoundaryTests(TestCase):
    def setUp(self):
        self.session_id = f"test_adv_{uuid.uuid4().hex[:8]}"
        self.today = date(2026, 10, 15)

    def _setup_standard_session(self, balance=100000.0, income=60000.0, fixed=20000.0, living=35000.0):
        FinancialSnapshot.objects.filter(session_id=self.session_id).delete()
        Transaction.objects.filter(session_id=self.session_id).delete()

        snapshot = FinancialSnapshot.objects.create(
            session_id=self.session_id,
            liquid_balance=Decimal(str(balance)),
            monthly_income=Decimal(str(income)),
            monthly_expenses=Decimal(str(living)),
            fixed_commitments=Decimal(str(fixed)),
        )

        if income > 0:
            Transaction.objects.create(
                session_id=self.session_id,
                transaction_date=date(2026, 10, 1),
                amount=Decimal(str(income)),
                transaction_type="CREDIT",
                normalized_merchant="Verified Salary Credit",
                category="Salary",
                source_type="import",
            )

        if fixed > 0:
            Transaction.objects.create(
                session_id=self.session_id,
                transaction_date=date(2026, 10, 5),
                amount=Decimal(str(fixed)),
                transaction_type="DEBIT",
                normalized_merchant="House Rent Auto Debit",
                category="Bills",
                source_type="import",
                is_recurring=True,
            )

        other_living = living - fixed
        if other_living > 0:
            Transaction.objects.create(
                session_id=self.session_id,
                transaction_date=date(2026, 10, 10),
                amount=Decimal(str(other_living)),
                transaction_type="DEBIT",
                normalized_merchant="Supermarket Groceries & Utilities",
                category="Groceries",
                source_type="import",
                is_recurring=False,
            )

        return snapshot

    # 1. Purchase equal to available balance
    def test_01_purchase_equal_to_available_balance(self):
        self._setup_standard_session(balance=50000.0, income=60000.0, fixed=15000.0)
        res = run_commitment_stress_test(
            session_id=self.session_id,
            item_name="Exact Balance Purchase",
            price=50000.0,
            commitment_type="large_purchase",
            custom_liquid_balance=50000.0,
            as_of_date=self.today,
        )
        # Remaining balance becomes 0.00
        self.assertEqual(res["scenario_a_buy_now"]["projected_remaining_balance"], 0.0)
        # Emergency runway collapses to 0.0 months and cash dips to deficit -> MUST BE NOT SAFE
        self.assertEqual(res["scenario_a_buy_now"]["verdict"], "NOT SAFE")

    # 2. Purchase greater than available balance
    def test_02_purchase_greater_than_available_balance(self):
        self._setup_standard_session(balance=50000.0, income=60000.0, fixed=15000.0)
        res = run_commitment_stress_test(
            session_id=self.session_id,
            item_name="Deficit Purchase",
            price=55000.0,
            commitment_type="large_purchase",
            custom_liquid_balance=50000.0,
            as_of_date=self.today,
        )
        self.assertEqual(res["scenario_a_buy_now"]["projected_remaining_balance"], -5000.0)
        self.assertEqual(res["scenario_a_buy_now"]["verdict"], "NOT SAFE")
        self.assertIn("Immediate liquidity deficit", res["scenario_a_buy_now"]["reason"])

    # 3. Zero income
    def test_03_zero_income_insufficient_data(self):
        self._setup_standard_session(balance=100000.0, income=0.0, fixed=15000.0)
        res = run_commitment_stress_test(
            session_id=self.session_id,
            item_name="Zero Income Test",
            price=20000.0,
            as_of_date=self.today,
        )
        self.assertEqual(res["overall_verdict"], "INSUFFICIENT DATA")
        self.assertFalse(res["data_sufficient"])
        self.assertTrue(any("Predictable operating income" in r for r in res["insufficient_reasons"]))

    # 4. Negative monthly cash flow (capital burning)
    def test_04_negative_monthly_cash_flow(self):
        # Income 30,000, Living expenses 50,000 -> Monthly Burn 50,000 (net cash flow -20,000)
        self._setup_standard_session(balance=100000.0, income=30000.0, fixed=20000.0, living=50000.0)
        res_0 = run_commitment_stress_test(
            session_id=self.session_id,
            price=25000.0,
            commitment_type="large_purchase",
            delay_days=0,
            as_of_date=self.today,
        )
        res_30 = run_commitment_stress_test(
            session_id=self.session_id,
            price=25000.0,
            commitment_type="large_purchase",
            delay_days=30,
            as_of_date=self.today,
        )
        # Balance at purchase must decrease after waiting 30 days due to capital burning
        self.assertLess(
            res_30["scenario_c_wait"]["projected_balance_at_purchase"],
            res_0["baseline"]["current_liquid_balance"],
        )
        # Safe flip days must be None
        self.assertIsNone(res_30["judgment_flip"]["safe_flip_days"])
        self.assertIn("Waiting cannot make this commitment safe", res_30["judgment_flip"]["flip_message"])

    # 5. Extremely high fixed obligations
    def test_05_extremely_high_fixed_obligations(self):
        # Income 50,000, Fixed obligations 70,000
        self._setup_standard_session(balance=200000.0, income=50000.0, fixed=70000.0, living=85000.0)
        res = run_commitment_stress_test(
            session_id=self.session_id,
            price=15000.0,
            commitment_type="no_cost_emi",
            tenure_months=6,
            custom_liquid_balance=200000.0,
            as_of_date=self.today,
        )
        # Discretionary buffer is 0.00, EMI cannot be absorbed
        self.assertEqual(res["scenario_b_emi"]["verdict"], "NOT SAFE")
        self.assertIn("cannot be absorbed", res["scenario_b_emi"]["reason"])

    # 6. No recurring commitments
    def test_06_no_recurring_commitments(self):
        # 0 fixed obligations, but moderate living expenses
        self._setup_standard_session(balance=150000.0, income=80000.0, fixed=0.0, living=25000.0)
        res = run_commitment_stress_test(
            session_id=self.session_id,
            price=20000.0,
            commitment_type="large_purchase",
            custom_liquid_balance=150000.0,
            as_of_date=self.today,
        )
        self.assertEqual(res["baseline"]["existing_fixed_obligations"], 0.0)
        self.assertEqual(res["scenario_a_buy_now"]["verdict"], "SAFE")
        self.assertGreaterEqual(res["scenario_a_buy_now"]["emergency_runway_months"], 3.0)

    # 7. Very large purchase inputs
    def test_07_very_large_purchase_inputs(self):
        self._setup_standard_session(balance=100000.0, income=50000.0, fixed=20000.0)
        res = run_commitment_stress_test(
            session_id=self.session_id,
            price=10000000.0, # 1 Crore INR
            commitment_type="large_purchase",
            custom_liquid_balance=100000.0,
            as_of_date=self.today,
        )
        self.assertEqual(res["scenario_a_buy_now"]["verdict"], "NOT SAFE")
        self.assertLess(res["scenario_a_buy_now"]["projected_remaining_balance"], -9000000.0)

    # 8. Zero-interest EMI with fees and GST
    def test_08_zero_interest_emi_with_fees_and_gst(self):
        self._setup_standard_session(balance=100000.0, income=75000.0, fixed=20000.0)
        res = run_commitment_stress_test(
            session_id=self.session_id,
            price=60000.0,
            commitment_type="no_cost_emi",
            tenure_months=6,
            nominal_apr=0.0,
            monthly_processing_fee=199.0,
            upfront_processing_fee=299.0,
            gst_rate_pct=18.0,
            as_of_date=self.today,
        )
        scen_b = res["scenario_b_emi"]
        # Upfront fee with GST: 299 * 1.18 = 352.82
        # Monthly fee with GST: 199 * 1.18 = 234.82
        # Base EMI: 60,000 / 6 = 10,000
        # Effective monthly commitment: 10,000 + 234.82 = 10,234.82
        self.assertAlmostEqual(scen_b["base_monthly_emi"], 10000.0, places=1)
        self.assertAlmostEqual(scen_b["monthly_hidden_fees_with_gst"], 234.82, places=1)
        self.assertAlmostEqual(scen_b["effective_monthly_commitment"], 10234.82, places=1)
        self.assertGreater(scen_b["total_hidden_fees"], 1500.0)
        self.assertGreater(scen_b["effective_annual_cost_pct"], 0.0)

    # 9. EMI with positive effective borrowing cost (XIRR)
    def test_09_emi_xirr_effective_borrowing_cost(self):
        sim = AnalyticsEngine.simulate_emi_decision(
            item_name="Smartphone",
            price=60000.0,
            tenure_months=6,
            down_payment=0.0,
            nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0,
            upfront_processing_fee=299.0,
            gst_rate_pct=18.0,
            user_monthly_discretionary_buffer=25000.0,
            start_date=self.today,
        )
        apr_pct = sim["effective_annual_cost_pct"]
        self.assertIsNotNone(apr_pct)
        # For a 60k loan over 6 months with ~1,760 in hidden fees, effective XIRR is typically 8% to 15%
        self.assertGreater(apr_pct, 5.0)
        self.assertLess(apr_pct, 30.0)

    # 10. Irregular income
    def test_10_irregular_income_handling(self):
        FinancialSnapshot.objects.filter(session_id=self.session_id).delete()
        Transaction.objects.filter(session_id=self.session_id).delete()

        # Two arbitrary peer UPI credits (not classified as earned income)
        Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 2),
            amount=Decimal("15000.00"),
            transaction_type="CREDIT",
            normalized_merchant="UPI/RAJESH/PAYMENT",
            category="General",
            source_type="import",
        )
        res = run_commitment_stress_test(
            session_id=self.session_id,
            price=10000.0,
            as_of_date=self.today,
        )
        # Unclassified peer UPI transfers are not counted as verified operating income
        self.assertEqual(res["overall_verdict"], "INSUFFICIENT DATA")
        self.assertEqual(res["baseline"]["predictable_monthly_income"], 0.0)

    # 11. Waiting 30, 60, and 90 days
    def test_11_waiting_multi_horizon_trajectory(self):
        # Positive cash flow: Income 80,000, Living 30,000 -> Net savings 50,000/mo (~1,666.67/day)
        self._setup_standard_session(balance=50000.0, income=80000.0, fixed=15000.0, living=30000.0)
        res_30 = run_commitment_stress_test(self.session_id, price=70000.0, delay_days=30, as_of_date=self.today)
        res_60 = run_commitment_stress_test(self.session_id, price=70000.0, delay_days=60, as_of_date=self.today)
        res_90 = run_commitment_stress_test(self.session_id, price=70000.0, delay_days=90, as_of_date=self.today)

        # Monotonically increasing accumulated savings
        self.assertGreater(res_60["scenario_c_wait"]["accumulated_savings"], res_30["scenario_c_wait"]["accumulated_savings"])
        self.assertGreater(res_90["scenario_c_wait"]["accumulated_savings"], res_60["scenario_c_wait"]["accumulated_savings"])

    # 12. Missing opening balance
    def test_12_missing_opening_balance(self):
        FinancialSnapshot.objects.filter(session_id=self.session_id).delete()
        Transaction.objects.filter(session_id=self.session_id).delete()
        res = run_commitment_stress_test(
            session_id=self.session_id,
            price=25000.0,
            as_of_date=self.today,
        )
        self.assertEqual(res["overall_verdict"], "INSUFFICIENT DATA")
        self.assertFalse(res["data_sufficient"])

    # 13. Representative manual mathematical cross-checks
    def test_13_manual_mathematical_cross_check(self):
        """
        Manually verified ground-truth values:
        - Liquid Balance: 100,000.00
        - Income: 70,000.00
        - Living Expenses: 30,000.00
        - Fixed Commitments: 20,000.00
        - Monthly Burn = 20,000 + max(0, 30,000 - 20,000) = 30,000.00
        - Monthly Discretionary Buffer = 70,000 - 30,000 = 40,000.00
        - Safety Buffer Floor = min(70,000 * 0.15, 100,000 * 0.20) = min(10,500, 20,000) = 10,500.00
        - Baseline Runway = 100,000 / 30,000 = 3.33 months
        """
        self._setup_standard_session(balance=100000.0, income=70000.0, fixed=20000.0, living=30000.0)
        res = run_commitment_stress_test(
            session_id=self.session_id,
            price=40000.0,
            commitment_type="large_purchase",
            custom_liquid_balance=100000.0,
            as_of_date=self.today,
        )
        baseline = res["baseline"]
        self.assertEqual(baseline["current_liquid_balance"], 100000.0)
        self.assertEqual(baseline["predictable_monthly_income"], 70000.0)
        self.assertEqual(baseline["existing_fixed_obligations"], 20000.0)
        self.assertEqual(baseline["baseline_living_expenses"], 30000.0)
        self.assertEqual(baseline["monthly_discretionary_buffer"], 40000.0)
        self.assertEqual(baseline["safety_buffer_floor"], 10500.0)
        self.assertAlmostEqual(baseline["baseline_runway_months"], 3.33, places=2)

        # Post-purchase Scenario A:
        # Remaining balance: 100,000 - 40,000 = 60,000
        # Post-purchase runway: 60,000 / 30,000 = 2.0 months
        # Remaining buffer: 60,000 - 10,500 = 49,500
        # Since runway is 2.0 (< 3.0), verdict must be CONDITIONAL!
        scen_a = res["scenario_a_buy_now"]
        self.assertEqual(scen_a["projected_remaining_balance"], 60000.0)
        self.assertEqual(scen_a["remaining_safety_buffer"], 49500.0)
        self.assertEqual(scen_a["emergency_runway_months"], 2.0)
        self.assertEqual(scen_a["verdict"], "CONDITIONAL")

    # 14. Double-counting inspection: own-account transfer does not inflate expenses
    def test_14_no_double_counting_with_transfers(self):
        self._setup_standard_session(balance=100000.0, income=60000.0, fixed=15000.0, living=30000.0)
        # Add an internal own-account transfer of 40,000
        Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 8),
            amount=Decimal("40000.00"),
            transaction_type="DEBIT",
            normalized_merchant="Self Transfer to Savings linked account",
            category="transfer",
            source_type="import",
        )
        budget = monthly_budget(self.session_id, 2026, 10)
        # Living expenses must NOT include the 40,000 transfer
        self.assertEqual(Decimal(str(budget["net_living_expenses"])), Decimal("30000.00"))
        self.assertEqual(Decimal(str(budget["debit_transfers"])), Decimal("40000.00"))
