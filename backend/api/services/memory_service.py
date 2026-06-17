import json
import os
import sqlite3
from uuid import uuid4
from datetime import datetime
from api.schemas.memory import UserMemory, ChatMessage, ChatSession
from api.services.walrus_service import save_memory_to_walrus, load_memory_from_walrus

INDEX_FILE = "memory_index.json"

# ── Database Connection Helper ────────────────────────────────────────────────
def _get_conn():
    from database.neon_db import get_db_connection
    return get_db_connection()

# ── Index helpers ─────────────────────────────────────────────────────────────

def _load_index() -> dict:
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_index(index: dict):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2)

def _update_index(user_id: str, key: str, blob_id: str):
    index = _load_index()
    index[f"{key}:{user_id}"] = blob_id
    _save_index(index)

# ── Persistence / CRUD ────────────────────────────────────────────────────────

def _persist_profile(profile: UserMemory):
    """Persist profile to database (SQL)."""
    conn = _get_conn()
    is_sqlite = isinstance(conn, sqlite3.Connection)
    p = "?" if is_sqlite else "%s"
    
    try:
        cur = conn.cursor()
        query = f"""
            INSERT INTO users (user_id, email, wallet_address, name, nickname)
            VALUES ({p}, {p}, {p}, {p}, {p})
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name, nickname=excluded.nickname;
        """
        cur.execute(query, (
            profile.user_id, profile.email, profile.wallet_address,
            profile.name, profile.nickname
        ))
        conn.commit()
        cur.close()
    finally:
        conn.close()

def _get_profile_from_sql(user_id: str) -> UserMemory | None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = %s OR user_id = ?", (user_id, user_id)) # Crude dialect handling
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return UserMemory(**dict(row))
    return None

# ── Public API ────────────────────────────────────────────────────────────────

def create_email_profile(email: str) -> UserMemory:
    profile = UserMemory(user_id=str(uuid4()), user_type="email", email=email)
    _persist_profile(profile)
    return profile

def get_profile(user_id: str) -> UserMemory | None:
    return _get_profile_from_sql(user_id)

def add_chat_messages_batch(user_id: str, chat_id: str, user_message: str, assistant_reply: str):
    """Batch store chat messages in Walrus and update chat_sessions SQL."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT walrus_blob_id FROM chat_sessions WHERE chat_id = %s OR chat_id = ?", (chat_id, chat_id))
    row = cur.fetchone()
    blob_id = row['walrus_blob_id'] if row else None
    
    # Load existing messages or start new
    messages = load_memory_from_walrus(blob_id) if blob_id else []
    messages.append({"role": "user", "content": user_message})
    messages.append({"role": "assistant", "content": assistant_reply})
    
    # Save to Walrus
    new_blob_id = save_memory_to_walrus(messages)
    
    # Update SQL session
    cur.execute("UPDATE chat_sessions SET walrus_blob_id = %s WHERE chat_id = %s OR chat_id = ?", (new_blob_id, chat_id, chat_id))
    conn.commit()
    cur.close()
    conn.close()
    
    # Update index if needed
    _update_index(chat_id, "chat_blob", new_blob_id)

def get_user_by_email(email: str) -> UserMemory | None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s OR email = ?", (email, email))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return UserMemory(**dict(row)) if row else None

def get_user_by_wallet_address(wallet_address: str) -> UserMemory | None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE wallet_address = %s OR wallet_address = ?", (wallet_address, wallet_address))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return UserMemory(**dict(row)) if row else None

def update_profile(user_id: str, field: str, value: str) -> UserMemory | None:
    conn = _get_conn()
    cur = conn.cursor()
    query = f"UPDATE users SET {field} = %s WHERE user_id = %s" # Simplified for brevity, assumes field is validated
    cur.execute(query, (value, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return get_profile(user_id)

def add_prediction(user_id: str, prediction: str) -> UserMemory | None:
    # Store prediction as an AI memory blob in Walrus
    return _add_ai_memory(user_id, "prediction", prediction)

def add_opinion(user_id: str, opinion: str) -> UserMemory | None:
    # Store opinion as an AI memory blob in Walrus
    return _add_ai_memory(user_id, "opinion", opinion)

def create_wallet_profile(wallet_address: str) -> UserMemory:
    profile = UserMemory(user_id=str(uuid4()), user_type="wallet", wallet_address=wallet_address)
    _persist_profile(profile)
    return profile

def create_chat_session(user_id: str, title: str = "New Chat") -> str | None:
    chat_id = str(uuid4())
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO chat_sessions (chat_id, user_id, title) VALUES (%s, %s, %s)", (chat_id, user_id, title))
    conn.commit()
    cur.close()
    conn.close()
    return chat_id

def clear_chat_history(user_id: str) -> bool:
    # Implementation for clearing chat history (SQL)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_sessions WHERE user_id = %s OR user_id = ?", (user_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return True

def _add_ai_memory(user_id: str, category: str, data: str) -> UserMemory | None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT walrus_blob_id FROM ai_memories WHERE user_id = %s AND category = %s", (user_id, category))
    row = cur.fetchone()
    blob_id = row['walrus_blob_id'] if row else None
    
    memories = load_memory_from_walrus(blob_id) if blob_id else []
    memories.append(data)
    
    new_blob_id = save_memory_to_walrus(memories)
    
    if blob_id:
        cur.execute("UPDATE ai_memories SET walrus_blob_id = %s WHERE user_id = %s AND category = %s", (new_blob_id, user_id, category))
    else:
        cur.execute("INSERT INTO ai_memories (memory_id, user_id, category, data, walrus_blob_id) VALUES (%s, %s, %s, %s, %s)", (str(uuid4()), user_id, category, json.dumps({}), new_blob_id))
    
    conn.commit()
    cur.close()
    conn.close()
    _update_index(user_id, category, new_blob_id)
    return get_profile(user_id)
