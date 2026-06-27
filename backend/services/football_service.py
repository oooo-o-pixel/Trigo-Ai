# backend/services/football_service.py
import os
import re
import json
import time
from datetime import datetime, timezone
import requests

from services import scorer_store

# ── API-Football (api-sports.io) ──────────────────────────────────────────────
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://v3.football.api-sports.io"
WC_LEAGUE_ID = 1

headers = {"x-apisports-key": FOOTBALL_API_KEY}

DAILY_REQUEST_BUDGET = int(os.getenv("FOOTBALL_API_DAILY_BUDGET", "90"))
_request_log = {"date": None, "count": 0}


def _budget_ok() -> bool:
    today = datetime.now(timezone.utc).date().isoformat()
    if _request_log["date"] != today:
        _request_log["date"] = today
        _request_log["count"] = 0
    return _request_log["count"] < DAILY_REQUEST_BUDGET


def _get(endpoint: str, params: dict = None) -> dict:
    if not _budget_ok():
        print(f"[FootballAPI] daily budget ({DAILY_REQUEST_BUDGET}) reached — skipping {endpoint}")
        return {}
    try:
        response = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=5)
        _request_log["count"] += 1
        if response.status_code == 200:
            data = response.json()
            if data.get("errors"):
                print(f"[FootballAPI] {endpoint} errors: {data['errors']}")
            return data
        print(f"[FootballAPI] {response.status_code} - {endpoint}: {response.text[:200]}")
        return {}
    except Exception as e:
        print(f"[FootballAPI] request error: {e}")
        return {}


_lineup_cache: dict[int, list] = {}
_fixture_id_cache: dict[tuple, int | None] = {}

# Events get a TTL, unlike lineups/fixture-IDs which are cached forever.
# Confirmed in testing: api-sports.io can post a goal's scorer immediately
# but backfill the assist field a little later — caching the first
# (assist-less) response forever would mean the app never picks up the
# correction once it lands.
_events_cache: dict[int, dict] = {}
EVENTS_CACHE_TTL = int(os.getenv("FOOTBALL_EVENTS_CACHE_TTL", "1800"))  # 30 min

# Free tier only allows querying fixtures within a small rolling window
# around "today" (confirmed via live error: a ~3-day window, roughly
# yesterday through tomorrow). Calls outside this range always fail
# with a plan error — skip them rather than waste budget and silently
# fall back to garbled names.
FIXTURE_DATE_WINDOW_DAYS = 1


def _within_allowed_date_window(match_date: datetime) -> bool:
    today = datetime.now(timezone.utc).date()
    delta = abs((match_date.date() - today).days)
    return delta <= FIXTURE_DATE_WINDOW_DAYS


def get_lineup(fixture_id: int) -> list:
    if fixture_id in _lineup_cache:
        return _lineup_cache[fixture_id]
    response = _get("/fixtures/lineups", {"fixture": fixture_id}).get("response", [])
    if response:
        _lineup_cache[fixture_id] = response
    return response


def get_match_events(fixture_id: int) -> list:
    cached = _events_cache.get(fixture_id)
    now = time.time()
    if cached and (now - cached["timestamp"]) < EVENTS_CACHE_TTL:
        return cached["data"]

    response = _get("/fixtures/events", {"fixture": fixture_id}).get("response", [])
    if response:
        _events_cache[fixture_id] = {"data": response, "timestamp": now}
        return response

    # Fresh call failed or got skipped by the budget guard — serve the last
    # good data rather than nothing, if we have any.
    return cached["data"] if cached else []


def _normalize_name(name: str) -> str:
    return (name or "").lower().replace(" republic", "").replace("-", " ").strip()


def _names_match(a: str, b: str) -> bool:
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _find_fixture_id(home_name: str, away_name: str, match_date: datetime) -> int | None:
    key = (home_name, away_name, match_date.date().isoformat())
    if key in _fixture_id_cache:
        return _fixture_id_cache[key]

    if not _within_allowed_date_window(match_date):
        # Outside free-tier date range — don't bother calling, it'll
        # always fail with a plan error on this tier.
        _fixture_id_cache[key] = None
        return None

    response = _get("/fixtures", {
        "date": match_date.strftime("%Y-%m-%d"),
        "timezone": "UTC"
    }).get("response", [])

    found = None
    for m in response:
        if m.get("league", {}).get("id") != WC_LEAGUE_ID:
            continue
        h = m["teams"]["home"]["name"]
        a = m["teams"]["away"]["name"]
        if _names_match(h, home_name) and _names_match(a, away_name):
            found = m["fixture"]["id"]
            break

    _fixture_id_cache[key] = found
    return found


def format_lineup_for_match(home_name: str, away_name: str, match_date: datetime) -> str:
    fixture_id = _find_fixture_id(home_name, away_name, match_date)
    if fixture_id is None:
        return ""
    lineup_data = get_lineup(fixture_id)
    if not lineup_data:
        return ""
    lines = []
    for side in lineup_data:
        team_name = side.get("team", {}).get("name", "Unknown")
        formation = side.get("formation") or "unknown formation"
        starters = ", ".join(
            p["player"]["name"] for p in side.get("startXI", []) if p.get("player")
        )
        lines.append(f"      {team_name} ({formation}): {starters}")
    return "\n".join(lines)


def _get_clean_scorers_from_api(home_name: str, away_name: str, match_date: datetime) -> dict | None:
    """
    Fetch goalscorer + assister names from api-sports.io events.
    Returns {"home": [...], "away": [...]} or None if unavailable.
    Verified against real match reporting — scorer/assist names and
    substitution timing both checked out for the Norway-Senegal test case.
    """
    fixture_id = _find_fixture_id(home_name, away_name, match_date)
    if fixture_id is None:
        return None
    events = get_match_events(fixture_id)
    if not events:
        return None

    home_scorers, away_scorers = [], []
    for ev in events:
        if ev.get("type") != "Goal":
            continue
        minute = ev.get("time", {}).get("elapsed")
        extra = ev.get("time", {}).get("extra")
        minute_str = f"{minute}+{extra}'" if extra else f"{minute}'"
        team = ev.get("team", {}).get("name", "")
        scorer = ev.get("player", {}).get("name") or "Unknown"
        detail = ev.get("detail", "")
        # Sibling field to "player" — null for most penalties/own goals,
        # present for open-play goals.
        assist_name = (ev.get("assist") or {}).get("name")

        if detail == "Own Goal":
            entry = f"{scorer} {minute_str} (OG)"
        elif detail == "Penalty":
            entry = f"{scorer} {minute_str} (p)"
        elif assist_name:
            entry = f"{scorer} {minute_str} (assist: {assist_name})"
        else:
            entry = f"{scorer} {minute_str}"

        if _names_match(team, home_name):
            home_scorers.append(entry)
        else:
            away_scorers.append(entry)

    return {"home": home_scorers, "away": away_scorers}


# ── worldcup26.ir ─────────────────────────────────────────────────────────────
WC26_BASE = "https://worldcup26.ir"

_games_cache = {"data": None, "timestamp": 0, "ttl": 300, "has_live": False}


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_scorers(raw: str) -> list[str]:
    if not raw or raw == "null":
        return []
    try:
        json_str = raw.strip()
        if json_str.startswith("{") and json_str.endswith("}"):
            json_str = "[" + json_str[1:-1] + "]"
        scorers = json.loads(json_str)
        return [s.strip() for s in scorers if s.strip()]
    except Exception:
        return re.findall(r'"([^"]+)"', raw)


def _fetch_games() -> list:
    cache = _games_cache
    now = time.time()
    current_ttl = 30 if cache.get("has_live") else cache["ttl"]
    if cache["data"] is not None and (now - cache["timestamp"]) < current_ttl:
        return cache["data"]
    try:
        resp = requests.get(f"{WC26_BASE}/get/games", timeout=5)
        if resp.status_code == 200:
            games = resp.json().get("games", [])
            cache["data"] = games
            cache["timestamp"] = now
            cache["has_live"] = any(g.get("time_elapsed") == "live" for g in games)
            return games
        print(f"[WorldCup26] {resp.status_code} fetching /get/games")
    except Exception as e:
        print(f"[WorldCup26] request error: {e}")
    return cache["data"] if cache["data"] is not None else []


def _parse_game(g: dict) -> dict | None:
    home = g.get("home_team_name_en")
    away = g.get("away_team_name_en")
    if not home or not away:
        return None
    try:
        match_date = datetime.strptime(g["local_date"], "%m/%d/%Y %H:%M")
    except Exception:
        return None

    raw_round = g.get("round") or ""
    group = g.get("group") or None

    return {
        "home": home,
        "away": away,
        "home_score": _to_int(g.get("home_score")),
        "away_score": _to_int(g.get("away_score")),
        "home_scorers": _parse_scorers(g.get("home_scorers", "")),
        "away_scorers": _parse_scorers(g.get("away_scorers", "")),
        "status": g.get("time_elapsed"),
        "finished": g.get("finished") == "TRUE",
        "group": group,
        "round": raw_round,
        "date": match_date,
    }


def _get_parsed_games() -> list:
    parsed = [_parse_game(g) for g in _fetch_games()]
    return [g for g in parsed if g is not None]


def _is_knockout(m: dict) -> bool:
    no_group = not m.get("group")
    round_str = (m.get("round") or "").lower()
    knockout_keywords = ("round of", "quarter", "semi", "final", "third")
    round_is_knockout = any(k in round_str for k in knockout_keywords)
    return no_group or round_is_knockout


def _format_scorers(m: dict) -> str:
    """
    Resolution order for scorer/assist data:
      1. Permanent Postgres store (scorer_store) — survives the free-tier
         date window closing and survives server restarts.
      2. Live api-sports.io lookup — only works while the match is inside
         the free-tier rolling date window. If it succeeds, the clean
         result is written to scorer_store so it's available forever
         after this point, even once the window closes.
      3. worldcup26.ir raw names — last resort, no assist data, names can
         be garbled for some players.
    """
    home_scorers = m.get("home_scorers", [])
    away_scorers = m.get("away_scorers", [])

    if not (home_scorers or away_scorers):
        return ""

    date_iso = m["date"].date().isoformat()

    stored = scorer_store.get_stored_scorers(m["home"], m["away"], date_iso)
    if stored and (stored["home"] or stored["away"]):
        home_scorers = stored["home"]
        away_scorers = stored["away"]
    else:
        clean = _get_clean_scorers_from_api(m["home"], m["away"], m["date"])
        if clean and (clean["home"] or clean["away"]):
            home_scorers = clean["home"]
            away_scorers = clean["away"]
            scorer_store.store_scorers(m["home"], m["away"], date_iso, clean["home"], clean["away"])

    lines = []
    for scorer in home_scorers:
        lines.append(f"      ⚽ {scorer} ({m['home']})")
    for scorer in away_scorers:
        lines.append(f"      ⚽ {scorer} ({m['away']})")
    return "\n".join(lines)


def format_match(m: dict) -> str:
    date_str = m["date"].strftime("%Y-%m-%d")
    label = f"Group {m['group']}" if m.get("group") else (m.get("round") or "Knockout")
    if m["home_score"] is not None and m["away_score"] is not None:
        return f"{m['home']} {m['home_score']}-{m['away_score']} {m['away']} [{label}, {date_str}]"
    return f"{m['home']} vs {m['away']} [{label}, {date_str}]"


def get_live_matches() -> list:
    return [m for m in _get_parsed_games() if m["status"] == "live"]


def get_recent_results(limit: int = 5) -> list:
    finished = [m for m in _get_parsed_games() if m["finished"]]
    finished.sort(key=lambda m: m["date"])
    return finished[-limit:]


def get_upcoming_fixtures(limit: int = 5) -> list:
    upcoming = [m for m in _get_parsed_games() if m["status"] == "notstarted"]
    upcoming.sort(key=lambda m: m["date"])
    return upcoming[:limit]


# ── Bracket ───────────────────────────────────────────────────────────────────

_ROUND_ORDER = {
    "round of 32": 1,
    "round of 16": 2,
    "quarter-finals": 3,
    "semi-finals": 4,
    "third place": 5,
    "final": 6,
}

def _round_sort_key(round_str: str) -> int:
    return _ROUND_ORDER.get((round_str or "").lower().strip(), 99)


def get_bracket() -> list:
    knockout = [m for m in _get_parsed_games() if _is_knockout(m)]
    if not knockout:
        return []
    rounds: dict[str, list] = {}
    for m in knockout:
        r = m.get("round") or "Knockout"
        rounds.setdefault(r, []).append(m)
    for r in rounds:
        rounds[r].sort(key=lambda m: m["date"])
    sorted_rounds = sorted(rounds.items(), key=lambda kv: _round_sort_key(kv[0]))
    return [{"round": r, "matches": matches} for r, matches in sorted_rounds]


def _format_bracket_match(m: dict) -> str:
    if m["home_score"] is not None and m["away_score"] is not None:
        result = f"{m['home_score']}-{m['away_score']}"
        if m["finished"]:
            if m["home_score"] > m["away_score"]:
                winner = m["home"]
            elif m["away_score"] > m["home_score"]:
                winner = m["away"]
            else:
                winner = "Draw/Penalties"
            return f"  {m['home']} {result} {m['away']}  → {winner} advances"
        else:
            return f"  {m['home']} {result} {m['away']}  [LIVE]"
    date_str = m["date"].strftime("%b %d, %H:%M UTC")
    return f"  {m['home']} vs {m['away']}  [{date_str}]"


# ── Standings ─────────────────────────────────────────────────────────────────

_groups_cache = {"data": None, "timestamp": 0, "ttl": 300}


def _fetch_groups() -> list:
    cache = _groups_cache
    now = time.time()
    if cache["data"] is not None and (now - cache["timestamp"]) < cache["ttl"]:
        return cache["data"]
    try:
        resp = requests.get(f"{WC26_BASE}/get/groups", timeout=5)
        if resp.status_code == 200:
            groups = resp.json().get("groups", [])
            cache["data"] = groups
            cache["timestamp"] = now
            return groups
        print(f"[WorldCup26] {resp.status_code} fetching /get/groups")
    except Exception as e:
        print(f"[WorldCup26] request error: {e}")
    return cache["data"] if cache["data"] is not None else []


def _build_team_name_map() -> dict:
    mapping = {}
    for g in _fetch_games():
        hid, hname = g.get("home_team_id"), g.get("home_team_name_en")
        aid, aname = g.get("away_team_id"), g.get("away_team_name_en")
        if hid and hname:
            mapping[hid] = hname
        if aid and aname:
            mapping[aid] = aname
    return mapping


def get_standings() -> list:
    groups = _fetch_groups()
    if not groups:
        return []
    name_map = _build_team_name_map()
    result = []
    for g in groups:
        rows = []
        for t in g.get("teams", []):
            team_id = t.get("team_id")
            rows.append({
                "team": name_map.get(team_id, f"Team {team_id}"),
                "played": _to_int(t.get("mp")) or 0,
                "points": _to_int(t.get("pts")) or 0,
                "gd": _to_int(t.get("gd")) or 0,
                "gf": _to_int(t.get("gf")) or 0,
            })
        rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"]))
        result.append({"group": g.get("name"), "rows": rows})
    result.sort(key=lambda grp: grp["group"] or "")
    return result


# ── Main context builder ──────────────────────────────────────────────────────

def get_match_context_for_ai() -> str:
    context_parts = ["=== FIFA WORLD CUP 2026 DATA ==="]
    has_real_data = False

    live = get_live_matches()
    if live:
        has_real_data = True
        context_parts.append("\n🔴 LIVE NOW:")
        for m in live:
            context_parts.append(f"  - {format_match(m)}")
            scorers = _format_scorers(m)
            if scorers:
                context_parts.append(f"      Goals so far:\n{scorers}")
            lineup_text = format_lineup_for_match(m["home"], m["away"], m["date"])
            if lineup_text:
                context_parts.append(lineup_text)

    recent = get_recent_results(5)
    if recent:
        has_real_data = True
        context_parts.append("\n✅ RECENT RESULTS:")
        for m in recent:
            context_parts.append(f"  - {format_match(m)}")
            scorers = _format_scorers(m)
            if scorers:
                context_parts.append(scorers)

    upcoming = get_upcoming_fixtures(5)
    if upcoming:
        has_real_data = True
        context_parts.append("\n📅 UPCOMING FIXTURES:")
        for m in upcoming:
            context_parts.append(f"  - {format_match(m)}")

    standings = get_standings()
    if standings:
        has_real_data = True
        context_parts.append("\n📊 GROUP STANDINGS:")
        for group in standings:
            context_parts.append(f"  Group {group['group']}:")
            for rank, row in enumerate(group["rows"], start=1):
                context_parts.append(
                    f"    {rank}. {row['team']} - {row['points']}pts "
                    f"({row['played']} played, GD {row['gd']:+d})"
                )

    bracket = get_bracket()
    if bracket:
        has_real_data = True
        context_parts.append("\n🏆 KNOCKOUT BRACKET:")
        for section in bracket:
            context_parts.append(f"\n  {section['round'].upper()}:")
            for m in section["matches"]:
                context_parts.append(_format_bracket_match(m))

    if has_real_data:
        snapshot_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        context_parts.insert(1, (
            f"[LIVE DATA — snapshot taken {snapshot_time}. Scores, results, "
            f"standings, and bracket from worldcup26.ir; goalscorer names, "
            f"assists, and lineups from api-sports.io where available. Use "
            f"ONLY the data below for any 2026 World Cup scores, goalscorers, "
            f"assists, or results — NEVER invent or guess these details. If a "
            f"match or scorer is not listed below, say you don't have that "
            f"confirmed rather than making it up.]"
        ))
    else:
        context_parts.append("""
[NO LIVE DATA AVAILABLE RIGHT NOW — general background only, not current scores/fixtures:]
FIFA World Cup 2026 is hosted by USA, Canada and Mexico.
It features 48 teams for the first time — expanded from 32.
The tournament runs from June 11 to July 19, 2026.
Key favourites include Brazil, France, England, Argentina, Spain and Portugal.
Group stage fixtures are scheduled across 16 host cities in North America.
Use your football knowledge to discuss predictions, history, and team analysis,
but do not state specific 2026 scores, lineups, or standings as fact right now.""")

    return "\n".join(context_parts)