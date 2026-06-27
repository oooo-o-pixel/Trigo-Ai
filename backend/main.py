from dotenv import load_dotenv
load_dotenv()

import threading
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from services.ai_service import get_ai_reply, generate_chat_title, stream_ai_reply
from services.memory_extractor import extract_memory
from services.memory_service import (
    create_email_profile,
    create_wallet_profile,
    update_profile,
    add_prediction,
    add_opinion,
    get_profile,
    get_user_by_email,
    get_user_by_wallet_address,
    add_chat_messages_batch,
    clear_chat_history,
    create_chat_session,
    get_chat_sessions_summary,
    get_single_chat_history,
    delete_chat_session,
)

app = FastAPI(
    title="Trigo-Ai",
    description="AI Football Companion with Walrus Memory",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request / Response Models ──────────────────────────────────────────────────

class EmailRegisterRequest(BaseModel):
    email: str

class WalletRegisterRequest(BaseModel):
    wallet_address: str

class ProfileSetupRequest(BaseModel):
    user_id: str
    name: str
    nickname: Optional[str] = None

class ChatRequest(BaseModel):
    user_id: str
    chat_id: str
    message: str

class ChatResponse(BaseModel):
    success: bool
    message: str
    memory_detected: Optional[dict] = None
    user_id: Optional[str] = None
    reply: Optional[str] = None
    display_name: Optional[str] = None
    chat_title: Optional[str] = None

# ── Helper ─────────────────────────────────────────────────────────────────────

def resolve_display_name(user) -> str:
    if user.name:
        return user.name
    if user.nickname:
        return user.nickname
    if user.email:
        return user.email.split("@")[0].capitalize()
    if user.wallet_address:
        return f"{user.wallet_address[:6]}...{user.wallet_address[-4:]}"
    return "Pundit"

def run_background_memory(user_id: str, message: str):
    """Extracts structured memory (name, club, prediction etc) and persists to Postgres."""
    memory = extract_memory(message)
    if memory:
        if memory["type"] in ["name", "nickname", "favorite_club", "favorite_player", "supported_country"]:
            update_profile(user_id, memory["type"], memory["value"])
        elif memory["type"] == "prediction":
            add_prediction(user_id, memory["value"])
        elif memory["type"] == "opinion":
            add_opinion(user_id, memory["value"])

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def home():
    return {"success": True, "message": "Welcome to Trigo-Ai API!"}


@app.get("/health")
def health_check():
    return {"success": True, "status": "API is healthy and running!"}


@app.post("/chat/new")
def create_chat(user_id: str):
    chat_id = create_chat_session(user_id)
    if not chat_id:
        return {"success": False, "message": "User not found"}
    return {"success": True, "chat_id": chat_id}


@app.post("/register/email")
def register_email(request: EmailRegisterRequest):
    existing = get_user_by_email(request.email)
    if existing:
        return {
            "success": True,
            "user_id": existing.user_id,
            "is_new": False,
            "name_required": existing.name is None,
            "message": "Already registered"
        }
    user = create_email_profile(request.email)
    return {
        "success": True,
        "user_id": user.user_id,
        "is_new": True,
        "name_required": True,
        "message": "Registered successfully"
    }


@app.post("/register/wallet")
def register_wallet(request: WalletRegisterRequest):
    existing = get_user_by_wallet_address(request.wallet_address)
    if existing:
        return {
            "success": True,
            "user_id": existing.user_id,
            "is_new": False,
            "name_required": existing.name is None,
            "message": "Already registered"
        }
    user = create_wallet_profile(request.wallet_address)
    return {
        "success": True,
        "user_id": user.user_id,
        "is_new": True,
        "name_required": True,
        "message": "Registered successfully"
    }


@app.post("/profile/setup")
def profile_setup(request: ProfileSetupRequest):
    profile = get_profile(request.user_id)
    if not profile:
        return {"success": False, "message": "User not found"}

    update_profile(request.user_id, "name", request.name.strip())
    if request.nickname:
        update_profile(request.user_id, "nickname", request.nickname.strip())

    display_name = request.nickname or request.name
    return {
        "success": True,
        "display_name": display_name,
        "message": f"Welcome, {display_name}!"
    }


@app.get("/profile/{user_id}")
def get_user_profile(user_id: str):
    user = get_profile(user_id)
    if not user:
        return {"success": False, "message": "User not found"}
    return {
        "success": True,
        "display_name": resolve_display_name(user),
        "profile": user
    }


@app.get("/chat/sessions/{user_id}")
def get_chat_sessions(user_id: str):
    sessions = get_chat_sessions_summary(user_id)
    if sessions is None:
        return {"success": False, "message": "User not found"}
    return {"success": True, "sessions": sessions}


@app.get("/chat/history/{user_id}/{chat_id}")
def get_chat_history(user_id: str, chat_id: str):
    result = get_single_chat_history(user_id, chat_id)
    if result is None:
        return {"success": False, "message": "Chat session not found"}
    return {
        "success": True,
        "chat_id": chat_id,
        "title": result["title"],
        "messages": result["messages"]
    }


@app.delete("/chat/history/{user_id}")
def delete_chat_history(user_id: str):
    success = clear_chat_history(user_id)
    if not success:
        return {"success": False, "message": "User not found"}
    return {"success": True, "message": "Chat history cleared"}


@app.delete("/chat/session/{user_id}/{chat_id}")
def delete_chat_session_route(user_id: str, chat_id: str):
    success = delete_chat_session(user_id, chat_id)
    if not success:
        return {"success": False, "message": "Chat session not found"}
    return {"success": True, "message": "Chat deleted"}


@app.post("/chat", response_model=ChatResponse)
def chat(chat_request: ChatRequest):
    user = get_profile(chat_request.user_id)

    if not user:
        return ChatResponse(
            success=False,
            message="User not found. Please register first.",
        )

    session = next(
        (s for s in user.chat_sessions if s.chat_id == chat_request.chat_id),
        None
    )
    is_first_message = session is not None and len(session.messages) == 0

    chat_history = []
    if session and session.messages:
        for msg in session.messages[-20:]:
            if msg.role in ("user", "assistant") and msg.content:
                chat_history.append({"role": msg.role, "content": msg.content})

    reply = get_ai_reply(chat_request.message, user, chat_history=chat_history)

    add_chat_messages_batch(
        chat_request.user_id,
        chat_request.chat_id,
        chat_request.message,
        reply,
    )

    updated_user = get_profile(chat_request.user_id)
    display_name = resolve_display_name(updated_user) if updated_user else None

    chat_title = None
    if is_first_message:
        chat_title = generate_chat_title(chat_request.message)
        if chat_title:
            for s in user.chat_sessions:
                if s.chat_id == chat_request.chat_id:
                    s.title = chat_title
                    break
            from services.memory_service import _persist
            _persist(user)

    threading.Thread(
        target=run_background_memory,
        args=(chat_request.user_id, chat_request.message),
        daemon=True
    ).start()

    return ChatResponse(
        success=True,
        message="Reply generated.",
        memory_detected=None,
        user_id=chat_request.user_id,
        reply=reply,
        display_name=display_name,
        chat_title=chat_title,
    )


@app.post("/chat/stream")
async def chat_stream(chat_request: ChatRequest, request: Request):
    user = get_profile(chat_request.user_id)

    if not user:
        async def err():
            yield "User not found. Please register first."
        return StreamingResponse(err(), media_type="text/plain")

    session = next(
        (s for s in user.chat_sessions if s.chat_id == chat_request.chat_id),
        None
    )
    is_first_message = session is not None and len(session.messages) == 0

    chat_history = []
    if session and session.messages:
        for msg in session.messages[-20:]:
            if msg.role in ("user", "assistant") and msg.content:
                chat_history.append({"role": msg.role, "content": msg.content})

    async def event_generator():
        full_reply = ""
        aborted = False
        try:
            for chunk in stream_ai_reply(chat_request.message, user, chat_history=chat_history):
                if await request.is_disconnected():
                    aborted = True
                    break
                full_reply += chunk
                yield chunk
        finally:
            if full_reply and not aborted:
                add_chat_messages_batch(
                    chat_request.user_id,
                    chat_request.chat_id,
                    chat_request.message,
                    full_reply,
                )

                if is_first_message:
                    chat_title = generate_chat_title(chat_request.message)
                    if chat_title:
                        for s in user.chat_sessions:
                            if s.chat_id == chat_request.chat_id:
                                s.title = chat_title
                                break
                        from services.memory_service import _persist
                        _persist(user)

                threading.Thread(
                    target=run_background_memory,
                    args=(chat_request.user_id, chat_request.message),
                    daemon=True
                ).start()

    return StreamingResponse(event_generator(), media_type="text/plain")