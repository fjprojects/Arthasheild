"""
Task 17 — imported-session snapshot/overview API regressions.

`compute_imported_session_overview` derives deterministic statement metrics from
imported (source_type='import') transactions only. The endpoint must enforce the
consent gate, never merge persona transactions, never extrapolate partial-month
coverage, and serialize only safe counterparty labels at the response boundary.
All data here is synthetic.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model
User = get_user_model()
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction
from api.tests.privacy_scan import response_leaks as _response_leaks

IMPORTED_OVERVIEW_URL = '/api/v1/insights/imported-overview/'

# Stored (already sanitized) narration -> final safe label serialized by the view.
CASES = [
    ('UPI/[REDACTED_UPI_ID]', 'Unidentified Counterparty'),
    ('Payment to Rahul [REDACTED_PHONE]', 'Unidentified Counterparty'),
    ('PAN [REDACTED_PAN] A/C [REDACTED_ACCOUNT]', 'Unidentified Counterparty'),
    ('UPI/9811234567@upi', 'Unidentified Counterparty'),
    ('UPI/SWIGGY/ORDER_9824219/[REDACTED_UPI_ID]', 'Swiggy'),
    ('Chai Point', 'Chai Point'),
]

FORBIDDEN = (
    '9876543210', 'ABCDE1234F', '112233445566', '9811234567', 'Rahul',
    '@upi', '@icici', 'ORDER_9824219', 'REDACTED', 'USER_PRIMARY',
    'Payment to ', 'A/C ',
)

# Recursive response scan: identifier shapes, narration and redaction markers.
# Shared with the Task 15 suite; it runs the production sanitizer patterns
# alongside the narrative/marker shapes (see api.tests.privacy_scan).


class Task17ImportedOverviewApiTests(TestCase):
    """Consent-gated, import-scoped, non-extrapolating, privacy-safe overview."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='task17_user', password='pw')

    def _make_session(self, import_tx_specs, persona_tx_specs=None):
        """Creates a consented session with the given imported (and optional
        persona) transactions. Returns (session_id, client, token, import_ids)."""
        session_id = f'task17_{uuid.uuid4().hex[:8]}'
        snap, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)

        import_ids = []
        for day, amount, tx_type, merchant in import_tx_specs:
            tx = Transaction.objects.create(
                snapshot=snap,
                session_id=session_id,
                transaction_date=day,
                amount=Decimal(amount),
                transaction_type=tx_type,
                normalized_merchant=merchant,
                category='Uncategorized',
                source_type=Transaction.SOURCE_IMPORT,
            )
            import_ids.append(str(tx.id))

        for day, amount, tx_type, merchant in (persona_tx_specs or []):
            Transaction.objects.create(
                snapshot=snap,
                session_id=session_id,
                transaction_date=day,
                amount=Decimal(amount),
                transaction_type=tx_type,
                normalized_merchant=merchant,
                category='Uncategorized',
                source_type=Transaction.SOURCE_PERSONA,
            )

        client = APIClient()
        _session, token = SecureSession.issue_session(session_id)
        ConsentAuditLog.objects.create(
            session_id=session_id,
            user=self.user,
            consent_version='v1.0-task17',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )
        return session_id, client, token, import_ids

    def _overview(self, client, session_id, token):
        response = client.post(
            IMPORTED_OVERVIEW_URL,
            {'session_id': session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_01_consent_is_required(self):
        session_id = f'task17_noconsent_{uuid.uuid4().hex[:8]}'
        FinancialSnapshot.objects.get_or_create(session_id=session_id)
        Transaction.objects.create(
            snapshot=FinancialSnapshot.objects.get(session_id=session_id),
            session_id=session_id,
            transaction_date=date(2026, 10, 2),
            amount=Decimal('45000'),
            transaction_type='CREDIT',
            normalized_merchant='ACH CRED CLIENT GLOBAL TECH STIPEND',
            category='Uncategorized',
            source_type=Transaction.SOURCE_IMPORT,
        )
        client = APIClient()
        _session, token = SecureSession.issue_session(session_id)
        response = client.post(
            IMPORTED_OVERVIEW_URL,
            {'session_id': session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get('code'), 'CONSENT_REQUIRED')

    def test_02_empty_session_reports_insufficient_reason(self):
        session_id, client, token, _ids = self._make_session([])
        body = self._overview(client, session_id, token)
        self.assertFalse(body['has_imported_data'])
        self.assertFalse(body['data_sufficient'])
        self.assertEqual(body['insufficient_reason'], 'NO_IMPORTED_TRANSACTIONS')
        self.assertIsNone(body['statement_period'])
        self.assertEqual(body['transactions'], [])
        self.assertEqual(body['transaction_count'], 0)

    def test_03_overview_uses_only_imported_transactions(self):
        session_id, client, token, import_ids = self._make_session(
            [
                (date(2026, 10, 2), '45000.00', 'CREDIT', 'ACH CRED CLIENT GLOBAL TECH STIPEND'),
                (date(2026, 10, 3), '4200.00', 'DEBIT', 'POS ADOBE SYSTEMS RENEWAL'),
            ],
            persona_tx_specs=[
                (date(2026, 10, 1), '75000.00', 'CREDIT', 'SALARY CREDIT CORPORATE'),
                (date(2026, 10, 4), '18000.00', 'DEBIT', 'UPI/CULT FIT/MEMBERSHIP'),
            ],
        )
        body = self._overview(client, session_id, token)

        self.assertTrue(body['has_imported_data'])
        self.assertTrue(body['data_sufficient'])
        self.assertEqual(body['transaction_count'], 2)
        self.assertEqual(
            {row['id'] for row in body['transactions']},
            set(import_ids),
        )
        for row in body['transactions']:
            self.assertEqual(row['source_type'], 'import')

        # Persona credits must never inflate imported-statement metrics.
        self.assertEqual(body['summary']['monthly_income'], '45000.00')
        self.assertEqual(body['summary']['monthly_expenses'], '4200.00')
        self.assertEqual(body['budget']['operating_income'], '45000.00')
        self.assertEqual(body['budget']['net_living_expenses'], '4200.00')

    def test_04_statement_period_resolves_busiest_month(self):
        session_id, client, token, _ids = self._make_session([
            (date(2026, 9, 5), '100.00', 'DEBIT', 'UPI/KIRANA STORE'),
            (date(2026, 9, 15), '100.00', 'DEBIT', 'UPI/KIRANA STORE'),
            (date(2026, 10, 2), '45000.00', 'CREDIT', 'ACH CRED CLIENT GLOBAL TECH STIPEND'),
            (date(2026, 10, 3), '4200.00', 'DEBIT', 'POS ADOBE SYSTEMS RENEWAL'),
            (date(2026, 10, 20), '300.00', 'DEBIT', 'UPI/SWIGGY/ORDER_9824219/swiggy@icici'),
        ])
        body = self._overview(client, session_id, token)

        period = body['statement_period']
        self.assertEqual(period['reporting_year'], 2026)
        self.assertEqual(period['reporting_month'], 10)
        self.assertEqual(period['label'], 'October 2026')
        self.assertEqual(period['start_date'], '2026-09-05')
        self.assertEqual(period['end_date'], '2026-10-20')

        coverage = body['data_coverage']
        self.assertEqual(coverage['days_covered'], 46)
        self.assertEqual(coverage['distinct_months'], 2)
        self.assertEqual(coverage['transaction_count'], 5)

    def test_05_safe_to_spend_withheld_without_verified_balance(self):
        session_id, client, token, _ids = self._make_session([
            (date(2026, 10, 2), '45000.00', 'CREDIT', 'ACH CRED CLIENT GLOBAL TECH STIPEND'),
            (date(2026, 10, 3), '4200.00', 'DEBIT', 'POS ADOBE SYSTEMS RENEWAL'),
        ])
        body = self._overview(client, session_id, token)

        # Imported statements carry no verified balance: the figure must be
        # withheld with an explicit machine-readable reason, never fabricated.
        self.assertEqual(body['safe_to_spend_status'], 'INSUFFICIENT_DATA')
        self.assertIn('LIQUID_BALANCE_UNKNOWN', body['safe_to_spend_reason'])
        self.assertIsNone(body['safe_to_spend']['safe_to_spend_daily'])
        self.assertIsNone(body['safe_to_spend']['safe_to_spend_weekly'])
        self.assertFalse(body['safe_to_spend']['available'])
        self.assertTrue(body['safe_to_spend']['guidance'])
        self.assertFalse(body['health_metrics']['liquid_balance_known'])
        self.assertIsNone(body['summary']['liquid_balance'])
        self.assertFalse(body['summary']['liquid_balance_known'])

    def test_06_response_contains_only_safe_counterparty_labels(self):
        specs = [
            (date(2026, 10, day), '100.00', 'DEBIT', narration)
            for day, (narration, _expected) in enumerate(CASES, start=1)
        ]
        session_id, client, token, import_ids = self._make_session(specs)
        body = self._overview(client, session_id, token)

        rows_by_id = {row['id']: row for row in body['transactions']}
        for day, (narration, expected) in enumerate(CASES, start=1):
            row = rows_by_id[import_ids[day - 1]]
            self.assertEqual(row['merchant'], expected, msg=narration)
            self.assertEqual(row['description'], expected, msg=narration)

        blob = json.dumps(body)
        for sensitive in FORBIDDEN:
            self.assertNotIn(sensitive, blob, msg=f'leaked {sensitive}')

        leaks = _response_leaks(body)
        self.assertEqual(leaks, [], msg=f'response leaked {leaks}')

        # The stored narration is never rewritten by the overview response path.
        stored = list(
            Transaction.objects.filter(session_id=session_id).values_list(
                'normalized_merchant', flat=True
            )
        )
        for narration, _expected in CASES:
            self.assertIn(narration, stored)

    def test_07_sessions_cannot_see_each_others_imports(self):
        session_a, client_a, token_a, ids_a = self._make_session([
            (date(2026, 10, 2), '45000.00', 'CREDIT', 'ACH CRED CLIENT GLOBAL TECH STIPEND'),
        ])
        session_b, client_b, token_b, ids_b = self._make_session([
            (date(2026, 10, 5), '9999.00', 'DEBIT', 'POS CROMA ELECTRONICS STORE'),
        ])

        body_a = self._overview(client_a, session_a, token_a)
        body_b = self._overview(client_b, session_b, token_b)

        ids_returned_a = {row['id'] for row in body_a['transactions']}
        ids_returned_b = {row['id'] for row in body_b['transactions']}
        self.assertEqual(ids_returned_a, set(ids_a))
        self.assertEqual(ids_returned_b, set(ids_b))
        self.assertFalse(ids_returned_a & ids_returned_b)
        self.assertEqual(body_a['summary']['monthly_income'], '45000.00')
        self.assertEqual(body_b['summary']['monthly_income'], '0.00')

    def test_08_partial_month_coverage_reported_not_extrapolated(self):
        # Five days of statement coverage inside October: a partial month.
        session_id, client, token, _ids = self._make_session([
            (date(2026, 10, 2), '45000.00', 'CREDIT', 'ACH CRED CLIENT GLOBAL TECH STIPEND'),
            (date(2026, 10, 6), '1000.00', 'DEBIT', 'UPI/KIRANA STORE'),
        ])
        body = self._overview(client, session_id, token)

        coverage = body['data_coverage']
        self.assertEqual(coverage['days_covered'], 5)
        self.assertTrue(coverage['is_partial_month_likely'])
        self.assertFalse(coverage['extrapolated'])
        self.assertTrue(coverage['note'])

        # Observed amounts are reported as-is: no full-month extrapolation.
        self.assertEqual(body['summary']['monthly_income'], '45000.00')
        self.assertEqual(body['summary']['monthly_expenses'], '1000.00')

    def test_09_summary_reports_confirmed_recurring_and_leakage(self):
        # Three consistent monthly subscription debits: cadence-CONFIRMED.
        session_id, client, token, _ids = self._make_session([
            (date(2026, 8, 16), '1650.00', 'DEBIT', 'POS OPENAI CHATGPT PLUS MONTHLY US-1182'),
            (date(2026, 9, 16), '1650.00', 'DEBIT', 'POS OPENAI CHATGPT PLUS MONTHLY US-1183'),
            (date(2026, 10, 16), '1650.00', 'DEBIT', 'POS OPENAI CHATGPT PLUS MONTHLY US-1184'),
        ])
        body = self._overview(client, session_id, token)

        summary = body['summary']
        self.assertEqual(summary['confirmed_recurring_count'], 1)
        self.assertEqual(summary['monthly_leakage'], '1650.00')
        self.assertEqual(summary['confirmed_commitments'], '1650.00')
        self.assertEqual(body['safe_to_spend']['pending_fixed_obligations'], 1650.0)
