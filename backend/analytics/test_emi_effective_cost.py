"""
Task 18 — EMI effective annual borrowing cost (XIRR) regressions.

The effective cost is derived from dated borrower cash flows:

    NPV(r) = sum( CF(i) / (1 + r) ** (days(i) / 365) ) = 0

Reference values in this module are produced by an *independent*
Newton-Raphson solver (``_reference_xirr``), not by the production bisection
helper. Closed-form cases are asserted directly as well, so the tests do not
validate the production code against itself.
"""
import calendar
import importlib
import json
import math
from datetime import date

from django.apps import apps as django_apps
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from analytics.services import AnalyticsEngine
from api.models import DecisionScenario

EMI_URL = '/api/v1/analytics/simulate-emi/'


# ---------------------------------------------------------------------------
# Independent reference implementation (different algorithm from production)
# ---------------------------------------------------------------------------

def _add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _reference_xirr(cash_flows, guess: float = 0.10, tolerance: float = 1e-13,
                    max_iterations: int = 200) -> float:
    """Independent Newton-Raphson XIRR (actual/365).

    Deliberately a different root-finding algorithm from the production
    bisection solver. Raises AssertionError if it cannot converge.
    """
    flows = sorted((d, float(a)) for d, a in cash_flows)
    t0 = flows[0][0]
    times = [(d - t0).days / 365.0 for d, _ in flows]
    amounts = [a for _, a in flows]

    def npv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** t for a, t in zip(amounts, times))

    def derivative(rate: float) -> float:
        return sum(
            -t * a / (1.0 + rate) ** (t + 1.0) for a, t in zip(amounts, times)
        )

    rate = guess
    for _ in range(max_iterations):
        f = npv(rate)
        slope = derivative(rate)
        if slope == 0.0:
            break
        candidate = rate - (f / slope)
        if candidate <= -1.0:
            candidate = (rate - 1.0) / 2.0
        if abs(candidate - rate) < tolerance:
            return candidate
        rate = candidate
    raise AssertionError('independent reference XIRR did not converge')


def _reference_cash_flows(price, n, nominal_pct=0.0, monthly_fee=0.0,
                          upfront_fee=0.0, gst_pct=18.0,
                          start=date(2026, 1, 1), down_payment=0.0):
    """Independent construction of the borrower's dated cash flows (floats)."""
    principal = price - down_payment
    if nominal_pct <= 0 or principal <= 0:
        emi = principal / n
    else:
        r = nominal_pct / 100.0 / 12.0
        factor = (1.0 + r) ** n
        emi = principal * r * factor / (factor - 1.0)
    gst = gst_pct / 100.0
    monthly_out = emi + monthly_fee * (1.0 + gst)
    net_disbursement = principal - upfront_fee * (1.0 + gst)
    flows = [(start, net_disbursement)]
    for k in range(1, n + 1):
        flows.append((_add_months(start, k), -monthly_out))
    return flows


def _reference_apr_pct(**kwargs) -> float:
    return _reference_xirr(_reference_cash_flows(**kwargs)) * 100.0


def _old_simplified_fee_load(price, n, monthly_fee, gst_pct=18.0, nominal_pct=0.0):
    """The pre-Task-18 formula, retained only to prove it is no longer used."""
    monthly_fee_with_gst = monthly_fee * (1.0 + gst_pct / 100.0)
    total_fees = monthly_fee_with_gst * n
    years = n / 12.0
    return round(nominal_pct + ((total_fees / price) / years) * 100.0, 2)


def _walk_non_finite(value, path='$'):
    """Return paths of NaN/Infinity numbers in a nested response structure."""
    hits = []
    if isinstance(value, dict):
        for key, nested in value.items():
            hits.extend(_walk_non_finite(nested, f'{path}.{key}'))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            hits.extend(_walk_non_finite(nested, f'{path}[{index}]'))
    elif isinstance(value, float) and not math.isfinite(value):
        hits.append(path)
    return hits


class XirrSolverTests(TestCase):
    """Root-solver correctness, convergence and failure behaviour."""

    def test_closed_form_one_year_returns_exact_rate(self):
        flows = [(date(2026, 1, 1), 1000.0), (date(2027, 1, 1), -1100.0)]
        result = AnalyticsEngine.calculate_xirr(flows)
        self.assertEqual(result['status'], 'OK')
        # +1000 today, -1100 in exactly 365 days => 10% annual effective.
        self.assertAlmostEqual(result['annual_rate_pct'], 10.0, delta=0.001)
        self.assertEqual(result['method'], 'XIRR_ACTUAL_365')
        self.assertTrue(result['converged'])

    def test_balanced_flows_return_zero_rate(self):
        flows = [
            (date(2026, 1, 1), 5000.0),
            (date(2026, 2, 1), -2500.0),
            (date(2026, 3, 1), -2500.0),
        ]
        result = AnalyticsEngine.calculate_xirr(flows)
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['annual_rate_pct'], 0.0)

    def test_no_sign_change_is_reported_not_fabricated(self):
        all_positive = AnalyticsEngine.calculate_xirr(
            [(date(2026, 1, 1), 100.0), (date(2026, 6, 1), 200.0)]
        )
        all_negative = AnalyticsEngine.calculate_xirr(
            [(date(2026, 1, 1), -100.0), (date(2026, 6, 1), -200.0)]
        )
        for result in (all_positive, all_negative):
            self.assertEqual(result['status'], 'UNAVAILABLE')
            self.assertEqual(result['reason'], 'NO_SIGN_CHANGE')
            self.assertIsNone(result['annual_rate'])
            self.assertIsNone(result['annual_rate_pct'])

    def test_invalid_cash_flows_are_rejected_safely(self):
        cases = [
            ([(date(2026, 1, 1), 100.0)], 'INSUFFICIENT_CASH_FLOWS'),
            ([(None, 100.0), (date(2026, 6, 1), -100.0)], 'INVALID_CASH_FLOW_DATE'),
            ([('not-a-date', 100.0), (date(2026, 6, 1), -100.0)], 'INVALID_CASH_FLOW_DATE'),
            ([(date(2026, 1, 1), 'oops'), (date(2026, 6, 1), -100.0)], 'INVALID_CASH_FLOW_AMOUNT'),
            ([(date(2026, 1, 1), float('nan')), (date(2026, 6, 1), -100.0)], 'INVALID_CASH_FLOW_AMOUNT'),
            ([(date(2026, 1, 1), float('inf')), (date(2026, 6, 1), -100.0)], 'INVALID_CASH_FLOW_AMOUNT'),
        ]
        for flows, reason in cases:
            result = AnalyticsEngine.calculate_xirr(flows)
            self.assertEqual(result['status'], 'UNAVAILABLE', msg=reason)
            self.assertEqual(result['reason'], reason)
            self.assertIsNone(result['annual_rate'])

    def test_non_convergence_is_reported(self):
        flows = [(date(2026, 1, 1), 1000.0), (date(2027, 1, 1), -1100.0)]
        result = AnalyticsEngine.calculate_xirr(flows, max_iterations=1)
        self.assertEqual(result['status'], 'UNAVAILABLE')
        self.assertEqual(result['reason'], 'NO_CONVERGENCE')
        self.assertFalse(result['converged'])
        self.assertIsNone(result['annual_rate'])

    def test_unbracketable_inverted_flow_is_reported(self):
        # Pay 200 today to receive 100 in a year: no positive-rate bracket.
        flows = [(date(2026, 1, 1), -200.0), (date(2027, 1, 1), 100.0)]
        result = AnalyticsEngine.calculate_xirr(flows)
        self.assertEqual(result['status'], 'UNAVAILABLE')
        self.assertEqual(result['reason'], 'NO_BRACKET')
        self.assertIsNone(result['annual_rate'])

    def test_long_horizon_extreme_rates_fail_cleanly(self):
        # A 50-year horizon makes the naive discount factor overflow at large
        # trial rates; the solver must fail cleanly instead of raising.
        flows = [(date(2026, 1, 1), -200.0), (date(2076, 1, 1), 100.0)]
        result = AnalyticsEngine.calculate_xirr(flows)
        self.assertEqual(result['status'], 'UNAVAILABLE')
        self.assertIn(result['reason'], {'NO_BRACKET', 'NO_CONVERGENCE'})
        self.assertIsNone(result['annual_rate'])
        self.assertIsNone(result['annual_rate_pct'])


class EmiEffectiveCostTests(TestCase):
    """Cash-flow scenarios and their independently calculated reference APRs."""

    def _sim(self, **kwargs):
        kwargs.setdefault('item_name', 'Scenario')
        kwargs.setdefault('start_date', date(2026, 1, 1))
        return AnalyticsEngine.simulate_emi_decision(**kwargs)

    def test_01_zero_interest_no_fees(self):
        result = self._sim(
            price=36000, tenure_months=6, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=0.0,
        )
        self.assertTrue(result['is_effective_cost_available'])
        self.assertEqual(result['effective_annual_cost_pct'], 0.0)
        self.assertEqual(result['apr_calculation']['status'], 'OK')
        self.assertEqual(result['apr_calculation']['net_disbursement'], 36000.0)
        self.assertEqual(result['fee_assumptions']['fees_paid'], 'none')
        self.assertEqual(len(result['apr_calculation']['cash_flows']), 7)

    def test_02_positive_interest_no_fees(self):
        result = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=12.0,
            monthly_processing_or_conv_fee=0.0,
        )
        reference = _reference_apr_pct(price=60000, n=12, nominal_pct=12.0)
        self.assertAlmostEqual(result['effective_annual_cost_pct'], reference, delta=0.01)
        # Monthly compounding makes the effective cost exceed the nominal rate.
        self.assertGreater(result['effective_annual_cost_pct'], 12.0)
        self.assertEqual(result['nominal_annual_interest_rate_pct'], 12.0)
        self.assertEqual(result['fee_assumptions']['fees_paid'], 'none')

    def test_03_upfront_processing_fee_without_gst(self):
        result = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=0.0, upfront_processing_fee=1000.0,
            gst_rate_pct=0.0,
        )
        reference = _reference_apr_pct(
            price=60000, n=12, upfront_fee=1000.0, gst_pct=0.0
        )
        self.assertAlmostEqual(result['effective_annual_cost_pct'], reference, delta=0.01)
        self.assertAlmostEqual(result['effective_annual_cost_pct'], 3.17, delta=0.01)
        self.assertEqual(result['total_hidden_fees_and_gst'], 1000.0)
        self.assertEqual(result['fee_assumptions']['upfront_fee_with_gst'], 1000.0)
        self.assertFalse(result['fee_assumptions']['gst_applied'])

    def test_04_upfront_processing_fee_with_gst(self):
        result = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=0.0, upfront_processing_fee=1000.0,
            gst_rate_pct=18.0,
        )
        reference = _reference_apr_pct(
            price=60000, n=12, upfront_fee=1000.0, gst_pct=18.0
        )
        self.assertAlmostEqual(result['effective_annual_cost_pct'], reference, delta=0.01)
        self.assertAlmostEqual(result['effective_annual_cost_pct'], 3.76, delta=0.01)
        self.assertEqual(result['total_hidden_fees_and_gst'], 1180.0)
        self.assertEqual(result['fee_assumptions']['upfront_fee_gst'], 180.0)
        self.assertTrue(result['fee_assumptions']['gst_applied'])

    def test_05_monthly_recurring_fee_without_gst(self):
        result = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0, gst_rate_pct=0.0,
        )
        reference = _reference_apr_pct(price=60000, n=12, monthly_fee=199.0, gst_pct=0.0)
        self.assertAlmostEqual(result['effective_annual_cost_pct'], reference, delta=0.01)
        self.assertAlmostEqual(result['effective_annual_cost_pct'], 7.55, delta=0.01)
        self.assertEqual(result['total_hidden_fees_and_gst'], 2388.0)

    def test_06_monthly_recurring_fee_with_gst(self):
        result = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0, gst_rate_pct=18.0,
        )
        reference = _reference_apr_pct(price=60000, n=12, monthly_fee=199.0, gst_pct=18.0)
        self.assertAlmostEqual(result['effective_annual_cost_pct'], reference, delta=0.01)
        self.assertAlmostEqual(result['effective_annual_cost_pct'], 8.94, delta=0.01)
        self.assertEqual(result['total_hidden_fees_and_gst'], 2817.84)
        self.assertEqual(result['fee_assumptions']['recurring_fee_with_gst_per_month'], 234.82)

    def test_07_both_upfront_and_recurring_charges(self):
        result = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0, upfront_processing_fee=1000.0,
            gst_rate_pct=18.0,
        )
        reference = _reference_apr_pct(
            price=60000, n=12, monthly_fee=199.0, upfront_fee=1000.0, gst_pct=18.0
        )
        self.assertAlmostEqual(result['effective_annual_cost_pct'], reference, delta=0.01)
        self.assertAlmostEqual(result['effective_annual_cost_pct'], 13.09, delta=0.01)
        self.assertGreater(result['effective_annual_cost_pct'], 8.94)
        self.assertEqual(result['fee_assumptions']['fees_paid'], 'upfront_and_monthly')

    def test_08_different_tenures(self):
        price, nominal, fee = 50000, 12.0, 99.0
        for tenure in (3, 6, 9, 12, 18, 24):
            result = self._sim(
                price=price, tenure_months=tenure,
                nominal_annual_interest_rate_pct=nominal,
                monthly_processing_or_conv_fee=fee,
            )
            reference = _reference_apr_pct(
                price=price, n=tenure, nominal_pct=nominal, monthly_fee=fee
            )
            self.assertAlmostEqual(
                result['effective_annual_cost_pct'], reference, delta=0.01,
                msg=f'tenure={tenure}',
            )
            self.assertGreaterEqual(result['effective_annual_cost_pct'], nominal)
            self.assertEqual(result['tenure_months'], tenure)
            self.assertEqual(len(result['apr_calculation']['cash_flows']), tenure + 1)
            self.assertFalse(_walk_non_finite(result))

    def test_09_month_end_and_leap_year_dates(self):
        # 2024-01-31 + 1 month clamps to the leap day; the final payment returns
        # to the 31st one year later.
        month_end = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0, start_date=date(2024, 1, 31),
        )
        self.assertEqual(month_end['apr_calculation']['first_payment_date'], '2024-02-29')
        self.assertEqual(month_end['apr_calculation']['last_payment_date'], '2025-01-31')
        self.assertAlmostEqual(
            month_end['effective_annual_cost_pct'],
            _reference_apr_pct(
                price=60000, n=12, monthly_fee=199.0, start=date(2024, 1, 31)
            ),
            delta=0.01,
        )

        leap_start = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0, start_date=date(2024, 2, 29),
        )
        self.assertEqual(leap_start['apr_calculation']['first_payment_date'], '2024-03-29')
        self.assertEqual(leap_start['apr_calculation']['last_payment_date'], '2025-02-28')
        self.assertAlmostEqual(
            leap_start['effective_annual_cost_pct'],
            _reference_apr_pct(
                price=60000, n=12, monthly_fee=199.0, start=date(2024, 2, 29)
            ),
            delta=0.01,
        )

        # The same loan started on 1 January must be within a few basis points.
        january = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0, start_date=date(2024, 1, 1),
        )
        self.assertLess(
            abs(january['effective_annual_cost_pct'] - month_end['effective_annual_cost_pct']),
            0.1,
        )

    def test_10_invalid_amounts_and_durations_are_safe(self):
        nan_result = self._sim(
            price=float('nan'), tenure_months=float('inf'),
            down_payment=float('inf'), nominal_annual_interest_rate_pct=float('nan'),
            monthly_processing_or_conv_fee=float('-inf'),
            upfront_processing_fee=float('nan'), gst_rate_pct=float('inf'),
            user_monthly_discretionary_buffer=float('nan'),
        )
        self.assertFalse(_walk_non_finite(nan_result))
        self.assertEqual(nan_result['apr_calculation']['status'], 'NOT_APPLICABLE')

        huge_tenure = self._sim(price=10000, tenure_months=10 ** 9)
        self.assertEqual(huge_tenure['tenure_months'], 600)
        self.assertIn('TENURE_CLAMPED_TO_600', huge_tenure['input_warnings'])
        self.assertFalse(_walk_non_finite(huge_tenure))

        zero_tenure = self._sim(price=10000, tenure_months=0)
        self.assertEqual(zero_tenure['tenure_months'], 1)
        self.assertIn('TENURE_CLAMPED_TO_1', zero_tenure['input_warnings'])

        negative = self._sim(
            price=-1000, tenure_months=-5, down_payment=-500,
            nominal_annual_interest_rate_pct=-10, monthly_processing_or_conv_fee=-50,
        )
        self.assertEqual(negative['price'], 0.0)
        self.assertEqual(negative['apr_calculation']['status'], 'NOT_APPLICABLE')
        self.assertFalse(_walk_non_finite(negative))

    def test_11_impossible_cash_flows_return_unavailable(self):
        # Upfront fee (with GST) exceeds the principal: nothing is disbursed.
        result = self._sim(
            price=1000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=0.0, upfront_processing_fee=2000.0,
            gst_rate_pct=18.0,
        )
        self.assertFalse(result['is_effective_cost_available'])
        self.assertIsNone(result['effective_annual_cost_pct'])
        self.assertIsNone(result['effective_apr_pct'])
        self.assertIsNone(result['true_effective_apr_pct'])
        self.assertEqual(result['apr_calculation']['status'], 'UNAVAILABLE')
        self.assertEqual(result['apr_calculation']['reason'], 'NON_POSITIVE_NET_DISBURSEMENT')
        self.assertIn('could not be calculated', result['hidden_trap_disclosure'])
        self.assertFalse(_walk_non_finite(result))

        bad_schedule = self._sim(
            price=60000, tenure_months=12,
            start_date=date(2026, 1, 1), first_payment_date=date(2026, 1, 1),
        )
        self.assertEqual(bad_schedule['apr_calculation']['reason'], 'INVALID_PAYMENT_SCHEDULE')
        self.assertIsNone(bad_schedule['effective_annual_cost_pct'])

    def test_12_reference_60000_scenario_reproduces_audited_result(self):
        # Exact audited inputs: ₹60,000 over 12 months, ₹199/month, 18% GST.
        result = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0, gst_rate_pct=18.0,
            start_date=date(2026, 1, 1),
        )
        reference = _reference_apr_pct(price=60000, n=12, monthly_fee=199.0, gst_pct=18.0)
        self.assertAlmostEqual(result['effective_annual_cost_pct'], reference, delta=0.01)
        # The audited ~8.9% is reproduced by the complete inputs, independently.
        self.assertAlmostEqual(result['effective_annual_cost_pct'], 8.9, delta=0.1)
        self.assertAlmostEqual(reference, 8.94075, delta=0.001)

    def test_13_old_simplified_formula_is_not_used(self):
        old_60k = _old_simplified_fee_load(60000, 12, 199.0)
        old_65k = _old_simplified_fee_load(65000, 12, 199.0)
        self.assertEqual(old_60k, 4.7)
        self.assertEqual(old_65k, 4.34)

        new_60k = self._sim(
            price=60000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0, gst_rate_pct=18.0,
        )['effective_annual_cost_pct']
        new_65k = self._sim(
            price=65000, tenure_months=12, nominal_annual_interest_rate_pct=0.0,
            monthly_processing_or_conv_fee=199.0, gst_rate_pct=18.0,
        )['effective_annual_cost_pct']

        self.assertAlmostEqual(new_60k, 8.94, delta=0.01)
        self.assertAlmostEqual(new_65k, 8.24, delta=0.01)
        # The corrected cash-flow result is materially different from the old
        # nominal-rate-plus-fee-load approximation in both directions.
        self.assertGreater(abs(new_60k - old_60k), 4.0)
        self.assertGreater(abs(new_65k - old_65k), 3.5)


class EmiApiEffectiveCostTests(TestCase):
    """API contract: authoritative XIRR result, safe unavailable state, validation."""

    def setUp(self):
        self.client = APIClient()

    def _post(self, payload):
        return self.client.post(EMI_URL, payload, format='json')

    def test_api_returns_xirr_components_and_matches_reference(self):
        response = self._post({
            'item_name': 'Reference Phone',
            'price': 60000.0,
            'tenure_months': 12,
            'down_payment': 0.0,
            'nominal_apr': 0.0,
            'monthly_processing_fee': 199.0,
            'discretionary_buffer': 14000.0,
            'start_date': '2026-01-01',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['nominal_annual_interest_rate_pct'], 0.0)
        self.assertAlmostEqual(data['effective_annual_cost_pct'], 8.94, delta=0.01)
        self.assertAlmostEqual(
            data['effective_annual_cost_pct'],
            _reference_apr_pct(price=60000, n=12, monthly_fee=199.0),
            delta=0.01,
        )
        self.assertTrue(data['is_effective_cost_available'])
        self.assertEqual(data['apr_calculation']['status'], 'OK')
        self.assertEqual(data['apr_calculation']['method'], 'XIRR_ACTUAL_365')
        self.assertEqual(data['apr_calculation']['annualization_basis'], 'actual_days/365')
        self.assertEqual(data['apr_calculation']['annual_rate_pct'], 8.94)
        self.assertEqual(data['apr_calculation']['first_payment_date'], '2026-02-01')
        self.assertEqual(data['apr_calculation']['last_payment_date'], '2027-01-01')
        self.assertEqual(data['fee_assumptions']['recurring_fee_with_gst_per_month'], 234.82)
        self.assertEqual(data['fee_assumptions']['upfront_fee_with_gst'], 0.0)
        self.assertFalse(_walk_non_finite(data))

    def test_api_and_engine_return_the_same_value(self):
        payload = {
            'price': 85000.0, 'tenure_months': 12, 'down_payment': 5000.0,
            'nominal_apr': 10.5, 'monthly_processing_fee': 149.0,
            'discretionary_buffer': 18000.0, 'upfront_processing_fee': 500.0,
            'gst_rate_pct': 18.0, 'start_date': '2026-01-01',
        }
        data = self._post(payload).json()
        engine = AnalyticsEngine.simulate_emi_decision(
            item_name='x', price=85000.0, tenure_months=12, down_payment=5000.0,
            nominal_annual_interest_rate_pct=10.5,
            monthly_processing_or_conv_fee=149.0,
            user_monthly_discretionary_buffer=18000.0,
            upfront_processing_fee=500.0, gst_rate_pct=18.0,
            start_date=date(2026, 1, 1),
        )
        self.assertEqual(data['effective_annual_cost_pct'], engine['effective_annual_cost_pct'])

    def test_api_unavailable_apr_serializes_null_not_nan(self):
        response = self._post({
            'price': 1000.0, 'tenure_months': 12,
            'monthly_processing_fee': 0.0, 'upfront_processing_fee': 2000.0,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsNone(data['effective_annual_cost_pct'])
        self.assertIsNone(data['effective_apr_pct'])
        self.assertIsNone(data['true_effective_apr_pct'])
        self.assertFalse(data['is_effective_cost_available'])
        self.assertEqual(data['apr_calculation']['status'], 'UNAVAILABLE')
        self.assertEqual(data['apr_calculation']['reason'], 'NON_POSITIVE_NET_DISBURSEMENT')
        # Raw body must be valid JSON, never NaN/Infinity literals.
        self.assertNotIn('NaN', response.content.decode())
        self.assertNotIn('Infinity', response.content.decode())
        json.loads(response.content.decode())

    def test_api_zero_principal_is_not_applicable(self):
        response = self._post({
            'price': 50000.0, 'down_payment': 50000.0, 'tenure_months': 6,
            'monthly_processing_fee': 0.0,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsNone(data['effective_annual_cost_pct'])
        self.assertEqual(data['apr_calculation']['status'], 'NOT_APPLICABLE')
        self.assertEqual(data['apr_calculation']['reason'], 'NO_PRINCIPAL_FINANCED')

    def test_api_rejects_non_finite_numbers(self):
        for bad in ('nan', 'inf', '-inf'):
            response = self._post({'price': bad})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, msg=bad)

    def test_api_rejects_invalid_dates(self):
        response = self._post({'price': 60000, 'start_date': 'not-a-date'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self._post({'price': 60000, 'first_payment_date': '2026-13-40'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_api_preserves_legacy_response_keys(self):
        response = self._post({'price': 60000, 'tenure_months': 12})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        for key in (
            'item_name', 'price', 'principal', 'tenure_months', 'nominal_apr',
            'advertised_interest_rate_pct', 'monthly_emi', 'effective_monthly_outflow',
            'total_hidden_fees_and_gst', 'total_overall_cost', 'total_repayment',
            'true_effective_apr_pct', 'effective_apr_pct', 'cost_breakdown',
            'affordability_verdict', 'is_viable', 'verdict', 'hidden_trap_disclosure',
        ):
            self.assertIn(key, data, msg=key)


class EmiAprPersistenceTests(TestCase):
    """The stored APR must never misrepresent a calculation that did not run."""

    def setUp(self):
        self.client = APIClient()

    def _post(self, payload):
        return self.client.post(EMI_URL, payload, format='json')

    def _scenario(self, payload):
        response = self._post(payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        row = DecisionScenario.objects.filter(item_name=data['item_name']).order_by('-created_at').first()
        self.assertIsNotNone(row)
        return data, row

    def test_01_genuine_zero_apr_is_stored_as_zero(self):
        data, row = self._scenario({
            'item_name': 'Genuine Zero Loan',
            'price': 36000, 'tenure_months': 6,
            'nominal_apr': 0.0, 'monthly_processing_fee': 0.0,
            'upfront_processing_fee': 0.0, 'start_date': '2026-01-01',
        })
        self.assertEqual(data['effective_annual_cost_pct'], 0.0)
        self.assertEqual(data['apr_calculation']['status'], 'OK')
        # A genuine zero-cost loan is stored as 0.0 with status OK: never NULL.
        self.assertIsNotNone(row.true_effective_apr)
        self.assertEqual(row.true_effective_apr, 0.0)
        self.assertEqual(row.apr_status, 'OK')

    def test_02_unavailable_apr_is_stored_as_null_with_status(self):
        data, row = self._scenario({
            'item_name': 'Unavailable Loan',
            'price': 1000, 'tenure_months': 12,
            'nominal_apr': 0.0, 'monthly_processing_fee': 0.0,
            'upfront_processing_fee': 2000.0, 'gst_rate_pct': 18.0,
        })
        self.assertIsNone(data['effective_annual_cost_pct'])
        self.assertEqual(data['apr_calculation']['status'], 'UNAVAILABLE')
        # NULL means "no reliable value" - never a misleading 0.0.
        self.assertIsNone(row.true_effective_apr)
        self.assertEqual(row.apr_status, 'UNAVAILABLE')

    def test_03_not_applicable_apr_is_stored_as_null_with_status(self):
        data, row = self._scenario({
            'item_name': 'No Principal Loan',
            'price': 50000, 'down_payment': 50000, 'tenure_months': 6,
            'nominal_apr': 12.0, 'monthly_processing_fee': 0.0,
        })
        self.assertIsNone(data['effective_annual_cost_pct'])
        self.assertEqual(data['apr_calculation']['status'], 'NOT_APPLICABLE')
        self.assertIsNone(row.true_effective_apr)
        self.assertEqual(row.apr_status, 'NOT_APPLICABLE')

    def test_04_database_value_always_matches_the_api_value(self):
        scenarios = [
            ({'item_name': 'Sync Zero', 'price': 12000, 'tenure_months': 6,
              'nominal_apr': 0.0, 'monthly_processing_fee': 0.0}, 'OK'),
            ({'item_name': 'Sync Computed', 'price': 60000, 'tenure_months': 12,
              'nominal_apr': 12.0, 'monthly_processing_fee': 199.0}, 'OK'),
            ({'item_name': 'Sync Unavailable', 'price': 1000, 'tenure_months': 12,
              'upfront_processing_fee': 5000.0}, 'UNAVAILABLE'),
            ({'item_name': 'Sync NotApplicable', 'price': 40000,
              'down_payment': 40000, 'tenure_months': 6}, 'NOT_APPLICABLE'),
        ]
        for payload, expected_status in scenarios:
            data, row = self._scenario(payload)
            self.assertEqual(data['apr_calculation']['status'], expected_status)
            self.assertEqual(row.apr_status, expected_status)
            self.assertEqual(
                row.true_effective_apr,
                data['effective_annual_cost_pct'],
                msg=f'{payload["item_name"]}',
            )

    def test_05_legacy_rows_are_labelled_not_misrepresented(self):
        migration = importlib.import_module(
            'api.migrations.0004_decisionscenario_apr_status'
        )
        legacy_computed = DecisionScenario.objects.create(
            item_name='Legacy Computed', price=60000, tenure_months=12,
            monthly_outflow=5234.82, total_hidden_fees=2817.84,
            true_effective_apr=4.34, apr_status=None, verdict='legacy',
        )
        legacy_zero = DecisionScenario.objects.create(
            item_name='Legacy Zero', price=5000, tenure_months=12,
            monthly_outflow=416.67, total_hidden_fees=0,
            true_effective_apr=0.0, apr_status=None, verdict='legacy',
        )

        migration.backfill_legacy_apr_status(django_apps, None)

        legacy_computed.refresh_from_db()
        legacy_zero.refresh_from_db()
        # A value computed by the superseded formula is kept but labelled.
        self.assertEqual(legacy_computed.apr_status, 'LEGACY_SUPERSEDED')
        self.assertEqual(legacy_computed.true_effective_apr, 4.34)
        # An ambiguous historic 0.0 is cleared, never presented as a 0% loan.
        self.assertEqual(legacy_zero.apr_status, 'LEGACY_AMBIGUOUS_ZERO')
        self.assertIsNone(legacy_zero.true_effective_apr)

    def test_06_no_pending_migrations(self):
        from django.core.management import call_command
        try:
            call_command('makemigrations', 'api', '--check', '--dry-run', verbosity=0)
        except SystemExit as exc:  # pragma: no cover - only on drift
            self.fail(f'Pending migrations detected (exit {exc}).')

    def test_07_model_field_is_nullable(self):
        field = DecisionScenario._meta.get_field('true_effective_apr')
        self.assertTrue(field.null)
        self.assertTrue(DecisionScenario._meta.get_field('apr_status').null)
        # The status column can carry every documented status value.
        self.assertGreaterEqual(
            DecisionScenario._meta.get_field('apr_status').max_length, 32
        )
