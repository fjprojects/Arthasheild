import json
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIRequestFactory
from advisor.services import AdvisorService
from api.views import DocumentAnalyzeView
from api.models import SecureSession, ConsentAuditLog


class AdvisorOutputValidationTests(TestCase):
    """
    The model answer is validated before it reaches the client: a malformed or
    off-schema answer is discarded, and every monetary figure the model states
    is checked against the deterministic metrics.
    """

    VALID_PAYLOAD = {
        "plain_english_summary": "Your recurring charges repeat every month.",
        "top_actionable_wins": [
            {"title": "Cancel an unused seat", "impact_amount": "Save ₹1,500/mo", "action": "Review."}
        ],
        "hidden_risks_and_predatory_clauses": [
            {"risk_name": "Auto-debit", "explanation": "Renews silently.", "severity": "MEDIUM"}
        ],
        "disclaimer": "Educational analysis. Not certified financial advice.",
    }

    def _live_call(self, payload):
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {
                    "candidates": [
                        {"content": {"parts": [{"text": json.dumps(payload)}]}}
                    ]
                }
                return AdvisorService.analyze_sanitized_statement(
                    "sanitized text",
                    {"health_score": 80, "monthly_leakage": 1500, "monthly_income": 82000},
                )

    def test_01_valid_answer_is_accepted(self):
        result = self._live_call(self.VALID_PAYLOAD)
        self.assertEqual(result["source"], "LIVE_GEMINI")
        self.assertTrue(result["is_ai_generated"])
        self.assertIn("model", result)

    def test_02_invalid_answers_are_discarded(self):
        broken = [
            {"plain_english_summary": "no other keys"},
            {**self.VALID_PAYLOAD, "top_actionable_wins": "not a list"},
            {**self.VALID_PAYLOAD, "plain_english_summary": ""},
            {**self.VALID_PAYLOAD, "top_actionable_wins": [{"no_title": 1}]},
        ]
        for payload in broken:
            result = self._live_call(payload)
            self.assertEqual(result["source"], "OFFLINE_RULE_BASED", msg=json.dumps(payload)[:80])
            self.assertFalse(result["is_ai_generated"])

    def test_03_amounts_outside_the_deterministic_metrics_force_offline_fallback(self):
        result = self._live_call(self.VALID_PAYLOAD)
        # ₹1,500 is a deterministic monetary metric, so it is verified.
        self.assertEqual(result["source"], "LIVE_GEMINI")
        self.assertTrue(result["numeric_claims_verified"])
        self.assertEqual(result["unverified_amount_claims"], [])

        invented = json.loads(json.dumps(self.VALID_PAYLOAD))
        invented["top_actionable_wins"][0]["impact_amount"] = "Save ₹9,999/mo"
        result = self._live_call(invented)
        # Unsupported rupee claims are rejected before the text reaches the UI.
        self.assertEqual(result["source"], "OFFLINE_RULE_BASED")
        self.assertFalse(result["is_ai_generated"])
        self.assertTrue(result["numeric_claims_verified"])
        self.assertEqual(result["unverified_amount_claims"], [])
        self.assertNotIn("9,999", json.dumps(result))

    def test_04_offline_fallback_quotes_no_invented_amounts(self):
        metrics = {
            "health_score": 80,
            "emergency_runway_months": 3.0,
            "recurring_commitments": {"monthly_commitments": 1990.0, "monthly_leakage": 649.0},
        }
        result = AdvisorService._generate_heuristic_response("sanitized", metrics)
        allowed = {80.0, 3.0, 1990.0, 649.0}
        for win in result["top_actionable_wins"]:
            for token in AdvisorService.AMOUNT_RE.findall(win["impact_amount"]):
                value = float(token.replace(",", ""))
                self.assertIn(value, allowed, msg=win["impact_amount"])

    def test_05_fallback_without_metrics_does_not_invent_a_health_score(self):
        result = AdvisorService._generate_heuristic_response("sanitized", {})
        self.assertNotIn("/100", result["plain_english_summary"])
        self.assertIn("No deterministic financial metrics", result["plain_english_summary"])

    def test_06_model_is_configurable_and_defaults_to_a_supported_flash_model(self):
        self.assertNotIn("2.0-flash", AdvisorService.get_model())
        with patch.dict("os.environ", {"GEMINI_MODEL": "synthetic-model-1"}):
            self.assertEqual(AdvisorService.get_model(), "synthetic-model-1")

    def test_07_no_secret_is_ever_logged_or_returned(self):
        result = AdvisorService._generate_heuristic_response("sanitized", {"health_score": 70})
        serialized = json.dumps(result)
        self.assertNotIn("GEMINI_API_KEY", serialized)
        self.assertNotIn("x-goog-api-key", serialized)


class AdvisorOfflineFallbackTests(TestCase):
    """
    Tests ensuring the AdvisorService and DocumentAnalyzeView accurately
    identify and label offline rule-based fallback insights without making
    unsupported AI claims.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.session, self.token = SecureSession.issue_session()
        ConsentAuditLog.objects.create(
            session_id=self.session.session_id,
            consent_version="v1.0",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

    def test_offline_fallback_when_api_key_not_set(self):
        """When GEMINI_API_KEY is not set, service must return labeled offline heuristic."""
        with patch.object(AdvisorService, "get_api_key", return_value=None):
            metrics = {
                "health_score": 72,
                "metrics": {"runway_months": 2.1},
            }
            res = AdvisorService.analyze_sanitized_statement(
                "2026-10-01 POS GROCERY 1200", metrics
            )

            # Strict Source & Labeling verification
            self.assertEqual(res.get("source"), "OFFLINE_RULE_BASED")
            self.assertFalse(res.get("is_ai_generated"))
            self.assertEqual(
                res.get("engine_label"), "Offline Rule-Based Financial Insights"
            )

            # Verify required structural fields
            self.assertIn("plain_english_summary", res)
            self.assertIn("top_actionable_wins", res)
            self.assertIn("hidden_risks_and_predatory_clauses", res)
            self.assertIn("disclaimer", res)

            # Must cite pre-computed deterministic metrics
            self.assertIn("72/100", res["plain_english_summary"])
            self.assertIn("2.1 months", res["plain_english_summary"])

    def test_offline_fallback_on_gemini_error(self):
        """When Gemini API call encounters network error or timeout, fallback is accurately labeled."""
        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post", side_effect=Exception("ConnectionRefused")):
                metrics = {"health_score": 60, "metrics": {"runway_months": 1.0}}
                res = AdvisorService.analyze_sanitized_statement("sanitized text", metrics)

                self.assertEqual(res.get("source"), "OFFLINE_RULE_BASED")
                self.assertFalse(res.get("is_ai_generated"))
                self.assertEqual(
                    res.get("engine_label"), "Offline Rule-Based Financial Insights"
                )

    def test_document_analyze_view_offline_labeling(self):
        """DocumentAnalyzeView returns explicit offline metadata when Gemini is unconfigured."""
        with patch.object(AdvisorService, "get_api_key", return_value=None):
            req = self.factory.post(
                "/api/v1/documents/analyze/",
                data={
                    "sanitized_text": "2026-10-01 POS GROCERY 1200",
                    "session_id": self.session.session_id,
                },
                format="json",
                HTTP_X_SESSION_TOKEN=self.token,
            )
            req.session = {}

            resp = DocumentAnalyzeView.as_view()(req)
            self.assertEqual(resp.status_code, 200)

            data = resp.data
            self.assertEqual(data.get("analysis_source"), "OFFLINE_RULE_BASED")
            self.assertFalse(data.get("is_ai_generated"))
            self.assertFalse(data.get("gemini_available"))
            self.assertEqual(
                data.get("engine_label"), "Offline Rule-Based Financial Insights"
            )
            self.assertIn(
                "analyzed strictly offline via local deterministic logic",
                data.get("privacy_guarantee", ""),
            )
            self.assertNotIn("LLM processed", data.get("privacy_guarantee", ""))

    def test_live_gemini_labeling_when_successful(self):
        """When live Gemini responds 200, it is labeled as Live Gemini AI Analysis."""
        mock_response = {
            "plain_english_summary": "Live AI summary from Gemini.",
            "top_actionable_wins": [],
            "hidden_risks_and_predatory_clauses": [],
            "disclaimer": "Live Gemini disclaimer.",
        }

        with patch.object(AdvisorService, "get_api_key", return_value="synthetic_test_key"):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": json.dumps(mock_response)}]
                            }
                        }
                    ]
                }

                res = AdvisorService.analyze_sanitized_statement(
                    "sanitized text", {"health_score": 80}
                )

                self.assertEqual(res.get("source"), "LIVE_GEMINI")
                self.assertTrue(res.get("is_ai_generated"))
                self.assertEqual(res.get("engine_label"), "Live Gemini AI Analysis")
