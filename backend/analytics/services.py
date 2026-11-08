import math
from datetime import date, datetime
from typing import Dict, List, Any, Optional

class AnalyticsEngine:
    """
    Deterministic Mathematical Finance Engine.
    All calculations are strictly deterministic Python math to prevent any AI hallucinations.
    """

    @staticmethod
    def calculate_runway(current_balance: float, monthly_fixed_burn: float) -> float:
        """Calculates emergency fund runway in months, clamped to >= 0.0."""
        if monthly_fixed_burn <= 0:
            return 12.0 if current_balance > 0 else 0.0
        return max(0.0, round(current_balance / monthly_fixed_burn, 2))

    @staticmethod
    def calculate_health_score(
        monthly_income: float,
        monthly_expenses: float,
        liquid_balance: float,
        fixed_commitments: float
    ) -> Dict[str, Any]:
        """
        Deterministic Financial Health Scorecard (0 to 100).
        Based on financial planning standards (Emergency Runway, DTI, Savings Rate).
        """
        effective_income = max(1.0, float(monthly_income))

        # 1. Runway Score (Max 35 pts)
        burn = float(fixed_commitments) or (float(monthly_expenses) * 0.6)
        runway_months = AnalyticsEngine.calculate_runway(float(liquid_balance), burn)
        
        if runway_months >= 6:
            runway_score = 35
        elif runway_months >= 3:
            runway_score = 25
        elif runway_months >= 1.5:
            runway_score = 15
        elif runway_months >= 0.8:
            runway_score = 8
        else:
            runway_score = 3

        # 2. Debt-to-Income Pressure (Max 35 pts)
        dti_ratio = round((float(fixed_commitments) / effective_income) * 100, 1)
        if monthly_income <= 0 and fixed_commitments > 0:
            dti_score = 0
            dti_ratio = 100.0
        elif dti_ratio <= 15:
            dti_score = 35
        elif dti_ratio <= 25:
            dti_score = 28
        elif dti_ratio <= 35:
            dti_score = 20
        elif dti_ratio <= 50:
            dti_score = 10
        else:
            dti_score = 2

        # 3. Savings / Buffer Rate (Max 30 pts)
        net_savings = float(monthly_income) - float(monthly_expenses)
        savings_rate = round((net_savings / effective_income) * 100, 1) if monthly_income > 0 else 0.0
        if savings_rate >= 25:
            savings_score = 30
        elif savings_rate >= 15:
            savings_score = 22
        elif savings_rate >= 5:
            savings_score = 14
        elif savings_rate >= 0:
            savings_score = 6
        else:
            savings_score = 0  # Burning capital

        total_score = max(5, min(100, runway_score + dti_score + savings_score))

        if total_score >= 80:
            grade = "A (Resilient)"
            summary = "Excellent financial foundation with healthy liquidity cushion and low debt pressure."
        elif total_score >= 60:
            grade = "B (Stable)"
            summary = "Fairly stable, but subscription leaks or debt commitments are eroding buffer."
        elif total_score >= 40:
            grade = "C (Vulnerable)"
            summary = "Tight liquidity runway. Vulnerable to unexpected financial shocks."
        else:
            grade = "D (Critical)"
            summary = "Immediate cashflow distress risk. Fixed commitments exceed safe limits."

        return {
            "health_score": total_score,
            "grade": grade,
            "summary": summary,
            "metrics": {
                "runway_months": runway_months,
                "debt_to_income_ratio_pct": dti_ratio,
                "savings_rate_pct": savings_rate,
                "net_monthly_buffer": round(net_savings, 2)
            },
            "disclaimer": "Deterministic rule-based mathematical model. For educational analysis only, not certified financial advice."
        }

    @staticmethod
    def calculate_safe_to_spend(
        current_balance: float,
        monthly_income: float,
        pending_fixed_obligations: float,
        days_remaining_in_month: int = 20,
        safety_buffer_pct: float = 0.15
    ) -> Dict[str, Any]:
        """
        Forward-looking liquidity engine.
        Calculates how much the user can safely spend today and this week without risking defaults.
        """
        days_remaining = max(1, days_remaining_in_month)
        bal = max(0.0, float(current_balance))
        inc = max(0.0, float(monthly_income))
        obligations = max(0.0, float(pending_fixed_obligations))
        
        # Reserve safety buffer (15% of monthly income or 20% of balance)
        emergency_floor = min(bal * 0.2, inc * safety_buffer_pct)
        
        disposable_pool = float(current_balance) - obligations - emergency_floor
        
        if disposable_pool <= 0:
            daily_safe = 0.0
            weekly_safe = 0.0
            status = "RESTRICTED_CASHFLOW"
            guidance = "Your pending commitments exceed available balance after safety buffer. Freeze non-essential purchases."
        else:
            daily_safe = round(disposable_pool / days_remaining, 2)
            weekly_safe = round(min(disposable_pool, daily_safe * 7), 2)
            status = "HEALTHY"
            guidance = f"You have ₹{daily_safe:,.2f} safe daily discretionary budget until next credit cycle."

        return {
            "safe_to_spend_daily": daily_safe,
            "safe_to_spend_weekly": weekly_safe,
            "uncommitted_discretionary_buffer": max(0.0, round(disposable_pool, 2)),
            "reserved_safety_floor": round(emergency_floor, 2),
            "pending_fixed_obligations": round(obligations, 2),
            "days_remaining_in_cycle": days_remaining,
            "status": status,
            "guidance": guidance
        }

    @staticmethod
    def simulate_emi_decision(
        item_name: str,
        price: float,
        tenure_months: int,
        down_payment: float = 0.0,
        nominal_annual_interest_rate_pct: float = 0.0,
        monthly_processing_or_conv_fee: float = 199.0,
        user_monthly_discretionary_buffer: float = 12000.0
    ) -> Dict[str, Any]:
        """
        EMI 'What-If' Reality Check Engine.
        Exposes hidden processing fees, GST on subvention, and computes True Effective APR.
        """
        p = max(0.0, float(price))
        dp = max(0.0, float(down_payment))
        principal = max(0.0, p - dp)
        n = max(1, int(tenure_months))
        nominal_rate = max(0.0, float(nominal_annual_interest_rate_pct))
        conv_fee = max(0.0, float(monthly_processing_or_conv_fee))
        disc_buffer = max(1.0, float(user_monthly_discretionary_buffer))
        
        # Calculate base EMI
        if nominal_rate <= 0 or principal <= 0:
            base_monthly_emi = principal / n
            total_interest = 0.0
        else:
            r = (nominal_rate / 100.0) / 12.0
            base_monthly_emi = (principal * r * math.pow(1 + r, n)) / (math.pow(1 + r, n) - 1)
            total_interest = (base_monthly_emi * n) - principal

        # Hidden fees calculation (Convenience fee + 18% GST)
        gst_rate = 0.18
        monthly_fee_with_gst = conv_fee * (1 + gst_rate)
        total_hidden_fees = monthly_fee_with_gst * n

        total_cash_outflow = dp + (base_monthly_emi * n) + total_hidden_fees
        effective_monthly_cost = base_monthly_emi + monthly_fee_with_gst

        # Approximate True Effective APR including hidden fees
        total_extra_paid = total_interest + total_hidden_fees
        effective_apr = round(((total_extra_paid / max(1.0, principal)) / (n / 12.0)) * 100, 2)

        # Affordability check
        pct_of_discretionary_eaten = round((effective_monthly_cost / disc_buffer) * 100, 1)
        
        if pct_of_discretionary_eaten > 40:
            is_viable = False
            verdict = "HIGH RISK: Would consume over 40% of your free monthly cash buffer."
        elif pct_of_discretionary_eaten > 25:
            is_viable = True
            verdict = "MODERATE: Manageable, but substantially reduces your buffer for emergency spending."
        else:
            is_viable = True
            verdict = "LOW RISK: Easily fits within your current discretionary cashflow."

        return {
            "item_name": item_name,
            "original_price": p,
            "tenure_months": n,
            "advertised_interest_rate_pct": nominal_rate,
            "base_monthly_emi": round(base_monthly_emi, 2),
            "effective_monthly_outflow": round(effective_monthly_cost, 2),
            "total_interest_paid": round(total_interest, 2),
            "total_hidden_fees_and_gst": round(total_hidden_fees, 2),
            "total_overall_cost": round(total_cash_outflow, 2),
            "true_effective_apr_pct": effective_apr,
            "pct_of_discretionary_buffer_used": pct_of_discretionary_eaten,
            "is_viable": is_viable,
            "verdict": verdict,
            "hidden_trap_disclosure": (
                f"Even with an advertised {nominal_rate}% interest rate, "
                f"recurring fees and GST add ₹{total_hidden_fees:,.2f} extra, "
                f"raising the true annual borrowing cost to {effective_apr}% APR."
            )
        }
