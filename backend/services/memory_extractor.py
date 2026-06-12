# memory_extractor.py
import json
from services.ai_service import get_client

def extract_memory(message: str) -> dict | None:
    client = get_client()
    if client is None:
        return None  # no OPENAI_API_KEY — skip extraction rather than crash
    prompt = f"""
    You are a memory extraction assistant for a football AI app.

    Read this user message and extract any personal information worth remembering.
    Return a JSON object with "type" and "value", or null if nothing is worth storing.

    Valid types:
    - "name" → user's real name
    - "nickname" → what they want to be called
    - "favorite_club" → their club
    - "favorite_player" → their favourite player
    - "supported_country" → country they support internationally
    - "prediction" → a match or tournament prediction
    - "opinion" → a football opinion or take

    Rules:
    - Return ONLY a JSON object or null. No explanation, no markdown.
    - If multiple things are mentioned, return the most significant one.
    - For predictions and opinions, store the full message as the value.

    Examples:
    Message: "I think Brazil will win the World Cup"
    Output: {{"type": "prediction", "value": "Brazil will win the World Cup"}}

    Message: "call me Triforce"
    Output: {{"type": "nickname", "value": "Triforce"}}

    Message: "what happened in the 1986 World Cup?"
    Output: null

    Message: "{message}"
    Output:
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        raw = response.choices[0].message.content.strip()

        if raw.lower() == "null" or not raw:
            return None

        return json.loads(raw)

    except Exception as e:
        print(f"[MemoryExtractor] error: {e}")
        return None