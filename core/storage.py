"""
Persistence Layer
Stores processed purchase requests to a local CSV file so the Dashboard /
History screen can show real, cumulative data across the session. This
acts as the transient application log referenced in the PRD (the system
does not claim to be a system-of-record for core financial data).
"""

import os
import pandas as pd
from datetime import datetime
from filelock import FileLock

LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "purchase_requests_log.csv")
LOCK_PATH = LOG_PATH + ".lock"

COLUMNS = [
    "request_id", "timestamp", "employee_name", "department", "item_raw",
    "item_matched", "sku", "quantity", "estimated_price", "required_date",
    "request_value", "action", "estimated_savings", "notes",
]


def _ensure_log_exists():
    if not os.path.exists(LOG_PATH):
        pd.DataFrame(columns=COLUMNS).to_csv(LOG_PATH, index=False)


def append_request(record: dict):
    _ensure_log_exists()
    with FileLock(LOCK_PATH):
        df = pd.read_csv(LOG_PATH)
        next_id = f"PR-{len(df) + 1:04d}"
        record = {**record, "request_id": next_id, "timestamp": datetime.now().isoformat(timespec="seconds")}
        new_row = pd.DataFrame([record])
        if df.empty:
            df = new_row
        else:
            df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(LOG_PATH, index=False)
    return next_id


def load_history() -> pd.DataFrame:
    _ensure_log_exists()
    return pd.read_csv(LOG_PATH)


def dashboard_stats() -> dict:
    df = load_history()
    total = len(df)
    counts = df["action"].value_counts().to_dict() if total else {}
    return {
        "total_requests": total,
        "proceed": counts.get("PROCEED", 0),
        "hold": counts.get("HOLD", 0),
        "reduce": counts.get("REDUCE", 0),
        "investigate": counts.get("INVESTIGATE", 0),
        "expedite": counts.get("EXPEDITE", 0),
        "total_savings": round(df["estimated_savings"].fillna(0).sum(), 2) if total else 0.0,
    }
