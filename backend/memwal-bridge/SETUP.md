# MemWal Bridge — Setup Guide (Windows)

This is a small Node.js server that connects your Python FastAPI app to MemWal.
Your Python app calls it like any other API — plain HTTP requests on localhost.

---

## Step 1 — Check Node.js is installed

Open PowerShell and run:

```powershell
node --version
npm --version
```

Both should print a version number. If not, download Node.js from https://nodejs.org (LTS version).

---

## Step 2 — Put the bridge folder in your project

Copy the `memwal-bridge/` folder into your project root so it sits next to your Python files:

```
your-project/
├── ai_service.py
├── football_service.py
├── memory_service.py
├── memwal-bridge/          ← this folder
│   ├── index.ts
│   ├── package.json
│   ├── tsconfig.json
│   ├── .env.example
│   └── SETUP.md
└── .env
```

---

## Step 3 — Create the .env file for the bridge

Inside `memwal-bridge/`, copy `.env` to `.env(your .env)`:

```powershell
cd memwal-bridge
copy .env .env(your .env)
```

Now open `.env` in any text editor and fill in your values from the dashboard at
https://memory.walrus.xyz/dashboard:

```
MEMWAL_PRIVATE_KEY=<your delegate key private key>
MEMWAL_ACCOUNT_ID=<your MemWalAccount ID>
MEMWAL_RELAYER_URL=https://relayer.memory.walrus.xyz
BRIDGE_PORT=4100
```

**Where to find these in the dashboard:**

- `MEMWAL_ACCOUNT_ID` → Accounts section → copy the account ID
- `MEMWAL_PRIVATE_KEY` → Delegate Keys section → the private key (hex string)
- `MEMWAL_RELAYER_URL` → Whatever URL the dashboard shows (usually `https://relayer.memwal.ai`)

> ⚠️ Never commit `.env` to git. Add it to `.gitignore`.

---

## Step 4 — Install dependencies

In PowerShell, inside the `memwal-bridge/` folder:

```powershell
npm install
```

This installs `@mysten-incubation/memwal`, `express`, `typescript`, and `ts-node`.
It will take about 30-60 seconds the first time.

---

## Step 5 — Test it (dev mode, no build needed)

```powershell
npx ts-node index.ts
```

You should see:

```
[memwal-bridge] running on http://localhost:4100
[memwal-bridge] account: your-account-id
[memwal-bridge] relayer: https://relayer.memory.walrus.xyz
[memwal-bridge] endpoints: GET /health  POST /remember  POST /recall  POST /restore
```

---

## Step 6 — Verify it works (in a NEW PowerShell window)

**Health check:**

```powershell
Invoke-RestMethod -Uri "http://localhost:4100/health" | ConvertTo-Json
```

Expected response:

```json
{
  "status": "ok",
  "accountId": "your-account-id",
  "relayerUrl": "https://relayer.memwal.ai",
  "timestamp": "2026-06-26T..."
}
```

**Test remember:**

```powershell
Invoke-RestMethod -Uri "http://localhost:4100/remember" -Method POST `
  -ContentType "application/json" `
  -Body '{"namespace":"test-user","text":"I think Brazil will win the 2026 World Cup."}'
```

Expected:

```json
{ "success": true, "job_id": "..." }
```

**Test recall:**

```powershell
Invoke-RestMethod -Uri "http://localhost:4100/recall" -Method POST `
  -ContentType "application/json" `
  -Body '{"namespace":"test-user","query":"what team did the user predict to win?"}'
```

Expected:

```json
{ "success": true, "memories": ["I think Brazil will win the 2026 World Cup."] }
```

If all three return success, the sidecar is fully working. ✅

---

## Step 7 — Add MEMWAL_BRIDGE_URL to your main .env

In your project root `.env` (the Python one), add:

```
MEMWAL_BRIDGE_URL=http://localhost:4100
```

---

## Running both services together

You need **two terminals** open at the same time:

**Terminal 1 — MemWal bridge:**

```powershell
cd memwal-bridge
npx ts-node index.ts
```

**Terminal 2 — Your FastAPI app:**

```powershell
cd ..   (back to project root)
uvicorn main:app --reload
```

Both must be running for the full app to work.

---

## Troubleshooting

| Error                                            | Fix                                                       |
| ------------------------------------------------ | --------------------------------------------------------- |
| `ts-node: command not found`                     | Run `npm install` inside `memwal-bridge/` first           |
| `Cannot find module '@mysten-incubation/memwal'` | Run `npm install` inside `memwal-bridge/`                 |
| `Missing required env vars`                      | Check your `memwal-bridge/.env` has all three values      |
| `ECONNREFUSED` from Python                       | The bridge isn't running — start it in the first terminal |
| `500` from `/remember`                           | Check bridge terminal for the actual error message        |

---

## For deployment (production)

Build the TypeScript first, then run the compiled JS:

```powershell
npm run build
node dist/index.js
```

Or use `pm2` to keep both services running:

```powershell
npm install -g pm2
pm2 start "npx ts-node index.ts" --name memwal-bridge --cwd ./memwal-bridge
pm2 start "uvicorn main:app" --name fastapi-app
pm2 save
```
