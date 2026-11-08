import uuid
import secrets
import hashlib
from datetime import timedelta
from typing import Tuple, Optional
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class SecureSession(models.Model):
    """
    Server-issued, cryptographically secure session entity.
    Binds financial records to a verified session owner and prevents IDOR / session spoofing.
    """
    session_id = models.CharField(max_length=64, unique=True, db_index=True)
    token_hash = models.CharField(max_length=64, db_index=True)  # SHA-256 of raw secret token
    created_at = models.DateTimeField(auto_now_add=True)
    last_active_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    is_revoked = models.BooleanField(default=False)

    SESSION_LIFETIME_HOURS = 24

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "revoked" if self.is_revoked else ("expired" if self.is_expired else "active")
        return f"SecureSession [{self.session_id}] ({status})"

    @classmethod
    def hash_token(cls, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

    @classmethod
    def issue_session(cls, custom_session_id: Optional[str] = None) -> Tuple["SecureSession", str]:
        """
        Issues a cryptographically unpredictable session and high-entropy secret token.
        """
        raw_token = secrets.token_urlsafe(32)
        token_hash = cls.hash_token(raw_token)
        session_id = custom_session_id or f"sec_{secrets.token_hex(16)}"
        expires_at = timezone.now() + timedelta(hours=cls.SESSION_LIFETIME_HOURS)

        session = cls.objects.create(
            session_id=session_id,
            token_hash=token_hash,
            expires_at=expires_at,
            is_revoked=False
        )
        return session, raw_token

    def rotate_token(self) -> str:
        """
        Rotates the session credential, invalidating the old token.
        """
        new_raw_token = secrets.token_urlsafe(32)
        self.token_hash = self.hash_token(new_raw_token)
        self.expires_at = timezone.now() + timedelta(hours=self.SESSION_LIFETIME_HOURS)
        self.save(update_fields=['token_hash', 'expires_at', 'last_active_at'])
        return new_raw_token

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at


class ConsentAuditLog(models.Model):
    """
    Explicit User Consent Log.
    Tracks privacy consent timestamps, policy versions, and withdrawal status
    under DPDP / GDPR principles.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    session_id = models.CharField(max_length=128, blank=True)
    consent_version = models.CharField(max_length=20, default="v1.0")
    anonymized_processing_accepted = models.BooleanField(default=False)
    no_credential_disclosure_acknowledged = models.BooleanField(default=False)
    consented_at = models.DateTimeField(auto_now_add=True)
    # Withdrawal support (Phase 1.2)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-consented_at']

    def __str__(self):
        status = "active" if self.is_active else "withdrawn"
        return f"Consent {self.consent_version} [{status}] - {self.consented_at.strftime('%Y-%m-%d %H:%M')}"


class FinancialSnapshot(models.Model):
    """
    Deterministic financial health summary for a session.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    session_id = models.CharField(max_length=128, blank=True)
    liquid_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    monthly_income = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    monthly_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    fixed_commitments = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    monthly_leakage_detected = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    health_score = models.IntegerField(default=50)
    health_grade = models.CharField(max_length=30, default="B (Stable)")
    emergency_runway_months = models.FloatField(default=1.0)
    safe_to_spend_daily = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    safe_to_spend_weekly = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Snapshot [{self.session_id}] score={self.health_score}"


class Transaction(models.Model):
    """
    Pseudonymized, scrubbed transaction record.
    Never contains raw personal identifiers or bank credentials.
    source_type distinguishes synthetic persona data from real imports.
    fingerprint provides deterministic deduplication across multiple imports.
    """
    SOURCE_IMPORT = 'import'
    SOURCE_PERSONA = 'persona'
    SOURCE_CHOICES = [(SOURCE_IMPORT, 'Import'), (SOURCE_PERSONA, 'Persona')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snapshot = models.ForeignKey(
        FinancialSnapshot,
        on_delete=models.CASCADE,
        related_name='transactions',
        null=True,
        blank=True
    )
    session_id = models.CharField(max_length=128, blank=True)
    transaction_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(
        max_length=10,
        choices=[('DEBIT', 'Debit'), ('CREDIT', 'Credit')]
    )
    normalized_merchant = models.CharField(max_length=120)
    category = models.CharField(max_length=80, default="Uncategorized")
    is_recurring = models.BooleanField(default=False)
    is_leak = models.BooleanField(default=False)
    hidden_fee_estimate = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    risk_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Phase 1.2: deduplication fingerprint
    fingerprint = models.CharField(max_length=64, blank=True, db_index=True)
    # Phase 1.2.1: source separation
    source_type = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_IMPORT)

    class Meta:
        ordering = ['-transaction_date']
        constraints = [
            models.UniqueConstraint(
                fields=['session_id', 'fingerprint'],
                name='unique_tx_per_session',
                condition=models.Q(fingerprint__gt='')  # Only enforce when fingerprint is non-empty
            )
        ]

    def __str__(self):
        return f"{self.transaction_type} ₹{self.amount} @ {self.normalized_merchant} [{self.transaction_date}]"


class DecisionScenario(models.Model):
    """
    What-If EMI and Purchase Simulator records.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_id = models.CharField(max_length=128, blank=True)
    item_name = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    tenure_months = models.IntegerField(default=12)
    down_payment = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    nominal_apr = models.FloatField(default=0.0)
    true_effective_apr = models.FloatField(default=0.0)
    monthly_outflow = models.DecimalField(max_digits=12, decimal_places=2)
    total_hidden_fees = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    is_viable = models.BooleanField(default=True)
    verdict = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"EMI Scenario: {self.item_name} ₹{self.price}"
