"""Scratch audit verification script — read-only, no modifications."""
import json
import sys
import os

sys.path.insert(0, "backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django
django.setup()

from api.insights import (
    classify_credit, classify_debit, _categorize,
    _CATEGORY_KEYWORDS, CREDIT_CLASSIFICATION_RULES,
    detect_subscriptions, categorize_transactions,
)
from decimal import Decimal


def test_recurring_vs_leakage():
    """Verify the 9430 vs 6950 discrepancy from personas.json."""
    with open("synthetic_data/personas.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    rohit = next(p for p in data["personas"] if p["id"] == "persona_freelancer_rohit")

    print("=" * 70)
    print("TEST: Recurring vs Leakage Amounts (persona_freelancer_rohit)")
    print("=" * 70)

    recurring_total = 0
    leak_total = 0
    sub_total = 0

    for tx in rohit["transactions"]:
        if tx.get("is_recurring"):
            amt = tx["amount"]
            leak = tx.get("leak_flag", False) or False
            recurring_total += amt
            if leak:
                leak_total += amt
            desc = tx["description"][:45]
            cat = tx.get("category", "")
            print(f"  {desc:<45s}  amt={amt:>6}  leak={str(leak):<5s}  cat={cat}")

    print()
    print(f"  Total recurring (all types):       {recurring_total}")
    print(f"  Total leak_flag=True only:          {leak_total}")

    dls = rohit.get("detected_leaks_summary", {})
    print(f"  detected_leaks_summary.total:       {dls.get('total_monthly_leakage')}")
    print(f"  detected_leaks_summary.items_count: {dls.get('items_count')}")
    print()

    # Diagnosis
    print("  DIAGNOSIS:")
    print(f"    detected_leaks_summary counts ALL 5 subscription items = {dls.get('total_monthly_leakage')}")
    print(f"    But only 3 items have leak_flag=True in transactions = {leak_total}")
    print(f"    ChatGPT (1650) and GitHub Copilot (830) have leak_flag=None")
    print(f"    LeakageRadar shows {dls.get('total_monthly_leakage')} from detected_leaks_summary")
    print(f"    Audit Ledger LEAKS filter uses tx.is_leak (leak_flag) = {leak_total}")
    print()


def test_credit_classification():
    """Verify that the 40k credit is misclassified."""
    print("=" * 70)
    print("TEST: Credit Classification (tx_r10 = 40k DESIGN RET)")
    print("=" * 70)

    result = classify_credit("NEFT CRED APEX STUDIOS DESIGN RET")
    print(f"  classify_credit('NEFT CRED APEX STUDIOS DESIGN RET'):")
    for k, v in result.items():
        print(f"    {k}: {v}")
    print()
    print(f"  EXPECTED: credit_type=earned_income, category=salary")
    print(f"  ACTUAL:   credit_type={result['credit_type']}, category={result['category']}")
    print(f"  BUG: 'retainer' is in earned_income keywords but abbreviation 'RET' does not match")
    print()


def test_debit_rent_classification():
    """Verify that rent is classified as 'bills' not 'Rent & Housing'."""
    print("=" * 70)
    print("TEST: Debit Classification (tx_r15 = 22k Apartment Rent)")
    print("=" * 70)

    result = classify_debit("UPI/APARTMENT RENT/LANDLORD/9811234567@upi")
    print(f"  classify_debit('UPI/APARTMENT RENT/LANDLORD/...'):")
    for k, v in result.items():
        print(f"    {k}: {v}")
    print()
    print(f"  EXPECTED: category=rent_housing (or Rent & Housing)")
    print(f"  ACTUAL:   category={result['category']}")
    print(f"  BUG: _CATEGORY_KEYWORDS puts 'rent', 'apartment', 'landlord' under 'bills'")
    print()


def test_categorize_ignores_stored_category():
    """Verify categorize_transactions ignores tx.category field."""
    print("=" * 70)
    print("TEST: categorize_transactions ignores tx.category field")
    print("=" * 70)
    # Read the source
    import inspect
    src = inspect.getsource(categorize_transactions)
    uses_tx_category = "tx.category" in src
    print(f"  Source mentions tx.category: {uses_tx_category}")
    print(f"  Source calls classify_credit: {'classify_credit' in src}")
    print(f"  Source calls classify_debit: {'classify_debit' in src}")
    print()
    if not uses_tx_category:
        print("  BUG: categorize_transactions() NEVER reads tx.category from the database.")
        print("        It always recomputes from normalized_merchant via keyword matching.")
        print("        This discards authoritative categories stored during persona load / import.")
    print()


def test_sanitizer_ordering():
    """Verify account number is redacted as CARD instead of ACCOUNT."""
    print("=" * 70)
    print("TEST: Sanitizer Pattern Ordering (Account vs Card)")
    print("=" * 70)
    from sanitizer.services import SanitizerService
    # Rohit's account number format
    test_input = "Account Number: 4821-9988-1200-5541"
    result = SanitizerService.sanitize(test_input)
    print(f"  Input:     {test_input}")
    print(f"  Output:    {result['sanitized_text']}")
    print(f"  Redactions:")
    for r in result["redactions"]:
        print(f"    type={r['type']}, placeholder={r['placeholder']}, count={r['count']}")
    print()

    expected_placeholder = "[REDACTED_ACCOUNT]"
    if expected_placeholder in result["sanitized_text"]:
        print(f"  PASS: Account number correctly masked as {expected_placeholder}")
    elif "[REDACTED_CARD]" in result["sanitized_text"]:
        print(f"  BUG: Account number masked as [REDACTED_CARD] instead of [REDACTED_ACCOUNT]")
    else:
        print(f"  UNEXPECTED: Neither placeholder found")
    print()

    # Also test a plain card number
    test_card = "Card Number: 5432-1098-7654-3210"
    result2 = SanitizerService.sanitize(test_card)
    print(f"  Input:     {test_card}")
    print(f"  Output:    {result2['sanitized_text']}")
    print()

    # Test a standalone 16-digit number (no context)
    test_bare = "Payment via 4821998812005541"
    result3 = SanitizerService.sanitize(test_bare)
    print(f"  Input:     {test_bare}")
    print(f"  Output:    {result3['sanitized_text']}")
    print()


def test_emi_xirr_calculation():
    """Verify EMI and XIRR calculations for the reference example."""
    print("=" * 70)
    print("TEST: EMI Reality Check — 65000, 12 months, 199 fee, 18% GST")
    print("=" * 70)

    from analytics.stress_test import compute_stress_test
    from decimal import Decimal
    from datetime import date

    # Manually compute expected values
    principal = Decimal("65000")
    months = 12
    monthly_principal = principal / months
    fee_per_month = Decimal("199")
    gst_rate = Decimal("0.18")
    fee_gst = fee_per_month * gst_rate
    total_fee_per_month = fee_per_month + fee_gst
    monthly_outflow = monthly_principal + total_fee_per_month
    total_repayment = monthly_outflow * months
    total_fees_gst = total_fee_per_month * months

    print(f"  Principal:            {principal}")
    print(f"  Monthly principal:    {monthly_principal:.2f}")
    print(f"  Fee per month:        {fee_per_month}")
    print(f"  GST on fee (18%):     {fee_gst:.2f}")
    print(f"  Total fee+GST/month:  {total_fee_per_month:.2f}")
    print(f"  Monthly outflow:      {monthly_outflow:.2f}")
    print(f"  Total repayment:      {total_repayment:.2f}")
    print(f"  Total fees+GST:       {total_fees_gst:.2f}")
    print()

    # Now test the stress_test engine
    # Check if it has the EMI/XIRR computation
    import inspect
    src = inspect.getsource(compute_stress_test)
    has_xirr = "xirr" in src.lower()
    has_emi = "emi" in src.lower()
    print(f"  compute_stress_test has XIRR logic: {has_xirr}")
    print(f"  compute_stress_test has EMI logic:   {has_emi}")
    print()


def test_ai_analysis_snapshot_source():
    """Verify the AI analysis view uses the correct snapshot."""
    print("=" * 70)
    print("TEST: AI Analysis View — Snapshot Source Resolution")
    print("=" * 70)

    with open("backend/api/views.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Find the AI analysis section
    idx = content.find("advisor_insights = AdvisorService.analyze_sanitized_statement")
    if idx < 0:
        print("  Could not find AdvisorService call in views.py")
        return

    # Get surrounding context (200 chars before)
    start = max(0, idx - 500)
    end = min(len(content), idx + 300)
    snippet = content[start:end]

    # Check for hardcoded include_persona=True
    if "include_persona=True" in snippet:
        print("  BUG: AI analysis calls detect_subscriptions with include_persona=True (hardcoded)")
    else:
        print("  include_persona is dynamic or absent")

    # Check snapshot resolution
    if ".first()" in snippet:
        print("  WARNING: FinancialSnapshot uses .first() — may return persona snapshot over imported")
    print()

    # Check the exact line
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if "detect_subscriptions" in line and "include_persona" in line and i > 600:
            print(f"  Line {i+1}: {line.strip()}")
    for i, line in enumerate(lines):
        if "FinancialSnapshot" in line and "first" in line:
            print(f"  Line {i+1}: {line.strip()}")
    print()


def test_financial_intelligence_include_persona():
    """Verify FinancialIntelligence.jsx default for includePersona."""
    print("=" * 70)
    print("TEST: FinancialIntelligence.jsx includePersona Default")
    print("=" * 70)

    with open("frontend/src/components/FinancialIntelligence.jsx", "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if "includePersona" in line and ("useState" in line or "false" in line.lower()):
                print(f"  Line {i}: {line.strip()}")

    print()
    print("  DIAGNOSIS: includePersona defaults to false.")
    print("  In persona mode, the Financial Intelligence panel calls getSubscriptions")
    print("  with include_persona=false, which filters to source_type='import' only.")
    print("  With no imported data, subscriptions = 0, showing 'Zero subscription traps'.")
    print()


if __name__ == "__main__":
    test_recurring_vs_leakage()
    test_credit_classification()
    test_debit_rent_classification()
    test_categorize_ignores_stored_category()
    test_sanitizer_ordering()
    test_emi_xirr_calculation()
    test_ai_analysis_snapshot_source()
    test_financial_intelligence_include_persona()

    print("=" * 70)
    print("ALL VERIFICATION TESTS COMPLETE")
    print("=" * 70)
