"""
Vector Item-Code Mapping
Matches the cleaned free-text description against the company item master
and injects the official SKU + GL code. Uses fuzzy token matching as a
lightweight stand-in for a production embedding/vector-search index.
"""

from rapidfuzz import fuzz

HIGH_CONFIDENCE_THRESHOLD = 78
LOW_CONFIDENCE_THRESHOLD = 55


def _candidate_strings(row):
    """All text variants (canonical description + known aliases) that a
    row can be matched against — a lightweight stand-in for a semantic
    vector index over the item taxonomy."""
    candidates = [row["description"]]
    aliases = row.get("aliases", "")
    if isinstance(aliases, str) and aliases.strip():
        candidates.extend(a.strip() for a in aliases.split(";") if a.strip())
    return candidates


def match_item(cleaned_description: str, item_master_df):
    """
    Find the best matching catalog item for a cleaned description.

    Returns a dict:
        - sku, description, category, unit_price, gl_code (of best match, or None)
        - confidence: 0-100 fuzzy score
        - status: "matched" | "low_confidence" | "unmatched"
    """
    best_score = -1
    best_row = None

    for _, row in item_master_df.iterrows():
        row_best = max(
            fuzz.token_set_ratio(cleaned_description, cand)
            for cand in _candidate_strings(row)
        )
        if row_best > best_score:
            best_score = row_best
            best_row = row

    if best_row is None or best_score < LOW_CONFIDENCE_THRESHOLD:
        return {
            "sku": None,
            "description": None,
            "category": None,
            "unit_price": None,
            "gl_code": None,
            "confidence": max(best_score, 0),
            "status": "unmatched",
        }

    status = "matched" if best_score >= HIGH_CONFIDENCE_THRESHOLD else "low_confidence"

    return {
        "sku": best_row["sku"],
        "description": best_row["description"],
        "category": best_row["category"],
        "unit_price": float(best_row["unit_price"]),
        "gl_code": str(best_row["gl_code"]),
        "confidence": round(best_score, 1),
        "status": status,
    }
