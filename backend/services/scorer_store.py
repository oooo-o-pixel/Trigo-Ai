# backend/services/scorer_store.py
"""
Permanent storage for goalscorer/assist data, keyed by match identity.

Why this exists: api-sports.io's free tier only allows fixture lookups
within a rolling ~1-day window around "today". Once a match falls
outside that window, _find_fixture_id() can no longer resolve it, even
if it was successfully resolved yesterday. This module captures the
clean (scorer + assist) result the first time it's available and keeps
it in Postgres permanently, so it survives both the date-window cutoff
and server restarts (unlike the in-memory caches in football_service.py).
"""
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("NEON_DATABASE_URL")


def _get_conn():
    if not DATABASE_URL:
        print("[ScorerStore] DATABASE_URL not set — permanent scorer storage disabled")
        return None
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"[ScorerStore] connection error: {e}")
        return None


def init_scorer_table():
    """Call once at app startup."""
    conn = _get_conn()
    if not conn:
        return
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS match_scorers (
                    fixture_key TEXT PRIMARY KEY,
                    home_scorers JSONB NOT NULL,
                    away_scorers JSONB NOT NULL,
                    fetched_at TIMESTAMPTZ DEFAULT now()
                )
            """)
        print("[ScorerStore] match_scorers table ready")
    except Exception as e:
        print(f"[ScorerStore] init error: {e}")
    finally:
        conn.close()


def _make_key(home_name: str, away_name: str, match_date_iso: str) -> str:
    return f"{home_name.lower().strip()}|{away_name.lower().strip()}|{match_date_iso}"


def get_stored_scorers(home_name: str, away_name: str, match_date_iso: str) -> dict | None:
    conn = _get_conn()
    if not conn:
        return None
    key = _make_key(home_name, away_name, match_date_iso)
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT home_scorers, away_scorers FROM match_scorers WHERE fixture_key = %s",
                (key,),
            )
            row = cur.fetchone()
            if row:
                return {"home": row["home_scorers"], "away": row["away_scorers"]}
            return None
    except Exception as e:
        print(f"[ScorerStore] read error: {e}")
        return None
    finally:
        conn.close()


def store_scorers(home_name: str, away_name: str, match_date_iso: str, home_scorers: list, away_scorers: list):
    """Only call this with a CLEAN (api-sports.io) result — never store
    worldcup26.ir's raw/garbled fallback names permanently."""
    conn = _get_conn()
    if not conn:
        return
    key = _make_key(home_name, away_name, match_date_iso)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO match_scorers (fixture_key, home_scorers, away_scorers)
                VALUES (%s, %s, %s)
                ON CONFLICT (fixture_key) DO UPDATE
                SET home_scorers = EXCLUDED.home_scorers,
                    away_scorers = EXCLUDED.away_scorers,
                    fetched_at = now()
            """, (key, json.dumps(home_scorers), json.dumps(away_scorers)))
        print(f"[ScorerStore] stored clean scorers for {key}")
    except Exception as e:
        print(f"[ScorerStore] write error: {e}")
    finally:
        conn.close()