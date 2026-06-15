# Feed Minimal Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `7-ARTIFACT-HUB-V2` 内恢复真实 `/feed` 最小闭环，先打通列表页、分类页、详情页，再把 `ui-map` 中的 Feed 节点切到真实入口。

**Architecture:** 采用 `Node + Express + server-rendered HTML` 路线，不引入新的前端框架。实现上把 `/feed` 拆成独立 `src/feed/` 领域模块：`content.ts` 负责数据扫描与详情读取，`render.ts` 负责 HTML 输出，`server.ts` 负责装配 HTTP 服务，`index.ts` 仅保留启动逻辑。

**Tech Stack:** TypeScript, Node.js, Express, node:test, gray-matter, marked

---

## File Structure

- Create: `src/feed/types.ts`
- Create: `src/feed/utils.ts`
- Create: `src/feed/content.ts`
- Create: `src/feed/render.ts`
- Create: `src/feed/content.test.ts`
- Create: `src/feed/render.test.ts`
- Create: `src/feed/routes.test.ts`
- Create: `src/server.ts`
- Modify: `src/index.ts`
- Modify: `src/ops-ui/ui-map.ts`
- Modify: `README.md`
- Modify: `package.json`

### Responsibilities

- `src/feed/types.ts`: 定义 Feed 列表项、详情项、统计项和查询参数。
- `src/feed/utils.ts`: 处理 HTML escaping、slug 解析、时间格式化、状态和部门标签。
- `src/feed/content.ts`: 负责扫描 artifacts 根目录、读取 markdown/json 详情、构建缓存和过滤结果。
- `src/feed/render.ts`: 输出 `/feed` 列表页、分类页、详情页 HTML。
- `src/server.ts`: 组装现有 Hub API 与新的 `/feed` 路由，导出可测试的 `createHubServer()`。
- `src/index.ts`: 仅读取配置并启动服务，避免路由逻辑继续膨胀。

### Task 1: Feed Domain Data Layer

**Files:**
- Create: `src/feed/types.ts`
- Create: `src/feed/utils.ts`
- Create: `src/feed/content.ts`
- Create: `src/feed/content.test.ts`
- Modify: `package.json`

- [ ] **Step 1: Write the failing test**

```ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { FeedContentStore } from "./content.js";

test("FeedContentStore lists artifacts, computes stats, and reads markdown detail", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-content-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/a1",
          title: "Alpha Report",
          filename: "a1.md",
          type: "report",
          status: "completed",
          tags: ["macro", "risk"],
          chain_phase: "A3"
        }
      ]
    })
  );

  fs.writeFileSync(
    path.join(tradingDir, "a1.md"),
    `---
title: Alpha Report
department: trading
type: report
status: completed
tags:
  - macro
  - risk
date: 2026-05-20T10:00:00Z
---

# Alpha Report

This is the markdown body.
`
  );

  const store = new FeedContentStore(root);
  const list = store.listArtifacts();
  assert.equal(list.length, 1);
  assert.equal(list[0].url, "/feed/trading/a1");
  assert.equal(list[0].category, "trading");
  assert.equal(list[0].artifactId, "a1");

  const stats = store.getStats();
  assert.equal(stats.total, 1);
  assert.equal(stats.byDepartment.trading, 1);
  assert.equal(stats.byChainPhase.A3, 1);

  const detail = store.getArtifactDetail("trading", "a1");
  assert.ok(detail);
  assert.equal(detail?.title, "Alpha Report");
  assert.match(detail?.content ?? "", /This is the markdown body/);

  fs.rmSync(root, { recursive: true, force: true });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run build && npm test -- --test-name-pattern="FeedContentStore lists artifacts"`
Expected: FAIL with `Cannot find module './content.js'` or `FeedContentStore is not exported`

- [ ] **Step 3: Write minimal implementation**

```ts
// src/feed/types.ts
export interface FeedListItem {
  id: string;
  category: string;
  artifactId: string;
  title: string;
  department: string;
  type: string;
  status: string;
  date: string;
  chain_phase: string;
  tags: string[];
  excerpt?: string;
  url: string;
}

export interface FeedDetail extends FeedListItem {
  content: string;
  rawPath: string;
}

export interface FeedStats {
  total: number;
  byDepartment: Record<string, number>;
  byType: Record<string, number>;
  byStatus: Record<string, number>;
  byChainPhase: Record<string, number>;
}

export interface FeedQuery {
  category?: string;
  q?: string;
}
```

```ts
// src/feed/utils.ts
export function countBy(items: string[]): Record<string, number> {
  return items.reduce<Record<string, number>>((acc, item) => {
    if (!item) return acc;
    acc[item] = (acc[item] || 0) + 1;
    return acc;
  }, {});
}

export function stripMarkdown(input: string): string {
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
    .trim();
}
```

```ts
// src/feed/content.ts
import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";
import { CATEGORY_TO_DEPARTMENT } from "../category.js";
import type { FeedDetail, FeedListItem, FeedQuery, FeedStats } from "./types.js";
import { countBy, stripMarkdown } from "./utils.js";

export class FeedContentStore {
  private cache: FeedListItem[] | null = null;

  constructor(private readonly artifactsRoot: string) {}

  listArtifacts(query: FeedQuery = {}): FeedListItem[] {
    const items = this.cache ?? (this.cache = this.scanArtifacts());
    return items.filter((item) => {
      if (query.category && item.category !== query.category) return false;
      if (query.q) {
        const needle = query.q.toLowerCase();
        return [item.title, item.department, item.type, item.tags.join(" "), item.excerpt || ""]
          .join(" ")
          .toLowerCase()
          .includes(needle);
      }
      return true;
    });
  }

  getStats(): FeedStats {
    const items = this.listArtifacts();
    return {
      total: items.length,
      byDepartment: countBy(items.map((item) => item.department)),
      byType: countBy(items.map((item) => item.type)),
      byStatus: countBy(items.map((item) => item.status)),
      byChainPhase: countBy(items.map((item) => item.chain_phase))
    };
  }

  getArtifactDetail(category: string, artifactId: string): FeedDetail | null {
    const item = this.listArtifacts().find((entry) => entry.category === category && entry.artifactId === artifactId);
    if (!item) return null;

    const mdPath = path.join(this.artifactsRoot, category, `${artifactId}.md`);
    const jsonPath = path.join(this.artifactsRoot, category, `${artifactId}.json`);

    if (fs.existsSync(mdPath)) {
      const parsed = matter(fs.readFileSync(mdPath, "utf-8"));
      return { ...item, content: parsed.content, rawPath: mdPath };
    }

    if (fs.existsSync(jsonPath)) {
      const raw = fs.readFileSync(jsonPath, "utf-8");
      return { ...item, content: `\`\`\`json\n${raw}\n\`\`\``, rawPath: jsonPath };
    }

    return null;
  }

  refresh(): void {
    this.cache = null;
  }

  private scanArtifacts(): FeedListItem[] {
    if (!fs.existsSync(this.artifactsRoot)) return [];

    const categories = fs.readdirSync(this.artifactsRoot).filter((name) => {
      const current = path.join(this.artifactsRoot, name);
      return fs.statSync(current).isDirectory() && !name.startsWith(".") && name !== "tasks" && name !== "results";
    });

    const items: FeedListItem[] = [];

    for (const category of categories) {
      const indexFile = path.join(this.artifactsRoot, category, "index.json");
      if (!fs.existsSync(indexFile)) continue;
      const raw = JSON.parse(fs.readFileSync(indexFile, "utf-8")) as { artifacts?: Array<Record<string, unknown>>; last_updated?: string };
      const records = Array.isArray(raw) ? raw : (raw.artifacts || []);

      for (const record of records) {
        const rawId = String(record.artifact_id || record.id || "unknown");
        const artifactId = rawId.includes("/") ? rawId.split("/").pop() || rawId : rawId;
        const mdPath = path.join(this.artifactsRoot, category, `${artifactId}.md`);
        const excerpt = fs.existsSync(mdPath)
          ? stripMarkdown(matter(fs.readFileSync(mdPath, "utf-8")).content).slice(0, 200)
          : undefined;

        items.push({
          id: `${category}/${artifactId}`,
          category,
          artifactId,
          title: String(record.title || artifactId),
          department: CATEGORY_TO_DEPARTMENT[category] || "knowledge",
          type: String(record.type || "knowledge"),
          status: String(record.status || "completed"),
          date: String(record.date || raw.last_updated || new Date().toISOString()),
          chain_phase: String(record.chain_phase || ""),
          tags: Array.isArray(record.tags) ? record.tags.map(String) : [],
          excerpt,
          url: `/feed/${category}/${artifactId}`
        });
      }
    }

    items.sort((a, b) => b.date.localeCompare(a.date));
    return items;
  }
}
```

```json
// package.json
{
  "dependencies": {
    "express": "^4.21.0",
    "gray-matter": "^4.0.3",
    "marked": "^18.0.2"
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm install && npm run build && npm test -- --test-name-pattern="FeedContentStore lists artifacts"`
Expected: PASS with `1 test passed`

- [ ] **Step 5: Commit**

```bash
git add package.json src/feed/types.ts src/feed/utils.ts src/feed/content.ts src/feed/content.test.ts
git commit -m "feat(feed): add feed content store"
```

### Task 2: Feed HTML Rendering

**Files:**
- Create: `src/feed/render.ts`
- Create: `src/feed/render.test.ts`
- Test: `src/feed/render.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { renderFeedIndexHtml, renderFeedDetailHtml } from "./render.js";

test("renderFeedIndexHtml renders feed list, filters, and detail links", () => {
  const html = renderFeedIndexHtml({
    title: "Feed Content Portal",
    items: [
      {
        id: "trading/a1",
        category: "trading",
        artifactId: "a1",
        title: "Alpha Report",
        department: "trading",
        type: "report",
        status: "completed",
        date: "2026-05-20T10:00:00Z",
        chain_phase: "A3",
        tags: ["macro"],
        excerpt: "Body excerpt",
        url: "/feed/trading/a1"
      }
    ],
    stats: {
      total: 1,
      byDepartment: { trading: 1 },
      byType: { report: 1 },
      byStatus: { completed: 1 },
      byChainPhase: { A3: 1 }
    },
    query: { category: "trading", q: "alpha" }
  });

  assert.ok(html.includes("Feed Content Portal"));
  assert.ok(html.includes('action="/feed"'));
  assert.ok(html.includes('name="q"'));
  assert.ok(html.includes('href="/feed/trading/a1"'));
  assert.ok(html.includes("Alpha Report"));
  assert.ok(html.includes("Body excerpt"));
});

test("renderFeedDetailHtml renders markdown content and back link", () => {
  const html = renderFeedDetailHtml({
    id: "trading/a1",
    category: "trading",
    artifactId: "a1",
    title: "Alpha Report",
    department: "trading",
    type: "report",
    status: "completed",
    date: "2026-05-20T10:00:00Z",
    chain_phase: "A3",
    tags: ["macro"],
    url: "/feed/trading/a1",
    rawPath: "/tmp/a1.md",
    content: "# Alpha Report\n\nRendered body"
  });

  assert.ok(html.includes('href="/feed/trading"'));
  assert.ok(html.includes("Alpha Report"));
  assert.ok(html.includes("<h1>Alpha Report</h1>"));
  assert.ok(html.includes("Rendered body"));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run build && npm test -- --test-name-pattern="renderFeed(Index|Detail)Html"`
Expected: FAIL with `Cannot find module './render.js'`

- [ ] **Step 3: Write minimal implementation**

```ts
// src/feed/render.ts
import { marked } from "marked";
import type { FeedDetail, FeedListItem, FeedQuery, FeedStats } from "./types.js";

function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderStats(stats: FeedStats): string {
  return `<div class="feed-stats"><span>Total ${stats.total}</span></div>`;
}

function renderCard(item: FeedListItem): string {
  return `
    <article class="feed-card">
      <div class="feed-card-meta">${escapeHtml(item.department)} · ${escapeHtml(item.type)} · ${escapeHtml(item.chain_phase || "Unphased")}</div>
      <h2><a href="${escapeHtml(item.url)}">${escapeHtml(item.title)}</a></h2>
      <p>${escapeHtml(item.excerpt || "No excerpt available.")}</p>
    </article>
  `;
}

export function renderFeedIndexHtml(input: {
  title: string;
  items: FeedListItem[];
  stats: FeedStats;
  query: FeedQuery;
}): string {
  const cards = input.items.map(renderCard).join("");
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>${escapeHtml(input.title)}</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; background: #0b1020; color: #f8fafc; }
      main { max-width: 1080px; margin: 0 auto; padding: 32px 20px 48px; }
      form { display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0 24px; }
      input, select { padding: 10px 12px; border-radius: 10px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; }
      .feed-card { border: 1px solid #1e293b; border-radius: 16px; padding: 16px; margin-bottom: 12px; background: #111827; }
      a { color: #93c5fd; text-decoration: none; }
      .feed-stats { color: #94a3b8; margin-top: 8px; }
    </style>
  </head>
  <body>
    <main>
      <h1>${escapeHtml(input.title)}</h1>
      ${renderStats(input.stats)}
      <form method="GET" action="/feed">
        <input type="search" name="q" value="${escapeHtml(input.query.q || "")}" placeholder="Search artifacts" />
        <input type="text" name="category" value="${escapeHtml(input.query.category || "")}" placeholder="Category" />
        <button type="submit">Filter</button>
      </form>
      <section>${cards || "<p>No artifacts found.</p>"}</section>
    </main>
  </body>
</html>`;
}

export function renderFeedDetailHtml(detail: FeedDetail): string {
  const html = marked.parse(detail.content, { async: false }) as string;
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>${escapeHtml(detail.title)}</title>
  </head>
  <body>
    <main>
      <nav><a href="/feed/${escapeHtml(detail.category)}">Back to ${escapeHtml(detail.category)}</a></nav>
      <header>
        <h1>${escapeHtml(detail.title)}</h1>
        <p>${escapeHtml(detail.department)} · ${escapeHtml(detail.type)} · ${escapeHtml(detail.status)}</p>
      </header>
      <article>${html}</article>
    </main>
  </body>
</html>`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run build && npm test -- --test-name-pattern="renderFeed(Index|Detail)Html"`
Expected: PASS with `2 tests passed`

- [ ] **Step 5: Commit**

```bash
git add src/feed/render.ts src/feed/render.test.ts
git commit -m "feat(feed): add server rendered feed pages"
```

### Task 3: Wire Feed Routes Into the Hub Server

**Files:**
- Create: `src/server.ts`
- Create: `src/feed/routes.test.ts`
- Modify: `src/index.ts`

- [ ] **Step 1: Write the failing test**

```ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHubServer } from "./server.js";

function listen(server: ReturnType<typeof createHubServer>): Promise<{ baseUrl: string; close: () => Promise<void> }> {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("failed_to_listen");
      resolve({
        baseUrl: `http://127.0.0.1:${address.port}`,
        close: () => new Promise((done) => server.close(() => done()))
      });
    });
  });
}

test("createHubServer serves /feed list, category, and detail pages", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-"));
  const meta = fs.mkdtempSync(path.join(os.tmpdir(), "feed-meta-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });
  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [{ artifact_id: "trading/a1", title: "Alpha Report", filename: "a1.md", type: "report", status: "completed" }]
    })
  );
  fs.writeFileSync(path.join(tradingDir, "a1.md"), "# Alpha Report\n\nBody");

  const server = createHubServer({ artifactsRoot: root, metaRoot: meta });
  const { baseUrl, close } = await listen(server);

  try {
    const listRes = await fetch(`${baseUrl}/feed`);
    const categoryRes = await fetch(`${baseUrl}/feed/trading`);
    const detailRes = await fetch(`${baseUrl}/feed/trading/a1`);

    assert.equal(listRes.status, 200);
    assert.equal(categoryRes.status, 200);
    assert.equal(detailRes.status, 200);
    assert.match(await detailRes.text(), /Alpha Report/);
  } finally {
    await close();
    fs.rmSync(root, { recursive: true, force: true });
    fs.rmSync(meta, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run build && npm test -- --test-name-pattern="createHubServer serves /feed"`
Expected: FAIL with `Cannot find module './server.js'`

- [ ] **Step 3: Write minimal implementation**

```ts
// src/server.ts
import { createServer } from "node:http";
import path from "node:path";
import crypto from "node:crypto";
import fs from "node:fs";
import { loadConfig, resolveRepoRoot } from "./config.js";
import { ArtifactStore } from "./artifact-store.js";
import { EventBus } from "./event-bus.js";
import { readJson, sendJson, methodNotAllowed, notFound } from "./http-utils.js";
import { MetaStore } from "./meta-store.js";
import { RouterEngine } from "./router-engine.js";
import { WorkOrderManager } from "./work-order.js";
import type { Intent, MarketIntel } from "./types.js";
import { groupByWorkflowType, normalizeWorkflowType } from "./chain-workflow-guard.js";
import { FeedContentStore } from "./feed/content.js";
import { renderFeedDetailHtml, renderFeedIndexHtml } from "./feed/render.js";

export interface HubServerOptions {
  artifactsRoot?: string;
  metaRoot?: string;
}

export function createHubServer(options: HubServerOptions = {}) {
  const repoRoot = resolveRepoRoot();
  const config = loadConfig(repoRoot);
  const artifactsRoot = options.artifactsRoot || path.join(repoRoot, config.paths.artifacts_root);
  const metaRoot = options.metaRoot || path.join(repoRoot, config.paths.meta_root);
  const store = new ArtifactStore(artifactsRoot);
  const feedStore = new FeedContentStore(artifactsRoot);
  const meta = new MetaStore(metaRoot);
  const router = new RouterEngine();
  const events = new EventBus();
  const work = new WorkOrderManager(artifactsRoot);
  meta.setArtifactStore(store);

  return createServer(async (req, res) => {
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

    if (req.method === "GET" && url.pathname === "/feed") {
      const html = renderFeedIndexHtml({
        title: "Feed Content Portal",
        items: feedStore.listArtifacts({ q: url.searchParams.get("q") || undefined }),
        stats: feedStore.getStats(),
        query: { q: url.searchParams.get("q") || undefined }
      });
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

    if (req.method === "GET" && /^\/feed\/[^/]+$/.test(url.pathname)) {
      const category = url.pathname.split("/")[2] || "";
      const html = renderFeedIndexHtml({
        title: `Feed / ${category}`,
        items: feedStore.listArtifacts({ category, q: url.searchParams.get("q") || undefined }),
        stats: feedStore.getStats(),
        query: { category, q: url.searchParams.get("q") || undefined }
      });
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

    if (req.method === "GET" && /^\/feed\/[^/]+\/[^/]+$/.test(url.pathname)) {
      const [, , category, artifactId] = url.pathname.split("/");
      const detail = feedStore.getArtifactDetail(category, artifactId);
      if (!detail) return notFound(res);
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(renderFeedDetailHtml(detail));
      return;
    }

    // Keep the existing route/trace/chain/board handlers below this point.
  });
}
```

```ts
// src/index.ts
import { createHubServer } from "./server.js";
import { loadConfig, resolveRepoRoot } from "./config.js";

const repoRoot = resolveRepoRoot();
const config = loadConfig(repoRoot);
const server = createHubServer();

server.listen(config.server.port, config.server.host, () => {
  console.log(`artifact-hub-v2 listening on http://${config.server.host}:${config.server.port}`);
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run build && npm test -- --test-name-pattern="createHubServer serves /feed"`
Expected: PASS with `1 test passed`

- [ ] **Step 5: Commit**

```bash
git add src/server.ts src/index.ts src/feed/routes.test.ts
git commit -m "feat(feed): expose feed routes from hub server"
```

### Task 4: Promote Feed in UI Map and Docs

**Files:**
- Modify: `src/ops-ui/ui-map.ts`
- Modify: `src/ops-ui/ops-ui.test.ts`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

```ts
test("ops-ui ui-map marks /feed as implemented after feed recovery", async () => {
  const opsListener = await listen(createOpsServer());
  try {
    const res = await fetch(new URL("/ui-map", opsListener.url));
    const html = await res.text();
    assert.ok(html.includes('href="/feed"'));
    assert.ok(html.includes("Implemented"));
    assert.ok(!html.includes('/planned?target=%2Ffeed&label=%2Ffeed&node=feed&module=Feed'));
  } finally {
    await opsListener.close();
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run build && npm test -- --test-name-pattern="marks /feed as implemented"`
Expected: FAIL because `/feed` is still rendered as planned

- [ ] **Step 3: Write minimal implementation**

```ts
// src/ops-ui/ui-map.ts
{
  href: "/feed",
  label: "/feed",
  status: "implemented"
}
```

```md
<!-- README.md -->
| 研究中台 `/feed` | 恢复中 / 最小闭环已接入 | 当前主仓 `7-ARTIFACT-HUB-V2` 内提供 `/feed` 列表页、分类页、详情页 |
```

- [ ] **Step 4: Run full verification**

Run: `npm run build && npm test`
Expected: PASS with existing tests plus new feed tests all green

Run: `PORT=3467 npm start`
Expected: server starts and `/feed`, `/feed/trading`, `/feed/trading/a1` return HTML

- [ ] **Step 5: Commit**

```bash
git add src/ops-ui/ui-map.ts src/ops-ui/ops-ui.test.ts README.md
git commit -m "feat(feed): expose recovered feed in ui map"
```

## Self-Review

### Spec coverage

- 已覆盖 `/feed` 三段路由：Task 3
- 已覆盖 `src/feed/*` 模块拆分：Task 1 + Task 2
- 已覆盖 `ui-map` 从 planned 切到 implemented：Task 4
- 已覆盖 repo-local artifacts 路径适配：Task 1

### Placeholder scan

- 本计划没有使用 `TODO`、`TBD`、`implement later`
- 每个任务都包含测试、运行命令、实现代码和提交命令

### Type consistency

- 统一使用 `FeedContentStore`
- 统一使用 `renderFeedIndexHtml` / `renderFeedDetailHtml`
- 统一使用 `createHubServer`

Plan complete and saved to `docs/superpowers/plans/2026-05-20-feed-minimal-recovery.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
