from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime

class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ChatSession(BaseModel):
    chat_id: str
    title: Optional[str] = "New Chat"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    messages: List[ChatMessage] = Field(default_factory=list)

class UserMemory(BaseModel):
    user_id: str
    user_type: Literal["email", "wallet"]
    email: Optional[EmailStr] = None
    wallet_address: Optional[str] = None
    name: Optional[str] = None
    nickname: Optional[str] = None
    favorite_club: Optional[str] = None
    favorite_player: Optional[str] = None
    supported_country: Optional[str] = None
    predictions: List[str] = Field(default_factory=list)
    opinions: List[str] = Field(default_factory=list)
    # chat_history: List[ChatMessage] = Field(default_factory=list)
    chat_sessions: List[ChatSession] = Field(default_factory=list)
    