import os
import sys
import uuid
import django
from decimal import Decimal
from datetime import date

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile

from data_processor.models import NormalizedTransaction, StatementParseResult, SmsParseResult
from data_processor.normalizer import TransactionNormalizer
from data_processor.statement_parser import BankStatementParser
from data_processor.sms_parser import BankSmsParser
from sanitizer.services import SanitizerService
from api.models import ConsentAuditLog, FinancialSnapshot, Transaction
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

factory = APIRequestFactory()

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

results = []

def record(test_num, name, passed, evidence=""):
    results.append({
        "num": test_num,
        "name": name,
        "passed": passed,
        "evidence": evidence
    })
    status_str = "[PASS]" if passed else "[FAIL]"
    print(f"{status_str} Task {test_num}: {name} - {evidence[:100]}")

def run_all_tests():
    print("\n=======================================================")
    print("  ARTHASHIELD PHASE 1 DATA PROCESSING TEST SUITE  ")
    print("=======================================================\n")

    # 1. Valid CSV Statement
    csv_text = """Account Statement - Apex National Bank
Account Holder: Rohit Ramesh Verma
Account Number: 4821-9988-1200-5541
IFSC Code: APEX0001234
Date,Description,Debit,Credit,Balance
2026-10-02,ACH CRED CLIENT GLOBAL TECH STIPEND,,45000.00,45000.00
2026-10-03,POS ADOBE SYSTEMS RENEWAL INT US-882194,4200.00,,40800.00
2026-10-04,UPI/SWIGGY/ORDER_9824219/swiggy@icici,480.00,,40320.00
"""
    res1 = BankStatementParser.parse_csv_text(csv_text)
    passed1 = (
        len(res1.transactions) == 3 and
        res1.total_debits == Decimal('4680.00') and
        res1.total_credits == Decimal('45000.00') and
        res1.account_info.get('masked_account_number') == 'XX..5541'
    )
    record(1, "Valid CSV statement parsing", passed1, f"Extracted {len(res1.transactions)} txs, debits={res1.total_debits}, credits={res1.total_credits}")

    # 2. Valid PDF Statement
    res2 = BankStatementParser.parse_pdf_bytes(SYNTHETIC_PDF_BYTES)
    passed2 = (
        len(res2.transactions) == 2 and
        res2.transactions[0].transaction_type == 'CREDIT' and
        res2.transactions[1].transaction_type == 'DEBIT' and
        res2.transactions[0].amount == Decimal('45000.00') and
        res2.transactions[1].amount == Decimal('480.00')
    )
    record(2, "Valid PDF statement parsing", passed2, f"Extracted {len(res2.transactions)} txs via pdfplumber from synthetic PDF")

    # 3. Valid TXT Input (Pipe / Tab delimited)
    txt_content = """Date|Description|Amount|Type
2026-10-10|UPI/CHAIPOINT/EVENING|120.00|DEBIT
2026-10-15|NEFT CRED APEX STUDIOS|40000.00|CREDIT
"""
    res3 = BankStatementParser.parse_txt_bytes(txt_content.encode('utf-8'))
    passed3 = (
        len(res3.transactions) == 2 and
        res3.transactions[0].amount == Decimal('120.00') and
        res3.transactions[1].amount == Decimal('40000.00')
    )
    record(3, "Valid TXT statement parsing", passed3, f"Extracted {len(res3.transactions)} txs from pipe-delimited TXT dump")

    # 4. Invalid and Corrupted Files
    corrupted_pdf = b"%PDF-1.4\ncorrupted_random_garbage_content_without_xref"
    caught_corrupt = False
    try:
        BankStatementParser.parse_pdf_bytes(corrupted_pdf)
    except ValueError as e:
        caught_corrupt = True
        err_msg = str(e)

    caught_empty = False
    try:
        BankStatementParser.parse_file(SimpleUploadedFile("empty.csv", b""), "empty.csv")
    except ValueError:
        caught_empty = True

    passed4 = caught_corrupt and caught_empty
    record(4, "Invalid and corrupted file rejection", passed4, f"Caught corrupted PDF & 0-byte file gracefully with ValueError")

    # 5. Oversized File Rejection (> 5MB)
    large_payload = b"0" * (5 * 1024 * 1024 + 1024)
    caught_oversized = False
    try:
        BankStatementParser.parse_file(SimpleUploadedFile("large.csv", large_payload), "large.csv")
    except ValueError as e:
        if "exceeds maximum allowed limit" in str(e):
            caught_oversized = True
    record(5, "Oversized file rejection (>5MB)", caught_oversized, "Enforced 5MB MAX_UPLOAD_SIZE limit with clear error")

    # 6. Different Indian Date and Amount Formats
    d1 = TransactionNormalizer.parse_date("04/10/2026")
    d2 = TransactionNormalizer.parse_date("12-Oct-26")
    d3 = TransactionNormalizer.parse_date("2026-10-15")
    a1, _ = TransactionNormalizer.parse_amount("1,25,000.50")  # Lakhs comma
    a2, _ = TransactionNormalizer.parse_amount("INR 4,200.00")
    a3, dir3 = TransactionNormalizer.parse_amount("Rs. 5,735.00 Dr")
    a4, dir4 = TransactionNormalizer.parse_amount("45000.00 Cr")
    a5, dir5 = TransactionNormalizer.parse_amount("(1,500.00)")
    passed6 = (
        d1 == date(2026, 10, 4) and
        d2 == date(2026, 10, 12) and
        d3 == date(2026, 10, 15) and
        a1 == Decimal('125000.50') and
        a2 == Decimal('4200.00') and
        a3 == Decimal('5735.00') and dir3 == 'DEBIT' and
        a4 == Decimal('45000.00') and dir4 == 'CREDIT' and
        a5 == Decimal('1500.00') and dir5 == 'DEBIT'
    )
    record(6, "Indian date and amount format handling", passed6, f"Dates (DD/MM/YYYY, DD-Mon-YY, YYYY-MM-DD) and Lakhs amounts verified")

    # 7. Debit and Credit Identification
    row_separate = ["2026-10-05", "PHONE EMI", "", "5735.00", "34585.00"]
    col_map_sep = {"date": 0, "description": 1, "credit": 2, "debit": 3, "balance": 4}
    tx_sep = BankStatementParser._parse_single_row(row_separate, col_map_sep, "Row 1", "CSV")

    row_single_col = ["2026-10-10", "INTERNSHIP STIPEND", "8000.00 Cr", "12150.00"]
    col_map_single = {"date": 0, "description": 1, "amount": 2, "balance": 3}
    tx_single = BankStatementParser._parse_single_row(row_single_col, col_map_single, "Row 2", "CSV")

    passed7 = (
        tx_sep is not None and tx_sep.transaction_type == 'DEBIT' and tx_sep.amount == Decimal('5735.00') and
        tx_single is not None and tx_single.transaction_type == 'CREDIT' and tx_single.amount == Decimal('8000.00')
    )
    record(7, "Debit and credit identification", passed7, "Verified separate column and Dr/Cr suffix identification")

    # 8. UPI and Bank SMS Parsing (Multiple Indian Bank templates)
    sms_hdfc = "Dear Customer, INR 480.00 is debited from A/C **4821 on 04-OCT-26 to SWIGGY. Ref: 9824219. Avl Bal: INR 40,320.00"
    sms_sbi = "Your A/C 98765432101 debited by Rs.1200.00 on 12Oct26 transfer to AMAZON Ref No 6288192837. Avl Bal: Rs.34585.00"
    sms_axis = "INR 1,250.00 debited from Axis Bank A/c ending 4491 on 12-10-2026 14:30:15 at FIGMA. UPI Ref 44910283. Bal: INR 31,835.00"
    sms_credit = "Salary of INR 75,000.00 credited to A/C **9104 on 01-OCT-26 by GLOBEX CORP. Info: NEFT-GLOBEX-123. Avl Bal: INR 1,13,400.00"

    p_hdfc = BankSmsParser.parse_sms(sms_hdfc)
    p_sbi = BankSmsParser.parse_sms(sms_sbi)
    p_axis = BankSmsParser.parse_sms(sms_axis)
    p_cred = BankSmsParser.parse_sms(sms_credit)

    passed8 = (
        p_hdfc.is_valid and p_hdfc.transaction.amount == Decimal('480.00') and p_hdfc.transaction.transaction_type == 'DEBIT' and
        p_sbi.is_valid and p_sbi.transaction.amount == Decimal('1200.00') and p_sbi.transaction.reference_id == '6288192837' and
        p_axis.is_valid and p_axis.transaction.amount == Decimal('1250.00') and p_axis.transaction.merchant == 'Figma' and
        p_cred.is_valid and p_cred.transaction.amount == Decimal('75000.00') and p_cred.transaction.transaction_type == 'CREDIT'
    )
    record(8, "UPI and Indian Bank SMS alert parsing", passed8, f"Successfully parsed HDFC, SBI, Axis, and NEFT salary credit alerts")

    # 9. Ambiguous / Promotional / OTP SMS Handling
    otp_sms = "Your OTP for login is 884920. Do not share with anyone."
    promo_sms = "Pre-approved loan up to 5 Lakhs! Click now bit.ly/bankloan"
    bill_sms = "Your credit card statement generated. Total due Rs. 14,200.00"
    bal_sms = "Your available balance for A/C *4821 is Rs.54,200.00 as on 31-Oct-26."

    p_otp = BankSmsParser.parse_sms(otp_sms)
    p_promo = BankSmsParser.parse_sms(promo_sms)
    p_bill = BankSmsParser.parse_sms(bill_sms)
    p_bal = BankSmsParser.parse_sms(bal_sms)

    passed9 = (
        not p_otp.is_valid and p_otp.is_ambiguous and
        not p_promo.is_valid and p_promo.is_ambiguous and
        not p_bill.is_valid and p_bill.is_ambiguous and
        not p_bal.is_valid and p_bal.is_ambiguous
    )
    record(9, "Ambiguous and non-transaction SMS rejection", passed9, "Rejected OTPs, promotions, CC bill statements, and balance queries")

    # 10. Duplicate Transaction Detection
    tx_a = NormalizedTransaction("", date(2026, 10, 4), "SWIGGY ORDER", Decimal('480.00'), "DEBIT", "SMS", reference_id="9824219")
    tx_b = NormalizedTransaction("", date(2026, 10, 4), "SWIGGY ORDER DUP", Decimal('480.00'), "DEBIT", "SMS", reference_id="9824219")
    tx_c = NormalizedTransaction("", date(2026, 10, 5), "AMAZON PURCHASE", Decimal('1500.00'), "DEBIT", "SMS", reference_id="882194")
    uniques, dup_count = TransactionNormalizer.deduplicate_transactions([tx_a, tx_b, tx_c])
    passed10 = len(uniques) == 2 and dup_count == 1
    record(10, "Duplicate transaction detection & deduplication", passed10, f"Eliminated {dup_count} duplicate transaction(s)")

    # 11. Transaction Normalization (All 9 Standard Fields)
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
    passed11 = (
        norm.transaction_id != "" and
        norm.transaction_date == date(2026, 10, 4) and
        norm.description == "UPI/SWIGGY/ORDER_9824219/swiggy@icici" and
        norm.amount == Decimal('480.00') and
        norm.transaction_type == "DEBIT" and
        norm.source == "SMS_ALERT" and
        norm.merchant == "Swiggy" and
        norm.reference_id == "9824219" and
        norm.currency == "INR"
    )
    record(11, "Standard 9-field transaction normalization", passed11, f"All 9 canonical fields populated with normalized values")

    # 12. Decimal-Based Amount Precision (Zero floating-point loss)
    amounts = [Decimal('0.10'), Decimal('0.20'), Decimal('0.30')]
    total = sum(amounts)
    # Compare with standard float floating-point error (0.1 + 0.2 != 0.3)
    float_error = (0.1 + 0.2) != 0.3
    passed12 = (total == Decimal('0.60')) and float_error and isinstance(norm.amount, Decimal)
    record(12, "Decimal-based financial math precision", passed12, f"Sum={total} (Decimal exact precision enforced)")

    # 13. PII Masking (Expanded Indian Data Formats)
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
    passed13 = (
        "Rohit Ramesh Verma" not in san_txt and
        "ABCDE1234F" not in san_txt and
        "1234 5678 9012" not in san_txt and
        "4821-9988-1200-5541" not in san_txt and
        "9876543210" not in san_txt and
        "rohit.verma.freelance@gmail.com" not in san_txt and
        "rohit@okaxis" not in san_txt and
        "APEX0001234" not in san_txt and
        "Priya Sharma" not in san_txt and
        san_res["total_redactions_count"] >= 10
    )
    record(13, "PII masking across Indian financial formats", passed13, f"Redacted {san_res['total_redactions_count']} sensitive elements")

    # 14. PII Leakage Prevention in Logs & AI Payloads
    safe_log = SanitizerService.safe_log_str("Error processing card 4821-9988-1200-5541 for user rohit@gmail.com")
    no_log_leak = "4821-9988-1200-5541" not in safe_log and "rohit@gmail.com" not in safe_log
    
    # Server-side sanitization in DocumentAnalyzeView
    req14 = factory.post('/api/v1/documents/analyze/', {
        "sanitized_text": "Account Holder: Sunil Kumar, PAN: PQRST9876K, A/C: 112233445566"
    }, format='json')
    resp14 = DocumentAnalyzeView.as_view()(req14)
    no_ai_leak = "Sunil Kumar" not in str(resp14.data) and "PQRST9876K" not in str(resp14.data)
    passed14 = no_log_leak and no_ai_leak
    record(14, "PII leakage prevention in logs & AI payloads", passed14, "Server-side sanitization enforced before external AI calls and logging")

    # 15. Consent Enforcement
    # Ensure session starts unconsented
    unconsented_session = f"unconsented_user_{uuid.uuid4().hex[:8]}"
    ConsentAuditLog.objects.filter(session_id=unconsented_session).delete()

    req15_block = factory.post('/api/v1/documents/analyze/', {
        "sanitized_text": "Clean transaction text",
        "session_id": unconsented_session,
        "enforce_consent": True
    }, format='json')
    resp15_block = DocumentAnalyzeView.as_view()(req15_block)
    blocked = resp15_block.status_code == 403 and resp15_block.data.get("code") == "CONSENT_REQUIRED"

    # Grant consent
    req15_consent = factory.post('/api/v1/privacy/consent/', {
        "session_id": unconsented_session,
        "consent_version": "v1.0-test",
        "anonymized_processing_accepted": True,
        "no_credential_disclosure_acknowledged": True
    }, format='json')
    resp15_consent = ConsentAuditView.as_view()(req15_consent)

    # Now request should succeed
    req15_allow = factory.post('/api/v1/documents/analyze/', {
        "sanitized_text": "Clean transaction text",
        "session_id": unconsented_session,
        "enforce_consent": True
    }, format='json')
    resp15_allow = DocumentAnalyzeView.as_view()(req15_allow)
    allowed = resp15_allow.status_code == 200

    passed15 = blocked and allowed
    record(15, "Consent enforcement under DPDP standards", passed15, f"Blocked HTTP 403 when unconsented; allowed HTTP 200 after consent log")

    # 16. Existing API Regression Tests
    # 16.1 Persona List
    r_personas = PersonaListView.as_view()(factory.get('/api/v1/personas/'))
    p_personas = r_personas.status_code == 200 and len(r_personas.data.get("personas", [])) >= 3

    # 16.2 Select Persona
    r_sel = SelectPersonaView.as_view()(factory.post('/api/v1/personas/select/', {"persona_id": "persona_freelancer_rohit", "session_id": "reg_test"}, format='json'))
    p_sel = r_sel.status_code == 200 and "health_metrics" in r_sel.data

    # 16.3 Sanitize Preview with text and PDF
    r_san = SanitizePreviewView.as_view()(factory.post('/api/v1/privacy/sanitize-preview/', {"raw_text": "A/C: 123456789012"}, format='json'))
    p_san = r_san.status_code == 200 and r_san.data.get("total_redactions_count") >= 1

    # 16.4 Parse Statement API Endpoint
    r_stmt = ParseStatementView.as_view()(factory.post('/api/v1/data/parse-statement/', {"raw_text": csv_text, "format": "csv"}, format='json'))
    p_stmt = r_stmt.status_code == 200 and len(r_stmt.data.get("transactions", [])) == 3

    # 16.5 Parse SMS API Endpoint
    r_sms = ParseSmsView.as_view()(factory.post('/api/v1/data/parse-sms/', {"sms_text": sms_hdfc}, format='json'))
    p_sms = r_sms.status_code == 200 and r_sms.data.get("status") == "PARSED"

    # 16.6 Simulate EMI
    r_emi = SimulateEmiView.as_view()(factory.post('/api/v1/analytics/simulate-emi/', {"price": 50000, "tenure_months": 6}, format='json'))
    p_emi = r_emi.status_code == 200 and "true_effective_apr_pct" in r_emi.data

    # 16.7 Nuke Data
    r_nuke = NukeDataView.as_view()(factory.post('/api/v1/privacy/nuke-data/', {"session_id": "reg_test"}, format='json'))
    p_nuke = r_nuke.status_code == 200 and r_nuke.data.get("status") == "HARD_PURGE_SUCCESSFUL"

    passed16 = p_personas and p_sel and p_san and p_stmt and p_sms and p_emi and p_nuke
    record(16, "Existing API regression tests", passed16, "All 7 API endpoints verified and functioning with zero regressions")

    print("\n=======================================================")
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    print(f"TOTAL TESTS: {total} | PASSED: {passed} | FAILED: {failed}")
    if failed == 0:
        print(">>> 100% PHASE 1 DATA PROCESSING TESTS PASSED! <<<")
    print("=======================================================\n")
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
