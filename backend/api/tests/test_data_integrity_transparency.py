"""
Regression tests for the pre-release data-integrity and transparency fixes.

Covered contracts:
1. Imported and persona datasets never cross-contaminate identity, evidence,
   refund allocation or the stress-test baseline.
2. Recurring-payment confidence is explicit: a single debit is a probable
   candidate, never a confirmed recurring commitment.
3. Health metrics reveal insufficient data and coverage limitations instead of
   presenting an unverified grade as an observed result.
4. Consent-gated analysis and correction endpoints cannot be called after
   withdrawal, and string booleans such as "false" are not treated as true.

All fixtures are synthetic.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction
from api.insights import (
    classify_credit,
    compute_dataset_financial_metrics,
    compute_imported_session_overview,
    detect_subscriptions,
    generate_evidence_briefing,
    monthly_budget,
    resolve_credit_classification,
)
from analytics.stress_test import run_commitment_stress_test


STRESS_URL = "/api/v1/analytics/commitment-stress-test/"
EXPLAIN_URL = "/api/v1/analytics/commitment-stress-test/explain/"
CORRECTION_URL = "/api/v1/insights/correct-transaction/"
BRIEFING_URL = "/api/v1/insights/evidence-briefing/"
SUBSCRIPTIONS_URL = "/api/v1/insights/subscriptions/"
WITHDRAW_URL = "/api/v1/privacy/consent/withdraw/"
BUDGET_URL = "/api/v1/insights/monthly-budget/"
OVERVIEW_URL = "/api/v1/insights/imported-overview/"


class DataIntegrityTestBase(TestCase):
    def setUp(self):
        super().setUp()
        self.session_id = f"integrity_{uuid.uuid4().hex[:10]}"
        self.session, self.token = SecureSession.issue_session(self.session_id)
        self.client = APIClient()
        self.consent = self._grant_consent()

    def _grant_consent(self):
        return ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version="v1.0-integrity",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

    def add_tx(
        self,
        day,
        amount,
        tx_type,
        merchant,
        *,
        source_type=Transaction.SOURCE_IMPORT,
        category="Uncategorized",
        is_recurring=False,
        session_id=None,
    ):
        return Transaction.objects.create(
            session_id=session_id or self.session_id,
            transaction_date=day,
            amount=Decimal(str(amount)),
            transaction_type=tx_type,
            normalized_merchant=merchant,
            category=category,
            source_type=source_type,
            is_recurring=is_recurring,
        )

    def post(self, url, payload=None, token=None):
        return self.client.post(
            url,
            payload or {},
            format="json",
            HTTP_X_SESSION_TOKEN=token or self.token,
        )


class DatasetSourceSeparationTests(DataIntegrityTestBase):
    def test_evidence_briefing_uses_only_the_requested_source(self):
        # Distinct months make the selected dataset observable through the
        # reporting period, independent of which insights happen to fire.
        self.add_tx(
            date(2026, 9, 1), "45000", "CREDIT", "SALARY CREDIT ACME CORP"
        )
        self.add_tx(
            date(2026, 9, 5), "12000", "DEBIT", "ACME RENT PAYMENT",
            category="Bills",
        )
        self.add_tx(
            date(2026, 6, 1),
            "75000",
            "CREDIT",
            "SALARY CREDIT DEMO EMPLOYER",
            source_type=Transaction.SOURCE_PERSONA,
        )
        self.add_tx(
            date(2026, 6, 4),
            "8000",
            "DEBIT",
            "DEMO LANDLORD RENT",
            source_type=Transaction.SOURCE_PERSONA,
            category="Bills",
        )

        imported_briefing = generate_evidence_briefing(self.session_id, include_persona=False)
        persona_briefing = generate_evidence_briefing(self.session_id, include_persona=True)

        self.assertEqual(imported_briefing["data_source"], "IMPORTED_STATEMENT")
        self.assertEqual(persona_briefing["data_source"], "PERSONA")

        imported_period = imported_briefing["reporting_period"]
        persona_period = persona_briefing["reporting_period"]
        self.assertEqual((imported_period["year"], imported_period["month"]), (2026, 9))
        self.assertEqual((persona_period["year"], persona_period["month"]), (2026, 6))

        imported_text = json.dumps(imported_briefing).upper()
        persona_text = json.dumps(persona_briefing).upper()
        self.assertNotIn("DEMO LANDLORD", imported_text)
        self.assertNotIn("DEMO EMPLOYER", imported_text)
        self.assertNotIn("ACME RENT", persona_text)
        self.assertNotIn("ACME CORP", persona_text)

    def test_briefing_endpoint_parses_string_false_as_imported(self):
        self.add_tx(date(2026, 10, 1), "45000", "CREDIT", "SALARY CREDIT ACME CORP")
        self.add_tx(
            date(2026, 10, 1),
            "75000",
            "CREDIT",
            "SALARY CREDIT DEMO EMPLOYER",
            source_type=Transaction.SOURCE_PERSONA,
        )

        response = self.post(
            BRIEFING_URL,
            {"session_id": self.session_id, "include_persona": "false"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data_source"], "IMPORTED_STATEMENT")

        persona_response = self.post(
            BRIEFING_URL,
            {"session_id": self.session_id, "include_persona": "true"},
        )
        self.assertEqual(persona_response.status_code, status.HTTP_200_OK)
        self.assertEqual(persona_response.json()["data_source"], "PERSONA")

    def test_prior_refund_replay_is_source_scoped(self):
        # A persona purchase that a current persona refund should match.
        self.add_tx(
            date(2026, 9, 10),
            "1000",
            "DEBIT",
            "AMAZON",
            source_type=Transaction.SOURCE_PERSONA,
            category="Shopping",
        )
        # An imported prior refund must not consume the persona debit capacity.
        self.add_tx(
            date(2026, 9, 20),
            "1000",
            "CREDIT",
            "AMAZON REFUND",
            source_type=Transaction.SOURCE_IMPORT,
            category="Refund",
        )
        self.add_tx(
            date(2026, 10, 5),
            "1000",
            "CREDIT",
            "AMAZON REFUND",
            source_type=Transaction.SOURCE_PERSONA,
            category="Refund",
        )

        budget = monthly_budget(self.session_id, 2026, 10, include_persona=True)
        refund = next(
            row for row in budget["refund_details"]
            if row["date"] == "2026-10-05"
        )

        # The persona refund keeps the full persona debit capacity: the imported
        # prior refund was not replayed against the persona ledger.
        self.assertEqual(Decimal(refund["matched_amount"]), Decimal("1000.00"))
        self.assertEqual(Decimal(refund["unmatched_amount"]), Decimal("0.00"))
        self.assertTrue(refund["matched_purchases"])

    def test_stress_test_never_borrows_a_persona_snapshot_in_imported_mode(self):
        # A snapshot created by persona selection must not become the imported
        # statement's liquid balance.
        FinancialSnapshot.objects.create(
            session_id=self.session_id,
            liquid_balance=Decimal("120000.00"),
            monthly_income=Decimal("80000.00"),
            monthly_expenses=Decimal("40000.00"),
            fixed_commitments=Decimal("25000.00"),
        )
        self.add_tx(date(2026, 10, 1), "50000", "CREDIT", "SALARY CREDIT ACME CORP")
        self.add_tx(
            date(2026, 10, 5),
            "20000",
            "DEBIT",
            "APARTMENT RENT LANDLORD",
            category="Bills",
            is_recurring=True,
        )

        result = run_commitment_stress_test(
            session_id=self.session_id,
            price=10000.0,
            include_persona=False,
            as_of_date=date(2026, 10, 15),
        )

        self.assertEqual(result["dataset_source"], "IMPORTED_STATEMENT")
        self.assertEqual(result["baseline"]["current_liquid_balance"], 0.0)
        self.assertFalse(result["baseline"]["balance_verified"])
        self.assertEqual(result["overall_verdict"], "INSUFFICIENT DATA")
        self.assertTrue(
            any("balance" in reason.lower() for reason in result["insufficient_reasons"])
        )

    def test_stress_test_evidence_is_scoped_to_the_selected_source(self):
        persona_credit = self.add_tx(
            date(2026, 10, 1),
            "75000",
            "CREDIT",
            "SALARY CREDIT DEMO EMPLOYER",
            source_type=Transaction.SOURCE_PERSONA,
        )
        import_credit = self.add_tx(
            date(2026, 10, 1), "45000", "CREDIT", "SALARY CREDIT ACME CORP"
        )

        imported_result = run_commitment_stress_test(
            session_id=self.session_id,
            price=10000.0,
            custom_liquid_balance=120000.0,
            include_persona=False,
            as_of_date=date(2026, 10, 15),
        )
        persona_result = run_commitment_stress_test(
            session_id=self.session_id,
            price=10000.0,
            custom_liquid_balance=120000.0,
            include_persona=True,
            as_of_date=date(2026, 10, 15),
        )

        self.assertEqual(imported_result["dataset_source"], "IMPORTED_STATEMENT")
        self.assertEqual(persona_result["dataset_source"], "PERSONA_SCENARIO")
        self.assertIn(
            str(import_credit.id),
            imported_result["evidence_ledger"]["all_cited_tx_ids"],
        )
        self.assertNotIn(
            str(persona_credit.id),
            imported_result["evidence_ledger"]["all_cited_tx_ids"],
        )
        self.assertIn(
            str(persona_credit.id),
            persona_result["evidence_ledger"]["all_cited_tx_ids"],
        )
        self.assertNotIn(
            str(import_credit.id),
            persona_result["evidence_ledger"]["all_cited_tx_ids"],
        )

    def test_stress_test_endpoint_parses_string_false_as_imported(self):
        self.add_tx(date(2026, 10, 1), "45000", "CREDIT", "SALARY CREDIT ACME CORP")
        response = self.post(
            STRESS_URL,
            {
                "price": 10000,
                "custom_liquid_balance": 120000,
                "include_persona": "false",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["dataset_source"], "IMPORTED_STATEMENT")


class RecurringConfidenceTests(DataIntegrityTestBase):
    def test_single_debit_is_a_probable_candidate_not_a_confirmed_commitment(self):
        self.add_tx(
            date(2026, 10, 5),
            "649",
            "DEBIT",
            "SPOTIFY SUBSCRIPTION",
            category="Subscriptions",
            is_recurring=True,
        )

        rows = detect_subscriptions(self.session_id, include_persona=False)
        row = next(r for r in rows if "SPOTIFY" in r["merchant"].upper())

        self.assertEqual(row["confidence"], "PROBABLE")
        self.assertFalse(row["is_financial_commitment"])
        self.assertFalse(row["is_potential_leakage"])
        self.assertEqual(row["occurrence_count"], 1)

    def test_repeated_consistent_debits_are_confirmed_commitments(self):
        for month in (1, 2, 3):
            self.add_tx(
                date(2026, month, 5),
                "649",
                "DEBIT",
                "NETFLIX SUBSCRIPTION",
                category="Subscriptions",
            )

        rows = detect_subscriptions(self.session_id, include_persona=False)
        row = next(r for r in rows if "NETFLIX" in r["merchant"].upper())

        self.assertEqual(row["confidence"], "CONFIRMED")
        self.assertTrue(row["is_financial_commitment"])
        self.assertGreaterEqual(row["occurrence_count"], 3)

    def test_subscription_api_separates_confirmed_and_probable_amounts(self):
        for month in (1, 2, 3):
            self.add_tx(
                date(2026, month, 5),
                "649",
                "DEBIT",
                "NETFLIX SUBSCRIPTION",
                category="Subscriptions",
            )
        self.add_tx(
            date(2026, 10, 7),
            "199",
            "DEBIT",
            "SPOTIFY SUBSCRIPTION",
            category="Subscriptions",
            is_recurring=True,
        )

        response = self.post(
            SUBSCRIPTIONS_URL,
            {"session_id": self.session_id, "include_persona": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()

        self.assertGreater(Decimal(body["confirmed_monthly_commitment"]), Decimal("0"))
        self.assertGreater(Decimal(body["probable_monthly_commitment"]), Decimal("0"))
        self.assertEqual(body["count"], 2)

        by_merchant = {row["merchant"].upper(): row for row in body["subscriptions"]}
        netflix = next(v for k, v in by_merchant.items() if "NETFLIX" in k)
        spotify = next(v for k, v in by_merchant.items() if "SPOTIFY" in k)
        self.assertEqual(netflix["confidence"], "CONFIRMED")
        self.assertTrue(netflix["is_financial_commitment"])
        self.assertEqual(spotify["confidence"], "PROBABLE")
        self.assertFalse(spotify["is_financial_commitment"])
        self.assertFalse(spotify["is_potential_leakage"])


class HealthTransparencyTests(DataIntegrityTestBase):
    def test_imported_overview_reports_estimated_health_and_limits(self):
        self.add_tx(date(2026, 10, 1), "50000", "CREDIT", "SALARY CREDIT ACME CORP")
        self.add_tx(
            date(2026, 10, 5),
            "20000",
            "DEBIT",
            "APARTMENT RENT LANDLORD",
            category="Bills",
            is_recurring=True,
        )

        overview = compute_imported_session_overview(self.session_id)
        health = overview["health_metrics"]

        self.assertFalse(health["liquid_balance_known"])
        self.assertEqual(health["health_status"], "ESTIMATED")
        self.assertEqual(
            health["metric_basis"]["health_score"], "ESTIMATED_BALANCE_UNAVAILABLE"
        )
        self.assertEqual(
            health["metric_basis"]["runway"], "WITHHELD_BALANCE_UNAVAILABLE"
        )
        self.assertTrue(health["grade"].startswith("ESTIMATED"))
        self.assertIn("grade_raw", health)
        self.assertNotIn(health["grade"], {"A (Resilient)", "B (Stable)"})

        for limitation in (
            "LIQUID_BALANCE_UNAVAILABLE",
            "EMERGENCY_RUNWAY_WITHHELD",
            "SAFE_TO_SPEND_UNAVAILABLE",
            "HEALTH_SCORE_ESTIMATED",
        ):
            self.assertIn(limitation, overview["coverage_limitations"])

        self.assertEqual(overview["safe_to_spend"]["status"], "INSUFFICIENT_DATA")
        self.assertIsNone(overview["safe_to_spend"]["safe_to_spend_daily"])

    def test_dataset_metrics_withhold_health_and_runway_without_balance(self):
        self.add_tx(date(2026, 10, 1), "50000", "CREDIT", "SALARY CREDIT ACME CORP")

        metrics = compute_dataset_financial_metrics(self.session_id, include_persona=False)

        self.assertIsNone(metrics["health_score"])
        self.assertIsNone(metrics["health_grade"])
        self.assertEqual(metrics["health_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(metrics["emergency_runway_months"])
        self.assertEqual(metrics["metric_basis"]["runway"], "WITHHELD")
        self.assertIn(
            "LIQUID_BALANCE_UNAVAILABLE", metrics["coverage_limitations"]
        )

    def test_persona_metrics_are_labelled_as_scenario_estimates(self):
        FinancialSnapshot.objects.create(
            session_id=self.session_id,
            liquid_balance=Decimal("120000.00"),
            monthly_income=Decimal("80000.00"),
            monthly_expenses=Decimal("40000.00"),
            fixed_commitments=Decimal("25000.00"),
        )
        self.add_tx(
            date(2026, 10, 1),
            "80000",
            "CREDIT",
            "SALARY CREDIT DEMO EMPLOYER",
            source_type=Transaction.SOURCE_PERSONA,
        )

        metrics = compute_dataset_financial_metrics(self.session_id, include_persona=True)

        self.assertEqual(metrics["health_status"], "ESTIMATED")
        self.assertEqual(
            metrics["metric_basis"]["health_score"], "PERSONA_SCENARIO_ESTIMATE"
        )
        self.assertIn("PERSONA_SCENARIO_ESTIMATE", metrics["coverage_limitations"])


class NovemberCreditClassificationRegressionTests(DataIntegrityTestBase):
    """Regression coverage for the November 2026 imported statement.

    The two credits are real corporate bank-rail receipts but carry no payroll
    keyword. They must not collapse to ₹0 operating income, and they must not be
    presented as confirmed salary either.
    """

    def _add_november_statement(self):
        rows = [
            (date(2026, 11, 1), "55000", "CREDIT", "Ach Credit Northstar Services", "unclassified_credit"),
            (date(2026, 11, 2), "16000", "DEBIT", "Rent", "rent_housing"),
            (date(2026, 11, 3), "1599", "DEBIT", "Adobe Creative Cloud", "subscriptions"),
            (date(2026, 11, 4), "2350", "DEBIT", "City Mart Grocery", "food"),
            (date(2026, 11, 5), "4100", "DEBIT", "Education Loan Emi", "emi"),
            (date(2026, 11, 7), "620", "DEBIT", "Zomato", "food"),
            (date(2026, 11, 9), "1200", "DEBIT", "Aws Cloud Compute Ec2", "subscriptions"),
            (date(2026, 11, 11), "12500", "CREDIT", "Neft Credit Orbit Design", "unclassified_credit"),
            (date(2026, 11, 13), "899", "DEBIT", "Figma Professional", "subscriptions"),
            (date(2026, 11, 16), "1000", "DEBIT", "Transfer", "other"),
            (date(2026, 11, 18), "410", "DEBIT", "Swiggy", "food"),
        ]
        for day, amount, tx_type, merchant, category in rows:
            self.add_tx(day, amount, tx_type, merchant, category=category)

    def test_november_probable_business_credits_feed_operating_surplus(self):
        self._add_november_statement()

        budget = monthly_budget(self.session_id, 2026, 11, include_persona=False)

        self.assertEqual(Decimal(budget["total_credits"]), Decimal("67500.00"))
        self.assertEqual(Decimal(budget["earned_income"]), Decimal("0.00"))
        self.assertEqual(Decimal(budget["business_income"]), Decimal("67500.00"))
        self.assertEqual(Decimal(budget["confirmed_operating_income"]), Decimal("0.00"))
        self.assertEqual(Decimal(budget["operating_income"]), Decimal("67500.00"))
        self.assertEqual(budget["operating_income_status"], "PROBABLE")
        self.assertTrue(budget["operating_income_includes_probable"])

        self.assertEqual(Decimal(budget["net_living_expenses"]), Decimal("28178.00"))
        self.assertEqual(Decimal(budget["operating_surplus"]), Decimal("39322.00"))

        self.assertEqual(Decimal(budget["unclassified_inflows"]), Decimal("0.00"))
        self.assertEqual(Decimal(budget["credit_breakdown"]["business_income"]), Decimal("67500.00"))
        self.assertEqual(Decimal(budget["credit_breakdown"]["unclassified"]), Decimal("0.00"))

        classification = budget["income_classification"]
        self.assertEqual(classification["status"], "PROBABLE")
        self.assertEqual(classification["probable_income_transaction_count"], 2)
        self.assertTrue(classification["requires_review"])
        self.assertIn("probable business", classification["note"].lower())

    def test_november_credit_breakdown_still_reconciles_to_total_credits(self):
        self._add_november_statement()
        breakdown = monthly_budget(self.session_id, 2026, 11, include_persona=False)["credit_breakdown"]

        exclusive_buckets = (
            "earned_income", "business_income", "investment_yield",
            "capital_liquidation", "investment_transfers", "refunds",
            "transfers", "reimbursements", "unclassified",
        )
        reconciled = sum((Decimal(breakdown[key]) for key in exclusive_buckets), Decimal("0"))
        self.assertEqual(reconciled, Decimal("67500.00"))
        # The compatibility alias must not be double-counted in reconciliation.
        self.assertEqual(
            Decimal(breakdown["investment_income"]),
            Decimal(breakdown["investment_yield"]),
        )

    def test_bank_rail_business_credits_are_probable_not_confirmed_salary(self):
        northstar = classify_credit("Ach Credit Northstar Services")
        orbit = classify_credit("Neft Credit Orbit Design")

        for info in (northstar, orbit):
            self.assertEqual(info["credit_type"], "business_income")
            self.assertTrue(info["is_operating_income"])
            self.assertEqual(info["classification_status"], "PROBABLE")
            self.assertTrue(info["requires_review"])

        salary = classify_credit("ACH CREDIT NORTHSTAR SALARY")
        payroll = classify_credit("NEFT CREDIT APEX PAYROLL")
        self.assertEqual(salary["credit_type"], "earned_income")
        self.assertEqual(payroll["credit_type"], "earned_income")
        self.assertFalse(salary["requires_review"])

    def test_ambiguous_or_peer_credits_remain_unclassified(self):
        cases = (
            "NEFT CREDIT RAHUL SHARMA",       # bank rail, personal counterparty
            "ACH CREDIT GLOBAL TECH",          # bank rail, no professional signal
            "UPI/NORTHSTAR SERVICES/9876543210",  # professional name, no bank rail
        )
        for narration in cases:
            info = classify_credit(narration)
            self.assertEqual(info["credit_type"], "unclassified", msg=narration)
            self.assertFalse(info["is_operating_income"], msg=narration)
            self.assertTrue(info["requires_review"], msg=narration)

    def test_transfers_and_refunds_are_not_probable_business_income(self):
        self.add_tx(
            date(2026, 11, 1), "55000", "CREDIT", "NEFT CREDIT NORTHSTAR SERVICES"
        )
        self.add_tx(
            date(2026, 11, 2), "10000", "CREDIT", "NEFT CREDIT SELF TRANSFER"
        )
        self.add_tx(
            date(2026, 11, 3), "2000", "CREDIT", "NEFT CREDIT AMAZON REFUND"
        )
        self.add_tx(
            date(2026, 11, 4), "40000", "CREDIT", "SALARY CREDIT ACME CORP"
        )

        budget = monthly_budget(self.session_id, 2026, 11, include_persona=False)

        self.assertEqual(Decimal(budget["business_income"]), Decimal("55000.00"))
        self.assertEqual(Decimal(budget["earned_income"]), Decimal("40000.00"))
        self.assertEqual(Decimal(budget["credit_breakdown"]["transfers"]), Decimal("10000.00"))
        self.assertEqual(Decimal(budget["credit_breakdown"]["refunds"]), Decimal("2000.00"))
        self.assertEqual(Decimal(budget["operating_income"]), Decimal("95000.00"))
        self.assertEqual(budget["operating_income_status"], "PROBABLE")

    def test_unclassified_only_statement_reports_uncertain_surplus(self):
        self.add_tx(
            date(2026, 11, 5), "1480", "CREDIT", "UPI/FriendPayer/split_dinner_123"
        )
        self.add_tx(
            date(2026, 11, 6), "5000", "DEBIT", "Apartment Rent Landlord",
            category="Bills",
        )

        budget = monthly_budget(self.session_id, 2026, 11, include_persona=False)

        self.assertEqual(Decimal(budget["operating_income"]), Decimal("0.00"))
        self.assertEqual(budget["operating_income_status"], "UNCLASSIFIED")
        self.assertEqual(Decimal(budget["unclassified_inflows"]), Decimal("1480.00"))
        self.assertTrue(budget["income_classification"]["requires_review"])
        self.assertIn("not an observed result", budget["income_classification"]["note"])
        self.assertEqual(Decimal(budget["operating_surplus"]), Decimal("-5000.00"))

    def test_importer_placeholder_does_not_override_narration(self):
        placeholder = self.add_tx(
            date(2026, 11, 11), "12500", "CREDIT", "Neft Credit Orbit Design",
            category="Unclassified Credit",
        )
        info = resolve_credit_classification(placeholder)

        self.assertEqual(info["credit_type"], "business_income")
        self.assertEqual(info["category"], "business_income")
        self.assertEqual(info["category_source"], "NARRATION")

        confirmed = self.add_tx(
            date(2026, 11, 12), "40000", "CREDIT", "NEFT CRED ORBIT DESIGN",
            category="Freelance Income",
        )
        confirmed_info = resolve_credit_classification(confirmed)
        self.assertEqual(confirmed_info["credit_type"], "earned_income")
        self.assertEqual(confirmed_info["category_source"], "STORED_CATEGORY")
        self.assertFalse(confirmed_info["requires_review"])

    def test_stress_test_withholds_probable_income_from_survival_math(self):
        self.add_tx(
            date(2026, 11, 1), "55000", "CREDIT", "Ach Credit Northstar Services",
            category="unclassified_credit",
        )
        self.add_tx(
            date(2026, 11, 11), "12500", "CREDIT", "Neft Credit Orbit Design",
            category="unclassified_credit",
        )
        self.add_tx(
            date(2026, 11, 2), "16000", "DEBIT", "Rent", category="rent_housing",
        )

        result = run_commitment_stress_test(
            session_id=self.session_id,
            price=10000.0,
            custom_liquid_balance=120000.0,
            include_persona=False,
            as_of_date=date(2026, 11, 18),
        )

        self.assertEqual(result["baseline"]["predictable_monthly_income"], 0.0)
        self.assertEqual(result["baseline"]["probable_income_withheld"], 67500.0)
        self.assertEqual(result["overall_verdict"], "INSUFFICIENT DATA")

    def test_capital_movements_and_investment_liquidation_are_not_earned_income(self):
        # Point 7: Capital movements are not earned income
        self.add_tx(date(2026, 11, 2), "50000", "CREDIT", "MUTUAL FUND REDEMPTION PAYOUT")
        self.add_tx(date(2026, 11, 3), "25000", "CREDIT", "ZERODHA BROKER WITHDRAWAL")
        self.add_tx(date(2026, 11, 4), "1500", "CREDIT", "TCS DIVIDEND CREDITED")

        budget = monthly_budget(self.session_id, 2026, 11, include_persona=False)

        self.assertEqual(Decimal(budget["earned_income"]), Decimal("0.00"))
        self.assertEqual(Decimal(budget["business_income"]), Decimal("0.00"))
        self.assertEqual(Decimal(budget["credit_breakdown"]["capital_liquidation"]), Decimal("50000.00"))
        self.assertEqual(Decimal(budget["credit_breakdown"]["investment_transfers"]), Decimal("25000.00"))
        self.assertEqual(Decimal(budget["credit_breakdown"]["investment_yield"]), Decimal("1500.00"))
        # Only investment yield is passive operating income; capital liquidation & transfers are excluded
        self.assertEqual(Decimal(budget["confirmed_operating_income"]), Decimal("1500.00"))
        self.assertEqual(Decimal(budget["operating_income"]), Decimal("1500.00"))
        self.assertEqual(budget["operating_income_status"], "CONFIRMED")
        self.assertFalse(budget["operating_income_includes_probable"])

    def test_monthly_budget_isolates_imported_and_persona_sources(self):
        # Point 11: Imported and persona sources remain isolated
        self._add_november_statement()
        self.add_tx(
            date(2026, 11, 1), "99000", "CREDIT", "SALARY CREDIT DEMO PERSONA",
            source_type=Transaction.SOURCE_PERSONA,
        )
        self.add_tx(
            date(2026, 11, 5), "30000", "DEBIT", "PERSONA LUXURY EXPENSE",
            source_type=Transaction.SOURCE_PERSONA,
        )

        imported_budget = monthly_budget(self.session_id, 2026, 11, include_persona=False)
        persona_budget = monthly_budget(self.session_id, 2026, 11, include_persona=True)

        self.assertEqual(Decimal(imported_budget["total_credits"]), Decimal("67500.00"))
        self.assertEqual(Decimal(imported_budget["operating_income"]), Decimal("67500.00"))
        self.assertEqual(imported_budget["operating_income_status"], "PROBABLE")

        self.assertEqual(Decimal(persona_budget["total_credits"]), Decimal("99000.00"))
        self.assertEqual(Decimal(persona_budget["earned_income"]), Decimal("99000.00"))
        self.assertEqual(Decimal(persona_budget["operating_income"]), Decimal("99000.00"))
        self.assertEqual(persona_budget["operating_income_status"], "CONFIRMED")

    def test_sync_intelligence_does_not_duplicate_transactions(self):
        # Point 12: Repeated SYNC INTELLIGENCE does not duplicate transactions
        self._add_november_statement()
        initial_tx_count = Transaction.objects.filter(session_id=self.session_id).count()
        self.assertEqual(initial_tx_count, 11)

        for _ in range(3):
            resp = self.post(BUDGET_URL, {"include_persona": False})
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            data = resp.json()
            self.assertEqual(data["year"], 2026)
            self.assertEqual(data["month"], 11)
            self.assertEqual(Decimal(data["total_credits"]), Decimal("67500.00"))

        final_tx_count = Transaction.objects.filter(session_id=self.session_id).count()
        self.assertEqual(final_tx_count, initial_tx_count)

    def test_november_statement_partial_month_reporting_preserved(self):
        # Point 13: Partial-month reporting remains unchanged
        self._add_november_statement()
        budget = monthly_budget(self.session_id, 2026, 11, include_persona=False)

        coverage = budget["data_coverage"]
        self.assertTrue(coverage["is_partial_month_likely"])
        self.assertFalse(coverage["extrapolated"])
        self.assertEqual(coverage["days_covered"], 18)
        self.assertEqual(coverage["start_date"], "2026-11-01")
        self.assertEqual(coverage["end_date"], "2026-11-18")
        self.assertEqual(coverage["transaction_count"], 11)
        self.assertEqual(budget["statement_period"]["label"], "November 2026")


class ConsentGateRegressionTests(DataIntegrityTestBase):
    def test_new_analysis_endpoints_require_consent(self):
        no_consent_id = f"no_consent_{uuid.uuid4().hex[:8]}"
        _session, token = SecureSession.issue_session(no_consent_id)
        tx = self.add_tx(
            date(2026, 10, 1),
            "45000",
            "CREDIT",
            "SALARY CREDIT ACME CORP",
            session_id=no_consent_id,
        )

        stress = self.post(STRESS_URL, {"price": 10000}, token=token)
        explain = self.post(
            EXPLAIN_URL,
            {"decision_packet": {"overall_verdict": "SAFE"}},
            token=token,
        )
        correction = self.post(
            CORRECTION_URL,
            {"transaction_id": str(tx.id), "new_category": "Salary"},
            token=token,
        )

        self.assertEqual(stress.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(stress.json()["code"], "CONSENT_REQUIRED")
        self.assertEqual(explain.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(explain.json()["code"], "CONSENT_REQUIRED")
        self.assertEqual(correction.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(correction.json()["code"], "CONSENT_REQUIRED")

        tx.refresh_from_db()
        self.assertEqual(tx.category, "Uncategorized")

    def test_withdrawn_consent_blocks_stress_test_and_correction(self):
        tx = self.add_tx(
            date(2026, 10, 1), "45000", "CREDIT", "SALARY CREDIT ACME CORP"
        )
        withdraw = self.post(WITHDRAW_URL, {"session_id": self.session_id})
        self.assertEqual(withdraw.status_code, status.HTTP_200_OK)

        stress = self.post(STRESS_URL, {"price": 10000})
        correction = self.post(
            CORRECTION_URL,
            {"transaction_id": str(tx.id), "new_category": "Salary"},
        )

        self.assertEqual(stress.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(correction.status_code, status.HTTP_403_FORBIDDEN)
        tx.refresh_from_db()
        self.assertEqual(tx.category, "Uncategorized")
