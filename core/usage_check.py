"""
Gate 4 - Usage Check
Compares the requested volume (after any internal transfer) with the
preceding 90 days of consumption and prompts resizing when the requested
quantity is excessive or insufficient relative to typical usage.
"""

OVERSTOCK_MONTHS_THRESHOLD = 3.0
# Only flag as urgent understock when the remaining need represents a very
# thin buffer (roughly under a week) — small routine orders that simply
# happen to be less than a month's usage are normal, not urgent.
UNDERSTOCK_MONTHS_THRESHOLD = 0.2


def check_usage(sku: str, department: str, remaining_qty: int, usage_df):
    if sku is None or remaining_qty <= 0:
        return {
            "avg_monthly_usage": None,
            "months_of_supply": None,
            "status": "not_applicable" if sku is None else "fully_covered_by_transfer",
        }

    row = usage_df[(usage_df["sku"] == sku) & (usage_df["department"] == department)]

    if row.empty:
        return {
            "avg_monthly_usage": None,
            "months_of_supply": None,
            "status": "no_usage_history",
        }

    r = row.iloc[0]
    avg_usage = (float(r["month_1_usage"]) + float(r["month_2_usage"]) + float(r["month_3_usage"])) / 3.0

    if avg_usage <= 0:
        months_of_supply = float("inf")
    else:
        months_of_supply = remaining_qty / avg_usage

    if months_of_supply == float("inf") or months_of_supply > OVERSTOCK_MONTHS_THRESHOLD:
        status = "overstock_flag"
    elif months_of_supply < UNDERSTOCK_MONTHS_THRESHOLD:
        status = "understock_flag"
    else:
        status = "normal_range"

    return {
        "avg_monthly_usage": round(avg_usage, 1),
        "months_of_supply": None if months_of_supply == float("inf") else round(months_of_supply, 1),
        "status": status,
    }
