"""EMI/XIRR verification — read-only."""
import sys, os
sys.path.insert(0, "backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
import django
django.setup()

from analytics.services import AnalyticsEngine
from datetime import date
from decimal import Decimal

result = AnalyticsEngine.simulate_emi_decision(
    item_name="Test Phone",
    price=65000.0,
    tenure_months=12,
    down_payment=0.0,
    nominal_annual_interest_rate_pct=0.0,
    monthly_processing_or_conv_fee=199.0,
    upfront_processing_fee=0.0,
    gst_rate_pct=18.0,
    user_monthly_discretionary_buffer=12000.0,
    start_date=date(2026, 11, 17),
)

cb = result["cost_breakdown"]
apr_calc = result["apr_calculation"]
fa = result["fee_assumptions"]

print("=== EMI Simulation: 65k, 12mo, 199 fee, 18% GST ===")
print("  principal_financed:       ", cb["principal_financed"])
print("  monthly_emi (base):       ", result["monthly_emi"])
print("  monthly_fee_with_gst:     ", cb["monthly_fee_with_gst"])
print("  effective_monthly_outflow:", result["effective_monthly_outflow"])
print("  total_repayment:          ", cb["total_repayment"])
print("  total_fees_and_gst:       ", cb["total_fees_and_gst"])
print("  total_cash_outflow:       ", cb["total_cash_outflow"])
print("  total_interest:           ", cb["total_interest"])
print()
print("  XIRR status:              ", apr_calc["status"])
print("  XIRR converged:           ", apr_calc["converged"])
print("  XIRR annual_rate:         ", apr_calc["annual_rate"])
print("  XIRR annual_rate_pct:     ", apr_calc["annual_rate_pct"])
print("  XIRR iterations:          ", apr_calc["iterations"])
print("  net_disbursement:         ", apr_calc["net_disbursement"])
print("  monthly_outflow:          ", apr_calc["monthly_outflow"])
print()
print("  Fee assumptions:")
print("    recurring_fee_per_month:         ", fa["recurring_fee_per_month"])
print("    recurring_fee_gst_per_month:     ", fa["recurring_fee_gst_per_month"])
print("    recurring_fee_with_gst_per_month:", fa["recurring_fee_with_gst_per_month"])
print("    recurring_fee_total_with_gst:    ", fa["recurring_fee_total_with_gst"])
print()

# Manual cross-check
principal = Decimal("65000")
monthly_principal = principal / 12
fee = Decimal("199")
gst = fee * Decimal("0.18")
fee_gst = fee + gst
monthly_outflow = monthly_principal + fee_gst
total_repayment = monthly_outflow * 12
total_fees = fee_gst * 12
print("=== Manual Cross-Check ===")
print("  monthly_principal:  ", monthly_principal)
print("  fee+gst/month:      ", fee_gst)
print("  monthly_outflow:    ", monthly_outflow)
print("  total_repayment:    ", total_repayment)
print("  total_fees+gst:     ", total_fees)

# Verify XIRR independently with known cash flows
print()
print("=== Independent XIRR Verification ===")
# For 0% interest, borrower receives 65000 today and pays (5416.67 + 234.82) * 12 monthly
# Net disbursement = 65000 (no upfront fee)
# Monthly outflow = 5416.67 + 234.82 = 5651.49
# XIRR should be the annual cost of paying 234.82/mo extra on a 65000 principal
net_disb = float(principal)
mo_pay = float(monthly_outflow)
start = date(2026, 11, 17)
flows = [(start, net_disb)]
for m in range(1, 13):
    pay_date = date(2026 + (10 + m) // 12, (10 + m) % 12 + 1, 17)
    flows.append((pay_date, -mo_pay))
print("  Cash flows for XIRR:")
for d, a in flows:
    print(f"    {d}: {a:.2f}")
xirr_result = AnalyticsEngine.calculate_xirr(flows)
print()
print("  XIRR result:")
print("    status:    ", xirr_result["status"])
print("    converged: ", xirr_result["converged"])
print("    annual_rate:", xirr_result["annual_rate"])
print("    annual_pct:", xirr_result["annual_rate_pct"])
print("    iterations:", xirr_result["iterations"])
