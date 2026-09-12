"""
Persistence Layer
Stores processed purchase requests to a local CSV file so the Dashboard,
My Requests, and Analytics screens show real, cumulative data.

Two distinct fields matter here:
    - action:       the AI's recommendation (PROCEED/HOLD/REDUCE/INVESTIGATE/EXPEDITE)
    - final_status: what the purchasing manager actually decided to do about it
                     (defaults to "Pending Review" until they click one of the
                     Approve / Hold / Investigate / Expedite buttons)

This acts as the transient application log referenced in the PRD (the system
does not claim to be a system-of-record for core financial/ERP data).
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
    "request_value", "action", "estimated_savings", "notes", "final_status",
]

VALID_FINAL_STATUSES = ["Pending Review", "Approved", "On Hold", "Investigate", "Expedited", "Saved"]
DEFAULT_STATUS = "Pending Review"


def _ensure_log_exists():
    if not os.path.exists(LOG_PATH):
        pd.DataFrame(columns=COLUMNS).to_csv(LOG_PATH, index=False)


def _load_locked() -> pd.DataFrame:
    _ensure_log_exists()
    df = pd.read_csv(LOG_PATH)
    # Backfill final_status for any rows written before this column existed.
    if "final_status" not in df.columns:
        df["final_status"] = DEFAULT_STATUS
    df["final_status"] = df["final_status"].fillna(DEFAULT_STATUS)
    return df


def append_request(record: dict) -> str:
    """Persist a newly processed request. Returns its generated request_id."""
    with FileLock(LOCK_PATH):
        df = _load_locked()
        next_id = f"PR-{len(df) + 1:04d}"
        record = {
            **record,
            "request_id": next_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "final_status": record.get("final_status", DEFAULT_STATUS),
        }
        new_row = pd.DataFrame([record])
        df = new_row if df.empty else pd.concat([df, new_row], ignore_index=True)
        df.to_csv(LOG_PATH, index=False)
    return next_id


def update_status(request_id: str, new_status: str) -> bool:
    """Update the manager-facing disposition of an existing request.
    Returns True if the record was found and updated, False otherwise."""
    if new_status not in VALID_FINAL_STATUSES:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of {VALID_FINAL_STATUSES}.")

    with FileLock(LOCK_PATH):
        df = _load_locked()
        mask = df["request_id"] == request_id
        if not mask.any():
            return False
        df.loc[mask, "final_status"] = new_status
        df.to_csv(LOG_PATH, index=False)
    return True


def get_request(request_id: str):
    df = _load_locked()
    match = df[df["request_id"] == request_id]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def load_history() -> pd.DataFrame:
    return _load_locked()


def dashboard_stats() -> dict:
    df = load_history()
    total = len(df)
    status_counts = df["final_status"].value_counts().to_dict() if total else {}
    action_counts = df["action"].value_counts().to_dict() if total else {}
    return {
        "total_requests": total,
        "approved": status_counts.get("Approved", 0),
        "on_hold": status_counts.get("On Hold", 0),
        "investigate": status_counts.get("Investigate", 0),
        "expedited": status_counts.get("Expedited", 0),
        "pending_review": status_counts.get("Pending Review", 0) + status_counts.get("Saved", 0),
        "ai_proceed": action_counts.get("PROCEED", 0),
        "ai_reduce": action_counts.get("REDUCE", 0),
        "ai_hold": action_counts.get("HOLD", 0),
        "ai_investigate": action_counts.get("INVESTIGATE", 0),
        "ai_expedite": action_counts.get("EXPEDITE", 0),
        "total_savings": round(df["estimated_savings"].fillna(0).sum(), 2) if total else 0.0,
    }


def reset_demo_data():
    """Wipe the request log. Used by the Settings screen's real 'reset' action."""
    with FileLock(LOCK_PATH):
        pd.DataFrame(columns=COLUMNS).to_csv(LOG_PATH, index=False)
