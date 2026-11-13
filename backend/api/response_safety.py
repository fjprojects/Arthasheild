"""
Response-boundary privacy layer for financial ingestion endpoints.

Uploaded statements, SMS bodies and parser diagnostics are untrusted input that
can carry personal names and financial identifiers. This module is the single
place where such content is turned into a form that is safe to serialize, so
no ingestion endpoint has to re-implement the rules.

Guarantees
----------
* Stored data is never modified here. Raw narrations remain available for the
  financial calculations, matching and reconciliation that need them.
* A serialized field never echoes the original content. When a safe label
  cannot be established, a generic label is returned instead.
* Financial facts (amount, date, direction, balances, totals) are preserved
  exactly, so reconciliation and refund matching keep working.
* Internal identifiers (transaction id, session id) are preserved: they carry
  no personal information and are required for API operations.

Documented limitation
---------------------
Personal-name detection in *free text* is heuristic: a name that is not
attached to an explicit person context ("paid to", "from", "beneficiary",
"UPI/...", "POS/...") can survive inside an echoed message or preview.
Structured fields never rely on that heuristic - they always resolve to a safe
counterparty label. No claim is made that every possible personal name is
removed from arbitrary free text.
"""
import re
from typing import Any, Dict, List, Optional

from sanitizer.services import SanitizerService

from api.insights import (
    _BUSINESS_SIGNAL_RE,
    _MERCHANT_LEXICON_RE,
    _REFERENCE_SUFFIX_RE,
    _brand_key_for,
    _safe_counterparty_label,
)

# ---------------------------------------------------------------------------
# Generic labels and placeholders
# ---------------------------------------------------------------------------
GENERIC_TRANSACTION_LABEL = 'Bank Transaction'
PERSON_PLACEHOLDER = '[REDACTED_PERSON]'
MASKED_ACCOUNT_LABEL = 'XX..XXXX'
DEFAULT_ERROR_MESSAGE = 'Unable to process the request.'


# A personal name that follows an explicit person context. The context keywords
# are matched case-insensitively; the name itself must be written in title case,
# which keeps SHOUTED merchant tokens ("SWIGGY") out.
_PERSON_CONTEXT_RE = re.compile(
    r'\b(?P<context>(?i:'
    r'payment\s+to|paid\s+to|sent\s+to|transferred\s+to|credited\s+to|debited\s+to|'
    r'received\s+from|dear|hello|hi|for|beneficiary|payee|account\s*holder|holder\s*name|'
    r'upi|pos|neft|imps|rtgs|ach|nach|from|to'
    r'))(?P<sep>[\s/:.\-]{1,3})(?P<name>(?:[A-Z][a-z]+\s+){1,2}[A-Z][a-z]+)\b'
)

# A greeting that opens with a name: "Rahul Sharma, INR 500 has been debited".
_LEADING_NAME_RE = re.compile(
    r'^(?P<name>(?:[A-Z][a-z]+\s+){1,2}[A-Z][a-z]+)\s*(?=[,;:])'
)

# Words that look like a name but never are. Masking them would corrupt an
# otherwise useful message ("Dear Customer", "Total Amount").
_GENERIC_NAME_WORDS = frozenset({
    'customer', 'user', 'member', 'sir', 'madam', 'valued', 'team', 'all',
    'total', 'closing', 'opening', 'balance', 'date', 'transaction', 'statement',
    'amount', 'debit', 'credit', 'ref', 'utr', 'rrn', 'order', 'invoice', 'upi',
    'neft', 'imps', 'rtgs', 'payment', 'salary', 'transfer', 'transferring',
    'account', 'beneficiary', 'payee', 'holder', 'bank', 'card', 'aadhaar', 'pan',
    'vpa', 'available', 'avl', 'bal', 'particulars', 'narration', 'remarks',
    'dear', 'hello', 'hi', 'sms', 'alert', 'info', 'fyi', 'note', 'indian',
    'rupees', 'inr', 'rs', 'account', 'self', 'your',
})

# Masked account tokens such as "XX..4821" or "**4821".
_MASKED_ACCOUNT_TOKEN_RE = re.compile(r'\b(?:X{2,}|\*{2,})[.\- ]*\d{3,}\b')

# One-time passwords, PINs and passcodes are credentials. The app never asks
# for them and must never echo one back.
_CREDENTIAL_RE = re.compile(
    r'\b(?P<label>otp|pin|passcode|password|security\s*code|auth\s*code|'
    r'verification\s*code|cvv|atm\s*pin)'
    r'(?P<sep>[^\w]{0,3}(?:(?:is|was|has|had)\b)?[^\w]{0,3})'
    r'(?P<value>\d{4,8}|(?=[^\s]{0,12}\d)[A-Za-z0-9@#$%^&*!]{6,12})\b',
    re.IGNORECASE,
)
CREDENTIAL_PLACEHOLDER = '[REDACTED_OTP]'

# "Row 12: ..." style parser diagnostics: the row number is safe, the content is not.
_ROW_DIAGNOSTIC_RE = re.compile(r'^\s*Row\s+(\d+)\s*:\s*(?P<detail>.*)$', re.IGNORECASE)


def _is_generic_phrase(name: str) -> bool:
    """True when a name-shaped phrase contains a word that is never a name."""
    words = {word.strip('.,;:').lower() for word in (name or '').split()}
    return bool(words & _GENERIC_NAME_WORDS)


def _is_person_name(name: str) -> bool:
    """
    True when a name-shaped phrase looks like a personal name.

    A phrase is *not* a personal name when it contains a word that never names
    a person ("Account Holder"), when it resolves to a recognized brand
    ("Swiggy"), when it is in the demo merchant lexicon, or when it carries a
    business signal ("Rahul Sharma Technologies"). This reuses the canonical
    brand map, the merchant lexicon and the business vocabulary that the insight
    engine already applies, so a recognized merchant is never mistaken for a
    person.
    """
    if not name:
        return False
    if _is_generic_phrase(name):
        return False
    if _brand_key_for(name):
        return False
    if _MERCHANT_LEXICON_RE.search(name):
        return False
    if _BUSINESS_SIGNAL_RE.search(name):
        return False
    return True


def mask_person_names(text: str) -> str:
    """
    Replaces personal names that follow an explicit person context.

    Heuristic by design: only title-case names introduced by a person keyword
    (or opening a message as a greeting) are masked, and recognized brands and
    business names are always preserved.
    """
    if not text:
        return ''

    def _replace(match):
        name = match.group('name')
        if not _is_person_name(name):
            return match.group(0)
        return f"{match.group('context')}{match.group('sep')}{PERSON_PLACEHOLDER}"

    masked = _PERSON_CONTEXT_RE.sub(_replace, text)

    def _replace_leading(match):
        name = match.group('name')
        if not _is_person_name(name):
            return match.group(0)
        return f"{PERSON_PLACEHOLDER}{masked[match.end('name'):]}"

    return _LEADING_NAME_RE.sub(_replace_leading, masked)


def strip_references(text: str) -> str:
    """
    Removes transaction / order / invoice reference identifiers from free text.

    Only keyword-anchored references are removed ("Ref 1234", "ORD-9824219",
    "Invoice No. INV-2026-7781"), so ordinary amounts and dates survive.
    """
    if not text:
        return ''
    cleaned = _REFERENCE_SUFFIX_RE.sub(' ', text)
    return re.sub(r'\s+', ' ', cleaned).strip()


def safe_free_text(text: str) -> str:
    """
    Converts untrusted free text (an SMS body, a statement preview) into
    display-safe text: identifiers redacted, credentials masked, references
    removed, personal names in a person context masked, and masked account
    tokens dropped.
    """
    if not text:
        return ''
    cleaned = SanitizerService.sanitize(text)['sanitized_text']
    cleaned = _CREDENTIAL_RE.sub(
        lambda m: f"{m.group('label')}{m.group('sep')}{CREDENTIAL_PLACEHOLDER}",
        cleaned,
    )
    cleaned = strip_references(cleaned)
    cleaned = _MASKED_ACCOUNT_TOKEN_RE.sub(' ', cleaned)
    cleaned = mask_person_names(cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()


def safe_error_message(error: Any, fallback: str = DEFAULT_ERROR_MESSAGE) -> str:
    """
    Converts an exception (or an arbitrary diagnostic) into a controlled
    message that cannot carry source content.

    The exception type and category are preserved; identifiers are redacted and
    personal names are masked. No traceback is ever included.
    """
    text = str(error or '').strip()
    if not text:
        return fallback
    cleaned = SanitizerService.sanitize(text)['sanitized_text']
    cleaned = mask_person_names(cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return fallback
    return cleaned


def safe_parse_errors(errors: Optional[List[Any]]) -> List[str]:
    """
    Builds controlled parser warnings.

    The row number is kept (it identifies the problem without exposing it); the
    row content is never reproduced, even if a parser ever puts it there.
    """
    safe: List[str] = []
    for item in errors or []:
        match = _ROW_DIAGNOSTIC_RE.match(str(item))
        if match:
            safe.append(f"Row {match.group(1)}: Failed to extract a valid transaction.")
        else:
            safe.append(safe_error_message(item, 'A statement row could not be parsed.'))
    return safe


def display_mask_breakdown(original: str, masked: str) -> Dict[str, int]:
    """
    Counts what the display layer removed on top of the sanitizer.

    The sanitization preview uses this to keep its redaction audit honest: a
    user can see that names and references were masked for the response.
    """
    return {
        'person_names': (masked or '').count(PERSON_PLACEHOLDER),
        'references': len(_REFERENCE_SUFFIX_RE.findall(original or '')),
        'masked_account_tokens': len(_MASKED_ACCOUNT_TOKEN_RE.findall(original or '')),
        'credentials': (masked or '').count(CREDENTIAL_PLACEHOLDER),
    }


def safe_account_info(account_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Builds safe account metadata.

    No account digits leave the ingestion boundary: a masked account number is
    reported without any digit. Bank names and IFSC codes are public branch
    identifiers and are preserved.
    """
    safe: Dict[str, Any] = {}
    for key, value in (account_info or {}).items():
        if key == 'masked_account_number':
            safe[key] = MASKED_ACCOUNT_LABEL
        elif isinstance(value, str):
            safe[key] = SanitizerService.sanitize(value)['sanitized_text']
        else:
            safe[key] = value
    return safe


def safe_transaction_payload(transaction: Any) -> Dict[str, Any]:
    """
    Builds the serialized payload for one parsed transaction.

    Financial facts are preserved exactly. The identity fields become a safe
    display label, and the transaction reference is not exposed: a reference is
    a financial identifier, not a value the client needs.
    """
    payload = transaction.to_dict()
    label = _safe_counterparty_label(
        (getattr(transaction, 'merchant', None) or getattr(transaction, 'description', None) or '')
    )
    payload['merchant'] = label
    payload['description'] = label
    payload['reference_id'] = None
    return payload


def safe_statement_payload(result: Any) -> Dict[str, Any]:
    """
    Builds the serialized payload of a parsed statement.

    Totals, row counts and the detected format are preserved; transactions,
    warnings and account metadata are converted to their safe forms.
    """
    payload = result.to_dict()
    payload['transactions'] = [
        safe_transaction_payload(tx) for tx in getattr(result, 'transactions', []) or []
    ]
    payload['errors'] = safe_parse_errors(getattr(result, 'errors', None))
    payload['account_info'] = safe_account_info(getattr(result, 'account_info', None))
    return payload
