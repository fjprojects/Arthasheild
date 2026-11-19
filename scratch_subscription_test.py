"""Verify detect_subscriptions behavior with/without include_persona."""
import sys, os
sys.path.insert(0, "backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
import django
django.setup()

from api.insights import detect_subscriptions
from api.models import Transaction, FinancialSnapshot, SecureSession
from django.test import TestCase
from datetime import date
from decimal import Decimal
import uuid

# Create a temporary session with persona transactions
session_id = str(uuid.uuid4())

# Create session
session = SecureSession.objects.create(session_id=session_id)
# Create snapshot
snapshot = FinancialSnapshot.objects.create(session_id=session_id)

# Insert Rohit's recurring transactions as persona source
rohit_recurring = [
    ("POS ADOBE SYSTEMS RENEWAL INT", 4200, True),
    ("POS AMAZON WEB SERVICES CLOUD", 1500, True),
    ("POS FIGMA SUBSCRIPTION CA", 1250, True),
    ("POS OPENAI CHATGPT PLUS MONTHLY", 1650, False),
    ("POS GITHUB COPILOT AUTO-DEBIT", 830, False),
]

for desc, amt, leak in rohit_recurring:
    Transaction.objects.create(
        snapshot=snapshot,
        session_id=session_id,
        transaction_date=date(2026, 10, 5),
        amount=Decimal(str(amt)),
        transaction_type="DEBIT",
        normalized_merchant=desc,
        category="Subscriptions",
        is_recurring=True,
        is_leak=leak,
        source_type="persona",
    )
    # Add a second occurrence for recurring detection
    Transaction.objects.create(
        snapshot=snapshot,
        session_id=session_id,
        transaction_date=date(2026, 9, 5),
        amount=Decimal(str(amt)),
        transaction_type="DEBIT",
        normalized_merchant=desc,
        category="Subscriptions",
        is_recurring=True,
        is_leak=leak,
        source_type="persona",
    )

print("=" * 70)
print("TEST: detect_subscriptions with include_persona=True")
print("=" * 70)
result_with = detect_subscriptions(session_id, include_persona=True)
print(f"  Found {len(result_with)} recurring patterns")
for s in result_with:
    cost = s.get("estimated_monthly_cost", 0)
    is_comm = s.get("is_financial_commitment", False)
    is_leak = s.get("is_potential_leakage", False)
    cclass = s.get("commitment_class", "?")
    print(f"    {s.get('merchant', '?')[:40]:<40s}  cost={cost:<8}  commitment={is_comm}  leak={is_leak}  class={cclass}")

print()
print("=" * 70)
print("TEST: detect_subscriptions with include_persona=False")
print("=" * 70)
result_without = detect_subscriptions(session_id, include_persona=False)
print(f"  Found {len(result_without)} recurring patterns")
for s in result_without:
    cost = s.get("estimated_monthly_cost", 0)
    print(f"    {s.get('merchant', '?')[:40]:<40s}  cost={cost}")

print()
print("DIAGNOSIS: When include_persona=False, detector finds 0 patterns because")
print("           all transactions are source_type='persona', filtered out by the query.")

# Cleanup
Transaction.objects.filter(session_id=session_id).delete()
FinancialSnapshot.objects.filter(session_id=session_id).delete()
SecureSession.objects.filter(session_id=session_id).delete()
print()
print("Cleanup complete.")
