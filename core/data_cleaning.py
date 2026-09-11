"""
Gate 1 - Data Cleaning & Standardization
Intercepts the raw purchase request text, strips noise, fixes obvious
typographical issues and produces a standardized description that can be
fed into the item-matching step.
"""

import re

# A small domain vocabulary used to nudge common typo corrections.
# In a production system this would be replaced by a spell-checker trained
# on the company's item taxonomy, but this keeps the demo fully offline.
_KNOWN_TOKENS = [
    "helmet", "protective", "industrial", "laptop", "charger", "chair",
    "ergonomic", "office", "printer", "toner", "cartridge", "glove",
    "cut-resistant", "safety", "vest", "visibility", "mouse", "wireless",
    "optical", "keyboard", "welding", "rod", "filter", "air", "bag",
    "desk", "standard", "business", "class",
]

_COMMON_TYPOS = {
    "saftey": "safety",
    "helms": "helmet",
    "helmit": "helmet",
    "chargr": "charger",
    "chargar": "charger",
    "lapto": "laptop",
    "labtop": "laptop",
    "ofice": "office",
    "cheir": "chair",
    "galoves": "gloves",
    "gloove": "glove",
    "printr": "printer",
    "tonar": "toner",
}


def _closest_known_token(word: str) -> str:
    """Return the closest known vocabulary token for a word, or the word
    unchanged if nothing is close enough."""
    import difflib

    lower = word.lower()
    if lower in _COMMON_TYPOS:
        return _COMMON_TYPOS[lower]
    matches = difflib.get_close_matches(lower, _KNOWN_TOKENS, n=1, cutoff=0.8)
    return matches[0] if matches else lower


def clean_description(raw_text: str) -> dict:
    """
    Clean and standardize a raw purchase-request item description.

    Returns a dict with:
        - original: the raw text as submitted
        - cleaned: the standardized description (Title Case)
        - corrections: list of (before, after) token corrections applied
        - special_chars_removed: bool
    """
    if raw_text is None:
        raw_text = ""

    original = raw_text.strip()

    # Strip special characters (keep letters, numbers, spaces, hyphens)
    stripped = re.sub(r"[^A-Za-z0-9\s\-]", " ", original)
    special_chars_removed = stripped != original

    stripped = re.sub(r"\s+", " ", stripped).strip()

    tokens = stripped.split(" ")
    corrections = []
    fixed_tokens = []
    for tok in tokens:
        if not tok:
            continue
        fixed = _closest_known_token(tok)
        if fixed.lower() != tok.lower():
            corrections.append((tok, fixed))
        fixed_tokens.append(fixed)

    cleaned = " ".join(fixed_tokens).strip()
    cleaned = cleaned.title() if cleaned else "Unclassified Item"

    return {
        "original": original,
        "cleaned": cleaned,
        "corrections": corrections,
        "special_chars_removed": special_chars_removed,
    }
