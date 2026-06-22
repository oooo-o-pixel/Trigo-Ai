# Test memory service
from services.memory_service import (
    create_email_profile,
    update_profile,
    add_prediction,
    add_opinion,
    get_user_by_email
)

# Create a new user
profile = create_email_profile("test@example.com")

print("Created New profile:", profile)
print("-" * 50)

# Update user profile
updated_profile = update_profile(
    profile.user_id,
    "name",
    "John Doe"
)
updated_profile = update_profile(
    profile.user_id,
    "nickname",
    "Johnny"
)
updated_profile = update_profile(
    profile.user_id,
    "favorite_club",
    "FC Barcelona"
)
updated_profile = update_profile(
    profile.user_id,
    "favorite_player",
    "Lionel Messi"
)
updated_profile = update_profile(
    profile.user_id,
    "supported_country",
    "Spain"
)

# Add a prediction
add_prediction(profile.user_id, "Barcelona will win the league this season.")

# Add an opinion
add_opinion(profile.user_id, "I think Barcelona is the best team in the world.")

# Retrieve user by email
retrieved_profile = get_user_by_email("test@example.com")

print("Updated Profile:", updated_profile)
print("Retrieved Profile:", retrieved_profile)