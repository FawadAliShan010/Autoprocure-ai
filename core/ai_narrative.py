"""
AI Narrative Layer

Turns the structured gate results + decision into the human-readable
reasoning shown on the "AI Procurement Decision" screen.

If a GROQ_API_KEY environment variable is set, this calls the Groq LLM API
(openai/gpt-oss-120b) to produce a polished narrative.

If no key is configured, it falls back to a deterministic template built
from the same structured facts, so the app remains fully functional.
"""

import os

# Current production Groq model
GROQ_MODEL = "openai/gpt-oss-120b"


def _fallback_narrative(
    action: str,
    reasons: list,
    estimated_savings: float
) -> str:
    lines = [f"Recommended Action: {action}", ""]

    lines.append("Reasoning:")
    for r in reasons:
        lines.append(f"- {r}")

    if estimated_savings and estimated_savings > 0:
        lines.append("")
        lines.append(
            f"Estimated Savings: ${estimated_savings:,.2f}"
        )

    return "\n".join(lines)


def generate_reasoning(
    action: str,
    reasons: list,
    estimated_savings: float,
    context: dict
) -> str:
    """
    Generate a concise AI-powered procurement recommendation.

    context:
        Dictionary containing information such as item, department,
        requested quantity, and employee.
    """

    api_key = os.environ.get("GROQ_API_KEY", "").strip()

    # No API key -> use reliable rule-based fallback
    if not api_key:
        return _fallback_narrative(
            action,
            reasons,
            estimated_savings
        )

    try:
        from groq import Groq

        client = Groq(api_key=api_key)

        prompt = (
            "You are an AI procurement analyst. "
            "Given the structured procurement facts below, write a concise "
            "4-6 sentence professional recommendation for a purchasing manager. "
            "State the recommended action clearly, then justify it using the "
            "provided facts. Do not invent numbers, facts, or assumptions.\n\n"

            f"Recommended Action: {action}\n\n"

            "Facts:\n"
            + "\n".join(f"- {r}" for r in reasons)
            + "\n\n"

            f"Estimated Savings: ${estimated_savings:,.2f}\n\n"

            f"Context: {context}\n"
        )

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=350,
            temperature=0.3,
        )

        text = response.choices[0].message.content.strip()

        return (
            text
            if text
            else _fallback_narrative(
                action,
                reasons,
                estimated_savings
            )
        )

    except Exception:
        # Never let the AI layer crash the procurement application.
        return _fallback_narrative(
            action,
            reasons,
            estimated_savings
        )
