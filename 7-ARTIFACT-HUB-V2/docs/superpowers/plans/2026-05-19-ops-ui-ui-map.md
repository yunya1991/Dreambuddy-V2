# Ops UI `/ui-map` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `7-ARTIFACT-HUB-V2` 的 ops-ui `GET /ui-map` 落地为 “Tabs + 右侧抽屉 + Docs” 的可用页面，用于对齐治理信息架构与后续页面建设。

**Architecture:** 保持当前 `renderUiMapHtml()` 的“服务端拼 HTML + 少量原生 JS”模式；在同一页面内实现顶层 Tabs（Map/Prototypes/Docs），Map 节点点击打开右侧抽屉展示详情，Docs Tab 输出文档链接/路由清单/环境变量/实现状态。

**Tech Stack:** Node.js + TypeScript + Express（现有）；Node test runner（现有 `node:test`）。

---

## File Structure (to modify)

- Modify: [/src/ops-ui/server.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/server.ts)
- Modify: [/src/ops-ui/ui-map.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts)
- Modify: [/src/ops-ui/ops-ui.test.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts)
- Optional Modify: [/README.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/README.md)（把 ops-ui 从“规划中”更新为“已存在”）
- Optional Modify: [/OPS_UI_README.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/OPS_UI_README.md)

---

### Task 1: Fix ops-ui default port to 3457

**Files:**
- Modify: [/src/ops-ui/server.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/server.ts)

- [ ] **Step 1: Update default port**

Change:

```ts
const port = opts?.port ?? Number(process.env.OPS_UI_PORT || 3456);
```

To:

```ts
const port = opts?.port ?? Number(process.env.OPS_UI_PORT || 3457);
```

- [ ] **Step 2: Build to ensure TS compiles**

Run:

```bash
npm run build
```

Expected: exit code 0.

---

### Task 2: Introduce top-level Tabs (Map / Prototypes / Docs)

**Files:**
- Modify: [/src/ops-ui/ui-map.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts)
- Test: [/src/ops-ui/ops-ui.test.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts)

- [ ] **Step 1: Write failing test for Tabs skeleton**

Add assertions to the existing test `ops-ui exposes ui map page with visual architecture sections`:

```ts
assert.ok(html.includes("Map"));
assert.ok(html.includes("Prototypes"));
assert.ok(html.includes("Docs"));
assert.ok(html.includes('data-root-tab="map"'));
assert.ok(html.includes('data-root-tab="prototypes"'));
assert.ok(html.includes('data-root-tab="docs"'));
```

Expected: FAIL initially（现有页面没有顶层 Tabs 结构）。

- [ ] **Step 2: Implement root tabs HTML skeleton**

In `renderUiMapHtml()`:

1) Add root tab buttons near the top (after hero), e.g.

```html
<div class="root-tabs" role="tablist" aria-label="ui-map root tabs">
  <button class="root-tab-btn active" type="button" data-root-tab="map">Map</button>
  <button class="root-tab-btn" type="button" data-root-tab="prototypes">Prototypes</button>
  <button class="root-tab-btn" type="button" data-root-tab="docs">Docs</button>
</div>
```

2) Wrap existing sections into root panels, e.g.

```html
<section class="root-panel active" data-root-panel="map"> ... hero + canvas ... </section>
<section class="root-panel" data-root-panel="prototypes"> ... 现有“页面原型预览” ... </section>
<section class="root-panel" data-root-panel="docs"> ... 新增 Docs 内容（Task 4） ... </section>
```

3) Add CSS rules mirroring existing `.tab-btn` / `.preview-panel` toggling style:

- `.root-tabs` container
- `.root-tab-btn` / `.root-tab-btn.active`
- `.root-panel` / `.root-panel.active`

- [ ] **Step 3: Add JS to switch root tabs**

Extend the current inline script (already handles `.tab-btn` and `.diagram-btn`) to also handle `.root-tab-btn`:

```js
const rootButtons = Array.from(document.querySelectorAll(".root-tab-btn"));
const rootPanels = Array.from(document.querySelectorAll(".root-panel"));

function activateRootTab(name) {
  rootButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.rootTab === name));
  rootPanels.forEach((panel) => panel.classList.toggle("active", panel.dataset.rootPanel === name));
}

rootButtons.forEach((btn) => {
  btn.addEventListener("click", () => activateRootTab(btn.dataset.rootTab || "map"));
});
```

- [ ] **Step 4: Run tests**

Run:

```bash
npm run build
npm test
```

Expected: tests PASS.

---

### Task 3: Map Tab node click → right-side drawer

**Files:**
- Modify: [/src/ops-ui/ui-map.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts)
- Test: [/src/ops-ui/ops-ui.test.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts)

- [ ] **Step 1: Write failing test for drawer skeleton**

Extend the ui-map test:

```ts
assert.ok(html.includes('id="uiMapDrawer"'));
assert.ok(html.includes('data-node="feed"'));
assert.ok(html.includes('data-node="ops"'));
assert.ok(html.includes('data-node="query"'));
assert.ok(html.includes('data-node="hub"'));
assert.ok(html.includes('data-node="data"'));
```

Expected: FAIL initially（暂无 drawer，节点无 data-node）。

- [ ] **Step 2: Add clickable node attributes**

Update the five `<article class="node" id="stage-...">` nodes to include:

```html
data-node="feed"
role="button"
tabindex="0"
```

Node mapping:

- `#stage-feed` → `data-node="feed"`
- `#stage-ops` → `data-node="ops"`
- `#stage-query` → `data-node="query"`
- `#stage-hub` → `data-node="hub"`
- `#stage-data` → `data-node="data"`

- [ ] **Step 3: Implement drawer HTML**

Add a drawer element inside Map Tab panel, e.g. near the canvas end:

```html
<aside class="drawer" id="uiMapDrawer" aria-hidden="true">
  <div class="drawer-header">
    <strong id="drawerTitle">—</strong>
    <button type="button" class="drawer-close" id="drawerCloseBtn">Close</button>
  </div>
  <div class="drawer-body" id="drawerBody"></div>
</aside>
```

- [ ] **Step 4: Implement drawer CSS**

Add CSS for a right-side sliding drawer:

- fixed/absolute within Map panel (prefer `position: sticky` + `top`, or `position: fixed` with `right: 24px` depending on layout)
- open/close states via a class like `.drawer.open`
- ensure on small screens（existing `@media (max-width: 1280px)`）drawer becomes stacked (e.g. full width under canvas) or overlays

- [ ] **Step 5: Implement drawer data model**

In inline script, create a map:

```js
const NODE_META = {
  feed: { title: "Feed Content Portal", description: "...", links: [...], apis: [...], status: "planned|implemented" },
  ops:  { ... },
  query:{ ... },
  hub:  { ... },
  data: { ... }
};
```

Populate values to match the spec:

- description: 1-2 段短文
- links: routes (`/`, `/ui-map`, `/health`, `/api/ops/queues`, `/api/ops/strategy-library`, `/api/ops/strategy-library/file?id=...`)
- apis: provide sample curl / JSON snippets
- status: `implemented/planned`（用 pill 样式）

- [ ] **Step 6: Implement click/keyboard handlers**

Behavior:

- clicking a node opens drawer and renders its content
- pressing Enter/Space on focused node triggers open
- close button closes drawer
- optional: `Escape` closes drawer

Implementation sketch:

```js
const drawer = document.getElementById("uiMapDrawer");
const drawerTitle = document.getElementById("drawerTitle");
const drawerBody = document.getElementById("drawerBody");
const closeBtn = document.getElementById("drawerCloseBtn");

function openDrawer(key) { ... }
function closeDrawer() { ... }
```

- [ ] **Step 7: Run tests**

Run:

```bash
npm run build
npm test
```

Expected: PASS.

---

### Task 4: Docs Tab content (1/2/3/4)

**Files:**
- Modify: [/src/ops-ui/ui-map.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts)
- Test: [/src/ops-ui/ops-ui.test.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts)

- [ ] **Step 1: Write failing test for Docs blocks**

Add assertions:

```ts
assert.ok(html.includes("Docs"));
assert.ok(html.includes("文档链接"));
assert.ok(html.includes("页面路由清单"));
assert.ok(html.includes("环境变量"));
assert.ok(html.includes("实现状态"));
```

- [ ] **Step 2: Implement Docs panel HTML**

Docs panel contains 4 sections:

1) 文档链接

- Display as copyable paths (avoid `file://` hard dependency):

```html
<pre>/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/OPS_UI_README.md</pre>
```

Include at least:

- `README.md`
- `OPS_UI_README.md`
- `GOVERNANCE_SPEC.md` / `OBJECT_MODEL.md` / `CHAIN_WORKFLOWS.md`（as listed in README）

2) 页面路由清单

- List:
  - `GET /`（ops home）
  - `GET /ui-map`
  - `GET /health`
  - `GET /api/ops/health`
  - `GET /api/ops/queues`
  - `GET /api/ops/strategy-library`
  - `GET /api/ops/strategy-library/file?id=...`
  - `GET /api/ops/strategy-stats`
  - `POST /api/ops/route/decide`
  - `POST /api/ops/route/execute`
  - `GET /api/ops/traces/:traceId`

Each item shows: purpose + status pill（implemented/planned）。

3) 环境变量

- Show variable names and brief meaning:
  - `OPS_UI_PORT` / `OPS_UI_HOST`
  - `HUB_URL` / `GATEWAY_URL`
  - `OPS_ADMIN_TOKEN`

For `OPS_ADMIN_TOKEN` do not print value. Only show:

```html
<span class="pill ok">set</span> / <span class="pill warn">unset</span>
```

4) 实现状态

- Summary list matching current codebase reality:
  - implemented: `/`, `/ui-map`, `/health`, `/api/ops/queues`, `/api/ops/strategy-library`, `/api/ops/strategy-library/file`, `/api/ops/health`, proxy routes, etc.
  - planned: anything not yet present (if any)

- [ ] **Step 3: Run tests**

Run:

```bash
npm run build
npm test
```

Expected: PASS.

---

### Task 5: Align docs (optional but recommended)

**Files:**
- Optional Modify: [/README.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/README.md)
- Optional Modify: [/OPS_UI_README.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/OPS_UI_README.md)

- [ ] **Step 1: Update README ops-ui section**

Replace “规划中/尚无 start:ops” wording with current run commands, e.g.

```bash
npm run build
OPS_UI_PORT=3457 node dist/ops-ui/server.js
```

- [ ] **Step 2: Update OPS_UI_README status table**

Ensure the top “当前实现状态”与当前仓库一致（目前已存在 `src/ops-ui`，且 `/ui-map` 已可运行）。

---

## Manual Verification Checklist

- [ ] `npm run build` succeeds
- [ ] `npm test` succeeds
- [ ] Run ops-ui locally and verify:

```bash
npm run build
OPS_UI_PORT=3457 node dist/ops-ui/server.js
```

Open:

- `http://127.0.0.1:3457/ui-map`
- Map/Prototypes/Docs 切换正常
- Map：点击节点打开 drawer，drawer 内容随节点变化，Close 可关闭
- Docs：文档链接/路由清单/环境变量/实现状态展示完整

