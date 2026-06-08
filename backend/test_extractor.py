# test extractor
from services.memory_extractor import extract_memory

# Test cases
test_messages = [
    "My name is John Doe",
    "You can call me Johnny",
    "My favorite club is FC Barcelona",
    "My favorite player is Lionel Messi",
    "I predict that Spain will win the match",
    "In my opinion, Brazil is the best team"
]

for msg in test_messages:
    result = extract_memory(msg)
    print(f"Message: {msg}")
    print(f"Extracted Memory: {result}")
    print("-" * 50)