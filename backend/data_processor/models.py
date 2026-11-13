from dataclasses import dataclass, field, asdict
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from typing import Optional, Dict, Any, List
import uuid
import hashlib

from .errors import StatementParseError

@dataclass
class NormalizedTransaction:
    """
    Canonical representation of a single financial transaction.
    Standardized across CSV statements, PDF statements, TXT dumps, and SMS alerts.
    """
    transaction_id: str
    transaction_date: date
    description: str
    amount: Decimal
    transaction_type: str  # 'DEBIT' | 'CREDIT'
    source: str           # 'STATEMENT_CSV' | 'STATEMENT_PDF' | 'STATEMENT_TXT' | 'SMS_ALERT'
    merchant: Optional[str] = None
    reference_id: Optional[str] = None
    currency: str = "INR"
    available_balance: Optional[Decimal] = None
    category: Optional[str] = "Uncategorized"
    is_recurring: bool = False
    raw_source: Optional[str] = None

    def __post_init__(self):
        # Enforce Decimal amount
        if not isinstance(self.amount, Decimal):
            try:
                self.amount = Decimal(str(self.amount))
            except (InvalidOperation, TypeError, ValueError):
                # The offending value can be arbitrary statement content: it is
                # never included in the error message.
                raise StatementParseError("Invalid transaction amount.")

        # Amount must be non-negative in the normalized record; direction is determined by transaction_type
        if self.amount < Decimal('0'):
            self.amount = abs(self.amount)

        # Enforce transaction_type
        self.transaction_type = self.transaction_type.upper().strip()
        if self.transaction_type not in ('DEBIT', 'CREDIT'):
            # The supplied type can be arbitrary statement content: it is never
            # included in the error message.
            raise StatementParseError("Transaction type must be 'DEBIT' or 'CREDIT'.")

        # Normalize currency
        if not self.currency:
            self.currency = "INR"
        else:
            self.currency = self.currency.upper().strip()

        # Clean strings
        self.description = self.description.strip() if self.description else "Unspecified Transaction"
        if self.merchant:
            self.merchant = self.merchant.strip()
        if self.reference_id:
            self.reference_id = self.reference_id.strip()

        # If transaction_id is empty, generate a deterministic hash
        if not self.transaction_id:
            self.transaction_id = self.generate_hash()

    def generate_hash(self) -> str:
        """
        Generates a deterministic content hash for transaction deduplication.
        """
        ref = (self.reference_id or "").lower().strip()
        desc = (self.merchant or self.description).lower().strip()
        seed = f"{self.transaction_date.isoformat()}_{self.amount:.2f}_{self.transaction_type}_{ref or desc}"
        return hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "amount": float(self.amount),
            "amount_decimal": str(self.amount),
            "transaction_type": self.transaction_type,
            "source": self.source,
            "merchant": self.merchant,
            "reference_id": self.reference_id,
            "currency": self.currency,
            "available_balance": float(self.available_balance) if self.available_balance is not None else None,
            "category": self.category,
            "is_recurring": self.is_recurring,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NormalizedTransaction":
        tx_date = data["transaction_date"]
        if isinstance(tx_date, str):
            tx_date = date.fromisoformat(tx_date)
        
        amount = Decimal(str(data["amount"]))
        balance = Decimal(str(data["available_balance"])) if data.get("available_balance") is not None else None

        return cls(
            transaction_id=data.get("transaction_id", ""),
            transaction_date=tx_date,
            description=data.get("description", ""),
            amount=amount,
            transaction_type=data.get("transaction_type", "DEBIT"),
            source=data.get("source", "UNKNOWN"),
            merchant=data.get("merchant"),
            reference_id=data.get("reference_id"),
            currency=data.get("currency", "INR"),
            available_balance=balance,
            category=data.get("category", "Uncategorized"),
            is_recurring=data.get("is_recurring", False),
            raw_source=data.get("raw_source")
        )

@dataclass
class StatementParseResult:
    """
    Complete output of a parsed bank statement.
    """
    transactions: List[NormalizedTransaction] = field(default_factory=list)
    account_info: Dict[str, Any] = field(default_factory=dict)
    total_debits: Decimal = Decimal('0.00')
    total_credits: Decimal = Decimal('0.00')
    net_flow: Decimal = Decimal('0.00')
    raw_row_count: int = 0
    parsed_count: int = 0
    errors: List[str] = field(default_factory=list)
    format_detected: str = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transactions": [t.to_dict() for t in self.transactions],
            "account_info": self.account_info,
            "total_debits": float(self.total_debits),
            "total_credits": float(self.total_credits),
            "net_flow": float(self.net_flow),
            "raw_row_count": self.raw_row_count,
            "parsed_count": self.parsed_count,
            "errors": self.errors,
            "format_detected": self.format_detected
        }

@dataclass
class SmsParseResult:
    """
    Output of a parsed bank/UPI SMS notification.
    """
    transaction: Optional[NormalizedTransaction] = None
    is_valid: bool = False
    is_ambiguous: bool = False
    rejection_reason: Optional[str] = None
    raw_sms: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction": self.transaction.to_dict() if self.transaction else None,
            "is_valid": self.is_valid,
            "is_ambiguous": self.is_ambiguous,
            "rejection_reason": self.rejection_reason,
            "raw_sms": self.raw_sms
        }

