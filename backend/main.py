from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from services.ai_service import get_ai_reply, generate_chat_title
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
    add_chat_message,
    clear_chat_history,
    create_chat_session,
)

app = FastAPI(
    title="Trigo-Ai",
    description="AI Football Companion with Walrus Memory",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # update to your frontend domain after deployment
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
    return {
        "success": True,
        "chat_id": chat_id
    }


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
    user = get_profile(user_id)
    if not user:
        return {"success": False, "message": "User not found"}
    sessions = [
        {
            "chat_id": s.chat_id,
            "title": s.title,
            "created_at": s.created_at,
            "message_count": len(s.messages)
        }
        for s in user.chat_sessions
    ]
    return {"success": True, "sessions": sessions}


@app.get("/chat/history/{user_id}/{chat_id}")
def get_chat_history(user_id: str, chat_id: str):
    user = get_profile(user_id)
    if not user:
        return {"success": False, "message": "User not found"}
    session = next(
        (s for s in user.chat_sessions if s.chat_id == chat_id), None
    )
    if not session:
        return {"success": False, "message": "Chat session not found"}
    return {
        "success": True,
        "chat_id": chat_id,
        "title": session.title,
        "messages": session.messages
    }


@app.delete("/chat/history/{user_id}")
def delete_chat_history(user_id: str):
    success = clear_chat_history(user_id)
    if not success:
        return {"success": False, "message": "User not found"}
    return {"success": True, "message": "Chat history cleared"}


@app.post("/chat", response_model=ChatResponse)
def chat(chat_request: ChatRequest):
    user = get_profile(chat_request.user_id)

    if not user:
        return ChatResponse(
            success=False,
            message="User not found. Please register first.",
        )

    # check if this is the first message in the session
    session = next(
        (s for s in user.chat_sessions if s.chat_id == chat_request.chat_id),
        None
    )
    is_first_message = session is not None and len(session.messages) == 0

    # extract and store memory
    memory = extract_memory(chat_request.message)
    if memory:
        if memory["type"] in ["name", "nickname", "favorite_club", "favorite_player", "supported_country"]:
            update_profile(chat_request.user_id, memory["type"], memory["value"])
        elif memory["type"] == "prediction":
            add_prediction(chat_request.user_id, memory["value"])
        elif memory["type"] == "opinion":
            add_opinion(chat_request.user_id, memory["value"])

    # get AI reply
    reply = get_ai_reply(chat_request.message, user)

    # save chat messages
    add_chat_message(chat_request.user_id, chat_request.chat_id, "user", chat_request.message)
    add_chat_message(chat_request.user_id, chat_request.chat_id, "assistant", reply)

    # generate title only on first message
    chat_title = generate_chat_title(chat_request.message) if is_first_message else None

    # update session title if first message
    if is_first_message and chat_title:
        user_updated = get_profile(chat_request.user_id)
        if user_updated:
            for s in user_updated.chat_sessions:
                if s.chat_id == chat_request.chat_id:
                    s.title = chat_title
                    break
            from services.memory_service import _persist
            _persist(user_updated)

    # refresh display name in case memory updated it
    updated_user = get_profile(chat_request.user_id)
    display_name = resolve_display_name(updated_user) if updated_user else None

    return ChatResponse(
        success=True,
        message="Memory updated!" if memory else "No memory extracted.",
        memory_detected=memory,
        user_id=chat_request.user_id,
        reply=reply,
        display_name=display_name,
        chat_title=chat_title,
    )