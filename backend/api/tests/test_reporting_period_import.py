"""
Reporting-period, dataset-isolation and duplicate-ingestion regression tests.
Ported from reference audit suite.

Covers the Financial Intelligence defect where an imported November 2026
statement was rendered as October 2026 with Rs 0.00 metrics.
Synthetic data only.
"""
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction
from api.insights import monthly_budget, resolve_reporting_period
from api.views import MonthlyBudgetView, ParseStatementView


class AuthRequestFactory(APIRequestFactory):
    def __init__(self, get_token_fn, **defaults):
        super().__init__(**defaults)
        self.get_token_fn = get_token_fn

    def request(self, **kwargs):
        token = self.get_token_fn()
        if token and 'HTTP_X_SESSION_TOKEN' not in kwargs:
            kwargs['HTTP_X_SESSION_TOKEN'] = token
        return super().request(**kwargs)


def _snap(session_id):
    snap, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
    return snap


def _tx(snap, session_id, merchant, amount, tx_type, tx_date, source_type='import'):
    return Transaction.objects.create(
        snapshot=snap,
        session_id=session_id,
        transaction_date=tx_date,
        amount=Decimal(str(amount)),
        transaction_type=tx_type,
        normalized_merchant=merchant,
        category='Uncategorized',
        is_recurring=False,
        source_type=source_type,
        fingerprint='',
    )


# 11 synthetic November 2026 transactions: one credit + ten debits (Rs 4,800 total).
NOV_ROWS = [
    ('Salary Credit', 82000, 'CREDIT', date(2026, 11, 1)),
    ('Swiggy Restaurant Order', 480, 'DEBIT', date(2026, 11, 2)),
    ('Netflix Subscription', 199, 'DEBIT', date(2026, 11, 3)),
    ('BigBasket Grocery', 250, 'DEBIT', date(2026, 11, 4)),
    ('Amazon Shopping', 1200, 'DEBIT', date(2026, 11, 7)),
    ('Uber Taxi', 350, 'DEBIT', date(2026, 11, 9)),
    ('Apollo Pharmacy', 89, 'DEBIT', date(2026, 11, 12)),
    ('Cafe Coffee Day', 640, 'DEBIT', date(2026, 11, 15)),
    ('BESCOM Electricity', 310, 'DEBIT', date(2026, 11, 18)),
    ('Spotify Premium', 75, 'DEBIT', date(2026, 11, 21)),
    ('Flipkart Shopping', 1207, 'DEBIT', date(2026, 11, 24)),
]

NOV_CSV = (
    "Date,Description,Debit,Credit,Balance\n"
    "2026-11-01,SALARY CREDIT NOV,,82000.00,120000.00\n"
    "2026-11-02,UPI/SWIGGY RESTAURANT,480.00,,119520.00\n"
    "2026-11-03,NETFLIX SUBSCRIPTION,199.00,,119321.00\n"
    "2026-11-04,BIGBASKET GROCERY,250.00,,119071.00\n"
    "2026-11-07,AMAZON SHOPPING,1200.00,,117871.00\n"
    "2026-11-09,UBER TAXI,350.00,,117521.00\n"
    "2026-11-12,APOLLO PHARMACY,89.00,,117432.00\n"
    "2026-11-15,CAFE COFFEE DAY,640.00,,116792.00\n"
    "2026-11-18,BESCOM ELECTRICITY,310.00,,116482.00\n"
    "2026-11-21,SPOTIFY PREMIUM,75.00,,116407.00\n"
    "2026-11-24,FLIPKART SHOPPING,1207.00,,115200.00\n"
)


class ReportingPeriodDerivationTests(TestCase):
    def setUp(self):
        self.session_id = 'test_period_%s' % uuid.uuid4().hex[:8]
        self.snap = _snap(self.session_id)
        # October residue must never define the reporting period.
        _tx(self.snap, self.session_id, 'Swiggy Restaurant Order', 100, 'DEBIT', date(2026, 10, 20))
        for merchant, amount, tx_type, tx_date in NOV_ROWS:
            _tx(self.snap, self.session_id, merchant, amount, tx_type, tx_date)

    def test_reports_imported_november_not_october(self):
        result = monthly_budget(self.session_id)
        self.assertEqual(result['reporting_period']['year'], 2026)
        self.assertEqual(result['reporting_period']['month'], 11)
        self.assertEqual(result['reporting_period']['label'], 'November 2026')
        self.assertEqual(result['year'], 2026)
        self.assertEqual(result['month'], 11)

    def test_derived_period_flag(self):
        self.assertTrue(monthly_budget(self.session_id)['reporting_period_derived'])
        explicit = monthly_budget(self.session_id, 2026, 11)
        self.assertFalse(explicit['reporting_period_derived'])

    def test_november_values_are_calculated(self):
        result = monthly_budget(self.session_id)
        self.assertEqual(Decimal(result['operating_income']), Decimal('82000.00'))
        self.assertEqual(Decimal(result['gross_living_expenses']), Decimal('4800.00'))
        self.assertEqual(Decimal(result['net_living_expenses']), Decimal('4800.00'))
        self.assertNotEqual(Decimal(result['operating_income']), Decimal('0'))

    def test_partial_month_actuals_not_extrapolated(self):
        result = monthly_budget(self.session_id)
        self.assertEqual(result['data_completeness']['status'], 'PARTIAL_MONTH')
        self.assertEqual(
            result['data_completeness']['policy'], 'ACTUALS_ONLY_NO_EXTRAPOLATION'
        )
        self.assertTrue(result['data_completeness']['is_partial_month'])
        self.assertEqual(Decimal(result['gross_living_expenses']), Decimal('4800.00'))
        self.assertLess(Decimal(result['gross_living_expenses']), Decimal('14400.00'))

    def test_insufficient_data_reports_no_data(self):
        empty_session = 'test_period_empty_%s' % uuid.uuid4().hex[:8]
        period = resolve_reporting_period(empty_session)
        self.assertEqual(period['status'], 'NO_DATA')
        result = monthly_budget(empty_session)
        self.assertEqual(result['data_completeness']['status'], 'NO_DATA')
        self.assertEqual(result['reporting_period']['status'], 'NO_DATA')
        self.assertEqual(Decimal(result['operating_income']), Decimal('0.00'))


class DatasetIsolationTests(TestCase):
    def setUp(self):
        self.import_session = 'test_iso_import_%s' % uuid.uuid4().hex[:8]
        self.import_snap = _snap(self.import_session)
        for merchant, amount, tx_type, tx_date in NOV_ROWS:
            _tx(self.import_snap, self.import_session, merchant, amount, tx_type, tx_date)
        _tx(self.import_snap, self.import_session, 'PersonaData Store', 9999, 'DEBIT', date(2026, 11, 5),
            source_type='persona')

    def test_import_mode_uses_only_imported_rows(self):
        result = monthly_budget(self.import_session, include_persona=False)
        self.assertEqual(Decimal(result['gross_living_expenses']), Decimal('4800.00'))
        self.assertEqual(result['reporting_period']['dataset'], 'import_only')

    def test_demo_mode_includes_persona_rows(self):
        result = monthly_budget(self.import_session, include_persona=True)
        self.assertEqual(Decimal(result['gross_living_expenses']), Decimal('9999.00'))
        self.assertEqual(result['reporting_period']['dataset'], 'combined')

    def test_persona_only_session_has_no_import_data(self):
        persona_session = 'test_iso_persona_%s' % uuid.uuid4().hex[:8]
        persona_snap = _snap(persona_session)
        _tx(persona_snap, persona_session, 'PersonaData Store', 500, 'DEBIT', date(2026, 11, 6),
            source_type='persona')

        import_only = monthly_budget(persona_session, include_persona=False)
        self.assertEqual(import_only['data_completeness']['status'], 'NO_DATA')
        demo = monthly_budget(persona_session, include_persona=True)
        self.assertEqual(Decimal(demo['gross_living_expenses']), Decimal('500.00'))


class MonthlyBudgetApiTests(TestCase):
    def setUp(self):
        self.session_id = 'test_budget_api_%s' % uuid.uuid4().hex[:8]
        self.session, self.token = SecureSession.issue_session(self.session_id)
        self.factory = AuthRequestFactory(lambda: getattr(self, 'token', None))
        snap = _snap(self.session_id)
        for merchant, amount, tx_type, tx_date in NOV_ROWS:
            _tx(snap, self.session_id, merchant, amount, tx_type, tx_date)

    def _grant_consent(self):
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version='v1.0-period-test',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

    def test_api_derives_period_when_year_month_omitted(self):
        self._grant_consent()
        resp = MonthlyBudgetView.as_view()(self.factory.post(
            '/api/v1/insights/monthly-budget/',
            {'session_id': self.session_id}, format='json'
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['reporting_period']['label'], 'November 2026')
        self.assertEqual(resp.data['month'], 11)
        self.assertTrue(resp.data['reporting_period_derived'])
        self.assertEqual(Decimal(resp.data['gross_living_expenses']), Decimal('4800.00'))

    def test_api_explicit_period_still_supported(self):
        self._grant_consent()
        resp = MonthlyBudgetView.as_view()(self.factory.post(
            '/api/v1/insights/monthly-budget/',
            {'session_id': self.session_id, 'year': 2026, 'month': 11}, format='json'
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['reporting_period_derived'])
        self.assertEqual(resp.data['month'], 11)

    def test_api_rejects_half_specified_period(self):
        self._grant_consent()
        resp = MonthlyBudgetView.as_view()(self.factory.post(
            '/api/v1/insights/monthly-budget/',
            {'session_id': self.session_id, 'year': 2026}, format='json'
        ))
        self.assertEqual(resp.status_code, 400)

    def test_api_requires_active_consent(self):
        resp = MonthlyBudgetView.as_view()(self.factory.post(
            '/api/v1/insights/monthly-budget/',
            {'session_id': self.session_id}, format='json'
        ))
        self.assertEqual(resp.status_code, 403)


class DuplicateIngestionTests(TestCase):
    def setUp(self):
        self.session_id = 'test_dup_%s' % uuid.uuid4().hex[:8]
        self.session, self.token = SecureSession.issue_session(self.session_id)
        self.factory = AuthRequestFactory(lambda: getattr(self, 'token', None))
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version='v1.0-period-test',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

    def _import(self, csv_text, persist=True):
        return ParseStatementView.as_view()(self.factory.post(
            '/api/v1/data/parse-statement/',
            {'raw_text': csv_text, 'format': 'csv', 'session_id': self.session_id, 'persist': persist},
            format='json'
        ))

    def test_reimport_is_idempotent(self):
        first = self._import(NOV_CSV)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['persistence']['imported'], 11)

        second = self._import(NOV_CSV)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['persistence']['imported'], 0)
        self.assertEqual(second.data['persistence']['skipped_duplicates'], 11)
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id, source_type='import').count(), 11
        )

    def test_identical_rows_in_one_statement_both_persist(self):
        csv_text = (
            "Date,Description,Debit,Credit,Balance\n"
            "2026-11-02,UPI/CHAI STALL,30.00,,1000.00\n"
            "2026-11-02,UPI/CHAI STALL,30.00,,970.00\n"
        )
        resp = self._import(csv_text)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['persistence']['imported'], 2)
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id).count(), 2
        )

    def test_period_follows_imported_dataset_after_import(self):
        self._import(NOV_CSV)
        result = monthly_budget(self.session_id)
        self.assertEqual(result['reporting_period']['label'], 'November 2026')
        self.assertEqual(result['reporting_period']['transaction_count'], 11)
