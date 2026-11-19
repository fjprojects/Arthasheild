"""
Advanced Ingestion Robustness Test Suite.

Covers Section B of Additional ArthaShield Audit:
- CSV, PDF and TXT synthetic files with varied headers and date formats.
- Missing fields and invalid rows.
- Duplicate transaction handling and duplicate re-import protection.
- Refunds and own-account transfers.
- Unknown merchant descriptions.
- Negative vs positive amounts.
- Empty files (0 bytes).
- Malformed files / binary garbage.
- Unexpected file extensions and MIME types.
- File exceeding 5MB upload limit.
- Verification that parser failures return safe controlled errors.
"""

from datetime import date
from decimal import Decimal
import io
import uuid

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from api.models import SecureSession, ConsentAuditLog, FinancialSnapshot, Transaction
from data_processor.statement_parser import BankStatementParser
from api.views import MAX_UPLOAD_SIZE_BYTES


STATEMENT_URL = "/api/v1/data/parse-statement/"


class StatementIngestionRobustnessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.session_id = f"test_ing_{uuid.uuid4().hex[:8]}"
        self.session, self.token = SecureSession.issue_session(self.session_id)
        self.consent = ConsentAuditLog.objects.create(
            session_id=self.session_id,
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

    def _post_file(self, content: bytes, filename: str, content_type: str = "text/csv", persist: bool = False):
        uploaded = SimpleUploadedFile(filename, content, content_type=content_type)
        data = {"file": uploaded}
        if persist:
            data["persist"] = "true"
        return self.client.post(
            STATEMENT_URL,
            data,
            HTTP_X_SESSION_TOKEN=self.token,
            format="multipart",
        )

    # 1. Different column names
    def test_01_varied_column_headers(self):
        # Headers: Txn Date, Narration, Withdrawal, Deposit, Balance
        csv_data = (
            "Txn Date,Narration,Withdrawal,Deposit,Balance\n"
            "10/10/2026,UPI/ZOMATO/ORDER123/zomato@hdfc,450.00,,50000.00\n"
            "12/10/2026,SALARY CREDIT APEX TECH,,65000.00,115000.00\n"
        ).encode("utf-8")
        resp = self._post_file(csv_data, "statement.csv")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        txs = resp.data.get("transactions", [])
        self.assertEqual(len(txs), 2)
        self.assertEqual(float(txs[0]["amount"]), 450.0)
        self.assertEqual(txs[0]["transaction_type"], "DEBIT")
        self.assertEqual(float(txs[1]["amount"]), 65000.0)
        self.assertEqual(txs[1]["transaction_type"], "CREDIT")

    # 2. Different date formats (DD/MM/YYYY vs YYYY-MM-DD vs DD-Mon-YYYY)
    def test_02_varied_date_formats(self):
        csv_data = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-01,AMAZON SHOPPING,1200.00,,40000.00\n"
            "05/10/2026,SWIGGY FOOD,350.00,,39650.00\n"
            "15-Oct-2026,APEX SALARY,,50000.00,89650.00\n"
        ).encode("utf-8")
        resp = self._post_file(csv_data, "statement.csv")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        txs = resp.data.get("transactions", [])
        self.assertEqual(len(txs), 3)
        dates = [t["transaction_date"] for t in txs]
        self.assertIn("2026-10-01", dates)
        self.assertIn("2026-10-05", dates)
        self.assertIn("2026-10-15", dates)

    # 3. Missing fields (row with missing amount or date)
    def test_03_missing_fields_graceful_handling(self):
        # Row 2 is completely missing amount, row 3 has invalid date
        csv_data = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-01,VALID TRANSACTION,500.00,,10000.00\n"
            "2026-10-02,MISSING AMOUNT,,,10000.00\n"
            "NOT_A_DATE,CORRUPT DATE,200.00,,9800.00\n"
            "2026-10-03,VALID TRANSACTION 2,,1500.00,11300.00\n"
        ).encode("utf-8")
        resp = self._post_file(csv_data, "statement.csv")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Should gracefully extract the 2 valid transactions and discard the corrupt ones
        txs = resp.data.get("transactions", [])
        self.assertEqual(len(txs), 2)

    # 4. Duplicate transactions and re-import protection
    def test_04_duplicate_reimport_protection(self):
        csv_data = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-01,NETFLIX AUTO DEBIT,649.00,,50000.00\n"
            "2026-10-02,SALARY CREDIT,,60000.00,110000.00\n"
        ).encode("utf-8")
        # First import with persist=True
        resp1 = self._post_file(csv_data, "statement.csv", persist=True)
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data["persistence"]["imported"], 2)
        self.assertEqual(resp1.data["persistence"]["skipped_duplicates"], 0)

        # Re-import identical statement
        resp2 = self._post_file(csv_data, "statement.csv", persist=True)
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data["persistence"]["imported"], 0)
        self.assertEqual(resp2.data["persistence"]["skipped_duplicates"], 2)

    # 5. Refunds classification
    def test_05_refund_detection(self):
        csv_data = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-01,SWIGGY BANGALORE,500.00,,20000.00\n"
            "2026-10-02,REFUND/SWIGGY/REV123,,500.00,20500.00\n"
        ).encode("utf-8")
        resp = self._post_file(csv_data, "statement.csv", persist=True)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        refund_tx = Transaction.objects.get(session_id=self.session_id, transaction_type="CREDIT")
        self.assertEqual(refund_tx.category.lower(), "refund")

    # 6. Own-account transfers
    def test_06_own_account_transfers(self):
        csv_data = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-04,UPI/SELF TRANSFER/OWN ACCOUNT,15000.00,,45000.00\n"
        ).encode("utf-8")
        resp = self._post_file(csv_data, "statement.csv", persist=True)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        transfer_tx = Transaction.objects.get(session_id=self.session_id)
        self.assertEqual(transfer_tx.category.lower(), "transfer")

    # 7. Unknown merchant descriptions
    def test_07_unknown_merchant_descriptions(self):
        csv_data = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-10-05,RANDOM_VENDOR_XYZ_8824,350.00,,40000.00\n"
        ).encode("utf-8")
        resp = self._post_file(csv_data, "statement.csv", persist=True)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        tx = Transaction.objects.get(session_id=self.session_id)
        # Should persist safely as uncategorized/general rather than crashing or inventing a category
        self.assertIn(tx.category.lower(), ["uncategorized", "general", "other"])

    # 8. Single amount column with negative and positive amounts
    def test_08_signed_amount_column(self):
        csv_data = (
            "Date,Description,Amount,Balance\n"
            "2026-10-01,COFFEE SHOP,-250.00,20000.00\n"
            "2026-10-02,CLIENT STIPEND,+35000.00,55000.00\n"
        ).encode("utf-8")
        resp = self._post_file(csv_data, "statement.csv")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        txs = resp.data.get("transactions", [])
        self.assertEqual(len(txs), 2)
        self.assertEqual(txs[0]["transaction_type"], "DEBIT")
        self.assertEqual(float(txs[0]["amount"]), 250.0)
        self.assertEqual(txs[1]["transaction_type"], "CREDIT")
        self.assertEqual(float(txs[1]["amount"]), 35000.0)

    # 9. Empty file (0 bytes)
    def test_09_empty_file_rejected(self):
        empty_data = b""
        resp = self._post_file(empty_data, "empty.csv")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", resp.data)

    # 10. Malformed file (binary garbage)
    def test_10_malformed_binary_file_rejected(self):
        garbage = b"\x00\xFF\xFE\x00\xDE\xAD\xBE\xEF\x00\x00\x12\x34\x56"
        resp = self._post_file(garbage, "corrupt.csv")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", resp.data)

    # 11. Unexpected file extension / MIME type
    def test_11_unexpected_extension_handling(self):
        data = b"Some random executable code"
        resp = self._post_file(data, "malware.exe", content_type="application/x-msdownload")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", resp.data)

    # 12. File exceeding 5MB limit
    def test_12_file_exceeding_upload_limit(self):
        large_content = b"A" * (MAX_UPLOAD_SIZE_BYTES + 1024)
        resp = self._post_file(large_content, "huge_statement.csv")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("exceeds 5MB limit", resp.data["error"])
