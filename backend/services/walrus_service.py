# backend/services/walrus_service.py
import json
import os
from walrus import WalrusClient
from schemas.memory import UserMemory

# Defaults are the official Walrus testnet endpoints (free public publisher).
# Mainnet publishers require WAL payment — override via env vars when ready.
WALRUS_PUBLISHER_URL = os.getenv("WALRUS_PUBLISHER_URL", "https://publisher.walrus-testnet.walrus.space")
WALRUS_AGGREGATOR_URL = os.getenv("WALRUS_AGGREGATOR_URL", "https://aggregator.walrus-testnet.walrus.space")

client = WalrusClient(
    publisher_base_url=WALRUS_PUBLISHER_URL,
    aggregator_base_url=WALRUS_AGGREGATOR_URL
)


def save_memory_to_walrus(profile: UserMemory) -> str | None:
    """
    Serialise UserMemory to JSON and upload to Walrus.
    Returns the blob_id string or None if it fails.
    """
    try:
        data = profile.model_dump()
        blob_bytes = json.dumps(data).encode("utf-8")

        response = client.put_blob(
            data=blob_bytes,
            epochs=10,       # store for 10 epochs (~10 days on testnet)
            deletable=True   # allow updates
        )

        # extract blob_id from response
        if isinstance(response, dict):
            blob_id = (
                response.get("newlyCreated", {}).get("blobObject", {}).get("blobId")
                or response.get("alreadyCertified", {}).get("blobId")
            )
            return blob_id

        return None

    except Exception as e:
        print(f"[Walrus] save error: {e}")
        return None


def load_memory_from_walrus(blob_id: str) -> UserMemory | None:
    """
    Fetch a blob from Walrus by blob_id and deserialise into UserMemory.
    Returns UserMemory or None if it fails.
    """
    try:
        blob_bytes = client.get_blob(blob_id)
        data = json.loads(blob_bytes.decode("utf-8"))
        return UserMemory(**data)

    except Exception as e:
        print(f"[Walrus] load error: {e}")
        return None