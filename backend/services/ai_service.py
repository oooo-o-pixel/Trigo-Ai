import os
from openai import OpenAI
from schemas.memory import UserMemory
from services.football_service import get_match_context_for_ai

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def build_system_prompt(user: UserMemory | None) -> str:
    base = """You are TRIGO-AI, an expert football companion and World Cup 2026 analyst.
    You are passionate, knowledgeable, and witty — like a football pundit who never lets you forget when you were wrong.

    Your personality:
    - You give sharp, confident takes on World Cup 2026 matches, players, tactics, and transfers
    - You LOVE to roast users about their bad predictions — bring it up unprompted when relevant
    - When a user's prediction was wrong, clown on them with energy and emojis 😂🤣
    - When a user's prediction was RIGHT, big them up like they're a genius
    - You have banter but you're never mean — think group chat energy
    - Use football slang naturally: "clean sheet", "bottle it", "park the bus" etc
    - Keep responses concise, punchy and entertaining
    - You ALWAYS reference real match data when answering questions about fixtures or results
    - You are an expert on ALL World Cup history from 1930 to present — answer historical questions with confidence
    - You specialise in World Cup 2026 for current fixtures, predictions and live discussion
    - If asked about anything completely unrelated to football, politely redirect back to football"""

    football_context = get_match_context_for_ai()
    base += f"\n\n{football_context}"

    if not user:
        return base

    memory_lines = []

    if user.name:
        memory_lines.append(f"- The user's name is {user.name}.")
    if user.nickname:
        memory_lines.append(f"- They go by '{user.nickname}'.")
    if user.favorite_club:
        memory_lines.append(f"- Their favourite club is {user.favorite_club}.")
    if user.favorite_player:
        memory_lines.append(f"- Their favourite player is {user.favorite_player}.")
    if user.supported_country:
        memory_lines.append(f"- They support {user.supported_country} internationally.")
    if user.predictions:
        memory_lines.append(f"- Their World Cup predictions so far: {', '.join(user.predictions[-3:])}.")
    if user.opinions:
        memory_lines.append(f"- Their recent opinions: {', '.join(user.opinions[-3:])}.")

    if memory_lines:
        memory_block = "\n".join(memory_lines)
        base += f"\n\n=== USER MEMORY ===\n{memory_block}\n\nUse this to personalise your responses — reference their predictions when results come in, roast them if they were wrong, celebrate if they were right. Always address them by name if you know it."

    return base


def get_ai_reply(message: str, user: UserMemory | None = None) -> str:
    system_prompt = build_system_prompt(user)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]
    )

    return response.choices[0].message.content


def generate_chat_title(first_message: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Generate a short 4-word football chat title for this opening message. Return only the title, no punctuation, no quotes: '{first_message}'"
            }],
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ChatTitle] error: {e}")
        return "Football Chat Session"