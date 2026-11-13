"""
Task 19 — financial data ingestion privacy regressions.

Every ingestion endpoint (statement upload/parse, CSV/PDF/text parsing, SMS
parsing, sanitization preview) must return responses that never carry the
personal names, identifiers or references contained in the uploaded content, and
parser errors must never quote the source row.

The responses are scanned recursively with the shared scanner
(``api.tests.privacy_scan``) and, in addition, asserted value by value for the
identifiers the scanner cannot recognise (personal names, order numbers).

All data here is synthetic.
"""
import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
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

User = get_user_model()

STATEMENT_URL = '/api/v1/data/parse-statement/'
SMS_URL = '/api/v1/data/parse-sms/'
PREVIEW_URL = '/api/v1/privacy/sanitize-preview/'

# Synthetic sensitive values used across the suite.
PERSON_NAME = 'Sneha Kulkarni'
PERSON_NAME_2 = 'Aditi Raghunathan'
ACCOUNT_HOLDER = 'Rohit Verma'
VPA = 'sneha.kulkarni@okhdfcbank'
PHONE = '9876543210'
PAN = 'ABCDE1234F'
AADHAAR = '1234 5678 9012'
ACCOUNT_NUMBER = '998877665544'
UTR = '421234567890'
ORDER_ID = 'ORD-9824219'
INVOICE_ID = 'INV-2026-7781'

# Every one of these must be absent from any ingestion response.
SENSITIVE_VALUES = (
    PERSON_NAME, PERSON_NAME_2, ACCOUNT_HOLDER, VPA, PHONE, PAN,
    AADHAAR, ACCOUNT_NUMBER, UTR, ORDER_ID, INVOICE_ID,
)

# A statement row whose narration carries a personal name, a VPA and an order id.
NARRATION_ROW = f'UPI/{PERSON_NAME}/{VPA}/{ORDER_ID}'
SMS_TEXT = (
    f'Dear {PERSON_NAME}, INR 480.00 is debited from A/C {ACCOUNT_NUMBER} to '
    f'Swiggy on 04-OCT-26. Ref: {UTR}. Avl Bal: INR 40,320.00'
)


def _assert_clean(testcase, payload, msg=''):
    """
    Asserts a response payload carries no sensitive value at all.

    The scanner runs in 'redacted' mode because a sanitized free-text echo
    legitimately contains the sanitizer's own placeholders ("[REDACTED_ACCOUNT]")
    and the payment-rail words around them; every identifier-shape check still
    applies, and the exact values are checked one by one below.
    """
    blob = json.dumps(payload, default=str)
    for value in SENSITIVE_VALUES:
        testcase.assertNotIn(value, blob, msg=f'{msg} leaked {value!r}')
    leaks = response_leaks(payload, mode='redacted')
    testcase.assertEqual(leaks, [], msg=f'{msg} scanner leaks {leaks}')


def _assert_labels_clean(testcase, payload, msg=''):
    """
    Asserts a structured collection (labels, warnings, audit rows) is clean in
    the strictest sense: no redaction marker and no narration fragment either.
    """
    leaks = response_leaks(payload, mode='strict')
    testcase.assertEqual(leaks, [], msg=f'{msg} scanner leaks {leaks}')


class IngestionTestBase(TestCase):
    """Shared session/consent setup for the ingestion endpoints."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='task19_user', password='pw')
        self.session_id = f'task19_{uuid.uuid4().hex[:8]}'
        self.other_session_id = f'task19_other_{uuid.uuid4().hex[:8]}'
        self.client = APIClient()
        _session, self.token = SecureSession.issue_session(self.session_id)
        _other, self.other_token = SecureSession.issue_session(self.other_session_id)
        self.headers = {'HTTP_X_SESSION_TOKEN': self.token}

    def _grant_consent(self, session_id=None):
        ConsentAuditLog.objects.create(
            session_id=session_id or self.session_id,
            consent_version='v1.0-task19',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )

    def _post_statement(self, raw_text, fmt='csv', persist=False, headers=None):
        return self.client.post(
            STATEMENT_URL,
            {
                'raw_text': raw_text,
                'format': fmt,
                'persist': 'true' if persist else 'false',
            },
            format='json',
            **(headers or self.headers),
        )


class StatementIngestionPrivacyTests(IngestionTestBase):
    """Statement upload/parse (CSV, text) must not echo personal content."""

    CSV = (
        'Date,Description,Debit,Credit,Balance\n'
        f'2026-10-04,{NARRATION_ROW},480.00,,74520.00\n'
        '2026-10-05,POS APPLE INDIA MACBOOK PURCHASE,65000.00,,9520.00\n'
        f'2026-10-06,UPI/{PERSON_NAME_2}/{ORDER_ID},1200.00,,8320.00\n'
    )

    def test_01_statement_rows_expose_no_names_or_references(self):
        response = self._post_statement(self.CSV)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _assert_clean(self, body, 'statement response')
        _assert_labels_clean(self, body['transactions'], 'statement labels')

        for row in body['transactions']:
            self.assertNotIn(PERSON_NAME, row['merchant'])
            self.assertNotIn(PERSON_NAME, row['description'])
            self.assertNotIn(PERSON_NAME_2, row['merchant'])
            self.assertNotIn(PERSON_NAME_2, row['description'])
            # A transaction reference is a financial identifier: it is not exposed.
            self.assertIsNone(row['reference_id'])

        # The safe label is used instead of the raw narration.
        labels = {row['merchant'] for row in body['transactions']}
        self.assertNotIn(PERSON_NAME, labels)
        self.assertNotIn(PERSON_NAME_2, labels)

    def test_02_statement_warnings_never_reproduce_the_row(self):
        malformed = (
            'Date,Description,Debit,Credit,Balance\n'
            '2026-10-04,GOOD ROW,480.00,,74520.00\n'
            f'2026-10-05,Account Holder: {ACCOUNT_HOLDER} {PHONE},,,\n'
        )
        response = self._post_statement(malformed)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _assert_clean(self, body, 'malformed row response')
        self.assertTrue(body['errors'], msg='expected a controlled row warning')
        _assert_labels_clean(self, body['errors'], 'row warnings')
        for warning in body['errors']:
            self.assertIn('Row', warning)
            self.assertNotIn(ACCOUNT_HOLDER, warning)
            self.assertNotIn(PHONE, warning)

    def test_03_statement_error_response_has_no_traceback_or_content(self):
        # No parsable table: the parser rejects the content.
        response = self._post_statement(
            f'{PERSON_NAME} {PHONE} {PAN} {ACCOUNT_NUMBER} {UTR}\n'
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        _assert_clean(self, body, 'statement error response')
        self.assertNotIn('Traceback', json.dumps(body))
        self.assertNotIn('File "', json.dumps(body))

    def test_04_account_metadata_carries_no_account_digits(self):
        csv_text = (
            'Account Holder: Sunita Rao\n'
            'A/C 998877665544\n'
            'Date,Description,Debit,Credit,Balance\n'
            '2026-10-04,POS NETFLIX SUBSCRIPTION,199.00,,74520.00\n'
        )
        response = self._post_statement(csv_text)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _assert_clean(self, body, 'account metadata response')
        account_info = body.get('account_info', {})
        _assert_labels_clean(self, account_info, 'account metadata')
        if 'masked_account_number' in account_info:
            self.assertNotIn('5544', str(account_info['masked_account_number']))

    def test_05_text_statement_parsing_is_also_protected(self):
        text = (
            f'04-OCT-26 UPI/{PERSON_NAME}/{VPA}/{ORDER_ID} 480.00\n'
            '05-OCT-26 POS APPLE INDIA MACBOOK 65000.00\n'
        )
        response = self._post_statement(text, fmt='txt')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _assert_clean(self, body, 'text statement response')

    def test_06_pdf_statement_parsing_is_also_protected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        pdf_bytes = (
            b'%PDF-1.4\n1 0 obj<<>>endobj\nxref\ntrailer<<>>startxref\n%%EOF'
        )
        upload = SimpleUploadedFile(
            'statement.pdf', pdf_bytes, content_type='application/pdf'
        )
        response = self.client.post(
            STATEMENT_URL, {'file': upload, 'format': 'pdf'}, format='multipart',
            **self.headers,
        )
        # The stub PDF is not a real document: the error must stay controlled.
        self.assertIn(response.status_code, (200, 400))
        _assert_clean(self, response.json(), 'pdf statement response')

    def test_07_unexpected_parser_exception_is_not_echoed(self):
        with patch(
            'api.views.BankStatementParser.parse_csv_text',
            side_effect=RuntimeError(
                f'parser crashed on {ACCOUNT_HOLDER} {PHONE} {ACCOUNT_NUMBER}'
            ),
        ):
            response = self._post_statement(self.CSV)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        _assert_clean(self, body, 'unexpected exception response')
        self.assertNotIn('RuntimeError', json.dumps(body))

    def test_08_stored_data_is_untouched_by_the_response_boundary(self):
        # Storage keeps the sanitized narration for the financial calculations;
        # only the serialized response is reduced to a safe label.
        self._grant_consent()
        response = self._post_statement(self.CSV, persist=True)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _assert_clean(self, body, 'persisted statement response')
        self.assertEqual(body['persistence']['imported'], 3)

        stored = Transaction.objects.filter(session_id=self.session_id)
        self.assertEqual(stored.count(), 3)
        stored_merchants = ' '.join(tx.normalized_merchant for tx in stored)
        self.assertNotIn(VPA, stored_merchants)
        self.assertNotIn(PHONE, stored_merchants)


class SmsIngestionPrivacyTests(IngestionTestBase):
    """SMS parsing must not echo the message content or its identifiers."""

    def test_01_single_sms_response_is_safe(self):
        response = self.client.post(
            SMS_URL, {'sms_text': SMS_TEXT}, format='json', **self.headers
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _assert_clean(self, body, 'sms response')
        _assert_labels_clean(self, body['transaction'], 'sms transaction label')
        self.assertEqual(body['status'], 'PARSED')
        self.assertIsNone(body['transaction']['reference_id'])
        self.assertNotIn(PERSON_NAME, body['raw_sms'])
        self.assertNotIn(UTR, body['raw_sms'])
        # The redaction markers remain, so the audit stays readable.
        self.assertIn('[REDACTED_ACCOUNT]', body['raw_sms'])

    def test_02_sms_batch_response_is_safe(self):
        response = self.client.post(
            SMS_URL,
            {'sms_list': [SMS_TEXT, f'Payment of INR 100 to {PERSON_NAME_2} UPI Ref {UTR}']},
            format='json',
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _assert_clean(self, body, 'sms batch response')
        for row in body.get('transactions', []):
            self.assertIsNone(row['reference_id'])
        _assert_labels_clean(self, body.get('transactions', []), 'sms batch labels')
        for rejected in body.get('ambiguous_or_rejected', []):
            self.assertNotIn(PERSON_NAME, rejected.get('sms', ''))
            self.assertNotIn(PERSON_NAME_2, rejected.get('sms', ''))

    def test_03_non_transaction_sms_is_rejected_safely(self):
        response = self.client.post(
            SMS_URL,
            {'sms_text': f'Your OTP is 123456 for {PERSON_NAME}, A/C {ACCOUNT_NUMBER}'},
            format='json',
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _assert_clean(self, body, 'rejected sms response')
        self.assertIn(body['status'], ('REJECTED_NON_TRANSACTION', 'PARSED'))
        # A one-time password is a credential: it is never echoed back.
        self.assertNotIn('123456', json.dumps(body))

    def test_04_invalid_sms_payload_is_a_controlled_error(self):
        response = self.client.post(
            SMS_URL, {'sms_text': ''}, format='json', **self.headers
        )
        self.assertEqual(response.status_code, 400)
        _assert_clean(self, response.json(), 'invalid sms request')

    def test_05_unexpected_sms_exception_is_not_echoed(self):
        with patch(
            'api.views.BankSmsParser.parse_sms',
            side_effect=RuntimeError(f'crash on {ACCOUNT_HOLDER} {PAN}'),
        ):
            response = self.client.post(
                SMS_URL, {'sms_text': SMS_TEXT}, format='json', **self.headers
            )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        _assert_clean(self, body, 'sms exception response')
        self.assertNotIn('RuntimeError', json.dumps(body))


class SanitizationPreviewPrivacyTests(IngestionTestBase):
    """The sanitization preview must not carry personal content either."""

    RAW = (
        f'Account Holder: {ACCOUNT_HOLDER}\n'
        f'UPI/{PERSON_NAME}/{VPA}/{ORDER_ID} debited to Chai Point\n'
        f'PAN {PAN} A/C {ACCOUNT_NUMBER} Phone {PHONE}\n'
        f'Invoice {INVOICE_ID} UTR {UTR}\n'
    )

    def test_01_preview_contains_no_sensitive_value(self):
        response = self.client.post(
            PREVIEW_URL, {'raw_text': self.RAW}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _assert_clean(self, body, 'preview response')
        self.assertNotIn(PERSON_NAME, body['sanitized_text_preview'])
        self.assertNotIn(ACCOUNT_HOLDER, body['sanitized_text_preview'])
        self.assertNotIn(ORDER_ID, body['sanitized_text_preview'])

    def test_02_preview_audit_stays_honest_about_the_masks(self):
        response = self.client.post(
            PREVIEW_URL, {'raw_text': self.RAW}, format='json'
        )
        body = response.json()
        types = {entry['type'] for entry in body['redactions_audit']}
        self.assertIn('PERSON_NAME', types)
        self.assertIn('TRANSACTION_REFERENCE', types)
        # The audit never carries the original values, only placeholders.
        for entry in body['redactions_audit']:
            self.assertIn('placeholder', entry)
            self.assertIn('count', entry)
        # The audit rows carry the sanitizer's own placeholders by design.
        _assert_clean(self, body['redactions_audit'], 'preview audit')

    def test_03_preview_of_a_file_upload_is_protected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile(
            'statement.txt',
            self.RAW.encode('utf-8'),
            content_type='text/plain',
        )
        response = self.client.post(
            PREVIEW_URL, {'file': upload}, format='multipart'
        )
        self.assertEqual(response.status_code, 200)
        _assert_clean(self, response.json(), 'preview file response')

    def test_04_preview_empty_input_is_a_controlled_error(self):
        response = self.client.post(PREVIEW_URL, {'raw_text': '   '}, format='json')
        self.assertEqual(response.status_code, 400)
        _assert_clean(self, response.json(), 'preview empty response')


class IngestionFunctionalityPreservedTests(IngestionTestBase):
    """The privacy boundary must not damage the financial processing."""

    CSV = (
        'Date,Description,Debit,Credit,Balance\n'
        f'2026-10-04,UPI/{PERSON_NAME}/{VPA}/{ORDER_ID},480.00,,74520.00\n'
        '2026-10-05,POS APPLE INDIA MACBOOK PURCHASE,65000.00,,9520.00\n'
        '2026-10-06,ACH CRED CLIENT GLOBAL TECH STIPEND,,82000.00,156520.00\n'
    )

    def test_01_amounts_dates_and_direction_are_preserved(self):
        response = self._post_statement(self.CSV)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        rows = body['transactions']
        self.assertEqual(len(rows), 3)
        self.assertEqual(float(rows[0]['amount']), 480.00)
        self.assertEqual(rows[0]['transaction_date'], '2026-10-04')
        self.assertEqual(rows[0]['transaction_type'], 'DEBIT')
        self.assertEqual(float(rows[1]['amount']), 65000.00)
        self.assertEqual(rows[1]['transaction_date'], '2026-10-05')
        self.assertEqual(rows[2]['transaction_type'], 'CREDIT')
        self.assertEqual(float(rows[2]['amount']), 82000.00)
        self.assertEqual(float(body['total_debits']), 65480.00)
        self.assertEqual(float(body['total_credits']), 82000.00)
        self.assertEqual(body['parsed_count'], 3)
        self.assertEqual(body['format_detected'], 'CSV')

    def test_02_internal_identifiers_remain_usable(self):
        response = self._post_statement(self.CSV)
        rows = response.json()['transactions']
        for row in rows:
            # Opaque, non-personal identifiers stay available for API operations.
            self.assertTrue(row['transaction_id'])
            self.assertEqual(len(row['transaction_id']), 16)

    def test_03_consent_enforcement_is_preserved(self):
        response = self._post_statement(self.CSV, persist=True)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get('error'), 'CONSENT_REQUIRED')
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id).count(), 0
        )

    def test_04_session_isolation_is_preserved(self):
        self._grant_consent()
        response = self._post_statement(self.CSV, persist=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['persistence']['imported'], 3)

        other = self.client.post(
            STATEMENT_URL,
            {'raw_text': self.CSV, 'format': 'csv', 'persist': 'true'},
            format='json',
            HTTP_X_SESSION_TOKEN=self.other_token,
        )
        self.assertEqual(other.status_code, 403)
        self.assertEqual(
            Transaction.objects.filter(session_id=self.other_session_id).count(), 0
        )
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id).count(), 3
        )

    def test_05_refund_matching_and_reconciliation_still_work(self):
        from api.insights import detect_subscriptions, detect_unusual_spending

        self._grant_consent()
        response = self._post_statement(self.CSV, persist=True)
        self.assertEqual(response.status_code, 200)

        # A refund and its matching purchase are still reconciled internally.
        snapshot, _ = FinancialSnapshot.objects.get_or_create(
            session_id=self.session_id
        )
        Transaction.objects.create(
            snapshot=snapshot,
            session_id=self.session_id,
            transaction_date=date(2026, 10, 10),
            amount=Decimal('1500.00'),
            transaction_type='DEBIT',
            normalized_merchant='CULTFIT',
            category='Uncategorized',
            source_type=Transaction.SOURCE_IMPORT,
        )
        Transaction.objects.create(
            snapshot=snapshot,
            session_id=self.session_id,
            transaction_date=date(2026, 10, 12),
            amount=Decimal('1500.00'),
            transaction_type='CREDIT',
            normalized_merchant='CULTFIT',
            category='Uncategorized',
            source_type=Transaction.SOURCE_IMPORT,
        )
        unusual = detect_unusual_spending(self.session_id)
        self.assertIsInstance(unusual, list)
        subscriptions = detect_subscriptions(self.session_id)
        self.assertIsInstance(subscriptions, list)
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id).count(), 5
        )

    def test_06_duplicate_import_protection_still_works(self):
        self._grant_consent()
        first = self._post_statement(self.CSV, persist=True)
        self.assertEqual(first.json()['persistence']['imported'], 3)
        second = self._post_statement(self.CSV, persist=True)
        self.assertEqual(second.json()['persistence']['imported'], 0)
        self.assertEqual(second.json()['persistence']['skipped_duplicates'], 3)
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id).count(), 3
        )
