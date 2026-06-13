# backend/services/football_service.py
import os
import time
import requests

FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"
WC_ID = "WC"

headers = {
    "X-Auth-Token": FOOTBALL_API_KEY
}

# ── Cache ─────────────────────────────────────────────────────────────────────
_cache = {"data": None, "timestamp": 0}
CACHE_TTL = 300  # 5 minutes


# ── Request handler ───────────────────────────────────────────────────────────

def _get(endpoint: str, params: dict = None) -> dict:
    try:
        response = requests.get(
            f"{BASE_URL}{endpoint}",
            headers=headers,
            params=params,
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
        print(f"[FootballAPI] {response.status_code} - {endpoint}: {response.text[:200]}")
        return {}
    except Exception as e:
        print(f"[FootballAPI] request error: {e}")
        return {}


# ── Data fetchers ─────────────────────────────────────────────────────────────

def get_live_matches() -> list:
    data = _get(f"/competitions/{WC_ID}/matches", {"status": "IN_PLAY,PAUSED"})
    return data.get("matches", [])


def get_recent_results(limit: int = 5) -> list:
    data = _get(f"/competitions/{WC_ID}/matches", {"status": "FINISHED"})
    matches = data.get("matches", [])
    return matches[-limit:]


def get_upcoming_fixtures(limit: int = 5) -> list:
    data = _get(f"/competitions/{WC_ID}/matches", {"status": "TIMED,SCHEDULED"})
    matches = data.get("matches", [])
    return matches[:limit]


def get_standings() -> list:
    data = _get(f"/competitions/{WC_ID}/standings")
    return data.get("standings", [])


# ── Formatter ─────────────────────────────────────────────────────────────────

def format_match(match: dict) -> str:
    try:
        home = match["homeTeam"]["name"] or "TBD"
        away = match["awayTeam"]["name"] or "TBD"
        date = match["utcDate"][:10]
        stage = match["stage"].replace("_", " ").title()
        home_score = match["score"]["fullTime"]["home"]
        away_score = match["score"]["fullTime"]["away"]

        if home_score is not None and away_score is not None:
            return f"{home} {home_score}-{away_score} {away} [{stage}, {date}]"
        else:
            return f"{home} vs {away} [{stage}, {date}]"
    except:
        return "Match data unavailable"


# ── Main context builder (cached) ─────────────────────────────────────────────

def get_match_context_for_ai() -> str:
    now = time.time()

    # return cached data if still fresh
    if _cache["data"] and (now - _cache["timestamp"]) < CACHE_TTL:
        return _cache["data"]

    # rebuild context
    context_parts = ["=== FIFA WORLD CUP 2026 DATA ==="]

    live = get_live_matches()
    if live:
        context_parts.append("\n🔴 LIVE NOW:")
        for match in live:
            context_parts.append(f"  - {format_match(match)}")

    recent = get_recent_results(5)
    if recent:
        context_parts.append("\n✅ RECENT RESULTS:")
        for match in recent:
            context_parts.append(f"  - {format_match(match)}")

    upcoming = get_upcoming_fixtures(5)
    if upcoming:
        context_parts.append("\n📅 UPCOMING FIXTURES:")
        for match in upcoming:
            context_parts.append(f"  - {format_match(match)}")

    # fallback if no data yet
    if len(context_parts) == 1:
        context_parts.append("""
FIFA World Cup 2026 is hosted by USA, Canada and Mexico.
It features 48 teams for the first time — expanded from 32.
The tournament runs from June 11 to July 19, 2026.
Key favourites include Brazil, France, England, Argentina, Spain and Portugal.
Group stage fixtures are scheduled across 16 host cities in North America.
Use your football knowledge to discuss predictions, history, and team analysis
until live match data becomes available.""")

    result = "\n".join(context_parts)

    # update cache
    _cache["data"] = result
    _cache["timestamp"] = now
    print(f"[FootballAPI] cache refreshed at {time.strftime('%H:%M:%S')}")

    return result