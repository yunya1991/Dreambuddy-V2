# UI Map Monitoring Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `3457 /ui-map` into a stable monitoring map entry that sends users from the `feed` and `chain` nodes to the real Hub pages on `3456`.

**Architecture:** Keep `ops-ui` as an SSR entry layer only. Extend `src/ops-ui/ui-map.ts` to render a dedicated `chain` node, monitoring-first drawer content, and explicit primary actions; use `src/ops-ui/routes/index.ts` only to resolve Hub base URL and pass runtime status into the map; update tests and docs to freeze the `3457 = map` / `3456 = real pages` boundary.

**Tech Stack:** Node.js, TypeScript, SSR HTML string rendering, Express router, `node:test`

---

## File Map

### Existing files to modify

- `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
  - Add dedicated `chain` node, monitoring-entry drawer structure, and runtime status notice
- `7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`
  - Validate `HUB_URL`, probe Hub health for `/ui-map`, and pass status into renderer
- `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`
  - Add route/render coverage for node structure, absolute links, and invalid/unreachable Hub handling
- `7-ARTIFACT-HUB-V2/OPS_UI_README.md`
  - Freeze the `3457 -> 3456` monitoring-entry contract

### No new runtime files needed

- Reuse the current `ops-ui` SSR structure
- Do not add `/feed` or `/chain` proxy routes in `ops-ui`
- Do not add frontend frameworks or client-side state libraries

---

### Task 1: Add Failing Tests For Monitoring Map Nodes

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

- [ ] **Step 1: Write the failing test for dedicated `feed` and `chain` monitoring nodes**

Append this test to `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`:

```ts
test("ui-map exposes dedicated feed and chain monitoring nodes with canonical Hub links", async () => {
  const prevHubUrl = process.env.HUB_URL;
  delete process.env.OPS_UI_FEED_BASE_URL;
  process.env.HUB_URL = "http://127.0.0.1:3456";

  const opsListener = await listen(createOpsServer());
  try {
    const res = await fetch(new URL("/ui-map?node=feed", opsListener.url));
    assert.equal(res.status, 200);
    const html = await res.text();

    assert.ok(html.includes('id="stage-feed"'));
    assert.ok(html.includes('id="stage-chain"'));
    assert.ok(html.includes('data-node="feed"'));
    assert.ok(html.includes('data-node="chain"'));
    assert.ok(html.includes('href="http://127.0.0.1:3456/feed"'));
    assert.ok(html.includes('href="http://127.0.0.1:3456/chain"'));
    assert.ok(html.includes("进入 Feed 监控页"));
    assert.ok(html.includes("进入 Chain 监控页"));
  } finally {
    process.env.HUB_URL = prevHubUrl;
    await opsListener.close();
  }
});
```

- [ ] **Step 2: Write the failing test for monitoring-first drawer emphasis**

Append this test to the same file:

```ts
test("ui-map feed drawer keeps monitoring entry primary and demotes planned feed links", async () => {
  const prevHubUrl = process.env.HUB_URL;
  process.env.HUB_URL = "http://127.0.0.1:3456";

  const opsListener = await listen(createOpsServer());
  try {
    const res = await fetch(new URL("/ui-map?node=feed", opsListener.url));
    assert.equal(res.status, 200);
    const html = await res.text();

    assert.ok(html.includes("真实监控入口"));
    assert.ok(html.includes("当前目标地址"));
    assert.ok(!html.includes("Planned Links"));
    assert.ok(!html.includes('label: "/feed/[category]"'));
  } finally {
    process.env.HUB_URL = prevHubUrl;
    await opsListener.close();
  }
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/ops-ui/ops-ui.test.js
```

Expected: FAIL because the current map has no dedicated `chain` node and the drawer still emphasizes planned feed links.

- [ ] **Step 4: Commit the red test checkpoint**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts
git commit -m "test(artifact-hub): capture ui-map monitoring entry expectations"
```

---

### Task 2: Implement Dedicated Feed And Chain Monitoring Entry UI

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

- [ ] **Step 1: Add the dedicated `chain` node to the map canvas**

Update the node layout section in `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts` by adding styles and markup like this:

```ts
#stage-chain {
  --accent: #7dd3fc;
  top: 28px;
  left: 48%;
  width: 22%;
  min-height: 324px;
}
```

```html
<article class="node" id="stage-chain" data-node="chain" role="button" tabindex="0">
  <div class="header">
    <div class="eyeline">Monitoring Entry</div>
    <h3>Chain Monitor</h3>
    <p>链路监控入口，负责进入 workflow、trace、task、result 与异常状态的真实页面。</p>
  </div>
  <div class="body">
    <div class="grid-tiles">
      <div class="tile"><strong>/chain</strong><span>进入真实链路监控首页</span></div>
      <div class="tile"><strong>Workflow View</strong><span>从监控地图进入具体工作流视角</span></div>
    </div>
  </div>
</article>
```

- [ ] **Step 2: Replace drawer metadata for `feed` and `chain` with monitoring-entry content**

Update the `NODE_META` block in `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`:

```ts
feed: {
  title: "Feed Monitoring Entry",
  status: "implemented",
  description: "内容监控入口，负责把用户从治理地图送到 Hub 上的真实 /feed 页面。",
  links: [
    { href: "${feedHomeHref}", label: "进入 Feed 监控页", status: "implemented" }
  ],
  targetUrl: "${feedHomeHref}",
  notes: [
    "查看部门、阶段、类型、标签与正文语义",
    "此入口不承载真实内容，只负责进入 Hub 页面"
  ]
},
chain: {
  title: "Chain Monitoring Entry",
  status: "implemented",
  description: "链路监控入口，负责把用户从治理地图送到 Hub 上的真实 /chain 页面。",
  links: [
    { href: "${chainHomeHref}", label: "进入 Chain 监控页", status: "implemented" }
  ],
  targetUrl: "${chainHomeHref}",
  notes: [
    "查看 workflow、trace、task、result 与异常状态",
    "此入口不承载真实监控内容，只负责进入 Hub 页面"
  ]
}
```

- [ ] **Step 3: Change drawer rendering to a monitoring-entry structure**

Replace the current generic `renderDrawer()` body in `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts` with:

```ts
function renderDrawer(meta) {
  if (!drawerTitle || !drawerBody) return;
  drawerTitle.textContent = meta.title;
  drawerBody.innerHTML = [
    '<div class="drawer-block">',
    '<span class="drawer-status">' + meta.status + "</span>",
    "<p>" + meta.description + "</p>",
    "</div>",
    '<div class="drawer-block"><h4>真实监控入口</h4><ul>' +
      meta.links.map((item) => renderDrawerLink(item)).join("") +
    "</ul></div>",
    '<div class="drawer-block"><h4>当前目标地址</h4><p><code>' + escapeHtml(meta.targetUrl) + "</code></p></div>",
    '<div class="drawer-block"><h4>运行说明</h4><ul>' +
      meta.notes.map((item) => "<li>" + escapeHtml(item) + "</li>").join("") +
    "</ul></div>"
  ].join("");
}
```

- [ ] **Step 4: Remove planned feed links from the primary `feed` drawer path**

Delete the planned feed route entries from the `feed` node metadata in `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`:

```ts
{
  href: "/planned?target=%2Ffeed%2F%5Bcategory%5D&label=%2Ffeed%2F%5Bcategory%5D&node=feed&module=Feed",
  label: "/feed/[category]",
  status: "planned"
},
{
  href: "/planned?target=%2Ffeed%2F%5Bcategory%5D%2F%5BartifactId%5D&label=%2Ffeed%2F%5Bcategory%5D%2F%5BartifactId%5D&node=feed&module=Feed",
  label: "/feed/[category]/[artifactId]",
  status: "planned"
}
```

Keep planned links only on nodes that are still genuinely planned, such as `query` and `data`.

- [ ] **Step 5: Run tests to verify the UI behavior passes**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/ops-ui/ops-ui.test.js
```

Expected: PASS for the new `feed`/`chain` node expectations and no regressions in existing `/ui-map` tests.

- [ ] **Step 6: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts 7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts
git commit -m "feat(artifact-hub): turn ui-map into feed and chain monitoring entry"
```

---

### Task 3: Add Hub URL Validation And Unreachable Target Notice

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
- Modify: `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

- [ ] **Step 1: Write the failing test for invalid `HUB_URL`**

Append this test to `7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`:

```ts
test("ui-map shows a clear notice when HUB_URL is invalid", async () => {
  const prevHubUrl = process.env.HUB_URL;
  process.env.HUB_URL = "not-a-url";

  const opsListener = await listen(createOpsServer());
  try {
    const res = await fetch(new URL("/ui-map?node=feed", opsListener.url));
    assert.equal(res.status, 200);
    const html = await res.text();

    assert.ok(html.includes("目标监控页当前不可达"));
    assert.ok(html.includes("请检查 Hub 3456 是否已启动"));
    assert.ok(!html.includes('href="not-a-url/feed"'));
  } finally {
    process.env.HUB_URL = prevHubUrl;
    await opsListener.close();
  }
});
```

- [ ] **Step 2: Write the failing test for unreachable Hub**

Append this test to the same file:

```ts
test("ui-map shows an unavailable notice when hub health probe fails", async () => {
  const prevHubUrl = process.env.HUB_URL;
  process.env.HUB_URL = "http://127.0.0.1:6553";

  const opsListener = await listen(createOpsServer());
  try {
    const res = await fetch(new URL("/ui-map?node=chain", opsListener.url));
    assert.equal(res.status, 200);
    const html = await res.text();

    assert.ok(html.includes("目标监控页当前不可达"));
    assert.ok(html.includes("请检查 Hub 3456 是否已启动"));
    assert.ok(html.includes("http://127.0.0.1:6553/chain"));
  } finally {
    process.env.HUB_URL = prevHubUrl;
    await opsListener.close();
  }
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/ops-ui/ops-ui.test.js
```

Expected: FAIL because `/ui-map` does not yet validate Hub target health or render an unavailable notice.

- [ ] **Step 4: Implement Hub validation and probe status in the router**

Update `7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`:

```ts
type UiMapHubStatus =
  | { kind: "ok"; baseUrl: string }
  | { kind: "invalid"; baseUrl: string | null }
  | { kind: "unreachable"; baseUrl: string };

async function resolveUiMapHubStatus(feedBaseUrl: string): Promise<UiMapHubStatus> {
  if (!feedBaseUrl) return { kind: "invalid", baseUrl: null };
  try {
    new URL(feedBaseUrl);
  } catch {
    return { kind: "invalid", baseUrl: null };
  }

  const health = await safeFetchJson(new URL("/health", feedBaseUrl).toString());
  return health.ok ? { kind: "ok", baseUrl: feedBaseUrl } : { kind: "unreachable", baseUrl: feedBaseUrl };
}
```

Then change the `/ui-map` route handler:

```ts
router.get("/ui-map", async (_req: Request, res: Response) => {
  const hubStatus = await resolveUiMapHubStatus(feedBaseUrl);
  return sendHtml(
    res,
    200,
    renderUiMapHtml({
      host: "127.0.0.1",
      port: Number(process.env.OPS_UI_PORT || 3457),
      feedBaseUrl,
      hubStatus
    })
  );
});
```

- [ ] **Step 5: Render the unavailable notice in the drawer**

Update the `renderUiMapHtml()` signature and drawer notice handling in `7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`:

```ts
export function renderUiMapHtml(params: {
  host: string;
  port: number;
  feedBaseUrl: string;
  hubStatus: { kind: "ok" | "invalid" | "unreachable"; baseUrl: string | null };
}): string
```

Add a helper:

```ts
function renderHubStatusNotice(hubStatus: { kind: "ok" | "invalid" | "unreachable"; baseUrl: string | null }): string {
  if (hubStatus.kind === "ok") return "";
  return [
    '<div class="drawer-block">',
    "<h4>运行状态提示</h4>",
    "<p>目标监控页当前不可达。</p>",
    "<p>请检查 Hub 3456 是否已启动。</p>",
    hubStatus.baseUrl ? "<p><code>" + escapeHtml(hubStatus.baseUrl) + "</code></p>" : "",
    "</div>"
  ].join("");
}
```

And insert it inside `renderDrawer(meta)` after the target URL block:

```ts
+ renderHubStatusNotice(HUB_STATUS),
```

Represent `hubStatus` in the page script with:

```ts
const HUB_STATUS = ${JSON.stringify(hubStatus)};
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/ops-ui/ops-ui.test.js
```

Expected: PASS and `/ui-map` now clearly separates invalid/unreachable Hub target issues from map rendering.

- [ ] **Step 7: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts 7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts 7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts
git commit -m "fix(artifact-hub): show ui-map monitoring target status"
```

---

### Task 4: Update Ops UI Documentation And Final Verification

**Files:**
- Modify: `7-ARTIFACT-HUB-V2/OPS_UI_README.md`

- [ ] **Step 1: Update the runtime contract in `OPS_UI_README.md`**

Replace the local access section in `7-ARTIFACT-HUB-V2/OPS_UI_README.md` with:

```md
## 8.1 本地访问与验证约定

- `http://127.0.0.1:3457/ui-map?node=feed` 是监控地图入口
- `http://127.0.0.1:3457/ui-map?node=chain` 是链路监控地图入口
- `http://127.0.0.1:3456/feed` 是真实内容监控页
- `http://127.0.0.1:3456/chain` 是真实链路监控页
- `ops-ui` 只负责入口、状态说明与上下文跳转，不承载 `/feed` 或 `/chain` 真实内容
- `HUB_URL` 默认应指向 `http://127.0.0.1:3456`
```

- [ ] **Step 2: Run the focused test suite**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2
npm run build
node --test dist/src/ops-ui/ops-ui.test.js
```

Expected: PASS for all `ops-ui` tests after the doc-aligned runtime changes.

- [ ] **Step 3: Run a browser/manual verification checklist**

Verify these URLs in the browser:

```text
http://127.0.0.1:3457/ui-map?node=feed
http://127.0.0.1:3457/ui-map?node=chain
http://127.0.0.1:3456/feed
http://127.0.0.1:3456/chain
```

Confirm:

- `feed` drawer opens by default from `?node=feed`
- `chain` drawer opens by default from `?node=chain`
- `feed` primary action jumps to `3456 /feed`
- `chain` primary action jumps to `3456 /chain`
- the drawer shows monitoring-entry wording, not planned-route wording

- [ ] **Step 4: Commit**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 7-ARTIFACT-HUB-V2/OPS_UI_README.md
git commit -m "docs(artifact-hub): document ui-map monitoring entry contract"
```

---

## Self-Review

### Spec coverage

- `3457 = map`, `3456 = real pages`: covered by Task 2 and Task 4
- dedicated `feed` and `chain` monitoring nodes: covered by Task 1 and Task 2
- no content proxy in `ops-ui`: enforced in Task 2 and Task 3 by limiting router changes to URL/status only
- invalid/unreachable Hub messaging: covered by Task 3
- documentation alignment: covered by Task 4

### Placeholder scan

- No `TODO`, `TBD`, or “implement later” markers remain
- Each task has explicit files, code snippets, commands, and expected outcomes

### Type consistency

- `renderUiMapHtml()` gains a `hubStatus` parameter and Task 3 updates both caller and renderer
- `NODE_META.feed` and `NODE_META.chain` both use `links`, `targetUrl`, and `notes`
- The runtime contract consistently uses `HUB_URL` as the canonical base

