from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal

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

    