"""
Gate 2 - Budget Check
Queries department budget records and flags requests that exceed the
remaining monthly allocation for the requesting department.
"""


def check_budget(department: str, request_value: float, budgets_df):
    row = budgets_df[budgets_df["department"] == department]

    if row.empty:
        return {
            "department": department,
            "monthly_budget": None,
            "spent_this_month": None,
            "remaining_budget": None,
            "request_value": round(request_value, 2),
            "exceeds_budget": None,
            "status": "unknown_department",
        }

    monthly_budget = float(row.iloc[0]["monthly_budget"])
    spent = float(row.iloc[0]["spent_this_month"])
    remaining = round(monthly_budget - spent, 2)
    exceeds = request_value > remaining

    return {
        "department": department,
        "monthly_budget": monthly_budget,
        "spent_this_month": spent,
        "remaining_budget": remaining,
        "request_value": round(request_value, 2),
        "exceeds_budget": exceeds,
        "status": "variance_flag" if exceeds else "within_budget",
    }
