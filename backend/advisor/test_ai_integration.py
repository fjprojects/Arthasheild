"""
Verification suite for the optional live AI (advisor) integration.

Covers the ten release scenarios for the Gemini path:

  1. normal imported financial history
  2. no imported transactions
  3. insufficient financial history
  4. unusual spending
  5. confirmed subscription commitments
  6. variable subscription amounts
  7. refund and own-account transfer exclusions
  8. invalid model responses
  9. provider timeout / unavailable API
 10. offline fallback

It also verifies the privacy boundary of the outbound payload, that the
deterministic engine stays authoritative, and that a provider failure never
breaks the dashboard.

IMPORTANT - what is real and what is simulated:

  * The provider transport is MOCKED here. A genuine live request requires a
    real GEMINI_API_KEY, which is never available in an automated suite. The
    mock exercises the transport, validation and failure-handling contract
    only; it is never counted as live AI verification.
  * The offline fallback, the deterministic engine and the privacy boundary
    are exercised for real, without any mock.
"""

import json
from datetime import date
from unittest.mock import patch

import requests
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from advisor.services import AdvisorService
from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction
from api.views import DocumentAnalyzeView


VALID_MODEL_ANSWER = {
    "plain_english_summary": "Your recurring charges repeat every month.",
    "top_actionable_wins": [
        {
            "title": "Cancel an unused streaming seat",
            "impact_amount": "Reduce identified recurring charges worth 649.0/mo",
            "action": "Review the subscription before the next renewal.",
        }
    ],
    "hidden_risks_and_predatory_clauses": [
        {
            "risk_name": "Auto-debit renewal",
            "explanation": "The charge renews silently each month.",
            "severity": "MEDIUM",
        }
    ],
    "disclaimer": "Educational analysis. Not certified financial advice.",
}


def provider_answer(text_payload, thought=None):
    """Builds a provider response body, optionally with a reasoning part."""
    parts = []
    if thought is not None:
        parts.append({"text": thought, "thought": True})
    parts.append({"text": text_payload})
    return {"candidates": [{"content": {"parts": parts}, "finishReason": "STOP"}]}


class AdvisorTestBase(TestCase):
    """Shared session, consent and synthetic transaction helpers."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.session, self.token = SecureSession.issue_session()
        self.session_id = self.session.session_id
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version="v1.0-ai-verification",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

    def add_tx(self, day, amount, kind, merchant, source="import", category="Uncategorized"):
        return Transaction.objects.create(
            session_id=self.session_id,
            transaction_date=day,
            amount=amount,
            transaction_type=kind,
            normalized_merchant=merchant,
            category=category,
            source_type=source,
        )

    def make_snapshot(self, **kwargs):
        defaults = dict(
            session_id=self.session_id,
            monthly_income=75000,
            monthly_expenses=25769,
            monthly_leakage_detected=649,
            health_score=78,
            health_grade="A (Strong)",
            emergency_runway_months=3.5,
            safe_to_spend_daily=1200,
            liquid_balance=107693,
        )
        defaults.update(kwargs)
        return FinancialSnapshot.objects.create(**defaults)

    def analyze(self, sanitized_text="2026-10-01 POS NETFLIX SUBSCRIPTION 649.00"):
        req = self.factory.post(
            "/api/v1/documents/analyze/",
            data={"sanitized_text": sanitized_text, "session_id": self.session_id},
            format="json",
            HTTP_X_SESSION_TOKEN=self.token,
        )
        req.session = {}
        return DocumentAnalyzeView.as_view()(req)


class AdvisorTransportContractTests(AdvisorTestBase):
    """The request the application makes and how the answer is read back."""

    def test_01_stable_api_route_is_used_first(self):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = provider_answer(
                    json.dumps(VALID_MODEL_ANSWER)
                )
                AdvisorService.analyze_sanitized_statement("sanitized", {"health_score": 80})

                url = mock_post.call_args[0][0]
                self.assertIn("/v1/models/", url)
                self.assertNotIn("/v1beta/", url)
                self.assertIn(AdvisorService.get_model(), url)

    def test_02_beta_route_is_the_fallback_when_the_stable_route_is_absent(self):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.side_effect = [
                    _status(404),
                    _status(200, provider_answer(json.dumps(VALID_MODEL_ANSWER))),
                ]
                result = AdvisorService.analyze_sanitized_statement(
                    "sanitized", {"health_score": 80}
                )
                self.assertEqual(mock_post.call_count, 2)
                self.assertIn("/v1beta/", mock_post.call_args[0][0])
                self.assertEqual(result["source"], "LIVE_GEMINI")

    def test_03_a_non_404_failure_does_not_retry_another_route(self):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value = _status(500)
                result = AdvisorService.analyze_sanitized_statement(
                    "sanitized", {"health_score": 80}
                )
                self.assertEqual(mock_post.call_count, 1)
                self.assertEqual(result["source"], "OFFLINE_RULE_BASED")

    def test_04_reasoning_parts_are_not_mistaken_for_the_answer(self):
        """A thinking model may return reasoning before the answer."""
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = provider_answer(
                    json.dumps(VALID_MODEL_ANSWER),
                    thought="Let me check the pre-computed metrics first...",
                )
                result = AdvisorService.analyze_sanitized_statement(
                    "sanitized", {"health_score": 80}
                )
                self.assertEqual(result["source"], "LIVE_GEMINI")
                self.assertIn("recurring charges", result["plain_english_summary"])

    def test_05_a_response_without_an_answer_part_is_rejected(self):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {
                    "candidates": [{"content": {"parts": [{"text": "thinking only", "thought": True}]}}]
                }
                result = AdvisorService.analyze_sanitized_statement(
                    "sanitized", {"health_score": 80}
                )
                self.assertEqual(result["source"], "OFFLINE_RULE_BASED")

    def test_06_a_blocked_prompt_is_rejected(self):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {
                    "promptFeedback": {"blockReason": "SAFETY"}
                }
                result = AdvisorService.analyze_sanitized_statement(
                    "sanitized", {"health_score": 80}
                )
                self.assertEqual(result["source"], "OFFLINE_RULE_BASED")

    def test_07_request_configuration_is_derived_from_the_pinned_model(self):
        """thinkingLevel errors on older models; temperature is ignored on new ones."""
        modern = AdvisorService._generation_config("gemini-3.6-flash")
        self.assertEqual(modern["thinkingConfig"], {"thinkingLevel": "LOW"})
        self.assertNotIn("temperature", modern)
        self.assertEqual(modern["responseMimeType"], "application/json")

        legacy = AdvisorService._generation_config("gemini-2.5-flash")
        self.assertNotIn("thinkingConfig", legacy)
        self.assertEqual(legacy["temperature"], 0.2)

        self.assertFalse(AdvisorService._supports_thinking_level("gemini-2.5-flash"))
        self.assertTrue(AdvisorService._supports_thinking_level("gemini-3.6-flash"))

    def test_08_the_configured_model_is_currently_supported(self):
        """gemini-2.5-flash is deprecated and is shut down on 2026-12-01."""
        self.assertEqual(AdvisorService.DEFAULT_MODEL, "gemini-3.6-flash")
        self.assertNotIn("2.5-flash", AdvisorService.DEFAULT_MODEL)
        self.assertNotIn("2.0-flash", AdvisorService.DEFAULT_MODEL)

    def test_09_without_a_key_no_request_is_made_at_all(self):
        with patch.object(AdvisorService, "get_api_key", return_value=None):
            with patch("requests.post") as mock_post:
                result = AdvisorService.analyze_sanitized_statement(
                    "sanitized", {"health_score": 80}
                )
                mock_post.assert_not_called()
                self.assertEqual(result["source"], "OFFLINE_RULE_BASED")

    def test_10_the_key_is_only_ever_sent_as_a_header(self):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = provider_answer(
                    json.dumps(VALID_MODEL_ANSWER)
                )
                AdvisorService.analyze_sanitized_statement("sanitized", {"health_score": 80})
                _, kwargs = mock_post.call_args
                self.assertEqual(kwargs["headers"]["x-goog-api-key"], "synthetic_test_key")
                self.assertNotIn("synthetic_test_key", json.dumps(kwargs["json"]))
                self.assertNotIn("synthetic_test_key", mock_post.call_args[0][0])


class AdvisorPrivacyBoundaryTests(AdvisorTestBase):
    """What actually leaves the host, and what comes back."""

    def test_01_the_outbound_payload_contains_no_raw_personal_identifiers(self):
        raw_text = (
            "Account Holder: Rajesh Kumar Verma\n"
            "Account Number: 998877665544\n"
            "Registered Phone: 9876543210\n"
            "PAN: ABCDE1234F\n"
            "2026-10-01 POS NETFLIX SUBSCRIPTION 649.00"
        )
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = provider_answer(
                    json.dumps(VALID_MODEL_ANSWER)
                )
                AdvisorService.analyze_sanitized_statement(raw_text, {"health_score": 80})
                sent = json.dumps(mock_post.call_args[1]["json"])

        for probe in (
            "Rajesh",
            "Kumar",
            "Verma",
            "998877665544",
            "9876543210",
            "ABCDE1234F",
        ):
            self.assertNotIn(probe, sent, msg=f"{probe} must not reach the provider")

    def test_02_the_outbound_payload_is_only_sanitized_text_and_metrics(self):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = provider_answer(
                    json.dumps(VALID_MODEL_ANSWER)
                )
                AdvisorService.analyze_sanitized_statement(
                    "[USER_PRIMARY] POS NETFLIX 649.00", {"health_score": 80}
                )
                body = mock_post.call_args[1]["json"]

        self.assertEqual(list(body.keys()), ["contents", "generationConfig"])
        self.assertEqual(len(body["contents"]), 1)
        self.assertIn("[USER_PRIMARY]", body["contents"][0]["parts"][0]["text"])

    def test_03_the_key_never_appears_in_the_response(self):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = provider_answer(
                    json.dumps(VALID_MODEL_ANSWER)
                )
                result = AdvisorService.analyze_sanitized_statement(
                    "sanitized", {"health_score": 80}
                )
        serialized = json.dumps(result)
        self.assertNotIn("synthetic_test_key", serialized)
        self.assertNotIn("x-goog-api-key", serialized)


class AdvisorScenarioTests(AdvisorTestBase):
    """The ten release scenarios, exercised through the real API view."""

    # -- scenario 1 ---------------------------------------------------------
    def test_01_scenario_normal_imported_history(self):
        self.make_snapshot()
        self.add_tx(date(2026, 10, 1), 75000, "CREDIT", "Client Global Tech Stipend")
        self.add_tx(date(2026, 10, 5), 649, "DEBIT", "Netflix Subscription")
        self.add_tx(date(2026, 10, 8), 25000, "DEBIT", "Landlord Rent Transfer")

        resp = self.analyze()
        self.assertEqual(resp.status_code, 200)
        data = resp.data

        self.assertEqual(data["analysis_source"], "OFFLINE_RULE_BASED")
        self.assertFalse(data["is_ai_generated"])
        self.assertEqual(data["metrics"]["monthly_income"], 75000.0)
        self.assertEqual(data["metrics"]["monthly_expenses"], 25769.0)
        # The deterministic figures are carried through untouched.
        self.assertEqual(data["metrics"]["recurring_commitments"]["monthly_leakage"], 0.0)
        self.assertIn("78/100", data["advisor_insights"]["plain_english_summary"])

    # -- scenario 2 ---------------------------------------------------------
    def test_02_scenario_no_imported_transactions(self):
        resp = self.analyze()
        self.assertEqual(resp.status_code, 200)
        data = resp.data

        self.assertEqual(data["metrics"]["recurring_commitments"]["monthly_commitments"], 0.0)
        self.assertEqual(data["metrics"]["recurring_commitments"]["confirmed_commitment_count"], 0)
        self.assertIn(
            "No deterministic financial metrics",
            data["advisor_insights"]["plain_english_summary"],
        )

    # -- scenario 3 ---------------------------------------------------------
    def test_03_scenario_insufficient_financial_history(self):
        """A single transaction is not a history: nothing may be invented."""
        self.add_tx(date(2026, 10, 5), 649, "DEBIT", "Netflix Subscription")

        resp = self.analyze()
        data = resp.data

        self.assertEqual(data["metrics"]["recurring_commitments"]["confirmed_commitment_count"], 0)
        self.assertEqual(data["metrics"]["recurring_commitments"]["monthly_leakage"], 0.0)
        self.assertNotIn("/100", data["advisor_insights"]["plain_english_summary"])

    # -- scenario 4 ---------------------------------------------------------
    def test_04_scenario_unusual_spending(self):
        """Unusual spending is a deterministic signal; the AI cannot alter it."""
        from api.insights import detect_unusual_spending

        self.add_tx(date(2026, 10, 2), 500, "DEBIT", "Chai Point")
        self.add_tx(date(2026, 10, 3), 500, "DEBIT", "Chai Point")
        self.add_tx(date(2026, 10, 4), 500, "DEBIT", "Chai Point")
        self.add_tx(date(2026, 10, 5), 49999, "DEBIT", "LUXURY TRAVEL AGENCY")

        findings = detect_unusual_spending(self.session_id, include_persona=False)
        anomalies = [f for f in findings if "travel" in str(f.get("merchant", "")).lower()]
        self.assertTrue(anomalies, msg="the deterministic detector must flag the outlier")
        self.assertEqual(anomalies[0]["reason"], "large_amount")

        resp = self.analyze()
        self.assertEqual(resp.status_code, 200)
        # The AI section does not restate or change the deterministic figures.
        self.assertNotIn("49999", json.dumps(resp.data["advisor_insights"]))

    # -- scenario 5 ---------------------------------------------------------
    def test_05_scenario_confirmed_subscription_commitments(self):
        for month in (8, 9, 10):
            self.add_tx(date(2026, month, 5), 649, "DEBIT", "Netflix Subscription")
        self.make_snapshot(monthly_leakage_detected=649)

        resp = self.analyze()
        data = resp.data

        recurring = data["metrics"]["recurring_commitments"]
        self.assertEqual(recurring["monthly_leakage"], 649.0)
        self.assertEqual(recurring["confirmed_commitment_count"], 1)
        self.assertIn("649.0", json.dumps(data["advisor_insights"]))

    # -- scenario 6 ---------------------------------------------------------
    def test_06_scenario_variable_subscription_amounts(self):
        """A variable subscription is reported with its observed range."""
        for month, amount in ((8, 199), (9, 249), (10, 299)):
            self.add_tx(date(2026, month, 5), amount, "DEBIT", "Netflix Subscription")

        resp = self.analyze()
        recurring = resp.data["metrics"]["recurring_commitments"]
        self.assertEqual(recurring["monthly_leakage"], 249.0)

        from api.insights import detect_subscriptions

        entry = [
            s for s in detect_subscriptions(self.session_id, include_persona=False)
            if "Netflix" in s["merchant"]
        ][0]
        self.assertEqual(float(entry["observed_amount_min"]), 199.0)
        self.assertEqual(float(entry["observed_amount_max"]), 299.0)
        self.assertEqual(entry["commitment_class"], "subscription_commitment")

    # -- scenario 7 ---------------------------------------------------------
    def test_07_scenario_refund_and_transfer_exclusions(self):
        """Refunds and own-account transfers are excluded by the engine."""
        self.make_snapshot()
        self.add_tx(date(2026, 10, 1), 75000, "CREDIT", "Client Global Tech Stipend")
        self.add_tx(date(2026, 10, 5), 5000, "DEBIT", "Swiggy Order 5551234")
        self.add_tx(date(2026, 10, 8), 10000, "DEBIT", "Self Transfer")
        self.add_tx(date(2026, 10, 10), 5000, "CREDIT", "REFUND SWIGGY ORDER 5551234")

        from api.insights import compute_imported_session_overview

        overview = compute_imported_session_overview(self.session_id)
        summary = overview["summary"]

        # The refund is matched to the purchase it reverses (shared reference),
        # so the purchase no longer counts as spending; the own-account
        # transfer is excluded from spending and from income.
        self.assertEqual(float(summary["monthly_income"]), 75000.0)
        self.assertEqual(float(summary["monthly_expenses"]), 0.0)
        self.assertEqual(float(overview["budget"]["debit_transfers"]), 10000.0)
        self.assertEqual(float(overview["budget"]["refunds_applied"]), 5000.0)
        self.assertEqual(float(overview["budget"]["gross_living_expenses"]), 5000.0)

    # -- scenario 8 ---------------------------------------------------------
    def test_08_scenario_invalid_model_responses(self):
        broken = [
            {"plain_english_summary": "no other keys"},
            {**VALID_MODEL_ANSWER, "top_actionable_wins": "not a list"},
            {**VALID_MODEL_ANSWER, "plain_english_summary": ""},
            {**VALID_MODEL_ANSWER, "top_actionable_wins": [{"no_title": 1}]},
            {**VALID_MODEL_ANSWER, "disclaimer": 42},
        ]
        for payload in broken:
            with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
                with patch("requests.post") as mock_post:
                    mock_post.return_value.status_code = 200
                    mock_post.return_value.json.return_value = provider_answer(json.dumps(payload))
                    resp = self.analyze()
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.data["analysis_source"], "OFFLINE_RULE_BASED")
            self.assertFalse(resp.data["is_ai_generated"])

    # -- scenario 9 ---------------------------------------------------------
    def test_09_scenario_provider_unavailable_or_timeout(self):
        self.make_snapshot()
        # An imported row is required for the selected dataset to be available;
        # without it the view correctly reports INSUFFICIENT_DATA instead of
        # inventing figures from a snapshot alone.
        self.add_tx(date(2026, 10, 1), 75000, "CREDIT", "Client Global Tech Stipend")
        for label, mock_setup in (
            ("timeout", _raise_timeout),
            ("network error", _raise_network_error),
            ("http 500", _status_500),
            ("http 429", _status_429),
        ):
            with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
                with patch("requests.post") as mock_post:
                    mock_setup(mock_post)
                    resp = self.analyze()

            self.assertEqual(resp.status_code, 200, msg=label)
            self.assertEqual(resp.data["analysis_source"], "OFFLINE_RULE_BASED", msg=label)
            self.assertFalse(resp.data["gemini_available"], msg=label)
            # The deterministic figures survive the provider failure.
            self.assertEqual(resp.data["metrics"]["monthly_income"], 75000.0, msg=label)

    # -- scenario 10 --------------------------------------------------------
    def test_10_scenario_offline_fallback_is_labelled_and_derived(self):
        self.make_snapshot()
        resp = self.analyze()
        data = resp.data

        self.assertEqual(data["analysis_source"], "OFFLINE_RULE_BASED")
        self.assertFalse(data["is_ai_generated"])
        self.assertEqual(data["engine_label"], "Offline Rule-Based Financial Insights")
        self.assertIn("Zero external egress", data["privacy_guarantee"])
        self.assertNotIn("LLM processed", data["privacy_guarantee"])

        insights = data["advisor_insights"]
        self.assertTrue(insights["numeric_claims_verified"])
        self.assertEqual(insights["unverified_amount_claims"], [])
        # Every amount quoted by the fallback is one the engine produced.
        allowed = {75000.0, 25769.0, 649.0, 78.0, 3.5, 1200.0}
        for token in AdvisorService.AMOUNT_RE.findall(
            json.dumps(insights["top_actionable_wins"])
        ):
            self.assertIn(float(token.replace(",", "")), allowed)

    # -- authority of the deterministic engine ------------------------------
    def test_11_the_ai_cannot_overwrite_the_deterministic_figures(self):
        self.make_snapshot()
        self.add_tx(date(2026, 10, 1), 75000, "CREDIT", "Client Global Tech Stipend")
        hostile = {
            "plain_english_summary": "Your income is 999999 and you save 888888.",
            "top_actionable_wins": [
                {"title": "x", "impact_amount": "Save 777777", "action": "y"}
            ],
            "hidden_risks_and_predatory_clauses": [],
            "disclaimer": "d",
        }
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = provider_answer(json.dumps(hostile))
                resp = self.analyze()

        data = resp.data
        # The deterministic metrics are unchanged by the model answer.
        self.assertEqual(data["metrics"]["monthly_income"], 75000.0)
        self.assertEqual(data["metrics"]["monthly_expenses"], 25769.0)
        # The invented figures are identified, not presented as verified.
        self.assertFalse(data["advisor_insights"]["numeric_claims_verified"])
        self.assertIn("₹999999", data["advisor_insights"]["unverified_amount_claims"])
        self.assertIn("₹777777", data["advisor_insights"]["unverified_amount_claims"])

    def test_12_ai_output_is_distinguishable_from_verified_facts(self):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = provider_answer(
                    json.dumps(VALID_MODEL_ANSWER)
                )
                resp = self.analyze()

        data = resp.data
        self.assertTrue(data["is_ai_generated"])
        self.assertTrue(data["gemini_available"])
        self.assertEqual(data["analysis_source"], "LIVE_GEMINI")
        self.assertEqual(data["engine_label"], "Live Gemini AI Analysis")
        self.assertEqual(data["advisor_insights"]["model"], AdvisorService.get_model())
        # The verified figures live in a separate object from the AI commentary.
        self.assertNotIn("advisor_insights", data["metrics"])
        self.assertIn("metrics", data)
        self.assertNotIn("plain_english_summary", data["metrics"])

    def test_13_consent_is_required_before_any_ai_analysis(self):
        ConsentAuditLog.objects.filter(session_id=self.session_id).update(is_active=False)
        resp = self.analyze()
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data.get("code"), "CONSENT_REQUIRED")


def _status(code, body=None):
    response = requests.Response()
    response.status_code = code
    response._content = json.dumps(body or {}).encode()
    return response


def _status_500(mock_post):
    mock_post.return_value = _status(500)


def _status_429(mock_post):
    mock_post.return_value = _status(429)


def _raise_timeout(mock_post):
    mock_post.side_effect = requests.exceptions.Timeout("simulated timeout")


def _raise_network_error(mock_post):
    mock_post.side_effect = requests.exceptions.ConnectionError("simulated network error")
