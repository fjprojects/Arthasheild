"""
Regression tests for Mimiq Usability Improvements:
1. Single-debit recurring classification (not confirmed or overdue).
2. Elimination of unsupported "OVERDUE" claims (replaced with "CYCLE_ELAPSED").
3. Category consistency and monthly budget category drilldown items.
4. Transaction category correction by DB UUID and synthetic persona ID.
"""

from datetime import date
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from api.models import SecureSession, Transaction, FinancialSnapshot
from api.insights import (
    detect_subscriptions,
    monthly_budget,
    RECURRING_CONFIRMED,
    RECURRING_PROBABLE,
    RECURRING_WEAK,
)

INIT_URL = "/api/v1/auth/session/init/"
CONSENT_LOG_URL = "/api/v1/privacy/consent/"
CORRECT_URL = "/api/v1/insights/correct-transaction/"


class UsabilityImprovementsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        resp = self.client.post(INIT_URL)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.session_id = resp.data["session_id"]
        self.session_token = resp.data["session_token"]
        self.client.post(
            CONSENT_LOG_URL,
            {
                "consent_version": "v1.1-2026-11",
                "anonymized_processing_accepted": True,
                "no_credential_disclosure_acknowledged": True,
            },
            HTTP_X_SESSION_TOKEN=self.session_token,
            format="json",
        )

    def test_single_debit_never_confirmed_or_overdue(self):
        """
        Verify that a single debit cannot be classified as RECURRING_CONFIRMED
        and never receives an 'OVERDUE' status.
        """
        Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 8, 1),
            amount=Decimal("1500.00"),
            transaction_type="DEBIT",
            normalized_merchant="Cult Fit Bengaluru",
            category="Healthcare",
            is_recurring=True,
            source_type=Transaction.SOURCE_IMPORT,
        )

        result = detect_subscriptions(self.session_id, as_of_date=date(2026, 10, 1))
        self.assertEqual(len(result), 1)
        sub = result[0]

        # Must NOT be CONFIRMED
        self.assertNotEqual(sub["confidence"], RECURRING_CONFIRMED)
        self.assertEqual(sub["confidence"], RECURRING_PROBABLE)
        self.assertFalse(sub["is_financial_commitment"])
        self.assertFalse(sub["is_potential_leakage"])

        # Must NOT be OVERDUE
        self.assertNotEqual(sub["projection_status"], "OVERDUE")
        self.assertEqual(sub["projection_status"], "CYCLE_ELAPSED")
        self.assertTrue(any("1 debit occurrence" in e or "Single debit" in e for e in sub["evidence"]))

    def test_cadence_projection_never_claims_overdue(self):
        """
        Verify that multi-debit recurring streams whose expected date has passed
        receive 'CYCLE_ELAPSED' rather than unsupported 'OVERDUE'.
        """
        dates = [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
        for d in dates:
            Transaction.objects.create(
                session_id=self.session_id,
                transaction_date=d,
                amount=Decimal("649.00"),
                transaction_type="DEBIT",
                normalized_merchant="Netflix India",
                category="Entertainment",
                source_type=Transaction.SOURCE_IMPORT,
            )

        result = detect_subscriptions(self.session_id, as_of_date=date(2026, 10, 1))
        self.assertEqual(len(result), 1)
        sub = result[0]

        self.assertEqual(sub["confidence"], RECURRING_CONFIRMED)
        self.assertNotEqual(sub["projection_status"], "OVERDUE")
        self.assertEqual(sub["projection_status"], "CYCLE_ELAPSED")

    def test_monthly_budget_returns_category_transactions(self):
        """
        Verify that monthly_budget reconciles totals and returns category_transactions
        enabling full drilldown inspection of contributing items (including 'Other Discretionary').
        """
        tx1 = Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 5),
            amount=Decimal("450.00"),
            transaction_type="DEBIT",
            normalized_merchant="Swiggy Bangalore",
            category="Food & Dining",
            source_type=Transaction.SOURCE_IMPORT,
        )
        tx2 = Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 12),
            amount=Decimal("1200.00"),
            transaction_type="DEBIT",
            normalized_merchant="Airtel Broadband",
            category="Bills & Utilities",
            source_type=Transaction.SOURCE_IMPORT,
        )
        tx3 = Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 15),
            amount=Decimal("350.00"),
            transaction_type="DEBIT",
            normalized_merchant="Misc Corner Shop",
            category="Other Discretionary",
            source_type=Transaction.SOURCE_IMPORT,
        )

        budget = monthly_budget(self.session_id, year=2026, month=10)
        self.assertIn("category_transactions", budget)
        cat_txs = budget["category_transactions"]

        # Category display names must be consistent title-cased
        self.assertIn("Food & Dining", cat_txs)
        self.assertIn("Bills & Utilities", cat_txs)
        self.assertIn("Other Discretionary", cat_txs)

        # Swiggy in Food & Dining
        food_items = cat_txs["Food & Dining"]
        self.assertEqual(len(food_items), 1)
        self.assertEqual(food_items[0]["id"], str(tx1.id))
        self.assertEqual(float(food_items[0]["amount"]), 450.0)

        # Misc Corner Shop in Other Discretionary
        other_items = cat_txs["Other Discretionary"]
        self.assertEqual(len(other_items), 1)
        self.assertEqual(other_items[0]["id"], str(tx3.id))
        self.assertEqual(float(other_items[0]["amount"]), 350.0)

    def test_transaction_correction_by_db_uuid(self):
        """
        Verify that a live transaction can be corrected by database UUID.
        """
        tx = Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 10),
            amount=Decimal("2500.00"),
            transaction_type="DEBIT",
            normalized_merchant="Corner Mart",
            category="Other Discretionary",
        )

        payload = {
            "session_id": self.session_id,
            "transaction_id": str(tx.id),
            "new_category": "Shopping",
        }

        resp = self.client.post(
            CORRECT_URL,
            payload,
            format="json",
            HTTP_X_SESSION_TOKEN=self.session_token,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "CORRECTION_SAVED")
        self.assertEqual(resp.data["current_category"], "Shopping")

        tx.refresh_from_db()
        self.assertEqual(tx.category, "Shopping")
        self.assertIn("Category updated from Other Discretionary to Shopping", tx.risk_note)

    def test_transaction_correction_by_persona_fingerprint(self):
        """
        Verify that a persona transaction can be corrected using its synthetic ID (fingerprint).
        """
        tx = Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 15),
            amount=Decimal("1200.00"),
            transaction_type="DEBIT",
            normalized_merchant="Cloud Hosting Co",
            category="General",
            source_type=Transaction.SOURCE_PERSONA,
            fingerprint="tx_r05",
        )

        payload = {
            "session_id": self.session_id,
            "transaction_id": "tx_r05",
            "new_category": "Bills & Utilities",
        }

        resp = self.client.post(
            CORRECT_URL,
            payload,
            format="json",
            HTTP_X_SESSION_TOKEN=self.session_token,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "CORRECTION_SAVED")
        self.assertEqual(resp.data["current_category"], "Bills & Utilities")

        tx.refresh_from_db()
        self.assertEqual(tx.category, "Bills & Utilities")

    def test_transaction_correction_rejects_invalid_category(self):
        """
        Verify that invalid category strings are rejected with 400 Bad Request.
        """
        tx = Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 10),
            amount=Decimal("500.00"),
            transaction_type="DEBIT",
            normalized_merchant="Cafe",
            category="Food & Dining",
        )

        payload = {
            "session_id": self.session_id,
            "transaction_id": str(tx.id),
            "new_category": "Bogus Nonexistent Category",
        }

        resp = self.client.post(
            CORRECT_URL,
            payload,
            format="json",
            HTTP_X_SESSION_TOKEN=self.session_token,
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "INVALID_CATEGORY")

    def test_transaction_correction_cross_session_isolation(self):
        """
        Verify that a session cannot modify transactions belonging to another session.
        """
        other_resp = self.client.post(INIT_URL)
        other_session_id = other_resp.data["session_id"]
        tx = Transaction.objects.create(
            session_id=other_session_id,
            transaction_date=date(2026, 10, 10),
            amount=Decimal("500.00"),
            transaction_type="DEBIT",
            normalized_merchant="Cafe",
            category="Food & Dining",
        )

        payload = {
            "session_id": self.session_id,
            "transaction_id": str(tx.id),
            "new_category": "Shopping",
        }

        resp = self.client.post(
            CORRECT_URL,
            payload,
            format="json",
            HTTP_X_SESSION_TOKEN=self.session_token,
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_aws_vs_amazon_normalization(self):
        """
        Verify that AWS Cloud is disambiguated from Amazon Shopping in merchant normalization.
        """
        from api.insights import get_recurring_merchant_key, _canonical_display_label

        aws_key, _cluster, aws_label = get_recurring_merchant_key("AWS EMEA CLOUD SVCS BANGALORE")
        self.assertEqual(aws_key, "aws_cloud")
        self.assertEqual(aws_label, "AWS Cloud")
        self.assertEqual(_canonical_display_label(aws_key), "AWS Cloud")

        amzn_key, _amzn_cluster, amzn_label = get_recurring_merchant_key("AMAZON SELLER SERVICES RETAIL")
        self.assertIn("amazon", amzn_key)
        self.assertNotEqual(amzn_key, "aws_cloud")

    def test_unusual_spending_excludes_rent_and_emi(self):
        """
        Verify that fixed contractual commitments (rent, loans) are never flagged
        as discretionary spending anomalies, and that category cohorts are used.
        """
        from api.insights import detect_unusual_spending

        # Create normal coffee debits in Food & Dining
        for day in [2, 5, 8, 12]:
            Transaction.objects.create(
                session_id=self.session_id,
                transaction_date=date(2026, 10, day),
                amount=Decimal("200.00"),
                transaction_type="DEBIT",
                normalized_merchant="Third Wave Coffee",
                category="Food & Dining",
                source_type=Transaction.SOURCE_IMPORT,
            )

        # Create large Rent debit (contractual obligation)
        Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 1),
            amount=Decimal("25000.00"),
            transaction_type="DEBIT",
            normalized_merchant="HDFC RENT PAYMENT TO LANDLORD",
            category="Rent & Housing",
            is_recurring=True,
            source_type=Transaction.SOURCE_IMPORT,
        )

        # Create large EMI debit
        Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 5),
            amount=Decimal("7500.00"),
            transaction_type="DEBIT",
            normalized_merchant="AXIS BANK AUTO DEBIT EMI",
            category="EMI / Loan",
            is_recurring=True,
            source_type=Transaction.SOURCE_IMPORT,
        )

        # Create an actual discretionary spike in Food & Dining (e.g. ₹4000 vs ₹200 baseline)
        spike = Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 20),
            amount=Decimal("4000.00"),
            transaction_type="DEBIT",
            normalized_merchant="Fancy Banquet Dining",
            category="Food & Dining",
            source_type=Transaction.SOURCE_IMPORT,
        )

        anomalies = detect_unusual_spending(self.session_id, include_persona=False)
        flagged_merchants = [a["merchant"] for a in anomalies]
        flagged_ids = [a["id"] for a in anomalies]

        # Rent and EMI must NOT be flagged
        self.assertFalse(any("rent" in m.lower() for m in flagged_merchants))
        self.assertFalse(any("emi" in m.lower() for m in flagged_merchants))

        # The Food & Dining spike MUST be flagged with category cohort
        self.assertIn(str(spike.id), flagged_ids)
        spike_anomaly = next(a for a in anomalies if a["id"] == str(spike.id))
        self.assertEqual(spike_anomaly["cohort_type"], "CATEGORY_COHORT")
        self.assertEqual(spike_anomaly["cohort_label"], "Food & Dining")

    def test_credit_correction_updates_operating_income(self):
        """
        Verify that correcting an Unclassified Credit to Freelance Income
        updates verified operating income in compute_dataset_financial_metrics.
        """
        from api.insights import compute_dataset_financial_metrics

        tx = Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=date(2026, 10, 1),
            amount=Decimal("40000.00"),
            transaction_type="CREDIT",
            normalized_merchant="NEFT INWARD CR KRONOS CLIENT",
            category="Unclassified Credit",
            source_type=Transaction.SOURCE_IMPORT,
        )

        metrics_before = compute_dataset_financial_metrics(self.session_id, include_persona=False)
        self.assertEqual(metrics_before["monthly_income"], 0.0)

        # Correct to Freelance Income
        payload = {
            "session_id": self.session_id,
            "transaction_id": str(tx.id),
            "new_category": "Freelance Income",
        }
        resp = self.client.post(
            CORRECT_URL,
            payload,
            format="json",
            HTTP_X_SESSION_TOKEN=self.session_token,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        metrics_after = compute_dataset_financial_metrics(self.session_id, include_persona=False)
        self.assertEqual(metrics_after["monthly_income"], 40000.0)
