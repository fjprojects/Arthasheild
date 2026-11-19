"""
Synthetic Persona Scenario Simulation.
Deterministic Engine Evaluation Across 5 Archetypal Financial Scenarios.

NOTE: This is an automated algorithmic simulation across 5 synthetic financial profiles
to verify mathematical model behavior across diverse cash-flow patterns.
It is NOT an empirical human usability study.
"""

from datetime import date
from decimal import Decimal
import uuid
import json

from api.models import SecureSession, ConsentAuditLog, FinancialSnapshot, Transaction
from analytics.stress_test import run_commitment_stress_test


def run_usability_study():
    participants = [
        {
            "id": "P1_ARUN",
            "name": "Arun S. (Salaried Software Eng, 28)",
            "goal": "Evaluate ₹75,000 Laptop on 6M No-Cost EMI",
            "income": 70000.0,
            "liquid_balance": 45000.0,
            "rent": 22000.0,
            "living_expenses": 38000.0,
            "commitment": {
                "item_name": "Pro Developer Laptop",
                "price": 75000.0,
                "type": "no_cost_emi",
                "tenure": 6,
                "down_payment": 0.0,
                "monthly_fee": 199.0,
                "upfront_fee": 299.0,
            }
        },
        {
            "id": "P2_PRIYA",
            "name": "Priya M. (Freelance Designer, 25)",
            "goal": "Evaluate ₹18,000 Annual Design Suite Subscription",
            "income": 45000.0,
            "liquid_balance": 25000.0,
            "rent": 12000.0,
            "living_expenses": 28000.0,
            "commitment": {
                "item_name": "Creative Suite Annual",
                "price": 18000.0,
                "type": "large_purchase",
                "tenure": 1,
                "down_payment": 0.0,
                "monthly_fee": 0.0,
                "upfront_fee": 0.0,
            }
        },
        {
            "id": "P3_KARTHIK",
            "name": "Karthik R. (Systems Analyst, 31)",
            "goal": "Evaluate ₹50,000 Motorcycle Down Payment",
            "income": 85000.0,
            "liquid_balance": 110000.0,
            "rent": 20000.0,
            "living_expenses": 35000.0,
            "commitment": {
                "item_name": "Motorcycle Down Payment",
                "price": 50000.0,
                "type": "large_purchase",
                "tenure": 1,
                "down_payment": 0.0,
                "monthly_fee": 0.0,
                "upfront_fee": 0.0,
            }
        },
        {
            "id": "P4_ANANYA",
            "name": "Ananya D. (Senior PM, 34)",
            "goal": "Evaluate ₹90,000 Smartphone on 12M EMI",
            "income": 125000.0,
            "liquid_balance": 80000.0,
            "rent": 35000.0,
            "living_expenses": 55000.0,
            "commitment": {
                "item_name": "Flagship Smartphone",
                "price": 90000.0,
                "type": "no_cost_emi",
                "tenure": 12,
                "down_payment": 10000.0,
                "monthly_fee": 199.0,
                "upfront_fee": 500.0,
            }
        },
        {
            "id": "P5_VIKRAM",
            "name": "Vikram J. (Strategy Consultant, 39)",
            "goal": "Evaluate ₹35,000 Tablet: Buy Now vs Wait 45 Days",
            "income": 65000.0,
            "liquid_balance": 55000.0,
            "rent": 25000.0,
            "living_expenses": 58000.0,
            "commitment": {
                "item_name": "Executive Tablet",
                "price": 35000.0,
                "type": "large_purchase",
                "tenure": 1,
                "down_payment": 0.0,
                "monthly_fee": 0.0,
                "upfront_fee": 0.0,
            }
        }
    ]

    results = []

    for p in participants:
        sid = f"study_{p['id'].lower()}_{uuid.uuid4().hex[:6]}"
        snap = FinancialSnapshot.objects.create(
            session_id=sid,
            liquid_balance=Decimal(str(p["liquid_balance"])),
            monthly_income=Decimal(str(p["income"])),
            monthly_expenses=Decimal(str(p["living_expenses"])),
            fixed_commitments=Decimal(str(p["rent"])),
        )

        Transaction.objects.create(
            session_id=sid,
            transaction_date=date(2026, 10, 1),
            amount=Decimal(str(p["income"])),
            transaction_type="CREDIT",
            normalized_merchant="Verified Salary / Client Payout",
            category="Salary",
            source_type="import",
        )
        Transaction.objects.create(
            session_id=sid,
            transaction_date=date(2026, 10, 5),
            amount=Decimal(str(p["rent"])),
            transaction_type="DEBIT",
            normalized_merchant="House Rent Auto Debit",
            category="Bills",
            source_type="import",
            is_recurring=True,
        )
        other_exp = p["living_expenses"] - p["rent"]
        if other_exp > 0:
            Transaction.objects.create(
                session_id=sid,
                transaction_date=date(2026, 10, 10),
                amount=Decimal(str(other_exp)),
                transaction_type="DEBIT",
                normalized_merchant="Living Expenses & Utilities",
                category="Groceries",
                source_type="import",
                is_recurring=False,
            )

        c = p["commitment"]
        res = run_commitment_stress_test(
            session_id=sid,
            item_name=c["item_name"],
            price=c["price"],
            commitment_type=c["type"],
            tenure_months=c["tenure"],
            down_payment=c["down_payment"],
            monthly_processing_fee=c["monthly_fee"],
            upfront_processing_fee=c["upfront_fee"],
            delay_days=30,
            as_of_date=date(2026, 10, 15),
        )

        results.append({
            "participant": p["name"],
            "goal": p["goal"],
            "verdict": res["overall_verdict"],
            "reason": res["primary_reason"],
            "safe_flip_days": res["judgment_flip"]["safe_flip_days"],
            "flips_to_safe_at_30d": res["judgment_flip"]["flips_to_safe"],
            "evidence_tx_count": res["evidence_ledger"]["verified_session_tx_count"],
        })

    return results

if __name__ == "__main__":
    out = run_usability_study()
    print(json.dumps(out, indent=2))
