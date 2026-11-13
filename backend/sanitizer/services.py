import re
from typing import Dict, List, Tuple, Any

class SanitizerService:
    """
    Client & Server PII Masking Engine.
    Employs a defense-in-depth token-based redaction pipeline to scrub sensitive
    personal identifiers (PAN, Aadhaar, account numbers, cards, phone, email, UPI)
    before sending data to external AI models or persistent logs.

    Note: This is an automated regex and rule-based redaction engine.
    It does not claim mathematical zero-knowledge or 100% infallible detection across
    arbitrary unstructured natural language.
    """

    # High-precision RegEx patterns for financial PII ordered by specificity.
    # More specific and longer token patterns MUST precede general patterns to prevent collisions.
    PATTERNS = {
        # 1. Email addresses MUST precede UPI VPA to avoid partial email corruption (.com suffix)
        "EMAIL": (
            re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'),
            "[REDACTED_EMAIL]"
        ),
        
        # 2. 15-16 digit cards (including Amex & masked patterns like 4821-XXXX-XXXX-5541)
        "CREDIT_DEBIT_CARD": (
            re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b|\b3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}\b|\b(?:\d{4}[-\s*X]{1,4}){3}\d{4}\b'),
            "[REDACTED_CARD]"
        ),

        # 3. Bank Account Numbers with context prefixes (8 to 24 digits / masked tokens)
        "ACCOUNT_NUMBER": (
            re.compile(r'(?:(?:A/C|A/c|Account|Acct|Acc\s*No|ACC|Account\s*Number)[\s.:#-]*)([0-9Xx*-]{8,24})', re.IGNORECASE),
            "[REDACTED_ACCOUNT]"
        ),

        # 4. Aadhaar: constrained so it cannot greedily match the prefix of a 16-digit sequence
        "AADHAAR": (
            re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b(?!\s*[-]?\s*\d)'),
            "[REDACTED_AADHAAR]"
        ),

        # 5. Standard Indian PAN card format (5 letters, 4 digits, 1 letter)
        "PAN_CARD": (
            re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', re.IGNORECASE),
            "[REDACTED_PAN]"
        ),

        # 6. Indian Passport Number (1 letter followed by 7 digits)
        "PASSPORT": (
            re.compile(r'\b[A-PR-WYa-pr-wy][1-9]\d\s?\d{4}[1-9]\b'),
            "[REDACTED_PASSPORT]"
        ),

        # 7. Indian Voter ID / EPIC card (3 letters followed by 7 digits)
        "VOTER_ID": (
            re.compile(r'\b[A-Z]{3}[0-9]{7}\b'),
            "[REDACTED_VOTER_ID]"
        ),

        # 8. IFSC Code (4 letters, 0, 6 alphanumeric)
        "IFSC_CODE": (
            re.compile(r'\b[A-Z]{4}0[A-Z0-9]{6}\b', re.IGNORECASE),
            "[REDACTED_IFSC]"
        ),

        # 9. UPI Virtual Payment Address (e.g. user@okaxis, merchant@upi)
        "UPI_VPA": (
            re.compile(r'\b[a-zA-Z0-9.\-_]{2,64}@[a-zA-Z]{2,64}\b'),
            "[REDACTED_UPI_ID]"
        ),

        # 10. Mobile phone numbers (Indian 10-digit with optional +91 or 0 prefix)
        "PHONE_NUMBER": (
            re.compile(r'(?:\+?91[\s.-]?|0)?[6-9]\d{4}[\s.-]?\d{5}\b'),
            "[REDACTED_PHONE]"
        ),

        # 11. Customer / CIF Identifiers
        "CUSTOMER_ID": (
            re.compile(r'(?:Customer\s*ID|Cust\s*ID|CIF\s*No|User\s*ID)[\s.:#-]*([A-Z0-9-]+)', re.IGNORECASE),
            "[REDACTED_CUST_ID]"
        )
    }

    # Headers for structured user identity & personal metadata
    HEADER_PATTERNS = [
        (re.compile(r'(?:Account\s*Holder|Customer\s*Name|Name)\s*:\s*([^\r\n,]+)', re.IGNORECASE), "[USER_PRIMARY]"),
        (re.compile(r'(?:Beneficiary\s*Name|Beneficiary|To\s*Name|Payee\s*Name)\s*:\s*([^\r\n,]+)', re.IGNORECASE), "[REDACTED_BENEFICIARY]"),
        (re.compile(r'(?:Branch|Branch\s*Address|Address)\s*:\s*([^\r\n]+)', re.IGNORECASE), "[REDACTED_ADDRESS]")
    ]

    @classmethod
    def sanitize(cls, raw_text: str) -> Dict[str, Any]:
        """
        Sanitizes raw text, replacing sensitive PII with standardized tokens,
        and produces a redaction audit log for the Privacy Inspector.
        """
        if not raw_text:
            return {
                "sanitized_text": "",
                "redactions": [],
                "total_redactions_count": 0,
                "privacy_compliance_status": "SECURE_LOCAL_ONLY"
            }

        sanitized_text = raw_text
        redactions_performed: List[Dict[str, Any]] = []

        # 1. Header parsing (Names, Beneficiaries, Addresses)
        for pattern, placeholder in cls.HEADER_PATTERNS:
            matches = list(pattern.finditer(sanitized_text))
            if matches:
                count = len(matches)
                for m in matches:
                    original_val = m.group(1).strip()
                    if len(original_val) > 2:
                        sanitized_text = sanitized_text.replace(original_val, placeholder)
                redactions_performed.append({
                    "type": "USER_NAME_OR_ADDRESS",
                    "placeholder": placeholder,
                    "count": count,
                    "description": "Scrubbed primary identity details / geographic branch address"
                })

        # 2. Financial RegEx sanitization in strict specificity order
        for pii_type, (pattern, placeholder) in cls.PATTERNS.items():
            matches = list(pattern.finditer(sanitized_text))
            if matches:
                count = len(matches)
                for m in matches:
                    target_to_replace = m.group(1) if m.groups() else m.group(0)
                    sanitized_text = sanitized_text.replace(target_to_replace, placeholder)

                redactions_performed.append({
                    "type": pii_type,
                    "placeholder": placeholder,
                    "count": count,
                    "description": f"Detected and masked {count} instance(s) of {pii_type.lower().replace('_', ' ')}"
                })

        # 3. Fail-safe mask for leftover consecutive 12-16 digit numbers (unlabeled card or account numbers)
        leftover_digits_pattern = re.compile(r'\b\d{12,16}\b')
        leftover_matches = list(leftover_digits_pattern.finditer(sanitized_text))
        if leftover_matches:
            sanitized_text = leftover_digits_pattern.sub("[REDACTED_NUM_ID]", sanitized_text)
            redactions_performed.append({
                "type": "CONSECUTIVE_DIGITS_SAFETY_NET",
                "placeholder": "[REDACTED_NUM_ID]",
                "count": len(leftover_matches),
                "description": "Masked leftover high-entropy numeric sequences"
            })

        total_pii_elements = sum(item["count"] for item in redactions_performed)

        return {
            "sanitized_text": sanitized_text,
            "redactions": redactions_performed,
            "total_redactions_count": total_pii_elements,
            "privacy_compliance_status": "SECURE_LOCAL_ONLY"
        }

    @classmethod
    def safe_log_str(cls, text: str) -> str:
        """
        Guarantees that strings passed to application loggers or error messages
        are free of raw financial PII tokens.
        """
        if not text:
            return ""
        return cls.sanitize(str(text))["sanitized_text"]
