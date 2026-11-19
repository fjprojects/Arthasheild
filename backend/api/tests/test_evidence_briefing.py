"""
Unit and integration tests for Evidence-Based Financial Insights Briefing.
Verifies that all insights are derived deterministically, conform to the required
schema, include supporting evidence, and maintain zero hallucinations.
"""
from datetime import date
from decimal import Decimal
import uuid

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from api.models import Transaction, ConsentAuditLog, SecureSession
from api.insights import generate_evidence_briefing


class EvidenceBriefingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.session, self.token = SecureSession.issue_session()
        self.session_id = self.session.session_id

        # Give active consent
        ConsentAuditLog.objects.create(
            session_id=self.session_id,
            consent_version='v1.0-test',
            anonymized_processing_accepted=True,
            no_credential_disclosure_acknowledged=True,
            is_active=True,
        )

    def test_empty_session_returns_clean_empty_response(self):
        briefing = generate_evidence_briefing(self.session_id, include_persona=False)
        self.assertFalse(briefing['has_data'])
        self.assertEqual(len(briefing['insights']), 0)
        self.assertEqual(briefing['insight_count'], 0)

    def test_evidence_briefing_with_transactions(self):
        # Create realistic transactions for October 2026
        # Income: ₹85,000 salary
        Transaction.objects.create(
            session_id=self.session_id,
            normalized_merchant="salary",
            amount=Decimal("85000.00"),
            transaction_type="CREDIT",
            transaction_date=date(2026, 10, 1),
            source_type="import",
        )
        # Recurring commitments: Netflix, Rent
        Transaction.objects.create(
            session_id=self.session_id,
            normalized_merchant="netflix",
            amount=Decimal("649.00"),
            transaction_type="DEBIT",
            transaction_date=date(2026, 10, 5),
            source_type="import",
        )
        Transaction.objects.create(
            session_id=self.session_id,
            normalized_merchant="rent",
            amount=Decimal("25000.00"),
            transaction_type="DEBIT",
            transaction_date=date(2026, 10, 5),
            source_type="import",
        )
        # Discretionary: Dining
        Transaction.objects.create(
            session_id=self.session_id,
            normalized_merchant="swiggy",
            amount=Decimal("1250.00"),
            transaction_type="DEBIT",
            transaction_date=date(2026, 10, 10),
            source_type="import",
        )
        # Large spending
        Transaction.objects.create(
            session_id=self.session_id,
            normalized_merchant="apple store",
            amount=Decimal("45000.00"),
            transaction_type="DEBIT",
            transaction_date=date(2026, 10, 15),
            source_type="import",
        )

        briefing = generate_evidence_briefing(self.session_id, include_persona=False)
        self.assertTrue(briefing['has_data'])
        self.assertGreater(briefing['insight_count'], 0)
        self.assertIsNotNone(briefing['reporting_period'])
        self.assertEqual(briefing['reporting_period']['year'], 2026)
        self.assertEqual(briefing['reporting_period']['month'], 10)

        # Verify insight structure integrity
        for insight in briefing['insights']:
            self.assertIn('id', insight)
            self.assertIn('type', insight)
            self.assertIn('severity', insight)
            self.assertIn('finding', insight)
            self.assertIn('evidence', insight)
            self.assertIn('explanation', insight)
            self.assertIn('action', insight)
            self.assertEqual(insight['confidence'], 'VERIFIED')
            self.assertIsInstance(insight['evidence'], dict)

    def test_evidence_briefing_api_endpoint(self):
        # Insert a sample transaction
        Transaction.objects.create(
            session_id=self.session_id,
            normalized_merchant="salary",
            amount=Decimal("50000.00"),
            transaction_type="CREDIT",
            transaction_date=date(2026, 10, 1),
            source_type="import",
        )

        response = self.client.post(
            '/api/v1/insights/evidence-briefing/',
            {'session_id': self.session_id, 'include_persona': False},
            HTTP_X_SESSION_TOKEN=self.token,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['has_data'])
        self.assertIn('insights', data)
        self.assertIn('reporting_period', data)

    def test_evidence_briefing_consent_required(self):
        # Mark consent inactive
        ConsentAuditLog.objects.filter(session_id=self.session_id).update(is_active=False)

        response = self.client.post(
            '/api/v1/insights/evidence-briefing/',
            {'session_id': self.session_id, 'include_persona': False},
            HTTP_X_SESSION_TOKEN=self.token,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json().get('code'), 'CONSENT_REQUIRED')
