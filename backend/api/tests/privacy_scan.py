"""
Shared privacy leak scanner for API response regressions.

Every string in an API response is checked against two groups of patterns:

1. **Local patterns** - narration fragments, redaction markers and reference
   numbers that are not PII shapes but must never survive into a "safe"
   response (for example ``Payment to `` or ``UPI/``).

2. **Production patterns** - taken directly from
   ``sanitizer.services.SanitizerService.PATTERNS``. These are the very
   compiled regexes the application uses to redact PII, so the positive-control
   tests exercise the production detection logic instead of a private copy
   that could silently drift away from it.

Opaque system-generated identifiers (UUIDs) are skipped by the shape scan: a
randomly generated UUID can contain a 10-digit run that is indistinguishable
from an Indian phone number (measured collision rate: ~0.33% per UUID).
Identifiers are not user data, so skipping them removes a false positive
without weakening detection of real PII in any other value.
"""
import re

from sanitizer.services import SanitizerService

# Narrative/marker shapes that must never appear in a serialized response.
LOCAL_PATTERNS = [
    ('phone', re.compile(r'(?<!\d)[6-9]\d{9}(?!\d)')),
    ('email_or_vpa', re.compile(r'[\w.+-]+@[\w.-]+')),
    ('pan', re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b')),
    ('aadhaar', re.compile(r'\b\d{4}\s\d{4}\s\d{4}\b')),
    ('marker', re.compile(r'REDACTED|USER_PRIMARY', re.IGNORECASE)),
    ('reference', re.compile(r'\b(?:ORD[- ]?5555|REF[- ]?777|PAY[- ]?\d{3})\b', re.IGNORECASE)),
    ('narration', re.compile(r'UPI/|REFUND |Payment to |A/C |NEFT ', re.IGNORECASE)),
]

# The production detector, reused verbatim (no copy, no drift).
PRODUCTION_PATTERNS = [
    (f'prod_{name.lower()}', pattern)
    for name, (pattern, _placeholder) in SanitizerService.PATTERNS.items()
]

SENSITIVE_PATTERNS = LOCAL_PATTERNS + PRODUCTION_PATTERNS

UUID_VALUE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE
)


def is_opaque_identifier(value: str) -> bool:
    """True for system-generated identifiers, which carry no user data."""
    return bool(UUID_VALUE.match(value.strip()))


# Patterns that describe *unredacted label* content. A display label must never
# contain a redaction marker or a raw narration fragment.
#
# A sanitized free-text echo (an SMS body, a statement preview) legitimately
# contains both: the sanitizer's own placeholders ("[REDACTED_ACCOUNT]") and the
# payment-rail words around them ("A/C [REDACTED_ACCOUNT]"). The 'redacted'
# scan mode therefore skips these two patterns for such echoes, while every
# identifier-shape check (phone, PAN, VPA, email, Aadhaar, account, card and
# the other production patterns) still applies. The default 'strict' mode is
# unchanged.
LABEL_ONLY_PATTERNS = ('marker', 'narration')


def response_leaks(payload, mode: str = 'strict'):
    """
    Returns (path, pattern-name) for every sensitive match in any string value.

    The walk covers every branch of the response tree, so a leak nested in a
    list, a dict or a deep key cannot escape the scan.

    mode='strict'   - every pattern applies (structured / label responses).
    mode='redacted' - the label-only patterns are skipped, for responses that
                      deliberately carry the sanitizer's own redaction markers.
    """
    skip = set(LABEL_ONLY_PATTERNS) if mode == 'redacted' else set()
    hits = []

    def walk(value, path):
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, f'{path}.{key}')
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f'{path}[{index}]')
        elif isinstance(value, str):
            if is_opaque_identifier(value):
                return
            for name, pattern in SENSITIVE_PATTERNS:
                if name in skip:
                    continue
                if pattern.search(value):
                    hits.append((path, name))

    walk(payload, '$')
    return hits
