import os
import json
from uuid import uuid4
import time
import concurrent.futures
from datetime import datetime

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json
from contextlib import contextmanager
from services.walrus_service import (
    save_memory_to_walrus, load_memory_from_walrus,
    save_text_to_walrus, load_text_from_walrus,
)

from schemas.memory import UserMemory, ChatMessage, ChatSession

DATABASE_URL = os.environ["DATABASE_URL"]

# Fields that live directly on the users table
USERS_TABLE_FIELDS = {"name", "nickname"}
# Fields that live as rows in ai_memories (single-value, upserted)
MEMORY_CATEGORY_FIELDS = {"favorite_club", "favorite_player", "supported_country"}

# ── Connection pool ────────────────────────────────────────────────────────────
# Reuses already-authenticated connections instead of opening a fresh
# TCP+TLS+auth handshake to Neon on every single call.
_pool = psycopg2.pool.SimpleConnectionPool(
    1, 10, DATABASE_URL, cursor_factory=RealDictCursor
)


@contextmanager
def get_conn():
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ── Internal: build a full UserMemory from DB rows ────────────────────────────

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

                # Fetch all Walrus blobs for this session in parallel instead
                # of one-at-a-time — turns N sequential round-trips into 1
                # batch of concurrent ones.
                blob_ids = [m["walrus_blob_id"] for m in msg_rows]
                if blob_ids:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                        contents = list(executor.map(load_text_from_walrus, blob_ids))
                else:
                    contents = []

                messages = [
                    ChatMessage(
                        role=m["role"],
                        content=content or "",
                        timestamp=m["timestamp"].isoformat() if m["timestamp"] else datetime.utcnow().isoformat()
                    )
                    for m, content in zip(msg_rows, contents)
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


# ── Persist (kept for main.py's direct title-sync calls) ──────────────────────

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
                "SELECT * FROM messages WHERE chat_id = %s ORDER BY timestamp ASC",
                (chat_id,)
            )
            msg_rows = cur.fetchall()

    blob_ids = [m["walrus_blob_id"] for m in msg_rows]
    if blob_ids:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            contents = list(executor.map(load_text_from_walrus, blob_ids))
    else:
        contents = []

    messages = [
        {
            "role": m["role"],
            "content": content or "",
            "timestamp": m["timestamp"].isoformat() if m["timestamp"] else None,
        }
        for m, content in zip(msg_rows, contents)
    ]
    return {"title": session_row["title"], "messages": messages}

    blob_id = save_text_to_walrus_with_retry(content)
    if not blob_id:
        print(f"[Memory] Walrus save failed — message not persisted to Postgres")
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (chat_id, role, walrus_blob_id) VALUES (%s, %s, %s)",
                (chat_id, role, blob_id)
            )


def add_chat_messages_batch(user_id: str, chat_id: str, user_message: str, assistant_reply: str):
    # Save both messages to Walrus in parallel instead of sequentially —
    # halves the worst-case wait when Walrus is slow.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        user_future = executor.submit(save_text_to_walrus_with_retry, user_message)
        reply_future = executor.submit(save_text_to_walrus_with_retry, assistant_reply)
        user_blob_id = user_future.result()
        reply_blob_id = reply_future.result()

    if not user_blob_id or not reply_blob_id:
        print(f"[Memory] Walrus save failed — message(s) not persisted to Postgres")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (chat_id, role, walrus_blob_id) VALUES (%s, 'user', %s), (%s, 'assistant', %s)",
                (chat_id, user_blob_id, chat_id, reply_blob_id)
            )


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


def save_text_to_walrus_with_retry(content: str, retries=1, delay=1) -> str | None:
    # Kept short — this runs on the blocking /chat request path, so a slow
    # retry loop here directly delays the user's reply.
    for attempt in range(retries + 1):
        blob_id = save_text_to_walrus(content)
        if blob_id:
            return blob_id
        if attempt < retries:
            time.sleep(delay)
    return None

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