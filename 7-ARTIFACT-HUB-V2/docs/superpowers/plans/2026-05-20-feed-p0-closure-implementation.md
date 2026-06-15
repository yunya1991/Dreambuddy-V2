# Feed P0 Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local `/feed` reach the agreed P0 closure by exposing Chinese department entrances, fixed `A0-A9` stage entrances, a temporary `做梦部` mapping, and detail pages with explicit Chinese classification fields.

**Architecture:** Keep the current SSR `/feed` route and reuse `FeedContentStore`, but add a P0-oriented mapping layer inside `src/feed/*` so the homepage can render product-facing department/stage entrances instead of raw engineering categories. Reuse current repo-local artifacts as the source of truth and apply temporary mapping rules for `做梦部`, `知识库`, and `治理部` without introducing a new storage system.

**Tech Stack:** Node.js, TypeScript, `node:test`, SSR HTML, repo-local JSON artifacts

---

## File Map

### Existing files to modify

- `7-ARTIFACT-HUB-V2/src/feed/types.ts`
  - Add P0-facing department/stage label fields and homepage summary structures
- `7-ARTIFACT-HUB-V2/src/feed/content.ts`
  - Add temporary department mapping, fixed `A0-A9` summary generation, and `做梦部` assignment rule
- `7-ARTIFACT-HUB-V2/src/feed/render.ts`
  - Replace engineering filter-first homepage with P0 entrances and Chinese detail fields
- `7-ARTIFACT-HUB-V2/src/feed/content.test.ts`
  - TDD for mapping and summary generation
- `7-ARTIFACT-HUB-V2/src/feed/render.test.ts`
  - TDD for homepage entrances and detail field output
- `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`
  - TDD for homepage, department entrance, and A-stage entrance behavior
- `7-ARTIFACT-HUB-V2/src/server.ts`
  - Pass P0 query fields and support entrance-driven list rendering

### Supporting docs to update after behavior lands

- `7-ARTIFACT-HUB-V2/README.md`
- `7-ARTIFACT-HUB-V2/OPS_UI_README.md`

---

### Task 1: Freeze P0 Mapping Rules In Feed Query Layer

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/feed/types.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/content.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/content.test.ts`

- [ ] **Step 1: Write the failing tests**

Add tests to `7-ARTIFACT-HUB-V2/src/feed/content.test.ts` covering:

```ts
test("FeedContentStore maps current sources to Chinese P0 departments", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-p0-departments-"));
  fs.mkdirSync(path.join(root, "research"), { recursive: true });
  fs.mkdirSync(path.join(root, "governance"), { recursive: true });
  fs.mkdirSync(path.join(root, "trading"), { recursive: true });

  fs.writeFileSync(
    path.join(root, "research", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        { artifact_id: "research/intel-a1", title: "Intel", chain_phase: "A1", type: "report", status: "completed", tags: ["market-analysis"] },
        { artifact_id: "research/dream-note-001", title: "Dream Note", chain_phase: "A3", type: "note", status: "completed", tags: ["dream", "oneirology"] }
      ]
    })
  );
  fs.writeFileSync(
    path.join(root, "governance", "index.json"),
    JSON.stringify({ last_updated: "2026-05-20T00:00:00Z", artifacts: [{ artifact_id: "governance/audit-001", title: "Audit", status: "completed" }] })
  );
  fs.writeFileSync(
    path.join(root, "trading", "index.json"),
    JSON.stringify({ last_updated: "2026-05-20T00:00:00Z", artifacts: [{ artifact_id: "trading/order-001", title: "Order", chain_phase: "A9", status: "completed" }] })
  );

  const store = new FeedContentStore(root);
  const all = store.listArtifacts();
  assert.equal(all.find((item) => item.id === "research/dream-note-001")?.departmentLabel, "做梦部");
  assert.equal(all.find((item) => item.id === "research/intel-a1")?.departmentLabel, "知识库");
  assert.equal(all.find((item) => item.id === "governance/audit-001")?.departmentLabel, "治理部");
  assert.equal(all.find((item) => item.id === "trading/order-001")?.departmentLabel, "交易部");
  fs.rmSync(root, { recursive: true, force: true });
});

test("FeedContentStore exposes fixed A0-A9 summary with zero-count stages", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-p0-stages-"));
  fs.mkdirSync(path.join(root, "research"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "research", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [{ artifact_id: "research/intel-a1", title: "Intel", chain_phase: "A1", status: "completed" }]
    })
  );

  const store = new FeedContentStore(root);
  const summary = store.getHomepageSummary();
  assert.deepEqual(summary.stageEntries.map((item) => item.label), ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"]);
  assert.equal(summary.stageEntries.find((item) => item.label === "A1")?.count, 1);
  assert.equal(summary.stageEntries.find((item) => item.label === "A0")?.count, 0);
  fs.rmSync(root, { recursive: true, force: true });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/feed/content.test.js
```

Expected: FAIL because `departmentLabel`, `getHomepageSummary()`, and temporary `做梦部` mapping do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Extend `7-ARTIFACT-HUB-V2/src/feed/types.ts` with:

```ts
export interface FeedEntranceItem {
  label: string;
  count: number;
  href: string;
}

export interface FeedHomepageSummary {
  departmentEntries: FeedEntranceItem[];
  stageEntries: FeedEntranceItem[];
}
```

Add `departmentLabel` and `typeLabel` to `FeedListItem`, then implement in `7-ARTIFACT-HUB-V2/src/feed/content.ts`:

```ts
const FIXED_STAGE_LABELS = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"] as const;

function resolveDepartmentLabel(item: { category: string; tags: string[]; title: string }): string {
  if (item.category === "trading") return "交易部";
  if (item.category === "governance") return "治理部";
  const dreamSignals = [item.title, item.tags.join(" ")].join(" ").toLowerCase();
  if (dreamSignals.includes("dream") || dreamSignals.includes("oneirology")) return "做梦部";
  return "知识库";
}

getHomepageSummary(): FeedHomepageSummary {
  const items = this.listArtifacts();
  const departmentEntries = ["交易部", "做梦部", "治理部", "知识库"].map((label) => ({
    label,
    count: items.filter((item) => item.departmentLabel === label).length,
    href: `/feed?department=${encodeURIComponent(label)}`
  }));
  const stageEntries = FIXED_STAGE_LABELS.map((label) => ({
    label,
    count: items.filter((item) => item.chainPhase === label).length,
    href: `/feed?chainPhase=${encodeURIComponent(label)}`
  }));
  return { departmentEntries, stageEntries };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/feed/content.test.js
```

Expected: PASS with P0 mapping and fixed-stage summaries green.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/feed/types.ts 7-ARTIFACT-HUB-V2/src/feed/content.ts 7-ARTIFACT-HUB-V2/src/feed/content.test.ts
git commit -m "feat(artifact-hub): add feed p0 mapping rules"
```

---

### Task 2: Replace Filter-First Homepage With P0 Entrances

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/feed/render.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/render.test.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/server.ts`

- [ ] **Step 1: Write the failing tests**

Add to `7-ARTIFACT-HUB-V2/src/feed/render.test.ts`:

```ts
test("renderFeedIndexHtml shows Chinese department entrances and fixed A0-A9 stage entrances", () => {
  const html = renderFeedIndexHtml({
    title: "Dream 产物中心",
    items: [],
    stats: { total: 0, byDepartment: {}, byType: {}, byStatus: {}, byChainPhase: {} },
    query: {},
    summary: {
      departmentEntries: [
        { label: "交易部", count: 1, href: "/feed?department=%E4%BA%A4%E6%98%93%E9%83%A8" },
        { label: "做梦部", count: 1, href: "/feed?department=%E5%81%9A%E6%A2%A6%E9%83%A8" },
        { label: "治理部", count: 1, href: "/feed?department=%E6%B2%BB%E7%90%86%E9%83%A8" },
        { label: "知识库", count: 1, href: "/feed?department=%E7%9F%A5%E8%AF%86%E5%BA%93" }
      ],
      stageEntries: ["A0","A1","A2","A3","A4","A5","A6","A7","A8","A9"].map((label) => ({ label, count: label === "A1" ? 1 : 0, href: `/feed?chainPhase=${label}` }))
    }
  });

  assert.match(html, /交易部/);
  assert.match(html, /做梦部/);
  assert.match(html, /A0/);
  assert.match(html, /A9/);
  assert.doesNotMatch(html, /name="Department"/);
});
```

Add to `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`:

```ts
test("createHubServer exposes P0 department and stage entrances on /feed", async () => {
  const res = await fetch(`${baseUrl}/feed`);
  const html = await res.text();
  assert.match(html, /做梦部/);
  assert.match(html, /A0/);
  assert.match(html, /A9/);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/feed/render.test.js dist/feed/routes.test.js
```

Expected: FAIL because homepage rendering does not yet accept `summary` or show the fixed P0 entrances.

- [ ] **Step 3: Write minimal implementation**

Update `renderFeedIndexHtml()` signature:

```ts
export function renderFeedIndexHtml(input: {
  title: string;
  items: FeedListItem[];
  stats: FeedStats;
  query: FeedQuery;
  summary: FeedHomepageSummary;
}): string
```

Replace the current filter-first block in `7-ARTIFACT-HUB-V2/src/feed/render.ts` with two explicit entrance rows:

```ts
<section class="entry-section">
  <h2>部门入口</h2>
  <div class="entry-row">${input.summary.departmentEntries.map(renderEntryButton).join("")}</div>
</section>
<section class="entry-section">
  <h2>A 系列</h2>
  <div class="entry-row">${input.summary.stageEntries.map(renderEntryButton).join("")}</div>
</section>
```

Keep search, list cards, and pagination, but remove `Category / Department / Status / Chain Phase / Limit / Offset` from the primary surface.

In `7-ARTIFACT-HUB-V2/src/server.ts`, pass `feedStore.getHomepageSummary()` into `renderFeedIndexHtml()`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/feed/render.test.js dist/feed/routes.test.js
```

Expected: PASS with Chinese department entrances and `A0-A9` visible on `/feed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/feed/render.ts 7-ARTIFACT-HUB-V2/src/feed/render.test.ts 7-ARTIFACT-HUB-V2/src/feed/routes.test.ts 7-ARTIFACT-HUB-V2/src/server.ts
git commit -m "feat(artifact-hub): render feed p0 homepage entrances"
```

---

### Task 3: Make Department And Stage Entrances Produce Real Lists

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/feed/content.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/server.ts`

- [ ] **Step 1: Write the failing tests**

Add to `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`:

```ts
test("department entrance for 做梦部 returns a non-empty list using temporary research mapping", async () => {
  const res = await fetch(`${baseUrl}/feed?department=${encodeURIComponent("做梦部")}`);
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.match(html, /做梦部/);
  assert.match(html, /Dream|dream|oneirology/);
});

test("A-stage entrance for A1 returns matching items and A0 returns an empty-state list", async () => {
  const a1 = await fetch(`${baseUrl}/feed?chainPhase=A1`);
  const a0 = await fetch(`${baseUrl}/feed?chainPhase=A0`);
  assert.equal(a1.status, 200);
  assert.equal(a0.status, 200);
  assert.match(await a1.text(), /A1/);
  assert.match(await a0.text(), /No artifacts found|暂无相关产物/);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/feed/routes.test.js
```

Expected: FAIL because current list filtering still uses raw engineering categories and raw department values.

- [ ] **Step 3: Write minimal implementation**

Update `listArtifacts()` department filtering in `7-ARTIFACT-HUB-V2/src/feed/content.ts`:

```ts
if (query.department && item.departmentLabel !== query.department) return false;
```

Ensure each list item includes:

```ts
departmentLabel: resolveDepartmentLabel({ category, tags: normalizeTags(entry.tags), title: entry.title || artifactId }),
typeLabel: resolveTypeLabel(entry.type || "knowledge")
```

Make the empty state explicit in `renderFeedIndexHtml()`:

```ts
const cards = input.items.length > 0 ? input.items.map(renderCard).join("") : "<p>暂无相关产物。</p>";
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/feed/routes.test.js dist/feed/content.test.js
```

Expected: PASS with `做梦部` and `A1/A0` entrance behavior green.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/feed/content.ts 7-ARTIFACT-HUB-V2/src/feed/routes.test.ts 7-ARTIFACT-HUB-V2/src/server.ts
git commit -m "feat(artifact-hub): wire feed p0 entrance lists"
```

---

### Task 4: Freeze Chinese Detail Fields For P0

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/feed/render.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/render.test.ts`

- [ ] **Step 1: Write the failing tests**

Add to `7-ARTIFACT-HUB-V2/src/feed/render.test.ts`:

```ts
test("renderFeedDetailHtml shows fixed Chinese classification fields for P0", () => {
  const html = renderFeedDetailHtml({
    id: "research/intel-report-001",
    category: "research",
    artifactId: "intel-report-001",
    filename: "intel-report-001.md",
    title: "BTC市场情报分析报告",
    department: "research",
    departmentLabel: "知识库",
    type: "report",
    typeLabel: "报告",
    status: "completed",
    date: "2026-05-20",
    chainPhase: "A1",
    tags: ["bitcoin", "market-analysis"],
    excerpt: "alpha",
    url: "/feed/research/intel-report-001",
    content: "# Report",
    rawPath: "/tmp/intel-report-001.md",
    governanceContext: {
      workflowId: "wf-1",
      workflowType: "trading_v2",
      traceId: "trace-1",
      chainPhase: "A1"
    }
  });

  assert.match(html, /部门/);
  assert.match(html, /知识库/);
  assert.match(html, /阶段/);
  assert.match(html, /A1/);
  assert.match(html, /类型/);
  assert.match(html, /报告/);
  assert.match(html, /标签/);
  assert.match(html, /bitcoin/);
  assert.match(html, /查看链路监控/);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/feed/render.test.js
```

Expected: FAIL because the detail page does not yet render the fixed Chinese classification block.

- [ ] **Step 3: Write minimal implementation**

In `7-ARTIFACT-HUB-V2/src/feed/render.ts`, replace the current free-form detail meta block with:

```ts
<aside class="detail-side">
  <h2>分类信息</h2>
  <p><strong>部门</strong>：${escapeHtml(detail.departmentLabel || "未归类")}</p>
  <p><strong>阶段</strong>：${escapeHtml(detail.chainPhase || "未分阶段")}</p>
  <p><strong>类型</strong>：${escapeHtml(detail.typeLabel || "未知类型")}</p>
  <p><strong>标签</strong>：${escapeHtml(detail.tags.join(", ") || "无标签")}</p>
  <hr />
  <h2>治理上下文</h2>
  <p>trace_id: ${escapeHtml(detail.governanceContext?.traceId || "none")}</p>
  <p>workflow: ${escapeHtml(detail.governanceContext?.workflowType || "legacy_chain")}</p>
  <p><a href="${escapeHtml(buildChainDetailHref(detail))}">查看链路监控</a></p>
</aside>
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/feed/render.test.js
```

Expected: PASS with the fixed P0 detail classification fields visible.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/feed/render.ts 7-ARTIFACT-HUB-V2/src/feed/render.test.ts
git commit -m "feat(artifact-hub): freeze feed p0 detail fields"
```

---

### Task 5: P0 Docs And Final Verification

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/README.md`
- Modify: `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`

- [ ] **Step 1: Write the failing tests**

Add to `7-ARTIFACT-HUB-V2/src/feed/routes.test.ts`:

```ts
test("feed P0 homepage exposes 做梦部 and fixed A0-A9 entrances", async () => {
  const res = await fetch(`${baseUrl}/feed`);
  const html = await res.text();
  assert.match(html, /做梦部/);
  for (const label of ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"]) {
    assert.match(html, new RegExp(label));
  }
});
```

- [ ] **Step 2: Run the targeted test suite**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/feed/content.test.js dist/feed/render.test.js dist/feed/routes.test.js
```

Expected: Any remaining failures now point to missing P0 homepage/detail wiring.

- [ ] **Step 3: Update docs**

Update `7-ARTIFACT-HUB-V2/README.md` to explicitly document:

```md
### Feed P0 最小闭环

- 首页固定显示 `交易部 / 做梦部 / 治理部 / 知识库`
- 首页固定显示 `A0-A9`
- 当前真数据阶段为 `A1 / A3 / A9`
- 无数据阶段先显示 `0`
- `做梦部` 当前先由 `research` 中临时映射的内容承接
```

- [ ] **Step 4: Run browser and HTTP verification**

Run:

```bash
python3 - <<'PY'
import urllib.request
for url in [
    "http://127.0.0.1:3456/feed",
    "http://127.0.0.1:3456/feed?department=%E5%81%9A%E6%A2%A6%E9%83%A8",
    "http://127.0.0.1:3456/feed?chainPhase=A1",
    "http://127.0.0.1:3456/feed?chainPhase=A0",
]:
    with urllib.request.urlopen(url, timeout=5) as r:
        print(url, r.status)
PY
```

Then browser-check:

```bash
agent-browser open "http://127.0.0.1:3456/feed" && agent-browser wait --load networkidle && agent-browser snapshot -i
```

Expected:

- homepage shows `做梦部`
- homepage shows `A0-A9`
- `做梦部` entrance is non-empty
- `A1` entrance is non-empty
- `A0` entrance shows the explicit empty state

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/README.md 7-ARTIFACT-HUB-V2/src/feed/routes.test.ts
git commit -m "docs(artifact-hub): document feed p0 closure"
```

---

## Self-Review

### Spec coverage check

- Chinese department entrances: covered by Task 1 and Task 2
- Fixed `A0-A9` entrances: covered by Task 1, Task 2, and Task 5
- Temporary `做梦部` mapping: covered by Task 1 and Task 3
- Fixed Chinese detail fields: covered by Task 4
- Browser/runtime verification: covered by Task 5

### Placeholder scan

- No `TODO`, `TBD`, or “implement later” placeholders remain.
- Every task includes exact files, tests, commands, and commit messages.

### Type consistency

- `departmentLabel`, `typeLabel`, and `FeedHomepageSummary` are introduced once and reused consistently.
- Query entry URLs stay on `/feed?department=...` and `/feed?chainPhase=...` throughout the plan.
