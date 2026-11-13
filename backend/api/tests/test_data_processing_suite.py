import uuid
from decimal import Decimal
from datetime import date
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory

from data_processor.models import NormalizedTransaction
from data_processor.normalizer import TransactionNormalizer
from data_processor.statement_parser import BankStatementParser
from data_processor.sms_parser import BankSmsParser
from sanitizer.services import SanitizerService
from api.models import ConsentAuditLog, SecureSession
from api.views import (
    ParseStatementView,
    ParseSmsView,
    SanitizePreviewView,
    DocumentAnalyzeView,
    PersonaListView,
    SelectPersonaView,
    SimulateEmiView,
    NukeDataView,
    ConsentAuditView
)

SYNTHETIC_PDF_BYTES = b'''%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 200 >> stream
BT
/F1 12 Tf
50 700 Td
(Account Statement - Apex National Bank) Tj
0 -20 Td
(Date,Description,Debit,Credit,Balance) Tj
0 -20 Td
(2026-10-02,ACH CRED CLIENT GLOBAL TECH STIPEND,,45000.00,45000.00) Tj
0 -20 Td
(2026-10-04,UPI/SWIGGY/ORDER_9824219,480.00,,40320.00) Tj
ET
endstream
endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000236 00000 n 
0000000488 00000 n 
trailer << /Size 6 /Root 1 0 R >>
startxref
567
%%EOF
'''


class DataProcessingSuiteTests(TestCase):
    """Wraps Tasks 1 through 16 from Phase 1 data processing into standard Django TestCase."""

    def setUp(self):
        self.factory = APIRequestFactory()

    def test_task_01_valid_csv_parsing(self):
        csv_text = """Account Statement - Apex National Bank
Account Holder: Rohit Ramesh Verma
Account Number: 4821-9988-1200-5541
IFSC Code: APEX0001234
Date,Description,Debit,Credit,Balance
2026-10-02,ACH CRED CLIENT GLOBAL TECH STIPEND,,45000.00,45000.00
2026-10-03,POS ADOBE SYSTEMS RENEWAL INT US-882194,4200.00,,40800.00
2026-10-04,UPI/SWIGGY/ORDER_9824219/swiggy@icici,480.00,,40320.00
"""
        res = BankStatementParser.parse_csv_text(csv_text)
        self.assertEqual(len(res.transactions), 3)
        self.assertEqual(res.total_debits, Decimal('4680.00'))
        self.assertEqual(res.total_credits, Decimal('45000.00'))
        self.assertEqual(res.account_info.get('masked_account_number'), 'XX..5541')

    def test_task_02_valid_pdf_parsing(self):
        res = BankStatementParser.parse_pdf_bytes(SYNTHETIC_PDF_BYTES)
        self.assertEqual(len(res.transactions), 2)
        self.assertEqual(res.transactions[0].transaction_type, 'CREDIT')
        self.assertEqual(res.transactions[1].transaction_type, 'DEBIT')
        self.assertEqual(res.transactions[0].amount, Decimal('45000.00'))
        self.assertEqual(res.transactions[1].amount, Decimal('480.00'))

    def test_task_03_valid_txt_parsing(self):
        txt_content = """Date|Description|Amount|Type
2026-10-10|UPI/CHAIPOINT/EVENING|120.00|DEBIT
2026-10-15|NEFT CRED APEX STUDIOS|40000.00|CREDIT
"""
        res = BankStatementParser.parse_txt_bytes(txt_content.encode('utf-8'))
        self.assertEqual(len(res.transactions), 2)
        self.assertEqual(res.transactions[0].amount, Decimal('120.00'))
        self.assertEqual(res.transactions[1].amount, Decimal('40000.00'))

    def test_task_04_invalid_corrupted_file_rejection(self):
        corrupted_pdf = b"%PDF-1.4\ncorrupted_random_garbage_content_without_xref"
        with self.assertRaises(ValueError):
            BankStatementParser.parse_pdf_bytes(corrupted_pdf)
        with self.assertRaises(ValueError):
            BankStatementParser.parse_file(SimpleUploadedFile("empty.csv", b""), "empty.csv")

    def test_task_05_oversized_file_rejection(self):
        large_payload = b"0" * (5 * 1024 * 1024 + 1024)
        with self.assertRaises(ValueError) as ctx:
            BankStatementParser.parse_file(SimpleUploadedFile("large.csv", large_payload), "large.csv")
        self.assertIn("exceeds maximum allowed limit", str(ctx.exception))

    def test_task_06_indian_date_and_amount_handling(self):
        d1 = TransactionNormalizer.parse_date("04/10/2026")
        d2 = TransactionNormalizer.parse_date("12-Oct-26")
        d3 = TransactionNormalizer.parse_date("2026-10-15")
        a1, _ = TransactionNormalizer.parse_amount("1,25,000.50")
        a2, _ = TransactionNormalizer.parse_amount("INR 4,200.00")
        a3, dir3 = TransactionNormalizer.parse_amount("Rs. 5,735.00 Dr")
        a4, dir4 = TransactionNormalizer.parse_amount("45000.00 Cr")
        a5, dir5 = TransactionNormalizer.parse_amount("(1,500.00)")
        self.assertEqual(d1, date(2026, 10, 4))
        self.assertEqual(d2, date(2026, 10, 12))
        self.assertEqual(d3, date(2026, 10, 15))
        self.assertEqual(a1, Decimal('125000.50'))
        self.assertEqual(a2, Decimal('4200.00'))
        self.assertEqual(a3, Decimal('5735.00'))
        self.assertEqual(dir3, 'DEBIT')
        self.assertEqual(a4, Decimal('45000.00'))
        self.assertEqual(dir4, 'CREDIT')
        self.assertEqual(a5, Decimal('1500.00'))
        self.assertEqual(dir5, 'DEBIT')

    def test_task_07_debit_credit_identification(self):
        row_sep = ["2026-10-05", "PHONE EMI", "", "5735.00", "34585.00"]
        col_map_sep = {"date": 0, "description": 1, "credit": 2, "debit": 3, "balance": 4}
        tx_sep = BankStatementParser._parse_single_row(row_sep, col_map_sep, "Row 1", "CSV")

        row_single = ["2026-10-10", "INTERNSHIP STIPEND", "8000.00 Cr", "12150.00"]
        col_map_single = {"date": 0, "description": 1, "amount": 2, "balance": 3}
        tx_single = BankStatementParser._parse_single_row(row_single, col_map_single, "Row 2", "CSV")

        self.assertIsNotNone(tx_sep)
        self.assertEqual(tx_sep.transaction_type, 'DEBIT')
        self.assertEqual(tx_sep.amount, Decimal('5735.00'))
        self.assertIsNotNone(tx_single)
        self.assertEqual(tx_single.transaction_type, 'CREDIT')
        self.assertEqual(tx_single.amount, Decimal('8000.00'))

    def test_task_08_upi_and_indian_bank_sms_parsing(self):
        sms_hdfc = "Dear Customer, INR 480.00 is debited from A/C **4821 on 04-OCT-26 to SWIGGY. Ref: 9824219. Avl Bal: INR 40,320.00"
        sms_sbi = "Your A/C 98765432101 debited by Rs.1200.00 on 12Oct26 transfer to AMAZON Ref No 6288192837. Avl Bal: Rs.34585.00"
        sms_axis = "INR 1,250.00 debited from Axis Bank A/c ending 4491 on 12-10-2026 14:30:15 at FIGMA. UPI Ref 44910283. Bal: INR 31,835.00"
        sms_credit = "Salary of INR 75,000.00 credited to A/C **9104 on 01-OCT-26 by GLOBEX CORP. Info: NEFT-GLOBEX-123. Avl Bal: INR 1,13,400.00"

        p_hdfc = BankSmsParser.parse_sms(sms_hdfc)
        p_sbi = BankSmsParser.parse_sms(sms_sbi)
        p_axis = BankSmsParser.parse_sms(sms_axis)
        p_cred = BankSmsParser.parse_sms(sms_credit)

        self.assertTrue(p_hdfc.is_valid)
        self.assertEqual(p_hdfc.transaction.amount, Decimal('480.00'))
        self.assertEqual(p_hdfc.transaction.transaction_type, 'DEBIT')

        self.assertTrue(p_sbi.is_valid)
        self.assertEqual(p_sbi.transaction.amount, Decimal('1200.00'))
        self.assertEqual(p_sbi.transaction.reference_id, '6288192837')

        self.assertTrue(p_axis.is_valid)
        self.assertEqual(p_axis.transaction.amount, Decimal('1250.00'))
        self.assertEqual(p_axis.transaction.merchant, 'Figma')

        self.assertTrue(p_cred.is_valid)
        self.assertEqual(p_cred.transaction.amount, Decimal('75000.00'))
        self.assertEqual(p_cred.transaction.transaction_type, 'CREDIT')

    def test_task_09_ambiguous_non_transaction_sms_rejection(self):
        otp_sms = "Your OTP for login is 884920. Do not share with anyone."
        promo_sms = "Pre-approved loan up to 5 Lakhs! Click now bit.ly/bankloan"
        bill_sms = "Your credit card statement generated. Total due Rs. 14,200.00"
        bal_sms = "Your available balance for A/C *4821 is Rs.54,200.00 as on 31-Oct-26."

        self.assertFalse(BankSmsParser.parse_sms(otp_sms).is_valid)
        self.assertFalse(BankSmsParser.parse_sms(promo_sms).is_valid)
        self.assertFalse(BankSmsParser.parse_sms(bill_sms).is_valid)
        self.assertFalse(BankSmsParser.parse_sms(bal_sms).is_valid)

    def test_task_10_duplicate_detection_deduplication(self):
        tx_a = NormalizedTransaction("", date(2026, 10, 4), "SWIGGY ORDER", Decimal('480.00'), "DEBIT", "SMS", reference_id="9824219")
        tx_b = NormalizedTransaction("", date(2026, 10, 4), "SWIGGY ORDER DUP", Decimal('480.00'), "DEBIT", "SMS", reference_id="9824219")
        tx_c = NormalizedTransaction("", date(2026, 10, 5), "AMAZON PURCHASE", Decimal('1500.00'), "DEBIT", "SMS", reference_id="882194")
        uniques, dup_count = TransactionNormalizer.deduplicate_transactions([tx_a, tx_b, tx_c])
        self.assertEqual(len(uniques), 2)
        self.assertEqual(dup_count, 1)

    def test_task_11_nine_field_normalization(self):
        norm = TransactionNormalizer.normalize_transaction(
            raw_date="04-OCT-2026",
            raw_description="UPI/SWIGGY/ORDER_9824219/swiggy@icici",
            amount="480.00",
            transaction_type="DEBIT",
            source="SMS_ALERT",
            reference_id="9824219",
            available_balance="40320.00",
            currency="INR"
        )
        self.assertNotEqual(norm.transaction_id, "")
        self.assertEqual(norm.transaction_date, date(2026, 10, 4))
        self.assertEqual(norm.description, "UPI/SWIGGY/ORDER_9824219/swiggy@icici")
        self.assertEqual(norm.amount, Decimal('480.00'))
        self.assertEqual(norm.transaction_type, "DEBIT")
        self.assertEqual(norm.source, "SMS_ALERT")
        self.assertEqual(norm.merchant, "Swiggy")
        self.assertEqual(norm.reference_id, "9824219")
        self.assertEqual(norm.currency, "INR")

    def test_task_12_decimal_precision_math(self):
        amounts = [Decimal('0.10'), Decimal('0.20'), Decimal('0.30')]
        total = sum(amounts)
        self.assertEqual(total, Decimal('0.60'))
        self.assertNotEqual(0.1 + 0.2, 0.3)

    def test_task_13_pii_masking_indian_formats(self):
        pii_text = (
            "Account Holder: Rohit Ramesh Verma\n"
            "Customer ID: CUST-884920\n"
            "PAN: ABCDE1234F\n"
            "Aadhaar: 1234 5678 9012\n"
            "Account Number: 4821-9988-1200-5541\n"
            "Card: 4821 9988 1200 5541\n"
            "Amex: 3782-822456-91006\n"
            "Phone: +91-9876543210\n"
            "Email: rohit.verma.freelance@gmail.com\n"
            "UPI: rohit@okaxis\n"
            "IFSC: APEX0001234\n"
            "Passport: Z1234567\n"
            "Voter: ABC1234567\n"
            "Beneficiary Name: Priya Sharma"
        )
        san_res = SanitizerService.sanitize(pii_text)
        san_txt = san_res["sanitized_text"]
        self.assertNotIn("Rohit Ramesh Verma", san_txt)
        self.assertNotIn("ABCDE1234F", san_txt)
        self.assertNotIn("1234 5678 9012", san_txt)
        self.assertNotIn("4821-9988-1200-5541", san_txt)
        self.assertNotIn("9876543210", san_txt)
        self.assertNotIn("rohit.verma.freelance@gmail.com", san_txt)
        self.assertNotIn("rohit@okaxis", san_txt)
        self.assertNotIn("APEX0001234", san_txt)
        self.assertNotIn("Priya Sharma", san_txt)
        self.assertGreaterEqual(san_res["total_redactions_count"], 10)

    def test_task_14_pii_leakage_prevention_logs_ai(self):
        safe_log = SanitizerService.safe_log_str("Error processing card 4821-9988-1200-5541 for user rohit@gmail.com")
        self.assertNotIn("4821-9988-1200-5541", safe_log)
        self.assertNotIn("rohit@gmail.com", safe_log)

        sec_ex, tok_ex = SecureSession.issue_session()
        ConsentAuditLog.objects.create(session_id=sec_ex.session_id, is_active=True, anonymized_processing_accepted=True, no_credential_disclosure_acknowledged=True)
        req = self.factory.post('/api/v1/documents/analyze/', {
            "sanitized_text": "Account Holder: Sunil Kumar, PAN: PQRST9876K, A/C: 112233445566"
        }, format='json', HTTP_X_SESSION_TOKEN=tok_ex)
        resp = DocumentAnalyzeView.as_view()(req)
        self.assertNotIn("Sunil Kumar", str(resp.data))
        self.assertNotIn("PQRST9876K", str(resp.data))

    def test_task_15_consent_enforcement_dpdp(self):
        unconsented_session = f"unconsented_user_{uuid.uuid4().hex[:8]}"
        u_sec, u_tok = SecureSession.issue_session(unconsented_session)
        ConsentAuditLog.objects.filter(session_id=unconsented_session).delete()

        req_block = self.factory.post('/api/v1/documents/analyze/', {
            "sanitized_text": "Clean transaction text",
            "session_id": unconsented_session,
            "enforce_consent": True
        }, format='json', HTTP_X_SESSION_TOKEN=u_tok)
        resp_block = DocumentAnalyzeView.as_view()(req_block)
        self.assertEqual(resp_block.status_code, 403)
        self.assertEqual(resp_block.data.get("code"), "CONSENT_REQUIRED")

        # Grant consent with explicit required flags
        req_consent = self.factory.post('/api/v1/privacy/consent/', {
            "session_id": unconsented_session,
            "consent_version": "v1.0-test",
            "anonymized_processing_accepted": True,
            "no_credential_disclosure_acknowledged": True
        }, format='json', HTTP_X_SESSION_TOKEN=u_tok)
        resp_consent = ConsentAuditView.as_view()(req_consent)
        self.assertEqual(resp_consent.status_code, 200)

        # Now authorized
        req_allow = self.factory.post('/api/v1/documents/analyze/', {
            "sanitized_text": "Clean transaction text",
            "session_id": unconsented_session,
            "enforce_consent": True
        }, format='json', HTTP_X_SESSION_TOKEN=u_tok)
        resp_allow = DocumentAnalyzeView.as_view()(req_allow)
        self.assertEqual(resp_allow.status_code, 200)

    def test_task_16_existing_api_regression_tests(self):
        reg_sec, reg_tok = SecureSession.issue_session("reg_test")
        ConsentAuditLog.objects.create(
            session_id="reg_test",
            consent_version="v1.0-task17",
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

        # Persona List
        r_personas = PersonaListView.as_view()(self.factory.get('/api/v1/personas/'))
        self.assertEqual(r_personas.status_code, 200)
        self.assertGreaterEqual(len(r_personas.data.get("personas", [])), 3)

        # Select Persona
        r_sel = SelectPersonaView.as_view()(self.factory.post('/api/v1/personas/select/', {"persona_id": "persona_freelancer_rohit", "session_id": "reg_test"}, format='json', HTTP_X_SESSION_TOKEN=reg_tok))
        self.assertEqual(r_sel.status_code, 200)
        self.assertIn("health_metrics", r_sel.data)

        # Sanitize Preview
        r_san = SanitizePreviewView.as_view()(self.factory.post('/api/v1/privacy/sanitize-preview/', {"raw_text": "A/C: 123456789012"}, format='json'))
        self.assertEqual(r_san.status_code, 200)
        self.assertGreaterEqual(r_san.data.get("total_redactions_count"), 1)

        # Parse Statement
        csv_text = "Date,Description,Debit,Credit,Balance\n2026-10-02,SALARY,,45000.00,45000.00\n2026-10-03,ADOBE,4200.00,,40800.00\n2026-10-04,SWIGGY,480.00,,40320.00"
        r_stmt = ParseStatementView.as_view()(self.factory.post('/api/v1/data/parse-statement/', {"raw_text": csv_text, "format": "csv"}, format='json', HTTP_X_SESSION_TOKEN=reg_tok))
        self.assertEqual(r_stmt.status_code, 200)
        self.assertEqual(len(r_stmt.data.get("transactions", [])), 3)

        # Parse SMS
        sms_hdfc = "Dear Customer, INR 480.00 is debited from A/C **4821 on 04-OCT-26 to SWIGGY. Ref: 9824219. Avl Bal: INR 40,320.00"
        r_sms = ParseSmsView.as_view()(self.factory.post('/api/v1/data/parse-sms/', {"sms_text": sms_hdfc}, format='json', HTTP_X_SESSION_TOKEN=reg_tok))
        self.assertEqual(r_sms.status_code, 200)
        self.assertEqual(r_sms.data.get("status"), "PARSED")

        # Simulate EMI
        r_emi = SimulateEmiView.as_view()(self.factory.post('/api/v1/analytics/simulate-emi/', {"price": 50000, "tenure_months": 6}, format='json'))
        self.assertEqual(r_emi.status_code, 200)
        self.assertIn("true_effective_apr_pct", r_emi.data)

        # Nuke Data
        r_nuke = NukeDataView.as_view()(self.factory.post('/api/v1/privacy/nuke-data/', {"session_id": "reg_test"}, format='json', HTTP_X_SESSION_TOKEN=reg_tok))
        self.assertEqual(r_nuke.status_code, 200)
        self.assertEqual(r_nuke.data.get("status"), "HARD_PURGE_SUCCESSFUL")


class KotakPhonePeGPaySmsTests(TestCase):
    """Dedicated synthetic coverage for Kotak Bank, PhonePe, and Google Pay SMS notifications."""

    def test_kotak_bank_debit(self):
        sms = "Sent Rs.1,500.00 from Kotak Bank AC X1234 to ZOMATO on 15-10-2026. Ref 662819201. Bal: Rs.45,200.00"
        res = BankSmsParser.parse_sms(sms)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.transaction.transaction_type, 'DEBIT')
        self.assertEqual(res.transaction.amount, Decimal('1500.00'))
        self.assertEqual(res.transaction.merchant, 'Zomato')
        self.assertEqual(res.transaction.reference_id, '662819201')
        self.assertEqual(res.transaction.available_balance, Decimal('45200.00'))

    def test_kotak_bank_credit(self):
        sms = "Kotak Bank: Rs 25,000.00 credited to AC X1234 on 16-10-2026 by ACME CORP. Ref 772819202. Avl Bal: Rs 70,200.00"
        res = BankSmsParser.parse_sms(sms)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.transaction.transaction_type, 'CREDIT')
        self.assertEqual(res.transaction.amount, Decimal('25000.00'))
        self.assertEqual(res.transaction.merchant, 'Acme Corp')
        self.assertEqual(res.transaction.reference_id, '772819202')
        self.assertEqual(res.transaction.available_balance, Decimal('70200.00'))

    def test_phonepe_debit(self):
        sms = "Paid Rs.350.00 to Chaipoint on PhonePe using Bank A/C ending 4821. Txn ID T2610161430. Avl Bal: Rs.34,235.00"
        res = BankSmsParser.parse_sms(sms)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.transaction.transaction_type, 'DEBIT')
        self.assertEqual(res.transaction.amount, Decimal('350.00'))
        self.assertEqual(res.transaction.merchant, 'Chaipoint')
        self.assertEqual(res.transaction.reference_id, 'T2610161430')

    def test_phonepe_credit(self):
        sms = "Received Rs.2,000.00 from Rahul Sharma on PhonePe. Txn ID T2610161431. Avl Bal: Rs.36,235.00"
        res = BankSmsParser.parse_sms(sms)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.transaction.transaction_type, 'CREDIT')
        self.assertEqual(res.transaction.amount, Decimal('2000.00'))
        self.assertEqual(res.transaction.merchant, 'Rahul Sharma')
        self.assertEqual(res.transaction.reference_id, 'T2610161431')

    def test_gpay_debit(self):
        sms = "You paid Rs.420.00 to Swiggy using Google Pay. UPI Ref: 4291028391. Date: 16-10-2026."
        res = BankSmsParser.parse_sms(sms)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.transaction.transaction_type, 'DEBIT')
        self.assertEqual(res.transaction.amount, Decimal('420.00'))
        self.assertEqual(res.transaction.merchant, 'Swiggy')
        self.assertEqual(res.transaction.reference_id, '4291028391')

    def test_gpay_credit(self):
        sms = "You received Rs.1,500.00 from Priya on Google Pay. UPI Ref: 5291028392. Date: 17-10-2026."
        res = BankSmsParser.parse_sms(sms)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.transaction.transaction_type, 'CREDIT')
        self.assertEqual(res.transaction.amount, Decimal('1500.00'))
        self.assertEqual(res.transaction.merchant, 'Priya')
        self.assertEqual(res.transaction.reference_id, '5291028392')

    def test_gpay_promotional_rejected(self):
        # Promotional / marketing SMS must be defensively rejected
        sms = "Earn scratch card up to Rs. 500! Pay your electricity bill on Google Pay now."
        res = BankSmsParser.parse_sms(sms)
        self.assertFalse(res.is_valid)
        self.assertTrue(res.is_ambiguous)

