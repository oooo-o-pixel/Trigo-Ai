from  fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from services.memory_extractor import extract_memory
from services.memory_service import (
    create_email_profile, 
    create_wallet_profile,
    update_profile, 
    add_prediction, 
    add_opinion, 
    get_user_by_email,
    get_user_by_wallet_address,
)

app = FastAPI(
    title="Trigo-Ai",
    description="AI Football Companion with WalMemory",
    version="1.0.0",
)

#Request and Response Models

class ChatRequest(BaseModel):
    wallet_address: Optional[str] = None
    email: Optional[str] = None
    message: str

class ChatResponse(BaseModel):
    success: bool
    message: str
    memory_detected: Optional[dict] = None
    user_id: Optional[str] = None
    reply: Optional[str] = None

# Root route
@app.get("/")
def home():
    return {
        "success": True,
        "message": "Welcome to Trigo-Ai API!"
    }

# health check route
@app.get("/health")
def health_check():
    return {
        "success": True,
        "status": "API is healthy and running!"
    }

# Chat route
@app.post("/chat", response_model=ChatResponse)
def chat(chat_request: ChatRequest):
    user = get_user_by_email(chat_request.email) if chat_request.email else None
    if not user and chat_request.wallet_address:
        user = get_user_by_wallet_address(chat_request.wallet_address)

    if not user:
        if chat_request.email:
            user = create_email_profile(chat_request.email)
        elif chat_request.wallet_address:
            user = create_wallet_profile(chat_request.wallet_address)

    user_id = user.user_id if user else None

    # Extract memory from the message
    memory = extract_memory(chat_request.message)

    if memory and user_id:
        if memory["type"] in ["name", "nickname", "favorite_club", "favorite_player", "supported_country"]:
            update_profile(user_id, memory["type"], memory["value"])
        elif memory["type"] == "prediction":
            add_prediction(user_id, memory["value"])
        elif memory["type"] == "opinion":
            add_opinion(user_id, memory["value"])

    # reply
    reply = "Alright it has been updated in the memory!" if memory else "I didn't quite catch that. Can you tell me more?"

    
    return ChatResponse(
        success=True,
        message="Memory updated successfully!" if memory else "No memory extracted from the message.",
        memory_detected=memory,
        user_id=user_id,
        reply=reply
    )