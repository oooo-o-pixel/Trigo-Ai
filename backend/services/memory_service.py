import os
import re
import time
import threading
from datetime import datetime

import requests
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json
from contextlib import contextmanager

from schemas.memory import UserMemory, ChatMessage, ChatSession

DATABASE_URL = os.environ["DATABASE_URL"]

MEMWAL_BRIDGE_URL = os.environ.get("MEMWAL_BRIDGE_URL", "http://localhost:4100")

USERS_TABLE_FIELDS = {"name", "nickname"}
MEMORY_CATEGORY_FIELDS = {"favorite_club", "favorite_player", "supported_country"}

# ── Smart filter ───────────────────────────────────────────────────────────────

_REMEMBER_PATTERNS = re.compile(
    r"\b("
    r"i think|i believe|i predict|i reckon|my prediction|gonna win|will win|will lose|"
    r"my favourite|my favorite|i support|i follow|i love|my team|my club|my player|"
    r"my name is|call me|i'm called|i am called|"
    r"best player|worst player|overrated|underrated|"
    r"should have|shouldn't have|deserved|robbed|"
    r"going through|knocked out|final|semi.?final|quarter.?final|"
    r"messi|ronaldo|mbappe|haaland|neymar|salah|vinicius|bellingham|"
    r"brazil|france|england|argentina|germany|spain|portugal|nigeria|"
    r"world cup|champions league|premier league|la liga|serie a|bundesliga"
    r")\b",
    re.IGNORECASE,
)

def _is_worth_remembering(text: str) -> bool:
    return bool(_REMEMBER_PATTERNS.search(text))


# ── Connection pool ────────────────────────────────────────────────────────────

_pool = psycopg2.pool.SimpleConnectionPool(
    1, 10, DATABASE_URL, cursor_factory=RealDictCursor
)


@contextmanager
def get_conn():
    conn = _pool.getconn()
    try:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            _pool.putconn(conn, close=True)
            conn = _pool.getconn()

        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            pass
        raise
    finally:
        try:
            _pool.putconn(conn)
        except Exception:
            pass


# ── MemWal bridge ──────────────────────────────────────────────────────────────

def remember_to_memwal(user_id: str, text: str) -> None:
    """Fire-and-forget: sends text to MemWal bridge in a background thread."""
    def _send():
        try:
            requests.post(
                f"{MEMWAL_BRIDGE_URL}/remember",
                json={"namespace": user_id, "text": text},
                timeout=120,
            )
        except Exception as e:
            print(f"[MemWal] remember failed for user={user_id}: {e}")

    threading.Thread(target=_send, daemon=True).start()


def recall_from_memwal(user_id: str, query: str) -> list[str]:
    """Blocking call before AI reply. Returns [] on any failure."""
    try:
        resp = requests.post(
            f"{MEMWAL_BRIDGE_URL}/recall",
            json={"namespace": user_id, "query": query},
            timeout=8,
        )
        data = resp.json()
        if data.get("success"):
            return data.get("memories", [])
    except Exception as e:
        print(f"[MemWal] recall failed for user={user_id}: {e}")
    return []


# ── Internal helpers ───────────────────────────────────────────────────────────

def _fetch_full_profile(user_id: str) -> UserMemory | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            user_row = cur.fetchone()
            if not user_row:
                return None

            cur.execute(
                "SELECT * FROM chat_sessions WHERE user_id = %s ORDER BY created_at ASC",
                (user_id,)
            )
            session_rows = cur.fetchall()

            chat_sessions = []
            for s in session_rows:
                cur.execute(
                    "SELECT * FROM messages WHERE chat_id = %s ORDER BY timestamp ASC",
                    (s["chat_id"],)
                )
                msg_rows = cur.fetchall()

                messages = [
                    ChatMessage(
                        role=m["role"],
                        content=m["content"] or "",
                        timestamp=m["timestamp"].isoformat() if m["timestamp"] else datetime.utcnow().isoformat()
                    )
                    for m in msg_rows
                ]

                chat_sessions.append(ChatSession(
                    chat_id=str(s["chat_id"]),
                    title=s["title"],
                    created_at=s["created_at"].isoformat() if s["created_at"] else datetime.utcnow().isoformat(),
                    messages=messages
                ))

            cur.execute(
                "SELECT * FROM ai_memories WHERE user_id = %s ORDER BY created_at ASC",
                (user_id,)
            )
            memory_rows = cur.fetchall()

    predictions, opinions = [], []
    favorite_club = favorite_player = supported_country = None

    for m in memory_rows:
        value = (m["data"] or {}).get("value")
        if m["category"] == "prediction":
            predictions.append(value)
        elif m["category"] == "opinion":
            opinions.append(value)
        elif m["category"] == "favorite_club":
            favorite_club = value
        elif m["category"] == "favorite_player":
            favorite_player = value
        elif m["category"] == "supported_country":
            supported_country = value

    return UserMemory(
        user_id=str(user_row["user_id"]),
        user_type="email" if user_row["email"] else "wallet",
        email=user_row["email"],
        wallet_address=user_row["wallet_address"],
        name=user_row["name"],
        nickname=user_row["nickname"],
        favorite_club=favorite_club,
        favorite_player=favorite_player,
        supported_country=supported_country,
        predictions=predictions,
        opinions=opinions,
        chat_sessions=chat_sessions,
    )


def _persist(profile: UserMemory):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET name = %s, nickname = %s WHERE user_id = %s",
                (profile.name, profile.nickname, profile.user_id)
            )
            for session in profile.chat_sessions:
                cur.execute(
                    "UPDATE chat_sessions SET title = %s WHERE chat_id = %s AND user_id = %s",
                    (session.title, session.chat_id, profile.user_id)
                )


# ── Public API ────────────────────────────────────────────────────────────────

def create_email_profile(email: str) -> UserMemory:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email) VALUES (%s) RETURNING user_id",
                (email,)
            )
            row = cur.fetchone()
    return UserMemory(user_id=str(row["user_id"]), user_type="email", email=email)


def create_wallet_profile(wallet_address: str) -> UserMemory:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (wallet_address) VALUES (%s) RETURNING user_id",
                (wallet_address,)
            )
            row = cur.fetchone()
    return UserMemory(user_id=str(row["user_id"]), user_type="wallet", wallet_address=wallet_address)


def get_profile(user_id: str) -> UserMemory | None:
    return _fetch_full_profile(user_id)


def get_user_by_email(email: str) -> UserMemory | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
    return _fetch_full_profile(str(row["user_id"])) if row else None


def get_user_by_wallet_address(wallet_address: str) -> UserMemory | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE wallet_address = %s", (wallet_address,))
            row = cur.fetchone()
    return _fetch_full_profile(str(row["user_id"])) if row else None


def update_profile(user_id: str, field: str, value: str) -> UserMemory | None:
    if field in USERS_TABLE_FIELDS:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE users SET {field} = %s WHERE user_id = %s",
                    (value, user_id)
                )
    elif field in MEMORY_CATEGORY_FIELDS:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_memories WHERE user_id = %s AND category = %s",
                    (user_id, field)
                )
                cur.execute(
                    "INSERT INTO ai_memories (user_id, category, data) VALUES (%s, %s, %s)",
                    (user_id, field, Json({"value": value}))
                )
    else:
        return None
    return get_profile(user_id)


def add_prediction(user_id: str, prediction: str) -> UserMemory | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_memories (user_id, category, data) VALUES (%s, 'prediction', %s)",
                (user_id, Json({"value": prediction}))
            )
    return get_profile(user_id)


def add_opinion(user_id: str, opinion: str) -> UserMemory | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_memories (user_id, category, data) VALUES (%s, 'opinion', %s)",
                (user_id, Json({"value": opinion}))
            )
    return get_profile(user_id)


def get_chat_sessions_summary(user_id: str) -> list | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            if not cur.fetchone():
                return None
            cur.execute(
                """
                SELECT cs.chat_id, cs.title, cs.created_at, COUNT(m.message_id) as message_count
                FROM chat_sessions cs
                LEFT JOIN messages m ON m.chat_id = cs.chat_id
                WHERE cs.user_id = %s
                GROUP BY cs.chat_id, cs.title, cs.created_at
                ORDER BY cs.created_at ASC
                """,
                (user_id,)
            )
            rows = cur.fetchall()
    return [
        {
            "chat_id": str(r["chat_id"]),
            "title": r["title"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "message_count": r["message_count"],
        }
        for r in rows
    ]


def get_single_chat_history(user_id: str, chat_id: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM chat_sessions WHERE chat_id = %s AND user_id = %s",
                (chat_id, user_id)
            )
            if not cur.fetchone():
                return None
            cur.execute("SELECT title FROM chat_sessions WHERE chat_id = %s", (chat_id,))
            session_row = cur.fetchone()
            cur.execute(
                "SELECT role, content, timestamp FROM messages WHERE chat_id = %s ORDER BY timestamp ASC",
                (chat_id,)
            )
            msg_rows = cur.fetchall()

    messages = [
        {
            "role": m["role"],
            "content": m["content"] or "",
            "timestamp": m["timestamp"].isoformat() if m["timestamp"] else None,
        }
        for m in msg_rows
    ]
    return {"title": session_row["title"], "messages": messages}


def add_chat_messages_batch(user_id: str, chat_id: str, user_message: str, assistant_reply: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (chat_id, role, content)
                VALUES (%s, 'user', %s), (%s, 'assistant', %s)
                """,
                (chat_id, user_message, chat_id, assistant_reply)
            )

    # Only store to MemWal if the message is worth remembering
    if _is_worth_remembering(user_message):
        remember_to_memwal(user_id, user_message)


def clear_chat_history(user_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            if not cur.fetchone():
                return False
            cur.execute("DELETE FROM chat_sessions WHERE user_id = %s", (user_id,))
    return True


def create_chat_session(user_id: str, title: str = "New Chat") -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            if not cur.fetchone():
                return None
            cur.execute(
                "INSERT INTO chat_sessions (user_id, title) VALUES (%s, %s) RETURNING chat_id",
                (user_id, title)
            )
            row = cur.fetchone()
    return str(row["chat_id"])


def delete_chat_session(user_id: str, chat_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM chat_sessions WHERE chat_id = %s AND user_id = %s",
                (chat_id, user_id)
            )
            if not cur.fetchone():
                return False
            cur.execute("DELETE FROM chat_sessions WHERE chat_id = %s", (chat_id,))
    return True