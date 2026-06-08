# This is a temporary implementation of the MemoryService. Walrus will be used here later on.
from uuid import uuid4
from schemas.memory import UserMemory

MEMORY_DB = {} # Temporary memory database

EMAIL_INDEX = {} # Temporary email index for quick lookup
WALLET_INDEX = {} # Temporary wallet index for quick lookup

# email-based profile creation
def create_email_profile(email: str) -> UserMemory:
    user_id = str(uuid4())
    profile = UserMemory(
        user_id=user_id,
        user_type="email",
        email=email
    )
    MEMORY_DB[user_id] = profile
    EMAIL_INDEX[email] = user_id

    return profile

# wallet-based profile creation
def create_wallet_profile(wallet_address: str) -> UserMemory:
    user_id = str(uuid4())
    profile = UserMemory(
        user_id=user_id,
        user_type="wallet",
        wallet_address=wallet_address
    )
    MEMORY_DB[user_id] = profile
    WALLET_INDEX[wallet_address] = user_id

    return profile

#get profile by user_id
def get_profile(user_id: str) -> UserMemory | None:
    return MEMORY_DB.get(user_id)

# get user by email
def get_user_by_email(email: str) -> UserMemory | None:
    user_id = EMAIL_INDEX.get(email)
    if user_id:
        return MEMORY_DB.get(user_id)
    return None

# get user by wallet address
def get_user_by_wallet_address(wallet_address: str) -> UserMemory | None:
    user_id = WALLET_INDEX.get(wallet_address)
    if user_id:
        return MEMORY_DB.get(user_id)
    return None

# update user profile
def update_profile(User_id: str, field: str, value: str) -> UserMemory | None:
    profile = MEMORY_DB.get(User_id)
    if profile and hasattr(profile, field):
        setattr(profile, field, value)
        return profile
    return None

# add prediction to user memory
def add_prediction(user_id: str, prediction: str) -> UserMemory | None:
    profile = MEMORY_DB.get(user_id)
    if profile:
        profile.predictions.append(prediction)
        return profile
    return None

# add opinion to user memory
def add_opinion(user_id: str, opinion: str) -> UserMemory | None:
    profile = MEMORY_DB.get(user_id)
    if profile:
        profile.opinions.append(opinion)
        return profile
    return None