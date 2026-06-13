# Trigo-Ai

Your football AI companion that remembers. A FastAPI backend that chats about football (World Cup 2026 pundit energy), extracts personal memories from your messages — name, favourite club, predictions, hot takes — and persists them as blobs on [Walrus](https://www.walrus.xyz/), the decentralized storage network on Sui.

## How it works

```
backend/
├── main.py                      # FastAPI app and routes
├── requirements.txt
├── schemas/memory.py            # UserMemory, ChatSession, ChatMessage models
└── services/
    ├── ai_service.py            # OpenAI chat replies + chat titles
    ├── memory_extractor.py      # GPT-based memory extraction from messages
    ├── memory_service.py        # profile CRUD, local cache, Walrus persistence
    ├── walrus_service.py        # Walrus blob upload/download
    └── football_service.py      # match context for the AI
```

Every profile change is serialized to JSON and uploaded to Walrus as a blob. Blob IDs are tracked in a local `memory_index.json`, with an in-memory cache as the fast path and fallback. Profiles survive server restarts — they're fetched back from Walrus by blob ID.

## Setup

Requires Python 3.10+.

```bash
git clone https://github.com/oooo-o-pixel/Trigo-Ai.git
cd Trigo-Ai
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

> **Dependency note:** the Walrus client is the `walrus-python` package (already in `requirements.txt`). Do **not** `pip install walrus` — that's an unrelated Redis library.

### Environment variables (optional)

Create `backend/.env`:

```bash
# Enables AI replies and GPT memory extraction. Without it the API still
# runs — /chat returns a placeholder reply and extraction is skipped.
OPENAI_API_KEY=sk-...

# Walrus endpoints. Defaults are the official free testnet publisher and
# aggregator — override these when moving to mainnet (mainnet publishing
# requires WAL tokens).
WALRUS_PUBLISHER_URL=https://publisher.walrus-testnet.walrus.space
WALRUS_AGGREGATOR_URL=https://aggregator.walrus-testnet.walrus.space
```

### Run the server

```bash
cd backend
../.venv/bin/uvicorn main:app --port 8000
```

Watch the logs for `[Memory] saved to Walrus: <blob_id>` — that's a successful upload. If Walrus is unreachable you'll see `[Memory] Walrus unavailable — using local cache only` instead, and data only lives until the process exits.

## Try it

```bash
# health check
curl http://127.0.0.1:8000/health

# register (returns a user_id — Walrus upload happens here, takes a few seconds)
UID=$(curl -s -X POST http://127.0.0.1:8000/register/email \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@test.com"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['user_id'])")

# set your name
curl -s -X POST http://127.0.0.1:8000/profile/setup \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$UID\",\"name\":\"Shaibu\"}"

# start a chat session and send a message
CHAT_ID=$(curl -s -X POST "http://127.0.0.1:8000/chat/new?user_id=$UID" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['chat_id'])")
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$UID\",\"chat_id\":\"$CHAT_ID\",\"message\":\"I support Arsenal\"}"

# the proof: restart the server (Ctrl+C, run uvicorn again), then —
curl -s http://127.0.0.1:8000/profile/$UID
# your profile comes back from Walrus, not local memory
```

### API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/register/email` | Register with email → `user_id` |
| POST | `/register/wallet` | Register with wallet address → `user_id` |
| POST | `/profile/setup` | Set name/nickname |
| GET | `/profile/{user_id}` | Fetch full profile (Walrus-backed) |
| POST | `/chat/new?user_id=` | Create a chat session → `chat_id` |
| POST | `/chat` | Send a message, get AI reply, memories extracted |
| GET | `/chat/sessions/{user_id}` | List chat sessions |
| GET | `/chat/history/{user_id}/{chat_id}` | Get messages in a session |
| DELETE | `/chat/history/{user_id}` | Clear all chat history |

## Uploading files to Walrus

The app uploads profiles automatically, but you can upload any file to Walrus yourself using the same client:

```python
from walrus import WalrusClient

client = WalrusClient(
    publisher_base_url="https://publisher.walrus-testnet.walrus.space",
    aggregator_base_url="https://aggregator.walrus-testnet.walrus.space",
)

with open("myfile.txt", "rb") as f:
    resp = client.put_blob(data=f.read(), epochs=10, deletable=True)

blob_id = (resp.get("newlyCreated", {}).get("blobObject", {}).get("blobId")
           or resp.get("alreadyCertified", {}).get("blobId"))
print("blob_id:", blob_id)

# read it back
print(client.get_blob(blob_id).decode())
```

Or with plain `curl` against the HTTP API:

```bash
# upload (PUT the raw bytes to the publisher)
curl -X PUT "https://publisher.walrus-testnet.walrus.space/v1/blobs?epochs=10&deletable=true" \
  --data-binary @myfile.txt

# download (GET from any aggregator by blob ID)
curl "https://aggregator.walrus-testnet.walrus.space/v1/blobs/<BLOB_ID>"
```

Things to know:

- **Blobs expire.** `epochs=10` keeps a blob for 10 storage epochs (~10 days on testnet). Re-upload or extend before expiry if you need it longer.
- **Blobs are public.** Anyone with the blob ID can read it — don't upload secrets or PII unencrypted.
- **Uploading the same bytes twice** returns `alreadyCertified` with the existing blob ID instead of `newlyCreated` — content is deduplicated network-wide.
- **Testnet is free; mainnet costs WAL.** The defaults here are testnet. For production, run your own publisher or use a paid one, and set the `WALRUS_*` env vars.

## License

MIT — see [LICENSE](LICENSE).
