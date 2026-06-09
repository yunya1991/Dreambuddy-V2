# Feed And Chain Core Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore real `/feed` and `/chain` core pages inside `7-ARTIFACT-HUB-V2`, fix local runtime routing, and connect both pages with shared governance context.

**Architecture:** Keep a single SSR Hub server in `src/server.ts`, evolve `src/feed/*`, add a dedicated `src/chain/*` area, and expose `/feed` and `/chain` as real Hub routes while `ops-ui` remains a navigation and governance entry point. Use repo-local artifacts/meta/config as the only source of truth and compose page-specific view models from existing stores before rendering HTML.

**Tech Stack:** Node.js, TypeScript, `node:test`, SSR HTML, Express-based `ops-ui`, repo-local JSON artifacts, SQLite-backed meta store

---

## File Map

### Existing files to modify

- `7-ARTIFACT-HUB-V2/src/server.ts`
  - Real Hub route wiring for `/feed` and `/chain`
- `7-ARTIFACT-HUB-V2/src/feed/content.ts`
  - Feed query composition and detail context enrichment
- `7-ARTIFACT-HUB-V2/src/feed/render.ts`
  - Feed index/detail rendering toward remote core behavior
- `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`
  - Existing route integration coverage
- `7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`
  - Runtime URL alignment and `ui-map` jump targets
- `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
  - Real `/feed` and `/chain` links instead of placeholders
- `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`
  - `ui-map` route/link expectations

### New files to create

- `7-ARTIFACT-HUB-V2/src/chain/types.ts`
  - Chain page view-model types
- `7-ARTIFACT-HUB-V2/src/chain/content.ts`
  - Chain query composition layer
- `7-ARTIFACT-HUB-V2/src/chain/render.ts`
  - Chain SSR HTML renderer
- `7-ARTIFACT-HUB-V2/src/chain/content.test.ts`
  - Chain query-layer tests
- `7-ARTIFACT-HUB-V2/src/chain/render.test.ts`
  - Chain renderer tests
- `7-ARTIFACT-HUB-V2/src/chain/routes.test.ts`
  - Chain route integration tests

### Supporting docs to update at the end

- `7-ARTIFACT-HUB-V2/README.md`
- `7-ARTIFACT-HUB-V2/OPS_UI_README.md`

---

### Task 1: Fix Local Runtime And UI Map Real Links

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

- [ ] **Step 1: Write the failing test for real `/chain` and canonical Hub base URL**

Add this test to `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`:

```ts
test("ops-ui ui-map points feed and chain nodes to the canonical local Hub", async () => {
  const prevHubUrl = process.env.HUB_URL;
  delete process.env.OPS_UI_FEED_BASE_URL;
  process.env.HUB_URL = "http://127.0.0.1:3456";

  const opsListener = await listen(createOpsServer());
  try {
    const res = await fetch(new URL("/ui-map?node=feed", opsListener.url));
    assert.equal(res.status, 200);
    const html = await res.text();
    assert.ok(html.includes('href="http://127.0.0.1:3456/feed"'));
    assert.ok(html.includes('href="http://127.0.0.1:3456/chain"'));
    assert.ok(!html.includes('href="http://127.0.0.1:8787/feed"'));
  } finally {
    process.env.HUB_URL = prevHubUrl;
    await opsListener.close();
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/ops-ui/ops-ui.test.js
```

Expected: FAIL because `ui-map` does not yet expose a real `/chain` link and local runtime assumptions still point at the old Hub default in output/docs.

- [ ] **Step 3: Write the minimal implementation**

Update `7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts` so the canonical Hub base resolves to `3456`:

```ts
function resolveHubBaseUrl(): string {
  return readOptionalEnvUrl("HUB_URL") ?? "http://127.0.0.1:3456";
}
```

Update `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts` to derive both real URLs:

```ts
const feedHomeHref = escapeHtml(joinBaseUrl(feedBaseUrl, "/feed"));
const chainHomeHref = escapeHtml(joinBaseUrl(feedBaseUrl, "/chain"));
```

In `NODE_META`, replace planned-only chain entry with:

```ts
chain: {
  title: "Chain Monitor",
  status: "implemented",
  description:
    "内部研究链路监控与内容/交易能力治理核心，负责展示 workflow、trace、task、result 与异常状态。",
  links: [
    { href: chainHomeHref, label: "/chain", status: "implemented" }
  ],
  apis: ["GET /chain/artifacts", "GET /chain/reviews", "GET /chain/performance"]
}
```

And in the default drawer block, include:

```ts
<li><div class="drawer-link-row"><a href="${chainHomeHref}">/chain</a><span class="drawer-link-state implemented">Implemented</span></div></li>
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/ops-ui/ops-ui.test.js
```

Expected: PASS and rendered `ui-map` HTML contains `http://127.0.0.1:3456/feed` and `http://127.0.0.1:3456/chain`.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts 7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts 7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts
git commit -m "fix(artifact-hub): align ui-map feed and chain runtime links"
```

---

### Task 2: Expand Feed Query Layer For Portal And Governance Context

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/feed/types.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/content.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/content.test.ts`

- [ ] **Step 1: Write the failing tests for filters, pagination, and governance context**

Append these tests to `7-ARTIFACT-HUB-V2/src/feed/content.test.ts`:

```ts
test("FeedContentStore filters artifacts by department, status, and chain phase", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-filters-"));
  fs.mkdirSync(path.join(root, "trading"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "trading", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        { artifact_id: "trading/a1", title: "A1", status: "completed", type: "report", chain_phase: "A3", tags: ["a3"] },
        { artifact_id: "trading/a2", title: "A2", status: "failed", type: "report", chain_phase: "A5", tags: ["a5"] }
      ]
    })
  );

  const store = new FeedContentStore(root);
  const items = store.listArtifacts({ department: "trading", status: "completed", chainPhase: "A3" });
  assert.equal(items.length, 1);
  assert.equal(items[0].artifactId, "a1");
  fs.rmSync(root, { recursive: true, force: true });
});

test("FeedContentStore paginates list results", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-page-"));
  fs.mkdirSync(path.join(root, "research"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "research", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        { artifact_id: "research/r1", title: "R1" },
        { artifact_id: "research/r2", title: "R2" },
        { artifact_id: "research/r3", title: "R3" }
      ]
    })
  );

  const store = new FeedContentStore(root);
  const page = store.listArtifacts({ limit: 2, offset: 1 });
  assert.deepEqual(page.map((item) => item.artifactId), ["r2", "r3"]);
  fs.rmSync(root, { recursive: true, force: true });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/feed/content.test.js
```

Expected: FAIL because `FeedQuery` and `FeedContentStore.listArtifacts()` do not yet support these fields.

- [ ] **Step 3: Write minimal implementation**

Extend `7-ARTIFACT-HUB-V2/src/feed/types.ts`:

```ts
export interface FeedQuery {
  category?: string;
  q?: string;
  department?: string;
  status?: string;
  chainPhase?: string;
  limit?: number;
  offset?: number;
}
```

Update `7-ARTIFACT-HUB-V2/src/feed/content.ts` filtering and slicing:

```ts
listArtifacts(query: FeedQuery = {}): FeedListItem[] {
  const items = this.cache ?? (this.cache = this.scanArtifacts());

  const filtered = items.filter((item) => {
    if (query.category && item.category !== query.category) return false;
    if (query.department && item.department !== query.department) return false;
    if (query.status && item.status !== query.status) return false;
    if (query.chainPhase && item.chainPhase !== query.chainPhase) return false;
    if (query.q) {
      const needle = query.q.toLowerCase();
      const haystack = [item.title, item.excerpt || "", item.tags.join(" "), item.category].join(" ").toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });

  const offset = query.offset ?? 0;
  const limit = query.limit ?? filtered.length;
  return filtered.slice(offset, offset + limit);
}
```

Also extend detail return shape with a governance context block:

```ts
governanceContext: {
  workflowId: item.workflowId ?? "";
  workflowType: item.workflowType ?? "legacy_chain";
  traceId: item.traceId ?? "";
  chainPhase: item.chainPhase;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/feed/content.test.js
```

Expected: PASS with the new filter and pagination coverage green.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/feed/types.ts 7-ARTIFACT-HUB-V2/src/feed/content.ts 7-ARTIFACT-HUB-V2/src/feed/content.test.ts
git commit -m "feat(artifact-hub): expand feed query context"
```

---

### Task 3: Upgrade Feed SSR To Remote-Core Homepage And Detail Behavior

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/feed/render.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/render.test.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/server.ts`

- [ ] **Step 1: Write the failing tests for homepage controls and detail cross-link**

Add to `7-ARTIFACT-HUB-V2/src/feed/render.test.ts`:

```ts
test("renderFeedIndexHtml includes navigation, filter chips, and pagination shell", () => {
  const html = renderFeedIndexHtml({
    title: "Dream 产物中心",
    items: [
      {
        id: "trading/a1",
        category: "trading",
        artifactId: "a1",
        filename: "a1.md",
        title: "A1 Report",
        department: "trading",
        type: "report",
        status: "completed",
        date: "2026-05-20",
        chainPhase: "A3",
        tags: ["A3"],
        excerpt: "alpha",
        url: "/feed/trading/a1"
      }
    ],
    stats: { total: 1, byDepartment: { trading: 1 }, byType: { report: 1 }, byStatus: { completed: 1 }, byChainPhase: { A3: 1 } },
    query: { q: "", category: "trading", department: "trading", chainPhase: "A3" }
  });

  assert.match(html, /Dream 产物中心/);
  assert.match(html, /组织架构/);
  assert.match(html, /驾驶舱/);
  assert.match(html, /上一页/);
  assert.match(html, /下一页/);
});

test("renderFeedDetailHtml includes governance context and chain jump link", () => {
  const html = renderFeedDetailHtml({
    id: "trading/a1",
    category: "trading",
    artifactId: "a1",
    filename: "a1.md",
    title: "A1 Report",
    department: "trading",
    type: "report",
    status: "completed",
    date: "2026-05-20",
    chainPhase: "A3",
    tags: ["A3"],
    excerpt: "alpha",
    url: "/feed/trading/a1",
    content: "# Report",
    rawPath: "/tmp/a1.md",
    governanceContext: {
      workflowId: "wf-1",
      workflowType: "legacy_chain",
      traceId: "trace-1",
      chainPhase: "A3"
    }
  });

  assert.match(html, /trace-1/);
  assert.match(html, /workflow/);
  assert.match(html, /href="\/chain\/legacy_chain\?artifactId=a1"/);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/feed/render.test.js dist/src/feed/routes.test.js
```

Expected: FAIL because the current renderer does not include the richer remote-core controls.

- [ ] **Step 3: Write minimal implementation**

Update `7-ARTIFACT-HUB-V2/src/feed/render.ts` index shell:

```ts
<header class="top-nav">
  <a href="/feed">产物中心</a>
  <a href="/chain">组织架构</a>
  <a href="/ops">驾驶舱</a>
</header>
<section class="toolbar">
  <input type="search" name="q" value="${escapeHtml(input.query.q || "")}" placeholder="搜索产物标题、标签..." />
  <div class="chip-row">${renderDepartmentChips(input.stats.byDepartment, input.query.department)}</div>
  <div class="chip-row">${renderPhaseChips(input.stats.byChainPhase, input.query.chainPhase)}</div>
</section>
<nav class="pagination">
  <button type="button">上一页</button>
  <button type="button">下一页</button>
</nav>
```

Update detail panel:

```ts
<aside class="detail-side">
  <h2>治理上下文</h2>
  <p>trace_id: ${escapeHtml(detail.governanceContext.traceId || "none")}</p>
  <p>workflow: ${escapeHtml(detail.governanceContext.workflowType || "legacy_chain")}</p>
  <p>chain_phase: ${escapeHtml(detail.governanceContext.chainPhase || "")}</p>
  <p><a href="/chain/${escapeHtml(detail.governanceContext.workflowType || "legacy_chain")}?artifactId=${escapeHtml(detail.artifactId)}">查看链路监控</a></p>
</aside>
```

Update `7-ARTIFACT-HUB-V2/src/server.ts` to pass richer query fields into `feedStore.listArtifacts()` and to use the new query object when rendering.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/feed/render.test.js dist/src/feed/routes.test.js
```

Expected: PASS with renderer and route integration green.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/feed/render.ts 7-ARTIFACT-HUB-V2/src/feed/render.test.ts 7-ARTIFACT-HUB-V2/src/feed/routes.test.ts 7-ARTIFACT-HUB-V2/src/server.ts
git commit -m "feat(artifact-hub): upgrade feed core portal ui"
```

---

### Task 4: Add Chain Query Layer And Route Coverage

**Files:**
- Create: `7-ARTIFACT-HUB-V2/src/chain/types.ts`
- Create: `7-ARTIFACT-HUB-V2/src/chain/content.ts`
- Create: `7-ARTIFACT-HUB-V2/src/chain/content.test.ts`
- Create: `7-ARTIFACT-HUB-V2/src/chain/routes.test.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/server.ts`

- [ ] **Step 1: Write the failing tests for chain overview and route**

Create `7-ARTIFACT-HUB-V2/src/chain/content.test.ts`:

```ts
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { ChainContentStore } from "./content.js";

test("ChainContentStore groups artifacts by workflow type and surfaces anomalies", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "chain-content-"));
  fs.mkdirSync(path.join(root, "trading"), { recursive: true });
  fs.mkdirSync(path.join(root, "tasks"), { recursive: true });
  fs.mkdirSync(path.join(root, "results"), { recursive: true });

  fs.writeFileSync(
    path.join(root, "trading", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        { artifact_id: "trading/a1", title: "A1", workflow_type: "legacy_chain", chain_phase: "A3", status: "completed" },
        { artifact_id: "trading/a2", title: "A2", workflow_type: "trading_v2", chain_phase: "A5", status: "processing" }
      ]
    })
  );
  fs.writeFileSync(path.join(root, "tasks", "task_a2.json"), JSON.stringify({ task_id: "task_a2", trace_id: "trace_a2", routing_plan: { mode: "RUN_CHAIN" } }));

  const store = new ChainContentStore(root);
  const overview = store.getOverview();
  assert.equal(overview.workflowGroups.legacy_chain.length, 1);
  assert.equal(overview.workflowGroups.trading_v2.length, 1);
  assert.ok(overview.anomalies.some((item) => item.kind === "missing_result"));
  fs.rmSync(root, { recursive: true, force: true });
});
```

Create `7-ARTIFACT-HUB-V2/src/chain/routes.test.ts`:

```ts
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import type { Server } from "node:http";
import { createHubServer } from "../server.js";

function listen(server: Server): Promise<{ baseUrl: string; close: () => Promise<void> }> {
  return new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") return reject(new Error("failed_to_listen"));
      resolve({
        baseUrl: `http://127.0.0.1:${address.port}`,
        close: () => new Promise((done) => server.close(() => done()))
      });
    });
  });
}

test("createHubServer serves /chain and /chain/:workflowType", async () => {
  const artifactsRoot = fs.mkdtempSync(path.join(os.tmpdir(), "chain-routes-artifacts-"));
  const metaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "chain-routes-meta-"));
  fs.mkdirSync(path.join(artifactsRoot, "trading"), { recursive: true });
  fs.writeFileSync(
    path.join(artifactsRoot, "trading", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [{ artifact_id: "trading/a1", title: "A1", workflow_type: "legacy_chain", chain_phase: "A3", status: "completed" }]
    })
  );

  const server = createHubServer({ artifactsRoot, metaRoot });
  const { baseUrl, close } = await listen(server);
  try {
    const overview = await fetch(`${baseUrl}/chain`);
    const legacy = await fetch(`${baseUrl}/chain/legacy_chain`);
    assert.equal(overview.status, 200);
    assert.equal(legacy.status, 200);
    assert.match(await overview.text(), /Chain Monitor/);
    assert.match(await legacy.text(), /legacy_chain/);
  } finally {
    await close();
    fs.rmSync(artifactsRoot, { recursive: true, force: true });
    fs.rmSync(metaRoot, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/chain/content.test.js dist/src/chain/routes.test.js
```

Expected: FAIL because the `src/chain/*` area and `/chain` real routes do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `7-ARTIFACT-HUB-V2/src/chain/types.ts`:

```ts
export interface ChainAnomaly {
  kind: "missing_task" | "missing_result" | "orphan_artifact" | "broken_trace_link";
  artifactId: string;
  workflowType: "legacy_chain" | "trading_v2";
}

export interface ChainWorkflowItem {
  artifactId: string;
  title: string;
  category: string;
  department: string;
  workflowType: "legacy_chain" | "trading_v2";
  chainPhase: string;
  status: string;
  feedUrl: string;
}

export interface ChainOverviewViewModel {
  workflowGroups: {
    legacy_chain: ChainWorkflowItem[];
    trading_v2: ChainWorkflowItem[];
  };
  anomalies: ChainAnomaly[];
}
```

Create `7-ARTIFACT-HUB-V2/src/chain/content.ts`:

```ts
import { ArtifactStore } from "../artifact-store.js";
import { normalizeWorkflowType } from "../chain-workflow-guard.js";
import { ChainOverviewViewModel, ChainWorkflowItem, ChainAnomaly } from "./types.js";

export class ChainContentStore {
  constructor(private readonly artifactsRoot: string) {}

  getOverview(): ChainOverviewViewModel {
    const store = new ArtifactStore(this.artifactsRoot);
    const items: ChainWorkflowItem[] = store.getArtifactsIndex().map((item) => ({
      artifactId: item.id,
      title: item.title,
      category: item.id.split("/")[0] ?? "",
      department: item.department,
      workflowType: normalizeWorkflowType(item.workflow_type),
      chainPhase: item.chain_phase,
      status: item.status,
      feedUrl: item.url.replace(/^\/api\/artifacts/, "/feed")
    }));

    const anomalies: ChainAnomaly[] = items
      .filter((item) => item.status !== "completed")
      .map((item) => ({
        kind: "missing_result",
        artifactId: item.artifactId,
        workflowType: item.workflowType
      }));

    return {
      workflowGroups: {
        legacy_chain: items.filter((item) => item.workflowType === "legacy_chain"),
        trading_v2: items.filter((item) => item.workflowType === "trading_v2")
      },
      anomalies
    };
  }
}
```

Wire `/chain` routes in `7-ARTIFACT-HUB-V2/src/server.ts`:

```ts
const chainStore = new ChainContentStore(artifactsRoot);
if (req.method === "GET" && url.pathname === "/chain") {
  const html = renderChainIndexHtml(chainStore.getOverview());
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(html);
  return;
}

if (req.method === "GET" && /^\/chain\/[^/]+$/.test(url.pathname)) {
  const workflowType = decodeURIComponent(url.pathname.split("/")[2] ?? "");
  const html = renderChainIndexHtml(chainStore.getOverview(), workflowType);
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(html);
  return;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/chain/content.test.js dist/src/chain/routes.test.js
```

Expected: PASS with the new query layer and route scaffolding in place.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/chain/types.ts 7-ARTIFACT-HUB-V2/src/chain/content.ts 7-ARTIFACT-HUB-V2/src/chain/content.test.ts 7-ARTIFACT-HUB-V2/src/chain/routes.test.ts 7-ARTIFACT-HUB-V2/src/server.ts
git commit -m "feat(artifact-hub): add chain query layer and routes"
```

---

### Task 5: Render Chain Monitor Page And Feed/Chain Cross Links

**Files:**
- Create: `7-ARTIFACT-HUB-V2/src/chain/render.ts`
- Create: `7-ARTIFACT-HUB-V2/src/chain/render.test.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/server.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/render.ts`

- [ ] **Step 1: Write the failing tests for chain rendering and reverse links**

Create `7-ARTIFACT-HUB-V2/src/chain/render.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { renderChainIndexHtml } from "./render.js";

test("renderChainIndexHtml includes workflow groups, anomalies, and feed links", () => {
  const html = renderChainIndexHtml({
    workflowGroups: {
      legacy_chain: [
        {
          artifactId: "trading/a1",
          title: "A1",
          category: "trading",
          department: "trading",
          workflowType: "legacy_chain",
          chainPhase: "A3",
          status: "completed",
          feedUrl: "/feed/trading/a1"
        }
      ],
      trading_v2: []
    },
    anomalies: [{ kind: "missing_result", artifactId: "trading/a2", workflowType: "trading_v2" }]
  }, "legacy_chain");

  assert.match(html, /Chain Monitor/);
  assert.match(html, /legacy_chain/);
  assert.match(html, /missing_result/);
  assert.match(html, /href="\/feed\/trading\/a1"/);
});
```

Also add to `7-ARTIFACT-HUB-V2/src/feed/render.test.ts`:

```ts
test("renderFeedDetailHtml includes reverse link from content to chain monitor", () => {
  const html = renderFeedDetailHtml({
    id: "trading/a1",
    category: "trading",
    artifactId: "a1",
    filename: "a1.md",
    title: "A1",
    department: "trading",
    type: "report",
    status: "completed",
    date: "2026-05-20",
    chainPhase: "A3",
    tags: [],
    excerpt: "",
    url: "/feed/trading/a1",
    content: "# A1",
    rawPath: "/tmp/a1.md",
    governanceContext: {
      workflowId: "wf-1",
      workflowType: "legacy_chain",
      traceId: "trace-1",
      chainPhase: "A3"
    }
  });

  assert.match(html, /查看链路监控/);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/chain/render.test.js dist/src/feed/render.test.js
```

Expected: FAIL because the chain renderer does not yet exist and the feed reverse link is incomplete.

- [ ] **Step 3: Write minimal implementation**

Create `7-ARTIFACT-HUB-V2/src/chain/render.ts`:

```ts
import type { ChainOverviewViewModel } from "./types.js";

function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderChainIndexHtml(input: ChainOverviewViewModel, selectedWorkflowType?: string): string {
  const workflowType = selectedWorkflowType ?? "all";
  const legacyCards = input.workflowGroups.legacy_chain.map((item) => `
    <article class="chain-card">
      <h3>${escapeHtml(item.title)}</h3>
      <p>${escapeHtml(item.chainPhase)} · ${escapeHtml(item.status)}</p>
      <a href="${escapeHtml(item.feedUrl)}">查看产物</a>
    </article>
  `).join("");

  const anomalies = input.anomalies.map((item) => `<li>${escapeHtml(item.kind)} · ${escapeHtml(item.artifactId)}</li>`).join("");

  return `<!doctype html>
  <html lang="zh-CN">
    <head><meta charset="utf-8" /><title>Chain Monitor</title></head>
    <body>
      <main>
        <h1>Chain Monitor</h1>
        <p>workflow_type: ${escapeHtml(workflowType)}</p>
        <section>${legacyCards}</section>
        <aside><ul>${anomalies}</ul></aside>
      </main>
    </body>
  </html>`;
}
```

Update `7-ARTIFACT-HUB-V2/src/server.ts` imports:

```ts
import { renderChainIndexHtml } from "./chain/render.js";
```

Keep the `/feed` detail cross-link text:

```ts
<a href="/chain/${escapeHtml(detail.governanceContext.workflowType || "legacy_chain")}?artifactId=${escapeHtml(detail.artifactId)}">查看链路监控</a>
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/chain/render.test.js dist/src/feed/render.test.js
```

Expected: PASS and both directions of navigation are visible in rendered HTML.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/chain/render.ts 7-ARTIFACT-HUB-V2/src/chain/render.test.ts 7-ARTIFACT-HUB-V2/src/server.ts 7-ARTIFACT-HUB-V2/src/feed/render.ts 7-ARTIFACT-HUB-V2/src/feed/render.test.ts
git commit -m "feat(artifact-hub): render chain monitor and cross links"
```

---

### Task 6: Final Docs And Full Verification

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/README.md`
- Modify: `7-ARTIFACT-HUB-V2/OPS_UI_README.md`
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/chain/routes.test.ts`

- [ ] **Step 1: Write the failing tests for ui-map chain jump and final route coverage**

Add to `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`:

```ts
test("ops-ui ui-map exposes real chain entry after chain recovery", async () => {
  const prevHubUrl = process.env.HUB_URL;
  process.env.HUB_URL = "http://127.0.0.1:3456";
  const opsListener = await listen(createOpsServer());
  try {
    const res = await fetch(new URL("/ui-map", opsListener.url));
    const html = await res.text();
    assert.ok(html.includes('href="http://127.0.0.1:3456/chain"'));
    assert.ok(!html.includes('/planned?target=%2Fchain'));
  } finally {
    process.env.HUB_URL = prevHubUrl;
    await opsListener.close();
  }
});
```

- [ ] **Step 2: Run the full targeted test suite**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test \
  dist/src/feed/content.test.js \
  dist/src/feed/render.test.js \
  dist/src/feed/routes.test.js \
  dist/src/chain/content.test.js \
  dist/src/chain/render.test.js \
  dist/src/chain/routes.test.js \
  dist/src/ops-ui/ops-ui.test.js
```

Expected: any remaining failures now point to missing final route or documentation wiring.

- [ ] **Step 3: Update docs with final runtime instructions**

Update `7-ARTIFACT-HUB-V2/README.md` with:

```md
### Feed + Chain 当前访问方式

- `GET /feed`
- `GET /feed/:category`
- `GET /feed/:category/:artifactId`
- `GET /chain`
- `GET /chain/:workflowType`

本地推荐启动：

```bash
cd 7-ARTIFACT-HUB-V2
npm run build
node dist/index.js
OPS_UI_PORT=3457 HUB_URL=http://127.0.0.1:3456 node dist/ops-ui/server.js
```
```

Update `7-ARTIFACT-HUB-V2/OPS_UI_README.md` with:

```md
- `ui-map` 中 `feed` 与 `chain` 节点都应跳转到 Hub 真实页面
- 独立运行 `ops-ui` 时必须显式设置 `HUB_URL=http://127.0.0.1:3456`
- `ops-ui` 不承载 `/feed` 或 `/chain` 内容本身，只负责进入真实页面
```

- [ ] **Step 4: Run final browser and HTTP verification**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node dist/index.js
```

In a second terminal:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
OPS_UI_PORT=3457 HUB_URL=http://127.0.0.1:3456 node dist/ops-ui/server.js
```

Then verify:

```bash
python3 - <<'PY'
import urllib.request
for url in [
    "http://127.0.0.1:3456/feed",
    "http://127.0.0.1:3456/chain",
    "http://127.0.0.1:3457/ui-map?node=feed",
]:
    with urllib.request.urlopen(url, timeout=5) as r:
        print(url, r.status)
PY
```

And browser-check:

```bash
agent-browser open "http://127.0.0.1:3457/ui-map?node=feed" && agent-browser wait --load networkidle && agent-browser snapshot -i
```

Expected:

- `/feed` returns `200`
- `/chain` returns `200`
- `ui-map` contains real feed and chain links
- browser snapshot shows accessible entry points

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/README.md 7-ARTIFACT-HUB-V2/OPS_UI_README.md 7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts 7-ARTIFACT-HUB-V2/src/feed/routes.test.ts 7-ARTIFACT-HUB-V2/src/chain/routes.test.ts
git commit -m "docs(artifact-hub): document feed and chain runtime verification"
```

---

## Self-Review

### Spec coverage check

- Runtime alignment: covered by Task 1 and Task 6
- Real `/feed` enhancement: covered by Task 2 and Task 3
- Real `/chain` routes and monitoring page: covered by Task 4 and Task 5
- Feed/chain cross-linking: covered by Task 3 and Task 5
- Docs and validation: covered by Task 6

### Placeholder scan

- No `TODO`, `TBD`, or “implement later” placeholders remain.
- Every task includes exact files, test snippets, commands, and commit messages.

### Type consistency

- Query layer names are consistent:
  - `FeedContentStore`
  - `ChainContentStore`
  - `ChainOverviewViewModel`
  - `renderChainIndexHtml()`
- `/chain/:workflowType` is used consistently in tests, renderer links, and route wiring.
