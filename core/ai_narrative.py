"""
AI Narrative Layer
Turns the structured gate results + decision into the human-readable
reasoning shown on the "AI Procurement Decision" screen.

If a GROQ_API_KEY environment variable is set, this calls the real Groq
LLM API (llama-3.3-70b-versatile) to produce a polished narrative. If no
key is configured, it falls back to a deterministic template built from
the same structured facts, so the app is 100% functional either way.
"""

import os

GROQ_MODEL = "llama-3.3-70b-versatile"


def _fallback_narrative(action: str, reasons: list, estimated_savings: float) -> str:
    lines = [f"Recommended Action: {action}", ""]
    lines.append("Reasoning:")
    for r in reasons:
        lines.append(f"- {r}")
    if estimated_savings and estimated_savings > 0:
        lines.append("")
        lines.append(f"Estimated Savings: ${estimated_savings:,.2f}")
    return "\n".join(lines)


def generate_reasoning(action: str, reasons: list, estimated_savings: float, context: dict) -> str:
    """
    context: dict with keys like item, department, requested_qty, employee
    used to give the LLM enough color to write a natural summary.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()

    if not api_key:
        return _fallback_narrative(action, reasons, estimated_savings)

    try:
        from groq import Groq

        client = Groq(api_key=api_key)

        prompt = (
            "You are an AI procurement analyst. Given the structured facts below, "
            "write a concise (4-6 sentence) professional recommendation for a "
            "purchasing manager. State the recommended action clearly, then "
            "justify it using the facts. Do not invent any numbers not given.\n\n"
            f"Recommended Action: {action}\n"
            f"Facts:\n" + "\n".join(f"- {r}" for r in reasons) + "\n"
            f"Estimated Savings: ${estimated_savings:,.2f}\n"
            f"Context: {context}\n"
        )

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350,
            temperature=0.3,
        )
        text = response.choices[0].message.content.strip()
        return text if text else _fallback_narrative(action, reasons, estimated_savings)
    except Exception as exc:  # noqa: BLE001 - never let AI layer crash the app
        fallback = _fallback_narrative(action, reasons, estimated_savings)
        return fallback + f"\n\n(Note: Groq API call failed, showing rule-based summary. Detail: {exc})"
