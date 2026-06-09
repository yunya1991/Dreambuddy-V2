# Feed Recovery Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `7-ARTIFACT-HUB-V2` 内恢复真实 `/feed`，让旧版产物中台的可见入口回归，并把 `/feed` 定位为治理 AI 黑箱的中间产物层入口，而不是传统用户前端内容页。

**Architecture:** `7-ARTIFACT-HUB-V2` 是 `/feed` 的唯一主线落点，`/feed` 与 `/ops`、后续 `/route`、`/trace`、`/queue`、`/strategy`、`/archive` 同属一个治理产品。恢复策略分两步：第一步先把旧备份的内容浏览、分类、详情能力迁回当前仓内；第二步逐步把 Feed 和 route/trace/task/result/query/data substrate 打通，使其从内容门户演进为治理中间产物层。

**Tech Stack:** Node.js, TypeScript, Express, server-rendered HTML, gray-matter, marked, repo-local artifact storage

---

## 1. Product Positioning

### 长期定位

- `/feed` 不是用户前端主页面。
- `/feed` 是治理中间产物层的可见入口。
- 它承担的核心职责不是复杂交互，而是把 AI 运行中的内容产物、路由结果、上下文痕迹和阶段状态外化出来。
- 它服务于治理 AI 黑箱、缓解漂移、支持回放和复盘。

### 结构归属

| 区域 | 长期职责 | 结论 |
|---|---|---|
| `3-FRONTEND` | 轻量用户入口、对话发起、结果消费 | 不作为 `/feed` 主落点 |
| `7-ARTIFACT-HUB-V2` | 治理中枢、中间产物层、统一数据底座 | 作为 `/feed` 主落点 |
| `src/ops-ui/` | `ui-map`、`planned`、治理控制台页面 | 与 `/feed` 同属一个产品，但不必直接承载 `/feed` 页面代码 |

### 当前结论

- 真实 `/feed` 应落在 `7-ARTIFACT-HUB-V2` 仓内。
- `ui-map?node=feed` 定义的是产品结构边界，而不是要求必须把 `/feed` 写进 `src/ops-ui/`。
- 更合理的组织方式是：`7-ARTIFACT-HUB-V2` 统一承载 `/feed` 与 `/ops`，但 `/feed` 可以有独立的 `src/feed/` 模块。

## 2. Baseline

### 当前三处基线

| 区域 | 现状 | 关键路径 |
|---|---|---|
| 旧备份内容门户 | 完整 Next `/feed` 内容门户，含列表页、详情页、读盘逻辑、统计接口 | `/Users/zhangjiangtao/Desktop/product-hub-backup` |
| 当前 Hub V2 | 已有 Hub 主服务与 `ops-ui` 子服务，`/feed` 在 `ui-map` 中仍是 planned | `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2` |
| 当前用户前端 | 已有一个精简版 `/feed`，但这不是本轮恢复主线 | `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway` |

### 关键判断

- 旧备份可提供 `/feed` 的页面结构、筛选逻辑、详情阅读和内容扫描基线。
- 当前 `7-ARTIFACT-HUB-V2` 没有完整 React/Next 页面层，因此不能机械照搬旧备份目录结构。
- 旧备份的最大适配点是两类：
  - 运行时适配：Next 页面改造成当前仓可承载的 Express + server-rendered HTML 结构
  - 数据路径适配：从 `~/.workbuddy/artifacts` 收敛到当前 V2 的 repo-local artifacts 根路径

## 3. Landing Strategy

### 主线方案

| 方案 | 结论 | 原因 |
|---|---|---|
| 在 `7-ARTIFACT-HUB-V2` 恢复真实 `/feed` | 推荐 | 符合长期产品归属，`/feed` 属于治理中间产物层，不属于用户前端主入口 |
| 在 `3-FRONTEND` 恢复真实 `/feed` | 备选 | 工程迁移更顺手，但会弱化 `/feed` 作为治理中间层的定位 |
| 继续保留当前 planned 或精简流式 `/feed` | 不满足目标 | 无法承接旧版内容门户和治理中间产物层职责 |

### 仓内组织建议

| 模块 | 建议位置 | 职责 |
|---|---|---|
| Feed 路由入口 | `src/index.ts` | 注册 `/feed`、`/feed/:category`、`/feed/:category/:artifactId` |
| Feed 页面渲染 | `src/feed/render.ts` | 输出列表页、分类页、详情页 HTML |
| Feed 数据读取 | `src/feed/content.ts` | 扫描 artifacts、聚合索引、读取详情、做缓存 |
| Feed 领域类型 | `src/feed/types.ts` | 约束列表项、详情项、统计结构 |
| Feed 工具函数 | `src/feed/utils.ts` | slug、日期、状态展示等辅助逻辑 |
| Feed 样式与片段 | `src/feed/templates.ts` 或 `src/feed/render.ts` | 卡片、过滤条、分页、详情页布局 |

### 与 `ops-ui` 的关系

- `src/ops-ui/` 继续负责 `/ui-map`、`/planned`、治理控制台页面。
- `/feed` 不必写进 `src/ops-ui/`，但必须由同一仓统一承载。
- 真实 `/feed` 上线后，`ui-map` 中 Feed 节点应从 planned 切换为 implemented。

## 4. Source-To-Target Mapping

### A. 必须迁移

| 来源文件 | 作用 | 新落点 | 迁移类型 | 说明 |
|---|---|---|---|---|
| `product-hub-backup/app/feed/page.tsx` | 列表页入口与统计聚合 | `src/feed/render.ts` + `src/index.ts` | 重写迁移 | 旧服务端组件逻辑需要改造成 Express 渲染函数 |
| `product-hub-backup/app/feed/FeedClient.tsx` | 列表页过滤、分页、搜索体验 | `src/feed/render.ts` 内联脚本或 `src/feed/templates.ts` | 重写迁移 | 不能直接复用 React 组件，需要提炼交互逻辑和结构 |
| `product-hub-backup/app/feed/[...slug]/page.tsx` | 详情页展示、markdown 渲染 | `src/feed/render.ts` + `src/index.ts` | 重写迁移 | 详情页路由和渲染逻辑要迁到 Express |
| `product-hub-backup/lib/content.server.ts` | 扫描 artifacts、生成索引、读取详情、缓存 | `src/feed/content.ts` | 强适配 | 是本轮最关键的数据层来源文件 |
| `product-hub-backup/lib/types.ts` | Feed 数据类型 | `src/feed/types.ts` | 适配迁移 | 仅保留当前仓需要的 Feed 域类型 |
| `product-hub-backup/lib/utils.ts` | 时间与展示辅助函数 | `src/feed/utils.ts` | 适配迁移 | 提炼为独立工具文件 |
| `product-hub-backup/lib/search.ts` | 搜索与过滤辅助 | `src/feed/content.ts` 或 `src/feed/utils.ts` | 部分迁移 | 保留有价值的过滤逻辑，不强求照搬全文搜索空壳 |

### B. 条件迁移

| 来源文件 | 作用 | 新落点 | 迁移类型 | 说明 |
|---|---|---|---|---|
| `product-hub-backup/app/api/stats/route.ts` | 统计接口 | `src/index.ts` 下新增 `GET /feed/stats` 或并入页面渲染 | 适配后新增 | 仅在需要独立统计接口时迁移 |
| `product-hub-backup/app/api/refresh/route.ts` | 手动刷新缓存 | `src/index.ts` 下新增 `POST /feed/refresh` | 适配后新增 | 当前仓若采用内存缓存则有价值 |
| `product-hub-backup/components/Header.tsx` | 顶部统计导航 | `src/feed/render.ts` | 部分迁移 | 只提取 feed 局部导航，不扩散到全仓布局 |
| `product-hub-backup/components/DreamAgentChat.tsx` | Agent 对话入口 | 暂不迁移 | 暂缓 | 本轮目标是恢复治理中间产物层，不是恢复聊天扩展能力 |

### C. 不建议直接迁移

| 来源文件 | 原因 | 处理建议 |
|---|---|---|
| `product-hub-backup/app/layout.tsx` | 当前仓不是 Next App Router 工程 | 不迁移 |
| `product-hub-backup/app/page.tsx` | 与当前 Hub 首页结构无关 | 不迁移 |
| `product-hub-backup/app/globals.css` | 当前仓无全局 React 样式体系 | 只提取必要 CSS 片段到 Feed 渲染模板 |
| `product-hub-backup/package.json` | 当前仓运行时是 Express，不是 Next | 只补依赖，不覆盖 |
| `product-hub-backup/tsconfig.json` | 当前仓已有 TS 配置 | 仅对照是否需要补别名或编译选项 |

## 5. Current File Replacement Map

### 当前仓内需要新增或修改的主线文件

| 当前文件 | 当前状态 | 恢复动作 |
|---|---|---|
| `src/index.ts` | 已承载 `/board`、`/ops` 与 Hub API | 增加 `/feed` 三段真实路由，并接入 Feed 模块 |
| `src/ops-ui/ui-map.ts` | Feed 链接仍为 planned | 真实 `/feed` 可用后切换为 implemented |
| `README.md` | 说明 `/feed` 为遗留实现待恢复 | 恢复后更新为已恢复或恢复中 |
| `src/feed/` | 当前不存在 | 新增 Feed 领域模块目录 |

## 6. Required Adaptations

### 运行时适配

- 旧备份是 Next App Router。
- 当前主线仓是 Node + Express。
- 因此旧 `/feed` 不能按目录级直接搬迁，只能按职责拆解后重组：
  - 页面入口逻辑 -> Express 路由
  - 服务端组件 -> HTML 渲染函数
  - 客户端交互 -> 内联脚本或简化版前端逻辑

### 数据路径适配

- 旧 `content.server.ts` 默认读取 `process.env.HOME/.workbuddy/artifacts`。
- 当前 V2 文档要求统一收敛到 repo-local artifacts 根路径。
- 恢复时应改造成：
  - 优先读当前仓配置路径
  - 必要时兼容环境变量覆盖
- 不建议继续把长期主线绑定到 `~/.workbuddy`。

### 能力定位适配

- 恢复初期先保留旧内容门户最有价值的三项能力：
  - 列表浏览
  - 分类浏览
  - 详情阅读
- 然后逐步补治理属性：
  - route 决策上下文
  - trace 入口
  - task/result 关联
  - query/data substrate 链接

### 交互复杂度适配

- 由于 `/feed` 的长期定位不是重交互用户前端，恢复时不需要追求复杂 SPA 化。
- 优先选择：
  - 服务端渲染
  - 轻量过滤
  - 可追踪链接
  - 明确的详情页与上下文入口

## 7. Recovery Checklist

- [ ] 在 `src/` 下新增 `feed` 模块目录
- [ ] 从旧 `content.server.ts` 提炼数据扫描与缓存逻辑到 `src/feed/content.ts`
- [ ] 把 artifacts 根路径从 `~/.workbuddy/artifacts` 改为当前 V2 配置主线
- [ ] 定义 `src/feed/types.ts`，收口 Feed 列表、详情、统计类型
- [ ] 在 `src/feed/render.ts` 实现列表页 HTML 渲染
- [ ] 在 `src/feed/render.ts` 实现详情页 HTML 渲染与 markdown 输出
- [ ] 在 `src/index.ts` 注册 `GET /feed`
- [ ] 在 `src/index.ts` 注册 `GET /feed/:category`
- [ ] 在 `src/index.ts` 注册 `GET /feed/:category/:artifactId`
- [ ] 补最小过滤能力，至少支持分类和基本搜索
- [ ] 视需要新增 `/feed/stats` 与 `/feed/refresh`
- [ ] 更新 `src/ops-ui/ui-map.ts`，把 Feed 节点改为真实可跳转入口
- [ ] 更新 `README.md`，把 `/feed` 从遗留待恢复改成当前主线能力

## 8. Governance Evolution

### 第一阶段：旧入口回归

- 目标：让真实 `/feed` 可访问。
- 能力：列表、分类、详情。
- 价值：旧版产物中台可见入口回归。

### 第二阶段：治理上下文化

- 目标：让 `/feed` 不只是浏览页，而是治理观察窗。
- 能力：
  - 链接到 route/trace
  - 显示阶段状态
  - 标注关联 task/result
- 价值：开始承担 AI 黑箱外化功能。

### 第三阶段：统一数据底座

- 目标：把 `/feed`、`query layer`、`data fabric`、`/ops` 串成统一治理产品。
- 能力：
  - 从内容浏览走向治理追踪
  - 从单页展示走向中间产物层
  - 从遗留恢复走向正式治理中枢

## 9. Fallback Note

- `3-FRONTEND` 仍可作为备选复用参考，但不再是本计划主线。
- 若未来确实需要把某些 Feed 展示能力镜像到用户前端，应视为“消费端投影”，而不是主实现位置。

## 10. Recommended Next Step

- 下一步直接基于本清单，开始 `7-ARTIFACT-HUB-V2` 内的 `/feed` 最小恢复包设计：
  - `src/feed/content.ts`
  - `src/feed/types.ts`
  - `src/feed/utils.ts`
  - `src/feed/render.ts`
  - `src/index.ts` 中的 `/feed` 三段路由
- 等真实 `/feed` 跑通后，再单独做 `ui-map` implemented 切换和治理增强。
