"""
AI Procurement Decision Engine
Aggregates the outputs of Gates 1-4 into a single recommended action:
PROCEED, HOLD, REDUCE, INVESTIGATE, or EXPEDITE.

Key behavior (mirrors the PRD case study): a budget flag on the ORIGINAL
requested quantity is not automatically final. If Gate 3 finds transferable
stock and/or Gate 4 finds the request is oversized relative to real usage,
the system recalculates the true external purchase need first — the
budget is re-checked against that adjusted, right-sized order. Only if the
adjusted order still exceeds budget does the request go on HOLD.
"""

from . import budget_check

# When usage indicates overstock, trim the external order down to roughly
# one month of typical consumption as a working buffer.
OVERSTOCK_BUFFER_MONTHS = 1.0


def decide(match_result: dict, department: str, requested_qty: float, unit_price: float,
           budgets_df, stock_result: dict, usage_result: dict):
    reasons = []
    action = "PROCEED"

    # --- Gate: item match ---
    if match_result["status"] == "unmatched":
        return {
            "action": "INVESTIGATE",
            "reasons": [
                f"Item description could not be confidently matched to the company item "
                f"master (confidence {match_result['confidence']}%). Routed to human review "
                "before any budget, stock, or usage checks can run."
            ],
            "adjusted_qty": requested_qty,
            "final_order_value": None,
            "estimated_savings": 0.0,
            "initial_budget_result": None,
            "final_budget_result": None,
        }

    confidence_note = (
        f"Item matched with high confidence ({match_result['confidence']}%) to "
        f"'{match_result['description']}' (SKU {match_result['sku']})."
        if match_result["status"] == "matched" else
        f"Item matched with moderate confidence ({match_result['confidence']}%) to "
        f"'{match_result['description']}' (SKU {match_result['sku']}) — recommend a quick human glance."
    )
    reasons.append(confidence_note)

    # --- Gate 2 (initial, informational): budget check on the raw request ---
    initial_value = round(requested_qty * unit_price, 2)
    initial_budget = budget_check.check_budget(department, initial_value, budgets_df)
    if initial_budget["exceeds_budget"]:
        reasons.append(
            f"Initial requested value ${initial_value:,.2f} exceeds the remaining "
            f"{department} budget of ${initial_budget['remaining_budget']:,.2f} — flagged for review."
        )
    else:
        reasons.append(
            f"Initial requested value ${initial_value:,.2f} is within the remaining "
            f"{department} budget of ${initial_budget['remaining_budget']:,.2f}."
        )

    # --- Gate 3: transfer from other sites reduces the external need ---
    qty_after_transfer = stock_result["remaining_after_transfer"]
    if stock_result["status"] == "transfer_available":
        sites = ", ".join(s["warehouse"] for s in stock_result["other_sites"])
        reasons.append(
            f"Gate 3 found {stock_result['transferable_qty']} idle/excess unit(s) available "
            f"for internal transfer from: {sites}. External need reduced to "
            f"{qty_after_transfer} unit(s)."
        )

    # --- Gate 4: usage-based right-sizing of what's left ---
    adjusted_qty = qty_after_transfer
    if usage_result["status"] == "overstock_flag" and usage_result.get("avg_monthly_usage"):
        buffer_qty = max(1, round(usage_result["avg_monthly_usage"] * OVERSTOCK_BUFFER_MONTHS))
        if buffer_qty < qty_after_transfer:
            adjusted_qty = buffer_qty
            reasons.append(
                f"Gate 4 usage check: remaining {qty_after_transfer} unit(s) represented "
                f"~{usage_result['months_of_supply']} months of supply at an average usage of "
                f"{usage_result['avg_monthly_usage']} units/month. External order right-sized "
                f"down to a {buffer_qty}-unit working buffer (~{OVERSTOCK_BUFFER_MONTHS:.0f} month)."
            )
    elif usage_result["status"] == "understock_flag":
        reasons.append(
            "Gate 4 usage check: remaining quantity is below typical short-term consumption — "
            "flagged as an urgent understock risk."
        )
    elif usage_result["status"] == "normal_range":
        reasons.append("Gate 4 usage check: remaining quantity is within normal historical usage range.")

    # --- Recalculate the real budget need after transfer + right-sizing ---
    final_order_value = round(adjusted_qty * unit_price, 2)
    final_budget = budget_check.check_budget(department, final_order_value, budgets_df)

    total_saved_units = requested_qty - adjusted_qty
    estimated_savings = round(max(total_saved_units, 0) * unit_price, 2)
    if estimated_savings > 0:
        reasons.append(
            f"Combined effect of the internal transfer and right-sizing: the external "
            f"purchase drops from {int(requested_qty)} to {int(adjusted_qty)} unit(s), an "
            f"estimated avoided spend of ${estimated_savings:,.2f}."
        )

    # --- Final action decision ---
    if usage_result["status"] == "understock_flag":
        action = "EXPEDITE"
    elif final_budget["exceeds_budget"]:
        action = "HOLD"
        reasons.append(
            f"Even after adjustment, the recalculated order value ${final_order_value:,.2f} "
            f"still exceeds the remaining {department} budget of "
            f"${final_budget['remaining_budget']:,.2f}. Held for manager override."
        )
    elif adjusted_qty < requested_qty:
        action = "REDUCE"
    else:
        action = "PROCEED"
        reasons.append("All gates cleared — no adjustment needed, request can proceed as submitted.")

    return {
        "action": action,
        "reasons": reasons,
        "adjusted_qty": adjusted_qty,
        "final_order_value": final_order_value,
        "estimated_savings": estimated_savings,
        "initial_budget_result": initial_budget,
        "final_budget_result": final_budget,
    }
