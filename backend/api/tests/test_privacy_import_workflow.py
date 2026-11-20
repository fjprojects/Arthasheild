"""
Comprehensive verification suite for the Privacy Inspector consent and import workflow.

Verifies the 8 core privacy, consent, and statement ingestion requirements:
1. Importing blocked when consent is withdrawn.
2. No transaction records created when consent is absent.
3. Preview Scrub redacts all supported PII fields.
4. Import with Consent stores only sanitized transaction data.
5. Audit Ledger reflects imported transactions.
6. Re-import of same synthetic statement triggers SHA-256 duplicate detection.
7. Network payloads and backend logs contain zero accidental raw PII.
8. Consent withdrawal after import enforces documented withdrawal behavior
   (blocks analysis/mutation, preserves audit trail, allows complete data shredding).
"""
import json
import logging
import re
import uuid
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    ConsentAuditLog,
    FinancialSnapshot,
    SecureSession,
    Transaction,
)
from api.tests.privacy_scan import response_leaks


class PrivacyImportWorkflowTests(TestCase):
    """
    End-to-end integration tests for the Privacy Inspector & Statement Import subsystem.
    """

    STATEMENT_URL = "/api/v1/data/parse-statement/"
    PREVIEW_URL = "/api/v1/privacy/sanitize-preview/"
    CONSENT_URL = "/api/v1/privacy/consent/"
    WITHDRAW_URL = "/api/v1/privacy/consent/withdraw/"
    OVERVIEW_URL = "/api/v1/insights/imported-overview/"
    CATEGORIZE_URL = "/api/v1/insights/categorize/"
    ANALYZE_URL = "/api/v1/documents/analyze/"
    BRIEFING_URL = "/api/v1/insights/evidence-briefing/"
    NUKE_URL = "/api/v1/privacy/nuke-data/"

    # Synthetic PII definitions
    RAW_PAN = "ABCDE1234F"
    RAW_AADHAAR = "1234 5678 9012"
    RAW_PHONE = "9876543210"
    RAW_EMAIL = "vikram.malhotra@bankdomain.com"
    RAW_CARD = "4111 2222 3333 4444"
    RAW_ACCOUNT = "998877665544"
    RAW_UPI = "sneha.kulkarni@okhdfcbank"
    RAW_NAME_1 = "Sneha Kulkarni"
    RAW_NAME_2 = "Vikram Malhotra"
    RAW_NAME_3 = "Sunita Rao"
    RAW_CUST_ID = "CUST-883920"
    RAW_ORDER_ID = "ORD-9824219"

    ALL_RAW_PII = [
        RAW_PAN,
        RAW_AADHAAR,
        RAW_PHONE,
        RAW_EMAIL,
        RAW_CARD,
        RAW_ACCOUNT,
        RAW_UPI,
        RAW_NAME_1,
        RAW_NAME_2,
        RAW_NAME_3,
        RAW_CUST_ID,
        RAW_ORDER_ID,
    ]

    # Specific financial identifiers and secrets that must never be stored raw
    RAW_FINANCIAL_PII = [
        RAW_PAN,
        RAW_AADHAAR,
        RAW_PHONE,
        RAW_EMAIL,
        RAW_CARD,
        RAW_ACCOUNT,
        RAW_UPI,
        RAW_CUST_ID,
        RAW_ORDER_ID,
    ]

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _create_session(self, prefix="workflow_test"):
        session_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
        _sess, token = SecureSession.issue_session(session_id)
        headers = {"HTTP_X_SESSION_TOKEN": token}
        return session_id, token, headers

    def _grant_consent_via_api(self, headers, version="v1.0-test"):
        res = self.client.post(
            self.CONSENT_URL,
            {
                "consent_version": version,
                "anonymized_processing_accepted": True,
                "no_credential_disclosure_acknowledged": True,
            },
            format="json",
            **headers,
        )
        self.assertEqual(res.status_code, 200)
        return res.json()

    def _withdraw_consent_via_api(self, headers):
        res = self.client.post(self.WITHDRAW_URL, {}, format="json", **headers)
        self.assertEqual(res.status_code, 200)
        return res.json()

    # -------------------------------------------------------------------------
    # 1. Verify importing is blocked when consent is withdrawn
    # -------------------------------------------------------------------------
    def test_01_import_blocked_when_consent_withdrawn(self):
        session_id, token, headers = self._create_session("req1")

        # Grant consent first
        self._grant_consent_via_api(headers)
        active_consent = ConsentAuditLog.objects.filter(
            session_id=session_id, is_active=True
        ).first()
        self.assertIsNotNone(active_consent)

        # Withdraw consent
        withdraw_res = self._withdraw_consent_via_api(headers)
        self.assertEqual(withdraw_res["status"], "CONSENT_WITHDRAWN")

        # Verify in DB that consent is inactive
        self.assertFalse(
            ConsentAuditLog.objects.filter(
                session_id=session_id, is_active=True
            ).exists()
        )

        # Attempt to import and persist
        statement_csv = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-04,POS STARBUCKS COFFEE,450.00,,50000.00\n"
        )
        res = self.client.post(
            self.STATEMENT_URL,
            {
                "raw_text": statement_csv,
                "format": "csv",
                "persist": "true",
            },
            format="json",
            **headers,
        )

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json().get("code"), "CONSENT_REQUIRED")
        self.assertEqual(
            Transaction.objects.filter(session_id=session_id).count(), 0
        )

    # -------------------------------------------------------------------------
    # 2. Verify no transaction records created when consent is absent
    # -------------------------------------------------------------------------
    def test_02_no_transaction_records_created_when_consent_absent(self):
        session_id, token, headers = self._create_session("req2")

        # Confirm no consent exists
        self.assertEqual(
            ConsentAuditLog.objects.filter(session_id=session_id).count(), 0
        )

        statement_csv = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-04,POS GROCERY STORE,1200.00,,48800.00\n"
            "2026-10-05,SALARY CREDIT,,50000.00,98800.00\n"
        )

        # Attempt persist with absent consent
        res = self.client.post(
            self.STATEMENT_URL,
            {
                "raw_text": statement_csv,
                "format": "csv",
                "persist": "true",
            },
            format="json",
            **headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json().get("code"), "CONSENT_REQUIRED")
        self.assertEqual(
            Transaction.objects.filter(session_id=session_id).count(), 0
        )

        # Non-persisted parse (preview mode) should return 200 but create 0 DB records
        res_preview = self.client.post(
            self.STATEMENT_URL,
            {
                "raw_text": statement_csv,
                "format": "csv",
                "persist": "false",
            },
            format="json",
            **headers,
        )
        self.assertEqual(res_preview.status_code, 200)
        self.assertIn("transactions", res_preview.json())
        self.assertEqual(len(res_preview.json()["transactions"]), 2)
        # Database must still have 0 records
        self.assertEqual(
            Transaction.objects.filter(session_id=session_id).count(), 0
        )

    # -------------------------------------------------------------------------
    # 3. Verify Preview Scrub redacts all supported PII fields
    # -------------------------------------------------------------------------
    def test_03_preview_scrub_redacts_all_supported_pii_fields(self):
        raw_input = (
            f"Account Holder: {self.RAW_NAME_3}\n"
            f"Beneficiary Name: {self.RAW_NAME_2}\n"
            f"Customer ID: {self.RAW_CUST_ID}\n"
            f"Account Number: {self.RAW_ACCOUNT}\n"
            f"Linked PAN: {self.RAW_PAN} and Aadhaar: {self.RAW_AADHAAR}\n"
            f"Card Number: {self.RAW_CARD}\n"
            f"Contact: {self.RAW_PHONE} Email: {self.RAW_EMAIL}\n"
            f"Paid via UPI to {self.RAW_UPI} Ref: {self.RAW_ORDER_ID}\n"
        )

        res = self.client.post(
            self.PREVIEW_URL,
            {"raw_text": raw_input},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()

        preview_text = data.get("sanitized_text_preview", "")
        self.assertTrue(len(preview_text) > 0)
        self.assertEqual(data.get("privacy_status"), "PII_STRIPPED_SERVER_BOUNDARY_ENFORCED")
        self.assertGreater(data.get("total_redactions_count", 0), 0)

        # Assert no raw sensitive tokens leak into the preview text or entire JSON
        json_blob = json.dumps(data)
        for sensitive in self.ALL_RAW_PII:
            self.assertNotIn(
                sensitive,
                preview_text,
                f"Preview text leaked sensitive token: {sensitive}",
            )
            self.assertNotIn(
                sensitive,
                json_blob,
                f"Response JSON payload leaked sensitive token: {sensitive}",
            )

        # Assert expected redaction placeholders are present in the scrubbed text
        expected_placeholders = [
            "[REDACTED_BENEFICIARY]",
            "[REDACTED_CUST_ID]",
            "[REDACTED_ACCOUNT]",
            "[REDACTED_PAN]",
            "[REDACTED_AADHAAR]",
            "[REDACTED_CARD]",
            "[REDACTED_PHONE]",
            "[REDACTED_EMAIL]",
            "[REDACTED_UPI_ID]",
        ]
        for placeholder in expected_placeholders:
            self.assertIn(
                placeholder,
                preview_text,
                f"Expected placeholder {placeholder} not found in scrubbed preview.",
            )

    # -------------------------------------------------------------------------
    # 4. Verify Import with Consent stores only sanitized transaction data
    # -------------------------------------------------------------------------
    def test_04_import_with_consent_stores_only_sanitized_data(self):
        session_id, token, headers = self._create_session("req4")
        self._grant_consent_via_api(headers)

        statement_csv = (
            "Date,Description,Debit,Credit,Balance\n"
            f"2026-10-04,UPI/Priya Sharma/{self.RAW_UPI}/{self.RAW_ORDER_ID},480.00,,74520.00\n"
            f"2026-10-05,TRANSFER TO A/C {self.RAW_ACCOUNT} MOB {self.RAW_PHONE},1500.00,,73020.00\n"
            f"2026-10-06,SALARY CREDIT ACCT 123456789012,,40000.00,113020.00\n"
        )

        res = self.client.post(
            self.STATEMENT_URL,
            {
                "raw_text": statement_csv,
                "format": "csv",
                "persist": "true",
            },
            format="json",
            **headers,
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("persistence", body)
        self.assertEqual(body["persistence"]["imported"], 3)
        self.assertEqual(body["persistence"]["skipped_duplicates"], 0)

        # Verify DB records
        txs = list(Transaction.objects.filter(session_id=session_id))
        self.assertEqual(len(txs), 3)

        for tx in txs:
            self.assertEqual(tx.source_type, Transaction.SOURCE_IMPORT)
            # Check normalized_merchant and any text fields for sensitive identifiers
            for sensitive in self.RAW_FINANCIAL_PII:
                self.assertNotIn(
                    sensitive,
                    tx.normalized_merchant,
                    f"Stored merchant leaked PII: {sensitive}",
                )
                self.assertNotIn(
                    sensitive,
                    tx.risk_note or "",
                    f"Stored risk_note leaked PII: {sensitive}",
                )

        # Verify that response payload enforces safe counterparty labels
        for tx_resp in body.get("transactions", []):
            self.assertNotIn("Priya Sharma", tx_resp["merchant"])
            self.assertNotIn(self.RAW_UPI, tx_resp["merchant"])
            self.assertNotIn(self.RAW_ACCOUNT, tx_resp["merchant"])

    # -------------------------------------------------------------------------
    # 5. Verify Audit Ledger reflects imported transactions
    # -------------------------------------------------------------------------
    def test_05_audit_ledger_reflects_imported_transactions(self):
        session_id, token, headers = self._create_session("req5")
        self._grant_consent_via_api(headers)

        statement_csv = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-01,POS NETFLIX SUBSCRIPTION,649.00,,49351.00\n"
            "2026-10-02,ELECTRICITY BILL PAYMENT,1850.00,,47501.00\n"
            "2026-10-03,SALARY CREDIT,,55000.00,102501.00\n"
        )
        import_res = self.client.post(
            self.STATEMENT_URL,
            {
                "raw_text": statement_csv,
                "format": "csv",
                "persist": "true",
            },
            format="json",
            **headers,
        )
        self.assertEqual(import_res.status_code, 200)

        # Query the Audit Ledger / Imported Overview endpoint
        overview_res = self.client.post(
            self.OVERVIEW_URL,
            {"session_id": session_id},
            format="json",
            **headers,
        )
        self.assertEqual(overview_res.status_code, 200)
        ledger_data = overview_res.json()

        self.assertTrue(ledger_data.get("has_imported_data"))
        self.assertEqual(ledger_data.get("transaction_count"), 3)

        ledger_txs = ledger_data.get("transactions", [])
        self.assertEqual(len(ledger_txs), 3)

        # Reconcile figures
        amounts = [float(tx["amount"]) for tx in ledger_txs]
        self.assertIn(649.0, amounts)
        self.assertIn(1850.0, amounts)
        self.assertIn(55000.0, amounts)

        # Statement period verification
        period = ledger_data.get("statement_period", {})
        self.assertEqual(period.get("start_date"), "2026-10-01")
        self.assertEqual(period.get("end_date"), "2026-10-03")

    # -------------------------------------------------------------------------
    # 6. Re-import same synthetic statement and verify SHA-256 duplicate detection
    # -------------------------------------------------------------------------
    def test_06_reimport_statement_sha256_duplicate_detection(self):
        session_id, token, headers = self._create_session("req6")
        self._grant_consent_via_api(headers)

        statement_csv = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-01,SWIGGY BANGALORE,350.00,,49650.00\n"
            "2026-10-02,UBER INDIA RIDES,220.00,,49430.00\n"
            "2026-10-02,UBER INDIA RIDES,220.00,,49210.00\n"  # Legitimate duplicate in same statement
        )

        # Initial import
        res1 = self.client.post(
            self.STATEMENT_URL,
            {
                "raw_text": statement_csv,
                "format": "csv",
                "persist": "true",
            },
            format="json",
            **headers,
        )
        self.assertEqual(res1.status_code, 200)
        p1 = res1.json().get("persistence", {})
        self.assertEqual(p1.get("imported"), 3)
        self.assertEqual(p1.get("skipped_duplicates"), 0)

        initial_count = Transaction.objects.filter(session_id=session_id).count()
        self.assertEqual(initial_count, 3)

        # Verify fingerprints exist and are 64-char SHA-256 hex strings
        fps = list(
            Transaction.objects.filter(session_id=session_id).values_list(
                "fingerprint", flat=True
            )
        )
        for fp in fps:
            self.assertTrue(bool(re.match(r"^[0-9a-f]{64}$", fp)))
        # The two identical Uber transactions have distinct occurrence hashes
        self.assertEqual(len(set(fps)), 3)

        # Re-import the exact same statement
        res2 = self.client.post(
            self.STATEMENT_URL,
            {
                "raw_text": statement_csv,
                "format": "csv",
                "persist": "true",
            },
            format="json",
            **headers,
        )
        self.assertEqual(res2.status_code, 200)
        p2 = res2.json().get("persistence", {})
        self.assertEqual(p2.get("imported"), 0)
        self.assertEqual(p2.get("skipped_duplicates"), 3)

        # DB count must remain exactly 3
        after_count = Transaction.objects.filter(session_id=session_id).count()
        self.assertEqual(after_count, 3)

    # -------------------------------------------------------------------------
    # 7. Inspect network payloads and backend logs for accidental raw PII exposure
    # -------------------------------------------------------------------------
    def test_07_network_payloads_and_logs_leak_no_raw_pii(self):
        session_id, token, headers = self._create_session("req7")
        self._grant_consent_via_api(headers)

        class LogCaptureHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records = []

            def emit(self, record):
                self.records.append(self.format(record))

        logger = logging.getLogger("api")
        log_capture = LogCaptureHandler()
        logger.addHandler(log_capture)

        try:
            # 1. Preview endpoint payload inspection
            raw_preview = (
                f"Account Holder: {self.RAW_NAME_3}\n"
                f"PAN: {self.RAW_PAN} AADHAAR: {self.RAW_AADHAAR}\n"
                f"Phone: {self.RAW_PHONE} Email: {self.RAW_EMAIL}\n"
                f"A/C: {self.RAW_ACCOUNT} Card: {self.RAW_CARD}\n"
            )
            res_preview = self.client.post(
                self.PREVIEW_URL,
                {"raw_text": raw_preview},
                format="json",
            )
            self.assertEqual(res_preview.status_code, 200)
            preview_json = json.dumps(res_preview.json())

            # 2. Statement parse payload inspection
            statement_csv = (
                "Date,Description,Debit,Credit,Balance\n"
                f"2026-10-04,UPI/{self.RAW_NAME_1}/{self.RAW_UPI}/{self.RAW_ORDER_ID},480.00,,74520.00\n"
            )
            res_parse = self.client.post(
                self.STATEMENT_URL,
                {
                    "raw_text": statement_csv,
                    "format": "csv",
                    "persist": "true",
                },
                format="json",
                **headers,
            )
            self.assertEqual(res_parse.status_code, 200)
            parse_json = json.dumps(res_parse.json())

            # 3. Overview payload inspection
            res_overview = self.client.post(
                self.OVERVIEW_URL,
                {"session_id": session_id},
                format="json",
                **headers,
            )
            self.assertEqual(res_overview.status_code, 200)
            overview_json = json.dumps(res_overview.json())

            # 4. Check for leaks in all response payloads
            for payload_str, endpoint_name in [
                (preview_json, "SanitizePreview"),
                (parse_json, "ParseStatement"),
                (overview_json, "ImportedOverview"),
            ]:
                for sensitive in self.ALL_RAW_PII:
                    self.assertNotIn(
                        sensitive,
                        payload_str,
                        f"Network payload for {endpoint_name} leaked {sensitive}",
                    )

            # 5. Check backend log records
            joined_logs = "\n".join(log_capture.records)
            for sensitive in self.ALL_RAW_PII:
                self.assertNotIn(
                    sensitive,
                    joined_logs,
                    f"Backend logs leaked sensitive value: {sensitive}",
                )

        finally:
            logger.removeHandler(log_capture)

    # -------------------------------------------------------------------------
    # 8. Test consent withdrawal after import and verify documented behavior
    # -------------------------------------------------------------------------
    def test_08_consent_withdrawal_after_import_documented_behavior(self):
        session_id, token, headers = self._create_session("req8")
        self._grant_consent_via_api(headers)

        # 1. Import transactions
        statement_csv = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-01,SWIGGY,350.00,,49650.00\n"
            "2026-10-02,AMAZON INDIA,1200.00,,48450.00\n"
        )
        self.client.post(
            self.STATEMENT_URL,
            {
                "raw_text": statement_csv,
                "format": "csv",
                "persist": "true",
            },
            format="json",
            **headers,
        )
        self.assertEqual(
            Transaction.objects.filter(session_id=session_id).count(), 2
        )

        # 2. Withdraw consent
        withdraw_res = self._withdraw_consent_via_api(headers)
        self.assertEqual(withdraw_res["status"], "CONSENT_WITHDRAWN")

        # Verify ConsentAuditLog is inactive and has withdrawn_at timestamp
        consent_record = (
            ConsentAuditLog.objects.filter(session_id=session_id)
            .order_by("-consented_at")
            .first()
        )
        self.assertFalse(consent_record.is_active)
        self.assertIsNotNone(consent_record.withdrawn_at)

        # 3. Subsequent mutation/import is blocked
        import_blocked = self.client.post(
            self.STATEMENT_URL,
            {
                "raw_text": (
                    "Date,Description,Debit,Credit,Balance\n"
                    "2026-10-03,NETFLIX,649.00,,47801.00\n"
                ),
                "format": "csv",
                "persist": "true",
            },
            format="json",
            **headers,
        )
        self.assertEqual(import_blocked.status_code, 403)
        self.assertEqual(import_blocked.json().get("code"), "CONSENT_REQUIRED")

        # 4. Intelligence endpoints requiring active consent are blocked
        for endpoint, url, payload in [
            ("ImportedOverview", self.OVERVIEW_URL, {"session_id": session_id}),
            ("EvidenceBriefing", self.BRIEFING_URL, {"session_id": session_id}),
            ("Categorization", self.CATEGORIZE_URL, {"session_id": session_id}),
            ("DocumentAnalyze", self.ANALYZE_URL, {"document_text": "Scrubbed text", "session_id": session_id}),
        ]:
            gated_res = self.client.post(
                url,
                payload,
                format="json",
                **headers,
            )
            self.assertEqual(
                gated_res.status_code,
                403,
                f"{endpoint} should return 403 after consent withdrawal",
            )
            self.assertEqual(gated_res.json().get("code"), "CONSENT_REQUIRED")

        # 5. Stored transactions remain preserved for audit trail prior to shredding
        self.assertEqual(
            Transaction.objects.filter(session_id=session_id).count(), 2
        )

        # 6. Execute 1-Click Data Shredder (Nuke Data)
        nuke_res = self.client.post(self.NUKE_URL, {}, format="json", **headers)
        self.assertEqual(nuke_res.status_code, 200)
        self.assertEqual(nuke_res.json().get("status"), "HARD_PURGE_SUCCESSFUL")

        # Verify complete erasure
        self.assertEqual(
            Transaction.objects.filter(session_id=session_id).count(), 0
        )
        self.assertEqual(
            FinancialSnapshot.objects.filter(session_id=session_id).count(), 0
        )
        self.assertEqual(
            ConsentAuditLog.objects.filter(session_id=session_id).count(), 0
        )
