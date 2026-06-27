import "dotenv/config";

import express from "express";
import type { Request, Response, NextFunction } from "express";
import { MemWal } from "@mysten-incubation/memwal";

const PORT = parseInt(process.env.BRIDGE_PORT ?? "4100");
const PRIVATE_KEY = process.env.MEMWAL_PRIVATE_KEY ?? "";
const ACCOUNT_ID = process.env.MEMWAL_ACCOUNT_ID ?? "";
const RELAYER_URL = process.env.MEMWAL_RELAYER_URL ?? "";

function checkEnv() {
  const missing = [];
  if (!PRIVATE_KEY) missing.push("MEMWAL_PRIVATE_KEY");
  if (!ACCOUNT_ID) missing.push("MEMWAL_ACCOUNT_ID");
  if (!RELAYER_URL) missing.push("MEMWAL_RELAYER_URL");
  if (missing.length) {
    console.error(
      `[memwal-bridge] Missing required env vars: ${missing.join(", ")}`,
    );
    process.exit(1);
  }
}

const clientCache = new Map<string, MemWal>();

function getClient(namespace: string): MemWal {
  if (!clientCache.has(namespace)) {
    const client = MemWal.create({
      key: PRIVATE_KEY,
      accountId: ACCOUNT_ID,
      serverUrl: RELAYER_URL,
      namespace,
    });
    clientCache.set(namespace, client);
  }
  return clientCache.get(namespace)!;
}

const app = express();
app.use(express.json());

app.use((req: Request, _res: Response, next: NextFunction) => {
  console.log(`[memwal-bridge] ${req.method} ${req.path}`);
  next();
});

app.get("/health", (_req: Request, res: Response) => {
  res.json({
    status: "ok",
    accountId: ACCOUNT_ID,
    relayerUrl: RELAYER_URL,
    timestamp: new Date().toISOString(),
  });
});

app.post("/remember", async (req: Request, res: Response) => {
  const { namespace, text } = req.body as { namespace?: string; text?: string };

  if (!namespace || !text) {
    res
      .status(400)
      .json({ success: false, error: "namespace and text are required" });
    return;
  }

  try {
    const client = getClient(namespace);
    const job = await client.remember(text);
    await client.waitForRememberJob(job.job_id);
    console.log(
      `[memwal-bridge] remembered for ns=${namespace}, job=${job.job_id}`,
    );
    res.json({ success: true, job_id: job.job_id });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[memwal-bridge] remember error: ${msg}`);
    res.status(500).json({ success: false, error: msg });
  }
});

app.post("/recall", async (req: Request, res: Response) => {
  const { namespace, query } = req.body as {
    namespace?: string;
    query?: string;
  };

  if (!namespace || !query) {
    res.status(400).json({
      success: false,
      memories: [],
      error: "namespace and query are required",
    });
    return;
  }

  try {
    const client = getClient(namespace);
    console.log(
      `[memwal-bridge] calling recall for ns=${namespace}, query="${query}"`,
    );

    const raw = await client.recall({ query, topK: 5, maxDistance: 0.7 });

    console.log(
      `[memwal-bridge] raw recall response:`,
      JSON.stringify(raw, null, 2),
    );

    let memories: string[] = [];
    if (Array.isArray(raw)) {
      memories = raw.map((r: any) => r.text ?? r).filter(Boolean);
    } else if (raw && typeof raw === "object") {
      const arr =
        (raw as any).results ??
        (raw as any).memories ??
        (raw as any).items ??
        (raw as any).data ??
        [];
      memories = arr
        .map((r: any) => r.text ?? r.content ?? r)
        .filter((x: any) => typeof x === "string");
    }

    console.log(
      `[memwal-bridge] recalled ${memories.length} memories for ns=${namespace}`,
    );
    res.json({ success: true, memories });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const stack = err instanceof Error ? err.stack : "";
    console.error(`[memwal-bridge] recall error: ${msg}`);
    console.error(`[memwal-bridge] recall stack: ${stack}`);
    res.status(500).json({ success: false, memories: [], error: msg });
  }
});

app.post("/restore", async (req: Request, res: Response) => {
  const { namespace } = req.body as { namespace?: string };

  if (!namespace) {
    res
      .status(400)
      .json({ success: false, memories: [], error: "namespace is required" });
    return;
  }

  try {
    const client = getClient(namespace);
    const raw = await client.restore(namespace);
    console.log(
      `[memwal-bridge] raw restore response:`,
      JSON.stringify(raw, null, 2),
    );

    let memories: string[] = [];
    if (Array.isArray(raw)) {
      memories = raw.map((r: any) => r.text ?? r).filter(Boolean);
    } else if (raw && typeof raw === "object") {
      const arr =
        (raw as any).results ??
        (raw as any).memories ??
        (raw as any).items ??
        (raw as any).data ??
        [];
      memories = arr
        .map((r: any) => r.text ?? r.content ?? r)
        .filter((x: any) => typeof x === "string");
    }

    console.log(
      `[memwal-bridge] restored ${memories.length} memories for ns=${namespace}`,
    );
    res.json({ success: true, memories });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[memwal-bridge] restore error: ${msg}`);
    res.status(500).json({ success: false, memories: [], error: msg });
  }
});

app.use((_req: Request, res: Response) => {
  res.status(404).json({ error: "not found" });
});

checkEnv();

app.listen(PORT, () => {
  console.log(`[memwal-bridge] running on http://localhost:${PORT}`);
  console.log(`[memwal-bridge] account: ${ACCOUNT_ID}`);
  console.log(`[memwal-bridge] relayer: ${RELAYER_URL}`);
  console.log(
    `[memwal-bridge] endpoints: GET /health  POST /remember  POST /recall  POST /restore`,
  );
});
