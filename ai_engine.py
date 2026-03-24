"""AI integration layer for Shadow Stress."""

from __future__ import annotations

from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY, MAX_CONTEXT_MESSAGES, MODEL

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

META_MARKER = "[META:"
UNKNOWN_TRIGGER = "unknown"
UNKNOWN_CATEGORY = "unknown"
UNKNOWN_TECHNIQUE = "unknown"

SYSTEM_PROMPT = """You are Shadow Stress, a professional workplace stress-support assistant.

You are not an entertainment chatbot. You are a practical support tool.
Write like an experienced psychologist: calm, direct, and actionable.

STRICT RULES:
- Never use emojis.
- Avoid decorative symbols and markdown noise.
- Do not start with generic sympathy phrases like "I understand how you feel".
- Do not begin with a question. Start with analysis first.
- Keep each response concise: max 4-5 sentences.
- Be concrete. Prefer exact instructions over vague advice.
- Name the emotion directly (anger, anxiety, exhaustion, frustration, etc.).
- Use plain text only. No markdown formatting.

ALGORITHM:

1. STATE ANALYSIS
Read the message and identify:
- The core emotion (anger, irritation, apathy, anxiety, shame, guilt, burnout, etc.)
- The trigger (what exactly caused it)
- The situation category (manager conflict, peer conflict, overload, unfairness, uncertainty, micromanagement, sabotage, bullying)

State it clearly in one line:
"You are feeling [emotion] because [trigger]. This is a reaction to [category]."

2. ONE TECHNIQUE
Give exactly one technique, not a list.
Pick the technique that best fits the specific situation.
Do not repeat techniques already used with this user when possible.

Technique toolbox:

Breathing:
- 4-7-8 breathing
- Box breathing
- Lion's breath

Body-based:
- Progressive muscle relaxation
- Fist tension-release cycle
- Cold water reset
- Grounding through feet pressure

Cognitive:
- Reframing
- Decatastrophizing
- Time-distance contrast (1 year / 5 years)
- Three-column thought check
- Devil's advocate perspective
- Observer perspective
- "So what?" chain

Behavioral:
- STOP technique
- Empty-chair exercise
- Unsent letter
- Anger journal
- 10-15 minute time-out
- Focus-switch counting task
- Physical release (squats / brisk walk)

Sensory:
- 5-4-3-2-1 grounding
- Single-object focus

Communication:
- I-statement rewrite
- Grey-rock communication
- Feedback sandwich preparation

3. CLARIFY IF NEEDED
If context is unclear, ask one precise follow-up question.
Avoid vague prompts like "tell me more".

4. PERSONALIZATION
Use user history:
- Avoid repeating previously suggested techniques.
- If a recurring pattern appears, name it directly.
- Adjust depth to user maturity (new user vs returning user).

5. INTERNAL METADATA LINE
At the end of each full response, add one line in this exact format:
[META: emotion=X, trigger=Y, category=Z, technique=W]

This line is for internal analytics and will be removed before sending the reply to the user.

USER HISTORY:
{user_history}
"""


def _build_messages(
    conversation_history: list[dict[str, Any]],
    final_user_message: str,
) -> list[dict[str, Any]]:
    """Build bounded context window for Anthropic API calls."""
    messages = list(conversation_history[-MAX_CONTEXT_MESSAGES:])
    messages.append({"role": "user", "content": final_user_message})
    return messages


def _extract_text(response: Any) -> str:
    """Extract text payload from Anthropic response."""
    return response.content[0].text


def get_ai_response(
    user_message: str,
    conversation_history: list[dict[str, Any]],
    user_history: str,
) -> str:
    """Generate assistant response for one user message."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT.format(user_history=user_history),
        messages=_build_messages(conversation_history, user_message),
    )
    return _extract_text(response)


def parse_meta(response_text: str) -> dict[str, str]:
    """Parse metadata line appended by the model."""
    meta = {
        "trigger": UNKNOWN_TRIGGER,
        "category": UNKNOWN_CATEGORY,
        "technique": UNKNOWN_TECHNIQUE,
    }
    if META_MARKER not in response_text:
        return meta

    try:
        meta_str = response_text.split(META_MARKER, 1)[1].split("]", 1)[0]
    except IndexError:
        return meta

    for part in meta_str.split(","):
        item = part.strip()
        if "=" not in item:
            continue

        key, value = item.split("=", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()

        if normalized_key in {"trigger"}:
            meta["trigger"] = normalized_value
        elif normalized_key in {"category"}:
            meta["category"] = normalized_value
        elif normalized_key in {"technique"}:
            meta["technique"] = normalized_value

    return meta


def clean_response(response_text: str) -> str:
    """Remove internal metadata suffix before sending text to user."""
    if META_MARKER in response_text:
        return response_text.split(META_MARKER, 1)[0].strip()
    return response_text.strip()


def generate_session_summary(
    conversation_history: list[dict[str, Any]],
    user_history: str,
) -> str:
    """Generate a short summary for a completed support session."""
    summary_instruction = (
        "Summarize this session in 2-3 concise sentences. "
        "Use plain text without markdown or special symbols."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=(
            "You are an analyst. Summarize the support session briefly and clearly. "
            f"Consider this user history: {user_history}. "
            "No markdown."
        ),
        messages=_build_messages(conversation_history, summary_instruction),
    )
    return _extract_text(response)


def generate_hr_advice(stats: dict[str, Any]) -> str:
    """Generate practical HR recommendations from aggregated statistics."""
    stats_text = (
        f"Total sessions: {stats['total_sessions']}\n"
        f"Active users: {stats['active_users']}\n"
        f"Categories: {stats['categories']}\n"
        f"Triggers: {stats['triggers']}\n"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system="You are an HR analyst. Write plain text only, no markdown.",
        messages=[
            {
                "role": "user",
                "content": (
                    "Anonymous team statistics:\n\n"
                    f"{stats_text}\n"
                    "Provide 3 specific recommendations for a team lead. "
                    "No generic advice, no emojis, no decorative symbols."
                ),
            }
        ],
    )
    return _extract_text(response)
