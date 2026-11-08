import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple

from .models import NormalizedTransaction, SmsParseResult
from .normalizer import TransactionNormalizer

# Strict anti-promotional and anti-OTP filters
NON_TRANSACTION_PATTERNS = [
    (re.compile(r'\b(?:otp|one\s*time\s*password|verification\s*code|secret\s*code)\b', re.IGNORECASE), "OTP / Authentication alert"),
    (re.compile(r'\b(?:apply\s*now|pre-approved|pre\s*approved|congratulations|click\s*here|hurry|offer|loan\s*up\s*to)\b', re.IGNORECASE), "Promotional / Marketing alert"),
    (re.compile(r'\b(?:statement\s*is\s*generated|e-statement|bill\s*is\s*generated|total\s*due|minimum\s*due)\b', re.IGNORECASE), "Credit card statement bill notice (not an individual transaction debit/credit)"),
    (re.compile(r'\b(?:mandate\s*status|e-mandate\s*registered|standing\s*instruction\s*created)\b', re.IGNORECASE), "Mandate administration alert"),
    (re.compile(r'^(?:your\s+available\s+balance|balance\s+enquiry|avl\s+bal\s+for\s+a/c)\b', re.IGNORECASE), "Balance enquiry alert (no debit/credit executed)"),
]

# Patterns to identify transaction direction
DEBIT_KEYWORDS = re.compile(
    r'\b(?:debited|debit|spent|paid|withdrawn|sent|transferred\s*to|dr\.?)\b',
    re.IGNORECASE
)
CREDIT_KEYWORDS = re.compile(
    r'\b(?:credited|credit|received|deposited|refunded|added\s*to|cr\.?)\b',
    re.IGNORECASE
)

# Pattern to capture transaction amount
# e.g. INR 480.00, Rs. 1,200.00, Rs.1200, Rs 75,000.00, ₹480
AMOUNT_PATTERN = re.compile(
    r'(?:INR|Rs\.?|₹)\s*(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\b',
    re.IGNORECASE
)

# Pattern to capture Available Balance
BALANCE_PATTERN = re.compile(
    r'(?:Avl\s*Bal|Available\s*Bal(?:ance)?|Bal(?:ance)?|Avail\s*Bal)[\s.:]*(?:INR|Rs\.?|₹)?\s*(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\b',
    re.IGNORECASE
)

# Pattern to capture Date in SMS
# e.g. on 04-OCT-26, on 12-10-2026, on 12Oct26, on 16-OCT-2026
DATE_PATTERN = re.compile(
    r'\b(?:on|dated)?\s*(\d{1,2}[-/](?:[A-Za-z]{3,9}|\d{1,2})[-/]\d{2,4}|\d{1,2}[A-Za-z]{3}\d{2,4})\b',
    re.IGNORECASE
)

# Pattern to capture UPI ID
UPI_VPA_PATTERN = re.compile(r'\b([a-zA-Z0-9.\-_]{2,64}@[a-zA-Z]{2,64})\b')

# Pattern to capture Reference / UTR
REF_PATTERN = re.compile(
    r'(?:UPI\s*Ref(?:\s*No)?|Ref\s*(?:No)?|Reference(?:\s*No)?|UTR|Txn\s*ID|Info)[\s.:#-]*([A-Za-z0-9\-_]{6,25})',
    re.IGNORECASE
)

class BankSmsParser:
    """
    Parser for Indian Bank & UPI SMS alerts.
    Converts unstructured notification messages into standardized NormalizedTransaction records.
    Defensively rejects promotional, OTP, or ambiguous non-transaction messages.
    """

    @classmethod
    def parse_sms(cls, sms_text: str, default_date: Optional[date] = None) -> SmsParseResult:
        """
        Parses a single SMS notification text.
        """
        if not sms_text or not sms_text.strip():
            return SmsParseResult(
                transaction=None,
                is_valid=False,
                is_ambiguous=True,
                rejection_reason="Empty SMS text",
                raw_sms=sms_text
            )

        text = sms_text.strip()

        # 1. Filter out promotional, OTP, or informational non-transaction messages
        for pattern, reason in NON_TRANSACTION_PATTERNS:
            if pattern.search(text):
                return SmsParseResult(
                    transaction=None,
                    is_valid=False,
                    is_ambiguous=True,
                    rejection_reason=reason,
                    raw_sms=text
                )

        # 2. Extract transaction direction (Debit vs Credit)
        is_debit = bool(DEBIT_KEYWORDS.search(text))
        is_credit = bool(CREDIT_KEYWORDS.search(text))

        if is_debit and is_credit:
            # Handle conflict (e.g. "debited... if not done, credit will be reversed")
            # The earliest keyword usually indicates the event
            debit_pos = DEBIT_KEYWORDS.search(text).start()
            credit_pos = CREDIT_KEYWORDS.search(text).start()
            direction = 'DEBIT' if debit_pos < credit_pos else 'CREDIT'
        elif is_debit:
            direction = 'DEBIT'
        elif is_credit:
            direction = 'CREDIT'
        else:
            return SmsParseResult(
                transaction=None,
                is_valid=False,
                is_ambiguous=True,
                rejection_reason="No debit or credit transaction action detected",
                raw_sms=text
            )

        # 3. Extract transaction amount
        # First, find available balance so we don't confuse balance with transaction amount
        bal_match = BALANCE_PATTERN.search(text)
        avail_balance: Optional[Decimal] = None
        bal_span = (-1, -1)
        if bal_match:
            try:
                avail_balance, _ = TransactionNormalizer.parse_amount(bal_match.group(1))
                bal_span = bal_match.span()
            except ValueError:
                pass

        # Find amounts that do not overlap with the balance match
        amt_matches = list(AMOUNT_PATTERN.finditer(text))
        tx_amount: Optional[Decimal] = None

        for m in amt_matches:
            # Check if this match is inside balance span
            if bal_span[0] != -1 and m.start() >= bal_span[0] and m.end() <= bal_span[1]:
                continue
            try:
                parsed_amt, _ = TransactionNormalizer.parse_amount(m.group(1))
                if parsed_amt > Decimal('0'):
                    tx_amount = parsed_amt
                    break
            except ValueError:
                continue

        if not tx_amount:
            return SmsParseResult(
                transaction=None,
                is_valid=False,
                is_ambiguous=True,
                rejection_reason="Could not determine financial transaction amount",
                raw_sms=text
            )

        # 4. Extract transaction date
        tx_date = default_date or date.today()
        date_match = DATE_PATTERN.search(text)
        if date_match:
            try:
                tx_date = TransactionNormalizer.parse_date(date_match.group(1))
            except ValueError:
                pass

        # 5. Extract merchant / recipient / VPA
        merchant = cls._extract_sms_merchant(text, direction)

        # 6. Extract Reference / UTR
        ref_id = None
        ref_match = REF_PATTERN.search(text)
        if ref_match:
            ref_id = ref_match.group(1).strip()

        # Build NormalizedTransaction
        norm_tx = NormalizedTransaction(
            transaction_id="",
            transaction_date=tx_date,
            description=f"SMS: {text[:100]}",
            amount=tx_amount,
            transaction_type=direction,
            source="SMS_ALERT",
            merchant=merchant,
            reference_id=ref_id,
            currency="INR",
            available_balance=avail_balance,
            raw_source=text
        )

        return SmsParseResult(
            transaction=norm_tx,
            is_valid=True,
            is_ambiguous=False,
            rejection_reason=None,
            raw_sms=text
        )

    @classmethod
    def parse_batch(cls, sms_list: List[str], default_date: Optional[date] = None) -> Tuple[List[NormalizedTransaction], List[SmsParseResult], int]:
        """
        Parses a list of SMS notifications, deduplicating valid transactions.
        Returns:
            Tuple of (unique_valid_transactions, all_results, duplicate_count)
        """
        all_results: List[SmsParseResult] = []
        raw_txs: List[NormalizedTransaction] = []

        for sms in sms_list:
            if not sms or not sms.strip():
                continue
            res = cls.parse_sms(sms, default_date=default_date)
            all_results.append(res)
            if res.is_valid and res.transaction:
                raw_txs.append(res.transaction)

        unique_txs, dups = TransactionNormalizer.deduplicate_transactions(raw_txs)
        return unique_txs, all_results, dups

    @classmethod
    def _extract_sms_merchant(cls, text: str, direction: str) -> str:
        """
        Extracts merchant, UPI recipient, or sender from SMS body.
        """
        # 1. Check for UPI VPA
        vpa_match = UPI_VPA_PATTERN.search(text)
        if vpa_match:
            vpa = vpa_match.group(1)
            # e.g. swiggy@icici -> Swiggy
            prefix = vpa.split('@')[0]
            if len(prefix) > 2 and not prefix.isdigit():
                return prefix.replace('.', ' ').replace('-', ' ').title()
            return vpa

        # 2. Patterns like "to SWIGGY", "at FIGMA", "from STARTUP LABS", "by GLOBEX CORP"
        if direction == 'DEBIT':
            match = re.search(r'\b(?:to|at|towards)\s+([A-Za-z0-9&.\-_ ]{2,30})', text, re.IGNORECASE)
        else:
            match = re.search(r'\b(?:from|by)\s+([A-Za-z0-9&.\-_ ]{2,30})', text, re.IGNORECASE)

        if match:
            candidate = match.group(1).strip()
            # Stop before keywords like Ref, on, A/c, Avl, via
            candidate = re.split(r'\b(?:Ref|on|A\/c|Acct|Avl|via|using|UPI)\b', candidate, flags=re.IGNORECASE)[0].strip()
            # Clean punctuation
            candidate = candidate.strip(".,;: -_")
            if len(candidate) > 2:
                return candidate.title()

        return "UPI/Bank Transfer"

