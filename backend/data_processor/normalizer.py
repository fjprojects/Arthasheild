import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple, List, Set, Dict, Any
import hashlib

from .models import NormalizedTransaction
from .transfers import classify_own_account_transfer
from .errors import StatementParseError

# Regex for currency symbols, commas, and whitespace
CURRENCY_PREFIXES = re.compile(r'^(?:INR|RS\.?|₹|\$|USD)\s*', re.IGNORECASE)
COMMAS_AND_SPACES = re.compile(r'[,\s]')
DR_CR_SUFFIX = re.compile(r'\s*(?:Dr|Cr|DR|CR)\.?\s*$', re.IGNORECASE)

# Standard Indian payment rail prefixes to clean from merchant names
RAIL_PREFIXES = re.compile(
    r'^(?:UPI[\/\-_]|POS\s+|ACH\s+(?:CRED|DEBIT)\s+|NEFT\s+(?:CRED|DEBIT)\s+|'
    r'IMPS[\/\-_]|RTGS[\/\-_]|E\-COMM[\/\-_]|ATM\s+WDL[\/\-_]|BILLDESK[\/\-_]|'
    r'RAZORPAY[\/\-_]|PAYTM[\/\-_]|INFO[\/\-_]|INB[\/\-_]|REV[\/\-_])',
    re.IGNORECASE
)

class TransactionNormalizer:
    """
    Standardizes dates, amounts (using Decimal), transaction directions,
    merchants, and reference IDs. Provides robust transaction deduplication.
    """

    @staticmethod
    def parse_amount(raw_val: Any) -> Tuple[Decimal, Optional[str]]:
        """
        Parses raw amount strings into a precise Decimal and optional direction hint ('DEBIT' | 'CREDIT').
        Handles:
          - Indian numbering system (1,23,456.78)
          - Standard numbering (123,456.78)
          - Dr / Cr suffixes ('500.00 Dr', '15000.00 Cr')
          - Negative numbers (-500.00 or (500.00))
        """
        if raw_val is None:
            raise StatementParseError("Amount cannot be None")

        if isinstance(raw_val, (int, float)):
            val_str = str(raw_val)
        else:
            val_str = str(raw_val).strip()

        if not val_str:
            raise StatementParseError("Empty amount string")

        direction_hint: Optional[str] = None

        # Check for Dr / Cr suffix
        val_clean = val_str
        if re.search(r'\b(?:dr|debit)\b', val_clean, re.IGNORECASE):
            direction_hint = 'DEBIT'
            val_clean = re.sub(r'\b(?:dr|debit)\b', '', val_clean, flags=re.IGNORECASE)
        elif re.search(r'\b(?:cr|credit)\b', val_clean, re.IGNORECASE):
            direction_hint = 'CREDIT'
            val_clean = re.sub(r'\b(?:cr|credit)\b', '', val_clean, flags=re.IGNORECASE)

        # Check for parentheses indicating negative/debit (e.g. '(500.00)')
        if val_clean.startswith('(') and val_clean.endswith(')'):
            direction_hint = 'DEBIT'
            val_clean = val_clean[1:-1].strip()

        # Check for minus sign
        if val_clean.startswith('-'):
            direction_hint = 'DEBIT'
            val_clean = val_clean[1:].strip()
        elif val_clean.startswith('+'):
            direction_hint = 'CREDIT'
            val_clean = val_clean[1:].strip()

        # Strip currency symbols
        val_clean = CURRENCY_PREFIXES.sub('', val_clean).strip()
        # Remove commas and non-breaking spaces
        val_clean = COMMAS_AND_SPACES.sub('', val_clean).strip()

        try:
            decimal_amount = Decimal(val_clean)
            return abs(decimal_amount), direction_hint
        except (InvalidOperation, TypeError):
            # The offending value can be an arbitrary statement cell: it is
            # never included in the error message.
            raise StatementParseError("Unable to parse the amount value.")

    @staticmethod
    def parse_date(raw_date: Any) -> date:
        """
        Parses different date formats into a standard datetime.date.
        Prioritizes Indian Day-Month-Year convention (DD/MM/YYYY, DD-MM-YYYY).
        """
        if isinstance(raw_date, date):
            if isinstance(raw_date, datetime):
                return raw_date.date()
            return raw_date

        if not raw_date:
            raise StatementParseError("Date cannot be empty")

        date_str = str(raw_date).strip()

        # Strip time component if present
        if ' ' in date_str and ('T' in date_str or ':' in date_str):
            date_str = re.split(r'[ T]', date_str)[0].strip()

        # Format candidates in order of Indian banking priority
        FORMATS = [
            "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
            "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
            "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y",
            "%d-%B-%Y", "%d %B %Y",
            "%Y-%m-%d", "%Y/%m/%d",
            "%b %d, %Y", "%B %d, %Y"
        ]

        # Handle uppercase month like 04-OCT-26
        # Title case the month portion
        parts = re.split(r'([/-])', date_str)
        if len(parts) >= 5:
            # e.g. ['04', '-', 'OCT', '-', '26']
            parts[2] = parts[2].capitalize()
            date_str = "".join(parts)

        for fmt in FORMATS:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        # Regex fallback for DD-Mon-YY or DD-Mon-YYYY (e.g. 12Oct26, 02-Oct-2026)
        match = re.match(r'^(\d{1,2})[-/\s]?([A-Za-z]{3,9})[-/\s]?(\d{2,4})$', date_str)
        if match:
            day, mon, year = match.groups()
            if len(year) == 2:
                year = f"20{year}"
            cleaned_str = f"{int(day):02d}-{mon[:3].capitalize()}-{year}"
            try:
                return datetime.strptime(cleaned_str, "%d-%b-%Y").date()
            except ValueError:
                pass

        # The raw cell value can be arbitrary statement content: it is never
        # included in the error message.
        raise StatementParseError("Unrecognized date format.")

    @staticmethod
    def extract_merchant(raw_description: str) -> str:
        """
        Cleans bank statement narrations to extract a recognizable merchant or recipient name.
        """
        if not raw_description:
            return "Unspecified Merchant"

        desc = raw_description.strip()

        # An own-account transfer narration ("UPI/SELF/TRANSFER") would otherwise
        # collapse to a bare "Self" and lose the evidence that this is an
        # internal movement rather than a payment. Keep the reason visible in a
        # stable, self-describing label so the classification stays correct.
        transfer = classify_own_account_transfer(desc)
        if transfer['is_own_account_transfer'] and transfer.get('label'):
            return transfer['label']

        # Strip common payment rail prefixes
        cleaned = RAIL_PREFIXES.sub('', desc).strip()

        # Handle UPI slash pattern: UPI/MERCHANT/ORDER_ID/vpa
        if '/' in cleaned:
            parts = [p.strip() for p in cleaned.split('/') if p.strip()]
            if parts:
                candidate = parts[0]
                # If first part looks like an internal code, check second part
                if len(candidate) <= 3 and len(parts) > 1:
                    candidate = parts[1]
                return candidate.title()

        # Handle 'to SWIGGY' or 'transfer to AMAZON'
        transfer_match = re.search(r'(?:to|at|by|transfer to)\s+([A-Za-z0-9&.\-_ ]{2,30})', desc, re.IGNORECASE)
        if transfer_match:
            candidate = transfer_match.group(1).strip()
            # Stop before Ref or A/C or Bal
            candidate = re.split(r'\b(?:Ref|A\/c|Acct|Bal|UPI|on)\b', candidate, flags=re.IGNORECASE)[0].strip()
            if candidate and len(candidate) > 2:
                return candidate.title()

        # Take first 4 words of cleaned string
        words = cleaned.split()
        if words:
            short_desc = " ".join(words[:4])
            return short_desc.title()

        return desc.title()

    @staticmethod
    def extract_reference_id(raw_text: str) -> Optional[str]:
        """
        Extracts reference numbers (UTR, Ref No, UPI Ref, Cheque No).
        """
        if not raw_text:
            return None

        patterns = [
            r'(?:UPI\s*Ref(?:\s*No)?|Ref\s*No|Reference(?:\s*No)?|Ref|UTR)[\s.:#-]*([A-Za-z0-9]{6,24})',
            r'(?:Txn\s*ID|Transaction\s*ID)[\s.:#-]*([A-Za-z0-9]{6,24})',
            r'\b(?:CHQ|CHEQUE)[\s.:#-]*(\d{6})\b'
        ]

        for pat in patterns:
            match = re.search(pat, raw_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    @classmethod
    def normalize_transaction(
        cls,
        raw_date: Any,
        raw_description: str,
        amount: Any,
        transaction_type: str,
        source: str,
        reference_id: Optional[str] = None,
        available_balance: Optional[Any] = None,
        currency: str = "INR",
        merchant: Optional[str] = None
    ) -> NormalizedTransaction:
        """
        Factory method to construct a validated NormalizedTransaction.
        """
        parsed_date = cls.parse_date(raw_date)
        parsed_amount, dir_hint = cls.parse_amount(amount)

        # Enforce direction
        final_type = (dir_hint or transaction_type).upper().strip()
        if final_type not in ('DEBIT', 'CREDIT'):
            # The supplied type can be arbitrary statement content: it is
            # never included in the error message.
            raise StatementParseError("Invalid transaction type.")

        parsed_balance = None
        if available_balance is not None and str(available_balance).strip():
            try:
                parsed_balance, _ = cls.parse_amount(available_balance)
            except ValueError:
                parsed_balance = None

        if not merchant:
            merchant = cls.extract_merchant(raw_description)

        if not reference_id:
            reference_id = cls.extract_reference_id(raw_description)

        return NormalizedTransaction(
            transaction_id="",  # Auto-generated in __post_init__
            transaction_date=parsed_date,
            description=raw_description.strip(),
            amount=parsed_amount,
            transaction_type=final_type,
            source=source,
            merchant=merchant,
            reference_id=reference_id,
            currency=currency,
            available_balance=parsed_balance,
            raw_source=raw_description
        )

    @staticmethod
    def deduplicate_transactions(transactions: List[NormalizedTransaction]) -> Tuple[List[NormalizedTransaction], int]:
        """
        Deduplicates a parsed statement using reliable identity evidence only:
        Key: (date, amount, transaction_type, reference_id) when a reference exists.

        Rows without a reference are NOT collapsed merely because their date, amount
        and description match: those may be two legitimate identical payments. Such
        rows are preserved here; repeat-import protection is applied later by the
        occurrence-aware import fingerprint in api.views._compute_fingerprint.

        Returns:
            Tuple of (unique_transactions_list, duplicate_count)
        """
        seen_keys: Set[str] = set()
        unique_list: List[NormalizedTransaction] = []
        duplicates_removed = 0

        for tx in transactions:
            ref = (tx.reference_id or "").lower().strip()
            if not ref:
                # No reliable identifier: preserve the row instead of guessing.
                unique_list.append(tx)
                continue

            key = f"{tx.transaction_date.isoformat()}_{tx.amount:.2f}_{tx.transaction_type}_{ref}"

            if key in seen_keys:
                duplicates_removed += 1
                continue

            seen_keys.add(key)
            unique_list.append(tx)

        return unique_list, duplicates_removed

