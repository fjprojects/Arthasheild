"""
Positive controls for the shared privacy leak scanner (Task 18.1).

These tests prove two things:

1. The UUID exclusion removes a *false* alert only. Real phone numbers (bare
   and embedded in narration), PANs, VPAs, emails, Aadhaar numbers, redaction
   markers and reference numbers are still detected.
2. The scanner genuinely exercises the **production** detector: the compiled
   patterns it uses are the very objects held by
   ``sanitizer.services.SanitizerService.PATTERNS`` (no private copy that could
   drift), and the scan runs over a real production API response.

All data here is synthetic.
"""
import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from api.models import (
    FinancialSnapshot,
    SecureSession,
    Transaction,
)
from api.tests.privacy_scan import (
    PRODUCTION_PATTERNS,
    SENSITIVE_PATTERNS,
    is_opaque_identifier,
    response_leaks,
)
from sanitizer.services import SanitizerService

User = get_user_model()

# A UUID whose final group is a 10-digit run starting with 6-9: identical in
# shape to an Indian mobile number, which is what made the scanner fire.
PHONE_SHAPED_UUID = '7529788d-68a1-43b5-8cc0-be6335293110'


class PrivacyScannerPositiveControlTests(TestCase):
    """Detection is intact; only opaque identifiers are skipped."""

    def test_01_uuid_identifiers_do_not_trigger_phone_alerts(self):
        identifiers = [
            PHONE_SHAPED_UUID,
            str(uuid.uuid4()),
            # A UUID whose last group is all digits: it contains a 10-digit
            # run that is indistinguishable from an Indian mobile number.
            '12345678-1234-1234-1234-987654321098',
        ]
        for identifier in identifiers:
            self.assertTrue(is_opaque_identifier(identifier), msg=identifier)
            self.assertEqual(response_leaks({'id': identifier}), [], msg=identifier)

        # The same values must not be silently accepted as PII either: they are
        # only skipped because they are opaque system identifiers.
        self.assertFalse(is_opaque_identifier('9876543210'))
        self.assertFalse(is_opaque_identifier('Payment to Rahul 9876543210'))

    def test_02_real_phone_numbers_are_detected(self):
        leaks = response_leaks({'merchant': '9876543210'})
        names = {name for _path, name in leaks}
        self.assertIn('phone', names)
        self.assertIn('prod_phone_number', names)

        # Formatted variants of the same number are caught too.
        for variant in ('98765 43210', '+91 9876543210', '09876543210'):
            self.assertTrue(response_leaks({'v': variant}), msg=variant)

    def test_03_phone_numbers_embedded_in_narration_are_detected(self):
        leaks = response_leaks({'merchant': 'Payment to Rahul 9876543210'})
        names = {name for _path, name in leaks}
        self.assertIn('phone', names)
        self.assertIn('narration', names)

        leaks = response_leaks({'merchant': 'UPI/9811234567@upi'})
        names = {name for _path, name in leaks}
        self.assertIn('phone', names)
        self.assertIn('email_or_vpa', names)
        self.assertIn('narration', names)

    def test_04_pan_vpa_and_other_shapes_are_detected(self):
        expectations = {
            'Payment to Ananya PAN ABCDE1234F': ('pan', 'prod_pan_card'),
            'UPI/9811234567@upi': ('email_or_vpa', 'prod_upi_vpa'),
            'rahul.sharma@example.com': ('email_or_vpa', 'prod_email'),
            'aadhaar 1234 5678 9012': ('aadhaar', 'prod_aadhaar'),
            'A/C 998877665544': ('narration', 'prod_account_number'),
            'Flipkart ORD-5555 Electronics': ('reference',),
            '[REDACTED_PHONE]': ('marker',),
            'USER_PRIMARY': ('marker',),
        }
        for value, expected_names in expectations.items():
            names = {name for _path, name in response_leaks({'v': value})}
            for expected in expected_names:
                self.assertIn(expected, names, msg=f'{value} -> {names}')

    def test_05_safe_values_stay_clean(self):
        safe_payload = {
            'merchant': 'Chai Point',
            'label': 'Unidentified Counterparty',
            'period': 'October 2026',
            'reason': 'NO_IMPORTED_TRANSACTIONS',
            'status': 'INSUFFICIENT_DATA',
            'amount': 60000.0,
            'nested': [{'id': PHONE_SHAPED_UUID}, 'Swiggy'],
        }
        self.assertEqual(response_leaks(safe_payload), [])

    def test_06_scanner_walks_every_branch(self):
        payload = {
            'level1': {
                'level2': [
                    {'level3': 'Payment to Rahul 9876543210'},
                ],
            },
        }
        leaks = response_leaks(payload)
        self.assertTrue(leaks)
        self.assertEqual(leaks[0][0], '$.level1.level2[0].level3')

    def test_07_scanner_uses_the_production_sanitizer_patterns(self):
        # Identity, not equality: the scanner must hold the production
        # compiled regexes themselves, so it cannot drift from the app.
        production = dict(SanitizerService.PATTERNS)
        for name, pattern in PRODUCTION_PATTERNS:
            key = name[len('prod_'):].upper()
            self.assertIn(key, production)
            self.assertIs(pattern, production[key][0], msg=key)

        # Every production pattern is part of the scan set.
        scanned = {id(pattern) for _name, pattern in SENSITIVE_PATTERNS}
        for key, (pattern, _placeholder) in production.items():
            self.assertIn(id(pattern), scanned, msg=key)

    def test_08_production_sanitizer_redacts_the_same_shapes(self):
        raw = (
            'Pay to Rahul 9876543210 via UPI/9811234567@upi '
            'PAN ABCDE1234F A/C 998877665544'
        )
        result = SanitizerService.sanitize(raw)
        sanitized = result['sanitized_text']
        self.assertNotIn('9876543210', sanitized)
        self.assertNotIn('ABCDE1234F', sanitized)
        self.assertNotIn('9811234567@upi', sanitized)
        self.assertNotIn('998877665544', sanitized)
        self.assertIn('[REDACTED_PHONE]', sanitized)
        self.assertGreater(result['total_redactions_count'], 0)

        # And the shared scanner flags the same raw text.
        self.assertTrue(response_leaks({'raw': raw}))


class PrivacyScannerProductionResponseTests(TestCase):
    """The scanner is run over a real production API response."""

    def setUp(self):
        self.user = User.objects.create_user(username='privacy_probe', password='pw')
        self.session_id = f'privacy_probe_{uuid.uuid4().hex[:8]}'
        snapshot, _ = FinancialSnapshot.objects.get_or_create(session_id=self.session_id)
        Transaction.objects.create(
            snapshot=snapshot,
            session_id=self.session_id,
            transaction_date=date(2026, 10, 5),
            amount=Decimal('50000'),
            transaction_type='DEBIT',
            normalized_merchant='Payment to Rahul 9876543210',
            category='Uncategorized',
            source_type=Transaction.SOURCE_IMPORT,
        )
        self.client = APIClient()
        _session, self.token = SecureSession.issue_session(self.session_id)
        consent = self.client.post(
            '/api/v1/privacy/consent/',
            {
                'session_id': self.session_id,
                'consent_version': 'v1.0-privacy-probe',
                'anonymized_processing_accepted': True,
                'no_credential_disclosure_acknowledged': True,
            },
            format='json',
            HTTP_X_SESSION_TOKEN=self.token,
        )
        self.assertEqual(consent.status_code, 200)

    def test_09_production_response_is_clean_and_a_leak_is_caught(self):
        response = self.client.post(
            '/api/v1/insights/unusual-spending/',
            {'session_id': self.session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=self.token,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()

        # The real production payload contains no sensitive value ...
        self.assertEqual(response_leaks(body), [], msg=str(response_leaks(body)))
        # ... while a deliberately leaked copy of the same payload is caught.
        leaked = dict(body)
        leaked['flagged'] = [{'id': PHONE_SHAPED_UUID, 'merchant': 'Payment to Rahul 9876543210'}]
        self.assertTrue(response_leaks(leaked))
        names = {name for _path, name in response_leaks(leaked)}
        self.assertIn('phone', names)
        self.assertIn('prod_phone_number', names)
