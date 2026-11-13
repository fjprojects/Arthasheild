"""
Task 22 — transfer classification edge cases and legacy import deduplication.

Two corrections:

1. An apparent own-account transfer that carries an additional beneficiary
   segment ("UPI/SELF/TRANSFER/RAHUL SHARMA") must be classified as uncertain,
   not confirmed: the transaction keeps its conservative treatment (an ordinary
   outflow) instead of being silently removed from the expenses.

2. A statement imported by an older build stored an own-account transfer with
   the legacy merchant ("Self"); the current build stores the canonical label
   ("Self Transfer"). The two representations denote the same transaction, so
   a re-import must not create a duplicate row.

All data here is synthetic.
"""
import hashlib
import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.insights import classify_credit, classify_debit, monthly_budget
from api.models import ConsentAuditLog, FinancialSnapshot, SecureSession, Transaction
from api.views import _compute_fingerprint
from data_processor.normalizer import TransactionNormalizer
from data_processor.transfers import (
    CONFIDENCE_CONFIRMED,
    CONFIDENCE_UNCERTAIN,
    classify_own_account_transfer,
    transfer_identity,
)

User = get_user_model()

LEGACY_MERCHANT = 'Self'          # what an older build stored
CURRENT_MERCHANT = 'Self Transfer'  # what the current build stores


class AmbiguousOwnAccountTransferTests(TestCase):
    """An extra beneficiary segment downgrades an own-account reading."""

    def test_01_upi_self_transfer_is_still_confirmed(self):
        result = classify_own_account_transfer('UPI/SELF/TRANSFER')
        self.assertTrue(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_CONFIRMED)
        self.assertEqual(result['marker'], 'self')

    def test_02_upi_self_transfer_with_a_beneficiary_is_uncertain(self):
        result = classify_own_account_transfer('UPI/SELF/TRANSFER/RAHUL SHARMA')
        self.assertFalse(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_UNCERTAIN)
        self.assertIn('BENEFICIARY', result['evidence'])

    def test_03_upi_self_transfer_with_a_vpa_is_uncertain(self):
        result = classify_own_account_transfer('UPI/SELF/TRANSFER/rahul@okhdfcbank')
        self.assertFalse(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_UNCERTAIN)

    def test_04_upi_self_ac_transfer_is_still_confirmed(self):
        result = classify_own_account_transfer('UPI/SELF AC/TRANSFER')
        self.assertTrue(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_CONFIRMED)
        self.assertEqual(result['marker'], 'self ac')

    def test_05_transfer_to_self_is_confirmed(self):
        result = classify_own_account_transfer('TRANSFER TO SELF')
        self.assertTrue(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_CONFIRMED)

    def test_06_transfer_to_another_person_stays_uncertain(self):
        result = classify_own_account_transfer('TRANSFER TO RAHUL SHARMA')
        self.assertFalse(result['is_own_account_transfer'])
        self.assertEqual(result['confidence'], CONFIDENCE_UNCERTAIN)

    def test_07_masked_account_and_beneficiary_variations(self):
        # A masked account token is the account holder's own account: it is
        # structural and does not name a beneficiary.
        confirmed = classify_own_account_transfer('UPI/SELF TRANSFER A/C XX..4821')
        self.assertTrue(confirmed['is_own_account_transfer'])
        self.assertEqual(confirmed['confidence'], CONFIDENCE_CONFIRMED)

        masked_reference = classify_own_account_transfer('UPI/SELF/TRANSFER/XX..4821')
        self.assertTrue(masked_reference['is_own_account_transfer'])

        # A beneficiary next to a masked account is still a beneficiary.
        ambiguous = classify_own_account_transfer('UPI/SELF/TRANSFER/RAHUL SHARMA/XX..4821')
        self.assertFalse(ambiguous['is_own_account_transfer'])
        self.assertEqual(ambiguous['confidence'], CONFIDENCE_UNCERTAIN)

        # A structural trailing segment (a rail word, a reference) is fine.
        for narration in (
            'UPI/SELF/TRANSFER/SAVINGS',
            'UPI/SELF/TRANSFER/ORDER-9824219',
            'UPI/SELF/TRANSFER/421234567890',
        ):
            result = classify_own_account_transfer(narration)
            self.assertTrue(result['is_own_account_transfer'], msg=narration)

    def test_08_transfer_fee_and_third_party_protections_are_preserved(self):
        fee = classify_own_account_transfer('UPI/SELF TRANSFER FEE')
        self.assertFalse(fee['is_own_account_transfer'])
        self.assertEqual(fee['confidence'], CONFIDENCE_UNCERTAIN)

        third_party = classify_own_account_transfer(
            'UPI/TRANSFER/RAHUL SHARMA/rahul@okhdfcbank'
        )
        self.assertFalse(third_party['is_own_account_transfer'])

    def test_09_ordinary_merchants_are_never_affected(self):
        for narration in (
            'POS SWIGGY/ORDER_9824219/swiggy@icici',
            'POS APPLE INDIA MACBOOK PRO PURCHASE',
            'ACH CRED CLIENT GLOBAL TECH STIPEND',
        ):
            result = classify_own_account_transfer(narration)
            self.assertFalse(result['is_own_account_transfer'], msg=narration)

    def test_10_an_uncertain_transfer_keeps_the_ordinary_expense_treatment(self):
        session_id = f'task22_uncertain_{uuid.uuid4().hex[:8]}'
        snapshot, _ = FinancialSnapshot.objects.get_or_create(session_id=session_id)
        Transaction.objects.create(
            snapshot=snapshot,
            session_id=session_id,
            transaction_date=date(2026, 10, 5),
            amount=Decimal('10000.00'),
            transaction_type='DEBIT',
            normalized_merchant='Self Transfer',
            category='Uncategorized',
            source_type=Transaction.SOURCE_IMPORT,
        )
        # The ambiguous narration is classified as an ordinary outflow, so it is
        # NOT removed from the living expenses.
        ambiguous_merchant = TransactionNormalizer.extract_merchant(
            'UPI/SELF/TRANSFER/RAHUL SHARMA'
        )
        self.assertFalse(classify_debit(ambiguous_merchant)['is_transfer'])
        res = monthly_budget(session_id, 2026, 10)
        # The stored row (a confirmed transfer) is excluded...
        self.assertEqual(Decimal(res['debit_transfers']), Decimal('10000.00'))
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('0.00'))


class TransferIdentityTests(TestCase):
    """The legacy and the current representation describe the same movement."""

    def test_01_legacy_and_current_representations_share_one_identity(self):
        self.assertEqual(
            transfer_identity(LEGACY_MERCHANT),
            transfer_identity(CURRENT_MERCHANT),
        )
        self.assertEqual(transfer_identity(LEGACY_MERCHANT), 'SELF')
        self.assertEqual(transfer_identity('Self Ac'), 'SELF_AC')
        self.assertEqual(transfer_identity('Self Ac Transfer'), 'SELF_AC')
        self.assertEqual(transfer_identity('Own Account'), 'OWN_ACCOUNT')
        self.assertEqual(transfer_identity('Own Account Transfer'), 'OWN_ACCOUNT')

    def test_02_different_own_account_movements_keep_different_identities(self):
        identities = {
            transfer_identity(LEGACY_MERCHANT),
            transfer_identity('Self Ac'),
            transfer_identity('Own Account'),
        }
        self.assertEqual(len(identities), 3)

    def test_03_ordinary_merchants_have_no_transfer_identity(self):
        for merchant in ('Swiggy', 'Apple India Macbook Pro', 'Netflix Subscription'):
            self.assertIsNone(transfer_identity(merchant), msg=merchant)


class LegacyImportDeduplicationTests(TestCase):
    """A legacy import must not duplicate an own-account transfer."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='task22_dedup', password='pw')
        self.session_id = f'task22_dedup_{uuid.uuid4().hex[:8]}'
        _session, self.token = SecureSession.issue_session(self.session_id)
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version='v1.0-task22',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
            consented_at=timezone.now(),
        )
        self.csv = (
            'Date,Description,Debit,Credit,Balance\n'
            '2026-10-01,ACH CRED CLIENT GLOBAL TECH STIPEND,,75000.00,75000.00\n'
            '2026-10-05,UPI/SELF/TRANSFER,10000.00,,65000.00\n'
        )

    def _import(self):
        return self.client.post(
            '/api/v1/data/parse-statement/',
            {'raw_text': self.csv, 'format': 'csv', 'persist': 'true',
             'session_id': self.session_id},
            format='json',
            HTTP_X_SESSION_TOKEN=self.token,
        )

    def _store_legacy_row(self):
        """Stores the row exactly as an older build would have stored it."""
        snapshot, _ = FinancialSnapshot.objects.get_or_create(
            session_id=self.session_id
        )

        class _LegacyTx:
            transaction_date = date(2026, 10, 5)
            amount = Decimal('10000.00')
            transaction_type = 'DEBIT'
            normalized_merchant = LEGACY_MERCHANT
            reference_id = ''

        legacy_tx = _LegacyTx()
        # The fingerprint an older build computed: the legacy merchant, no
        # occurrence suffix.
        legacy_fingerprint = hashlib.sha256(
            f"{self.session_id}|{legacy_tx.transaction_date}|{legacy_tx.amount}|"
            f"{legacy_tx.transaction_type}|{LEGACY_MERCHANT}|".encode('utf-8')
        ).hexdigest()
        return Transaction.objects.create(
            snapshot=snapshot,
            session_id=self.session_id,
            transaction_date=legacy_tx.transaction_date,
            amount=legacy_tx.amount,
            transaction_type=legacy_tx.transaction_type,
            normalized_merchant=LEGACY_MERCHANT,
            category='Uncategorized',
            source_type=Transaction.SOURCE_IMPORT,
            fingerprint=legacy_fingerprint,
        )

    def test_01_a_legacy_row_is_not_duplicated_by_the_current_import(self):
        legacy_row = self._store_legacy_row()

        response = self._import()
        self.assertEqual(response.status_code, 200)
        persistence = response.json()['persistence']
        # The transfer is recognised as the row that is already stored.
        self.assertEqual(persistence['imported'], 1)   # only the salary credit
        self.assertEqual(persistence['skipped_duplicates'], 1)

        stored = Transaction.objects.filter(session_id=self.session_id)
        self.assertEqual(stored.count(), 2)
        transfers = [t for t in stored if t.amount == Decimal('10000.00')]
        self.assertEqual(len(transfers), 1)
        # The original row is preserved, untouched.
        self.assertEqual(transfers[0].normalized_merchant, LEGACY_MERCHANT)
        self.assertEqual(transfers[0].id, legacy_row.id)

    def test_02_the_current_representation_is_recognised_by_the_same_path(self):
        # The current build stores the canonical label; the identity mapping is
        # what connects both representations.
        self.assertEqual(
            transfer_identity(LEGACY_MERCHANT),
            transfer_identity(CURRENT_MERCHANT),
        )
        row = self._store_legacy_row()
        response = self._import()
        self.assertEqual(response.json()['persistence']['skipped_duplicates'], 1)
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id, id=row.id).count(), 1
        )

    def test_03_ordinary_transactions_keep_their_exact_merchant_identity(self):
        # A re-import of an ordinary statement is still skipped by the
        # fingerprint, and a different merchant is never collapsed.
        first = self._import()
        self.assertEqual(first.json()['persistence']['imported'], 2)
        second = self._import()
        self.assertEqual(second.json()['persistence']['imported'], 0)
        self.assertEqual(second.json()['persistence']['skipped_duplicates'], 2)
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id).count(), 2
        )

    def test_04_a_different_merchant_with_the_same_amount_is_not_collapsed(self):
        snapshot, _ = FinancialSnapshot.objects.get_or_create(session_id=self.session_id)
        Transaction.objects.create(
            snapshot=snapshot,
            session_id=self.session_id,
            transaction_date=date(2026, 10, 5),
            amount=Decimal('10000.00'),
            transaction_type='DEBIT',
            normalized_merchant='Big Bazaar Groceries',
            category='Uncategorized',
            source_type=Transaction.SOURCE_IMPORT,
            fingerprint='legacy-other-merchant',
        )
        response = self._import()
        # The transfer is imported (it is a different transaction), the ordinary
        # row is not duplicated.
        self.assertEqual(response.json()['persistence']['imported'], 2)
        self.assertEqual(response.json()['persistence']['skipped_duplicates'], 0)
        self.assertEqual(
            Transaction.objects.filter(session_id=self.session_id).count(), 3
        )

    def test_05_two_different_own_account_movements_are_both_kept(self):
        snapshot, _ = FinancialSnapshot.objects.get_or_create(session_id=self.session_id)
        Transaction.objects.create(
            snapshot=snapshot,
            session_id=self.session_id,
            transaction_date=date(2026, 10, 5),
            amount=Decimal('10000.00'),
            transaction_type='DEBIT',
            normalized_merchant=LEGACY_MERCHANT,
            category='Uncategorized',
            source_type=Transaction.SOURCE_IMPORT,
            fingerprint='legacy-self',
        )
        # A different own-account movement (Self Ac) on the same day and amount
        # is a separate transaction and must not be collapsed into the legacy one.
        self.client.post(
            '/api/v1/data/parse-statement/',
            {
                'raw_text': (
                    'Date,Description,Debit,Credit,Balance\n'
                    '2026-10-05,UPI/SELF AC/TRANSFER,10000.00,,0.00\n'
                ),
                'format': 'csv', 'persist': 'true', 'session_id': self.session_id,
            },
            format='json',
            HTTP_X_SESSION_TOKEN=self.token,
        )
        transfers = Transaction.objects.filter(
            session_id=self.session_id, amount=Decimal('10000.00')
        )
        self.assertEqual(transfers.count(), 2)
        self.assertEqual(
            sorted(t.normalized_merchant for t in transfers),
            sorted([LEGACY_MERCHANT, 'Self Ac Transfer']),
        )

    def test_06_two_identical_transfers_in_one_statement_are_both_kept(self):
        response = self.client.post(
            '/api/v1/data/parse-statement/',
            {
                'raw_text': (
                    'Date,Description,Debit,Credit,Balance\n'
                    '2026-10-05,UPI/SELF/TRANSFER,10000.00,,0.00\n'
                    '2026-10-05,UPI/SELF/TRANSFER,10000.00,,0.00\n'
                ),
                'format': 'csv', 'persist': 'true', 'session_id': self.session_id,
            },
            format='json',
            HTTP_X_SESSION_TOKEN=self.token,
        )
        self.assertEqual(response.json()['persistence']['imported'], 2)
        self.assertEqual(
            Transaction.objects.filter(
                session_id=self.session_id, amount=Decimal('10000.00')
            ).count(),
            2,
        )

    def test_07_the_fingerprint_of_a_transfer_is_stable(self):
        # The fingerprint of the current representation is deterministic, so a
        # re-import under the current build matches exactly.
        class _Tx:
            transaction_date = date(2026, 10, 5)
            amount = Decimal('10000.00')
            transaction_type = 'DEBIT'
            normalized_merchant = CURRENT_MERCHANT
            reference_id = ''

        first = _compute_fingerprint(self.session_id, _Tx(), 0)
        second = _compute_fingerprint(self.session_id, _Tx(), 0)
        self.assertEqual(first, second)
        # The legacy representation hashes differently - which is exactly why
        # the compatibility path exists.
        legacy_tx = _Tx()
        legacy_tx.normalized_merchant = LEGACY_MERCHANT
        self.assertNotEqual(first, _compute_fingerprint(self.session_id, legacy_tx, 0))


class TransferFinancialAccuracyAfterTask22Tests(TestCase):
    """The financial treatment is unchanged by the two corrections."""

    def setUp(self):
        self.session_id = f'task22_fin_{uuid.uuid4().hex[:8]}'
        self.snapshot, _ = FinancialSnapshot.objects.get_or_create(
            session_id=self.session_id
        )
        rows = [
            (date(2026, 10, 1), 'ACH CRED CLIENT GLOBAL TECH STIPEND', 'CREDIT', '75000.00'),
            (date(2026, 10, 2), 'POS ADOBE SYSTEMS RENEWAL INT US-882194', 'DEBIT', '4200.00'),
            (date(2026, 10, 3), 'SWIGGY ORDER-5551234', 'DEBIT', '5000.00'),
            (date(2026, 10, 5), 'UPI/SELF/TRANSFER', 'DEBIT', '10000.00'),
            (date(2026, 10, 6), 'POS NETFLIX SUBSCRIPTION', 'DEBIT', '649.00'),
            (date(2026, 10, 17), 'UPI/SELF AC/TRANSFER', 'CREDIT', '10000.00'),
            (date(2026, 10, 18), 'REFUND SWIGGY ORDER-5551234', 'CREDIT', '5000.00'),
        ]
        for d, narration, direction, amount in rows:
            Transaction.objects.create(
                snapshot=self.snapshot,
                session_id=self.session_id,
                transaction_date=d,
                amount=Decimal(amount),
                transaction_type=direction,
                normalized_merchant=TransactionNormalizer.extract_merchant(narration),
                category='Uncategorized',
                source_type=Transaction.SOURCE_IMPORT,
            )

    def test_01_internal_transfer_does_not_inflate_expenses_or_income(self):
        res = monthly_budget(self.session_id, 2026, 10)
        # Debits: 4200 + 5000 + 10000 (transfer) + 649 = 19849
        self.assertEqual(Decimal(res['gross_debits']), Decimal('19849.00'))
        self.assertEqual(Decimal(res['debit_transfers']), Decimal('10000.00'))
        self.assertEqual(Decimal(res['gross_living_expenses']), Decimal('9849.00'))
        # The confirmed same-period refund is applied.
        self.assertEqual(Decimal(res['refunds_applied']), Decimal('5000.00'))
        self.assertEqual(Decimal(res['net_living_expenses']), Decimal('4849.00'))
        # The transfer credit is not earned income.
        self.assertEqual(Decimal(res['earned_income']), Decimal('75000.00'))
        self.assertEqual(Decimal(res['credit_breakdown']['transfers']), Decimal('10000.00'))
        self.assertEqual(Decimal(res['savings']), Decimal('70151.00'))

    def test_02_the_overview_reports_the_same_treatment(self):
        from api.insights import compute_imported_session_overview
        overview = compute_imported_session_overview(self.session_id)
        self.assertEqual(Decimal(overview['summary']['monthly_expenses']), Decimal('4849.00'))
        self.assertEqual(Decimal(overview['summary']['monthly_income']), Decimal('75000.00'))
        transfer_rows = [
            row for row in overview['transactions']
            if row['amount'] == '10000.00'
        ]
        self.assertEqual(len(transfer_rows), 2)
        for row in transfer_rows:
            self.assertTrue(row['is_internal_transfer'])
            self.assertEqual(row['merchant'], 'Internal Transfer')
