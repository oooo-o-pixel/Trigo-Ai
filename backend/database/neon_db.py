import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    USE_POSTGRES = True
except ImportError:
    print("[Database] psycopg2 not found. Falling back to SQLite.")
    USE_POSTGRES = False

def get_db_connection():
    if USE_POSTGRES and DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            return conn
        except Exception as e:
            print(f"[Database] Postgres connection failed: {e}. Using SQLite fallback.")
    
    # SQLite Fallback
    conn = sqlite3.connect("trigo_local.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Common schema definitions
    # Note: Using UUID for Postgres, TEXT for SQLite (compatible with UUID strings)
    id_type = "UUID" if USE_POSTGRES and not isinstance(conn, sqlite3.Connection) else "TEXT"
    
    # 1. Users
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            user_id {id_type} PRIMARY KEY,
            email TEXT UNIQUE,
            wallet_address TEXT UNIQUE,
            name TEXT,
            nickname TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Chat Sessions
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            chat_id {id_type} PRIMARY KEY,
            user_id {id_type} REFERENCES users(user_id) ON DELETE CASCADE,
            title TEXT,
            walrus_blob_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # 3. AI Memories
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS ai_memories (
            memory_id {id_type} PRIMARY KEY,
            user_id {id_type} REFERENCES users(user_id) ON DELETE CASCADE,
            category TEXT,
            data JSONB NOT NULL,
            walrus_blob_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    conn.commit()
    cur.close()
    conn.close()
