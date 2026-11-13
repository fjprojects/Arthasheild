"""
Own-account transfer recognition.

Deterministic, evidence-based classification of a bank narration as a movement
between the user's own accounts (a savings-account top-up, an internal sweep,
a UPI transfer to one's own account).

Rules
-----
* The narration is normalised (case folded, punctuation collapsed to spaces) and
  split into the segments banks use to separate the parties of a payment
  (``/``, ``|``, ``\\``, ``>``).
* An own-account transfer is CONFIRMED only when the narration carries
  own-account evidence (a SELF / OWN ACCOUNT marker) *together with* transfer
  evidence (TRANSFER, TFR, FUND TRANSFER, SWEEP ...), either as an explicit
  phrase ("transfer to self") or as two adjacent segments ("UPI/SELF/TRANSFER").
* The bare word "transfer" is never enough, and a bare own-account marker
  ("SELF" on its own) is never enough either: the word SELF without any
  transfer evidence or explicit phrase is ambiguous, so it stays uncertain.
* A further segment that is neither evidence nor structural (a beneficiary
  name, for example) makes the reading ambiguous as well: the narration is
  then UNCERTAIN, even though it mentions an own-account marker.
* Evidence that contradicts an internal movement (a counterparty VPA, a
  transfer fee, a loan/EMI/reimbursement/refund/salary marker) downgrades the
  result to UNCERTAIN: the transaction keeps its conservative classification
  and is explicitly flagged as an ambiguous transfer instead of being presented
  as a certain one.
* No language model is involved: the classification is a pure function of the
  narration text.
"""
import re
from typing import Any, Dict, List, Optional

CONFIDENCE_CONFIRMED = 'confirmed'
CONFIDENCE_UNCERTAIN = 'uncertain'
CONFIDENCE_NONE = 'none'

# Canonical labels used when an own-account transfer is confirmed. They keep
# the *reason* visible in the ledger instead of collapsing to a bare "Self".
# The label is derived from the own-account marker, so "SELF" and "SELF AC"
# movements stay distinguishable (and therefore never collapse into each other).
def _marker_label(marker: str) -> str:
    """Builds the canonical, self-describing label for an own-account marker."""
    return f"{marker.title()} Transfer"


SELF_TRANSFER_LABEL = _marker_label('self')
OWN_ACCOUNT_TRANSFER_LABEL = _marker_label('own account')

# Segments that identify one of the user's own accounts.
_OWN_ACCOUNT_SEGMENTS = frozenset({
    'self', 'self ac', 'self a c', 'self acc', 'self account', 'self accounts',
    'own', 'own ac', 'own a c', 'own acc', 'own account', 'own accounts',
    'same account', 'my account', 'my self', 'myself',
})

# Segments that identify a movement of money between accounts.
_TRANSFER_SEGMENTS = frozenset({
    'transfer', 'tfr', 'trf', 'fund transfer', 'internal transfer',
    'own transfer', 'self transfer', 'neft transfer', 'rtgs transfer',
    'imps transfer', 'upi transfer', 'credit transfer', 'debit transfer',
    'sweep', 'sweep in', 'sweep out', 'sweep in cr', 'sweep out dr',
    'sweep to', 'sweep dr', 'sweep cr', 'auto sweep',
})

# Phrase rules: an explicit own-account statement, evaluated on the normalised
# narration. Each rule names the evidence it matched (never the raw content)
# and the own-account marker it is based on.
_CONFIRMED_PHRASE_RULES = (
    ('SELF_TRANSFER_PHRASE', re.compile(r'\bself\s+transfer\b'), 'self'),
    ('TRANSFER_TO_SELF_PHRASE', re.compile(r'\btransfer(?:s)?\s+(?:to|from)\s+self\b'), 'self'),
    ('TFR_TO_SELF_PHRASE', re.compile(r'\btfr\s+(?:to|from)\s+self\b'), 'self'),
    ('FUND_TRANSFER_SELF_PHRASE', re.compile(r'\bfund\s+transfer\s+(?:to\s+|from\s+)?self\b'), 'self'),
    ('UPI_TO_SELF_PHRASE', re.compile(r'\bupi\s+(?:to|from)\s+self\b'), 'self'),
    ('SELF_UPI_PHRASE', re.compile(r'\bself\s+upi\b'), 'self'),
    ('SELF_AC_PHRASE', re.compile(r'\bself\s+(?:a\s*c|ac|acc)\b'), 'self ac'),
    ('SELF_ACCOUNT_PHRASE', re.compile(r'\bself\s+account\b'), 'self account'),
    ('OWN_ACCOUNT_PHRASE', re.compile(r'\bown\s+account\b'), 'own account'),
    ('OWN_AC_PHRASE', re.compile(r'\bown\s+(?:a\s*c|ac|acc)\b'), 'own ac'),
    ('TRANSFER_TO_OWN_PHRASE', re.compile(r'\b(?:transfer|tfr)\s+(?:to|from)\s+own\b'), 'own account'),
    ('INTRA_BANK_TRANSFER_PHRASE', re.compile(r'\bintra\s*[- ]?\s*bank\s+transfer\b'), None),
    ('INTER_ACCOUNT_PHRASE', re.compile(r'\binter\s*[- ]?\s*account\b'), None),
    ('LINKED_ACCOUNT_PHRASE', re.compile(r'\blinked\s+account\b'), None),
    ('SWEEP_PHRASE', re.compile(r'\b(?:auto\s+sweep|sweep\s+(?:in|out|dr|cr|to))\b'), None),
)

# Terms that contradict an own-account movement: a charge on a transfer is a
# real expense, and a loan / reimbursement / refund / salary movement is not
# an internal transfer.
_CONTRADICTION_TERMS = (
    'fee', 'fees', 'charge', 'charges', 'commission', 'penalty',
    'emi', 'loan', 'loans', 'disbursement', 'disbursed',
    'reimbursement', 'reimburse', 'claim', 'settlement',
    'refund', 'refunds', 'reversal', 'cashback', 'chargeback', 'rfd', 'returned',
    'salary', 'payroll', 'remuneration', 'stipend', 'wages', 'incentive', 'bonus',
    'interest', 'dividend', 'coupon', 'maturity',
    'insurance', 'premium', 'payout', 'advance',
)

# Evidence of a *counterparty* (not the user): a VPA or email address. Every
# UPI narration carries the payee's VPA, so its presence contradicts an
# own-account reading. A masked account token ("XX..4821") is the account
# holder's own account and therefore supports it.
_COUNTERPARTY_EVIDENCE_RE = re.compile(r'@', re.IGNORECASE)

# Terms that indicate the narration talks about a transfer at all.
_TRANSFER_SIGNAL_RE = re.compile(
    r'\btransfer(?:s|ring|red)?\b|\btfr\b|\btrf\b|\bsweep\b|\bself\b|\bown\b',
    re.IGNORECASE,
)

_RAIL_SPLIT_RE = re.compile(r'[|/\\>]')
_NON_ALNUM_RE = re.compile(r'[^a-z0-9]+')
_WHITESPACE_RE = re.compile(r'\s+')


def normalize_narration(text: str) -> str:
    """Case-folds the narration and collapses punctuation to single spaces."""
    if not text:
        return ''
    return _WHITESPACE_RE.sub(' ', _NON_ALNUM_RE.sub(' ', str(text).lower())).strip()


def narration_segments(text: str) -> List[str]:
    """
    Splits a narration into the segments banks use to separate parties.

    ``UPI/SELF/TRANSFER`` -> ``['upi', 'self', 'transfer']``
    """
    if not text:
        return []
    segments = []
    for raw in _RAIL_SPLIT_RE.split(str(text)):
        normalized = normalize_narration(raw)
        if normalized:
            segments.append(normalized)
    return segments


def _has_contradiction(normalized: str) -> bool:
    padded = f" {normalized} "
    for term in _CONTRADICTION_TERMS:
        if f" {term} " in padded or padded.startswith(f" {term} "):
            return True
        # also catch a plural/singular glued form such as "emiloan"
    return any(term in normalized for term in ('reimburs', 'chargeback', 'cashback'))


def _has_counterparty_evidence(text: str) -> bool:
    return bool(_COUNTERPARTY_EVIDENCE_RE.search(text or ''))


# ---------------------------------------------------------------------------
# Structural vocabulary
# ---------------------------------------------------------------------------
# Words that describe the STRUCTURE of a payment narration rather than a party.
# A segment built only from these words (or from a reference, an amount or a
# masked account token) cannot name a beneficiary, so it never blocks an
# own-account confirmation. This is deliberately an allowlist of structural
# words - not a personal-name pattern, which would misfire on merchants.
_STRUCTURAL_SEGMENTS = frozenset({
    # rails and channels
    'upi', 'pos', 'neft', 'imps', 'rtgs', 'ach', 'nach', 'ft', 'dd', 'atm',
    'card', 'debit card', 'credit card', 'net banking', 'netbanking', 'i2i',
    # direction and payment words
    'transfer', 'transfers', 'tfr', 'trf', 'fund', 'fund transfer', 'sweep',
    'sweep in', 'sweep out', 'sweep to', 'sweep dr', 'sweep cr', 'auto sweep',
    'in', 'out', 'to', 'from', 'by', 'via', 'for', 'and', 'the', 'of', 'a',
    'debit', 'credit', 'dr', 'cr', 'paid', 'payment', 'payments', 'self',
    # account and ownership words
    'account', 'acc', 'ac', 'a c', 'bank', 'banking', 'inter', 'linked',
    'internal', 'intra', 'primary', 'secondary', 'current', 'savings', 'salary',
    'fd', 'rd', 'recurring', 'deposit', 'own', 'my', 'same',
    # reference and amount words
    'ref', 'refs', 'reference', 'order', 'ord', 'txn', 'transaction', 'utr',
    'rrn', 'chq', 'cheque', 'receipt', 'id', 'no', 'num', 'number', 'code',
    'amount', 'amt', 'inr', 'rs', 'rupees', 'value', 'narration',
    'particulars', 'remarks', 'description', 'details', 'charges', 'fee',
})

# A segment that opens with a reference keyword carries a reference, not a party.
_REFERENCE_SEGMENT_RE = re.compile(
    r'^(?:order|ord|ref|reference|txn|transaction|utr|rrn|chq|cheque|id|inv|invoice)'
    r'[\s:#._/-]*',
    re.IGNORECASE,
)

# A masked account token ("XX..4821", "**4821") identifies an account, not a party.
_MASKED_ACCOUNT_SEGMENT_RE = re.compile(r'(?:X{2,}|\*{2,})[.\- ]*\d{3,}', re.IGNORECASE)


def _is_structural_segment(segment: str) -> bool:
    """True when a segment cannot name a beneficiary."""
    if not segment:
        return True
    if segment in _STRUCTURAL_SEGMENTS:
        return True
    if not re.search(r'[a-z]', segment):
        # Digits only: an amount or a reference.
        return True
    if _REFERENCE_SEGMENT_RE.match(segment):
        return True
    if _MASKED_ACCOUNT_SEGMENT_RE.search(segment):
        return True
    return False


def _is_evidence_segment(segment: str) -> bool:
    """True when a segment carries the own-account / transfer evidence itself."""
    if segment in _OWN_ACCOUNT_SEGMENTS or segment in _TRANSFER_SEGMENTS:
        return True
    for _rule, pattern, _label in _CONFIRMED_PHRASE_RULES:
        if pattern.search(segment):
            return True
    return False


def _possible_beneficiary_segments(segments: List[str]) -> List[str]:
    """
    Returns the segments that could name an additional beneficiary.

    A segment that is neither evidence (an own-account marker, a transfer verb
    or an explicit own-account phrase) nor structural (a rail word, a
    reference, an amount, a masked account token) is treated as a possible
    counterparty. Its presence downgrades an otherwise confirmed own-account
    transfer to ``uncertain``.
    """
    return [
        segment for segment in segments
        if not _is_evidence_segment(segment) and not _is_structural_segment(segment)
    ]


def own_account_marker(text: str) -> Optional[str]:
    """
    Returns the own-account marker a narration or merchant carries, or None.

    The marker is what makes a movement an own-account one ("SELF", "SELF AC",
    "OWN ACCOUNT"). It is resolved independently of the confirmation decision:
    a bare marker is too ambiguous to classify as a confirmed internal
    transfer, but it still belongs to the own-account family, which the import
    deduplication needs in order to recognise the same transaction across
    builds.
    """
    raw = str(text or '').strip()
    normalized = normalize_narration(raw)
    if not normalized:
        return None

    segments = narration_segments(raw)
    for segment in segments:
        if segment in _OWN_ACCOUNT_SEGMENTS:
            return segment
    for _rule, pattern, marker in _CONFIRMED_PHRASE_RULES:
        if marker and pattern.search(normalized):
            return marker
    return None


def transfer_identity(merchant: str) -> Optional[str]:
    """
    Returns the version-independent identity of an own-account transfer merchant.

    The identity is derived from the own-account *marker* the narration carried,
    so the representations written by different builds resolve to the same
    value:

    * ``Self`` (written by an older build) and ``Self Transfer`` (written now)
      both denote a transfer marked ``SELF``.
    * ``Self Ac`` and ``Self Ac Transfer`` both denote a ``SELF AC`` transfer.
    * ``Own Account`` and ``Own Account Transfer`` both denote an
      ``OWN ACCOUNT`` transfer.

    Every other merchant returns ``None``: merchant identity is never globally
    ignored, and two different own-account movements keep different identities.
    """
    marker = own_account_marker(merchant)
    if not marker:
        return None
    return re.sub(r'[^A-Z0-9]+', '_', marker.upper()).strip('_')


def classify_own_account_transfer(text: str) -> Dict[str, Any]:
    """
    Classifies a narration as an own-account transfer.

    Returns a dict with:
      * ``is_own_account_transfer`` - True only for a CONFIRMED own-account
        transfer. Every other case is False (conservative).
      * ``confidence`` - ``confirmed`` / ``uncertain`` / ``none``.
      * ``evidence`` - the identifier of the rule that matched (never the raw
        narration, so the result is safe to log or serialize).
      * ``label`` - the canonical label for a confirmed own-account transfer.
      * ``marker`` - the own-account marker the evidence was based on.
    """
    raw = str(text or '').strip()
    normalized = normalize_narration(raw)
    result = {
        'is_own_account_transfer': False,
        'confidence': CONFIDENCE_NONE,
        'evidence': None,
        'label': None,
        'marker': None,
    }
    if not normalized:
        return result

    segments = narration_segments(raw)

    marker_positions = [i for i, seg in enumerate(segments) if seg in _OWN_ACCOUNT_SEGMENTS]
    transfer_positions = [i for i, seg in enumerate(segments) if seg in _TRANSFER_SEGMENTS]

    has_own_evidence = bool(marker_positions)
    has_transfer_evidence = bool(transfer_positions)
    contradicted = _has_contradiction(normalized) or _has_counterparty_evidence(raw)
    # A further beneficiary/counterparty segment makes the reading ambiguous
    # unless the narration states the own-account movement explicitly.
    beneficiaries = _possible_beneficiary_segments(segments)

    # 1. Explicit own-account phrases ("transfer to self", "self transfer",
    #    "own account"). Evaluated on the normalised narration, independently of
    #    how the bank separated the parties.
    for rule, pattern, marker in _CONFIRMED_PHRASE_RULES:
        if not pattern.search(normalized):
            continue
        if contradicted:
            result.update(confidence=CONFIDENCE_UNCERTAIN, evidence=f'{rule}_CONTRADICTED')
            return result
        if beneficiaries:
            # The phrase states an own-account movement, but a further segment
            # could name a beneficiary: the reading stays uncertain.
            result.update(
                confidence=CONFIDENCE_UNCERTAIN,
                evidence=f'{rule}_POSSIBLE_BENEFICIARY',
            )
            return result
        result.update(
            is_own_account_transfer=True,
            confidence=CONFIDENCE_CONFIRMED,
            evidence=rule,
            marker=marker,
            label=_marker_label(marker) if marker else None,
        )
        return result

    # 2. Structured segment evidence: an own-account marker next to a transfer
    #    segment ("UPI/SELF/TRANSFER").
    if (
        has_own_evidence
        and has_transfer_evidence
        and any(abs(m - t) <= 1 for m in marker_positions for t in transfer_positions)
    ):
        if contradicted:
            result.update(
                confidence=CONFIDENCE_UNCERTAIN,
                evidence='OWN_ACCOUNT_MARKER_SEGMENT_CONTRADICTED',
            )
            return result
        if beneficiaries:
            # "UPI/SELF/TRANSFER" plus a further segment that is not structural
            # (a name, for instance) is ambiguous: conservative.
            result.update(
                confidence=CONFIDENCE_UNCERTAIN,
                evidence='OWN_ACCOUNT_MARKER_SEGMENT_POSSIBLE_BENEFICIARY',
            )
            return result
        marker = segments[marker_positions[0]]
        result.update(
            is_own_account_transfer=True,
            confidence=CONFIDENCE_CONFIRMED,
            evidence='OWN_ACCOUNT_MARKER_SEGMENT',
            marker=marker,
            label=_marker_label(marker),
        )
        return result

    # 3. A transfer that cannot be proven internal stays conservative.
    if has_transfer_evidence or _TRANSFER_SIGNAL_RE.search(normalized):
        result.update(confidence=CONFIDENCE_UNCERTAIN, evidence='TRANSFER_WITHOUT_OWN_EVIDENCE')
        return result

    return result


def is_own_account_transfer(text: str) -> bool:
    """Convenience predicate: True only for a confirmed own-account transfer."""
    return classify_own_account_transfer(text)['is_own_account_transfer']
