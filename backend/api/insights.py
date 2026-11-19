from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timedelta
import calendar
from collections import defaultdict
from typing import List, Dict, Any, Tuple, Optional
import re

from django.db.models import Sum, Q

from .models import Transaction, ConsentAuditLog, FinancialSnapshot
from data_processor.transfers import (
    CONFIDENCE_CONFIRMED,
    classify_own_account_transfer,
)

# ---------------------------------------------------------------------------
# Helper: simple keyword-based categorization
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS = {
    'food': [
        'swiggy', 'zomato', 'restaurant', 'cafe', 'food', 'meal', 'pizza',
        'burger', 'dine', 'biryani', 'tiffin', 'dhaba',
        'zepto', 'blinkit', 'groceries', 'grocery', 'chaipoint', 'chai point',
        'bigbasket', 'dunzo', 'instamart',
    ],
    'shopping': [
        'flipkart', 'myntra', 'shopping', 'store', 'retail', 'clothing',
        'apparel', 'meesho', 'ajio', 'nykaa',
    ],
    'travel': [
        'airline', 'flight', 'uber', 'ola', 'taxi', 'rail', 'train', 'hotel',
        'booking', 'makemytrip', 'irctc', 'goibibo', 'indigo',
    ],
    'bills': [
        'electricity', 'water', 'gas', 'utility', 'bill', 'telecom', 'mobile',
        'internet', 'broadband', 'postpaid', 'maintenance',
    ],
    # Rent is a distinct financial category, not a generic utility bill. It is
    # placed before ``bills`` so keyword fallback keeps the two separate.
    'rent_housing': [
        'rent', 'landlord', 'apartment', 'housing', 'tenancy', 'to-let',
        'house rent', 'flat rent', 'room rent', 'society rent',
    ],
    'salary': ['salary', 'payroll', 'remuneration', 'salary credited', 'salary credit'],
    'emi': ['emi', 'loan', 'mortgage', 'installment'],
    'subscriptions': [
        'netflix', 'spotify', 'prime', 'subscription', 'membership', 'saas',
        'gym', 'adobe', 'figma', 'openai', 'chatgpt', 'github', 'copilot',
        'aws', 'cloud', 'hotstar', 'youtube premium', 'notion', 'dropbox',
    ],
    'healthcare': [
        'hospital', 'clinic', 'pharmacy', 'medicine', 'doctor', 'lab',
        'health', 'apollo', 'practo', '1mg', 'pharmeasy',
    ],
}

_REFUND_STRIP_TERMS = {
    'refund', 'reversal', 'cashback', 'chargeback', 'rfd', 'returned', 'return',
    'order', 'cancelled', 'canceled', 'rev', 'auto', 'credit', 'debit', 'cr', 'dr',
    'pos', 'upi', 'payment', 'payout', 'store', 'retail', 'ltd', 'pvt', 'private',
    'limited', 'india', 'in', 'online', 'services', 'corp', 'bill', 'pay', 'txn',
    'transaction', 'transfer', 'tfr', 'supermarket', 'delivery', 'orders',
    'general_refund', 'merchant', 'ref', 'reference', 'ord',
    # Category terms -- matching solely on broad categories is strictly forbidden
    'shopping', 'food', 'travel', 'bills', 'rent housing', 'rent_housing',
    'healthcare', 'subscriptions', 'emi', 'salary', 'other'
}

# ---------------------------------------------------------------------------
# Orthogonal Refund Intelligence Dimensions
# ---------------------------------------------------------------------------
# 1. Match Confidence
MATCH_CONFIRMED = 'CONFIRMED'
MATCH_PROBABLE = 'PROBABLE'
MATCH_WEAK = 'WEAK'
MATCH_UNMATCHED = 'UNMATCHED'

# 2. Allocation Status
ALLOC_APPLIED = 'APPLIED'
ALLOC_SUGGESTED_NOT_APPLIED = 'SUGGESTED_NOT_APPLIED'
ALLOC_NOT_ALLOCATED = 'NOT_ALLOCATED'

# 3. Temporal Relation
TEMPORAL_SAME_PERIOD = 'SAME_PERIOD'
TEMPORAL_CROSS_MONTH = 'CROSS_MONTH'

# ---------------------------------------------------------------------------
# Recurring Payment Detection Dimensions
# ---------------------------------------------------------------------------
# Payment Types
PAYMENT_TYPE_SUBSCRIPTION = 'subscription'
PAYMENT_TYPE_RENT = 'rent'
PAYMENT_TYPE_EMI = 'emi_or_loan'
PAYMENT_TYPE_INSURANCE = 'insurance'
PAYMENT_TYPE_UTILITY = 'utility'
PAYMENT_TYPE_OTHER = 'other_recurring_payment'
PAYMENT_TYPE_UNKNOWN = 'unknown_recurring_payment'

# Cadences
CADENCE_WEEKLY = 'weekly'
CADENCE_FORTNIGHTLY = 'fortnightly'
CADENCE_MONTHLY = 'monthly'
CADENCE_QUARTERLY = 'quarterly'
CADENCE_ANNUAL = 'annual'
CADENCE_IRREGULAR = 'irregular'

# Confidence
RECURRING_CONFIRMED = 'CONFIRMED'
RECURRING_PROBABLE = 'PROBABLE'
RECURRING_WEAK = 'WEAK'

# Amount Variation
VARIATION_FIXED = 'fixed'
VARIATION_LOW = 'low_variance'
VARIATION_VARIABLE = 'variable'

# ---------------------------------------------------------------------------
# Commitment classes (Task 23)
# ---------------------------------------------------------------------------
# A repeated transaction is not automatically a subscription or a financial
# commitment. These four classes keep the ideas apart:
#
#   subscription_commitment  - a recurring payment to a subscription or billing
#                              service (Netflix, ChatGPT Plus, Adobe, a gym
#                              membership). It is a *potentially avoidable*
#                              commitment - the user may cancel it. It is never
#                              described as wasted money: usage is not
#                              observable from a statement.
#   fixed_obligation         - a recurring contractual or predictable obligation
#                              (rent, a loan instalment, insurance, a utility
#                              bill). A financial commitment, but not a
#                              subscription.
#   recurring_discretionary  - repeated ordinary spending at a cafe, restaurant,
#                              supermarket, pharmacy or similar merchant. A
#                              spending pattern, never a commitment.
#   recurring_pattern        - a repeated payment whose counterparty carries no
#                              commitment evidence at all. Observed and reported,
#                              never projected as a commitment.
COMMITMENT_SUBSCRIPTION = 'subscription_commitment'
COMMITMENT_FIXED_OBLIGATION = 'fixed_obligation'
COMMITMENT_DISCRETIONARY = 'recurring_discretionary'
COMMITMENT_PATTERN = 'recurring_pattern'

# Narration that evidences a billing relationship. Matched on word boundaries so
# that ordinary merchant names ("Premium", "Application") cannot match.
_SUBSCRIPTION_EVIDENCE_RE = re.compile(
    r'\b(?:netflix|spotify|hotstar|disney|prime\s*video|amazon\s*prime|youtube\s*premium|'
    r'apple\s*music|itunes|google\s*(?:play|storage|one)|chatgpt|openai|claude|anthropic|'
    r'canva|adobe|playstation|xbox|github|notion|dropbox|icloud|audible|kindle|zee5|'
    r'sonyliv|jiocinema|aha|crunchyroll|subscriptions?|memberships?|'
    r'meal\s*plan|premium\s*plan|monthly\s*plan|annual\s*plan|auto\s*debit|auto\s*renew|'
    r'renewal|billpay|bill\s*desk|gym|fitness)\b',
    re.IGNORECASE,
)

# Narration that evidences a fixed contractual obligation.
_OBLIGATION_EVIDENCE_RE = re.compile(
    r'\b(?:rent|landlord|tenancy|emi|loans?|mortgage|housing\s*finance|insurance|'
    r'electricity|water\s*bill|gas\s*bill|broadband|postpaid|society\s*maintenance|'
    r'maintenance)\b',
    re.IGNORECASE,
)

# Recurring consumables: repeated, but not a commitment and not avoidable.
_CONSUMABLE_EVIDENCE_RE = re.compile(
    r'\b(?:newspaper|newspapers|milk|daily\s*milk|courier|laundry|cleaning)\b',
    re.IGNORECASE,
)

# A membership is a recurring commitment even when the merchant is only
# described as a gym.
_MEMBERSHIP_EVIDENCE_RE = re.compile(
    r'\b(?:gym|fitness|yoga|cult\s*fit|cultfit|gold(?:s)?\s*gym|membership)\b',
    re.IGNORECASE,
)

# Canonical merchant mapping: ordered longest/most specific pattern first
_CANONICAL_BRAND_MAP = [
    # Amazon distinct services - specific sub-brands prioritized
    ('amazon pay', 'amazon_pay'),
    ('amazon marketplace', 'amazon_marketplace'),
    ('amazon fresh', 'amazon_fresh'),
    ('amazon pantry', 'amazon_pantry'),
    ('amazon wholesale', 'amazon_wholesale'),
    ('amazon prime', 'amazon_prime'),
    ('amazon', 'amazon'),
    # Swiggy distinct services
    ('swiggy instamart', 'swiggy_instamart'),
    ('swiggy dineout', 'swiggy_dineout'),
    ('swiggy genie', 'swiggy_genie'),
    ('swiggy minis', 'swiggy_minis'),
    ('swiggy', 'swiggy'),
    # Zomato distinct services
    ('zomato blinkit', 'zomato_blinkit'),
    ('blinkit', 'zomato_blinkit'),
    ('zomato hyperpure', 'zomato_hyperpure'),
    ('zomato', 'zomato'),
    # Flipkart distinct services
    ('flipkart grocery', 'flipkart_grocery'),
    ('flipkart supermart', 'flipkart_grocery'),
    ('flipkart wholesale', 'flipkart_wholesale'),
    ('flipkart', 'flipkart'),
    # Streaming & SaaS
    ('netflix', 'netflix'),
    ('spotify', 'spotify'),
    ('disney hotstar', 'disney_hotstar'),
    ('hotstar', 'disney_hotstar'),
    ('youtube premium', 'youtube_premium'),
    ('youtube', 'youtube'),
    ('apple music', 'apple_music'),
    ('apple.com/bill', 'apple_bill'),
    ('chatgpt', 'chatgpt'),
    ('openai', 'openai'),
    # Utilities & Telecom
    ('bescom', 'bescom'),
    ('tatapower', 'tata_power'),
    ('tata power', 'tata_power'),
    ('bses rajdhani', 'bses_rajdhani'),
    ('bses yamuna', 'bses_yamuna'),
    ('bses', 'bses'),
    ('act fibernet', 'act_fibernet'),
    ('airtel broadband', 'airtel_broadband'),
    ('airtel fiber', 'airtel_broadband'),
    ('airtel postpaid', 'airtel_postpaid'),
    ('airtel dth', 'airtel_dth'),
    ('airtel recharge', 'airtel_recharge'),
    ('airtel', 'airtel'),
    ('jio fiber', 'jio_fiber'),
    ('jiofiber', 'jio_fiber'),
    ('jio postpaid', 'jio_postpaid'),
    ('jio recharge', 'jio_recharge'),
    ('jiocinema', 'jio_cinema'),
    ('jio', 'jio'),
    # Fitness & Memberships
    ('cult fit', 'cult_fit'),
    ('cult.fit', 'cult_fit'),
    ('cultfit', 'cult_fit'),
    ('bb daily', 'bb_daily'),
    ('bbdaily', 'bb_daily'),
    ('country delight', 'country_delight'),
    # Loans & Finance
    ('hdfc home loan', 'hdfc_home_loan'),
    ('hdfc loan', 'hdfc_loan'),
    ('bajaj finance', 'bajaj_finance'),
    # Insurance
    ('lic of india', 'lic'),
    ('lic', 'lic'),
    ('hdfc ergo', 'hdfc_ergo'),
    ('max life', 'max_life'),
    ('icici prudential', 'icici_prudential'),
    ('star health', 'star_health'),
    ('acko', 'acko'),
    ('policybazaar', 'policybazaar'),
    # Known distinct platforms / retailers
    ('reliance digital', 'reliance_digital'),
    ('croma', 'croma'),
    ('myntra', 'myntra'),
    ('bookmyshow', 'bookmyshow'),
    ('makemytrip', 'makemytrip'),
    ('indigo', 'indigo'),
    ('decathlon', 'decathlon'),
    ('nykaa', 'nykaa'),
    ('meesho', 'meesho'),
    ('ajio', 'ajio'),
    ('uber', 'uber'),
    ('ola', 'ola'),
    ('apollo', 'apollo'),
]


def _extract_distinctive_tokens(text: str) -> set:
    """Extract distinctive merchant/counterparty keywords, stripping generic banking & category words."""
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', text.lower())
    tokens = set(cleaned.split())
    return {t for t in tokens if len(t) > 2 and t not in _REFUND_STRIP_TERMS}


def _extract_canonical_merchant(text: str) -> str:
    """
    Extract a canonical merchant identity from narration text.
    Distinguishes sub-brands such as Amazon Marketplace vs Amazon Pay,
    Swiggy Instamart vs Swiggy Dineout, Flipkart Grocery vs Flipkart.
    """
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', text.lower())
    norm_text = f" {' '.join(cleaned.split())} "

    for pattern, canonical in _CANONICAL_BRAND_MAP:
        if f" {pattern} " in norm_text:
            return canonical

    tokens = _extract_distinctive_tokens(text)
    if tokens:
        return sorted(tokens)[0]
    return ''


def _extract_reference_ids(text: str) -> set:
    """
    Extract transaction or order reference codes (e.g. REF#12345, ORD-9988, TXN554, UTR 402812345678).
    Strictly prevents false confirmed matches from:
    - Substring matches inside normal words (e.g., 'paid', 'idea', 'valid', 'solid')
    - Generic 1-3 digit numbers (e.g., 'order 12', 'ref 99')
    - Pure currency amounts or round numbers coincidentally mentioned
    """
    refs = set()
    cleaned = text.lower()

    # Pattern 1: Keywords like ref, reference, ord, order, txn, transaction, utr, rrn
    # Requires word boundary \b at start; tolerates repeated prefixes like Ref REF-123
    p1 = re.findall(r'\b(?:ref|reference|ord|order|txn|transaction|utr|rrn)[\s#:-]*(?:(?:ref|reference|ord|order|txn)[\s#:-]*)*([a-zA-Z0-9]{3,})', cleaned)

    # Pattern 2: Standalone 'id' keyword -- strictly requires explicit separator [#:-] or whitespace
    # and word boundary, preventing false triggers from 'paid', 'idea', 'valid', 'grid'
    p2 = re.findall(r'\bid[\s#:-]+([a-zA-Z0-9]{3,})', cleaned)

    for m in p1 + p2:
        # Must contain at least one digit
        if not any(c.isdigit() for c in m):
            continue
        # Pure numeric codes must be at least 3 digits to prevent coincidental 1-2 digit false matches (e.g. order 12)
        if m.isdigit() and len(m) < 3:
            continue
        refs.add(m)

    return refs


DEBIT_TRANSFER_KEYWORDS = [
    'self transfer', 'own account', 'transfer to self', 'transfer from self',
    'tfr to self', 'tfr from self', 'tfr to own', 'transfer to own',
    'auto sweep', 'sweep out', 'sweep dr', 'sweep-out', 'sweep to fd',
    'sweep to savings', 'inter account', 'inter-account', 'linked account',
    'self ac', 'self a/c', 'fund transfer self', 'intra-bank transfer'
]

# Display label used in the imported-session ledger for a confirmed own-account
# transfer. It names the movement without revealing any counterparty.
INTERNAL_TRANSFER_LABEL = 'Internal Transfer'

# The label is fixed and content-free, so it must survive the display boundary
# unchanged: an internal movement stays identifiable as one.
INTERNAL_TRANSFER_LABELS = frozenset({
    'internal transfer', 'internal account transfer',
})

CREDIT_CLASSIFICATION_RULES = {
    'refund': [
        'refund', 'reversal', 'cashback', 'chargeback', 'rfd', 'returned',
        'return', 'order cancelled', 'rev upi', 'rev pos', 'pos rev',
        'upi rev', 'reversed', 'auto reversal', 'credit reversal'
    ],
    'transfer': [
        'self transfer', 'own account', 'transfer to self', 'transfer from self',
        'tfr to self', 'tfr from self', 'auto sweep', 'sweep in', 'sweep cr',
        'sweep-in', 'inter account', 'inter-account', 'linked account',
        'self ac', 'self a/c', 'fund transfer self', 'intra-bank transfer'
    ],
    'reimbursement': [
        'reimbursement', 'reimburse', 'expense claim', 'claim settlement',
        'insurance claim', 'mediclaim', 'travel claim', 'claim payout',
        'corporate reimbursement', 'official reimbursement', 'medical reimbursement'
    ],
    'investment_yield': [
        'interest credited', 'interest credit', 'int.pd', 'fd interest',
        'savings interest', 'quarterly interest', 'term deposit interest',
        'dividend', 'dividend credited', 'coupon payment', 'interest paid',
        'deposit interest'
    ],
    'capital_liquidation': [
        'mutual fund redemption', 'mf redemption', 'redemption payout',
        'equity sale proceeds', 'stock sale proceeds', 'shares sold',
        'redemption proceeds', 'capital gain payout', 'liquidation proceeds'
    ],
    'investment_transfers': [
        'zerodha', 'groww', 'kuvera', 'upstox', 'angel one', 'paytm money',
        '5paisa', 'icicidirect'
    ],
    'earned_income': [
        'salary', 'payroll', 'remuneration', 'stipend', 'wages',
        'consulting fee', 'client payment', 'client stipend', 'freelance',
        'retainer', 'honorarium', 'payout', 'ach cred client', 'neft cred client',
        'direct deposit', 'salary credit', 'salary credited', 'professional fees',
        'consultancy', 'monthly salary', 'incentive payout', 'bonus credit'
    ],
}

_REFUND_CATEGORY_MAP = {
    'food': ['swiggy', 'zomato', 'restaurant', 'cafe', 'food', 'meal', 'pizza', 'burger', 'dine', 'biryani', 'tiffin', 'dhaba', 'eats'],
    'shopping': ['amazon', 'flipkart', 'myntra', 'shopping', 'store', 'retail', 'clothing', 'apparel', 'meesho', 'ajio', 'nykaa'],
    'travel': ['airline', 'flight', 'uber', 'ola', 'taxi', 'rail', 'train', 'hotel', 'booking', 'makemytrip', 'irctc', 'goibibo', 'indigo'],
    'bills': ['electricity', 'water', 'gas', 'utility', 'bill', 'telecom', 'mobile', 'internet', 'airtel', 'jio', 'broadband', 'bescom', 'tneb'],
    'subscriptions': ['netflix', 'spotify', 'prime', 'subscription', 'membership', 'saas', 'gym', 'hotstar', 'youtube premium', 'chatgpt'],
    'healthcare': ['hospital', 'clinic', 'pharmacy', 'medicine', 'doctor', 'lab', 'health', 'apollo', 'practo', '1mg', 'pharmeasy'],
}


def classify_credit(merchant: str, description: str = "") -> Dict[str, Any]:
    """
    Deterministically classifies incoming credit transactions into:
    - refund: merchant refund/reversal (associated with original spending category)
    - transfer: internal/own-account transfer
    - reimbursement: expense or insurance claim payout
    - investment_yield: FD interest, dividends, coupon payments (passive income)
    - capital_liquidation: mutual fund redemptions, stock sale proceeds (not income)
    - investment_transfers: broker cash withdrawals/transfers (not income)
    - earned_income: genuine salary, wages, business receipts, client payouts
    - unclassified: generic peer UPI or unidentified inflows (NOT counted as earned income)
    """
    text = f"{merchant} {description}".lower()
    # Own-account evidence is computed once and reported on every outcome, so a
    # caller can always tell a confirmed internal movement from an ambiguous one.
    transfer = classify_own_account_transfer(text)

    # 1. Check Refunds
    for kw in CREDIT_CLASSIFICATION_RULES['refund']:
        if kw in text:
            associated_cat = "general_refund"
            for cat, keywords in _REFUND_CATEGORY_MAP.items():
                if any(mkw in text for mkw in keywords):
                    associated_cat = cat
                    break
            return {
                "credit_type": "refund",
                "is_earned_income": False,
                "is_operating_income": False,
                "category": "refund",
                "associated_category": associated_cat,
                "label": "Merchant Refund / Reversal",
                "transfer_confidence": transfer['confidence'],
                "transfer_evidence": transfer['evidence'],
            }

    # 2. Check Internal Transfers (own-account movements are never earned income)
    if transfer['is_own_account_transfer']:
        return {
            "credit_type": "transfer",
            "is_earned_income": False,
            "is_operating_income": False,
            "category": "transfer",
            "associated_category": "internal_transfer",
            "label": "Internal Account Transfer",
            "transfer_confidence": transfer['confidence'],
            "transfer_evidence": transfer['evidence'],
        }

    # Legacy keyword fallback for records stored by earlier versions.
    for kw in CREDIT_CLASSIFICATION_RULES['transfer']:
        if kw in text:
            return {
                "credit_type": "transfer",
                "is_earned_income": False,
                "is_operating_income": False,
                "category": "transfer",
                "associated_category": "internal_transfer",
                "label": "Internal Account Transfer",
                "transfer_confidence": CONFIDENCE_CONFIRMED,
                "transfer_evidence": "LEGACY_KEYWORD",
            }

    # 3. Check Reimbursements
    for kw in CREDIT_CLASSIFICATION_RULES['reimbursement']:
        if kw in text:
            return {
                "credit_type": "reimbursement",
                "is_earned_income": False,
                "is_operating_income": False,
                "category": "reimbursement",
                "associated_category": "expense_reimbursement",
                "label": "Expense Reimbursement",
                "transfer_confidence": transfer['confidence'],
                "transfer_evidence": transfer['evidence'],
            }

    # 4. Check Investment Yield (Passive Income: FD interest, dividends, coupons)
    for kw in CREDIT_CLASSIFICATION_RULES['investment_yield']:
        if kw in text:
            return {
                "credit_type": "investment_yield",
                "is_earned_income": False,
                "is_operating_income": True,
                "category": "investment_yield",
                "associated_category": "investment_yield",
                "label": "Investment Yield (FD / Dividend)",
                "transfer_confidence": transfer['confidence'],
                "transfer_evidence": transfer['evidence'],
            }

    # 5. Check Capital Liquidation (Mutual fund redemptions, stock sale proceeds)
    for kw in CREDIT_CLASSIFICATION_RULES['capital_liquidation']:
        if kw in text:
            return {
                "credit_type": "capital_liquidation",
                "is_earned_income": False,
                "is_operating_income": False,
                "category": "capital_liquidation",
                "associated_category": "capital_liquidation",
                "label": "Capital Liquidation (MF / Equity)",
                "transfer_confidence": transfer['confidence'],
                "transfer_evidence": transfer['evidence'],
            }

    # 6. Check Broker Transfers (Zerodha, Groww cash withdrawals without yield/redemption evidence)
    for kw in CREDIT_CLASSIFICATION_RULES['investment_transfers']:
        if kw in text:
            return {
                "credit_type": "investment_transfers",
                "is_earned_income": False,
                "is_operating_income": False,
                "category": "investment_transfers",
                "associated_category": "broker_transfer",
                "label": "Broker Cash Transfer",
                "transfer_confidence": transfer['confidence'],
                "transfer_evidence": transfer['evidence'],
            }

    # 7. Check Earned Income (Salary, Wages, Client Receipts)
    for kw in CREDIT_CLASSIFICATION_RULES['earned_income']:
        if kw in text:
            return {
                "credit_type": "earned_income",
                "is_earned_income": True,
                "is_operating_income": True,
                "category": "salary",
                "associated_category": "earned_income",
                "label": "Earned Income",
                "transfer_confidence": transfer['confidence'],
                "transfer_evidence": transfer['evidence'],
            }

    # 8. Default: Unclassified Inflow (Generic peer UPI, unidentified credit)
    return {
        "credit_type": "unclassified",
        "is_earned_income": False,
        "is_operating_income": False,
        "category": "unclassified_credit",
        "associated_category": "unclassified_inflow",
        "label": "Unclassified Inflow",
        "transfer_confidence": transfer['confidence'],
        "transfer_evidence": transfer['evidence'],
    }


def classify_debit(merchant: str, description: str = "") -> Dict[str, Any]:
    """
    Classifies outgoing debit transactions:
    - Identifies genuine internal/own-account transfers on the debit side.
    - Excludes identified own-account transfers from living expenses.
    - Does NOT assume unidentified debits are transfers.

    The own-account decision is evidence-based (``data_processor.transfers``):
    a narration is only an internal transfer when it carries an own-account
    marker together with transfer evidence. A transfer that cannot be proven
    internal keeps its conservative classification and is reported as
    ``transfer_confidence='uncertain'`` instead of being presented as certain.
    """
    text = f"{merchant} {description}".lower()
    transfer = classify_own_account_transfer(text)
    if transfer['is_own_account_transfer']:
        return {
            "is_transfer": True,
            "category": "transfer",
            "label": "Internal Account Transfer",
            "transfer_confidence": transfer['confidence'],
            "transfer_evidence": transfer['evidence'],
        }

    # Legacy keyword fallback for records stored by earlier versions.
    for kw in DEBIT_TRANSFER_KEYWORDS:
        if kw in text:
            return {
                "is_transfer": True,
                "category": "transfer",
                "label": "Internal Account Transfer",
                "transfer_confidence": CONFIDENCE_CONFIRMED,
                "transfer_evidence": "LEGACY_KEYWORD",
            }

    cat = _categorize(merchant, 'DEBIT')
    return {
        "is_transfer": False,
        "category": cat,
        "label": category_display_name(cat),
        "transfer_confidence": transfer['confidence'],
        "transfer_evidence": transfer['evidence'],
    }


# ---------------------------------------------------------------------------
# Authoritative category resolution
# ---------------------------------------------------------------------------
# A stored, meaningful category is evidence of how the user (or a verified
# import) labelled a transaction. Keyword inference is only a fallback for
# generic placeholders. Canonical keys keep Rent & Housing separate from bills
# without rewriting the user's precise label at the response boundary.
_GENERIC_CATEGORY_KEYS = {
    '', 'general', 'uncategorized', 'uncategorised', 'unclassified',
    'other', 'unknown', 'none',
}

_CATEGORY_ALIASES = {
    'rent': 'rent_housing',
    'rent & housing': 'rent_housing',
    'rent and housing': 'rent_housing',
    'house rent': 'rent_housing',
    'housing': 'rent_housing',
    'landlord': 'rent_housing',
    'bill': 'bills',
    'bill & utilities': 'bills',
    'bills & utilities': 'bills',
    'utilities': 'bills',
    'emi': 'emi',
    'emi/loan': 'emi',
    'emi_or_loan': 'emi',
    'loan emi': 'emi',
    'bnpl loan': 'emi',
    'salary': 'salary',
    'payroll': 'salary',
    'freelance income': 'freelance_income',
    'internship stipend': 'internship_stipend',
    'allowance': 'allowance',
    'ai tools': 'subscriptions',
    'developer tools': 'subscriptions',
    'software subscriptions': 'subscriptions',
    'subscription': 'subscriptions',
    'health & fitness': 'healthcare',
    'fuel & commute': 'travel',
    'food & dining': 'food',
    'food delivery': 'food',
    'dining out': 'food',
    'groceries': 'food',
    'quick commerce': 'shopping',
    'quick snacks': 'food',
    'books & stationery': 'shopping',
    'education': 'other',
    'entertainment': 'subscriptions',
    'bank fees & fines': 'fees',
}

_CATEGORY_DISPLAY_NAMES = {
    'rent_housing': 'Rent & Housing',
    'subscriptions': 'Subscriptions',
    'healthcare': 'Healthcare',
    'freelance_income': 'Freelance Income',
    'internship_stipend': 'Internship Stipend',
    'emi': 'EMI / Loan',
    'unclassified_credit': 'Unclassified Credit',
}

_EARNED_INCOME_CATEGORY_KEYS = {
    'salary', 'freelance_income', 'internship_stipend', 'allowance',
}


def canonical_category_key(value: Any) -> str:
    """Normalize a stored category into a stable, comparable key."""
    text = str(value or '').strip().lower().replace('_', ' ')
    text = re.sub(r'\s+', ' ', text)
    if not text:
        return ''
    if text in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[text]
    return text.replace(' ', '_')


def category_display_name(key: str) -> str:
    """Return the canonical human-readable label for a category key.

    Existing engine categories are intentionally lowercase for machine
    consumers, while canonical finance categories (notably rent) receive a
    stable human-readable label. Rent must be handled before the generic
    keyword-key check because it is also a classifier key.
    """
    if not key:
        return 'Uncategorized'
    if key == 'rent_housing':
        return 'Rent & Housing'
    if key in set(_CATEGORY_KEYWORDS) | {'refund', 'transfer', 'other'}:
        return key
    return _CATEGORY_DISPLAY_NAMES.get(key, key.replace('_', ' ').title())


def _stored_category_key(tx) -> str:
    return canonical_category_key(getattr(tx, 'category', ''))


def _is_generic_category_key(key: str) -> bool:
    return key in _GENERIC_CATEGORY_KEYS


def resolve_transaction_category(tx) -> str:
    """Resolve one canonical category for a transaction.

    Precedence:
    1. a meaningful stored category (including a human correction),
    2. a deterministic classifier for generic/empty stored categories.

    This prevents a keyword guess from overwriting a verified label such as
    ``Rent & Housing`` or ``Freelance Income`` while still giving uncategorised
    imports a useful category.
    """
    stored_key = _stored_category_key(tx)
    if stored_key and not _is_generic_category_key(stored_key):
        return stored_key

    if getattr(tx, 'transaction_type', '') == 'CREDIT':
        return classify_credit(getattr(tx, 'normalized_merchant', ''))['category']
    return classify_debit(getattr(tx, 'normalized_merchant', ''))['category']


def resolve_credit_classification(tx) -> Dict[str, Any]:
    """Classify a credit, honouring a stored meaningful category.

    Narration rules remain the default, but a stored verified category such as
    ``Freelance Income`` is not demoted to ``unclassified_credit`` merely
    because a short narration lacks a salary keyword.
    """
    info = dict(classify_credit(getattr(tx, 'normalized_merchant', '')))
    stored_key = _stored_category_key(tx)
    has_meaningful_stored = bool(stored_key and not _is_generic_category_key(stored_key))
    is_user_correction = (
        'USER_CORRECTION' in str(getattr(tx, 'risk_note', '') or '').upper()
    )
    info['category_source'] = (
        'USER_CORRECTION' if is_user_correction
        else 'STORED_CATEGORY' if has_meaningful_stored
        else 'NARRATION'
    )

    # A verified label wins over a keyword guess, even when both are
    # meaningful. Narration remains the default only for generic/empty labels.
    if has_meaningful_stored:
        info['category'] = stored_key
        info['label'] = category_display_name(stored_key)

    if stored_key in _EARNED_INCOME_CATEGORY_KEYS and (
        info['credit_type'] == 'unclassified' or is_user_correction
    ):
        info.update({
            'credit_type': 'earned_income',
            'is_earned_income': True,
            'is_operating_income': True,
            'category': stored_key,
            'associated_category': 'earned_income',
            'label': category_display_name(stored_key),
        })
    elif stored_key == 'transfer' and (
        info['credit_type'] == 'unclassified' or is_user_correction
    ):
        info.update({
            'credit_type': 'transfer',
            'is_earned_income': False,
            'is_operating_income': False,
            'category': 'transfer',
            'associated_category': 'internal_transfer',
            'label': 'Internal Account Transfer',
        })
    elif stored_key == 'refund' and (
        info['credit_type'] == 'unclassified' or is_user_correction
    ):
        info.update({
            'credit_type': 'refund',
            'is_earned_income': False,
            'is_operating_income': False,
            'category': 'refund',
            'associated_category': 'general_refund',
            'label': 'Merchant Refund / Reversal',
        })
    elif stored_key == 'reimbursement' and (
        info['credit_type'] == 'unclassified' or is_user_correction
    ):
        info.update({
            'credit_type': 'reimbursement',
            'is_earned_income': False,
            'is_operating_income': False,
            'category': 'reimbursement',
            'associated_category': 'expense_reimbursement',
            'label': 'Expense Reimbursement',
        })
    return info


def _categorize(normalized_merchant: str, transaction_type: str = 'DEBIT') -> str:
    """Return a category based on keyword matching and transaction type."""
    merchant = normalized_merchant.lower()
    if transaction_type.upper() == 'CREDIT':
        return classify_credit(normalized_merchant)['category']

    for kw in DEBIT_TRANSFER_KEYWORDS:
        if kw in merchant:
            return 'transfer'

    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in merchant:
                return cat
    return 'other'


# ---------------------------------------------------------------------------
# 1. Transaction Categorization
# ---------------------------------------------------------------------------
def categorize_transactions(session_id: str, include_persona: bool = False) -> List[Dict[str, Any]]:
    source_type = (
        Transaction.SOURCE_PERSONA if include_persona else Transaction.SOURCE_IMPORT
    )
    qs = Transaction.objects.filter(session_id=session_id, source_type=source_type)
    result = []
    for tx in qs:
        category = resolve_transaction_category(tx)
        if tx.transaction_type == 'CREDIT':
            c_info = resolve_credit_classification(tx)
            credit_type = c_info['credit_type']
            is_earned = c_info['is_earned_income']
            is_transfer = False
            associated_cat = c_info.get('associated_category')
            category_source = c_info.get('category_source', 'NARRATION')
        else:
            d_info = classify_debit(tx.normalized_merchant)
            credit_type = None
            is_earned = False
            is_transfer = d_info['is_transfer']
            associated_cat = None
            stored_key = _stored_category_key(tx)
            category_source = (
                'USER_CORRECTION'
                if 'USER_CORRECTION' in str(getattr(tx, 'risk_note', '') or '').upper()
                else 'STORED_CATEGORY'
                if stored_key and not _is_generic_category_key(stored_key)
                else 'INFERRED_KEYWORD'
            )

        result.append({
            'id': str(tx.id),
            'date': tx.transaction_date.isoformat(),
            'amount': str(tx.amount),
            'type': tx.transaction_type,
            'merchant': _display_counterparty(tx.normalized_merchant),
            'category': category_display_name(category),
            'category_key': category,
            'category_source': category_source,
            'credit_type': credit_type,
            'is_earned_income': is_earned,
            'is_transfer': is_transfer,
            'associated_category': associated_cat,
            'source_type': tx.source_type,
        })
    return result


# ---------------------------------------------------------------------------
# 2. Monthly Budget Analyzer
# ---------------------------------------------------------------------------
def monthly_budget(session_id: str, year: int, month: int, include_persona: bool = False) -> Dict[str, Any]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    source_type = (
        Transaction.SOURCE_PERSONA if include_persona else Transaction.SOURCE_IMPORT
    )
    qs = Transaction.objects.filter(
        session_id=session_id,
        source_type=source_type,
        transaction_date__gte=start,
        transaction_date__lt=end,
    )

    credit_qs = qs.filter(transaction_type='CREDIT')
    debit_qs = qs.filter(transaction_type='DEBIT')

    total_credits = credit_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    earned_income = Decimal('0')
    investment_yield = Decimal('0')
    capital_liquidation = Decimal('0')
    investment_transfers = Decimal('0')
    refunds_total = Decimal('0')
    transfers_total = Decimal('0')
    reimbursements_total = Decimal('0')
    unclassified_total = Decimal('0')

    category_refunds = defaultdict(Decimal)
    refund_tx_list = []

    for tx in credit_qs:
        info = resolve_credit_classification(tx)
        ctype = info['credit_type']
        amt = tx.amount

        if ctype == 'earned_income':
            earned_income += amt
        elif ctype == 'investment_yield':
            investment_yield += amt
        elif ctype == 'capital_liquidation':
            capital_liquidation += amt
        elif ctype == 'investment_transfers':
            investment_transfers += amt
        elif ctype == 'refund':
            refunds_total += amt
            assoc = info.get('associated_category', 'general_refund')
            category_refunds[assoc] += amt
            refund_tx_list.append((tx, assoc))
        elif ctype == 'transfer':
            transfers_total += amt
        elif ctype == 'reimbursement':
            reimbursements_total += amt
        else:
            unclassified_total += amt

    operating_income = earned_income + investment_yield

    gross_debits = debit_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    debit_transfers = Decimal('0')
    cat_spend = defaultdict(Decimal)

    for tx in debit_qs:
        amt = tx.amount
        is_user_transfer = canonical_category_key(tx.category) == 'transfer'
        d_info = classify_debit(tx.normalized_merchant)
        if is_user_transfer or d_info['is_transfer']:
            debit_transfers += amt
            cat_spend['transfer'] += amt
        else:
            cat = resolve_transaction_category(tx)
            cat_spend[cat] += amt

    gross_living_expenses = gross_debits - debit_transfers

    # -------------------------------------------------------------------------
    # Evidence-Aware Refund Allocation Engine
    # -------------------------------------------------------------------------
    lookback_start = start - timedelta(days=180)
    all_candidate_debits_qs = Transaction.objects.filter(
        session_id=session_id,
        source_type=source_type,
        transaction_type='DEBIT',
        transaction_date__gte=lookback_start,
        transaction_date__lt=end
    )

    valid_candidate_debits = [
        d for d in all_candidate_debits_qs
        if not ((d.category and d.category.lower() == 'transfer') or classify_debit(d.normalized_merchant)['is_transfer'])
    ]

    debit_capacity = {str(d.id): d.amount for d in valid_candidate_debits}

    def _evaluate_candidates(r_tx: Transaction, current_capacity: Dict[str, Decimal]) -> Tuple[List[Dict[str, Any]], str, List[str]]:
        r_amt = r_tx.amount
        r_refs = _extract_reference_ids(r_tx.normalized_merchant)
        r_canonical = _extract_canonical_merchant(r_tx.normalized_merchant)
        r_tokens = _extract_distinctive_tokens(r_tx.normalized_merchant)

        scored_candidates = []
        for d in valid_candidate_debits:
            if d.transaction_date > r_tx.transaction_date:
                continue
            cap = current_capacity.get(str(d.id), Decimal('0'))
            if cap <= Decimal('0'):
                continue

            d_refs = _extract_reference_ids(d.normalized_merchant)
            d_canonical = _extract_canonical_merchant(d.normalized_merchant)
            d_tokens = _extract_distinctive_tokens(d.normalized_merchant)

            ref_match = bool(r_refs and (r_refs & d_refs))
            canonical_match = bool(r_canonical and d_canonical and r_canonical == d_canonical)
            token_match = bool(r_tokens and (r_tokens & d_tokens))

            if not (ref_match or canonical_match or token_match):
                continue

            exact_amt = (cap == r_amt or d.amount == r_amt)
            days_diff = (r_tx.transaction_date - d.transaction_date).days
            shared_refs = r_refs & d_refs if ref_match else set()
            shared_tokens = r_tokens & d_tokens if token_match else set()

            score = (1000 if ref_match else 0) + (500 if canonical_match else 0) + (100 if token_match else 0) + (20 if exact_amt else 0) - min(days_diff, 60) * 0.1

            scored_candidates.append({
                'score': score,
                'debit': d,
                'ref_match': ref_match,
                'canonical_match': canonical_match,
                'token_match': token_match,
                'exact_amt': exact_amt,
                'days_diff': days_diff,
                'shared_refs': shared_refs,
                'shared_tokens': shared_tokens,
                'd_canonical': d_canonical,
                'cap': cap,
            })

        if not scored_candidates:
            return [], MATCH_UNMATCHED, ["no_matching_debit_found"]

        scored_candidates.sort(key=lambda x: x['score'], reverse=True)

        tier1_refs = [c for c in scored_candidates if c['ref_match']]
        tier2_canonical = [c for c in scored_candidates if c['canonical_match'] and not c['ref_match']]

        # Case 1: CONFIRMED via reliable shared reference ID
        if tier1_refs:
            best = tier1_refs[0]
            evidence = [
                "shared_reference: matched",
                f"merchant: {_safe_counterparty_label(best['debit'].normalized_merchant)}",
                f"purchase_date: {best['debit'].transaction_date.isoformat()}",
                f"days_apart: {best['days_diff']}",
            ]
            if best['exact_amt']:
                evidence.append("exact_amount_match")
            return [best], MATCH_CONFIRMED, evidence

        # Case 2: Canonical merchant match evaluation
        if tier2_canonical:
            exact_matches = [c for c in tier2_canonical if c['exact_amt']]
            if len(tier2_canonical) == 1:
                best = tier2_canonical[0]
                evidence = [
                    "canonical_merchant: matched",
                    f"purchase_date: {best['debit'].transaction_date.isoformat()}",
                    f"days_apart: {best['days_diff']}",
                    "unique_eligible_purchase",
                ]
                if best['exact_amt']:
                    evidence.append("exact_amount_match")
                return [best], MATCH_PROBABLE, evidence
            elif len(exact_matches) == 1:
                best = exact_matches[0]
                evidence = [
                    "canonical_merchant: matched",
                    f"purchase_date: {best['debit'].transaction_date.isoformat()}",
                    f"days_apart: {best['days_diff']}",
                    "uniquely_identified_by_amount",
                    "exact_amount_match",
                ]
                return [best], MATCH_PROBABLE, evidence
            else:
                evidence = [
                    "canonical_merchant: ambiguous",
                    f"ambiguous_multiple_candidates: {len(tier2_canonical)} eligible purchases found",
                    "manual_review_recommended",
                ]
                return [], MATCH_WEAK, evidence

        # Case 3: Broad token match only -> WEAK / Ambiguous
        top_cand = scored_candidates[0]
        evidence = [
            "shared_tokens_only",
            "insufficient_evidence_for_allocation",
        ]
        return [], MATCH_WEAK, evidence

    # Replay prior refunds in [lookback_start, start) so prior debits reflect correct remaining balance
    prior_refunds_qs = Transaction.objects.filter(
        session_id=session_id,
        transaction_type='CREDIT',
        transaction_date__gte=lookback_start,
        transaction_date__lt=start
    ).order_by('transaction_date')
    if not include_persona:
        prior_refunds_qs = prior_refunds_qs.filter(source_type='import')

    for p_tx in prior_refunds_qs:
        if classify_credit(p_tx.normalized_merchant)['credit_type'] != 'refund':
            continue
        cands, conf, _ = _evaluate_candidates(p_tx, debit_capacity)
        if conf in (MATCH_CONFIRMED, MATCH_PROBABLE) and cands:
            p_rem = p_tx.amount
            for cand in cands:
                if p_rem <= Decimal('0'):
                    break
                d = cand['debit']
                cap = debit_capacity.get(str(d.id), Decimal('0'))
                if cap <= Decimal('0'):
                    continue
                alloc = min(p_rem, cap)
                p_rem -= alloc
                debit_capacity[str(d.id)] = cap - alloc

    # Metrics for current statement period
    confirmed_same_period_applied = Decimal('0')
    confirmed_cross_month_applied = Decimal('0')
    probable_same_period_suggested = Decimal('0')
    probable_cross_month_suggested = Decimal('0')
    unmatched_refunds = Decimal('0')
    confirmed_same_period_cat_refunds = defaultdict(Decimal)
    refund_details = []

    # Sort current refunds chronologically
    refund_tx_list.sort(key=lambda x: x[0].transaction_date)

    for tx, assoc in refund_tx_list:
        r_amt = tx.amount
        r_rem = r_amt

        eligible_cands, confidence, overall_evidence = _evaluate_candidates(tx, debit_capacity)

        matched_purchases_list = []
        r_applied_sum = Decimal('0')
        r_suggested_sum = Decimal('0')
        primary_temporal = None

        if confidence in (MATCH_CONFIRMED, MATCH_PROBABLE) and eligible_cands:
            for cand in eligible_cands:
                if r_rem <= Decimal('0'):
                    break
                d = cand['debit']
                cap = debit_capacity.get(str(d.id), Decimal('0'))
                if cap <= Decimal('0'):
                    continue

                alloc_amt = min(r_rem, cap)
                if alloc_amt > Decimal('0'):
                    r_rem -= alloc_amt
                    debit_capacity[str(d.id)] = cap - alloc_amt
                    is_same_period = (d.transaction_date.year == year and d.transaction_date.month == month)
                    cand_temporal = TEMPORAL_SAME_PERIOD if is_same_period else TEMPORAL_CROSS_MONTH
                    d_cat = classify_debit(d.normalized_merchant)['category']

                    if primary_temporal is None:
                        primary_temporal = cand_temporal

                    if confidence == MATCH_CONFIRMED:
                        cand_alloc_status = ALLOC_APPLIED
                        cand_allocated_amount = alloc_amt
                        cand_suggested_amount = Decimal('0')
                        r_applied_sum += alloc_amt

                        if is_same_period:
                            confirmed_same_period_applied += alloc_amt
                            confirmed_same_period_cat_refunds[d_cat] += alloc_amt
                        else:
                            confirmed_cross_month_applied += alloc_amt
                    else:
                        # PROBABLE: suggested, NOT applied
                        cand_alloc_status = ALLOC_SUGGESTED_NOT_APPLIED
                        cand_allocated_amount = Decimal('0')
                        cand_suggested_amount = alloc_amt
                        r_suggested_sum += alloc_amt

                        if is_same_period:
                            probable_same_period_suggested += alloc_amt
                        else:
                            probable_cross_month_suggested += alloc_amt

                    matched_purchases_list.append({
                        'debit_id': str(d.id),
                        'matched_transaction_id': str(d.id),
                        'purchase_date': d.transaction_date.isoformat(),
                        'merchant': _safe_counterparty_label(d.normalized_merchant),
                        'category': d_cat,
                        'allocated_amount': str(cand_allocated_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                        'suggested_amount': str(cand_suggested_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                        'match_confidence': confidence,
                        'temporal_relation': cand_temporal,
                        'allocation_status': cand_alloc_status,
                        'is_same_period': is_same_period,
                        'matching_evidence': overall_evidence,
                    })

        r_unmatched = r_rem
        unmatched_refunds += r_unmatched

        # Determine overall refund attribution fields
        if confidence == MATCH_CONFIRMED and matched_purchases_list:
            overall_alloc_status = ALLOC_APPLIED
            overall_allocated = r_applied_sum
            overall_suggested = Decimal('0')
            overall_temporal = primary_temporal
        elif confidence == MATCH_PROBABLE and matched_purchases_list:
            overall_alloc_status = ALLOC_SUGGESTED_NOT_APPLIED
            overall_allocated = Decimal('0')
            overall_suggested = r_suggested_sum
            overall_temporal = primary_temporal
        else:
            overall_alloc_status = ALLOC_NOT_ALLOCATED
            overall_allocated = Decimal('0')
            overall_suggested = Decimal('0')
            overall_temporal = None

        primary_matched_id = matched_purchases_list[0]['matched_transaction_id'] if matched_purchases_list else None

        refund_display_merchant = (
            matched_purchases_list[0]['merchant']
            if matched_purchases_list
            else _safe_counterparty_label(tx.normalized_merchant)
        )
        refund_details.append({
            'id': str(tx.id),
            'merchant': refund_display_merchant,
            'amount': str(r_amt.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'associated_category': assoc,
            'date': tx.transaction_date.isoformat(),
            # Three orthogonal dimensions
            'match_confidence': confidence,
            'temporal_relation': overall_temporal,
            'allocation_status': overall_alloc_status,
            'status': overall_alloc_status,
            'matched_transaction_id': primary_matched_id,
            'matching_evidence': overall_evidence,
            'allocated_amount': str(overall_allocated.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'suggested_amount': str(overall_suggested.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'matched_amount': str((overall_allocated if confidence == MATCH_CONFIRMED else overall_suggested).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'same_period_matched': str((overall_allocated if overall_temporal == TEMPORAL_SAME_PERIOD and confidence == MATCH_CONFIRMED else Decimal('0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'cross_month_matched': str((overall_allocated if overall_temporal == TEMPORAL_CROSS_MONTH and confidence == MATCH_CONFIRMED else (overall_suggested if overall_temporal == TEMPORAL_CROSS_MONTH else Decimal('0'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'unmatched_amount': str(r_unmatched.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'matched_purchases': matched_purchases_list,
        })

    # Net living expenses strictly reduced ONLY by confirmed applied same-period refunds
    net_living_expenses = max(Decimal('0'), gross_living_expenses - confirmed_same_period_applied)

    # Net category spending accounting ONLY for confirmed applied same-period refunds
    net_cat_spend = {}
    for c, gross_c in cat_spend.items():
        if c == 'transfer':
            continue
        ref_c = confirmed_same_period_cat_refunds.get(c, Decimal('0'))
        net_c = max(Decimal('0'), gross_c - ref_c)
        net_cat_spend[c] = str(net_c.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    # Net operating surplus: operating_income - net_living_expenses
    operating_surplus = operating_income - net_living_expenses
    overspending = net_living_expenses > operating_income

    total_account_cash_movement = total_credits - gross_debits

    total_applied = confirmed_same_period_applied + confirmed_cross_month_applied
    total_suggested = probable_same_period_suggested + probable_cross_month_suggested

    cat_spend_str = {k: str(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) for k, v in cat_spend.items()}
    cat_refund_str = {k: str(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) for k, v in category_refunds.items()}

    return {
        'year': year,
        'month': month,
        'income': str(operating_income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'earned_income': str(earned_income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'investment_yield': str(investment_yield.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'operating_income': str(operating_income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'capital_liquidation': str(capital_liquidation.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'investment_transfers': str(investment_transfers.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'total_credits': str(total_credits.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'total_inflow': str(total_credits.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'unclassified_inflows': str(unclassified_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'credit_breakdown': {
            'earned_income': str(earned_income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'investment_yield': str(investment_yield.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'investment_income': str(investment_yield.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'capital_liquidation': str(capital_liquidation.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'investment_transfers': str(investment_transfers.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'refunds': str(refunds_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'transfers': str(transfers_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'reimbursements': str(reimbursements_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'unclassified': str(unclassified_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        },
        'gross_living_expenses': str(gross_living_expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'matched_refunds': str((total_applied + total_suggested).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'refunds_applied': str(confirmed_same_period_applied.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'confirmed_same_period_refunds': str(confirmed_same_period_applied.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'confirmed_cross_month_applied': str(confirmed_cross_month_applied.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'probable_same_period_refunds': str(probable_same_period_suggested.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'suggested_refunds': str(total_suggested.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'same_period_matched_refunds': str(confirmed_same_period_applied.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'cross_month_matched_refunds': str((confirmed_cross_month_applied + probable_cross_month_suggested).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'unmatched_refunds': str(unmatched_refunds.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'net_living_expenses': str(net_living_expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'operating_surplus': str(operating_surplus.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'expenses': str(net_living_expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'gross_expenses': str(gross_debits.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'gross_outflows': str(gross_debits.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'gross_debits': str(gross_debits.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'living_expenses': str(gross_living_expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'debit_transfers': str(debit_transfers.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'net_expenses': str(net_living_expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'living_expenses_after_refunds': str(net_living_expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'refunds_received': str(refunds_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'savings': str(operating_surplus.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'net_cashflow': str(total_account_cash_movement.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'total_account_cash_movement': str(total_account_cash_movement.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'overspending': overspending,
        'category_spending': cat_spend_str,
        'category_refunds': cat_refund_str,
        'net_category_spending': net_cat_spend,
        'refund_details': refund_details,
        'refund_matching_policy': 'CONFIRMED matches (shared reference ID) set allocation_status=APPLIED and reduce net living expenses. PROBABLE matches set allocation_status=SUGGESTED_NOT_APPLIED with allocated_amount=0. WEAK and UNMATCHED set allocation_status=NOT_ALLOCATED.',
        'single_account_limitation_note': 'Single-account analysis: External transfers reflect unlinked inflows/outflows without visibility into counterparty balances.',
    }

# ---------------------------------------------------------------------------
# Helper: Calculation of Median
# ---------------------------------------------------------------------------
def _calculate_median(values: List[Decimal]) -> Decimal:
    """Calculate the median of a list of Decimal values."""
    if not values:
        return Decimal('0')
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return ((sorted_vals[mid - 1] + sorted_vals[mid]) / Decimal('2')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Recurring Payment Keyword Classification & Heuristics
# ---------------------------------------------------------------------------
_SUBSCRIPTION_KEYWORDS = [
    'netflix', 'spotify', 'prime', 'amazon prime', 'hotstar', 'disney', 'youtube',
    'apple music', 'apple.com/bill', 'itunes', 'google play', 'google storage', 'google one',
    'chatgpt', 'openai', 'claude', 'anthropic', 'canva', 'adobe', 'playstation', 'xbox',
    'github', 'notion', 'medium', 'dropbox', 'icloud', 'audible', 'kindle', 'zee5',
    'sonyliv', 'jiocinema', 'aha', 'crunchyroll', 'subscription', 'membership', 'meal plan'
]

# Short keywords that must match on word boundaries: as bare substrings they
# would match ordinary words ("premium" contains "emi", "application" contains
# "lic", "subway" contains "sub") and misclassify a merchant as an obligation.
_WORD_BOUNDED_KEYWORDS = frozenset({'emi', 'lic'})

_RENT_KEYWORDS = [
    'rent', 'landlord', 'house rent', 'flat rent', 'room rent', 'nestaway',
    'nobroker', 'to-let', 'tenancy', 'society rent', 'housing rent'
]

_EMI_KEYWORDS = [
    'emi', 'loan', 'mortgage', 'housing finance', 'bajaj finance', 'hdfc loan',
    'sbi loan', 'icici loan', 'vehicle loan', 'car loan', 'auto loan', 'home loan',
    'personal loan', 'credit card emi', 'idfc first loan', 'tata capital', 'muthoot',
    'mahindra finance', 'chola', 'aditya birla finance', 'kotak loan'
]

_INSURANCE_KEYWORDS = [
    'insurance', 'lic', 'hdfc ergo', 'max life', 'icici prudential', 'sbi life',
    'star health', 'care health', 'tata aia', 'policybazaar', 'acko', 'bajaj allianz',
    'new india assurance', 'national insurance', 'oriental insurance', 'life insurance',
    'general insurance', 'health insurance'
]

_UTILITY_KEYWORDS = [
    'electricity', 'water', 'gas', 'power', 'bescom', 'tatapower', 'tata power',
    'bses', 'cesc', 'msedcl', 'tneb', 'uppcl', 'dhbvn', 'uhbvn', 'indraprastha gas',
    'mgl', 'mahanagar gas', 'adani gas', 'piped gas', 'cylinder', 'hpcl gas', 'iocl gas',
    'broadband', 'wifi', 'wi-fi', 'fibernet', 'act fibernet', 'airtel broadband',
    'airtel fiber', 'jio fiber', 'jiofiber', 'hathway', 'you broadband', 'bsnl broadband',
    'postpaid', 'airtel postpaid', 'jio postpaid', 'vi postpaid', 'vodafone postpaid',
    'water board', 'bwssb', 'djb', 'municipal water'
]

_OTHER_RECURRING_KEYWORDS = [
    'gym', 'fitness', 'cult.fit', 'cultfit', 'gold s gym', 'golds gym', 'yoga',
    'newspaper', 'times of india', 'hindu', 'milk', 'bb daily', 'bbdaily',
    'country delight', 'maid', 'cook', 'maintenance', 'society maintenance'
]

_PEER_TRANSFER_TERMS = [
    'friend', 'friends', 'splitwise', 'roommate', 'mom', 'dad', 'brother',
    'sister', 'family', 'sent to friend', 'repayment to friend'
]

_BUSINESS_INDICATOR_TERMS = [
    'merchant', 'store', 'ltd', 'pvt', 'services', 'technologies', 'infotech',
    'retail', 'corp', 'limited', 'enterprises', 'traders', 'agency', 'mart',
    'bazaar', 'hospital', 'pharmacy', 'clinic', 'gym', 'academy', 'foods',
    'kitchen', 'restaurant', 'cafe', 'infra', 'solutions', 'billdesk', 'payu',
    'razorpay', 'ccavenue', 'renew', 'bill', 'recharge', 'groceries', 'supermarket',
    'power', 'electricity', 'insurance', 'life', 'care', 'health', 'digital'
]

# Personal VPA pattern (narrow, high-precision evidence only):
# e.g. rahul.sharma@okaxis, ananya.sen@okhdfcbank, pooja_patel@paytm
# NOTE: a single-token handle such as "rahul@okaxis" is NOT matched here because a
# bare token cannot be distinguished from a small merchant identifier. Those cases
# are reported as UNCERTAIN by classify_upi_counterparty() instead of being assumed.
_PERSONAL_VPA_PATTERN = re.compile(
    r'\b[a-z]{3,25}[._][a-z]{3,25}@(okaxis|okhdfcbank|okicici|paytm|ybl|ibl|upi|axisbank|sbi|apl)\b'
)

# UPI VPA shape as it appears in narrations (local-part@handle).
_VPA_PATTERN = re.compile(r'\b([a-z0-9][a-z0-9._\-]{0,63})@([a-z]{2,20})\b')

# PSP handles that are overwhelmingly issued to individuals. Being on this list is
# necessary but not sufficient: the local part must also look name-like.
_PERSONAL_VPA_HANDLES = frozenset({
    'okaxis', 'okhdfcbank', 'okicici', 'oksbi', 'paytm', 'ybl', 'ibl', 'upi',
    'axisbank', 'sbi', 'apl', 'airtel', 'fbl', 'jupiteraxis', 'naviaxis',
})

# Tokens inside a VPA local part that signal a biller / commercial entity.
_BUSINESS_VPA_LOCAL_TERMS = frozenset({
    'bill', 'bills', 'billpay', 'pay', 'pays', 'payment', 'recharge', 'renew',
    'renewal', 'store', 'stores', 'mart', 'care', 'health', 'insurance', 'bank',
    'ltd', 'limited', 'pvt', 'private', 'services', 'service', 'tech', 'techno',
    'technologies', 'digital', 'foods', 'food', 'kitchen', 'cafe', 'gym',
    'fitness', 'hospital', 'clinic', 'pharmacy', 'academy', 'solutions', 'corp',
    'enterprise', 'enterprises', 'traders', 'agency', 'retail', 'electricity',
    'power', 'gas', 'water', 'broadband', 'telecom', 'india', 'online',
})

# Classification labels for UPI counterparties
COUNTERPARTY_PERSONAL = 'personal'
COUNTERPARTY_COMMERCIAL = 'commercial'
COUNTERPARTY_UNCERTAIN = 'uncertain'
COUNTERPARTY_NOT_A_VPA = 'not_applicable'


def _looks_like_person_handle(local_part: str) -> bool:
    """
    Returns True only for genuinely name-like VPA local parts:
    - 10-digit mobile-number VPAs (e.g. 9876543210@upi)
    - separator-joined alphabetic name segments (e.g. rahul.sharma, ananya_sen, pooja-patel)
    A bare or partially numeric token (e.g. rahul1234, shop) provides insufficient
    evidence and is treated as ambiguous by the caller.
    """
    if not local_part:
        return False
    if local_part.isdigit():
        return len(local_part) == 10 and local_part[0] in '6789'
    parts = [p for p in re.split(r'[._\-]+', local_part) if p]
    return len(parts) >= 2 and all(len(p) >= 3 and p.isalpha() for p in parts)


def classify_upi_counterparty(text: str) -> str:
    """
    Conservative three-way classification of a narration that carries a UPI VPA.

    Returns one of:
    - 'commercial'     : known billers/merchants/utilities. Never discarded as peer UPI.
    - 'personal'       : strong personal evidence (name-like VPA on a personal PSP handle,
                          mobile-number VPA, explicit peer wording, UPI/<name>/<digits>).
    - 'uncertain'      : a VPA is present but the handle format is ambiguous. The payee is
                          neither excluded as a peer nor confidently treated as a merchant
                          subscription (see detect_subscriptions).
    - 'not_applicable' : no VPA in the narration; callers use their existing heuristics.

    The function deliberately does not treat every alphanumeric VPA as personal, which
    would hide legitimate merchants from recurring-payment detection.
    """
    lower = (text or '').lower()
    vpas = _VPA_PATTERN.findall(lower)
    if not vpas:
        return COUNTERPARTY_NOT_A_VPA

    # 1. Commercial / biller evidence always wins so merchants are never hidden.
    commercial_terms = (
        _SUBSCRIPTION_KEYWORDS + _RENT_KEYWORDS + _EMI_KEYWORDS +
        _INSURANCE_KEYWORDS + _UTILITY_KEYWORDS + _OTHER_RECURRING_KEYWORDS +
        _BUSINESS_INDICATOR_TERMS
    )
    words = set(re.sub(r'[^a-z0-9\s]', ' ', lower).split())
    for term in commercial_terms:
        term_lower = term.lower()
        if ' ' in term_lower:
            if term_lower in lower:
                return COUNTERPARTY_COMMERCIAL
        elif term_lower in words:
            return COUNTERPARTY_COMMERCIAL

    for local_part, _handle in vpas:
        local_tokens = set(re.split(r'[._\-]+', local_part))
        if local_tokens & _BUSINESS_VPA_LOCAL_TERMS:
            return COUNTERPARTY_COMMERCIAL

    # 2. Strong personal evidence.
    for term in _PEER_TRANSFER_TERMS:
        if term in lower:
            return COUNTERPARTY_PERSONAL
    if re.search(r'\b[6-9]\d{9}\b', text or ''):
        return COUNTERPARTY_PERSONAL
    if re.search(r'upi/[a-z\s]+/[0-9]+', lower):
        return COUNTERPARTY_PERSONAL

    for local_part, handle in vpas:
        if _PERSONAL_VPA_PATTERN.search(lower) and handle in _PERSONAL_VPA_HANDLES:
            return COUNTERPARTY_PERSONAL
        if handle in _PERSONAL_VPA_HANDLES and _looks_like_person_handle(local_part):
            return COUNTERPARTY_PERSONAL

    # 3. A VPA exists but identity is ambiguous: do not guess either way.
    return COUNTERPARTY_UNCERTAIN


def is_peer_upi(text: str) -> bool:
    """
    Identifies peer-to-peer personal transfers that must not be mistaken
    for commercial subscriptions or recurring bill payments.
    Inspects VPA patterns, mobile numbers, and personal names.
    Does NOT classify every VPA ending in @okaxis, @paytm or @okhdfcbank as peer:
    if commercial or business indicators exist (e.g. bescom.bill@hdfcbank,
    starhealth.renew@okaxis), it is recognized as a merchant.
    Ambiguous handles return False (not peer), but callers must treat them as
    uncertain rather than as confirmed commercial commitments.
    """
    lower = text.lower()

    verdict = classify_upi_counterparty(text)
    if verdict == COUNTERPARTY_COMMERCIAL:
        return False
    if verdict == COUNTERPARTY_PERSONAL:
        return True

    # No VPA (or an ambiguous one): fall back to the established narration heuristics.
    # Commercial / utility / biller / loan / rent / subscription terms prevent peer classification
    commercial_terms = (
        _SUBSCRIPTION_KEYWORDS + _RENT_KEYWORDS + _EMI_KEYWORDS +
        _INSURANCE_KEYWORDS + _UTILITY_KEYWORDS + _OTHER_RECURRING_KEYWORDS +
        _BUSINESS_INDICATOR_TERMS
    )
    for term in commercial_terms:
        if term in lower:
            return False

    # Check for personal peer markers
    for term in _PEER_TRANSFER_TERMS:
        if term in lower:
            return True

    # Check for 10-digit mobile number in UPI narration (e.g. UPI/FriendName/9876543210 or 9876543210@upi)
    if re.search(r'\b[6-9]\d{9}\b', text):
        return True

    # Check for personal UPI patterns: UPI/<name>/<number>
    if re.search(r'upi/[a-zA-Z\s]+/[0-9]+', lower):
        return True

    # Check for structured personal VPA without business terms (e.g. rahul.sharma@okaxis, ananya.sen@okhdfcbank)
    if _PERSONAL_VPA_PATTERN.search(lower):
        return True

    return False


# ---------------------------------------------------------------------------
# Counterparty display sanitization
# ---------------------------------------------------------------------------
# Redaction tokens emitted by the PII pipeline are internal markers, never display text.
_REDACTION_PLACEHOLDER_RE = re.compile(r'\[(?:REDACTED_[A-Z_]+|USER_PRIMARY)\]', re.IGNORECASE)

# Transaction / order / invoice reference suffixes, e.g. REF-752, ORD-9900, INV-123,
# "Invoice No. INV-2026-7781". The keyword and its value are removed together.
# A separator or whitespace is mandatory after the keyword so that ordinary words
# ("Investment", "Ordering") are never truncated.
_REFERENCE_SUFFIX_RE = re.compile(
    r'\b(?:ref(?:erence)?|ord(?:er)?|inv(?:oice)?|txn|transaction|utr|rrn|chq|cheque|trn|trf|receipt)'
    r'(?:\s*(?:no|num|number|id|code))?'
    r'(?:\s*[#:./\-]\s*|\s+)'
    r'[a-z0-9][a-z0-9._/\-]*',
    re.IGNORECASE,
)

# Standalone codes that carry digits (e.g. 752, T2610161430, TXN554) but are not part
# of an ordinary word. Requires 3+ digits so "7-Eleven" and "24x7" survive.
_STANDALONE_CODE_RE = re.compile(r'\b[a-z]{0,8}[-#]?\d{3,}[a-z0-9]*\b', re.IGNORECASE)

# Tokens that describe the payment rail rather than the counterparty.
_GENERIC_COUNTERPARTY_TOKENS = frozenset({
    'upi', 'pos', 'neft', 'imps', 'ach', 'nach', 'rtgs', 'txn', 'transaction',
    'payment', 'pay', 'paid', 'debit', 'credit', 'dr', 'cr', 'transfer', 'tfr',
    'ref', 'reference', 'order', 'invoice', 'inv', 'id', 'no', 'num', 'number',
    'account', 'ac', 'bank', 'towards', 'to', 'from', 'via', 'sent', 'received',
    'merchant', 'bill', 'billpay', 'vpa', 'the', 'and',
})


# ---------------------------------------------------------------------------
# Deduplication policy note (documented ambiguity, never silently discarded data)
# ---------------------------------------------------------------------------
DEDUPLICATION_POLICY = (
    "Duplicate-import protection requires reliable identity evidence: a matching "
    "transaction reference present in both records, or a matching import fingerprint. "
    "A fingerprint built without a reference carries an occurrence ordinal computed "
    "within the imported statement, so two legitimate identical payments on the same "
    "date are preserved while re-importing the same statement is still skipped. "
    "Known limitation: if the same reference-less, identical transaction arrives in two "
    "different statements, the system cannot prove whether it is a re-import or a second "
    "legitimate identical payment; the second occurrence is skipped because the "
    "content fingerprint is identical."
)


def _sanitize_counterparty_name(merchant_text: str, canonical_key: str = "") -> str:
    """
    Builds a safe display name for a counterparty.

    - Prefers the canonical merchant title when a brand is reliably recognized.
    - Removes PII (emails, VPAs, phones, account/card/PAN/Aadhaar identifiers) without
      ever restoring the original values.
    - Removes redaction placeholders such as [REDACTED_VPA] / [REDACTED_ACCOUNT], which
      are internal markers and must never appear as a merchant title.
    - Removes transaction/order/invoice reference suffixes and leftover separators.
    - Falls back to "Unidentified Counterparty" when no safe merchant name remains.

    This is a display-only transformation: it does not mutate stored records and does
    not claim perfect de-identification of arbitrary free text.
    """
    # 1. Known canonical brand
    if canonical_key and canonical_key not in ('unknown', 'other'):
        for pattern, canon in _CANONICAL_BRAND_MAP:
            if canon == canonical_key:
                return canonical_key.replace('_', ' ').title()

    cleaned = merchant_text or ""

    # 2. Drop redaction placeholders emitted by the PII pipeline.
    cleaned = _REDACTION_PLACEHOLDER_RE.sub(' ', cleaned)

    # 3. Redact residual PII that reaches this layer (never echoed back).
    cleaned = re.sub(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b', ' ', cleaned)
    cleaned = re.sub(r'\b[a-zA-Z0-9._\-]{2,64}@[a-zA-Z]{2,64}\b', ' ', cleaned)  # VPA
    cleaned = re.sub(
        r'(?:(?:A/C|A/c|A\.C|Account|Acct|Acc\s*No|ACC)[\s.:#-]*)([0-9Xx*-]{6,24})',
        ' ',
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r'\b(?:\d{4}[\s-]?){3}\d{4}\b', ' ', cleaned)  # card
    cleaned = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', ' ', cleaned)  # Aadhaar
    cleaned = re.sub(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', ' ', cleaned, flags=re.I)  # PAN
    cleaned = re.sub(r'(?:\+?91[\s.-]?|0)?[6-9]\d{4}[\s.-]?\d{5}\b', ' ', cleaned)  # phone
    cleaned = re.sub(r'\b\d{9,}\b', ' ', cleaned)  # bare account/reference digit runs
    cleaned = re.sub(r'\b[Xx*]{2,}\d{3,}\b', ' ', cleaned)  # masked account tokens

    # 4. Strip banking rail prefixes and reference suffixes.
    cleaned = re.sub(r'^(?:UPI|POS|NEFT|IMPS|ACH|NACH|RTGS|BIL|ATM|MB|IB)[\s/:\-]+', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\b(?:POS|TERMINAL|BRANCH|BR|TXN|AUTH)\s*[#:]?\s*\d+\b', ' ', cleaned, flags=re.I)
    cleaned = _REFERENCE_SUFFIX_RE.sub(' ', cleaned)
    cleaned = _STANDALONE_CODE_RE.sub(' ', cleaned)

    # 5. Clean leftover separators, punctuation and generic payment-rail tokens.
    cleaned = re.sub(r"[^A-Za-z0-9&' ]+", ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    words = [w for w in cleaned.split() if w.lower() not in _GENERIC_COUNTERPARTY_TOKENS]
    meaningful = ' '.join(words).strip()

    # 6. Safe fallback when no merchant identity can be established.
    if len(meaningful) < 3 or not re.search(r'[A-Za-z]{2,}', meaningful):
        return "Unidentified Counterparty"

    return meaningful.title()


# Internal redaction markers emitted by the PII pipeline (never user-facing text).
_INTERNAL_DISPLAY_MARKER_RE = re.compile(
    r'\[(?:REDACTED_[A-Z_]+|USER_PRIMARY)\]', re.IGNORECASE
)

# Residual identifiers that should never be rendered as a counterparty name, even if a
# record predates the current sanitizer (VPAs, mobile numbers, account numbers).
_RESIDUAL_IDENTIFIER_RE = re.compile(
    r'@|\b[6-9]\d{9}\b|(?:(?:A/C|A\.C|Account|Acct)[\s.:#-]*[0-9Xx*]{4,})',
    re.IGNORECASE,
)


def _display_counterparty(merchant_text: str) -> str:
    """
    Builds the user-facing name for a stored counterparty.

    Stored narrations have already passed through the PII sanitizer, so they may contain
    internal markers such as ``[REDACTED_UPI_ID]``. Those markers are never valid display
    text: this helper resolves a recognized brand when possible and otherwise scrubs the
    marker (plus any residual PII) down to "Unidentified Counterparty".

    Names that carry no marker and no residual identifier are returned unchanged, so a
    clean merchant name keeps the casing it was stored and imported with.

    Display-only: the stored record is never modified, and no original value is restored.
    """
    text = (merchant_text or "").strip()
    if not text:
        return "Unidentified Counterparty"
    if not (_INTERNAL_DISPLAY_MARKER_RE.search(text) or _RESIDUAL_IDENTIFIER_RE.search(text)):
        return text
    return _sanitize_counterparty_name(text, _extract_canonical_merchant(text))


# ---------------------------------------------------------------------------
# Privacy-safe counterparty labels
# ---------------------------------------------------------------------------
# Generic labels used whenever a narration identifies a person or cannot be
# safely presented as a merchant. They never contain the original narration.
PERSONAL_TRANSFER_LABEL = 'Personal Transfer'
UNIDENTIFIED_COUNTERPARTY_LABEL = 'Unidentified Counterparty'

_KNOWN_BRAND_KEYS = frozenset(canonical for _pattern, canonical in _CANONICAL_BRAND_MAP)

# Markers that prove an identifier was redacted from this narration.
_SENSITIVE_MARKER_RE = re.compile(
    r'\[REDACTED_(?:PHONE|UPI_ID|ACCOUNT|AADHAAR|PAN|CARD|EMAIL|BENEFICIARY)[^\]]*\]',
    re.IGNORECASE,
)
_PHONE_OR_VPA_RE = re.compile(r'@|\b[6-9]\d{9}\b')
_ACCOUNT_REFERENCE_RE = re.compile(
    r'(?:A/C|A\.C|Account|Acct|Acc\s*No)[\s.:#\-]*', re.IGNORECASE
)
_PERSONAL_PAYMENT_NARRATION_RE = re.compile(
    r'\b(?:payment|paid|pay|sent|transfer(?:red)?)\b[\s/:.\-]*(?:to|from)\b',
    re.IGNORECASE,
)
_SINGLE_NAME_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]{2,}$")
_REFUND_CONTEXT_RE = re.compile(
    r'\b(refund|refunded|reversal|reversed|chargeback|returned)\b', re.IGNORECASE
)
_BUSINESS_SIGNAL_RE = re.compile(
    r'\b(store|stores|shop|shops|mart|market|electronics|appliances|services?|'
    r'solutions?|technolog(?:y|ies)|systems?|labs?|pharmacy|diagnostics|hospital|'
    r'clinic|hotel|hotels|restaurant|restaurants|cafe|coffee|kitchen|bakery|dairy|'
    r'grocery|groceries|supermart|supermarket|kirana|salon|spa|gym|fitness|tuition|'
    r'school|college|institute|academy|coaching|travels?|airlines?|tours?|ticket|'
    r'tickets|booking|bookings|flight|flights|cinema|theatre|theater|fuel|petrol|'
    r'diesel|energy|subscription|memberships?|recharge|bill|bills|order|orders|'
    r'purchase|purchases|boutique|stationery|jewell?ers?|bank|insurance|finance|'
    r'capital|enterprises?|industries?|traders?|limited|ltd|pvt|private|llp|inc|'
    r'corp|company)\b',
    re.IGNORECASE,
)

# Recognized commercial names that carry no generic business keyword. This is a
# small, curated synthetic/demo lexicon, not an exhaustive merchant allowlist.
_MERCHANT_NAME_LEXICON = frozenset({
    'chai point', 'blue tokai', 'third wave coffee', 'cafe coffee day', 'local kirana',
    'standard chartered', 'tanishq', 'haldiram', 'bikanervala', 'karachi bakery',
    'nandini', 'amul', 'zara', 'westside', 'lifestyle', 'pantaloons', 'decathlon',
    'apple', 'macbook', 'apple india', 'samsung', 'oneplus', 'boat',
})
_MERCHANT_LEXICON_RE = re.compile(
    r'\b(?:'
    + '|'.join(
        re.escape(phrase)
        for phrase in sorted(_MERCHANT_NAME_LEXICON, key=len, reverse=True)
    )
    + r')\b',
    re.IGNORECASE,
)

# Two to four plain alphabetic words, with no brand, identifier, payment narration or
# commerce signal, are treated as an ambiguous counterparty. This is deliberately
# narrow: it runs only after every stronger signal above has been ruled out.
_AMBIGUOUS_PERSON_NAME_RE = re.compile(
    r"^[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){1,3}$"
)
_UNKNOWN_COUNTERPARTY_RE = re.compile(
    r'\b(?:unknown|unrecognised|unrecognized|unnamed)\b', re.IGNORECASE
)


def _brand_key_for(text: str) -> str:
    """Returns the canonical key of a recognized brand present in the narration."""
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', (text or '').lower())
    norm_text = f" {' '.join(cleaned.split())} "
    for pattern, canonical in _CANONICAL_BRAND_MAP:
        if f" {pattern} " in norm_text:
            return canonical
    return ''


def _canonical_display_label(canonical_key: str) -> str:
    """
    Maps an internal clustering key to a safe badge label.

    Internal keys are never rendered directly: unknown, generic or numeric keys fall
    back to the shared unidentified label so an identifier cannot reach the UI through
    the canonical badge.
    """
    key = (canonical_key or '').strip()
    if not key:
        return UNIDENTIFIED_COUNTERPARTY_LABEL
    for _pattern, canonical in _CANONICAL_BRAND_MAP:
        if canonical == key:
            return key.replace('_', ' ').title()
    if (
        key.lower() in _GENERIC_COUNTERPARTY_TOKENS
        or key.lower() in _REFUND_STRIP_TERMS
        or '@' in key
        or any(ch.isdigit() for ch in key)
    ):
        return UNIDENTIFIED_COUNTERPARTY_LABEL
    return key.replace('_', ' ').replace('-', ' ').title()


def _strip_reference_noise(text: str) -> str:
    """Removes redaction markers and transaction reference codes, preserving casing."""
    cleaned = _REDACTION_PLACEHOLDER_RE.sub(' ', text or '')
    cleaned = _REFERENCE_SUFFIX_RE.sub(' ', cleaned)
    cleaned = _STANDALONE_CODE_RE.sub(' ', cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9&' ]+", ' ', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()


def _safe_counterparty_label(merchant_text: str) -> str:
    """
    Builds a user-facing counterparty label that is safe for public display.

    Order of evidence:
    1. A recognized commercial brand is displayed by name.
    2. A personal UPI verdict, a phone/VPA, or a redacted identifier marker yields a
       generic label rather than a personal name.
    3. Account references and payment narration such as ``Payment to <name>`` yield a
       generic label.
    4. Remaining narrations are stripped of references, markers and payment-rail noise;
       a lone name-shaped label is treated as a personal transfer.

    Display-only. Stored records and matching/attribution logic are untouched, and no
    redacted value is ever reconstructed.
    """
    text = (merchant_text or '').strip()
    if not text:
        return UNIDENTIFIED_COUNTERPARTY_LABEL

    # A confirmed own-account transfer keeps its own fixed, content-free label.
    if text.lower() in INTERNAL_TRANSFER_LABELS:
        return INTERNAL_TRANSFER_LABEL

    brand_key = _brand_key_for(text)
    verdict = classify_upi_counterparty(text)

    # A personal UPI verdict or a residual phone/VPA is never shown as a merchant.
    # A recognized brand may still be named, because the brand, not the payer, is the
    # useful identity (e.g. the VPA on a Swiggy payment).
    if verdict == COUNTERPARTY_PERSONAL or _PHONE_OR_VPA_RE.search(text):
        if brand_key:
            return _sanitize_counterparty_name(text, brand_key)
        return PERSONAL_TRANSFER_LABEL

    if _ACCOUNT_REFERENCE_RE.search(text) or '[REDACTED_ACCOUNT]' in text.upper():
        return UNIDENTIFIED_COUNTERPARTY_LABEL
    if _PERSONAL_PAYMENT_NARRATION_RE.search(text):
        return PERSONAL_TRANSFER_LABEL

    # Everything else is scrubbed while preserving the original casing of an already
    # clean merchant label ("MakeMyTrip Flight Booking" must not be re-cased).
    label = _strip_reference_noise(text)
    words = [
        word for word in label.split()
        if word.lower() not in _GENERIC_COUNTERPARTY_TOKENS
    ]
    label = ' '.join(words).strip()
    if not label or not re.search(r'[A-Za-z]{2,}', label):
        return UNIDENTIFIED_COUNTERPARTY_LABEL
    if label.isupper():
        label = label.title()

    # A refund with no recognized brand and no matched purchase is far more likely a
    # personal reversal than a business. Keep the label only when the remaining words
    # carry a business signal; otherwise fall back to the generic label.
    if _REFUND_CONTEXT_RE.search(text) and not brand_key:
        remainder = re.sub(
            r'\b(refund|refunded|reversal|reversed|chargeback|returned|'
            r'upi|neft|imps|rtgs|ach|debit|credit)\b',
            ' ',
            label,
            flags=re.IGNORECASE,
        )
        remainder = ' '.join(remainder.split())
        words = [w for w in remainder.split() if any(c.isalpha() for c in w)]
        if len(words) <= 3 and not _BUSINESS_SIGNAL_RE.search(remainder):
            return PERSONAL_TRANSFER_LABEL

    if _UNKNOWN_COUNTERPARTY_RE.search(label):
        return UNIDENTIFIED_COUNTERPARTY_LABEL

    if _MERCHANT_LEXICON_RE.search(label):
        return label

    # A bare personal-looking name is ambiguous, not a confirmed transfer: nothing in
    # the narration proves the counterparty is a person, and nothing proves it is a
    # business. Never echo it as a merchant name.
    if (
        _AMBIGUOUS_PERSON_NAME_RE.match(label)
        and not brand_key
        and not _BUSINESS_SIGNAL_RE.search(label)
    ):
        return UNIDENTIFIED_COUNTERPARTY_LABEL

    if _SINGLE_NAME_LABEL_RE.match(label):
        # A lone token is ambiguous unless it is a recognized merchant brand.
        if brand_key:
            return _sanitize_counterparty_name(text, brand_key)
        return UNIDENTIFIED_COUNTERPARTY_LABEL
    return label


def _is_duplicate_import(tx1: Transaction, tx2: Transaction) -> bool:
    """
    Determines whether tx2 is a duplicate import of tx1.

    Duplicate-import protection is applied ONLY when reliable identity evidence exists:
    - matching non-empty import fingerprints on both records (ingestion fingerprints are
      occurrence-aware, see api.views._compute_fingerprint), or
    - a shared transaction/order reference ID extracted from both narrations.

    Two payments that merely share merchant, date and amount are NOT collapsed. Without
    a reference or fingerprint the engine cannot prove they are the same imported
    transaction, so both are preserved. See DEDUPLICATION_POLICY for the documented
    ambiguity between a re-import and a genuine identical second payment.
    """
    if tx1.transaction_date != tx2.transaction_date or tx1.amount != tx2.amount:
        return False
    if tx1.transaction_type != tx2.transaction_type:
        return False
    # Reliable fingerprint evidence
    if tx1.fingerprint and tx2.fingerprint:
        return tx1.fingerprint == tx2.fingerprint
    # Reliable reference evidence
    refs1 = _extract_reference_ids(tx1.normalized_merchant)
    refs2 = _extract_reference_ids(tx2.normalized_merchant)
    if refs1 and refs2:
        return bool(refs1 & refs2)
    # Missing or one-sided identity evidence is ambiguous: never discard on a guess.
    return False


def _is_ordinary_merchant(canonical_label: str, counterparty_class: str) -> bool:
    """
    True when the counterparty is an identifiable business rather than an
    unidentified or ambiguous handle.
    """
    if not canonical_label:
        return False
    if canonical_label.strip().lower() == UNIDENTIFIED_COUNTERPARTY_LABEL.lower():
        return False
    if counterparty_class and counterparty_class.upper() in ('UNCERTAIN', 'PERSONAL'):
        return False
    return True


def classify_commitment(
    merchant_text: str,
    payment_type: str,
    canonical_label: str = '',
    counterparty_class: str = '',
) -> Dict[str, Any]:
    """
    Classifies a recurring payment into a commitment class.

    Returns a dict with:
      * ``commitment_class`` - one of the four documented commitment classes.
      * ``commitment_evidence`` - the identifiers of the rules that matched
        (never the raw narration).
      * ``is_financial_commitment`` - True for a subscription commitment or a
        fixed obligation.
      * ``is_potential_leakage`` - True for a subscription commitment (the only
        class that can represent a *potentially avoidable* recurring expense).
    """
    text = (merchant_text or '').lower()
    evidence: List[str] = []

    # 1. A fixed contractual obligation (rent, instalment, insurance, utility).
    if payment_type in (PAYMENT_TYPE_RENT, PAYMENT_TYPE_EMI, PAYMENT_TYPE_INSURANCE, PAYMENT_TYPE_UTILITY):
        evidence.append('OBLIGATION_PAYMENT_TYPE')
    elif _OBLIGATION_EVIDENCE_RE.search(text):
        evidence.append('OBLIGATION_NARRATION')

    # 2. A subscription or billing relationship.
    if payment_type == PAYMENT_TYPE_SUBSCRIPTION:
        evidence.append('SUBSCRIPTION_PAYMENT_TYPE')
    elif _SUBSCRIPTION_EVIDENCE_RE.search(text):
        evidence.append('SUBSCRIPTION_NARRATION')

    if 'OBLIGATION_PAYMENT_TYPE' in evidence or 'OBLIGATION_NARRATION' in evidence:
        commitment_class = COMMITMENT_FIXED_OBLIGATION
        if 'SUBSCRIPTION_PAYMENT_TYPE' in evidence or 'SUBSCRIPTION_NARRATION' in evidence:
            evidence.append('OBLIGATION_AND_SUBSCRIPTION_EVIDENCE')
    elif 'SUBSCRIPTION_PAYMENT_TYPE' in evidence or 'SUBSCRIPTION_NARRATION' in evidence:
        commitment_class = COMMITMENT_SUBSCRIPTION
    elif payment_type == PAYMENT_TYPE_OTHER:
        # A gym membership is a cancellable commitment; maintenance is a fixed
        # obligation; the rest are consumables.
        if _MEMBERSHIP_EVIDENCE_RE.search(text):
            commitment_class = COMMITMENT_SUBSCRIPTION
            evidence.append('MEMBERSHIP_MERCHANT')
        elif _OBLIGATION_EVIDENCE_RE.search(text):
            commitment_class = COMMITMENT_FIXED_OBLIGATION
            evidence.append('MAINTENANCE_OBLIGATION')
        elif _CONSUMABLE_EVIDENCE_RE.search(text):
            commitment_class = COMMITMENT_DISCRETIONARY
            evidence.append('REPEAT_CONSUMABLE_MERCHANT')
        else:
            commitment_class = COMMITMENT_DISCRETIONARY
            evidence.append('REPEAT_ORDINARY_MERCHANT')
    else:
        # No commitment evidence at all. A repeat at an ordinary merchant is
        # discretionary spending; a repeat with no identifiable merchant is
        # only an observed pattern.
        if _is_ordinary_merchant(canonical_label, counterparty_class):
            commitment_class = COMMITMENT_DISCRETIONARY
            evidence.append('ORDINARY_MERCHANT_REPEAT')
        else:
            commitment_class = COMMITMENT_PATTERN
            evidence.append('UNIDENTIFIED_COUNTERPARTY_REPEAT')

    is_commitment = commitment_class in (
        COMMITMENT_SUBSCRIPTION,
        COMMITMENT_FIXED_OBLIGATION,
    )
    return {
        'commitment_class': commitment_class,
        'commitment_evidence': evidence,
        'is_financial_commitment': is_commitment,
        'is_potential_leakage': commitment_class == COMMITMENT_SUBSCRIPTION,
    }


def _commitment_cost_label(commitment_class: str, confidence: str) -> str:
    """
    Explains what the reported monthly figure represents, so that a repeated
    purchase is never presented as a commitment and a subscription is never
    presented as wasted money.
    """
    if commitment_class == COMMITMENT_SUBSCRIPTION:
        return (
            "Recurring subscription charge; review whether it is still used - "
            "cancelling it would free this amount each month"
        )
    if commitment_class == COMMITMENT_FIXED_OBLIGATION:
        return (
            "Recurring contractual obligation (rent, instalment, insurance or utility); "
            "not avoidable by choice in the usual case"
        )
    if commitment_class == COMMITMENT_DISCRETIONARY:
        return (
            "Repeated discretionary spending; the amount is the observed average and "
            "is not a fixed commitment"
        )
    return (
        "Observed recurring pattern without commitment evidence; no monthly "
        "commitment is implied"
    )


def classify_recurring_payment(merchant: str, category: str = "") -> str:
    """Classifies detected recurring payments into standard categories."""
    text = f"{merchant} {category}".lower()

    def _matches(keyword: str) -> bool:
        if keyword in _WORD_BOUNDED_KEYWORDS:
            return re.search(rf'\b{re.escape(keyword)}\b', text) is not None
        return keyword in text

    for kw in _RENT_KEYWORDS:
        if _matches(kw):
            return PAYMENT_TYPE_RENT
    for kw in _EMI_KEYWORDS:
        if _matches(kw):
            return PAYMENT_TYPE_EMI
    for kw in _INSURANCE_KEYWORDS:
        if _matches(kw):
            return PAYMENT_TYPE_INSURANCE
    for kw in _UTILITY_KEYWORDS:
        if _matches(kw):
            return PAYMENT_TYPE_UTILITY
    for kw in _SUBSCRIPTION_KEYWORDS:
        if _matches(kw):
            return PAYMENT_TYPE_SUBSCRIPTION
    for kw in _OTHER_RECURRING_KEYWORDS:
        if _matches(kw):
            return PAYMENT_TYPE_OTHER
    category_key = canonical_category_key(category)
    if category_key == 'rent_housing':
        return PAYMENT_TYPE_RENT
    if category_key in ('subscriptions', 'subscription'):
        return PAYMENT_TYPE_SUBSCRIPTION
    if category_key in ('bills', 'bill'):
        return PAYMENT_TYPE_UTILITY
    if category_key == 'emi':
        return PAYMENT_TYPE_EMI
    return PAYMENT_TYPE_UNKNOWN


def get_recurring_merchant_key(merchant_text: str) -> Tuple[str, str, str]:
    """
    Returns (group_key, canonical_merchant, display_merchant).
    Ensures sub-brands (e.g. Swiggy Instamart vs Swiggy Dineout,
    Amazon Prime vs Amazon Shopping / Marketplace) are cleanly isolated.
    Avoids broad parent company catch-alls that lump retail shopping into subscriptions.
    Strips noise POS/terminal/location tokens while preserving merchant core identity.
    """
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', merchant_text.lower())
    norm_text = f" {' '.join(cleaned.split())} "

    # Check Amazon sub-services explicitly to avoid lumping retail into Prime
    if ' amazon prime ' in norm_text or ' prime video ' in norm_text:
        return 'amazon_prime', 'amazon_prime', 'Amazon Prime'
    elif ' amazon fresh ' in norm_text:
        return 'amazon_fresh', 'amazon_fresh', 'Amazon Fresh'
    elif ' amazon pay ' in norm_text:
        return 'amazon_pay', 'amazon_pay', 'Amazon Pay'
    elif ' amazon ' in norm_text:
        # General Amazon retail shopping remains distinct from subscriptions
        return 'amazon_shopping', 'amazon_shopping', 'Amazon Shopping'

    # Check Airtel sub-services explicitly
    if ' airtel broadband ' in norm_text or ' airtel fiber ' in norm_text:
        return 'airtel_broadband', 'airtel_broadband', 'Airtel Broadband'
    elif ' airtel postpaid ' in norm_text:
        return 'airtel_postpaid', 'airtel_postpaid', 'Airtel Postpaid'
    elif ' airtel ' in norm_text:
        return 'airtel_recharge', 'airtel_recharge', 'Airtel Recharge'

    # Check Jio sub-services explicitly
    if ' jio fiber ' in norm_text or ' jiofiber ' in norm_text:
        return 'jio_fiber', 'jio_fiber', 'Jio Fiber'
    elif ' jio postpaid ' in norm_text:
        return 'jio_postpaid', 'jio_postpaid', 'Jio Postpaid'
    elif ' jiocinema ' in norm_text:
        return 'jio_cinema', 'jio_cinema', 'JioCinema'
    elif ' jio ' in norm_text:
        return 'jio_recharge', 'jio_recharge', 'Jio Recharge'

    # Check remaining canonical brand map
    for pattern, canonical in _CANONICAL_BRAND_MAP:
        if pattern in ('amazon', 'airtel', 'jio'):
            continue  # Already handled specifically above
        if f" {pattern} " in norm_text:
            return canonical, canonical, merchant_text.strip()

    # For other merchants: strip POS/terminal numbers and noise to handle dynamic location/POS changes
    cleaned_tokens = re.sub(r'\b(?:pos|terminal|txn|counter|branch|br|ref|reference|ord|order|inv|bill|no)\s*[-:#]?\s*[a-z0-9#]+\b', '', cleaned, flags=re.I)
    cleaned_tokens = re.sub(r'^(?:upi|pos|neft|imps|ach|nach)\s*[/:-]\s*', '', cleaned_tokens, flags=re.I)
    tokens = [t for t in cleaned_tokens.split() if t not in _REFUND_STRIP_TERMS and not t.isdigit()]
    if tokens:
        key = ' '.join(tokens)
        return key, tokens[0], merchant_text.strip()

    fallback = merchant_text.strip().lower()
    return fallback, fallback, merchant_text.strip()


def _detect_cadence_and_intervals(dates: List[date]) -> Tuple[str, Decimal, bool, List[str]]:
    """
    Given sorted distinct dates, computes median interval in days,
    detects cadence (weekly, fortnightly, monthly, quarterly, annual, or irregular),
    and evaluates robust interval consistency allowing for reasonable real-world delays
    (e.g. 37-day interval due to weekend/holiday processing).
    Returns (cadence, median_interval, is_consistent, cadence_notes).
    """
    if len(dates) <= 1:
        return CADENCE_MONTHLY, Decimal('30'), True, []

    intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    median_interval = _calculate_median([Decimal(x) for x in intervals])
    k_intervals = len(intervals)
    cadence_notes: List[str] = []

    # Check cadence intervals with bounded delay tolerance
    if Decimal('5') <= median_interval <= Decimal('9'):
        cadence = CADENCE_WEEKLY
        normal = sum(1 for iv in intervals if 5 <= iv <= 10)
        delayed = sum(1 for iv in intervals if 11 <= iv <= 13)
        consistent = (normal + delayed == k_intervals) and (normal >= max(1, k_intervals - 1))
        if delayed > 0 and consistent:
            cadence_notes.append("Weekly cadence observed with minor delay")

    elif Decimal('12') <= median_interval <= Decimal('17'):
        cadence = CADENCE_FORTNIGHTLY
        normal = sum(1 for iv in intervals if 11 <= iv <= 19)
        delayed = sum(1 for iv in intervals if 20 <= iv <= 22)
        consistent = (normal + delayed == k_intervals) and (normal >= max(1, k_intervals - 1))
        if delayed > 0 and consistent:
            cadence_notes.append("Fortnightly cadence observed with minor delay")

    elif Decimal('25') <= median_interval <= Decimal('36'):
        cadence = CADENCE_MONTHLY
        # Standard monthly is 25-36 days. Allow up to 42 days for 1 delayed payment (e.g. 37 days)
        normal = sum(1 for iv in intervals if 25 <= iv <= 36)
        delayed = sum(1 for iv in intervals if 37 <= iv <= 42)
        consistent = (normal + delayed == k_intervals) and (normal >= max(1, k_intervals - 1))
        if delayed > 0 and consistent:
            delayed_vals = [iv for iv in intervals if 37 <= iv <= 42]
            cadence_notes.append(f"Monthly cadence observed with delayed payment ({delayed_vals[0]} days)")

    elif Decimal('75') <= median_interval <= Decimal('105'):
        cadence = CADENCE_QUARTERLY
        normal = sum(1 for iv in intervals if 75 <= iv <= 105)
        delayed = sum(1 for iv in intervals if 106 <= iv <= 118)
        consistent = (normal + delayed == k_intervals) and (normal >= max(1, k_intervals - 1))
        if delayed > 0 and consistent:
            cadence_notes.append("Quarterly cadence observed with minor delay")

    elif Decimal('330') <= median_interval <= Decimal('400'):
        cadence = CADENCE_ANNUAL
        normal = sum(1 for iv in intervals if 330 <= iv <= 400)
        delayed = sum(1 for iv in intervals if 401 <= iv <= 415)
        consistent = (normal + delayed == k_intervals) and (normal >= max(1, k_intervals - 1))
        if delayed > 0 and consistent:
            cadence_notes.append("Annual cadence observed with leap-year/processing delay")

    else:
        cadence = CADENCE_IRREGULAR
        consistent = False

    if not consistent:
        cadence = CADENCE_IRREGULAR

    return cadence, median_interval, consistent, cadence_notes


def _project_calendar_next_date(last_date: date, cadence: str) -> Optional[date]:
    """
    Computes the next recurring date aware of calendar month boundaries and leap years.
    Clamps day of month to maximum days in target month (e.g. Jan 31 -> Feb 28 or Feb 29).
    """
    if cadence == CADENCE_WEEKLY:
        return last_date + timedelta(days=7)
    elif cadence == CADENCE_FORTNIGHTLY:
        return last_date + timedelta(days=14)
    elif cadence == CADENCE_MONTHLY:
        year = last_date.year + (1 if last_date.month == 12 else 0)
        month = 1 if last_date.month == 12 else last_date.month + 1
        max_days = calendar.monthrange(year, month)[1]
        day = min(last_date.day, max_days)
        return date(year, month, day)
    elif cadence == CADENCE_QUARTERLY:
        year = last_date.year + ((last_date.month + 2) // 12)
        month = ((last_date.month + 2) % 12) + 1
        max_days = calendar.monthrange(year, month)[1]
        day = min(last_date.day, max_days)
        return date(year, month, day)
    elif cadence == CADENCE_ANNUAL:
        year = last_date.year + 1
        month = last_date.month
        max_days = calendar.monthrange(year, month)[1]
        day = min(last_date.day, max_days)
        return date(year, month, day)
    else:
        return None


def _evaluate_amount_variation(amounts: List[Decimal], payment_type: str) -> str:
    """Evaluates whether debit amounts are fixed, low variance, or variable."""
    if not amounts or len(amounts) <= 1:
        return VARIATION_FIXED
    min_amt = min(amounts)
    max_amt = max(amounts)
    if min_amt == max_amt:
        return VARIATION_FIXED

    # Utility bills with fluctuating amounts are categorized as variable
    if payment_type == PAYMENT_TYPE_UTILITY:
        return VARIATION_VARIABLE

    avg = sum(amounts) / Decimal(len(amounts))
    if avg <= Decimal('0'):
        return VARIATION_FIXED
    max_dev = max(abs(a - avg) for a in amounts)
    rel_dev = max_dev / avg
    if rel_dev <= Decimal('0.10'):
        return VARIATION_LOW
    return VARIATION_VARIABLE


# ---------------------------------------------------------------------------
# 3. Subscription Detector (Evidence-Based Recurring Payment Engine)
# ---------------------------------------------------------------------------
def detect_subscriptions(
    session_id: str,
    include_persona: bool = False,
    as_of_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """
    Evidence-based recurring payment detection engine.
    - Evaluates complete session debit history (not just selected month).
    - Filters out credits, refunds/reversals, own-account debit transfers, and peer UPI transfers.
    - Preserves legitimate same-day identical transactions with unique reference IDs.
    - Deduplicates true re-imports via source/transaction fingerprints and reference matching.
    - Groups by canonical merchant identity to avoid conflating distinct sub-brands (e.g. Swiggy Instamart vs Dineout).
    - Supports weekly, fortnightly, monthly, quarterly, and annual cadence with robust delay tolerance.
    - Multi-tier confidence: CONFIRMED (>=3 consistent debits), PROBABLE (2 compatible debits), WEAK (irregular).
    - Classifies payment type: subscription, rent, emi_or_loan, insurance, utility, other_recurring_payment, unknown_recurring_payment.
    - Computes calendar-aware next payment dates (handles leap years and month lengths).
    - Withholds unsupported projected annual costs for irregular cadences.
    """
    source_type = (
        Transaction.SOURCE_PERSONA if include_persona else Transaction.SOURCE_IMPORT
    )
    qs = Transaction.objects.filter(
        session_id=session_id,
        source_type=source_type,
        transaction_type='DEBIT',
    )
    all_debits = list(qs.order_by('transaction_date', 'created_at'))

    # Group eligible debits
    groups = defaultdict(list)
    for tx in all_debits:
        # Exclude identified own-account transfers (both model-classified and user-corrected)
        if canonical_category_key(tx.category) == 'transfer':
            continue
        debit_info = classify_debit(tx.normalized_merchant)
        if debit_info.get('is_transfer'):
            continue

        # Exclude identified peer UPI transfers
        if is_peer_upi(tx.normalized_merchant):
            continue

        # Exclude refund/reversal-like debits
        lower_m = tx.normalized_merchant.lower()
        if any(term in lower_m for term in ['refund', 'reversal', 'cashback', 'chargeback', 'returned']):
            continue

        group_key, canonical, display_m = get_recurring_merchant_key(tx.normalized_merchant)
        groups[group_key].append(tx)

    result = []
    eval_as_of = as_of_date if as_of_date is not None else date.today()

    for group_key, items in groups.items():
        # Sort chronologically
        items = sorted(items, key=lambda t: (t.transaction_date, t.id))

        # Deduplicate true duplicate imports while preserving legitimate same-day identical payments
        deduped_items = []
        for t in items:
            is_dup = False
            for existing in deduped_items:
                if _is_duplicate_import(existing, t):
                    is_dup = True
                    break
            if not is_dup:
                deduped_items.append(t)

        count = len(deduped_items)
        if count == 0:
            continue
        # Real transaction IDs for this recurrence. Downstream engines must use
        # these instead of the legacy boolean ``candidates`` flag so evidence
        # can be validated against the active session ledger.
        candidate_transaction_ids = [str(t.id) for t in deduped_items]

        latest_tx = deduped_items[-1]
        _, canonical_merchant, _ = get_recurring_merchant_key(latest_tx.normalized_merchant)
        display_merchant = _sanitize_counterparty_name(latest_tx.normalized_merchant, canonical_merchant)
        counterparty_class = classify_upi_counterparty(latest_tx.normalized_merchant)
        payment_type = classify_recurring_payment(
            latest_tx.normalized_merchant,
            category_display_name(resolve_transaction_category(latest_tx)),
        )
        if counterparty_class == COUNTERPARTY_UNCERTAIN:
            # Conservative handling: an ambiguous UPI handle must not be presented as a
            # commercial subscription or a confirmed recurring commitment.
            payment_type = PAYMENT_TYPE_UNKNOWN

        amounts = [Decimal(str(t.amount)) for t in deduped_items]
        dates = [t.transaction_date for t in deduped_items]
        unique_dates = sorted(list(set(dates)))
        avg_amount = sum(amounts) / Decimal(count)
        observed_total_spend = sum(amounts).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        observed_period_average = avg_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        amount_variation = _evaluate_amount_variation(amounts, payment_type)

        if count == 1:
            # Single occurrence: only include if explicitly flagged as recurring (backward compatibility)
            if not deduped_items[0].is_recurring:
                continue
            cadence = CADENCE_MONTHLY
            median_interval = Decimal('30')
            confidence = RECURRING_PROBABLE
            candidates = False
            cadence_notes = []
            monthly_cost = avg_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            annual_cost = (avg_amount * Decimal('12')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            est_monthly_str = str(monthly_cost)
            est_annual_str = str(annual_cost)
            next_date = _project_calendar_next_date(dates[0], cadence)
            next_date_str = next_date.isoformat() if next_date else None
            is_past_projection = next_date < eval_as_of if next_date else False
            projection_status = "OVERDUE" if is_past_projection else "UPCOMING"
            evidence = [
                "1 debit occurrence explicitly flagged as recurring subscription in statement metadata",
                "Single transaction observed; monthly cadence estimated",
                f"Classification: {payment_type.replace('_', ' ').capitalize()} based on merchant profile",
                "Recurrence observed from single statement entry; contractual terms unverified",
            ]
        elif len(unique_dates) == 1:
            # Multiple same-day transactions but only 1 date observed across time
            cadence = CADENCE_IRREGULAR
            median_interval = Decimal('0')
            confidence = RECURRING_WEAK
            candidates = True
            cadence_notes = []
            est_monthly_str = None
            est_annual_str = None
            next_date_str = None
            is_past_projection = False
            projection_status = "NOT_PROJECTABLE"
            evidence = [
                f"{count} same-day debit occurrences observed on {dates[0].isoformat()}",
                "Cadence: Irregular (insufficient distinct dates to establish temporal recurrence)",
                f"Classification: {payment_type.replace('_', ' ').capitalize()} identified from merchant profile",
                f"Observed total spend: ₹{observed_total_spend}; projected annual cost withheld due to non-cadenced history",
                "Recurrence inferred from observed transaction history; not a verified contractual commitment",
            ]
        else:
            cadence, median_interval, is_consistent, cadence_notes = _detect_cadence_and_intervals(unique_dates)

            # Determine confidence
            if len(unique_dates) >= 3:
                if cadence != CADENCE_IRREGULAR and is_consistent:
                    confidence = RECURRING_CONFIRMED
                elif cadence != CADENCE_IRREGULAR:
                    confidence = RECURRING_PROBABLE
                else:
                    confidence = RECURRING_WEAK
            elif len(unique_dates) == 2:
                if cadence != CADENCE_IRREGULAR:
                    confidence = RECURRING_PROBABLE
                else:
                    # Two arbitrary transactions with non-matching cadence must not be reported
                    continue
            else:
                continue

            candidates = True

            # Calculate estimates based on cadence
            if cadence == CADENCE_WEEKLY:
                monthly_cost = (avg_amount * Decimal('52') / Decimal('12')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                annual_cost = (avg_amount * Decimal('52')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                est_monthly_str = str(monthly_cost)
                est_annual_str = str(annual_cost)
            elif cadence == CADENCE_FORTNIGHTLY:
                monthly_cost = (avg_amount * Decimal('26') / Decimal('12')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                annual_cost = (avg_amount * Decimal('26')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                est_monthly_str = str(monthly_cost)
                est_annual_str = str(annual_cost)
            elif cadence == CADENCE_MONTHLY:
                monthly_cost = avg_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                annual_cost = (avg_amount * Decimal('12')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                est_monthly_str = str(monthly_cost)
                est_annual_str = str(annual_cost)
            elif cadence == CADENCE_QUARTERLY:
                monthly_cost = (avg_amount / Decimal('3')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                annual_cost = (avg_amount * Decimal('4')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                est_monthly_str = str(monthly_cost)
                est_annual_str = str(annual_cost)
            elif cadence == CADENCE_ANNUAL:
                monthly_cost = (avg_amount / Decimal('12')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                annual_cost = avg_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                est_monthly_str = str(monthly_cost)
                est_annual_str = str(annual_cost)
            else:  # CADENCE_IRREGULAR
                # Withhold projected annual commitment to prevent cost distortion
                est_monthly_str = None
                est_annual_str = None

            # Calendar-aware next payment projection
            next_date = _project_calendar_next_date(unique_dates[-1], cadence)
            if next_date is not None:
                next_date_str = next_date.isoformat()
                if next_date < eval_as_of:
                    is_past_projection = True
                    days_stale = (eval_as_of - unique_dates[-1]).days
                    if days_stale > 90:
                        projection_status = "STALE_HISTORY"
                    else:
                        projection_status = "OVERDUE"
                else:
                    is_past_projection = False
                    projection_status = "UPCOMING"
            else:
                next_date_str = None
                is_past_projection = False
                projection_status = "NOT_PROJECTABLE"

            span_days = (unique_dates[-1] - unique_dates[0]).days
            evidence = [
                f"{count} debit occurrences observed across {span_days} days of transaction history",
            ]
            if cadence != CADENCE_IRREGULAR:
                evidence.append(f"Cadence: {cadence.capitalize()} (median interval: {median_interval} days)")
                for note in cadence_notes:
                    evidence.append(note)
            else:
                evidence.append(f"Cadence: Irregular intervals observed ({', '.join(str((unique_dates[i+1]-unique_dates[i]).days) for i in range(len(unique_dates)-1))} days)")

            if amount_variation == VARIATION_FIXED:
                evidence.append(f"Fixed debit amount: ₹{avg_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}")
            elif amount_variation == VARIATION_LOW:
                evidence.append(f"Low-variance debit amounts (mean ₹{avg_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)})")
            else:
                evidence.append(f"Variable debit amounts (mean ₹{avg_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}, range ₹{min(amounts)} - ₹{max(amounts)})")

            evidence.append(f"Classification: {payment_type.replace('_', ' ').capitalize()} identified from merchant profile")
            if cadence == CADENCE_IRREGULAR:
                evidence.append(f"Observed total spend: ₹{observed_total_spend} across {span_days} days; projected annual commitment withheld to avoid cost distortion")
            if is_past_projection:
                if projection_status == "STALE_HISTORY":
                    evidence.append(f"Historical statement: projected date ({next_date_str}) is in the past (last debit {(eval_as_of - unique_dates[-1]).days} days ago)")
                else:
                    evidence.append(f"Projected next debit date ({next_date_str}) has passed relative to as-of date ({eval_as_of.isoformat()})")
            evidence.append("Recurrence inferred from observed transaction history; not a verified contractual commitment")

        if counterparty_class == COUNTERPARTY_UNCERTAIN:
            # Ambiguous peer/merchant identity: keep the observation visible but never
            # present it as a confident commercial recurring commitment. Projected
            # monthly/annual costs are withheld because the payee itself is unverified.
            confidence = RECURRING_WEAK
            est_monthly_str = None
            est_annual_str = None
            evidence.append(
                "Counterparty UPI handle is ambiguous; commercial classification, "
                "projected cost and recurring confidence withheld pending manual review"
            )

        # Task 23: a recurrence and a commitment are different questions. Three
        # matching monthly purchases at an ordinary merchant are a spending
        # pattern, not a financial commitment, so they are never reported as a
        # confirmed commitment.
        recurrence_confidence = confidence
        commitment = classify_commitment(
            latest_tx.normalized_merchant,
            payment_type,
            _canonical_display_label(canonical_merchant),
            counterparty_class,
        )
        if not commitment['is_financial_commitment'] and confidence == RECURRING_CONFIRMED:
            confidence = RECURRING_PROBABLE
            evidence.append(
                "Repeated payments observed, but no subscription or contractual "
                "evidence: treated as a spending pattern, not a financial commitment"
            )
        evidence.append(
            "Commitment classification: "
            f"{commitment['commitment_class'].replace('_', ' ')} "
            f"({', '.join(commitment['commitment_evidence'])})"
        )
        if commitment['commitment_class'] == COMMITMENT_SUBSCRIPTION:
            evidence.append(
                "Subscription/billing evidence present; the recurring charge may be "
                "cancelled if it is no longer used - usage is not observable from the statement"
            )

        amount_min = min(amounts).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        amount_max = max(amounts).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        result.append({
            'id': str(latest_tx.id),
            'merchant': display_merchant,
            'canonical_merchant': canonical_merchant,
            'canonical_label': _canonical_display_label(canonical_merchant),
            'identifier': display_merchant,
            'payment_type': payment_type,
            'cadence': cadence,
            'occurrence_count': count,
            'transaction_dates': [d.isoformat() for d in [t.transaction_date for t in deduped_items]],
            'transaction_amounts': [str(a.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) for a in amounts],
            'average_amount': str(avg_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'observed_total_spend': str(observed_total_spend),
            'observed_period_average': str(observed_period_average),
            'observed_amount_min': str(amount_min),
            'observed_amount_max': str(amount_max),
            'observed_amount_range': (
                str(amount_min) if amount_min == amount_max
                else f"{amount_min} - {amount_max}"
            ),
            'amount_variation': amount_variation,
            'confidence': confidence,
            'recurrence_confidence': recurrence_confidence,
            'commitment_class': commitment['commitment_class'],
            'commitment_evidence': commitment['commitment_evidence'],
            'is_financial_commitment': bool(
                commitment['is_financial_commitment'] and confidence == RECURRING_CONFIRMED
            ),
            'is_potential_leakage': bool(
                commitment['is_potential_leakage'] and confidence == RECURRING_CONFIRMED
            ),
            'evidence': evidence,
            'estimated_monthly_cost': est_monthly_str,
            'estimated_annual_cost': est_annual_str,
            'estimated_next_date': next_date_str,
            'is_past_projection': is_past_projection,
            'projection_status': projection_status,
            'cost_label': (
                _commitment_cost_label(commitment['commitment_class'], confidence)
                if est_monthly_str is not None
                else (
                    "Observed debits for an ambiguous counterparty; projected commitment withheld"
                    if counterparty_class == COUNTERPARTY_UNCERTAIN
                    else "Observed historical debits; projected annual cost withheld due to irregular cadence"
                )
            ),
            # Backward compatibility fields
            'monthly_estimate': est_monthly_str,
            'yearly_estimate': est_annual_str,
            # Backward-compatible flag retained for existing UI/tests. Actual
            # evidence is the validated ID list below.
            'candidates': candidates,
            'candidate_transaction_ids': candidate_transaction_ids,
        })

    # Sort primarily by estimated_monthly_cost or observed_period_average descending
    result.sort(key=lambda s: Decimal(s['estimated_monthly_cost'] or s['observed_period_average']), reverse=True)
    return result

# ---------------------------------------------------------------------------
# 4. Unusual Spending Detector
# ---------------------------------------------------------------------------
def detect_unusual_spending(session_id: str, include_persona: bool = False) -> List[Dict[str, Any]]:
    source_type = (
        Transaction.SOURCE_PERSONA if include_persona else Transaction.SOURCE_IMPORT
    )
    qs = Transaction.objects.filter(
        session_id=session_id,
        source_type=source_type,
        transaction_type='DEBIT',
    )
    tx_list = list(qs)

    # Task 23: the duplicate scan used to run one EXISTS query per transaction
    # (121 queries for 120 debits). The candidates are grouped once from the
    # rows that were already loaded, so the whole scan costs a single query and
    # the semantics are unchanged: a same-merchant, same-amount debit within a
    # +/-30 day window is still a duplicate.
    by_identity = defaultdict(list)
    for tx in tx_list:
        by_identity[(tx.normalized_merchant, tx.amount, tx.source_type)].append(tx)

    flagged = []
    for tx in tx_list:
        peers = [t.amount for t in tx_list if t.id != tx.id]
        if peers:
            baseline = _calculate_median(peers)
            threshold = (baseline * Decimal('3')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if tx.amount > threshold:
                flagged.append({
                    'id': str(tx.id),
                    'reason': 'large_amount',
                    'amount': str(tx.amount),
                    'merchant': _display_counterparty(tx.normalized_merchant),
                    'date': tx.transaction_date.isoformat(),
                    'source_type': tx.source_type,
                    'baseline': str(baseline),
                    'threshold': str(threshold),
                })
                continue
        candidates = by_identity.get(
            (tx.normalized_merchant, tx.amount, tx.source_type), []
        )
        dup = any(
            candidate.id != tx.id
            and abs((candidate.transaction_date - tx.transaction_date).days) <= 30
            for candidate in candidates
        )
        if dup:
            flagged.append({
                'id': str(tx.id),
                'reason': 'duplicate_amount_merchant',
                'amount': str(tx.amount),
                'merchant': _display_counterparty(tx.normalized_merchant),
                'date': tx.transaction_date.isoformat(),
                'source_type': tx.source_type,
            })
    return flagged

# ---------------------------------------------------------------------------
# 5. Spending Pattern Analyzer
# ---------------------------------------------------------------------------
def spending_patterns(session_id: str, months: int = 6, include_persona: bool = False) -> Dict[str, Any]:
    today = date.today()
    month_list = []
    for i in range(months - 1, -1, -1):
        month_date = today.replace(day=1) - timedelta(days=30 * i)
        month_list.append((month_date.year, month_date.month))
    monthly_breakdown = {}
    for y, m in month_list:
        monthly_breakdown[f"{y}-{m:02d}"] = monthly_budget(session_id, y, m, include_persona)
    cat_trends = defaultdict(list)
    for data in monthly_breakdown.values():
        for cat, val in data['category_spending'].items():
            cat_trends[cat].append(Decimal(val))
    trend_analysis = {}
    for cat, values in cat_trends.items():
        if len(values) >= 2:
            start = values[0]
            end = values[-1]
            if start == Decimal('0'):
                pct_change = Decimal('0')
            else:
                pct_change = ((end - start) / start * Decimal('100')).quantize(Decimal('0.1'))
            trend = 'increase' if pct_change > 0 else 'decrease'
            trend_analysis[cat] = {'pct_change': str(pct_change), 'trend': trend}
    return {'monthly_breakdown': monthly_breakdown, 'category_trends': trend_analysis}



# ---------------------------------------------------------------------------
# Task 17: Imported-session snapshot/overview computation
# ---------------------------------------------------------------------------
def _derive_statement_period(transactions):
    if not transactions:
        return None, None, None, None
    dates = [t.transaction_date for t in transactions]
    start_date = min(dates)
    end_date = max(dates)
    month_counts = defaultdict(int)
    for d in dates:
        month_counts[(d.year, d.month)] += 1
    year, month = max(month_counts.items(), key=lambda kv: (kv[1], kv[0][0], kv[0][1]))[0]
    return start_date, end_date, year, month


def _resolve_display_category(t) -> str:
    """Dynamically resolve a transaction's display category.

    If the persisted ``t.category`` is ``Uncategorized`` or empty, the
    classification engine is invoked on the normalized merchant so that
    imported transactions receive a meaningful label even when the import
    pipeline stored a generic placeholder.

    The result is formatted for human display (title-case, underscores
    replaced by spaces).
    """
    return category_display_name(resolve_transaction_category(t))


def compute_imported_session_overview(session_id: str) -> Dict[str, Any]:
    from analytics.services import AnalyticsEngine
    import calendar as _cal

    qs = Transaction.objects.filter(session_id=session_id, source_type='import').order_by('transaction_date')
    txs = list(qs)
    if not txs:
        return {
            'source': 'IMPORTED_STATEMENT',
            'has_imported_data': False,
            'data_sufficient': False,
            'insufficient_reason': 'NO_IMPORTED_TRANSACTIONS',
            'statement_period': None,
            'transactions': [],
            'transaction_count': 0,
        }

    start_date, end_date, year, month = _derive_statement_period(txs)
    budget = monthly_budget(session_id, year, month, include_persona=False)

    try:
        subs = detect_subscriptions(session_id, include_persona=False)
    except Exception:
        subs = []
    confirmed_commitments = Decimal('0')
    for s in subs:
        # Task 23: only a confirmed financial commitment (a subscription charge or
        # a fixed obligation) is reserved for the upcoming bill. Repeated
        # discretionary spending never reserves money.
        if s.get('is_financial_commitment'):
            try:
                confirmed_commitments += Decimal(str(s.get('estimated_monthly_cost') or '0'))
            except Exception:
                pass

    monthly_leakage = Decimal('0')
    probable_review_amount = Decimal('0')
    verified_leak_tx_ids = set()
    recurring_review_tx_ids = set()
    for s in subs:
        # A potentially avoidable recurring charge: a confirmed subscription
        # commitment. A weak detection or a repeated purchase is never presented
        # as recoverable money.
        if s.get('is_potential_leakage'):
            try:
                monthly_leakage += Decimal(str(s.get('estimated_monthly_cost') or '0'))
            except Exception:
                pass
            for tx_id in s.get('candidate_transaction_ids') or []:
                if isinstance(tx_id, str):
                    verified_leak_tx_ids.add(tx_id)
        elif s.get('confidence') == RECURRING_PROBABLE:
            try:
                probable_review_amount += Decimal(str(s.get('estimated_monthly_cost') or '0'))
            except Exception:
                pass
            for tx_id in s.get('candidate_transaction_ids') or []:
                if isinstance(tx_id, str):
                    recurring_review_tx_ids.add(tx_id)

    days_covered = (end_date - start_date).days + 1 if start_date and end_date else 0
    unique_days = len(set(t.transaction_date for t in txs))
    distinct_months = len(set((t.transaction_date.year, t.transaction_date.month) for t in txs))

    try:
        monthly_income = Decimal(str(budget.get('operating_income') or budget.get('income') or '0'))
    except Exception:
        monthly_income = Decimal('0')
    try:
        monthly_expenses = Decimal(str(budget.get('net_living_expenses') or budget.get('expenses') or '0'))
    except Exception:
        monthly_expenses = Decimal('0')

    liquid_balance_known = False
    liquid_balance = Decimal('0')

    health = AnalyticsEngine.calculate_health_score(
        monthly_income=float(monthly_income),
        monthly_expenses=float(monthly_expenses),
        liquid_balance=float(liquid_balance) if liquid_balance_known else 0.0,
        fixed_commitments=float(confirmed_commitments),
    )

    period_end = date(year, month, _cal.monthrange(year, month)[1])
    reference_date = end_date if end_date else period_end
    if reference_date > period_end:
        reference_date = period_end
    days_remaining = (period_end - reference_date).days
    if days_remaining < 0:
        days_remaining = 0

    safe_to_spend_sufficient = (
        (monthly_income > 0 or monthly_expenses > 0) and days_remaining > 0 and liquid_balance_known
    )
    if safe_to_spend_sufficient:
        safe = AnalyticsEngine.calculate_safe_to_spend(
            current_balance=float(liquid_balance),
            monthly_income=float(monthly_income),
            pending_fixed_obligations=float(confirmed_commitments),
            days_remaining_in_month=max(1, days_remaining),
        )
        safe_to_spend_status = 'AVAILABLE'
        safe_to_spend_reason = None
    else:
        reason_parts = []
        if not liquid_balance_known:
            reason_parts.append('LIQUID_BALANCE_UNKNOWN')
        if days_remaining <= 0:
            reason_parts.append('PERIOD_ENDED')
        if monthly_income <= 0 and monthly_expenses <= 0:
            reason_parts.append('INSUFFICIENT_TRANSACTION_DATA')
        safe = {
            'safe_to_spend_daily': None,
            'safe_to_spend_weekly': None,
            'uncommitted_discretionary_buffer': None,
            'reserved_safety_floor': None,
            'pending_fixed_obligations': float(confirmed_commitments),
            'days_remaining_in_cycle': days_remaining,
            'status': 'INSUFFICIENT_DATA',
            'guidance': 'Safe-to-Spend is unavailable because imported statement coverage or required balance data is insufficient. Provide a current balance and an in-period statement to compute a reliable figure.',
            'available': False,
            'insufficient_reason': ','.join(reason_parts) or 'INSUFFICIENT_DATA',
        }
        safe_to_spend_status = 'INSUFFICIENT_DATA'
        safe_to_spend_reason = safe.get('insufficient_reason')

    tx_rows = []
    for t in txs:
        # An own-account transfer keeps its place in the ledger but is labelled
        # as what it is, instead of appearing as an ordinary counterparty.
        is_internal_transfer = (t.category and t.category.lower() == 'transfer') or classify_debit(t.normalized_merchant)['is_transfer']
        merchant = (
            INTERNAL_TRANSFER_LABEL
            if is_internal_transfer
            else _display_counterparty(t.normalized_merchant)
        )
        tx_rows.append({
            'id': str(t.id),
            'date': t.transaction_date.isoformat(),
            'description': merchant,
            'merchant': merchant,
            'amount': str(t.amount),
            'type': t.transaction_type,
            'category': _resolve_display_category(t),
            'is_recurring': t.is_recurring,
            # Evidence-derived: a static persona/import flag is never treated
            # as proof that money is recoverable.
            'leak_flag': str(t.id) in verified_leak_tx_ids,
            'recurring_review_flag': str(t.id) in recurring_review_tx_ids,
            'source_type': t.source_type,
            'is_internal_transfer': is_internal_transfer,
        })

    coverage = {
        'start_date': start_date.isoformat() if start_date else None,
        'end_date': end_date.isoformat() if end_date else None,
        'days_covered': days_covered,
        'unique_transaction_days': unique_days,
        'transaction_count': len(txs),
        'distinct_months': distinct_months,
        'is_partial_month_likely': days_covered < 28 or distinct_months > 1,
        'extrapolated': False,
        'note': 'Metrics are calculated from imported transactions in the statement period only. Partial-month statements are not extrapolated to full-month income.',
    }

    return {
        'source': 'IMPORTED_STATEMENT',
        'has_imported_data': True,
        'leakage_basis': 'EVIDENCE_BASED_RECURRING_DETECTION',
        'data_sufficient': True,
        'session_id': session_id,
        'statement_period': {
            'start_date': start_date.isoformat() if start_date else None,
            'end_date': end_date.isoformat() if end_date else None,
            'reporting_year': year,
            'reporting_month': month,
            'label': f"{_cal.month_name[month]} {year}" if year and month else None,
        },
        'data_coverage': coverage,
        'budget': budget,
        'health_metrics': {
            **health,
            'liquid_balance_known': liquid_balance_known,
            # A deterministic score computed without a verified balance is an
            # estimate, and runway must not be presented as an observed value.
            'metric_basis': {
                'income': 'OBSERVED_FROM_IMPORTED_TRANSACTIONS',
                'expenses': 'OBSERVED_FROM_IMPORTED_TRANSACTIONS',
                'runway': 'WITHHELD_BALANCE_UNAVAILABLE' if not liquid_balance_known else 'OBSERVED',
                'health_score': 'ESTIMATED_BALANCE_UNAVAILABLE' if not liquid_balance_known else 'OBSERVED',
            },
        },
        'safe_to_spend': safe,
        'safe_to_spend_status': safe_to_spend_status,
        'safe_to_spend_reason': safe_to_spend_reason,
        'summary': {
            'monthly_income': str(monthly_income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'monthly_expenses': str(monthly_expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'confirmed_commitments': str(confirmed_commitments.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'monthly_leakage': str(monthly_leakage.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'confirmed_recurring_count': sum(1 for s in subs if s.get('is_financial_commitment')),
            'probable_review_count': sum(1 for s in subs if s.get('confidence') == RECURRING_PROBABLE),
            'probable_review_amount': str(probable_review_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'liquid_balance': str(liquid_balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) if liquid_balance_known else None,
            'liquid_balance_known': liquid_balance_known,
        },
        'transactions': tx_rows,
        'transaction_count': len(txs),
    }


def compute_dataset_financial_metrics(
    session_id: str,
    include_persona: bool = False,
) -> Dict[str, Any]:
    """Derive AI-facing metrics from exactly one selected dataset.

    The requested source is validated against the active session: a persona
    request with no persona rows, or an imported request with no imported rows,
    returns INSUFFICIENT_DATA. It never silently substitutes the other source
    or a persona-created snapshot.

    Runway is only produced when a balance appropriate to the selected source is
    available. Imported statements have no verified balance in this schema, so
    their runway is withheld rather than borrowed from a persona snapshot.
    """
    from analytics.services import AnalyticsEngine

    source_label = 'PERSONA_SCENARIO' if include_persona else 'IMPORTED_STATEMENT'
    source_type = Transaction.SOURCE_PERSONA if include_persona else Transaction.SOURCE_IMPORT
    qs = Transaction.objects.filter(session_id=session_id, source_type=source_type)
    txs = list(qs.order_by('transaction_date'))
    base = {
        'status': 'INSUFFICIENT_DATA',
        'data_source': source_label,
        'source_type': source_type,
        'dataset_transaction_count': len(txs),
        'reporting_period': None,
        'monthly_income': 0.0,
        'monthly_expenses': 0.0,
        'health_score': None,
        'health_grade': None,
        'emergency_runway_months': None,
        'runway_status': 'INSUFFICIENT_DATA',
        'balance_source': None,
        'recurring_commitments': {
            'monthly_commitments': 0.0,
            'monthly_leakage': 0.0,
            'probable_review_amount': 0.0,
            'confirmed_commitment_count': 0,
            'recurring_pattern_count': 0,
            'review_candidate_count': 0,
        },
        'metric_basis': {
            'income': 'OBSERVED_FROM_SELECTED_DATASET',
            'expenses': 'OBSERVED_FROM_SELECTED_DATASET',
            'recurring': 'EVIDENCE_BASED_DETECTION',
            'runway': 'WITHHELD',
        },
    }
    if not txs:
        base['insufficient_reason'] = (
            'NO_PERSONA_TRANSACTIONS_IN_SELECTED_DATASET'
            if include_persona else 'NO_IMPORTED_TRANSACTIONS_IN_SELECTED_DATASET'
        )
        return base

    start_date, end_date, year, month = _derive_statement_period(txs)
    budget = monthly_budget(session_id, year, month, include_persona=include_persona)
    subs = detect_subscriptions(session_id, include_persona=include_persona)

    monthly_income = _to_dataset_decimal(budget.get('operating_income') or budget.get('income'))
    monthly_expenses = _to_dataset_decimal(
        budget.get('net_living_expenses') or budget.get('expenses')
    )
    commitments = Decimal('0')
    leakage = Decimal('0')
    probable_review = Decimal('0')
    confirmed_count = 0
    pattern_count = 0
    review_count = 0
    for entry in subs:
        estimated = _to_dataset_decimal(
            entry.get('estimated_monthly_cost') or entry.get('observed_period_average')
        )
        if entry.get('is_financial_commitment'):
            commitments += estimated
            confirmed_count += 1
        elif entry.get('confidence') == RECURRING_PROBABLE:
            probable_review += estimated
            review_count += 1
        else:
            pattern_count += 1
        if entry.get('is_potential_leakage'):
            leakage += estimated

    balance = None
    balance_source = None
    fixed_commitments = commitments
    if include_persona:
        snapshot = (
            FinancialSnapshot.objects.filter(session_id=session_id)
            .order_by('-created_at')
            .first()
        )
        if snapshot and snapshot.liquid_balance > 0:
            balance = Decimal(str(snapshot.liquid_balance))
            balance_source = 'PERSONA_SCENARIO_SNAPSHOT'
            if snapshot.fixed_commitments > 0:
                fixed_commitments = Decimal(str(snapshot.fixed_commitments))

    health = None
    health_grade = None
    if balance is not None:
        health = AnalyticsEngine.calculate_health_score(
            monthly_income=float(monthly_income),
            monthly_expenses=float(monthly_expenses),
            liquid_balance=float(balance),
            fixed_commitments=float(fixed_commitments),
        )
        health_grade = health.get('grade')

    runway = None
    runway_status = 'INSUFFICIENT_DATA'
    if balance is not None and monthly_income > 0 and monthly_expenses >= 0:
        burn = monthly_expenses if monthly_expenses > 0 else fixed_commitments
        if burn > 0:
            runway = float((balance / burn).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            runway_status = 'AVAILABLE'

    base.update({
        'status': 'AVAILABLE',
        'reporting_period': {
            'start_date': start_date.isoformat() if start_date else None,
            'end_date': end_date.isoformat() if end_date else None,
            'label': (
                f"{_cal_month_name(month)} {year}"
                if month and year else None
            ),
        },
        'monthly_income': float(monthly_income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'monthly_expenses': float(monthly_expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'health_score': health.get('health_score') if health else None,
        'health_grade': health_grade,
        'emergency_runway_months': runway,
        'runway_status': runway_status,
        'balance_source': balance_source,
        'recurring_commitments': {
            'monthly_commitments': float(commitments.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'monthly_leakage': float(leakage.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'probable_review_amount': float(probable_review.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'confirmed_commitment_count': confirmed_count,
            'recurring_pattern_count': pattern_count,
            'review_candidate_count': review_count,
        },
        'metric_basis': {
            'income': 'OBSERVED_FROM_SELECTED_DATASET',
            'expenses': 'OBSERVED_FROM_SELECTED_DATASET',
            'recurring': 'EVIDENCE_BASED_DETECTION',
            'runway': 'PERSONA_SCENARIO_ESTIMATE' if include_persona and runway is not None else 'WITHHELD',
            'health_score': 'PERSONA_SCENARIO_ESTIMATE' if include_persona and health else None,
        },
    })
    if runway is None:
        base['insufficient_reason'] = 'BALANCE_UNAVAILABLE_FOR_SELECTED_DATASET'
    return base


def _to_dataset_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or '0'))
    except Exception:
        return Decimal('0')


def _cal_month_name(month: Optional[int]) -> Optional[str]:
    if not month:
        return None
    import calendar as _cal
    return _cal.month_name[month]


# ---------------------------------------------------------------------------
# Evidence-Based Financial Insights Briefing
# ---------------------------------------------------------------------------
# This is ArthaShield's core differentiator. Every insight is backed by
# deterministic calculations from the existing financial engine. The AI
# layer may explain results but never invents financial figures.
#
# Insight structure:
#   id        — stable identifier for the insight type + context
#   type      — one of the _INSIGHT_TYPES below
#   severity  — CRITICAL / HIGH / MEDIUM / LOW / INFO
#   finding   — one-line plain-English statement of what happened
#   evidence  — concrete numbers and transaction references
#   explanation — why this was detected (the rule or calculation)
#   action    — actionable suggestion for the user
#   confidence — always 'VERIFIED' (deterministic calculation)
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {
    'CRITICAL': 0,
    'HIGH': 1,
    'MEDIUM': 2,
    'LOW': 3,
    'INFO': 4,
}

_INSIGHT_TYPES = [
    'BUDGET_STATUS',
    'TOP_EXPENSE',
    'SPENDING_SPIKE',
    'RECURRING_COMMITMENT',
    'POTENTIAL_LEAK',
    'UNUSUAL_TRANSACTION',
    'INCOME_ANALYSIS',
    'REFUND_WATCH',
]


def generate_evidence_briefing(session_id: str, include_persona: bool = False) -> Dict[str, Any]:
    """
    Synthesise a structured, evidence-based financial briefing from existing
    deterministic calculations. No new computations are invented — every
    insight wraps an existing engine output with human-readable context.

    Returns:
        dict with keys: insights, reporting_period, generated_at,
        data_source, insight_count, has_data
    """
    import calendar as _cal

    # ----- Resolve transactions & period ---------------------------------
    qs = Transaction.objects.filter(session_id=session_id)
    if not include_persona:
        qs = qs.filter(source_type='import')
    txs = list(qs.order_by('transaction_date'))

    if not txs:
        return {
            'insights': [],
            'reporting_period': None,
            'generated_at': datetime.now().isoformat(),
            'data_source': 'PERSONA' if include_persona else 'IMPORTED_STATEMENT',
            'insight_count': 0,
            'has_data': False,
        }

    start_date, end_date, year, month = _derive_statement_period(txs)
    period_label = f"{_cal.month_name[month]} {year}" if year and month else "Unknown Period"

    # ----- Call existing engines -----------------------------------------
    budget = monthly_budget(session_id, year, month, include_persona)

    try:
        subs = detect_subscriptions(session_id, include_persona)
    except Exception:
        subs = []

    try:
        unusual = detect_unusual_spending(session_id, include_persona)
    except Exception:
        unusual = []

    # ----- Build insights ------------------------------------------------
    insights = []

    # 1. BUDGET_STATUS
    operating_income = Decimal(budget.get('operating_income', '0'))
    net_expenses = Decimal(budget.get('net_living_expenses', '0'))
    operating_surplus = Decimal(budget.get('operating_surplus', '0'))
    overspending = budget.get('overspending', False)

    if operating_income > 0:
        expense_ratio = (net_expenses / operating_income * Decimal('100')).quantize(
            Decimal('0.1'), rounding=ROUND_HALF_UP
        )
        if overspending:
            severity = 'CRITICAL'
            finding = f"You spent more than you earned in {period_label}."
            action = "Review discretionary categories and identify expenses you can defer or reduce."
        elif expense_ratio > Decimal('80'):
            severity = 'HIGH'
            finding = f"Your expenses consume {expense_ratio}% of your income in {period_label}."
            action = "Your savings margin is thin. Consider setting a spending cap on your top category."
        elif expense_ratio > Decimal('50'):
            severity = 'MEDIUM'
            finding = f"Your expenses consume {expense_ratio}% of your income in {period_label}."
            action = "You have a reasonable savings margin. Consider automating the surplus into savings."
        else:
            severity = 'LOW'
            finding = f"Your expenses consume only {expense_ratio}% of your income in {period_label}."
            action = "Strong savings position. Consider investing the surplus for long-term growth."

        insights.append({
            'id': f'budget_status_{year}_{month}',
            'type': 'BUDGET_STATUS',
            'severity': severity,
            'finding': finding,
            'evidence': {
                'operating_income': str(operating_income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'net_expenses': str(net_expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'operating_surplus': str(operating_surplus.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'expense_to_income_ratio': str(expense_ratio) + '%',
                'period': period_label,
            },
            'explanation': (
                f"Operating income (₹{operating_income.quantize(Decimal('0.01'))}) minus "
                f"net living expenses (₹{net_expenses.quantize(Decimal('0.01'))}) gives a "
                f"surplus of ₹{operating_surplus.quantize(Decimal('0.01'))}. "
                f"Expense-to-income ratio is {expense_ratio}%."
            ),
            'action': action,
            'confidence': 'VERIFIED',
        })

    # 2. TOP_EXPENSE — largest spending category
    cat_spending = budget.get('category_spending', {})
    if cat_spending:
        top_cat = max(
            ((k, Decimal(v)) for k, v in cat_spending.items() if k != 'transfer'),
            key=lambda x: x[1],
            default=None,
        )
        if top_cat and top_cat[1] > 0:
            cat_name, cat_amount = top_cat
            cat_pct = (
                (cat_amount / net_expenses * Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
                if net_expenses > 0 else Decimal('0')
            )
            severity = 'HIGH' if cat_pct > Decimal('40') else 'MEDIUM' if cat_pct > Decimal('25') else 'LOW'
            display_cat = cat_name.replace('_', ' ').title()

            # Top 3 categories for context
            sorted_cats = sorted(
                ((k, Decimal(v)) for k, v in cat_spending.items() if k != 'transfer' and Decimal(v) > 0),
                key=lambda x: x[1],
                reverse=True,
            )[:3]
            top_categories = {
                k.replace('_', ' ').title(): str(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
                for k, v in sorted_cats
            }

            insights.append({
                'id': f'top_expense_{year}_{month}',
                'type': 'TOP_EXPENSE',
                'severity': severity,
                'finding': f"Your largest expense category is {display_cat} at ₹{cat_amount.quantize(Decimal('0.01'))} ({cat_pct}% of expenses).",
                'evidence': {
                    'top_category': display_cat,
                    'amount': str(cat_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                    'percentage_of_expenses': str(cat_pct) + '%',
                    'top_categories': top_categories,
                    'period': period_label,
                },
                'explanation': (
                    f"{display_cat} spending of ₹{cat_amount.quantize(Decimal('0.01'))} represents "
                    f"{cat_pct}% of total net living expenses (₹{net_expenses.quantize(Decimal('0.01'))})."
                ),
                'action': f"Review your {display_cat.lower()} transactions to identify any non-essential spending that can be reduced.",
                'confidence': 'VERIFIED',
            })

    # 3. RECURRING_COMMITMENT — confirmed recurring payments
    confirmed_subs = [s for s in subs if s.get('confidence') == RECURRING_CONFIRMED]
    probable_subs = [s for s in subs if s.get('confidence') == RECURRING_PROBABLE]

    if confirmed_subs:
        total_confirmed_monthly = sum(
            Decimal(s.get('estimated_monthly_cost', '0') or '0') for s in confirmed_subs
        )
        commitment_pct = (
            (total_confirmed_monthly / operating_income * Decimal('100')).quantize(
                Decimal('0.1'), rounding=ROUND_HALF_UP
            )
            if operating_income > 0 else Decimal('0')
        )

        severity = 'HIGH' if commitment_pct > Decimal('30') else 'MEDIUM' if commitment_pct > Decimal('15') else 'LOW'

        sub_details = []
        for s in confirmed_subs[:5]:  # Top 5 for readability
            sub_details.append({
                'merchant': _safe_counterparty_label(s.get('merchant', '')),
                'monthly_cost': s.get('estimated_monthly_cost', '0'),
                'payment_type': s.get('payment_type', 'unknown'),
                'cadence': s.get('cadence', 'unknown'),
            })

        insights.append({
            'id': f'recurring_commitment_{year}_{month}',
            'type': 'RECURRING_COMMITMENT',
            'severity': severity,
            'finding': f"You have {len(confirmed_subs)} confirmed recurring payment(s) totalling ₹{total_confirmed_monthly.quantize(Decimal('0.01'))}/month.",
            'evidence': {
                'confirmed_count': len(confirmed_subs),
                'probable_count': len(probable_subs),
                'total_monthly_cost': str(total_confirmed_monthly.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'commitment_to_income_ratio': str(commitment_pct) + '%' if operating_income > 0 else 'N/A',
                'top_commitments': sub_details,
                'period': period_label,
            },
            'explanation': (
                f"{len(confirmed_subs)} recurring payments were detected with CONFIRMED confidence. "
                f"Total monthly commitment of ₹{total_confirmed_monthly.quantize(Decimal('0.01'))} "
                + (f"represents {commitment_pct}% of operating income." if operating_income > 0 else ".")
            ),
            'action': "Review each recurring payment. Cancel subscriptions you no longer use. Negotiate better rates for utilities and insurance.",
            'confidence': 'VERIFIED',
        })

    # 4. POTENTIAL_LEAK — probable recurring payments that might be leaking money
    leak_subs = [
        s for s in subs
        if s.get('confidence') in (RECURRING_CONFIRMED, RECURRING_PROBABLE)
        and s.get('is_potential_leakage', False)
    ]
    if leak_subs:
        total_leak_monthly = sum(
            Decimal(s.get('estimated_monthly_cost', '0') or '0') for s in leak_subs
        )
        leak_details = []
        for s in leak_subs[:5]:
            leak_details.append({
                'merchant': _safe_counterparty_label(s.get('merchant', '')),
                'monthly_cost': s.get('estimated_monthly_cost', '0'),
                'payment_type': s.get('payment_type', 'unknown'),
                'confidence': s.get('confidence', 'UNKNOWN'),
            })

        severity = 'HIGH' if total_leak_monthly > Decimal('500') else 'MEDIUM'
        insights.append({
            'id': f'potential_leak_{year}_{month}',
            'type': 'POTENTIAL_LEAK',
            'severity': severity,
            'finding': f"{len(leak_subs)} recurring payment(s) flagged as potential leakage, totalling ₹{total_leak_monthly.quantize(Decimal('0.01'))}/month.",
            'evidence': {
                'leak_count': len(leak_subs),
                'total_monthly_leakage': str(total_leak_monthly.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'annual_impact': str((total_leak_monthly * 12).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'flagged_payments': leak_details,
                'period': period_label,
            },
            'explanation': (
                f"These payments are recurring charges to discretionary services (subscriptions, "
                f"memberships). If unused, they represent ₹{(total_leak_monthly * 12).quantize(Decimal('0.01'))} "
                f"per year in avoidable spending."
            ),
            'action': "Check whether you actively use each flagged service. Cancel inactive subscriptions to recover this spending.",
            'confidence': 'VERIFIED',
        })

    # 5. UNUSUAL_TRANSACTION — transactions flagged by the anomaly detector
    if unusual:
        large_amount = [u for u in unusual if u.get('reason') == 'large_amount']
        duplicates = [u for u in unusual if u.get('reason') == 'duplicate_amount_merchant']

        if large_amount:
            top_unusual = large_amount[0]
            insights.append({
                'id': f'unusual_tx_{top_unusual.get("id", "unknown")}',
                'type': 'UNUSUAL_TRANSACTION',
                'severity': 'HIGH',
                'finding': f"₹{top_unusual['amount']} to {_safe_counterparty_label(top_unusual.get('merchant', 'Unknown'))} on {top_unusual['date']} is significantly above your typical spending.",
                'evidence': {
                    'amount': top_unusual['amount'],
                    'merchant': _safe_counterparty_label(top_unusual.get('merchant', '')),
                    'date': top_unusual['date'],
                    'baseline_median': top_unusual.get('baseline', 'N/A'),
                    'threshold': top_unusual.get('threshold', 'N/A'),
                    'total_flagged': len(large_amount),
                },
                'explanation': (
                    f"This transaction exceeds 3× the median of all other debits "
                    f"(median: ₹{top_unusual.get('baseline', 'N/A')}, threshold: ₹{top_unusual.get('threshold', 'N/A')}). "
                    f"{len(large_amount)} transaction(s) total were flagged as unusually large."
                ),
                'action': "Verify this transaction is intentional. If unexpected, contact your bank immediately.",
                'confidence': 'VERIFIED',
            })

        if duplicates:
            insights.append({
                'id': f'duplicate_flag_{year}_{month}',
                'type': 'UNUSUAL_TRANSACTION',
                'severity': 'MEDIUM',
                'finding': f"{len(duplicates)} potential duplicate charge(s) detected — same merchant, same amount within 30 days.",
                'evidence': {
                    'duplicate_count': len(duplicates),
                    'examples': [
                        {
                            'merchant': _safe_counterparty_label(d.get('merchant', '')),
                            'amount': d['amount'],
                            'date': d['date'],
                        }
                        for d in duplicates[:3]
                    ],
                },
                'explanation': (
                    "Transactions with the same merchant and amount appearing within a 30-day window "
                    "may indicate accidental double charges. This is a detection flag, not a fraud accusation."
                ),
                'action': "Review these charges. If unintentional, contact the merchant for a refund.",
                'confidence': 'VERIFIED',
            })

    # 6. INCOME_ANALYSIS
    earned_income = Decimal(budget.get('earned_income', '0'))
    investment_yield = Decimal(budget.get('investment_yield', '0'))
    total_credits = Decimal(budget.get('total_credits', '0'))
    refunds_received = Decimal(budget.get('refunds_received', '0'))
    credit_breakdown = budget.get('credit_breakdown', {})
    unclassified_credits = Decimal(credit_breakdown.get('unclassified', '0'))

    if total_credits > 0:
        income_sources = {
            k.replace('_', ' ').title(): v
            for k, v in credit_breakdown.items()
            if Decimal(v or '0') > 0
        }

        severity = 'INFO'
        if operating_income == 0 and total_credits > 0:
            severity = 'MEDIUM'
            if unclassified_credits > 0:
                finding = (
                    f"No earned or investment income detected in {period_label}. "
                    f"Total inflows of \u20b9{total_credits.quantize(Decimal('0.01'))} include "
                    f"\u20b9{unclassified_credits.quantize(Decimal('0.01'))} in unclassified credits "
                    f"requiring review."
                )
            else:
                finding = (
                    f"No earned or investment income detected in {period_label}. "
                    f"Total inflows of \u20b9{total_credits.quantize(Decimal('0.01'))} are from non-income sources."
                )
        elif unclassified_credits > 0:
            finding = (
                f"Total credits of \u20b9{total_credits.quantize(Decimal('0.01'))}: "
                f"Recognised operating income \u20b9{operating_income.quantize(Decimal('0.01'))}, "
                f"Unclassified credits \u20b9{unclassified_credits.quantize(Decimal('0.01'))}."
            )
        elif earned_income > 0 and investment_yield > 0:
            finding = (
                f"Income from {len([v for v in income_sources.values() if Decimal(v) > 0])} source(s) "
                f"in {period_label}: \u20b9{operating_income.quantize(Decimal('0.01'))} operating income."
            )
        else:
            finding = f"Operating income of \u20b9{operating_income.quantize(Decimal('0.01'))} in {period_label}."

        # Build transparent explanation with unclassified reconciliation
        if unclassified_credits > 0:
            explanation = (
                f"Total credits of \u20b9{total_credits.quantize(Decimal('0.01'))} include "
                f"\u20b9{operating_income.quantize(Decimal('0.01'))} recognised operating income "
                f"and \u20b9{unclassified_credits.quantize(Decimal('0.01'))} unclassified credits. "
                f"Unclassified credits lack verified payroll, yield or client contract markers "
                f"and are conservatively excluded from operating income rather than guessed."
            )
        else:
            explanation = (
                f"Total credits of \u20b9{total_credits.quantize(Decimal('0.01'))} include "
                f"earned income (\u20b9{earned_income.quantize(Decimal('0.01'))}), "
                f"investment yields (\u20b9{investment_yield.quantize(Decimal('0.01'))}), "
                f"and refunds (\u20b9{refunds_received.quantize(Decimal('0.01'))})."
            )

        insights.append({
            'id': f'income_analysis_{year}_{month}',
            'type': 'INCOME_ANALYSIS',
            'severity': severity,
            'finding': finding,
            'evidence': {
                'total_credits': str(total_credits.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'operating_income': str(operating_income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'earned_income': str(earned_income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'investment_yield': str(investment_yield.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'refunds_received': str(refunds_received.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'unclassified_credits': str(unclassified_credits.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'income_sources': income_sources,
                'period': period_label,
            },
            'explanation': explanation,
            'action': (
                "Review unclassified credits to determine whether they represent earned income, "
                "client payments, or other inflows. Diversify income sources when possible."
            ) if unclassified_credits > 0 else (
                "Diversify income sources when possible. Track investment returns separately for tax planning."
            ),
            'confidence': 'VERIFIED',
        })

    # 7. REFUND_WATCH
    refund_details = budget.get('refund_details', [])
    if refund_details:
        confirmed_refunds = [r for r in refund_details if r.get('allocation_status') == ALLOC_APPLIED]
        unmatched_refunds = [r for r in refund_details if r.get('allocation_status') == ALLOC_NOT_ALLOCATED]

        if unmatched_refunds:
            total_unmatched = sum(Decimal(r.get('amount', '0')) for r in unmatched_refunds)
            severity = 'MEDIUM' if total_unmatched > Decimal('500') else 'LOW'
            insights.append({
                'id': f'refund_watch_{year}_{month}',
                'type': 'REFUND_WATCH',
                'severity': severity,
                'finding': f"{len(unmatched_refunds)} refund(s) totalling ₹{total_unmatched.quantize(Decimal('0.01'))} could not be matched to an original purchase.",
                'evidence': {
                    'total_refunds': len(refund_details),
                    'confirmed_matched': len(confirmed_refunds),
                    'unmatched': len(unmatched_refunds),
                    'unmatched_amount': str(total_unmatched.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                    'period': period_label,
                },
                'explanation': (
                    f"The refund matching engine found {len(refund_details)} refund(s) in {period_label}. "
                    f"{len(confirmed_refunds)} were matched to original purchases with confirmed evidence. "
                    f"{len(unmatched_refunds)} could not be matched — the original purchase may be outside "
                    f"the statement period or from a different account."
                ),
                'action': "Check the unmatched refunds against your purchase history to ensure all expected refunds have been received.",
                'confidence': 'VERIFIED',
            })
        elif confirmed_refunds:
            total_confirmed = sum(Decimal(r.get('allocated_amount', '0')) for r in confirmed_refunds)
            insights.append({
                'id': f'refund_watch_{year}_{month}',
                'type': 'REFUND_WATCH',
                'severity': 'INFO',
                'finding': f"All {len(confirmed_refunds)} refund(s) in {period_label} were matched to original purchases (₹{total_confirmed.quantize(Decimal('0.01'))} recovered).",
                'evidence': {
                    'total_refunds': len(refund_details),
                    'confirmed_matched': len(confirmed_refunds),
                    'total_recovered': str(total_confirmed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                    'period': period_label,
                },
                'explanation': (
                    f"The refund matching engine confirmed all {len(confirmed_refunds)} refund(s) are "
                    f"linked to identified purchases with shared reference evidence."
                ),
                'action': "No action needed. All refunds are accounted for.",
                'confidence': 'VERIFIED',
            })

    # ----- Sort by severity and return -----------------------------------
    insights.sort(key=lambda i: _SEVERITY_ORDER.get(i['severity'], 99))

    return {
        'insights': insights,
        'reporting_period': {
            'start_date': start_date.isoformat() if start_date else None,
            'end_date': end_date.isoformat() if end_date else None,
            'year': year,
            'month': month,
            'label': period_label,
        },
        'generated_at': datetime.now().isoformat(),
        'data_source': 'PERSONA' if include_persona else 'IMPORTED_STATEMENT',
        'insight_count': len(insights),
        'has_data': True,
    }
