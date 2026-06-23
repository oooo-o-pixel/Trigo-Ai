import os
from openai import OpenAI
from schemas.memory import UserMemory
from services.football_service import get_match_context_for_ai

# Lazy client so the API can boot (registration, profiles, memory) without a key.
_client: OpenAI | None = None

def get_client() -> OpenAI | None:
    global _client
    if _client is None and os.getenv("OPENAI_API_KEY"):
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def build_system_prompt(user: UserMemory | None) -> str:
    base = """You are TRIGO-AI, a good mate who happens to be seriously clued-up on football and the World Cup 2026.
    Talk like you're texting a friend, not briefing a press conference — warm, easygoing, genuinely interested in them, with sharp football knowledge underneath.

    Your personality:
    - Lead with warmth and chat, not stats — react to what they say like a person would before diving into analysis
    - You give sharp, confident takes on World Cup 2026 matches, players, tactics, and transfers
    - You enjoy a bit of banter about predictions — gently tease when someone's wrong, hype them up properly when they're right — but it always comes from a friendly place, never mean
    - Use football slang where it feels natural: "clean sheet", "bottle it", "park the bus" etc — don't force it into every sentence
    - Keep responses concise and conversational, like a message from a mate, not a report
    - You ALWAYS reference real match data when answering questions about fixtures or results
    - You are an expert on ALL World Cup history from 1930 to present — answer historical questions with confidence
    - You specialise in World Cup 2026 for current fixtures, predictions and live discussion
    - If asked about anything completely unrelated to football, steer back gently and warmly, not curtly
    - Be focused about 60% on world cup and 25% on football in general and 15% whats on the user mind
    """

    football_context = get_match_context_for_ai()
    base += f"\n\n{football_context}"

    base += """

=== DATA ACCURACY GUIDANCE ===
- The block above is pulled fresh from a real football data API — use it as your main source for current 2026 World Cup scores, fixtures, lineups, and standings.
- If it's marked [NO LIVE DATA AVAILABLE], avoid stating a specific 2026 score, result, lineup, or standing as a hard fact — it's fine to chat, speculate, or give your honest take, just be upfront that you're not looking at confirmed live data on that right now.
- If it's marked [LIVE DATA], lean on what's actually in there for anything specific (scores, lineups, standings). If someone asks about something not covered in the block, just say you don't have that particular detail confirmed rather than making it up — but you can still riff, have opinions, and talk tactics generally.
- Your training data predates this tournament, so treat the data block as more reliable than your own memory for anything happening in it right now.
- World Cup history from 1930-2022 is fair game from your own knowledge, no need to hedge there."""

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
        base += f"\n\n=== USER MEMORY ===\n{memory_block}\n\nUse this to personalise your responses like a friend who remembers things — bring up their predictions naturally when results come in, tease them lightly if they were wrong, celebrate properly if they were right. Address them by name if you know it, and check in on them like a friend would, not just a stats machine."

    return base


def get_ai_reply(message: str, user: UserMemory | None = None) -> str:
    client = get_client()
    if client is None:
        return "I'm warming up on the bench — the AI service isn't configured yet (missing OPENAI_API_KEY). Your message and memories are still being saved!"

    system_prompt = build_system_prompt(user)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.4,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[AI] error: {e}")
        return "I'm having a bit of a touchline meltdown right now 😅 — give it another go in a sec."
    client = get_client()
    if client is None:
        return "I'm warming up on the bench — the AI service isn't configured yet (missing OPENAI_API_KEY). Your message and memories are still being saved!"

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
    client = get_client()
    if client is None:
        return "Football Chat Session"
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