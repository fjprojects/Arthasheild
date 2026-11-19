"""
Regressions for the verified financial-consistency, provenance, privacy and
reliability upgrades.

All data in this module is synthetic or read from the checked-in demo persona
fixture. The tests deliberately pin the difference between observed ledger
evidence, scenario metadata and deterministic estimates.
"""
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from advisor.services import AdvisorService
from analytics.stress_test import run_commitment_stress_test
from api.insights import (
    compute_dataset_financial_metrics,
    categorize_transactions,
    category_display_name,
    detect_subscriptions,
    monthly_budget,
    resolve_credit_classification,
    resolve_transaction_category,
)
from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction
from sanitizer.services import SanitizerService


class VerifiedUpgradeTestBase(TestCase):
    """Consented session helpers shared by the regression classes."""

    def setUp(self):
        super().setUp()
        suffix = uuid.uuid4().hex[:10]
        self.session_id = f"verified_{suffix}"
        self.session, self.token = SecureSession.issue_session(self.session_id)
        self.client = APIClient()
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version="v1.0-verified-upgrades",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        self.snapshot = FinancialSnapshot.objects.create(
            session_id=self.session_id,
            liquid_balance=Decimal("120000.00"),
            monthly_income=Decimal("80000.00"),
            monthly_expenses=Decimal("40000.00"),
            fixed_commitments=Decimal("25000.00"),
        )

    def add_tx(self, day, amount, tx_type, merchant, category="Uncategorized",
               source_type=None, is_recurring=False, risk_note=""):
        return Transaction.objects.create(
            snapshot=self.snapshot,
            session_id=self.session_id,
            transaction_date=day,
            amount=Decimal(str(amount)),
            transaction_type=tx_type,
            normalized_merchant=merchant,
            category=category,
            source_type=source_type or Transaction.SOURCE_IMPORT,
            is_recurring=is_recurring,
            risk_note=risk_note,
        )


class StressTestEvidenceValidationTests(VerifiedUpgradeTestBase):
    """Only real candidate IDs from the active session may become evidence."""

    def setUp(self):
        super().setUp()
        self.valid_tx = self.add_tx(
            date(2026, 10, 2), "45000", "CREDIT", "SALARY CREDIT ACME CORP"
        )
        self.second_valid_tx = self.add_tx(
            date(2026, 10, 3), "4200", "DEBIT", "NETFLIX SUBSCRIPTION"
        )
        other_session = f"other_{uuid.uuid4().hex[:8]}"
        other_snapshot, _ = FinancialSnapshot.objects.get_or_create(
            session_id=other_session
        )
        self.cross_session_tx = Transaction.objects.create(
            snapshot=other_snapshot,
            session_id=other_session,
            transaction_date=date(2026, 10, 4),
            amount=Decimal("100"),
            transaction_type="DEBIT",
            normalized_merchant="UNRELATED CHARGE",
            source_type=Transaction.SOURCE_IMPORT,
        )

    def _detector_result(self):
        return [
            {
                "is_financial_commitment": True,
                "is_potential_leakage": False,
                "estimated_monthly_cost": "1000.00",
                "candidate_transaction_ids": [
                    str(self.valid_tx.id),
                    123456789,
                    None,
                    {},
                    str(self.valid_tx.id),
                    str(self.cross_session_tx.id),
                ],
            },
            {
                "is_financial_commitment": False,
                "is_potential_leakage": True,
                "estimated_monthly_cost": "500.00",
                # Legacy boolean is deliberately not an evidence source.
                "candidates": True,
            },
        ]

    def test_malformed_duplicate_and_cross_session_ids_are_ignored(self):
        with patch(
            "analytics.stress_test.detect_subscriptions",
            return_value=self._detector_result(),
        ):
            result = run_commitment_stress_test(
                session_id=self.session_id,
                as_of_date=date(2026, 10, 20),
            )

        evidence = result["evidence_ledger"]
        self.assertEqual(
            evidence["commitment_evidence_ids"].count(str(self.valid_tx.id)), 1
        )
        self.assertNotIn(str(self.cross_session_tx.id), json.dumps(evidence))
        self.assertNotIn("123456789", json.dumps(evidence))
        self.assertEqual(evidence["all_cited_tx_ids"], [str(self.valid_tx.id)])

    def test_missing_or_empty_candidate_lists_never_produce_evidence(self):
        detector_rows = [
            {
                "is_financial_commitment": True,
                "estimated_monthly_cost": "1000.00",
                "candidates": True,
            },
            {
                "is_financial_commitment": True,
                "estimated_monthly_cost": "1000.00",
                "candidate_transaction_ids": [],
            },
            {
                "is_financial_commitment": True,
                "estimated_monthly_cost": "1000.00",
                "candidate_transaction_ids": "not-a-list",
            },
        ]
        with patch(
            "analytics.stress_test.detect_subscriptions",
            return_value=detector_rows,
        ):
            result = run_commitment_stress_test(
                session_id=self.session_id,
                as_of_date=date(2026, 10, 20),
            )

        self.assertEqual(result["evidence_ledger"]["commitment_evidence_ids"], [])

    def test_detector_failure_is_not_swallowed_into_a_safe_verdict(self):
        with patch(
            "analytics.stress_test.detect_subscriptions",
            side_effect=RuntimeError("detector unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                run_commitment_stress_test(
                    session_id=self.session_id,
                    as_of_date=date(2026, 10, 20),
                )

    def test_view_returns_explicit_computation_error_on_internal_failure(self):
        with patch(
            "api.views.run_commitment_stress_test",
            side_effect=RuntimeError("detector unavailable"),
        ):
            response = self.client.post(
                "/api/v1/analytics/commitment-stress-test/",
                {"item_name": "Laptop", "price": 65000},
                format="json",
                HTTP_X_SESSION_TOKEN=self.token,
            )

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["code"], "STRESS_TEST_COMPUTATION_ERROR")
        self.assertNotIn("SAFE", json.dumps(body))


class CategoryAuthorityTests(VerifiedUpgradeTestBase):
    """Stored meaningful categories and human corrections are authoritative."""

    def test_stored_freelance_income_is_not_demoted_to_unclassified_credit(self):
        tx = self.add_tx(
            date(2026, 10, 1), "40000", "CREDIT", "CLIENT PAYMENT RECEIVED",
            category="Freelance Income",
        )
        info = resolve_credit_classification(tx)

        self.assertEqual(info["credit_type"], "earned_income")
        self.assertTrue(info["is_earned_income"])
        self.assertEqual(info["category"], "freelance_income")
        self.assertEqual(info["category_source"], "STORED_CATEGORY")
        row = next(r for r in categorize_transactions(self.session_id) if r["id"] == str(tx.id))
        self.assertEqual(row["category_key"], "freelance_income")
        self.assertEqual(row["credit_type"], "earned_income")
        budget = monthly_budget(self.session_id, 2026, 10)
        self.assertEqual(Decimal(budget["operating_income"]), Decimal("40000.00"))

    def test_stored_rent_and_housing_is_distinct_from_generic_bills(self):
        tx = self.add_tx(
            date(2026, 10, 25), "22000", "DEBIT", "APARTMENT RENT LANDLORD",
            category="Rent & Housing",
        )

        self.assertEqual(resolve_transaction_category(tx), "rent_housing")
        self.assertEqual(category_display_name("rent_housing"), "Rent & Housing")
        row = next(r for r in categorize_transactions(self.session_id) if r["id"] == str(tx.id))
        self.assertEqual(row["category_key"], "rent_housing")
        self.assertEqual(row["category"], "Rent & Housing")
        self.assertNotEqual(row["category_key"], "bills")

    def test_user_correction_survives_categorization(self):
        tx = self.add_tx(
            date(2026, 10, 6), "1500", "DEBIT", "UPI MERCHANT PAYMENT",
            category="Bills",
        )
        response = self.client.post(
            "/api/v1/insights/correct-transaction/",
            {
                "transaction_id": str(tx.id),
                "new_category": "Rent & Housing",
                "notes": "Verified by user as rent",
            },
            format="json",
            HTTP_X_SESSION_TOKEN=self.token,
        )
        self.assertEqual(response.status_code, 200)
        tx.refresh_from_db()

        row = next(r for r in categorize_transactions(self.session_id) if r["id"] == str(tx.id))
        self.assertEqual(row["category_source"], "USER_CORRECTION")
        self.assertEqual(row["category_key"], "rent_housing")
        self.assertIn("USER_CORRECTION", tx.risk_note)

    def test_keyword_fallback_applies_only_to_generic_categories(self):
        inferred = self.add_tx(
            date(2026, 10, 7), "649", "DEBIT", "NETFLIX SUBSCRIPTION",
            category="",
        )
        rows = {r["id"]: r for r in categorize_transactions(self.session_id)}

        self.assertEqual(rows[str(inferred.id)]["category_source"], "INFERRED_KEYWORD")
        self.assertEqual(rows[str(inferred.id)]["category_key"], "subscriptions")

    def test_rent_is_an_obligation_not_discretionary_leakage(self):
        for month in (8, 9, 10):
            self.add_tx(
                date(2026, month, 25), "22000", "DEBIT", "APARTMENT RENT LANDLORD",
                category="Rent & Housing",
            )

        entries = detect_subscriptions(self.session_id)
        rent_entries = [entry for entry in entries if entry["payment_type"] == "rent"]

        self.assertEqual(len(rent_entries), 1)
        self.assertTrue(rent_entries[0]["is_financial_commitment"])
        self.assertFalse(rent_entries[0]["is_potential_leakage"])
        self.assertEqual(rent_entries[0]["occurrence_count"], 3)
        self.assertTrue(rent_entries[0]["candidate_transaction_ids"])


class DatasetProvenanceTests(VerifiedUpgradeTestBase):
    """The selected dataset is resolved once and never silently substituted."""

    def setUp(self):
        super().setUp()
        self.import_tx = self.add_tx(
            date(2026, 10, 2), "45000", "CREDIT", "SALARY CREDIT ACME CORP"
        )
        self.add_tx(
            date(2026, 10, 3), "500", "DEBIT", "SWIGGY ORDER",
            source_type=Transaction.SOURCE_IMPORT,
        )
        self.persona_tx = self.add_tx(
            date(2026, 10, 2), "75000", "CREDIT", "SALARY CREDIT DEMO EMPLOYER",
            source_type=Transaction.SOURCE_PERSONA,
        )
        self.add_tx(
            date(2026, 10, 4), "1000", "DEBIT", "NETFLIX SUBSCRIPTION",
            source_type=Transaction.SOURCE_PERSONA,
        )

    def test_dataset_metrics_use_only_the_selected_source(self):
        imported = compute_dataset_financial_metrics(self.session_id, False)
        persona = compute_dataset_financial_metrics(self.session_id, True)

        self.assertEqual(imported["data_source"], "IMPORTED_STATEMENT")
        self.assertEqual(imported["status"], "AVAILABLE")
        self.assertEqual(imported["monthly_income"], 45000.0)

        self.assertEqual(persona["data_source"], "PERSONA_SCENARIO")
        self.assertEqual(persona["status"], "AVAILABLE")
        self.assertEqual(persona["monthly_income"], 75000.0)

    def test_imported_runway_is_withheld_but_persona_runway_is_labelled_estimate(self):
        imported = compute_dataset_financial_metrics(self.session_id, False)
        persona = compute_dataset_financial_metrics(self.session_id, True)

        self.assertIsNone(imported["emergency_runway_months"])
        self.assertEqual(imported["metric_basis"]["runway"], "WITHHELD")
        self.assertIsNotNone(persona["emergency_runway_months"])
        self.assertEqual(
            persona["metric_basis"]["runway"], "PERSONA_SCENARIO_ESTIMATE"
        )

    def test_document_analysis_endpoint_honours_include_persona(self):
        with patch.object(AdvisorService, "get_api_key", return_value=None):
            imported_response = self.client.post(
                "/api/v1/documents/analyze/",
                {"sanitized_text": "Account statement", "include_persona": False},
                format="json",
                HTTP_X_SESSION_TOKEN=self.token,
            )
            persona_response = self.client.post(
                "/api/v1/documents/analyze/",
                {"sanitized_text": "Account statement", "include_persona": True},
                format="json",
                HTTP_X_SESSION_TOKEN=self.token,
            )

        self.assertEqual(imported_response.status_code, 200)
        self.assertEqual(persona_response.status_code, 200)
        imported_metrics = imported_response.json()["metrics"]
        persona_metrics = persona_response.json()["metrics"]
        self.assertEqual(imported_metrics["data_source"], "IMPORTED_STATEMENT")
        self.assertEqual(imported_metrics["monthly_income"], 45000.0)
        self.assertEqual(persona_metrics["data_source"], "PERSONA_SCENARIO")
        self.assertEqual(persona_metrics["monthly_income"], 75000.0)

    def test_missing_selected_dataset_reports_insufficient_data(self):
        session_id = f"import_only_{uuid.uuid4().hex[:8]}"
        session, token = SecureSession.issue_session(session_id)
        ConsentAuditLog.objects.create(
            session_id=session_id,
            consent_version="v1.0-import-only",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )
        snapshot, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
        Transaction.objects.create(
            snapshot=snapshot,
            session_id=session_id,
            transaction_date=date(2026, 10, 2),
            amount=Decimal("45000"),
            transaction_type="CREDIT",
            normalized_merchant="SALARY CREDIT ACME CORP",
            source_type=Transaction.SOURCE_IMPORT,
        )
        client = APIClient()

        with patch.object(AdvisorService, "get_api_key", return_value=None):
            response = client.post(
                "/api/v1/documents/analyze/",
                {"sanitized_text": "Account statement", "include_persona": True},
                format="json",
                HTTP_X_SESSION_TOKEN=token,
            )

        self.assertEqual(response.status_code, 200)
        metrics = response.json()["metrics"]
        self.assertEqual(metrics["data_source"], "PERSONA_SCENARIO")
        self.assertEqual(metrics["dataset_status"], "INSUFFICIENT_DATA")
        self.assertNotIn("monthly_income", metrics)
        self.assertNotIn("emergency_runway_months", metrics)


class OfflineAdvisorEvidenceLanguageTests(TestCase):
    """Offline fallback must not claim unverified savings."""

    def test_offline_fallback_uses_evidence_qualified_language(self):
        metrics = {
            "health_score": 70,
            "emergency_runway_months": 4.5,
            "recurring_commitments": {
                "monthly_commitments": 9000,
                "monthly_leakage": 2480,
            },
        }
        with patch.object(AdvisorService, "get_api_key", return_value=None):
            result = AdvisorService.analyze_sanitized_statement("sanitized", metrics)

        blob = json.dumps(result).lower()
        self.assertEqual(result["source"], "OFFLINE_RULE_BASED")
        self.assertIn("review candidates", blob)
        self.assertIn("usage", blob)
        for unsupported_claim in (
            "idle cloud hosting",
            "duplicate seats",
            "unused services",
            "wasteful",
            "immediate savings",
            "eliminate",
            "guaranteed savings",
        ):
            self.assertNotIn(unsupported_claim, blob)

    def test_withheld_metrics_are_explained_instead_of_invented(self):
        with patch.object(AdvisorService, "get_api_key", return_value=None):
            result = AdvisorService.analyze_sanitized_statement(
                "sanitized", {"recurring_commitments": {}}
            )

        blob = json.dumps(result).lower()
        self.assertIn("withheld", blob)
        self.assertIn("verified balance", blob)

    def test_available_imported_metrics_are_not_described_as_missing(self):
        metrics = {
            "data_source": "IMPORTED_STATEMENT",
            "dataset_status": "AVAILABLE",
            "monthly_income": 45000.0,
            "monthly_expenses": 36815.0,
            "emergency_runway_months": None,
            "recurring_commitments": {},
        }
        with patch.object(AdvisorService, "get_api_key", return_value=None):
            result = AdvisorService.analyze_sanitized_statement("sanitized", metrics)

        summary = result["plain_english_summary"]
        self.assertIn("selected imported statement", summary)
        self.assertIn("observed income", summary)
        self.assertIn("withheld", summary)
        self.assertNotIn("no deterministic financial metrics", summary.lower())

    def test_persona_metrics_are_labelled_as_scenario(self):
        metrics = {
            "data_source": "PERSONA_SCENARIO",
            "monthly_income": 82000.0,
            "monthly_expenses": 39905.0,
            "emergency_runway_months": 1.97,
            "recurring_commitments": {},
        }
        with patch.object(AdvisorService, "get_api_key", return_value=None):
            result = AdvisorService.analyze_sanitized_statement("sanitized", metrics)

        summary = result["plain_english_summary"]
        self.assertIn("persona scenario", summary)
        self.assertIn("persona-scenario income", summary)


class SanitizerContextPrecedenceTests(TestCase):
    """Explicit account/card labels win over ambiguous digit shape."""

    def test_explicit_account_label_beats_card_shaped_number(self):
        raw = "Account Number: 1234567890123456"
        result = SanitizerService.sanitize(raw)

        self.assertEqual(
            result["sanitized_text"], "Account Number: [REDACTED_ACCOUNT]"
        )
        self.assertEqual(result["redactions"][0]["type"], "ACCOUNT_NUMBER")
        self.assertNotIn("1234567890123456", json.dumps(result))

    def test_explicit_card_labels_are_still_detected_as_cards(self):
        cases = {
            "Card Number: 1234 5678 9012 3456": "[REDACTED_CARD]",
            "Debit Card: 1234-5678-9012-3456": "[REDACTED_CARD]",
            "Credit Card: 378282246310005": "[REDACTED_CARD]",
        }
        for raw, placeholder in cases.items():
            with self.subTest(raw=raw):
                result = SanitizerService.sanitize(raw)
                self.assertIn(placeholder, result["sanitized_text"])
                self.assertTrue(
                    any(r["type"] == "CREDIT_DEBIT_CARD" for r in result["redactions"])
                )
                for numeric_token in raw.split(": ")[1].split():
                    self.assertNotIn(numeric_token, json.dumps(result))

    def test_account_alias_and_grouped_digits_are_redacted(self):
        raw = "A/C: 1234 5678 9012 3456"
        result = SanitizerService.sanitize(raw)

        self.assertEqual(result["sanitized_text"], "A/C: [REDACTED_ACCOUNT]")
        self.assertNotIn("1234 5678 9012 3456", json.dumps(result))


class RohitLeakageReconciliationTests(VerifiedUpgradeTestBase):
    """Static persona leakage metadata is not live evidence."""

    def test_static_summary_difference_is_explained_by_review_payments(self):
        fixture = (
            Path(settings.BASE_DIR).parent / "synthetic_data" / "personas.json"
        )
        with fixture.open("r", encoding="utf-8") as handle:
            persona = next(
                p for p in json.load(handle)["personas"]
                if p["id"] == "persona_freelancer_rohit"
            )

        response = self.client.post(
            "/api/v1/personas/select/",
            {"persona_id": "persona_freelancer_rohit"},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token,
        )
        self.assertEqual(response.status_code, 200)

        static_summary = persona["detected_leaks_summary"]
        static_total = Decimal(str(static_summary["total_monthly_leakage"]))
        static_items = {item["service"]: Decimal(str(item["monthly_cost"]))
                        for item in static_summary["dormant_subscriptions"]}
        self.assertEqual(static_total, Decimal("9430.00"))
        self.assertEqual(sum(static_items.values()), static_total)
        self.assertIn("ChatGPT Plus", static_items)
        self.assertIn("GitHub Copilot", static_items)
        static_difference = (
            static_items["ChatGPT Plus"] + static_items["GitHub Copilot"]
        )
        self.assertEqual(static_difference, Decimal("2480.00"))
        self.assertEqual(static_total - static_difference, Decimal("6950.00"))

        entries = detect_subscriptions(self.session_id, include_persona=True)
        self.assertEqual(detect_subscriptions(self.session_id, include_persona=False), [])

        def find_entry(fragment):
            return next(
                entry for entry in entries
                if fragment in entry["merchant"].lower()
            )

        chatgpt = find_entry("chatgpt")
        copilot = find_entry("copilot")
        rent = find_entry("rent")
        emi = find_entry("emi")

        self.assertEqual(Decimal(chatgpt["estimated_monthly_cost"]), Decimal("1650.00"))
        self.assertEqual(Decimal(copilot["estimated_monthly_cost"]), Decimal("830.00"))
        for review_payment in (chatgpt, copilot):
            self.assertEqual(review_payment["confidence"], "PROBABLE")
            self.assertFalse(review_payment["is_financial_commitment"])
            self.assertFalse(review_payment["is_potential_leakage"])

        self.assertEqual(rent["payment_type"], "rent")
        self.assertEqual(emi["payment_type"], "emi_or_loan")
        self.assertFalse(rent["is_potential_leakage"])
        self.assertFalse(emi["is_potential_leakage"])

        metrics = compute_dataset_financial_metrics(self.session_id, True)
        self.assertEqual(metrics["recurring_commitments"]["monthly_leakage"], 0.0)
        self.assertNotEqual(
            Decimal(str(metrics["recurring_commitments"]["monthly_leakage"])),
            static_total,
        )
