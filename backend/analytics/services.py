import calendar
import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Any, Optional

_MONEY_QUANTUM = Decimal('0.01')

# Upper bound for a single discounted cash-flow factor. Keeps the IRR solver
# finite for extreme rate/horizon combinations (no overflow, no NaN).
_MAX_DISCOUNT = 1e250


def _as_decimal(value, default: Decimal = Decimal('0')) -> Decimal:
    """Coerce arbitrary input to a finite Decimal, falling back safely."""
    if value is None:
        return default
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return default
    return result if result.is_finite() else default


def _as_int(value, default: int = 12) -> int:
    """Coerce arbitrary input to an int without raising on bad durations."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp_decimal(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return min(max(value, low), high)


def _add_months(start: date, months: int) -> date:
    """Calendar-month addition with end-of-month clamping (leap years included)."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _parse_date(value) -> Optional[date]:
    """Accept a date/datetime or an ISO ``YYYY-MM-DD`` string; else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _money(value: Decimal) -> float:
    """Round a Decimal to 2 dp using financial half-up rounding."""
    return float(value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP))


def _round_places(value: Decimal, places: int) -> float:
    quantum = Decimal('1').scaleb(-places)
    return float(value.quantize(quantum, rounding=ROUND_HALF_UP))


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
    def calculate_xirr(
        cash_flows,
        rate_tolerance: float = 1e-12,
        max_iterations: int = 200,
    ) -> Dict[str, Any]:
        """
        Dated internal rate of return (XIRR) using an actual-days/365 basis.

        The relationship solved is:

            NPV(r) = sum( CF(i) / (1 + r) ** (days(i) / 365) ) = 0

        Positive cash flows are money received by the borrower, negative cash
        flows are money paid by the borrower. The returned ``annual_rate`` is
        the annual effective borrowing rate (a fraction, not a percentage).

        A bracketed bisection method is used because it is deterministic and
        numerically stable for the monotonic NPV curve of a loan (one inflow
        followed by outflows). The function never raises for malformed input
        and never returns NaN or Infinity; instead it returns
        ``status='UNAVAILABLE'`` with a machine-readable ``reason``.
        """
        meta = {
            "method": "XIRR_ACTUAL_365",
            "annualization_basis": "actual_days/365",
            "solver": "bisection",
            "status": "UNAVAILABLE",
            "reason": None,
            "converged": False,
            "iterations": 0,
            "annual_rate": None,
            "annual_rate_pct": None,
        }

        def unavailable(reason: str) -> Dict[str, Any]:
            return {**meta, "status": "UNAVAILABLE", "reason": reason}

        try:
            normalized = []
            for entry in cash_flows:
                day, amount = entry
                parsed_day = _parse_date(day)
                if parsed_day is None:
                    return unavailable("INVALID_CASH_FLOW_DATE")
                try:
                    amount_float = float(amount)
                except (TypeError, ValueError):
                    return unavailable("INVALID_CASH_FLOW_AMOUNT")
                if not math.isfinite(amount_float):
                    return unavailable("INVALID_CASH_FLOW_AMOUNT")
                normalized.append((parsed_day, amount_float))
        except (TypeError, ValueError):
            return unavailable("INVALID_CASH_FLOWS")

        if len(normalized) < 2:
            return unavailable("INSUFFICIENT_CASH_FLOWS")

        normalized.sort(key=lambda item: item[0])
        t0 = normalized[0][0]
        days = [(day - t0).days for day, _ in normalized]
        amounts = [amount for _, amount in normalized]

        if not any(a > 0 for a in amounts) or not any(a < 0 for a in amounts):
            return unavailable("NO_SIGN_CHANGE")

        scale = sum(abs(a) for a in amounts)
        if scale <= 0:
            return unavailable("ZERO_CASH_FLOWS")

        def discount(rate: float, years: float) -> float:
            """(1 + rate) ** (-years), computed without overflow/underflow.

            The naive ``factor ** years`` raises OverflowError for extreme
            rate/horizon combinations (e.g. a 50-year horizon with a large
            trial rate). Working in log space and clamping keeps the value
            finite and preserves its sign for the bracketing logic.
            """
            if rate <= -1.0:
                return _MAX_DISCOUNT
            log_factor = -years * math.log1p(rate)
            if log_factor >= math.log(_MAX_DISCOUNT):
                return _MAX_DISCOUNT
            if log_factor <= -745.0:
                return 0.0
            return math.exp(log_factor)

        def npv(rate: float) -> float:
            total = 0.0
            for day, amount in zip(days, amounts):
                total += amount * discount(rate, day / 365.0)
            return total

        f_zero = npv(0.0)
        # A zero rate is a genuine root when undiscounted inflows equal outflows.
        if abs(f_zero) <= 1e-9 * scale:
            result = {**meta, "status": "OK", "reason": None, "converged": True,
                      "iterations": 0, "annual_rate": 0.0, "annual_rate_pct": 0.0}
            return result

        # Establish a bracket with a sign change. A normal loan has a negative
        # NPV at 0% and tends to +CF(0) as r -> +inf. A negative-cost set of
        # flows has a positive NPV at 0% and a sign change between -100% and 0%.
        if f_zero < 0:
            lo, flo = 0.0, f_zero
            hi, fhi = 1.0, npv(1.0)
            expansions = 0
            while fhi <= 0.0 and expansions < 64 and hi < 1e9:
                hi *= 2.0
                fhi = npv(hi)
                expansions += 1
            if fhi <= 0.0:
                return unavailable("NO_BRACKET")
        else:
            hi, fhi = 0.0, f_zero
            lo = -0.5
            flo = npv(lo)
            expansions = 0
            while flo >= 0.0 and expansions < 64:
                lo = (lo - 1.0) / 2.0
                if lo <= -1.0 + 1e-12:
                    lo = -1.0 + 1e-12
                flo = npv(lo)
                expansions += 1
            if flo >= 0.0:
                return unavailable("NO_BRACKET")

        rate = None
        converged = False
        iterations = 0
        if flo == 0.0:
            rate, converged = lo, True
        elif fhi == 0.0:
            rate, converged = hi, True
        else:
            for i in range(1, max_iterations + 1):
                iterations = i
                mid = (lo + hi) / 2.0
                if mid == lo or mid == hi:
                    rate, converged = mid, True
                    break
                fmid = npv(mid)
                if abs(fmid) <= 1e-9 * scale or (hi - lo) <= rate_tolerance * max(1.0, abs(mid)):
                    rate, converged = mid, True
                    break
                if (flo < 0.0) == (fmid < 0.0):
                    lo, flo = mid, fmid
                else:
                    hi, fhi = mid, fmid

        if not converged:
            return unavailable("NO_CONVERGENCE")
        if rate is None or not math.isfinite(rate) or rate <= -1.0:
            return unavailable("NON_FINITE_RESULT")

        return {
            **meta,
            "status": "OK",
            "reason": None,
            "converged": True,
            "iterations": iterations,
            "annual_rate": float(rate),
            "annual_rate_pct": _round_places(Decimal(str(rate)) * Decimal('100'), 2),
        }

    @staticmethod
    def simulate_emi_decision(
        item_name: str,
        price: float,
        tenure_months: int,
        down_payment: float = 0.0,
        nominal_annual_interest_rate_pct: float = 0.0,
        monthly_processing_or_conv_fee: float = 199.0,
        user_monthly_discretionary_buffer: float = 12000.0,
        upfront_processing_fee: float = 0.0,
        gst_rate_pct: float = 18.0,
        start_date=None,
        first_payment_date=None,
    ) -> Dict[str, Any]:
        """
        EMI "What-If" Reality Check Engine.

        Fee model (kept explicit so the meaning of every input is documented):

        * ``monthly_processing_or_conv_fee`` - a recurring convenience/levy
          charged every month for the whole tenure (historically ₹199/month).
        * ``upfront_processing_fee`` - optional one-time processing fee paid at
          disbursement; it is deducted from the amount the borrower receives.
        * ``gst_rate_pct`` - GST applied to both fee components (18% default).
          Set to 0 for a no-GST scenario.

        The effective annual borrowing cost is the XIRR of the borrower's
        actual dated cash flows (net disbursement in, EMI + recurring fee out),
        not a nominal-rate-plus-fee-load approximation.
        """
        warnings: List[str] = []

        # --- Input normalization (Decimal, bounded, never NaN/Inf) ---
        p = _clamp_decimal(_as_decimal(price), Decimal('0'), Decimal('1000000000000'))
        dp = _clamp_decimal(_as_decimal(down_payment), Decimal('0'), p)
        principal = max(Decimal('0'), p - dp)

        n = _as_int(tenure_months, 12)
        if n < 1:
            n = 1
            warnings.append('TENURE_CLAMPED_TO_1')
        elif n > 600:
            n = 600
            warnings.append('TENURE_CLAMPED_TO_600')

        nominal_rate = _clamp_decimal(
            _as_decimal(nominal_annual_interest_rate_pct), Decimal('0'), Decimal('1000')
        )
        recurring_fee = _clamp_decimal(
            _as_decimal(monthly_processing_or_conv_fee), Decimal('0'), Decimal('1000000000')
        )
        upfront_fee = _clamp_decimal(
            _as_decimal(upfront_processing_fee), Decimal('0'), Decimal('1000000000')
        )
        gst_rate = _clamp_decimal(
            _as_decimal(gst_rate_pct), Decimal('0'), Decimal('100')
        ) / Decimal('100')
        disc_buffer = _clamp_decimal(
            _as_decimal(user_monthly_discretionary_buffer, Decimal('12000')),
            Decimal('1'), Decimal('1000000000000')
        )

        # --- Amortizing EMI on the financed principal ---
        if nominal_rate <= 0 or principal <= 0:
            base_monthly_emi = principal / Decimal(n)
            total_interest = Decimal('0')
        else:
            monthly_rate = nominal_rate / Decimal('100') / Decimal('12')
            factor = (Decimal('1') + monthly_rate) ** n
            if factor == Decimal('1'):
                base_monthly_emi = principal / Decimal(n)
            else:
                base_monthly_emi = principal * monthly_rate * factor / (factor - Decimal('1'))
            total_interest = max(Decimal('0'), base_monthly_emi * Decimal(n) - principal)

        # --- Fees and GST ---
        recurring_fee_with_gst = recurring_fee * (Decimal('1') + gst_rate)
        upfront_fee_with_gst = upfront_fee * (Decimal('1') + gst_rate)
        total_recurring_fees = recurring_fee_with_gst * Decimal(n)
        total_fees_and_gst = total_recurring_fees + upfront_fee_with_gst

        effective_monthly_cost = base_monthly_emi + recurring_fee_with_gst
        total_repayment = (base_monthly_emi * Decimal(n)) + total_recurring_fees
        total_cash_outflow = dp + total_repayment + upfront_fee_with_gst

        # --- Dated cash flows and effective annual cost (XIRR) ---
        today = date.today()
        interest_date = _parse_date(start_date) or today
        first_pay = _parse_date(first_payment_date)

        apr_status = 'OK'
        apr_reason = None
        apr_result = None
        cash_flows = []

        if principal <= 0:
            apr_status = 'NOT_APPLICABLE'
            apr_reason = 'NO_PRINCIPAL_FINANCED'
        else:
            if first_pay is not None:
                if first_pay <= interest_date:
                    apr_status = 'UNAVAILABLE'
                    apr_reason = 'INVALID_PAYMENT_SCHEDULE'
                    payment_dates = []
                else:
                    payment_dates = [_add_months(first_pay, k) for k in range(n)]
            else:
                payment_dates = [_add_months(interest_date, k) for k in range(1, n + 1)]

            if apr_status == 'OK':
                net_disbursement = principal - upfront_fee_with_gst
                if net_disbursement <= 0:
                    apr_status = 'UNAVAILABLE'
                    apr_reason = 'NON_POSITIVE_NET_DISBURSEMENT'
                else:
                    solver_flows = [(interest_date, float(net_disbursement))]
                    solver_flows.extend(
                        (payment_date, -float(effective_monthly_cost))
                        for payment_date in payment_dates
                    )
                    cash_flows = [
                        {
                            "date": interest_date.isoformat(),
                            "amount": _money(net_disbursement),
                            "kind": "net_disbursement",
                        }
                    ]
                    cash_flows.extend(
                        {
                            "date": payment_date.isoformat(),
                            "amount": -_money(effective_monthly_cost),
                            "kind": "repayment",
                        }
                        for payment_date in payment_dates
                    )
                    apr_result = AnalyticsEngine.calculate_xirr(solver_flows)
                    if apr_result["status"] != 'OK':
                        apr_status = 'UNAVAILABLE'
                        apr_reason = apr_result.get("reason")

        effective_cost_pct = (
            apr_result["annual_rate_pct"]
            if apr_status == 'OK' and apr_result is not None
            else None
        )
        is_effective_cost_available = effective_cost_pct is not None

        # --- Affordability check against discretionary monthly buffer ---
        pct_of_discretionary_eaten = _round_places(
            (effective_monthly_cost / disc_buffer) * Decimal('100'), 1
        )

        if pct_of_discretionary_eaten > 40.0:
            is_viable = False
            status_label = "HIGH RISK"
            verdict = "HIGH RISK: Would consume over 40% of your free monthly cash buffer."
        elif pct_of_discretionary_eaten > 25.0:
            is_viable = True
            status_label = "MODERATE"
            verdict = "MODERATE: Manageable, but substantially reduces your buffer for emergency spending."
        else:
            is_viable = True
            status_label = "LOW RISK"
            verdict = "LOW RISK: Easily fits within your current discretionary cashflow."

        if apr_status == 'OK' and effective_cost_pct is not None:
            disclosure = (
                f"Advertised nominal rate: {_money(nominal_rate)}%. "
                f"Fees and GST add ₹{_money(total_fees_and_gst):,.2f} over {n} months. "
                f"Discounting the actual borrower cash flows (XIRR, actual/365) gives an "
                f"effective annual borrowing cost of {effective_cost_pct}%, not the nominal rate."
            )
        elif apr_status == 'NOT_APPLICABLE':
            disclosure = (
                "No principal is financed, so an effective annual borrowing cost is not defined."
            )
        else:
            disclosure = (
                "Effective annual borrowing cost could not be calculated for these inputs "
                f"({apr_reason}). The nominal rate and fee totals shown are not an APR."
            )

        cost_breakdown = {
            "principal_financed": _money(principal),
            "down_payment": _money(dp),
            "total_interest": _money(total_interest),
            "monthly_fee_with_gst": _money(recurring_fee_with_gst),
            "total_fees_and_gst": _money(total_fees_and_gst),
            "recurring_fees_and_gst": _money(total_recurring_fees),
            "upfront_fees_and_gst": _money(upfront_fee_with_gst),
            "total_cash_outflow": _money(total_cash_outflow),
            "total_repayment": _money(total_repayment),
        }

        fee_assumptions = {
            "upfront_fee": _money(upfront_fee),
            "upfront_fee_gst_rate_pct": _money(gst_rate * Decimal('100')),
            "upfront_fee_gst": _money(upfront_fee_with_gst - upfront_fee),
            "upfront_fee_with_gst": _money(upfront_fee_with_gst),
            "recurring_fee_per_month": _money(recurring_fee),
            "recurring_fee_gst_rate_pct": _money(gst_rate * Decimal('100')),
            "recurring_fee_gst_per_month": _money(recurring_fee_with_gst - recurring_fee),
            "recurring_fee_with_gst_per_month": _money(recurring_fee_with_gst),
            "recurring_fee_total_with_gst": _money(total_recurring_fees),
            "gst_applied": gst_rate > 0,
            "fees_financed": False,
            "fees_paid": (
                "upfront_and_monthly" if upfront_fee > 0 and recurring_fee > 0
                else "upfront" if upfront_fee > 0
                else "monthly" if recurring_fee > 0
                else "none"
            ),
        }

        apr_calculation = {
            "status": apr_status,
            "reason": apr_reason,
            "method": "XIRR_ACTUAL_365",
            "annualization_basis": "actual_days/365",
            "solver": "bisection",
            "converged": bool(apr_result and apr_result.get("converged")),
            "iterations": int(apr_result.get("iterations", 0)) if apr_result else 0,
            "annual_rate": (
                float(apr_result["annual_rate"])
                if apr_result and apr_result.get("annual_rate") is not None
                else None
            ),
            "annual_rate_pct": effective_cost_pct,
            "net_disbursement": (
                _money(principal - upfront_fee_with_gst) if principal > 0 else 0.0
            ),
            "upfront_fee_with_gst": _money(upfront_fee_with_gst),
            "monthly_outflow": _money(effective_monthly_cost),
            "repayment_count": n if principal > 0 else 0,
            "start_date": interest_date.isoformat(),
            "first_payment_date": cash_flows[1]["date"] if len(cash_flows) > 1 else None,
            "last_payment_date": cash_flows[-1]["date"] if len(cash_flows) > 1 else None,
            "cash_flows": cash_flows,
            "precision_note": (
                "Monetary components are computed in Decimal and displayed to 2 dp; "
                "XIRR is solved in float64 on unrounded amounts and reported to 2 dp."
            ),
        }

        affordability_verdict = {
            "status": status_label,
            "buffer_consumed_pct": pct_of_discretionary_eaten,
            "explanation": verdict,
            "is_viable": is_viable,
        }

        return {
            "item_name": item_name,
            "original_price": _money(p),
            "price": _money(p),
            "down_payment": _money(dp),
            "principal": _money(principal),
            "tenure_months": n,
            "advertised_interest_rate_pct": _money(nominal_rate),
            "nominal_apr": _money(nominal_rate),
            "nominal_annual_interest_rate_pct": _money(nominal_rate),
            "monthly_processing_fee": _money(recurring_fee),
            "monthly_recurring_fee": _money(recurring_fee),
            "monthly_fee_with_gst": _money(recurring_fee_with_gst),
            "upfront_processing_fee": _money(upfront_fee),
            "base_monthly_emi": _money(base_monthly_emi),
            "monthly_emi": _money(effective_monthly_cost),
            "effective_monthly_outflow": _money(effective_monthly_cost),
            "total_interest_paid": _money(total_interest),
            "total_hidden_fees_and_gst": _money(total_fees_and_gst),
            "total_overall_cost": _money(total_cash_outflow),
            "total_repayment": _money(total_repayment),
            "effective_annual_cost_pct": effective_cost_pct,
            "is_effective_cost_available": is_effective_cost_available,
            "true_effective_apr_pct": effective_cost_pct,
            "effective_apr_pct": effective_cost_pct,
            "apr_calculation": apr_calculation,
            "fee_assumptions": fee_assumptions,
            "apr_disclaimer": (
                "Model estimate from user-supplied inputs. Not a lender offer and "
                "not a regulatory APR disclosure."
            ),
            "pct_of_discretionary_buffer_used": pct_of_discretionary_eaten,
            "is_viable": is_viable,
            "verdict": verdict,
            "cost_breakdown": cost_breakdown,
            "affordability_verdict": affordability_verdict,
            "input_warnings": warnings,
            "hidden_trap_disclosure": disclosure,
        }
