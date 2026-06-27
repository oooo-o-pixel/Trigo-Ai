# backend/services/name_resolver.py
"""
Fixes worldcup26.ir's transliteration-garbled scorer names by fuzzy-matching
them against a real squad reference — entirely local, no external API call,
so it can't be rate-limited, suspended, or paywalled like every provider
tried so far in this project.

Works fine for LIVE matches: the squad list is static for the whole
tournament (rosters don't change mid-match), so there's no freshness lag —
only worldcup26.ir's score/scorer feed needs to be live, which it already is.

What this does NOT fix: assists. That data doesn't exist anywhere in
worldcup26.ir, garbled or not. _get_clean_scorers_from_api() (api-sports.io)
is still tried on top of this for assist enrichment when available — but
this resolver is what guarantees a correct *name* even when that account
is down/suspended/budget-exhausted.
"""
import os
import re
import json
import difflib

_SQUAD_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "squad_reference.json")
_squads: dict | None = None


def _load_squads() -> dict:
    global _squads
    if _squads is None:
        try:
            with open(_SQUAD_PATH, "r", encoding="utf-8") as f:
                _squads = json.load(f)
        except Exception as e:
            print(f"[NameResolver] failed to load squad reference: {e}")
            _squads = {}
    return _squads


def _split_name_and_minute(entry: str) -> tuple[str, str]:
    """'Paph Gviih 59'' -> ('Paph Gviih', "59'")"""
    match = re.match(r"^(.*?)\s*(\d+\+?\d*')$", entry.strip())
    if match:
        return match.group(1).strip(), match.group(2)
    return entry.strip(), ""


def resolve_player_name(garbled_name: str, team_name: str, cutoff: float = 0.45) -> str:
    """
    Returns the corrected name if a confident match is found in that team's
    squad, otherwise returns the original name unchanged — showing an
    uncertain-but-real name beats confidently substituting the wrong player.
    """
    squad = _load_squads().get(team_name)
    if not squad:
        return garbled_name  # no reference for this team yet — add it to squad_reference.json
    matches = difflib.get_close_matches(garbled_name, squad, n=1, cutoff=cutoff)
    return matches[0] if matches else garbled_name


def clean_scorer_entry(entry: str, team_name: str) -> str:
    """Takes a raw worldcup26.ir scorer string (name + minute combined) and
    returns it with the name portion corrected, minute preserved as-is."""
    name, minute = _split_name_and_minute(entry)
    clean_name = resolve_player_name(name, team_name)
    return f"{clean_name} {minute}".strip()