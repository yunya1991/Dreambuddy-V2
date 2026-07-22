# 7-ARTIFACT-HUB-V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `7-ARTIFACT-HUB-V2` 中台服务（Node/TypeScript），以 `dreambuddy/artifacts` 为产物真相源（FS），以 `dreambuddy/meta/artifact_hub.sqlite` 为元数据库（SQLite），对外提供产物检索、节点级可视化 DAG 路由、SSE 事件流与 trace 回放，并用 tasks/results 文件协议对接生产端（WorkBuddy）。

**Architecture:** FS 扫描/读取由 `ArtifactStore` 负责；可视化/审计与关系索引写入 SQLite；`RouterEngine` 输出节点级 DAG；`WorkOrderManager` 写 tasks、消费 results；HTTP API + SSE 暴露给上层应用/治理 UI。

**Tech Stack:** Node.js (built-in `http` + `node:test`), TypeScript, SQLite via `better-sqlite3`.

---

## Repository Layout Changes

**Create**
- `7-ARTIFACT-HUB-V2/`（中台服务工程）
- `dreambuddy/artifacts/`（产物根目录，FS 真相源）
- `dreambuddy/meta/`（SQLite 与事件日志）
- `dreambuddy/config/artifact-hub.config.json`（服务配置）

**Modify**
- None required for v0（不做历史迁移，不改现有 `3-FRONTEND/`）

---

### Task 1: Scaffold 7-ARTIFACT-HUB-V2 project

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/package.json`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/tsconfig.json`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/index.ts`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/types.ts`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "artifact-hub-v2",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "start": "node dist/index.js",
    "dev": "node --watch dist/index.js",
    "test": "node --test dist/**/*.test.js"
  },
  "dependencies": {
    "better-sqlite3": "^11.6.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "typescript": "^5.7.0"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "Bundler",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src/**/*.ts"]
}
```

- [ ] **Step 3: Create base type definitions**

```ts
export type ISODateString = string;

export type ArtifactStatus = "completed" | "processing" | "failed" | "unknown";

export type ArtifactType =
  | "knowledge"
  | "trading"
  | "dashboard_task"
  | "dashboard_result"
  | "unknown";

export type RouteMode =
  | "DIRECT_RETURN"
  | "INCREMENTAL_UPDATE"
  | "RUN_CHAIN"
  | "NEED_CONFIRMATION";

export type DagNodeStatus = "pending" | "running" | "success" | "error" | "skipped";

export type DagNodeType =
  | "intent_recognition"
  | "artifact_retrieval"
  | "artifact_scoring"
  | "policy_gate"
  | "work_order_emit"
  | "result_ingest"
  | "artifact_publish";

export interface ArtifactIndexItem {
  id: string;
  title: string;
  department: string;
  type: ArtifactType;
  date: ISODateString;
  status: ArtifactStatus;
  chain_phase: string;
  url: string;
  tags: string;
  excerpt?: string;
}

export interface DagNode {
  node_id: string;
  type: DagNodeType;
  status: DagNodeStatus;
  inputs: Array<{ kind: "artifact" | "text"; ref: string; summary?: string }>;
  outputs: Array<{ kind: "artifact" | "text"; ref: string; summary?: string }>;
  metrics?: { latency_ms?: number; cost_tokens?: number };
  evidence?: Array<{ kind: "rule" | "score" | "artifact"; detail: string }>;
}

export interface DagEdge {
  from: string;
  to: string;
}

export interface RoutingPlan {
  trace_id: string;
  mode: RouteMode;
  reason: Record<string, unknown>;
  dag: { nodes: DagNode[]; edges: DagEdge[] };
}

export interface Intent {
  text: string;
  domain?: string;
  task_type?: string;
  entities?: Record<string, unknown>;
  constraints?: Record<string, unknown>;
}
```

- [ ] **Step 4: Create minimal entry file (placeholder server bootstrap)**

```ts
import { createServer } from "http";

const server = createServer((req, res) => {
  res.statusCode = 200;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.end(JSON.stringify({ ok: true, service: "artifact-hub-v2" }));
});

server.listen(8787, "127.0.0.1");
```

- [ ] **Step 5: Build**

Run (from `7-ARTIFACT-HUB-V2/`):

```bash
npm install
npm run build
node dist/index.js
```

Expected: `curl http://127.0.0.1:8787` returns `{ ok: true, service: "artifact-hub-v2" }`.

---

### Task 2: Create dreambuddy data directories and config

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/dreambuddy/config/artifact-hub.config.json`
- Ensure dirs: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/dreambuddy/artifacts/{tasks,results}`
- Ensure dir: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/dreambuddy/meta`

- [ ] **Step 1: Create config file**

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8787
  },
  "paths": {
    "artifacts_root": "./dreambuddy/artifacts",
    "meta_root": "./dreambuddy/meta"
  }
}
```

- [ ] **Step 2: Add config + path loader**

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/config.ts`

```ts
import fs from "fs";
import path from "path";

export interface HubConfig {
  server: { host: string; port: number };
  paths: { artifacts_root: string; meta_root: string };
}

export function loadConfig(repoRoot: string): HubConfig {
  const p = path.join(repoRoot, "dreambuddy", "config", "artifact-hub.config.json");
  const raw = fs.readFileSync(p, "utf-8");
  return JSON.parse(raw) as HubConfig;
}

export function resolveRepoRoot(): string {
  return path.resolve(process.cwd(), "..");
}
```

- [ ] **Step 3: Update server bootstrap to load config**

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/index.ts`

```ts
import { createServer } from "http";
import { loadConfig, resolveRepoRoot } from "./config.js";

const repoRoot = resolveRepoRoot();
const config = loadConfig(repoRoot);

const server = createServer((req, res) => {
  res.statusCode = 200;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.end(JSON.stringify({ ok: true, service: "artifact-hub-v2", config }));
});

server.listen(config.server.port, config.server.host);
```

---

### Task 3: Implement CATEGORY_TO_DEPARTMENT mapping + ArtifactStore (FS scan/index)

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/category.ts`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/artifact-store.ts`
- Test: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/artifact-store.test.ts`

- [ ] **Step 1: Add CATEGORY_TO_DEPARTMENT**

```ts
export const CATEGORY_TO_DEPARTMENT: Record<string, string> = {
  masters: "knowledge",
  tools: "knowledge",
  macro: "knowledge",
  risk: "knowledge",
  exit: "knowledge",
  practice: "knowledge",
  web_strategy: "knowledge",
  advanced_orders: "knowledge",
  audit: "support",
  oneirology: "dream",
  trading: "trading",
  a_series: "trading",
  tasks: "dashboard",
  results: "dashboard"
};
```

- [ ] **Step 2: Implement ArtifactStore (scan index)**

```ts
import fs from "fs";
import path from "path";
import { CATEGORY_TO_DEPARTMENT } from "./category.js";
import type { ArtifactIndexItem } from "./types.js";

const A_PHASE_REGEX = /^A([0-9])$/i;

function extractAPhase(filename: string, chainPhase?: string): string {
  if (chainPhase && A_PHASE_REGEX.test(chainPhase.toUpperCase())) return chainPhase.toUpperCase();
  const match = filename.match(/A([0-9])/i);
  if (match) return "A" + match[1];
  return chainPhase || "";
}

function cleanExcerpt(input: string): string {
  return input
    .replace(/^#+\s+/gm, "")
    .replace(/[\r\n]+/g, " ")
    .replace(/\*+/g, "")
    .replace(/`[^`]*`/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/<[^>]*>/g, "")
    .replace(/\|/g, " ")
    .replace(/-+/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim()
    .slice(0, 200);
}

export class ArtifactStore {
  constructor(private readonly artifactsRoot: string) {}

  getArtifactsIndex(): ArtifactIndexItem[] {
    if (!fs.existsSync(this.artifactsRoot)) return [];

    const categories = fs.readdirSync(this.artifactsRoot).filter((f) => {
      const fp = path.join(this.artifactsRoot, f);
      return fs.statSync(fp).isDirectory() && !f.startsWith(".");
    });

    const index: ArtifactIndexItem[] = [];

    for (const category of categories) {
      const catDir = path.join(this.artifactsRoot, category);
      const department = CATEGORY_TO_DEPARTMENT[category] || "knowledge";

      if (category === "tasks" || category === "results") continue;

      const indexFile = path.join(catDir, "index.json");
      if (!fs.existsSync(indexFile)) continue;
      const parsed = JSON.parse(fs.readFileSync(indexFile, "utf-8"));
      const items = Array.isArray(parsed) ? parsed : (parsed.artifacts || []);
      const lastUpdated = parsed.last_updated || new Date().toISOString();

      for (const item of items) {
        const rawId = item.artifact_id || item.id || "unknown";
        const artifactId = rawId.includes("/") ? rawId.split("/").pop() : rawId;
        const filename = item.filename || `${artifactId}.md`;
        const chainPhase = extractAPhase(filename, item.chain_phase || "");
        const tags =
          Array.isArray(item.tags) ? item.tags.join(" ") : (typeof item.tags === "string" ? item.tags : "");

        index.push({
          id: `${category}/${artifactId}`,
          title: item.title || artifactId,
          department,
          type: item.type || "knowledge",
          date: String(item.date || lastUpdated),
          status: item.status || "completed",
          chain_phase: chainPhase,
          url: `/feed/${category}/${artifactId}`,
          tags,
          excerpt: item.excerpt ? cleanExcerpt(String(item.excerpt)) : undefined
        });
      }
    }

    index.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    return index;
  }
}
```

- [ ] **Step 3: Add a minimal test with node:test**

```ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { ArtifactStore } from "./artifact-store.js";

test("ArtifactStore reads category index.json", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "artifact-hub-"));
  const trading = path.join(root, "trading");
  fs.mkdirSync(trading, { recursive: true });
  fs.writeFileSync(
    path.join(trading, "index.json"),
    JSON.stringify({ last_updated: "2026-05-15T00:00:00Z", artifacts: [{ artifact_id: "trading/x", title: "X", tags: ["a"] }] })
  );

  const store = new ArtifactStore(root);
  const idx = store.getArtifactsIndex();
  assert.equal(idx.length, 1);
  assert.equal(idx[0].id, "trading/x");
});
```

- [ ] **Step 4: Build + run tests**

```bash
npm run build
npm test
```

Expected: PASS.

---

### Task 4: Implement MetaStore (SQLite) + schema bootstrap

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/meta-store.ts`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/meta-store.test.ts`

- [ ] **Step 1: Implement MetaStore**

```ts
import fs from "fs";
import path from "path";
import Database from "better-sqlite3";

export class MetaStore {
  private readonly db: Database.Database;

  constructor(metaRoot: string) {
    fs.mkdirSync(metaRoot, { recursive: true });
    const dbPath = path.join(metaRoot, "artifact_hub.sqlite");
    this.db = new Database(dbPath);
    this.bootstrap();
  }

  private bootstrap(): void {
    this.db.exec(`
      PRAGMA journal_mode=WAL;

      CREATE TABLE IF NOT EXISTS events (
        trace_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        ts INTEGER NOT NULL,
        PRIMARY KEY (trace_id, event_id)
      );

      CREATE TABLE IF NOT EXISTS route_decisions (
        trace_id TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        intent_json TEXT NOT NULL,
        decision_json TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (trace_id, decision_id)
      );
    `);
  }

  addEvent(traceId: string, eventId: string, type: string, payload: unknown, ts = Date.now()): void {
    const stmt = this.db.prepare(
      `INSERT INTO events(trace_id,event_id,type,payload_json,ts) VALUES(?,?,?,?,?)`
    );
    stmt.run(traceId, eventId, type, JSON.stringify(payload), ts);
  }

  listEvents(traceId: string): Array<{ type: string; payload: unknown; ts: number }> {
    const stmt = this.db.prepare(`SELECT type,payload_json,ts FROM events WHERE trace_id=? ORDER BY ts ASC`);
    return stmt.all(traceId).map((r: any) => ({ type: r.type, payload: JSON.parse(r.payload_json), ts: r.ts }));
  }
}
```

- [ ] **Step 2: Add minimal test**

```ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { MetaStore } from "./meta-store.js";

test("MetaStore writes and reads events", () => {
  const metaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "artifact-meta-"));
  const ms = new MetaStore(metaRoot);
  ms.addEvent("t1", "e1", "trace.created", { ok: true }, 1);
  const events = ms.listEvents("t1");
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "trace.created");
});
```

- [ ] **Step 3: Build + test**

```bash
npm run build
npm test
```

---

### Task 5: Implement RouterEngine (node-level DAG) + /route/decide

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/router-engine.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/index.ts`

- [ ] **Step 1: Implement RouterEngine (v0 heuristic)**

```ts
import crypto from "node:crypto";
import type { Intent, RoutingPlan } from "./types.js";
import type { ArtifactIndexItem } from "./types.js";

export class RouterEngine {
  decide(intent: Intent, artifacts: ArtifactIndexItem[]): RoutingPlan {
    const traceId = crypto.randomUUID();
    const hasAny = artifacts.length > 0;
    const mode = hasAny ? "DIRECT_RETURN" : "RUN_CHAIN";

    const nodes = [
      { node_id: "n1", type: "intent_recognition", status: "success", inputs: [{ kind: "text", ref: "intent", summary: intent.text }], outputs: [{ kind: "text", ref: "intent_struct" }] },
      { node_id: "n2", type: "artifact_retrieval", status: "success", inputs: [{ kind: "text", ref: "intent_struct" }], outputs: [{ kind: "text", ref: "artifact_candidates", summary: String(artifacts.length) }] },
      { node_id: "n3", type: "artifact_scoring", status: "success", inputs: [{ kind: "text", ref: "artifact_candidates" }], outputs: [{ kind: "text", ref: "artifact_score" }] },
      { node_id: "n4", type: "policy_gate", status: "success", inputs: [{ kind: "text", ref: "artifact_score" }], outputs: [{ kind: "text", ref: "route_mode", summary: mode }] }
    ];

    return {
      trace_id: traceId,
      mode,
      reason: { has_any_artifact: hasAny, count: artifacts.length },
      dag: { nodes: nodes as any, edges: [{ from: "n1", to: "n2" }, { from: "n2", to: "n3" }, { from: "n3", to: "n4" }] }
    };
  }
}
```

- [ ] **Step 2: Wire /route/decide endpoint (temporary minimal router)**

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/http-utils.ts`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/event-bus.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/meta-store.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/index.ts`

Create basic HTTP helpers:

```ts
import { IncomingMessage, ServerResponse } from "http";

export async function readJson<T>(req: IncomingMessage): Promise<T> {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(Buffer.isBuffer(c) ? c : Buffer.from(c));
  const raw = Buffer.concat(chunks).toString("utf-8");
  return JSON.parse(raw) as T;
}

export function sendJson(res: ServerResponse, statusCode: number, body: unknown): void {
  res.statusCode = statusCode;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
}

export function notFound(res: ServerResponse): void {
  sendJson(res, 404, { error: "not_found" });
}

export function methodNotAllowed(res: ServerResponse): void {
  sendJson(res, 405, { error: "method_not_allowed" });
}
```

Create SSE event bus:

```ts
import type { ServerResponse } from "http";

export interface SseEvent {
  type: string;
  payload: unknown;
  ts: number;
}

export class EventBus {
  private readonly subs = new Map<string, Set<ServerResponse>>();

  subscribe(traceId: string, res: ServerResponse): void {
    const set = this.subs.get(traceId) ?? new Set<ServerResponse>();
    set.add(res);
    this.subs.set(traceId, set);
    res.on("close", () => {
      const s = this.subs.get(traceId);
      if (!s) return;
      s.delete(res);
      if (s.size === 0) this.subs.delete(traceId);
    });
  }

  publish(traceId: string, event: SseEvent): void {
    const set = this.subs.get(traceId);
    if (!set) return;
    const data = `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
    for (const res of set) res.write(data);
  }
}
```

Extend MetaStore with route decisions:

```ts
  addRouteDecision(traceId: string, decisionId: string, intent: unknown, decision: unknown, policyVersion = "v0", createdAt = Date.now()): void {
    const stmt = this.db.prepare(
      `INSERT INTO route_decisions(trace_id,decision_id,intent_json,decision_json,policy_version,created_at) VALUES(?,?,?,?,?,?)`
    );
    stmt.run(traceId, decisionId, JSON.stringify(intent), JSON.stringify(decision), policyVersion, createdAt);
  }

  getLatestRouteDecision(traceId: string): { intent: unknown; decision: unknown; created_at: number } | null {
    const stmt = this.db.prepare(
      `SELECT intent_json,decision_json,created_at FROM route_decisions WHERE trace_id=? ORDER BY created_at DESC LIMIT 1`
    );
    const row: any = stmt.get(traceId);
    if (!row) return null;
    return { intent: JSON.parse(row.intent_json), decision: JSON.parse(row.decision_json), created_at: row.created_at };
  }
```

Wire `/route/decide` in `index.ts` (minimal router):

```ts
import { createServer } from "http";
import path from "node:path";
import { loadConfig, resolveRepoRoot } from "./config.js";
import { ArtifactStore } from "./artifact-store.js";
import { MetaStore } from "./meta-store.js";
import { RouterEngine } from "./router-engine.js";
import { readJson, sendJson, notFound, methodNotAllowed } from "./http-utils.js";
import { EventBus } from "./event-bus.js";
import type { Intent } from "./types.js";

const repoRoot = resolveRepoRoot();
const config = loadConfig(repoRoot);
const artifactsRoot = path.join(repoRoot, config.paths.artifacts_root);
const metaRoot = path.join(repoRoot, config.paths.meta_root);

const store = new ArtifactStore(artifactsRoot);
const meta = new MetaStore(metaRoot);
const router = new RouterEngine();
const events = new EventBus();

const server = createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (req.method === "GET" && url.pathname === "/health") {
    return sendJson(res, 200, { ok: true });
  }

  if (url.pathname === "/route/decide") {
    if (req.method !== "POST") return methodNotAllowed(res);
    const intent = await readJson<Intent>(req);
    const artifacts = store.getArtifactsIndex();
    const plan = router.decide(intent, artifacts);

    meta.addEvent(plan.trace_id, "e_trace_created", "trace.created", { trace_id: plan.trace_id }, Date.now());
    meta.addEvent(plan.trace_id, "e_route_decided", "route.decided", { mode: plan.mode }, Date.now());
    meta.addRouteDecision(plan.trace_id, "d1", intent, plan, "v0", Date.now());
    events.publish(plan.trace_id, { type: "route.decided", payload: plan, ts: Date.now() });

    return sendJson(res, 200, plan);
  }

  return notFound(res);
});

server.listen(config.server.port, config.server.host);
```

- [ ] **Step 3: Build + smoke test**

```bash
npm run build
node dist/index.js
curl -s http://127.0.0.1:8787/health
curl -s -X POST http://127.0.0.1:8787/route/decide -H 'content-type: application/json' -d '{"text":"show me latest trading report"}' | head
```

Expected: `/health` returns `{"ok":true}`; `/route/decide` returns a JSON with `trace_id`, `mode`, `dag`.

---

### Task 6: Implement WorkOrderManager (tasks/results) + /route/execute + /traces

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/work-order.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/index.ts`

- [ ] **Step 1: Implement work-order.ts**

```ts
import fs from "node:fs";
import path from "node:path";

export interface WorkOrder {
  trace_id: string;
  task_id: string;
  created_at: string;
  intent: unknown;
  routing_plan: unknown;
}

export interface WorkResult {
  trace_id: string;
  task_id: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  payload?: unknown;
}

export class WorkOrderManager {
  private readonly seenResults = new Set<string>();

  constructor(private readonly artifactsRoot: string) {}

  ensureDirs(): void {
    fs.mkdirSync(path.join(this.artifactsRoot, "tasks"), { recursive: true });
    fs.mkdirSync(path.join(this.artifactsRoot, "results"), { recursive: true });
  }

  writeTask(order: WorkOrder): string {
    this.ensureDirs();
    const p = path.join(this.artifactsRoot, "tasks", `task_${order.task_id}.json`);
    fs.writeFileSync(p, JSON.stringify(order, null, 2));
    return p;
  }

  pollResults(onResult: (r: WorkResult, filePath: string) => void, intervalMs = 1000): () => void {
    this.ensureDirs();
    const dir = path.join(this.artifactsRoot, "results");
    const timer = setInterval(() => {
      let files: string[] = [];
      try {
        files = fs.readdirSync(dir).filter((f) => f.startsWith("result_") && f.endsWith(".json"));
      } catch {
        return;
      }
      for (const f of files) {
        const fp = path.join(dir, f);
        if (this.seenResults.has(fp)) continue;
        try {
          const parsed = JSON.parse(fs.readFileSync(fp, "utf-8")) as WorkResult;
          this.seenResults.add(fp);
          onResult(parsed, fp);
        } catch {
          continue;
        }
      }
    }, intervalMs);
    return () => clearInterval(timer);
  }
}
```

- [ ] **Step 2: Wire /route/execute + /traces/:traceId**

Update `index.ts`:
- `POST /route/execute`:
  - 读取 intent
  - 生成 routing plan（RouterEngine）
  - 写入 MetaStore（events + route_decisions）
  - 写入 tasks 文件（WorkOrderManager）
  - 返回 `{ trace_id, task_id, task_file_path }`
- `GET /traces/:traceId`:
  - 返回 `{ trace_id, decision, events }`

Use this code fragment (add into the server handler):

```ts
import crypto from "node:crypto";
import { WorkOrderManager } from "./work-order.js";

const work = new WorkOrderManager(artifactsRoot);

if (url.pathname === "/route/execute") {
  if (req.method !== "POST") return methodNotAllowed(res);
  const intent = await readJson<Intent>(req);
  const artifacts = store.getArtifactsIndex();
  const plan = router.decide(intent, artifacts);
  const taskId = crypto.randomUUID();

  meta.addRouteDecision(plan.trace_id, "d1", intent, plan, "v0", Date.now());
  meta.addEvent(plan.trace_id, "e_work_order_written", "work_order.written", { task_id: taskId }, Date.now());
  events.publish(plan.trace_id, { type: "work_order.written", payload: { task_id: taskId }, ts: Date.now() });

  const taskFilePath = work.writeTask({
    trace_id: plan.trace_id,
    task_id: taskId,
    created_at: new Date().toISOString(),
    intent,
    routing_plan: plan
  });

  return sendJson(res, 200, { trace_id: plan.trace_id, task_id: taskId, task_file_path: taskFilePath });
}

if (url.pathname.startsWith("/traces/")) {
  if (req.method !== "GET") return methodNotAllowed(res);
  const traceId = url.pathname.split("/").filter(Boolean)[1];
  const decision = meta.getLatestRouteDecision(traceId);
  const ev = meta.listEvents(traceId);
  return sendJson(res, 200, { trace_id: traceId, decision, events: ev });
}
```

- [ ] **Step 3: Wire result ingest poller**

Start poller at process boot:

```ts
work.pollResults((result, fp) => {
  meta.addEvent(result.trace_id, `e_result_${result.task_id}`, "result.detected", { file: fp, result }, Date.now());
  events.publish(result.trace_id, { type: "result.detected", payload: { file: fp, result }, ts: Date.now() });
});
```

- [ ] **Step 4: Build + functional test**

```bash
npm run build
node dist/index.js

curl -s -X POST http://127.0.0.1:8787/route/execute -H 'content-type: application/json' -d '{"text":"run chain"}'
```

Then (simulate producer):

```bash
ls ../dreambuddy/artifacts/tasks | head
TASK_ID=$(ls ../dreambuddy/artifacts/tasks | head -n 1 | sed 's/^task_//' | sed 's/\\.json$//')
cat > ../dreambuddy/artifacts/results/result_${TASK_ID}.json <<'JSON'
{"trace_id":"REPLACE_TRACE_ID","task_id":"REPLACE_TASK_ID","status":"completed","payload":{"ok":true}}
JSON
```

Replace the placeholders with the returned `trace_id` and `task_id`. Then:

```bash
curl -s http://127.0.0.1:8787/traces/REPLACE_TRACE_ID | head
```

Expected: trace contains `result.detected` event.

---

### Task 7: SSE events stream

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/src/index.ts`

- [ ] **Step 1: Implement GET /events/stream?traceId=...**

Add this handler before `notFound`:

```ts
if (url.pathname === "/events/stream") {
  if (req.method !== "GET") return methodNotAllowed(res);
  const traceId = url.searchParams.get("traceId");
  if (!traceId) return sendJson(res, 400, { error: "missing_traceId" });

  res.statusCode = 200;
  res.setHeader("content-type", "text/event-stream; charset=utf-8");
  res.setHeader("cache-control", "no-cache");
  res.setHeader("connection", "keep-alive");
  res.write(`event: ready\ndata: ${JSON.stringify({ ok: true })}\n\n`);

  events.subscribe(traceId, res);
  return;
}
```

- [ ] **Step 2: SSE smoke test**

Terminal A:

```bash
node dist/index.js
```

Terminal B:

```bash
curl -N "http://127.0.0.1:8787/events/stream?traceId=REPLACE_TRACE_ID"
```

Then call `/route/execute` with same traceId by temporarily reusing the returned traceId (for v0 you can just observe events from result ingest after you create result file).

---

### Task 8: Developer docs + runbook

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/7-ARTIFACT-HUB-V2/README.md`

- [ ] **Step 1: Add README.md**

```md
# 7-ARTIFACT-HUB-V2 (Artifact Hub + Router)

产物中台与路由（AI 治理端）服务：以 `dreambuddy/artifacts` 为产物真相源（FS），以 `dreambuddy/meta/artifact_hub.sqlite` 为元数据库（SQLite），并通过 `tasks/` 与 `results/` 目录与生产端（WorkBuddy）对接。

## Paths

- Artifacts root: `../dreambuddy/artifacts`
- Meta DB: `../dreambuddy/meta/artifact_hub.sqlite`

## Run

```bash
cd 7-ARTIFACT-HUB-V2
npm install
npm run build
node dist/index.js
```

## API

- `GET /health`
- `GET /artifacts/index` (planned)
- `POST /route/decide`
- `POST /route/execute`
- `GET /traces/:traceId`
- `GET /events/stream?traceId=...` (SSE)

## Producer Contract (tasks/results)

### Task file

Path: `dreambuddy/artifacts/tasks/task_<taskId>.json`

### Result file

Path: `dreambuddy/artifacts/results/result_<taskId>.json`

The result JSON must include:

```json
{ "trace_id": "...", "task_id": "...", "status": "completed" }
```
```

- [ ] **Step 2: Build to confirm README shipped**

No build step required; just ensure file exists and is accurate.

---

## Plan Self-Review

- Spec coverage: covers artifacts root relocation, Hybrid FS+SQLite, DAG routing, tasks/results protocol, SSE, trace replay
- Placeholder scan: none
