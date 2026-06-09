# Ops UI Planned Link Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `/ui-map` Drawer 中的链接分为“已实现正常跳转”和“规划中统一跳转到 coming soon 占位页”两类。

**Architecture:** 保持现有 `renderUiMapHtml()` 的服务端 HTML 字符串 + 原生 JS 方案；为节点链接元数据增加状态字段，已实现链接继续输出真实目标，规划中链接统一转换到 `/planned` 占位页并携带原始目标路径参数。`/planned` 由 ops-ui 路由层统一渲染，避免提前占用未来真实 `/feed` 路由。

**Tech Stack:** Node.js + TypeScript + Express + `node:test`

---

## File Structure (to modify)

- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

---

### Task 1: 用测试固定链接分类行为

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

- [ ] **Step 1: 为已实现链接保留真实 href 增加断言**

```ts
assert.ok(html.includes('href="/health"'));
assert.ok(html.includes('href="/api/ops/queues"'));
```

- [ ] **Step 2: 为规划中链接跳转到统一占位页增加断言**

```ts
assert.ok(html.includes('href="/planned?target=%2Ffeed&label=%2Ffeed"'));
assert.ok(
  html.includes(
    'href="/planned?target=%2Ffeed%2F%5Bcategory%5D&label=%2Ffeed%2F%5Bcategory%5D"'
  )
);
```

- [ ] **Step 3: 为占位页路由增加 HTTP 断言**

```ts
const plannedRes = await fetch(new URL("/planned?target=%2Ffeed&label=%2Ffeed", opsListener.url));
assert.equal(plannedRes.status, 200);
const plannedHtml = await plannedRes.text();
assert.ok(plannedHtml.includes("coming soon"));
assert.ok(plannedHtml.includes("/feed"));
assert.ok(plannedHtml.includes("/ui-map"));
```

- [ ] **Step 4: 运行定向测试，确认先失败**

Run:

```bash
npm run build
npm test -- --test-name-pattern="ops-ui exposes ui map page with visual architecture sections|ops-ui serves planned route placeholder page"
```

Expected: FAIL，因为 `/planned` 还不存在，规划中链接也尚未分类。

---

### Task 2: 在 `ui-map` 中输出两类链接

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`

- [ ] **Step 1: 为链接元数据增加状态字段**

```ts
type DrawerLinkMeta = {
  href: string;
  label: string;
  status: "implemented" | "planned";
};
```

- [ ] **Step 2: 把 `NODE_META.links` 改成显式声明状态**

```ts
links: [
  { href: "/health", label: "/health", status: "implemented" },
  { href: "/feed", label: "/feed", status: "planned" }
]
```

- [ ] **Step 3: 增加统一占位页 href 构造函数**

```ts
function buildPlannedHref(item) {
  const params = new URLSearchParams({ target: item.href, label: item.label });
  return "/planned?" + params.toString();
}
```

- [ ] **Step 4: 渲染链接时按状态分流**

```ts
const href = item.status === "implemented" ? item.href : buildPlannedHref(item);
const badge =
  item.status === "implemented"
    ? '<span class="drawer-link-state implemented">Implemented</span>'
    : '<span class="drawer-link-state planned">Coming Soon</span>';
```

- [ ] **Step 5: 给链接状态补样式**

```css
.drawer-link-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.drawer-link-state.planned {
  color: #ffe2b3;
}
```

- [ ] **Step 6: 保持默认抽屉示例与新逻辑一致**

默认抽屉里的 `/`、`/health`、`/api/ops/*` 保持已实现直达链接；如需展示规划入口，使用 `/planned?...` 形式。

---

### Task 3: 添加统一占位页路由

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`

- [ ] **Step 1: 在路由文件中增加简单 HTML 渲染函数**

```ts
function renderPlannedPage(params: { target: string; label: string }): string {
  return `<!doctype html>...`;
}
```

- [ ] **Step 2: 增加 `GET /planned` 路由**

```ts
router.get("/planned", (req: Request, res: Response) => {
  const target = typeof req.query.target === "string" ? req.query.target : "/";
  const label = typeof req.query.label === "string" ? req.query.label : target;
  return sendHtml(res, 200, renderPlannedPage({ target, label }));
});
```

- [ ] **Step 3: 占位页至少包含以下信息**

```html
<h1>Coming Soon</h1>
<p>目标入口：/feed</p>
<a href="/ui-map">Back to UI Map</a>
```

- [ ] **Step 4: 对占位页内容做最小转义**

```ts
function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
```

---

### Task 4: 回归验证并重启服务

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`

- [ ] **Step 1: 全量编译与测试**

Run:

```bash
npm run build
npm test
```

Expected: PASS.

- [ ] **Step 2: 重启 3457 服务**

Run:

```bash
lsof -nP -iTCP:3457 -sTCP:LISTEN
kill <pid>
OPS_UI_PORT=3457 node dist/ops-ui/server.js
```

Expected: `/ui-map` 与 `/planned?...` 都返回 200。

- [ ] **Step 3: 手动验证**

Open:

```text
http://127.0.0.1:3457/ui-map
http://127.0.0.1:3457/planned?target=%2Ffeed&label=%2Ffeed
```

Check:

- 已实现链接点击后进入真实页面
- 规划中链接点击后进入统一占位页
- 占位页显示目标路径与返回 `/ui-map` 的入口
