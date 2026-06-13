import json
import os
from uuid import uuid4
from datetime import datetime
from schemas.memory import UserMemory, ChatMessage, ChatSession
from services.walrus_service import save_memory_to_walrus, load_memory_from_walrus

INDEX_FILE = "memory_index.json"

# ── In-memory fallback cache ──────────────────────────────────────────────────
# When Walrus is unreachable, profiles are kept here for the session.
_memory_cache: dict[str, UserMemory] = {}
_email_index: dict[str, str] = {}    # email → user_id
_wallet_index: dict[str, str] = {}   # wallet_address → user_id


# ── Index helpers (Walrus blob ID index stored locally) ───────────────────────

def _load_index() -> dict:
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_index(index: dict):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2)


# ── Persist to Walrus + update index ─────────────────────────────────────────

def _persist(profile: UserMemory):
    # always keep in local cache
    _memory_cache[profile.user_id] = profile
    if profile.email:
        _email_index[profile.email] = profile.user_id
    if profile.wallet_address:
        _wallet_index[profile.wallet_address] = profile.user_id

    # try Walrus — fail silently if unreachable
    blob_id = save_memory_to_walrus(profile)
    if blob_id:
        index = _load_index()
        index[f"user_id:{profile.user_id}"] = blob_id
        if profile.email:
            index[f"email:{profile.email}"] = blob_id
        if profile.wallet_address:
            index[f"wallet:{profile.wallet_address}"] = blob_id
        _save_index(index)
        print(f"[Memory] saved to Walrus: {blob_id}")
    else:
        print(f"[Memory] Walrus unavailable — using local cache only")


# ── Fetch from Walrus with local cache fallback ───────────────────────────────

def _fetch_by_user_id(user_id: str) -> UserMemory | None:
    # check local cache first (fast path)
    if user_id in _memory_cache:
        return _memory_cache[user_id]

    # try Walrus
    index = _load_index()
    blob_id = index.get(f"user_id:{user_id}")
    if blob_id:
        profile = load_memory_from_walrus(blob_id)
        if profile:
            _memory_cache[profile.user_id] = profile
            return profile

    return None


def _fetch_by_email(email: str) -> UserMemory | None:
    # check local index first
    user_id = _email_index.get(email)
    if user_id:
        return _fetch_by_user_id(user_id)

    # try Walrus index
    index = _load_index()
    blob_id = index.get(f"email:{email}")
    if blob_id:
        profile = load_memory_from_walrus(blob_id)
        if profile:
            _memory_cache[profile.user_id] = profile
            if profile.email:
                _email_index[profile.email] = profile.user_id
            return profile

    return None


def _fetch_by_wallet(wallet_address: str) -> UserMemory | None:
    # check local index first
    user_id = _wallet_index.get(wallet_address)
    if user_id:
        return _fetch_by_user_id(user_id)

    # try Walrus index
    index = _load_index()
    blob_id = index.get(f"wallet:{wallet_address}")
    if blob_id:
        profile = load_memory_from_walrus(blob_id)
        if profile:
            _memory_cache[profile.user_id] = profile
            if profile.wallet_address:
                _wallet_index[profile.wallet_address] = profile.user_id
            return profile

    return None


# ── Public API ────────────────────────────────────────────────────────────────

def create_email_profile(email: str) -> UserMemory:
    profile = UserMemory(user_id=str(uuid4()), user_type="email", email=email)
    _persist(profile)
    return profile


def create_wallet_profile(wallet_address: str) -> UserMemory:
    profile = UserMemory(user_id=str(uuid4()), user_type="wallet", wallet_address=wallet_address)
    _persist(profile)
    return profile


def get_profile(user_id: str) -> UserMemory | None:
    return _fetch_by_user_id(user_id)


def get_user_by_email(email: str) -> UserMemory | None:
    return _fetch_by_email(email)


def get_user_by_wallet_address(wallet_address: str) -> UserMemory | None:
    return _fetch_by_wallet(wallet_address)


def update_profile(user_id: str, field: str, value: str) -> UserMemory | None:
    profile = get_profile(user_id)
    if profile and hasattr(profile, field):
        setattr(profile, field, value)
        _persist(profile)
        return profile
    return None


def add_prediction(user_id: str, prediction: str) -> UserMemory | None:
    profile = get_profile(user_id)
    if profile:
        profile.predictions.append(prediction)
        _persist(profile)
        return profile
    return None


def add_opinion(user_id: str, opinion: str) -> UserMemory | None:
    profile = get_profile(user_id)
    if profile:
        profile.opinions.append(opinion)
        _persist(profile)
        return profile
    return None


def add_chat_message(user_id: str, chat_id: str, role: str, content: str):
    profile = get_profile(user_id)
    if not profile:
        return
    for chat in profile.chat_sessions:
        if chat.chat_id == chat_id:
            chat.messages.append(ChatMessage(role=role, content=content))
            break
    _persist(profile)


def clear_chat_history(user_id: str) -> bool:
    profile = get_profile(user_id)
    if not profile:
        return False
    profile.chat_sessions = []  # ← fixed from chat_history
    _persist(profile)
    return True


def create_chat_session(user_id: str, title: str = "New Chat") -> str | None:
    profile = get_profile(user_id)
    if not profile:
        return None
    chat_id = str(uuid4())
    profile.chat_sessions.append(
        ChatSession(
            chat_id=chat_id,
            title=title,
            created_at=datetime.utcnow().isoformat(),
            messages=[]
        )
    )
    _persist(profile)
    return chat_id