# backend/services/football_service.py
import os
import time
from datetime import datetime, timedelta, timezone
import requests

# ── API-Football (api-sports.io) — used ONLY for lineups + goal events now ───
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://v3.football.api-sports.io"
WC_LEAGUE_ID = 1  # FIFA World Cup, fixed across seasons in API-Football v3

headers = {
    "x-apisports-key": FOOTBALL_API_KEY
}

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
_events_cache: dict[int, list] = {}
_fixture_id_cache: dict[tuple, int | None] = {}


def get_lineup(fixture_id: int) -> list:
    if fixture_id in _lineup_cache:
        return _lineup_cache[fixture_id]
    response = _get("/fixtures/lineups", {"fixture": fixture_id}).get("response", [])
    if response:
        _lineup_cache[fixture_id] = response
    return response


def get_match_events(fixture_id: int) -> list:
    if fixture_id in _events_cache:
        return _events_cache[fixture_id]
    response = _get("/fixtures/events", {"fixture": fixture_id}).get("response", [])
    if response:
        _events_cache[fixture_id] = response
    return response


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


def format_events_for_match(home_name: str, away_name: str, match_date: datetime) -> str:
    fixture_id = _find_fixture_id(home_name, away_name, match_date)
    if fixture_id is None:
        return ""
    events = get_match_events(fixture_id)
    if not events:
        return ""

    lines = []
    for ev in events:
        if ev.get("type") != "Goal":
            continue
        minute = ev.get("time", {}).get("elapsed")
        extra = ev.get("time", {}).get("extra")
        minute_str = f"{minute}+{extra}'" if extra else f"{minute}'"
        team = ev.get("team", {}).get("name", "")
        scorer = ev.get("player", {}).get("name") or "Unknown"
        assist = ev.get("assist", {}).get("name")
        detail = ev.get("detail", "")

        if detail == "Own Goal":
            lines.append(f"      {minute_str} — {scorer} (OWN GOAL, for {team})")
        elif assist:
            lines.append(f"      {minute_str} — {scorer} ({team}), assisted by {assist}")
        else:
            tag = " (penalty)" if detail == "Penalty" else ""
            lines.append(f"      {minute_str} — {scorer} ({team}){tag}")

    return "\n".join(lines)


# ── worldcup26.ir — scores, live status, fixtures, standings, bracket ────────
WC26_BASE = "https://worldcup26.ir"

_games_cache = {"data": None, "timestamp": 0, "ttl": 60}


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fetch_games() -> list:
    cache = _games_cache
    now = time.time()
    if cache["data"] is not None and (now - cache["timestamp"]) < cache["ttl"]:
        return cache["data"]
    try:
        resp = requests.get(f"{WC26_BASE}/get/games", timeout=5)
        if resp.status_code == 200:
            games = resp.json().get("games", [])
            cache["data"] = games
            cache["timestamp"] = now
            return games
        print(f"[WorldCup26] {resp.status_code} fetching /get/games")
    except Exception as e:
        print(f"[WorldCup26] request error: {e}")
    return cache["data"] if cache["data"] is not None else []


def _parse_game(g: dict) -> dict | None:
    home = g.get("home_team_name_en")
    away = g.get("away_team_name_en")
    if not home or not away:
        return None  # unresolved knockout slot placeholder
    try:
        match_date = datetime.strptime(g["local_date"], "%m/%d/%Y %H:%M")
    except Exception:
        return None

    # round field distinguishes group stage from knockout rounds.
    # worldcup26.ir uses values like "Group Stage", "Round of 32",
    # "Round of 16", "Quarter-finals", "Semi-finals", "Final".
    # Anything that isn't "Group Stage" (and has no group letter) is knockout.
    raw_round = g.get("round") or ""
    group = g.get("group") or None  # present only in group stage games

    return {
        "home": home,
        "away": away,
        "home_score": _to_int(g.get("home_score")),
        "away_score": _to_int(g.get("away_score")),
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
    # A match is a knockout match if it has no group letter assigned.
    # We also cross-check the round string as a safety net.
    no_group = not m.get("group")
    round_str = (m.get("round") or "").lower()
    knockout_keywords = ("round of", "quarter", "semi", "final", "third")
    round_is_knockout = any(k in round_str for k in knockout_keywords)
    return no_group or round_is_knockout


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


# ── Bracket (knockout rounds) ─────────────────────────────────────────────────

# Round display order — earlier rounds first so the bracket reads top-to-bottom.
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
    """Return knockout matches grouped by round, sorted earliest-to-latest.
    Each entry: {"round": str, "matches": [parsed_game, ...]}
    Only includes rounds where at least one match has been scheduled
    (i.e. both team names are resolved — no placeholder slots).
    """
    knockout = [m for m in _get_parsed_games() if _is_knockout(m)]
    if not knockout:
        return []

    # Group by round name
    rounds: dict[str, list] = {}
    for m in knockout:
        r = m.get("round") or "Knockout"
        rounds.setdefault(r, []).append(m)

    # Sort matches within each round by date
    for r in rounds:
        rounds[r].sort(key=lambda m: m["date"])

    # Sort rounds in bracket order
    sorted_rounds = sorted(rounds.items(), key=lambda kv: _round_sort_key(kv[0]))
    return [{"round": r, "matches": matches} for r, matches in sorted_rounds]


def _format_bracket_match(m: dict) -> str:
    """Single line for a knockout match, with result or TBD."""
    if m["home_score"] is not None and m["away_score"] is not None:
        result = f"{m['home_score']}-{m['away_score']}"
        if m["finished"]:
            # Determine winner for clarity
            if m["home_score"] > m["away_score"]:
                winner = m["home"]
            elif m["away_score"] > m["home_score"]:
                winner = m["away"]
            else:
                winner = "Draw/Penalties"  # AET/pens — score alone won't tell us
            return f"  {m['home']} {result} {m['away']}  → {winner} advances"
        else:
            return f"  {m['home']} {result} {m['away']}  [LIVE]"
    date_str = m["date"].strftime("%b %d, %H:%M UTC")
    return f"  {m['home']} vs {m['away']}  [{date_str}]"


# ── Standings (group stage) ───────────────────────────────────────────────────
_groups_cache = {"data": None, "timestamp": 0, "ttl": 900}


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


def _group_stage_complete() -> bool:
    """True once every group-stage match is finished.
    Used to decide whether to show standings or bracket in context."""
    group_matches = [m for m in _get_parsed_games() if not _is_knockout(m)]
    if not group_matches:
        return False
    return all(m["finished"] for m in group_matches)


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
            events_text = format_events_for_match(m["home"], m["away"], m["date"])
            if events_text:
                context_parts.append(f"      Goals so far:\n{events_text}")
            lineup_text = format_lineup_for_match(m["home"], m["away"], m["date"])
            if lineup_text:
                context_parts.append(lineup_text)

    recent = get_recent_results(5)
    if recent:
        has_real_data = True
        context_parts.append("\n✅ RECENT RESULTS:")
        for m in recent:
            context_parts.append(f"  - {format_match(m)}")

        last_match = recent[-1]
        events_text = format_events_for_match(last_match["home"], last_match["away"], last_match["date"])
        if events_text:
            context_parts.append(f"\n  Goals in the last match ({format_match(last_match)}):")
            context_parts.append(events_text)

        lineup_text = format_lineup_for_match(last_match["home"], last_match["away"], last_match["date"])
        if lineup_text:
            context_parts.append(f"\n  Lineups from the last match ({format_match(last_match)}):")
            context_parts.append(lineup_text)

    upcoming = get_upcoming_fixtures(5)
    if upcoming:
        has_real_data = True
        context_parts.append("\n📅 UPCOMING FIXTURES:")
        for m in upcoming:
            context_parts.append(f"  - {format_match(m)}")

    # Show group standings during group stage, bracket once knockouts begin.
    # During the crossover period (group stage finishing + Round of 32 starting)
    # both sections can appear simultaneously — that's intentional and useful.
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
            f"[LIVE DATA — snapshot taken {snapshot_time}. Scores, live status, "
            f"standings, and bracket from worldcup26.ir; lineups and goal events from "
            f"api-sports.io. Treat everything below as the current source of "
            f"truth for the 2026 tournament.]"
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