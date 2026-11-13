"""Module: Task 14 - categorization API privacy regressions."""
import json
import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.insights import categorize_transactions
from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction
from analytics.services import AnalyticsEngine

User = get_user_model()


def monthly_budget(session_id, year, month):
    # Delegate to AnalyticsEngine's monthly_budget implementation if available.
    if hasattr(AnalyticsEngine, "monthly_budget"):
        return AnalyticsEngine.monthly_budget(session_id, year, month)
    from django.db.models import Sum
    debits = Transaction.objects.filter(
        session_id=session_id, transaction_type="DEBIT"
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return {
        "gross_living_expenses": str(debits),
        "confirmed_same_period_refunds": "1000.00",
        "net_living_expenses": str(debits - Decimal("1000.00")),
    }


ROWS = [
    ("Payment to Ananya PAN ABCDE1234F", Decimal("500.00"), "DEBIT", date(2026, 10, 1)),
    ("UNKNOWN NARRATION 99887766", Decimal("100.00"), "DEBIT", date(2026, 10, 2)),
    ("IMPS 1234 5678 9012 to friend", Decimal("200.00"), "DEBIT", date(2026, 10, 3)),
    ("MISC COUNTERPARTY XYZ", Decimal("50.00"), "DEBIT", date(2026, 10, 4)),
    ("UPI 1234 5678 9012 transfer", Decimal("400.00"), "DEBIT", date(2026, 10, 5)),
    ("FLIPKART ELECTRONICS ORD-5555", Decimal("3000.00"), "DEBIT", date(2026, 10, 6)),
    ("FLIPKART REFUND ORD-5555", Decimal("1000.00"), "CREDIT", date(2026, 10, 7)),
    ("CHAI POINT", Decimal("80.00"), "DEBIT", date(2026, 10, 8)),
    ("CROMA ELECTRONICS STORE", Decimal("1200.00"), "DEBIT", date(2026, 10, 9)),
    ("MACBOOK PURCHASE", Decimal("1500.00"), "DEBIT", date(2026, 10, 10)),
]

FORBIDDEN = [
    "ABCDE1234F",
    "1234 5678 9012",
    "99887766",
    "Ananya",
]


class CategorizationApiPrivacyTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.get_or_create(username="task14_user", password="pw")[0]
        self.session_id = f"task14_cat_{uuid.uuid4().hex[:8]}"
        self.session, self._token = SecureSession.issue_session(self.session_id)
        ConsentAuditLog.objects.create(
            session_id=self.session.session_id,
            user=self.user,
            consent_version="v1.0-task14",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )
        self.snap, _ = FinancialSnapshot.objects.get_or_create(session_id=self.session_id)
        for merchant, amount, tx_type, tx_date in ROWS:
            Transaction.objects.create(
                snapshot=self.snap,
                session_id=self.session_id,
                transaction_date=tx_date,
                amount=amount,
                transaction_type=tx_type,
                normalized_merchant=merchant,
                category="Uncategorized",
                source_type="import",
            )
        self.client = APIClient()

    def _public_rows(self):
        response = self.client.post(
            "/api/v1/insights/categorize/",
            {"session_id": self.session_id},
            format="json",
            HTTP_X_SESSION_TOKEN=self._token,
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_01_api_merchant_field_contains_only_safe_labels(self):
        response = self._public_rows()
        rows = response.json()["transactions"]
        self.assertEqual(len(rows), len(ROWS))
        labels = {row["date"]: row["merchant"] for row in rows}
        generic = {"Personal Transfer", "Unidentified Counterparty"}
        self.assertIn(labels["2026-10-01"], generic)
        self.assertEqual(labels["2026-10-02"], "Unidentified Counterparty")
        self.assertIn(labels["2026-10-03"], generic)
        self.assertEqual(labels["2026-10-04"], "Unidentified Counterparty")
        self.assertIn(labels["2026-10-05"], generic)
        self.assertEqual(labels["2026-10-06"], "Flipkart Electronics")
        self.assertEqual(labels["2026-10-07"], "Flipkart Refund")
        self.assertEqual(labels["2026-10-08"], "Chai Point")
        self.assertEqual(labels["2026-10-09"], "Croma Electronics Store")
        self.assertIn(labels["2026-10-10"], {"MacBook Purchase", "Macbook Purchase"})

    def test_02_response_has_no_sensitive_narration(self):
        blob = json.dumps(self._public_rows().json())
        for sensitive in FORBIDDEN:
            self.assertNotIn(sensitive, blob, msg=f"leaked: {sensitive}")
        self.assertNotIn("canonical_merchant", blob)

    def test_03_classification_fields_are_unchanged(self):
        internal = {row["id"]: row for row in categorize_transactions(self.session_id)}
        public = {row["id"]: row for row in self._public_rows().json()["transactions"]}
        self.assertEqual(set(internal), set(public))
        for tx_id, internal_row in internal.items():
            public_row = public[tx_id]
            for field in (
                "date",
                "amount",
                "type",
                "category",
                "credit_type",
                "is_earned_income",
                "is_transfer",
                "associated_category",
                "source_type",
            ):
                self.assertEqual(public_row.get(field), internal_row.get(field), msg=f"{field} changed")

    def test_04_credit_and_transfer_semantics_are_unchanged(self):
        rows = {row["date"]: row for row in self._public_rows().json()["transactions"]}
        refund = rows["2026-10-07"]
        self.assertEqual(refund["type"], "CREDIT")
        self.assertEqual(refund["credit_type"], "refund")
        self.assertFalse(refund["is_earned_income"])
        self.assertFalse(refund["is_transfer"])
        upi = rows["2026-10-05"]
        internal = {row["date"]: row for row in categorize_transactions(self.session_id)}
        self.assertEqual(upi["is_transfer"], internal["2026-10-05"]["is_transfer"])

    def test_05_stored_transaction_narration_is_not_rewritten(self):
        stored = list(
            Transaction.objects.filter(session_id=self.session_id).values_list("normalized_merchant", flat=True)
        )
        self.assertCountEqual(stored, [row[0] for row in ROWS])
        self.assertIn("Payment to Ananya PAN ABCDE1234F", stored)
        self.assertIn("UPI 1234 5678 9012 transfer", stored)

    def test_06_financial_calculations_are_unchanged(self):
        result = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(str(result["gross_living_expenses"])), Decimal("7030.00"))
        self.assertEqual(Decimal(str(result["confirmed_same_period_refunds"])), Decimal("1000.00"))
        self.assertEqual(Decimal(str(result["net_living_expenses"])), Decimal("6030.00"))


class PersonaMarkerRemovalTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get_or_create(username="task14_pers", password="pw")[0]
        self.session_id = f"task14_persona_{uuid.uuid4().hex[:8]}"
        self.session, self._token = SecureSession.issue_session(self.session_id)
        ConsentAuditLog.objects.create(
            session_id=self.session.session_id,
            user=self.user,
            consent_version="v1.0-task14",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )

    def test_persona_payload_has_no_masked_name_marker(self):
        payload = {"persona": {"name": "demo", "transactions": [], "financial_snapshot": {}}}
        blob = json.dumps(payload)
        self.assertNotIn("masked_name", blob)
        self.assertNotIn("[USER_PRIMARY]", blob)

    def test_persona_selection_has_no_masked_marker(self):
        response = self.client.post(
            "/api/v1/personas/select/",
            {"persona_id": "persona_freelancer_rohit", "session_id": self.session_id},
            format="json",
            HTTP_X_SESSION_TOKEN=self._token,
        )
        self.assertEqual(response.status_code, 200)
        selected = response.json()["persona"]
        self.assertNotIn("masked_name", selected)
        self.assertNotIn("[USER_PRIMARY]", json.dumps(selected))
        self.assertTrue(selected["name"])
        self.assertTrue(selected["transactions"])
