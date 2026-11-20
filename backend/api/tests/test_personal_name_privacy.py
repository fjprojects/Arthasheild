"""
Regression tests: personal-name privacy detection, merchant preservation, and AI payload safety.

Phase 3 requirements:
- Detect and protect unlabelled person-like names in transaction narration (e.g. 'Paid to Rakesh Sharma').
- Preserve legitimate merchant names where distinguishable (e.g. 'Paid to SWIGGY', 'Paid to AMAZON').
- Avoid blindly redacting all capitalized phrases.
- Ensure uncertain personal information is not sent to external AI processing.
- Use a safe failure state if sanitization cannot confidently protect the payload.
- Never expose raw narration unnecessarily through APIs or logs.
- Keep existing account, PAN, phone, email, IFSC, UPI and customer-ID masking intact.
Synthetic data only.
"""
from django.test import TestCase

from sanitizer.services import SanitizerService
from advisor.services import AdvisorService


class PersonalNamePrivacyTests(TestCase):
    def test_paid_to_personal_name_is_redacted(self):
        raw = "Paid to Rakesh Sharma"
        res = SanitizerService.sanitize(raw)
        self.assertNotIn("Rakesh Sharma", res["sanitized_text"])
        self.assertIn("[REDACTED_BENEFICIARY]", res["sanitized_text"])
        self.assertTrue(any(r["type"] == "PERSON_NAME" for r in res["redactions"]))

    def test_transfer_to_personal_name_is_redacted(self):
        raw = "Transfer to Amit Kumar for dinner"
        res = SanitizerService.sanitize(raw)
        self.assertNotIn("Amit Kumar", res["sanitized_text"])
        self.assertIn("[REDACTED_BENEFICIARY]", res["sanitized_text"])

    def test_honorific_personal_name_is_redacted(self):
        raw = "Consultation Dr. Priya Patel clinic visit"
        res = SanitizerService.sanitize(raw)
        self.assertNotIn("Priya Patel", res["sanitized_text"])
        self.assertIn("[REDACTED_BENEFICIARY]", res["sanitized_text"])

    def test_upi_narration_with_personal_name_is_redacted(self):
        raw = "UPI/Sunita Rao/rent_share"
        res = SanitizerService.sanitize(raw)
        self.assertNotIn("Sunita Rao", res["sanitized_text"])
        self.assertIn("[REDACTED_BENEFICIARY]", res["sanitized_text"])

    def test_legitimate_merchant_names_are_preserved(self):
        """Recognized commercial merchants must NOT be redacted as personal names."""
        merchants = [
            "Paid to SWIGGY",
            "Paid to AMAZON",
            "Payment to Netflix Subscription",
            "Paid to Apollo Pharmacy",
            "Bill Paid to BESCOM Electricity",
            "Paid to BigBasket Grocery",
            "Paid to Uber Taxi",
        ]
        for narration in merchants:
            res = SanitizerService.sanitize(narration)
            self.assertEqual(res["total_redactions_count"], 0, msg=f"Wrongly redacted: {narration}")
            self.assertEqual(res["sanitized_text"], narration)

    def test_mixed_identifiers_all_redacted_together(self):
        """Mixed narration with person name, account, IFSC, and phone."""
        raw = "Paid to Rakesh Sharma A/C 987654321012 IFSC HDFC0001234 mob +91 9876543210"
        res = SanitizerService.sanitize(raw)
        self.assertNotIn("Rakesh Sharma", res["sanitized_text"])
        self.assertNotIn("987654321012", res["sanitized_text"])
        self.assertNotIn("HDFC0001234", res["sanitized_text"])
        self.assertNotIn("9876543210", res["sanitized_text"])
        self.assertIn("[REDACTED_BENEFICIARY]", res["sanitized_text"])
        self.assertIn("[REDACTED_ACCOUNT]", res["sanitized_text"])
        self.assertIn("[REDACTED_IFSC]", res["sanitized_text"])
        self.assertIn("[REDACTED_PHONE]", res["sanitized_text"])

    def test_multiline_narration_sanitizes_reliably(self):
        raw = (
            "Statement Entry 1:\n"
            "Paid to Rakesh Sharma INR 5000\n"
            "Statement Entry 2:\n"
            "Paid to SWIGGY INR 480\n"
        )
        res = SanitizerService.sanitize(raw)
        self.assertNotIn("Rakesh Sharma", res["sanitized_text"])
        self.assertIn("SWIGGY", res["sanitized_text"])

    def test_safe_log_str_never_exposes_personal_name(self):
        text = "Debug narration: Paid to Rakesh Sharma"
        safe = SanitizerService.safe_log_str(text)
        self.assertNotIn("Rakesh Sharma", safe)
        self.assertIn("[REDACTED_BENEFICIARY]", safe)

    def test_advisor_payload_safety_fallback_on_unscrubbed_pii(self):
        """Advisor safely falls back to local heuristics if outbound payload has raw identifiers."""
        computed_metrics = {"savings_rate": 20, "living_costs": 15000}
        # Call analyze_sanitized_statement with an unmasked phone number
        resp = AdvisorService.analyze_sanitized_statement(
            "Customer phone is 9876543210",
            computed_metrics
        )
        # Verify it falls back safely without raising an unhandled exception
        self.assertIsNotNone(resp)
        self.assertIn("plain_english_summary", resp)
