# Planned Module Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `/planned` 占位页增强为按模块差异化展示的“平衡型模块卡片”页面，同时保持返回 `/ui-map?node=...` 的上下文恢复体验。

**Architecture:** 继续使用 `src/ops-ui/routes/index.ts` 中的服务端 HTML 字符串渲染，不新增框架或客户端状态管理。模块差异化内容通过一个小型服务端映射函数集中生成，`ui-map.ts` 仅负责继续输出带 `target / label / node / module` 的规划链接，测试通过 `node:test` 覆盖 Feed / Query Layer / Data Fabric 三类内容与节点恢复行为。

**Tech Stack:** Node.js + TypeScript + Express + `node:test`

---

## File Structure (to modify)

- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

---

### Task 1: 先用测试固定模块差异化内容

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

- [ ] **Step 1: 为 Feed 模块卡片写失败断言**

把 `ops-ui serves planned route placeholder page` 测试扩成明确的 Feed 卡片断言：

```ts
const res = await fetch(new URL("/planned?target=%2Ffeed&label=%2Ffeed&node=feed&module=Feed", opsListener.url));
assert.equal(res.status, 200);
const html = await res.text();
assert.ok(html.includes("内容门户结构"));
assert.ok(html.includes("/feed/[category]"));
assert.ok(html.includes("预计承接能力"));
assert.ok(html.includes("分类聚合"));
```

- [ ] **Step 2: 为 Query Layer 模块卡片写失败断言**

新增一个测试：

```ts
test("ops-ui planned page shows query layer module card", async () => {
  const opsListener = await listen(createOpsServer());
  try {
    const res = await fetch(
      new URL(
        "/planned?target=ArtifactIndex%20%2F%20ArtifactContent&label=ArtifactIndex%20%2F%20ArtifactContent&node=query&module=Query%20Layer",
        opsListener.url
      )
    );
    assert.equal(res.status, 200);
    const html = await res.text();
    assert.ok(html.includes("查询对象"));
    assert.ok(html.includes("ArtifactIndex"));
    assert.ok(html.includes("数据能力"));
    assert.ok(html.includes("摘要提取"));
  } finally {
    await opsListener.close();
  }
});
```

- [ ] **Step 3: 为 Data Fabric 模块卡片写失败断言**

新增一个测试：

```ts
test("ops-ui planned page shows data fabric module card", async () => {
  const opsListener = await listen(createOpsServer());
  try {
    const res = await fetch(
      new URL(
        "/planned?target=dreambuddy%2Fartifacts&label=dreambuddy%2Fartifacts&node=data&module=Data%20Fabric",
        opsListener.url
      )
    );
    assert.equal(res.status, 200);
    const html = await res.text();
    assert.ok(html.includes("底层目录"));
    assert.ok(html.includes("artifacts"));
    assert.ok(html.includes("协议与运行数据"));
    assert.ok(html.includes("task_*.json"));
  } finally {
    await opsListener.close();
  }
});
```

- [ ] **Step 4: 运行定向测试确认先失败**

Run:

```bash
npm run build
npm test -- --test-name-pattern="ops-ui serves planned route placeholder page|ops-ui planned page shows query layer module card|ops-ui planned page shows data fabric module card"
```

Expected: FAIL，因为当前 `/planned` 页还没有按模块渲染双列卡片。

---

### Task 2: 在服务端集中生成模块卡片内容

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`

- [ ] **Step 1: 定义模块卡片数据结构**

在 `index.ts` 中新增一个小型 helper，返回模块标题和两列列表：

```ts
type PlannedModuleCard = {
  leftTitle: string;
  leftItems: string[];
  rightTitle: string;
  rightItems: string[];
};
```

- [ ] **Step 2: 实现模块映射函数**

新增类似下面的函数：

```ts
function getPlannedModuleCard(moduleName: string, node: string): PlannedModuleCard {
  const normalizedModule = moduleName.trim().toLowerCase();
  const normalizedNode = node.trim().toLowerCase();

  if (normalizedModule === "feed" || normalizedNode === "feed") {
    return {
      leftTitle: "内容门户结构",
      leftItems: ["/feed", "/feed/[category]", "/feed/[category]/[artifactId]"],
      rightTitle: "预计承接能力",
      rightItems: ["内容浏览", "分类聚合", "上下文阅读"]
    };
  }

  if (normalizedModule === "query layer" || normalizedNode === "query") {
    return {
      leftTitle: "查询对象",
      leftItems: ["ArtifactIndex", "ArtifactContent", "SearchResult"],
      rightTitle: "数据能力",
      rightItems: ["分类映射", "摘要提取", "标签与 phase 聚合"]
    };
  }

  if (normalizedModule === "data fabric" || normalizedNode === "data") {
    return {
      leftTitle: "底层目录",
      leftItems: ["artifacts", "meta", "config"],
      rightTitle: "协议与运行数据",
      rightItems: ["task_*.json", "result_*.json", "archive / registry"]
    };
  }

  return {
    leftTitle: "模块结构",
    leftItems: ["规划中入口"],
    rightTitle: "预计承接能力",
    rightItems: ["后续页面入口承接"]
  };
}
```

- [ ] **Step 3: 在 `renderPlannedPage()` 中渲染平衡型双列卡片**

把当前的纯列表 section 改为基于 `getPlannedModuleCard()` 的双列模块卡片：

```ts
const moduleCard = getPlannedModuleCard(params.module, params.node);
const leftItems = moduleCard.leftItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
const rightItems = moduleCard.rightItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
```

并输出：

```html
<section class="section">
  <h2>${moduleName} Module Card</h2>
  <div class="module-grid">
    <div class="module-panel">
      <h3>${leftTitle}</h3>
      <ul>...</ul>
    </div>
    <div class="module-panel">
      <h3>${rightTitle}</h3>
      <ul>...</ul>
    </div>
  </div>
</section>
```

- [ ] **Step 4: 为模块卡片补最小 CSS**

在 `renderPlannedPage()` 的内联 `<style>` 中新增：

```css
.module-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 12px;
}

.module-panel {
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  padding: 14px;
}

.module-panel h3 {
  margin: 0 0 10px;
  font-size: 16px;
}
```

- [ ] **Step 5: 保持现有顶部区和返回区不变**

确保这些内容仍保留：

```html
<p>所属模块：<code>${moduleName}</code></p>
<p>目标路径：<code>${target}</code></p>
<a href="/ui-map?node=${node}">Back to Previous Node</a>
```

---

### Task 3: 保持 `ui-map` 中的上下文入口一致

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

- [ ] **Step 1: 为规划中链接上下文补回归断言**

在现有 `ops-ui exposes ui map page with visual architecture sections` 中保持这类断言存在：

```ts
assert.ok(html.includes('href="/planned?target=%2Ffeed&label=%2Ffeed&node=feed&module=Feed"'));
assert.ok(
  html.includes(
    'href="/planned?target=ArtifactIndex%20%2F%20ArtifactContent&label=ArtifactIndex%20%2F%20ArtifactContent&node=query&module=Query%20Layer"'
  )
);
assert.ok(
  html.includes(
    'href="/planned?target=dreambuddy%2Fartifacts&label=dreambuddy%2Fartifacts&node=data&module=Data%20Fabric"'
  )
);
```

- [ ] **Step 2: 保持 `NODE_META` 的规划中链接不回退**

确认 `ui-map.ts` 中三类规划模块的链接都仍然带完整参数：

```ts
href: "/planned?...&node=feed&module=Feed"
href: "/planned?...&node=query&module=Query%20Layer"
href: "/planned?...&node=data&module=Data%20Fabric"
```

- [ ] **Step 3: 保持节点恢复脚本不回退**

确认脚本尾部仍保留：

```js
const initialNode = new URLSearchParams(window.location.search).get("node");
if (initialNode && NODE_META[initialNode]) {
  activateRootTab("map");
  openDrawer(initialNode);
}
```

---

### Task 4: 回归验证并刷新本地服务

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts`
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ops-ui.test.ts`

- [ ] **Step 1: 运行全量编译与测试**

Run:

```bash
npm run build
npm test
```

Expected: PASS.

- [ ] **Step 2: 重启 `3457` 服务**

Run:

```bash
lsof -nP -iTCP:3457 -sTCP:LISTEN
kill <pid>
OPS_UI_PORT=3457 node dist/ops-ui/server.js
```

Expected: `http://127.0.0.1:3457/ui-map` 与三类 `/planned?...` 都返回 200。

- [ ] **Step 3: 手动检查三类模块页**

Open:

```text
http://127.0.0.1:3457/planned?target=%2Ffeed&label=%2Ffeed&node=feed&module=Feed
http://127.0.0.1:3457/planned?target=ArtifactIndex%20%2F%20ArtifactContent&label=ArtifactIndex%20%2F%20ArtifactContent&node=query&module=Query%20Layer
http://127.0.0.1:3457/planned?target=dreambuddy%2Fartifacts&label=dreambuddy%2Fartifacts&node=data&module=Data%20Fabric
```

Check:

- Feed 页面左列偏页面结构，右列偏承接能力
- Query Layer 页面左列偏查询对象，右列偏数据能力
- Data Fabric 页面左列偏底层目录，右列偏协议与运行数据
- 每页都保留所属模块、目标路径、返回上一个节点入口
