from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import List, Dict, Any

from django.db.models import Sum, Q

from .models import Transaction, ConsentAuditLog, FinancialSnapshot

# ---------------------------------------------------------------------------
# Helper: simple keyword‑based categorization
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS = {
    'food': ['swiggy', 'zomato', 'restaurant', 'cafe', 'food', 'meal', 'pizza', 'burger', 'dine', 'biryani', 'tiffin', 'dhaba'],
    'shopping': ['amazon', 'flipkart', 'myntra', 'shopping', 'store', 'retail', 'clothing', 'apparel'],
    'travel': ['airline', 'flight', 'uber', 'ola', 'taxi', 'rail', 'train', 'hotel', 'booking'],
    'bills': ['electricity', 'water', 'gas', 'utility', 'bill', 'telecom', 'mobile', 'internet'],
    'salary': ['salary', 'payroll', 'remuneration', 'salary credited', 'salary credit'],
    'emi': ['emi', 'loan', 'mortgage', 'installment'],
    'subscriptions': ['netflix', 'spotify', 'prime', 'subscription', 'membership', 'saas', 'gym'],
    'healthcare': ['hospital', 'clinic', 'pharmacy', 'medicine', 'doctor', 'lab', 'health'],
}

def _categorize(normalized_merchant: str) -> str:
    """Return a category based on keyword matching (case‑insensitive)."""
    merchant = normalized_merchant.lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in merchant:
                return cat
    return 'other'

# ---------------------------------------------------------------------------
# 1. Transaction Categorization
# ---------------------------------------------------------------------------
def categorize_transactions(session_id: str, include_persona: bool = False) -> List[Dict[str, Any]]:
    qs = Transaction.objects.filter(session_id=session_id)
    if not include_persona:
        qs = qs.filter(source_type='import')
    result = []
    for tx in qs:
        category = _categorize(tx.normalized_merchant)
        result.append({
            'id': str(tx.id),
            'date': tx.transaction_date.isoformat(),
            'amount': str(tx.amount),
            'type': tx.transaction_type,
            'merchant': tx.normalized_merchant,
            'category': category,
            'source_type': tx.source_type,
        })
    return result

# ---------------------------------------------------------------------------
# 2. Monthly Budget Analyzer
# ---------------------------------------------------------------------------
def monthly_budget(session_id: str, year: int, month: int, include_persona: bool = False) -> Dict[str, Any]:
    start = date(year, month, 1)
    # end of month (exclusive)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    qs = Transaction.objects.filter(session_id=session_id, transaction_date__gte=start, transaction_date__lt=end)
    if not include_persona:
        qs = qs.filter(source_type='import')
    # Income: CREDIT transactions (including salary)
    income = qs.filter(transaction_type='CREDIT').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    # Expenses: DEBIT transactions
    expenses = qs.filter(transaction_type='DEBIT').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    # Category‑wise spending (expenses only)
    cat_spend = defaultdict(Decimal)
    for tx in qs.filter(transaction_type='DEBIT'):
        cat = _categorize(tx.normalized_merchant)
        cat_spend[cat] += tx.amount
    savings = income - expenses
    overspending = expenses > income
    # format Decimal to string with two decimal places
    cat_spend_str = {k: str(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) for k, v in cat_spend.items()}
    return {
        'year': year,
        'month': month,
        'income': str(income.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'expenses': str(expenses.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'savings': str(savings.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'overspending': overspending,
        'category_spending': cat_spend_str,
    }

# ---------------------------------------------------------------------------
# 3. Subscription Detector
# ---------------------------------------------------------------------------
def detect_subscriptions(session_id: str, include_persona: bool = False) -> List[Dict[str, Any]]:
    qs = Transaction.objects.filter(session_id=session_id, is_recurring=True)
    if not include_persona:
        qs = qs.filter(source_type='import')
    subs = []
    for tx in qs:
        identifier = getattr(tx, 'reference_id', None) or tx.normalized_merchant
        subs.append({
            'id': str(tx.id),
            'merchant': tx.normalized_merchant,
            'identifier': identifier,
            'amount': str(tx.amount),
            'type': tx.transaction_type,
        })
    # Group by identifier to consolidate
    grouped = defaultdict(list)
    for s in subs:
        grouped[s['identifier']].append(s)
    result = []
    for identifier, items in grouped.items():
        amounts = [Decimal(i['amount']) for i in items]
        # Choose smallest amount as conservative monthly estimate
        monthly = min(amounts)
        yearly = (monthly * Decimal('12')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        result.append({
            'identifier': identifier,
            'merchant': items[0]['merchant'],
            'monthly_estimate': str(monthly.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'yearly_estimate': str(yearly),
            'candidates': len(items) > 1,
        })
    return result

# ---------------------------------------------------------------------------
# 4. Unusual Spending Detector
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


def detect_unusual_spending(session_id: str, include_persona: bool = False) -> List[Dict[str, Any]]:
    qs = Transaction.objects.filter(session_id=session_id, transaction_type='DEBIT')
    if not include_persona:
        qs = qs.filter(source_type='import')
    tx_list = list(qs)
    flagged = []
    for tx in tx_list:
        # Peer comparison baseline: exclude current transaction so it cannot inflate its own baseline
        peers = [t.amount for t in tx_list if t.id != tx.id]
        if peers:
            baseline = _calculate_median(peers)
            threshold = (baseline * Decimal('3')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if tx.amount > threshold:
                flagged.append({
                    'id': str(tx.id),
                    'reason': 'large_amount',
                    'amount': str(tx.amount),
                    'merchant': tx.normalized_merchant,
                    'date': tx.transaction_date.isoformat(),
                    'source_type': tx.source_type,
                    'baseline': str(baseline),
                    'threshold': str(threshold),
                })
                continue
        # Duplicate detection: same amount and merchant within 30 days window
        start_window = tx.transaction_date - timedelta(days=30)
        end_window = tx.transaction_date + timedelta(days=30)
        dup = Transaction.objects.filter(
            session_id=session_id,
            transaction_type='DEBIT',
            normalized_merchant=tx.normalized_merchant,
            amount=tx.amount,
            transaction_date__range=(start_window, end_window)
        ).exclude(id=tx.id)
        if not include_persona:
            dup = dup.filter(source_type='import')
        if dup.exists():
            flagged.append({
                'id': str(tx.id),
                'reason': 'duplicate_amount_merchant',
                'amount': str(tx.amount),
                'merchant': tx.normalized_merchant,
                'date': tx.transaction_date.isoformat(),
                'source_type': tx.source_type,
            })
    return flagged

# ---------------------------------------------------------------------------
# 5. Spending Pattern Analyzer
# ---------------------------------------------------------------------------
def spending_patterns(session_id: str, months: int = 6, include_persona: bool = False) -> Dict[str, Any]:
    today = date.today()
    # Build list of (year, month) for the last N months inclusive
    month_list = []
    for i in range(months - 1, -1, -1):
        # move back i months
        month_date = today.replace(day=1) - timedelta(days=30 * i)
        month_list.append((month_date.year, month_date.month))
    monthly_breakdown = {}
    for y, m in month_list:
        monthly_breakdown[f"{y}-{m:02d}"] = monthly_budget(session_id, y, m, include_persona)
    # Category trend analysis across the period
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

