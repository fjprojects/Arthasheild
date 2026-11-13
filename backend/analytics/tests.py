import math
from datetime import date
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from analytics.services import AnalyticsEngine
from api.models import DecisionScenario


class EmiSimulatorCalculationTests(TestCase):
    """
    Comprehensive regression test suite for EMI Reality Check Simulator.
    Tests zero interest, non-zero interest, processing fees, multiple tenures,
    and edge-case numerical resilience.
    """

    def test_zero_interest_zero_fee(self):
        """Zero interest loan with zero processing fee: true APR must be 0%."""
        result = AnalyticsEngine.simulate_emi_decision(
            item_name="Budget Smartphone",
            price=36000.0,
            tenure_months=6,
            down_payment=0.0,
            nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=0.0,
            user_monthly_discretionary_buffer=15000.0,
        )
        self.assertEqual(result["principal"], 36000.0)
        self.assertEqual(result["base_monthly_emi"], 6000.0)
        self.assertEqual(result["monthly_emi"], 6000.0)
        self.assertEqual(result["total_interest_paid"], 0.0)
        self.assertEqual(result["total_hidden_fees_and_gst"], 0.0)
        self.assertEqual(result["total_overall_cost"], 36000.0)
        self.assertEqual(result["total_repayment"], 36000.0)
        self.assertEqual(result["true_effective_apr_pct"], 0.0)
        self.assertEqual(result["cost_breakdown"]["principal_financed"], 36000.0)
        self.assertEqual(result["cost_breakdown"]["total_fees_and_gst"], 0.0)

    def test_zero_interest_with_processing_fee_trap(self):
        """0% No-Cost EMI with monthly processing fee exposes true effective APR."""
        price = 65000.0
        tenure = 12
        monthly_fee = 199.0  # 199 + 18% GST = 234.82/mo
        result = AnalyticsEngine.simulate_emi_decision(
            item_name="Flagship Smartphone",
            price=price,
            tenure_months=tenure,
            down_payment=0.0,
            nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=monthly_fee,
            user_monthly_discretionary_buffer=14000.0,
            start_date=date(2026, 1, 1),
        )
        expected_fee_with_gst = round(199.0 * 1.18, 2)  # 234.82
        expected_total_fees = round(expected_fee_with_gst * tenure, 2)  # 2817.84
        base_emi = round(price / tenure, 2)  # 5416.67
        expected_monthly = round(base_emi + expected_fee_with_gst, 2)  # 5651.49

        self.assertEqual(result["principal"], price)
        self.assertEqual(result["base_monthly_emi"], base_emi)
        self.assertEqual(result["monthly_emi"], expected_monthly)
        self.assertEqual(result["total_hidden_fees_and_gst"], expected_total_fees)
        self.assertEqual(result["cost_breakdown"]["total_fees_and_gst"], expected_total_fees)
        self.assertGreater(result["true_effective_apr_pct"], 0.0)
        # Correct XIRR (actual/365) for these exact cash flows. The old
        # simplified fee-load formula returned 4.34% and is now a regression guard.
        self.assertEqual(result["true_effective_apr_pct"], 8.24)
        self.assertEqual(result["apr_calculation"]["method"], "XIRR_ACTUAL_365")
        self.assertTrue(result["is_effective_cost_available"])
        self.assertIn("affordability_verdict", result)
        self.assertIn("status", result["affordability_verdict"])

    def test_standard_interest_multiple_tenures(self):
        """Tests standard interest-bearing loans across tenures (3, 6, 12, 24 months)."""
        tenures = [3, 6, 9, 12, 18, 24]
        price = 60000.0
        down_payment = 10000.0
        principal = price - down_payment
        apr = 12.0
        fee = 99.0

        for tenure in tenures:
            result = AnalyticsEngine.simulate_emi_decision(
                item_name=f"Laptop {tenure}M",
                price=price,
                tenure_months=tenure,
                down_payment=down_payment,
                nominal_annual_interest_rate_pct=apr,
                monthly_processing_or_conv_fee=fee,
                user_monthly_discretionary_buffer=20000.0,
                start_date=date(2026, 1, 1),
            )
            self.assertEqual(result["principal"], principal)
            self.assertEqual(result["tenure_months"], tenure)
            self.assertGreater(result["base_monthly_emi"], 0.0)
            self.assertGreater(result["monthly_emi"], result["base_monthly_emi"])
            self.assertGreater(result["total_overall_cost"], price)
            self.assertGreaterEqual(result["true_effective_apr_pct"], apr)
            self.assertFalse(math.isnan(result["true_effective_apr_pct"]))
            self.assertFalse(math.isinf(result["true_effective_apr_pct"]))

    def test_affordability_verdict_thresholds(self):
        """Verifies LOW RISK (<=25%), MODERATE (25-40%), and HIGH RISK (>40%) classifications."""
        buffer = 10000.0

        # Case 1: Low Risk (Outflow <= 2500)
        low_res = AnalyticsEngine.simulate_emi_decision(
            item_name="Affordable Item",
            price=12000.0,
            tenure_months=6,
            monthly_processing_or_conv_fee=0.0,
            user_monthly_discretionary_buffer=buffer,
        )
        self.assertEqual(low_res["affordability_verdict"]["status"], "LOW RISK")
        self.assertTrue(low_res["is_viable"])

        # Case 2: Moderate Risk (Outflow between 2500 and 4000)
        mod_res = AnalyticsEngine.simulate_emi_decision(
            item_name="Mid-range Item",
            price=18000.0,
            tenure_months=6,
            monthly_processing_or_conv_fee=0.0,
            user_monthly_discretionary_buffer=buffer,
        )
        self.assertEqual(mod_res["affordability_verdict"]["status"], "MODERATE")
        self.assertTrue(mod_res["is_viable"])

        # Case 3: High Risk (Outflow > 4000)
        high_res = AnalyticsEngine.simulate_emi_decision(
            item_name="Expensive Item",
            price=30000.0,
            tenure_months=6,
            monthly_processing_or_conv_fee=0.0,
            user_monthly_discretionary_buffer=buffer,
        )
        self.assertEqual(high_res["affordability_verdict"]["status"], "HIGH RISK")
        self.assertFalse(high_res["is_viable"])

    def test_edge_cases_zero_principal_and_invalid_inputs(self):
        """Zero principal, down payment equal to price, zero tenure or negative inputs must not raise errors."""
        # Down payment equals price
        res1 = AnalyticsEngine.simulate_emi_decision(
            item_name="Full Cash Down",
            price=50000.0,
            tenure_months=12,
            down_payment=50000.0,
            nominal_annual_interest_rate_pct=15.0,
            monthly_processing_or_conv_fee=0.0,
        )
        self.assertEqual(res1["principal"], 0.0)
        self.assertEqual(res1["base_monthly_emi"], 0.0)
        # No principal is financed, so an effective annual cost is undefined.
        self.assertIsNone(res1["true_effective_apr_pct"])
        self.assertFalse(res1["is_effective_cost_available"])
        self.assertEqual(res1["apr_calculation"]["status"], "NOT_APPLICABLE")
        self.assertEqual(res1["apr_calculation"]["reason"], "NO_PRINCIPAL_FINANCED")

        # Zero tenure clamped to at least 1
        res2 = AnalyticsEngine.simulate_emi_decision(
            item_name="Clamp Tenure",
            price=10000.0,
            tenure_months=0,
            nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=0.0,
        )
        self.assertEqual(res2["tenure_months"], 1)
        self.assertEqual(res2["base_monthly_emi"], 10000.0)

        # Negative inputs clamped safely
        res3 = AnalyticsEngine.simulate_emi_decision(
            item_name="Negative Inputs",
            price=-1000.0,
            tenure_months=-5,
            down_payment=-500.0,
            nominal_annual_interest_rate_pct=-10.0,
            monthly_processing_or_conv_fee=-50.0,
        )
        self.assertEqual(res3["price"], 0.0)
        self.assertEqual(res3["tenure_months"], 1)
        # Invalid/zero inputs must not raise and must not silently claim 0% APR.
        self.assertIsNone(res3["true_effective_apr_pct"])
        self.assertEqual(res3["apr_calculation"]["status"], "NOT_APPLICABLE")
        self.assertEqual(res3["apr_calculation"]["reason"], "NO_PRINCIPAL_FINANCED")


class EmiSimulatorApiViewTests(TestCase):
    """API endpoint tests for POST /api/v1/analytics/simulate-emi/."""

    def setUp(self):
        self.client = APIClient()

    def test_api_simulate_emi_success(self):
        payload = {
            "item_name": "Premium Laptop",
            "price": 85000.0,
            "tenure_months": 12,
            "down_payment": 5000.0,
            "nominal_apr": 10.5,
            "monthly_processing_fee": 149.0,
            "discretionary_buffer": 18000.0,
        }
        response = self.client.post(
            "/api/v1/analytics/simulate-emi/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        # Verify both legacy flat keys and modern structured contracts exist
        self.assertEqual(data["item_name"], "Premium Laptop")
        self.assertEqual(data["principal"], 80000.0)
        self.assertIn("monthly_emi", data)
        self.assertIn("effective_monthly_outflow", data)
        self.assertIn("true_effective_apr_pct", data)
        self.assertIn("effective_apr_pct", data)
        self.assertIn("cost_breakdown", data)
        self.assertEqual(data["cost_breakdown"]["principal_financed"], 80000.0)
        self.assertIn("total_fees_and_gst", data["cost_breakdown"])
        self.assertIn("total_cash_outflow", data["cost_breakdown"])
        self.assertIn("affordability_verdict", data)
        self.assertIn("status", data["affordability_verdict"])
        self.assertIn("buffer_consumed_pct", data["affordability_verdict"])

        # Verify scenario was recorded in DB
        self.assertTrue(DecisionScenario.objects.filter(item_name="Premium Laptop").exists())

    def test_api_simulate_emi_zero_interest(self):
        payload = {
            "item_name": "Smartphone 0% Promo",
            "price": 40000.0,
            "tenure_months": 6,
            "down_payment": 0.0,
            "nominal_apr": 0.0,
            "monthly_processing_fee": 0.0,
            "discretionary_buffer": 15000.0,
        }
        response = self.client.post(
            "/api/v1/analytics/simulate-emi/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["true_effective_apr_pct"], 0.0)
        self.assertEqual(data["monthly_emi"], round(40000.0 / 6, 2))
        self.assertEqual(data["cost_breakdown"]["total_fees_and_gst"], 0.0)
