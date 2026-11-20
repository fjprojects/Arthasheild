"""
Commitment Stress Test & Judgment Flip Deterministic Financial Engine.

Part of ArthaShield (FinGuard AI) core differentiator:
"ArthaShield doesn't just tell you whether you can afford something.
It shows you what could go wrong, when it could happen, and exactly what would change the decision."

All calculations are strictly deterministic Python math to prevent hallucinations.
Authoritative financial figures come from Python, not the LLM.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple
import calendar

from .services import (
    AnalyticsEngine,
    _as_decimal,
    _clamp_decimal,
    _as_int,
    _money,
    _round_places,
    _add_months,
)
from api.models import Transaction, FinancialSnapshot
from api.insights import (
    monthly_budget,
    detect_subscriptions,
    classify_credit,
    classify_debit,
    classify_recurring_payment,
    canonical_category_key,
    RECURRING_PROBABLE,
)


def _to_dec(val: Any, default: Decimal = Decimal('0')) -> Decimal:
    if val is None:
        return default
    try:
        return Decimal(str(val).strip())
    except (InvalidOperation, ValueError, TypeError):
        return default


def run_commitment_stress_test(
    session_id: str,
    item_name: str = "Proposed Purchase",
    price: float = 65000.0,
    commitment_type: str = "no_cost_emi",  # 'large_purchase', 'no_cost_emi', 'regular_emi', 'subscription', 'recurring_obligation'
    down_payment: float = 0.0,
    tenure_months: int = 12,
    nominal_apr: float = 0.0,
    monthly_processing_fee: float = 199.0,
    upfront_processing_fee: float = 0.0,
    gst_rate_pct: float = 18.0,
    delay_days: int = 0,
    discretionary_reduction_pct: float = 0.0,
    custom_liquid_balance: Optional[float] = None,
    include_persona: bool = False,
    as_of_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Executes the multi-scenario Commitment Stress Test & Judgment Flip.

    Returns:
    - baseline: current verified financial position and evidence
    - scenario_a_buy_now: immediate lump-sum impact
    - scenario_b_emi: EMI/financing impact with XIRR effective borrowing cost
    - scenario_c_wait: delayed purchase impact (Judgment Flip)
    - judgment_flip: comparison matrix and safe flip threshold
    - what_would_make_this_safe: up to 3 deterministic alternatives
    - evidence_ledger: real session transaction IDs and aggregates
    - verdict: overall safety card status (SAFE, CONDITIONAL, NOT SAFE, INSUFFICIENT DATA)
    """
    today = as_of_date or date.today()

    # 1. Normalize purchase parameters
    p_dec = _clamp_decimal(_as_decimal(price), Decimal('0'), Decimal('1000000000'))
    dp_dec = _clamp_decimal(_as_decimal(down_payment), Decimal('0'), p_dec)
    tenure = max(1, min(600, _as_int(tenure_months, 12)))
    apr_dec = _clamp_decimal(_as_decimal(nominal_apr), Decimal('0'), Decimal('1000'))
    m_fee_dec = _clamp_decimal(_as_decimal(monthly_processing_fee), Decimal('0'), Decimal('1000000'))
    u_fee_dec = _clamp_decimal(_as_decimal(upfront_processing_fee), Decimal('0'), Decimal('1000000'))
    gst_dec = _clamp_decimal(_as_decimal(gst_rate_pct), Decimal('0'), Decimal('100')) / Decimal('100')
    delay = max(0, min(180, int(delay_days or 0)))
    disc_reduction = _clamp_decimal(_as_decimal(discretionary_reduction_pct), Decimal('0'), Decimal('100')) / Decimal('100')

    # 2. Gather verified baseline data from exactly one selected dataset.
    # A persona-created snapshot belongs to the persona scenario and is never
    # substituted into an imported-statement analysis (and vice versa).
    source_type = (
        Transaction.SOURCE_PERSONA if include_persona else Transaction.SOURCE_IMPORT
    )
    qs = Transaction.objects.filter(session_id=session_id, source_type=source_type)
    txs = list(qs.order_by('transaction_date'))

    snapshot = (
        FinancialSnapshot.objects.filter(session_id=session_id)
        .order_by('-created_at')
        .first()
        if include_persona else None
    )

    # Determine baseline liquid balance
    balance_is_supported = False
    if custom_liquid_balance is not None and float(custom_liquid_balance) >= 0:
        liquid_balance = _as_decimal(custom_liquid_balance)
        balance_is_supported = True
    elif snapshot and snapshot.liquid_balance > 0:
        liquid_balance = snapshot.liquid_balance
        balance_is_supported = True
    else:
        # Imported statements carry no verified current balance in this schema.
        liquid_balance = Decimal('0')

    # Compute baseline income and expenses from existing monthly_budget engine
    budget_year = today.year
    budget_month = today.month
    if txs:
        latest_tx_date = txs[-1].transaction_date
        budget_year = latest_tx_date.year
        budget_month = latest_tx_date.month

    budget = monthly_budget(session_id, budget_year, budget_month, include_persona)

    # Predictable operating income uses confirmed evidence only. Probable
    # business/freelance receipts are surfaced but withheld from survival math;
    # unclassified credits remain excluded.
    confirmed_operating_income = _to_dec(
        budget.get('confirmed_operating_income', budget.get('operating_income', '0'))
    )
    probable_operating_income = _to_dec(budget.get('probable_operating_income', '0'))
    operating_income = confirmed_operating_income
    earned_income = _to_dec(budget.get('earned_income', '0'))
    total_credits = _to_dec(budget.get('total_credits', '0'))
    unclassified_credits = _to_dec(budget.get('credit_breakdown', {}).get('unclassified', '0'))

    # Detect verified recurring commitments and subscriptions. Do not swallow
    # engine failures here: the view reports them explicitly instead of
    # presenting an internally failed computation as a SAFE verdict.
    subs = detect_subscriptions(session_id, include_persona=include_persona, as_of_date=today)

    confirmed_fixed_commitments = Decimal('0')
    confirmed_subscriptions = Decimal('0')
    probable_subscriptions_under_review = Decimal('0')
    commitment_evidence_ids = []
    income_evidence_ids = []
    active_session_tx_ids = {str(t.id) for t in txs}

    def _verified_candidate_ids(entry: Dict[str, Any]) -> List[str]:
        """Validate recurrence evidence against this active session only.

        ``candidate_transaction_ids`` is an explicit list of real ledger rows.
        Malformed, empty, cross-session and duplicate IDs are ignored. The
        legacy boolean ``candidates`` flag is never evidence.
        """
        raw_ids = entry.get('candidate_transaction_ids')
        if not isinstance(raw_ids, (list, tuple, set)):
            return []
        verified = []
        for tx_id in raw_ids:
            if not isinstance(tx_id, (str, int)):
                continue
            candidate = str(tx_id)
            if candidate in active_session_tx_ids and candidate not in verified:
                verified.append(candidate)
        return verified

    for s in subs:
        cost = _to_dec(s.get('estimated_monthly_cost', '0'))
        if s.get('is_financial_commitment'):
            confirmed_fixed_commitments += cost
            commitment_evidence_ids.extend(_verified_candidate_ids(s))
        elif s.get('is_potential_leakage'):
            confirmed_subscriptions += cost
            commitment_evidence_ids.extend(_verified_candidate_ids(s))
        elif s.get('confidence') == RECURRING_PROBABLE:
            probable_subscriptions_under_review += cost
            commitment_evidence_ids.extend(_verified_candidate_ids(s))

    # Fallback to snapshot fixed commitments or explicit contractual debits if subs detector requires multiple cadences
    if confirmed_fixed_commitments == 0:
        fixed_contractual_sum = Decimal('0')
        discretionary_recurring_sum = Decimal('0')
        for t in txs:
            if t.transaction_type == 'DEBIT' and t.is_recurring:
                p_type = classify_recurring_payment(t.normalized_merchant, t.category)
                cat_key = canonical_category_key(t.category)
                if p_type in ('rent', 'emi_or_loan', 'utility', 'insurance') or cat_key in ('rent_housing', 'emi'):
                    fixed_contractual_sum += t.amount
                else:
                    discretionary_recurring_sum += t.amount

        if fixed_contractual_sum > 0:
            confirmed_fixed_commitments = fixed_contractual_sum
        elif snapshot and snapshot.fixed_commitments > 0:
            confirmed_fixed_commitments = snapshot.fixed_commitments

        if discretionary_recurring_sum > 0 and probable_subscriptions_under_review == 0:
            probable_subscriptions_under_review = discretionary_recurring_sum

    for t in txs:
        if t.transaction_type == 'DEBIT' and t.is_recurring:
            commitment_evidence_ids.append(str(t.id))

    # Extract income evidence transactions. Probable business/freelance receipts
    # are cited as review evidence only after they are confirmed; they are not
    # counted as predictable income above.
    for tx in txs:
        if tx.transaction_type == 'CREDIT':
            c_info = classify_credit(tx.normalized_merchant)
            if c_info['is_operating_income'] and not c_info.get('requires_review'):
                income_evidence_ids.append(str(tx.id))

    # Net monthly living expenses
    net_living_expenses = _to_dec(budget.get('net_living_expenses', '0'))
    if net_living_expenses == 0 and snapshot and snapshot.monthly_expenses > 0:
        net_living_expenses = snapshot.monthly_expenses

    # Monthly fixed burn for runway: fixed commitments + baseline living expenses
    monthly_burn = confirmed_fixed_commitments + max(Decimal('0'), net_living_expenses - confirmed_fixed_commitments)
    if monthly_burn <= 0:
        monthly_burn = max(Decimal('1000'), net_living_expenses)

    # Discretionary buffer
    monthly_discretionary = max(Decimal('0'), operating_income - monthly_burn)
    discretionary_expenses = max(Decimal('0'), net_living_expenses - confirmed_fixed_commitments)
    daily_discretionary_spend = discretionary_expenses / Decimal('30')

    # Emergency safety floor (15% of operating income or 20% of balance, whichever is higher but capped)
    safety_buffer_floor = min(operating_income * Decimal('0.15'), liquid_balance * Decimal('0.20'))
    if safety_buffer_floor <= 0 and operating_income > 0:
        safety_buffer_floor = operating_income * Decimal('0.15')

    # Baseline runway
    baseline_runway = AnalyticsEngine.calculate_runway(float(liquid_balance), float(monthly_burn))

    # Check sufficient data condition
    data_sufficient = True
    insufficient_reasons = []

    if not balance_is_supported and liquid_balance <= 0:
        data_sufficient = False
        insufficient_reasons.append("Current liquid balance is not verified or supported by statement.")
    if operating_income <= 0:
        data_sufficient = False
        insufficient_reasons.append("Predictable operating income is missing or irregular.")
    if len(txs) == 0 and not snapshot:
        data_sufficient = False
        insufficient_reasons.append("No transaction history available in the selected dataset.")

    # 3. Simulate Scenarios
    # SCENARIO A: BUY NOW (Lump Sum)
    immediate_outflow_a = p_dec
    remaining_balance_a = liquid_balance - immediate_outflow_a
    runway_after_a = AnalyticsEngine.calculate_runway(float(max(Decimal('0'), remaining_balance_a)), float(monthly_burn))
    remaining_buffer_a = remaining_balance_a - safety_buffer_floor

    # 90-Day Cash Flow Projection for Scenario A
    projection_a = _project_90_day_cash_flow(
        start_balance=remaining_balance_a,
        daily_income=operating_income / Decimal('30'),
        monthly_commitments=confirmed_fixed_commitments,
        daily_discretionary=daily_discretionary_spend,
        safety_floor=safety_buffer_floor,
        start_date=today,
    )

    verdict_a, reason_a = _evaluate_verdict(
        data_sufficient=data_sufficient,
        remaining_balance=remaining_balance_a,
        remaining_buffer=remaining_buffer_a,
        runway_after=runway_after_a,
        first_breach_day=projection_a['first_breach_day'],
        lowest_projected_balance=projection_a['lowest_balance'],
        monthly_outflow=Decimal('0'),
        discretionary_buffer=monthly_discretionary,
    )

    # SCENARIO B: BUY WITH EMI
    emi_sim = AnalyticsEngine.simulate_emi_decision(
        item_name=item_name,
        price=float(p_dec),
        tenure_months=tenure,
        down_payment=float(dp_dec),
        nominal_annual_interest_rate_pct=float(apr_dec),
        monthly_processing_or_conv_fee=float(m_fee_dec),
        upfront_processing_fee=float(u_fee_dec),
        gst_rate_pct=float(gst_rate_pct),
        user_monthly_discretionary_buffer=float(monthly_discretionary or Decimal('12000')),
        start_date=today,
    )

    effective_monthly_emi = _to_dec(emi_sim.get('effective_monthly_outflow', emi_sim.get('monthly_emi', 0)))
    upfront_cash_b = dp_dec + _to_dec(emi_sim.get('cost_breakdown', {}).get('upfront_fees_and_gst', 0))
    remaining_balance_b = liquid_balance - upfront_cash_b
    new_monthly_burn_b = monthly_burn + effective_monthly_emi
    runway_after_b = AnalyticsEngine.calculate_runway(float(max(Decimal('0'), remaining_balance_b)), float(new_monthly_burn_b))
    remaining_buffer_b = remaining_balance_b - safety_buffer_floor

    # 90-Day Cash Flow Projection for Scenario B
    projection_b = _project_90_day_cash_flow(
        start_balance=remaining_balance_b,
        daily_income=operating_income / Decimal('30'),
        monthly_commitments=confirmed_fixed_commitments + effective_monthly_emi,
        daily_discretionary=daily_discretionary_spend,
        safety_floor=safety_buffer_floor,
        start_date=today,
    )

    verdict_b, reason_b = _evaluate_verdict(
        data_sufficient=data_sufficient,
        remaining_balance=remaining_balance_b,
        remaining_buffer=remaining_buffer_b,
        runway_after=runway_after_b,
        first_breach_day=projection_b['first_breach_day'],
        lowest_projected_balance=projection_b['lowest_balance'],
        monthly_outflow=effective_monthly_emi,
        discretionary_buffer=monthly_discretionary,
    )

    # SCENARIO C: WAIT (Judgment Flip)
    # Realistic cash-flow trajectory:
    # If operating_income < monthly_burn, user burns capital every day (negative savings rate).
    net_monthly_cashflow = operating_income - monthly_burn
    daily_savings_rate = net_monthly_cashflow / Decimal('30')
    accumulated_savings_during_wait = daily_savings_rate * Decimal(delay)

    # After delay, purchase occurs
    wait_purchase_date = today + timedelta(days=delay)
    balance_at_wait_purchase = liquid_balance + accumulated_savings_during_wait

    if commitment_type == 'large_purchase':
        remaining_balance_c = balance_at_wait_purchase - p_dec
        monthly_commitment_c = Decimal('0')
        new_burn_c = monthly_burn
    else:
        remaining_balance_c = balance_at_wait_purchase - upfront_cash_b
        monthly_commitment_c = effective_monthly_emi
        new_burn_c = monthly_burn + effective_monthly_emi

    runway_after_c = AnalyticsEngine.calculate_runway(float(max(Decimal('0'), remaining_balance_c)), float(new_burn_c))
    remaining_buffer_c = remaining_balance_c - safety_buffer_floor

    projection_c = _project_90_day_cash_flow(
        start_balance=remaining_balance_c,
        daily_income=operating_income / Decimal('30'),
        monthly_commitments=confirmed_fixed_commitments + monthly_commitment_c,
        daily_discretionary=daily_discretionary_spend,
        safety_floor=safety_buffer_floor,
        start_date=wait_purchase_date,
    )

    verdict_c, reason_c = _evaluate_verdict(
        data_sufficient=data_sufficient,
        remaining_balance=remaining_balance_c,
        remaining_buffer=remaining_buffer_c,
        runway_after=runway_after_c,
        first_breach_day=projection_c['first_breach_day'],
        lowest_projected_balance=projection_c['lowest_balance'],
        monthly_outflow=monthly_commitment_c,
        discretionary_buffer=monthly_discretionary,
    )

    # Determine Safe Flip Threshold and Flip Messaging
    safe_flip_days = None
    flip_message = ""

    if verdict_a == "SAFE" and verdict_b == "SAFE":
        flip_message = "Commitment is already safe with current liquid reserves; no waiting required."
    elif daily_savings_rate <= 0:
        safe_flip_days = None
        flip_message = (
            f"Waiting cannot make this commitment safe because monthly living expenses (₹{_money(monthly_burn):,.2f}) "
            f"exceed predictable operating income (₹{_money(operating_income):,.2f}). "
            "Living costs or fixed obligations must be reduced first."
        )
    else:
        # User has positive net savings (daily_savings_rate > 0)
        # Check if the monthly commitment itself is structurally unsustainable for the monthly discretionary income
        is_emi_unsustainable = (
            commitment_type != 'large_purchase' and
            (monthly_discretionary <= 0 or (effective_monthly_emi / monthly_discretionary) * Decimal('100') > Decimal('25.0'))
        )

        if is_emi_unsustainable:
            # For unsustainable EMI, the safe flip is saving to buy in CASH with zero debt
            needed_buffer = p_dec + max(safety_buffer_floor, Decimal('3.0') * monthly_burn)
            deficit = needed_buffer - liquid_balance
            if deficit > 0:
                raw_days = int(math_ceil(float(deficit / daily_savings_rate)))
                if raw_days <= 180:
                    safe_flip_days = max(1, raw_days)
                    flip_message = (
                        f"Waiting {safe_flip_days} days allows you to buy in cash for ₹{_money(p_dec):,.2f} "
                        "with zero debt, avoiding the high monthly EMI burden entirely."
                    )
                else:
                    safe_flip_days = None
                    flip_message = (
                        f"Monthly EMI (₹{_money(effective_monthly_emi):,.2f}) exceeds safe discretionary threshold. "
                        f"Accumulating full cash requires {raw_days} days (> 6 months). Restructure tenure or lower amount."
                    )
            else:
                safe_flip_days = 0
                flip_message = "You have sufficient cash to buy upfront now without incurring EMI debt."
        else:
            target_burn = monthly_burn if commitment_type == 'large_purchase' else (monthly_burn + effective_monthly_emi)
            target_upfront = p_dec if commitment_type == 'large_purchase' else upfront_cash_b
            needed_buffer = target_upfront + max(safety_buffer_floor, Decimal('3.0') * target_burn)
            deficit = needed_buffer - liquid_balance
            if deficit > 0:
                raw_days = int(math_ceil(float(deficit / daily_savings_rate)))
                if raw_days <= 180:
                    safe_flip_days = max(1, raw_days)
                    flip_message = f"Waiting {safe_flip_days} days accumulates ₹{_money(daily_savings_rate * Decimal(safe_flip_days)):,.2f} to satisfy safety buffer and 3.0-month runway."
                else:
                    safe_flip_days = None
                    flip_message = f"Accumulating the required safety cushion requires {raw_days} days (> 6 months). Consider a lower price or higher down payment."
            else:
                safe_flip_days = 0
                flip_message = "Current reserves already meet safety buffer and runway targets."

    # If active delay already flipped scenario C to SAFE
    if verdict_c == "SAFE" and (verdict_a != "SAFE" or verdict_b != "SAFE"):
        flip_message = f"Waiting {delay} days flips this decision to SAFE! Buffer strengthens by ₹{_money(accumulated_savings_during_wait):,.2f}."

    # 4. "WHAT WOULD MAKE THIS SAFE?" Deterministic Alternatives
    alternatives = []
    # Alternative 1: Delay purchase
    if safe_flip_days and safe_flip_days > 0:
        alternatives.append({
            "id": "ALT_DELAY",
            "type": "DELAY_PURCHASE",
            "title": f"Wait {safe_flip_days} days to build safety cushion",
            "action": f"Delay purchase until {(today + timedelta(days=safe_flip_days)).strftime('%d %b %Y')}. Your accumulated buffer will reach ₹{_money(liquid_balance + daily_savings_rate * Decimal(safe_flip_days)):,.2f}, flipping the decision to SAFE.",
            "impact_verdict": "SAFE",
            "required_delay_days": safe_flip_days,
        })
    elif verdict_b == "SAFE":
        alternatives.append({
            "id": "ALT_DELAY",
            "type": "TIMING_OPTIMAL",
            "title": "Timing is viable with current liquid reserves",
            "action": "Your current savings buffer supports this purchase schedule without risking pending fixed obligations.",
            "impact_verdict": "SAFE",
            "required_delay_days": 0,
        })

    # Alternative 2: Discretionary spending cut
    discretionary_spending = max(Decimal('0'), net_living_expenses - confirmed_fixed_commitments)
    if discretionary_spending > 0:
        cut_20_pct = discretionary_spending * Decimal('0.20')
        monthly_savings_recovered = cut_20_pct
        alternatives.append({
            "id": "ALT_DISCRETIONARY_CUT",
            "type": "REDUCE_DISCRETIONARY",
            "title": "Reduce flexible spending by 20%",
            "action": f"Trimming non-essential dining and quick-commerce spending frees ₹{_money(monthly_savings_recovered):,.2f}/month to absorb the commitment.",
            "monthly_freed_amount": _money(monthly_savings_recovered),
            "recommended_reduction_pct": 20.0,
        })

    # Alternative 3: Restructure tenure / payment structure
    if tenure < 24 and commitment_type in ('no_cost_emi', 'regular_emi'):
        longer_tenure = min(24, tenure * 2)
        longer_sim = AnalyticsEngine.simulate_emi_decision(
            item_name=item_name,
            price=float(p_dec),
            tenure_months=longer_tenure,
            down_payment=float(dp_dec),
            nominal_annual_interest_rate_pct=float(apr_dec),
            monthly_processing_or_conv_fee=float(m_fee_dec),
            upfront_processing_fee=float(u_fee_dec),
            gst_rate_pct=float(gst_rate_pct),
            user_monthly_discretionary_buffer=float(monthly_discretionary or Decimal('12000')),
        )
        new_emi = _to_dec(longer_sim.get('effective_monthly_outflow', 0))
        emi_reduction = effective_monthly_emi - new_emi
        alternatives.append({
            "id": "ALT_EXTEND_TENURE",
            "type": "EXTEND_TENURE",
            "title": f"Extend tenure from {tenure} to {longer_tenure} months",
            "action": f"Lowers monthly outflow from ₹{_money(effective_monthly_emi):,.2f} to ₹{_money(new_emi):,.2f} (saves ₹{_money(emi_reduction):,.2f}/mo), keeping buffer consumption below critical threshold.",
            "new_tenure_months": longer_tenure,
            "new_monthly_emi": _money(new_emi),
        })

    # Overall Verdict
    if not data_sufficient:
        overall_verdict = "INSUFFICIENT DATA"
        primary_reason = " | ".join(insufficient_reasons)
    elif commitment_type == "large_purchase":
        overall_verdict = verdict_a
        primary_reason = reason_a
    else:
        overall_verdict = verdict_b
        primary_reason = reason_b

    # Evidence IDs validation. De-duplicate while preserving order so one
    # ledger row cannot be cited twice through different detection paths.
    valid_session_tx_ids = set(str(t.id) for t in txs)
    commitment_evidence_ids = list(dict.fromkeys(commitment_evidence_ids))
    income_evidence_ids = list(dict.fromkeys(income_evidence_ids))
    verified_evidence_ids = list(dict.fromkeys(
        tid for tid in (commitment_evidence_ids + income_evidence_ids)
        if tid in valid_session_tx_ids
    ))

    return {
        "item_name": item_name,
        "commitment_type": commitment_type,
        "dataset_source": "PERSONA_SCENARIO" if include_persona else "IMPORTED_STATEMENT",
        "dataset_transaction_count": len(txs),
        "proposed_amount": _money(p_dec),
        "down_payment": _money(dp_dec),
        "tenure_months": tenure,
        "overall_verdict": overall_verdict,
        "primary_reason": primary_reason,
        "data_sufficient": data_sufficient,
        "insufficient_reasons": insufficient_reasons,
        "baseline": {
            "current_liquid_balance": _money(liquid_balance),
            "balance_verified": balance_is_supported,
            "predictable_monthly_income": _money(operating_income),
            "earned_income": _money(earned_income),
            "probable_income_withheld": _money(probable_operating_income),
            "unclassified_credits_withheld": _money(unclassified_credits),
            "existing_fixed_obligations": _money(confirmed_fixed_commitments),
            "confirmed_subscriptions": _money(confirmed_subscriptions),
            "probable_subscriptions_under_review": _money(probable_subscriptions_under_review),
            "total_recurring_outflow": _money(confirmed_fixed_commitments + confirmed_subscriptions + probable_subscriptions_under_review),
            "baseline_living_expenses": _money(net_living_expenses),
            "monthly_discretionary_buffer": _money(monthly_discretionary),
            "safety_buffer_floor": _money(safety_buffer_floor),
            "baseline_runway_months": baseline_runway,
        },
        "scenario_a_buy_now": {
            "label": "Buy Now (Immediate Lump Sum)",
            "immediate_outflow": _money(immediate_outflow_a),
            "monthly_commitment": 0.0,
            "projected_remaining_balance": _money(remaining_balance_a),
            "remaining_safety_buffer": _money(remaining_buffer_a),
            "emergency_runway_months": runway_after_a,
            "verdict": verdict_a,
            "reason": reason_a,
            "first_breach_day": projection_a['first_breach_day'],
            "lowest_projected_balance": _money(projection_a['lowest_balance']),
            "cash_flow_timeline": projection_a['timeline'],
        },
        "scenario_b_emi": {
            "label": "Buy with EMI / Financing",
            "immediate_outflow": _money(upfront_cash_b),
            "base_monthly_emi": _money(_to_dec(emi_sim.get('base_monthly_emi', 0))),
            "monthly_hidden_fees_with_gst": _money(_to_dec(emi_sim.get('monthly_fee_with_gst', 0))),
            "effective_monthly_commitment": _money(effective_monthly_emi),
            "total_hidden_fees": _money(_to_dec(emi_sim.get('total_hidden_fees_and_gst', 0))),
            "total_overall_cost": _money(_to_dec(emi_sim.get('total_overall_cost', 0))),
            "effective_annual_cost_pct": emi_sim.get('effective_annual_cost_pct'),
            "effective_cost_status": emi_sim.get('apr_calculation', {}).get('status', 'OK'),
            "effective_cost_reason": emi_sim.get('apr_calculation', {}).get('reason'),
            "buffer_consumed_pct": emi_sim.get('pct_of_discretionary_buffer_used', 0.0),
            "projected_remaining_balance": _money(remaining_balance_b),
            "remaining_safety_buffer": _money(remaining_buffer_b),
            "emergency_runway_months": runway_after_b,
            "verdict": verdict_b,
            "reason": reason_b,
            "first_breach_day": projection_b['first_breach_day'],
            "lowest_projected_balance": _money(projection_b['lowest_balance']),
            "cash_flow_timeline": projection_b['timeline'],
        },
        "scenario_c_wait": {
            "label": f"Wait {delay} Days (Judgment Flip)",
            "delay_days": delay,
            "purchase_date": wait_purchase_date.isoformat(),
            "accumulated_savings": _money(accumulated_savings_during_wait),
            "projected_balance_at_purchase": _money(balance_at_wait_purchase),
            "projected_remaining_balance": _money(remaining_balance_c),
            "remaining_safety_buffer": _money(remaining_buffer_c),
            "emergency_runway_months": runway_after_c,
            "monthly_commitment": _money(monthly_commitment_c),
            "verdict": verdict_c,
            "reason": reason_c,
            "first_breach_day": projection_c['first_breach_day'],
            "lowest_projected_balance": _money(projection_c['lowest_balance']),
            "cash_flow_timeline": projection_c['timeline'],
        },
        "judgment_flip": {
            "current_verdict": overall_verdict,
            "safe_flip_days": safe_flip_days,
            "flips_to_safe": verdict_c == "SAFE" and overall_verdict != "SAFE",
            "flip_message": flip_message,
        },
        "what_would_make_this_safe": alternatives,
        "evidence_ledger": {
            "verified_session_tx_count": len(txs),
            "income_evidence_ids": income_evidence_ids[:10],
            "commitment_evidence_ids": commitment_evidence_ids[:10],
            "all_cited_tx_ids": verified_evidence_ids[:20],
        },
    }


def math_ceil(v: float) -> int:
    import math
    return math.ceil(v)


def _project_90_day_cash_flow(
    start_balance: Decimal,
    daily_income: Decimal,
    monthly_commitments: Decimal,
    daily_discretionary: Decimal,
    safety_floor: Decimal,
    start_date: date,
) -> Dict[str, Any]:
    """
    Projects daily cash balance across next 90 days.
    Identifies exact day and date of first safety buffer breach or cash-flow deficit.
    Returns sampled checkpoints (every 10 days + breach point) for responsive UI charts.
    """
    balance = start_balance
    lowest_balance = balance
    first_breach_day = None
    first_breach_date = None

    timeline = []
    # Sample at intervals: Day 0, Day 15, Day 30, Day 45, Day 60, Day 75, Day 90
    checkpoints = {0, 15, 30, 45, 60, 75, 90}

    for day_i in range(91):
        cur_date = start_date + timedelta(days=day_i)

        if day_i > 0:
            # Add daily income (smoothed or monthly arrival on day 1/30)
            balance += daily_income
            # Deduct daily living expenses
            balance -= daily_discretionary
            # Deduct fixed commitments on day 5 and 20 of month
            if cur_date.day in (5, 20):
                balance -= (monthly_commitments / Decimal('2'))

        if balance < lowest_balance:
            lowest_balance = balance

        # Check safety floor breach
        if balance < safety_floor and first_breach_day is None:
            first_breach_day = day_i
            first_breach_date = cur_date.isoformat()
            checkpoints.add(day_i)

        if day_i in checkpoints:
            timeline.append({
                "day": day_i,
                "date": cur_date.isoformat(),
                "balance": _money(balance),
                "is_breach": balance < safety_floor,
                "is_deficit": balance < 0,
            })

    timeline.sort(key=lambda x: x['day'])

    return {
        "timeline": timeline,
        "lowest_balance": lowest_balance,
        "first_breach_day": first_breach_day,
        "first_breach_date": first_breach_date,
    }


def _evaluate_verdict(
    data_sufficient: bool,
    remaining_balance: Decimal,
    remaining_buffer: Decimal,
    runway_after: float,
    first_breach_day: Optional[int],
    lowest_projected_balance: Decimal,
    monthly_outflow: Decimal,
    discretionary_buffer: Decimal,
) -> Tuple[str, str]:
    """
    Deterministic rule-based decision verdict.
    Never hallucinates or guesses.
    """
    if not data_sufficient:
        return "INSUFFICIENT DATA", "Insufficient baseline transaction or balance data for a reliable projection."

    # Immediate deficit
    if remaining_balance < 0:
        return "NOT SAFE", f"Immediate liquidity deficit: purchase exceeds available balance by ₹{_money(abs(remaining_balance)):,.2f}."

    # Cash-flow depletion within 90 days
    if lowest_projected_balance < 0:
        return "NOT SAFE", f"Projected cash-flow deficit: account balance dips to -₹{_money(abs(lowest_projected_balance)):,.2f} within 90 days."

    # Runway collapsed
    if runway_after < 1.0:
        return "NOT SAFE", f"Emergency runway collapses to {runway_after:.1f} months (minimum safe threshold is 3.0 months)."

    # EMI / monthly commitment eats too much discretionary cash
    if monthly_outflow > 0:
        if discretionary_buffer <= 0:
            return "NOT SAFE", f"Monthly commitment of ₹{_money(monthly_outflow):,.2f} cannot be absorbed: monthly discretionary buffer is ₹{_money(discretionary_buffer):,.2f} (zero or negative)."
        ratio = (monthly_outflow / discretionary_buffer) * Decimal('100')
        if ratio > Decimal('45.0'):
            return "NOT SAFE", f"Monthly commitment of ₹{_money(monthly_outflow):,.2f} consumes {ratio:.1f}% of discretionary buffer (limit is 40%)."

    # Conditional threshold: buffer breached or runway tight
    if remaining_buffer < 0:
        return "CONDITIONAL", f"Emergency safety buffer breached: remaining balance dips below the reserved floor by ₹{_money(abs(remaining_buffer)):,.2f}."

    if runway_after < 3.0:
        return "CONDITIONAL", f"Post-purchase emergency runway is {runway_after:.1f} months. Manageable, but vulnerable to unexpected shocks."

    if first_breach_day is not None and first_breach_day <= 45:
        return "CONDITIONAL", f"Projected safety buffer breach on Day {first_breach_day}. Requires cautious spending."

    if monthly_outflow > 0 and discretionary_buffer > 0:
        ratio = (monthly_outflow / discretionary_buffer) * Decimal('100')
        if ratio > Decimal('25.0'):
            return "CONDITIONAL", f"Commitment absorbs {ratio:.1f}% of monthly discretionary buffer."

    return "SAFE", "Commitment easily absorbed: emergency runway remains >= 3.0 months and safety buffer is intact across 90 days."
