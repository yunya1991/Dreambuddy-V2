# 2026-05-20 Worktree 分类处理表

> 目的：把当前 `dreambuddy-v2` 根仓中所有未提交改动按“系统职责 + 建议处理方式”进行分类，避免粗暴清理导致 `7-ARTIFACT-HUB-V2` 这一中间承接层丢失上下游关系。

## 1. 基本判断

- 当前 Git 根目录不是 `7-ARTIFACT-HUB-V2`，而是整个 `dreambuddy-v2`。
- 因此在 `7-ARTIFACT-HUB-V2` 目录里看到的 `git status`，实际反映的是整仓状态，而不是单一子系统状态。
- `7-ARTIFACT-HUB-V2` 作为中间环节，本来就会承接：
  - 上游：`6-TRADING`
  - 中间层：`7-ARTIFACT-HUB-V2`
  - 下游：`3-FRONTEND`
  - 共享底座：`dreambuddy/config`、`dreambuddy/artifacts`
- 当前问题不是“脏改动太多”，而是“多类改动尚未分组”。

## 2. 当前 git status 原始范围

### 2.1 下游消费层：`3-FRONTEND`

| 路径 | 类别 | 推测用途 | 建议处理 |
|---|---|---|---|
| `../3-FRONTEND/dream-universal-gateway/.gitignore` | 前端工程配置 | 忽略规则调整 | 单独归组，不与中台代码混提 |
| `../3-FRONTEND/dream-universal-gateway/eslint.config.mjs` | 前端工程配置 | lint 规则演进 | 单独归组 |
| `../3-FRONTEND/dream-universal-gateway/next.config.ts` | 前端运行配置 | Next 路由/构建配置 | 单独归组 |
| `../3-FRONTEND/dream-universal-gateway/package.json` | 前端依赖 | 前端依赖更新 | 单独归组 |
| `../3-FRONTEND/dream-universal-gateway/pnpm-lock.yaml` | 前端锁文件 | 依赖锁定 | 跟随前端依赖组 |
| `../3-FRONTEND/dream-universal-gateway/pnpm-workspace.yaml` | 工作区配置 | monorepo 工作区调整 | 单独归组 |
| `../3-FRONTEND/dream-universal-gateway/src/app/api/board/approval/[id]/route.ts` | 下游接口代理 | 董事会审批页面接口 | 与 board/ops 前端工作线一组 |
| `../3-FRONTEND/dream-universal-gateway/src/app/api/board/approval/summary/route.ts` | 下游接口代理 | 审批总览接口 | 与 board/ops 前端工作线一组 |
| `../3-FRONTEND/dream-universal-gateway/src/app/api/board/proposals/[id]/route.ts` | 下游接口代理 | proposal 详情接口 | 与 board/ops 前端工作线一组 |
| `../3-FRONTEND/dream-universal-gateway/src/app/api/board/review/route.ts` | 下游接口代理 | review 接口 | 与 board/ops 前端工作线一组 |
| `../3-FRONTEND/dream-universal-gateway/src/app/api/chain/artifacts/route.ts` | 下游接口代理 | chain artifacts 拉取 | 与 chain/feed 展示线一组 |
| `../3-FRONTEND/dream-universal-gateway/src/app/api/chat/route.ts` | 用户入口接口 | 聊天请求入口 | 保持独立，不混入 `/feed` 恢复 |
| `../3-FRONTEND/dream-universal-gateway/src/app/api/feed/route.ts` | 下游 feed 代理 | 原先前端 `/feed` 代理接口 | 保留但不纳入本轮主线 |
| `../3-FRONTEND/dream-universal-gateway/src/app/api/market/route/route.ts` | 市场化接口 | route 分发接口 | 与市场化前端线归组 |
| `../3-FRONTEND/dream-universal-gateway/src/middleware.ts` | 用户前端安全/鉴权 | 中间件逻辑 | 单独归组 |
| `../3-FRONTEND/dream-universal-gateway/.env.example` | 环境模板 | 前端环境变量样例 | 跟随前端配置组 |
| `../3-FRONTEND/dream-universal-gateway/src/app/api/ops/` | 新增下游 ops 代理 | 前端访问治理接口 | 与 board/ops 前端线一组 |
| `../3-FRONTEND/dream-universal-gateway/src/app/board/page.tsx` | 下游治理投影 | board 页面 | 与 board/ops 前端线一组 |
| `../3-FRONTEND/dream-universal-gateway/src/app/ops/` | 下游治理投影 | ops 页面 | 与 board/ops 前端线一组 |

### 2.2 上游生产层：`6-TRADING`

| 路径 | 类别 | 推测用途 | 建议处理 |
|---|---|---|---|
| `../6-TRADING/bridge/api/dream_api_server.py` | 交易桥接接口 | 对外 API 服务 | 保留为上游生产线，不混入中台恢复 |
| `../6-TRADING/bridge/api/realtime_api.py` | 交易桥接接口 | 实时行情/事件接口 | 保留为上游生产线 |
| `../6-TRADING/bridge/requirements.txt` | Python 依赖 | bridge 运行依赖 | 跟随上游生产线 |
| `../6-TRADING/scripts/mailbox_scanner.py` | 上游扫描器 | 任务/邮箱/消息扫描 | 保留为上游生产线 |

### 2.3 中间治理层：`7-ARTIFACT-HUB-V2` 核心代码

| 路径 | 类别 | 推测用途 | 建议处理 |
|---|---|---|---|
| `package.json` | 中台依赖 | Hub 依赖变化 | 与 `/feed` 恢复或 Hub 演进分开识别 |
| `package-lock.json` | 中台锁文件 | 依赖锁定 | 跟随中台依赖组 |
| `src/artifact-store.ts` | 中间层索引 | artifacts 列表索引 | 识别为 Hub 核心演进 |
| `src/index.ts` | 中间层入口 | Hub 服务主入口 | 识别为 Hub 核心演进 |
| `src/meta-store.ts` | 中间层元数据 | trace / audit / board 数据 | 识别为 Hub 核心演进 |
| `src/router-engine.ts` | 中间层路由决策 | route 决策逻辑 | 识别为 Hub 核心演进 |
| `src/types.ts` | 中台共享类型 | Hub 通用类型 | 识别为 Hub 核心演进 |
| `src/work-order.ts` | 中间层任务协议 | task/result 文件写入与轮询 | 识别为 Hub 核心演进 |
| `src/trading-bridge.ts` | 中间层上下游桥接 | 接 Trading bridge | 识别为桥接层演进 |
| `src/feed/` | 中间层 Feed 恢复 | 本轮 `/feed` 最小恢复包主线 | 单独隔离为本轮主任务 |

### 2.4 文档与结构资产：`7-ARTIFACT-HUB-V2` 内部

| 路径 | 类别 | 推测用途 | 建议处理 |
|---|---|---|---|
| `docs/superpowers/plans/2026-05-20-feed-minimal-recovery.md` | 实施计划 | `/feed` 最小恢复包计划 | 保留，纳入“实施计划”类 |
| `docs/superpowers/plans/2026-05-20-feed-recovery-mapping.md` | 恢复映射 | `/feed` 恢复来源与落点映射 | 保留，纳入“恢复设计”类 |
| `docs/architecture-diagram-01-overview.html` | 架构图资产 | 总览图 | 归入“架构图”类 |
| `docs/architecture-diagram-02-dataflow.html` | 架构图资产 | 数据流图 | 归入“架构图”类 |
| `FRONTEND_INTEGRATION_DESIGN.md` | 历史设计文档 | 前端集成设计 | 保留，但后续移入“跨系统集成”类 |
| `frontend-hub-trading三端联通.md` | 三端联通说明 | 前端-中台-交易联通说明 | 保留，移入“跨系统集成”类 |
| `public/` | 页面静态资产 | board / ops 静态 HTML | 保留，不做文档归档 |

### 2.5 共享底座：配置与运行态数据

| 路径 | 类别 | 推测用途 | 建议处理 |
|---|---|---|---|
| `../dreambuddy/config/artifact-hub.config.json` | 共享配置 | artifacts / meta 根路径配置 | 单独视为“系统配置变更” |
| `../dreambuddy/artifacts/governance/` | 运行产物 | 治理类产物 | 暂不清理，不并入代码整理 |
| `../dreambuddy/artifacts/research/` | 运行产物 | 研究类产物 | 暂不清理 |
| `../dreambuddy/artifacts/trading/` | 运行产物 | 交易类产物 | 暂不清理 |

### 2.6 本地备份与安全副本

| 路径 | 类别 | 推测用途 | 建议处理 |
|---|---|---|---|
| `../7-ARTIFACT-HUB-V2.backup-20260520-103752/` | 本地安全备份 | 手工回滚副本 | 保留，但排除出代码整理范围 |

## 3. 可执行分类结论

### A 类：本轮 `/feed` 恢复主线

包含：

- `src/feed/`
- `package.json`
- `package-lock.json`
- 后续会影响到的 `src/index.ts`
- 后续会影响到的 `src/ops-ui/ui-map.ts`
- 对应的 `/feed` 计划文档

建议：

- 作为单独工作线处理。
- 不要和 `3-FRONTEND`、`6-TRADING`、共享配置一起清理或提交。

### B 类：Hub 既有核心演进

包含：

- `src/artifact-store.ts`
- `src/meta-store.ts`
- `src/router-engine.ts`
- `src/types.ts`
- `src/work-order.ts`
- `src/trading-bridge.ts`

建议：

- 单独做一轮“Hub 核心待确认改动”清单。
- 在没有逐文件理解前，不要一键 stash 或回滚。

### C 类：上下游配套工作线

包含：

- `3-FRONTEND` 全部未提交改动
- `6-TRADING` 全部未提交改动

建议：

- 视为独立工作线。
- 本轮不纳入 `/feed` 恢复包的整理目标。

### D 类：文档与架构资产

包含：

- `docs/superpowers/plans/*`
- `docs/*.html`
- `FRONTEND_INTEGRATION_DESIGN.md`
- `frontend-hub-trading三端联通.md`

建议：

- 这是最适合最先“归档治理”的部分。
- 文档归类不会直接破坏运行逻辑，且最能帮助理清结构。

### E 类：共享配置与运行态产物

包含：

- `dreambuddy/config/*`
- `dreambuddy/artifacts/*`

建议：

- 暂不做“清理”动作。
- 先标注为“系统底座”，防止误删真实产物或当前配置。

## 4. 是否要在 `7-ARTIFACT-HUB-V2` 内做归档

结论：**要，但先从文档归类开始，不要先移动业务代码。**

原因：

- 文档归档不会直接打断运行逻辑。
- 当前 `7-ARTIFACT-HUB-V2` 承接上下游，代码目录一旦贸然移动，会立刻影响构建、引用和后续 TDD。
- 先把设计文档、恢复计划、结构图和跨系统说明归好类，能先把“认知结构”理顺，再决定代码怎么治理。

## 5. 建议的文档归档结构

当前 `7-ARTIFACT-HUB-V2` 已有：

- `docs/superpowers/specs/`
- `docs/superpowers/plans/`
- `docs/*.html`
- 根目录多份设计说明 `*.md`

建议在不破坏现有引用的前提下，新增逻辑归档目标：

```text
7-ARTIFACT-HUB-V2/
├── docs/
│   ├── superpowers/
│   │   ├── specs/
│   │   └── plans/
│   ├── architecture/
│   │   ├── diagrams/
│   │   └── domain/
│   ├── integration/
│   ├── governance/
│   └── recovery/
```

### 建议归档映射

| 当前文件 | 建议目标分类 | 说明 |
|---|---|---|
| `docs/architecture-diagram-01-overview.html` | `docs/architecture/diagrams/` | 架构总览图 |
| `docs/architecture-diagram-02-dataflow.html` | `docs/architecture/diagrams/` | 数据流图 |
| `FRONTEND_INTEGRATION_DESIGN.md` | `docs/integration/` | 前端与中台集成设计 |
| `frontend-hub-trading三端联通.md` | `docs/integration/` | 三端联通设计 |
| `BOARD_CONSOLE_DESIGN.md` | `docs/governance/` | 治理控制台相关设计 |
| `MARKET_CONSOLE_DESIGN.md` | `docs/governance/` | 市场化中台设计 |
| `GOVERNANCE_SPEC.md` | `docs/governance/` | 治理规范 |
| `OBJECT_MODEL.md` | `docs/architecture/domain/` | 对象模型 |
| `CHAIN_WORKFLOWS.md` | `docs/architecture/domain/` | 链路工作流 |
| `docs/superpowers/plans/2026-05-20-feed-recovery-mapping.md` | `docs/recovery/` 的引用入口或副本 | `/feed` 恢复映射文档 |
| `docs/superpowers/plans/2026-05-20-feed-minimal-recovery.md` | `docs/recovery/` 的引用入口或副本 | `/feed` 实施计划 |

## 6. 推荐执行顺序

### 第一步：只做文档归类，不移动代码

- 先建立 `docs/architecture/`
- 再建立 `docs/integration/`
- 再建立 `docs/governance/`
- 最后建立 `docs/recovery/`

### 第二步：先做“复制归档”或“索引归档”，不要立即删原文件

建议优先做：

- 新增 README 或 index 文档说明每类文档的归属
- 必要时复制一份到新目录
- 原路径先保留，防止外部引用断裂

### 第三步：待引用关系清晰后，再做真正物理迁移

只有在确认：

- README 链接已更新
- 计划文档引用已更新
- 外部脚本或人工流程不再依赖旧路径

才建议删除旧位置副本。

## 7. 当前最适合马上执行的动作

优先做这 3 件事：

1. 在 `7-ARTIFACT-HUB-V2/docs/` 下建立文档分类结构
2. 先把根目录的设计文档和 `docs/*.html` 做文档归类清单
3. 保持代码目录不动，继续用清晰文档结构支撑 `/feed` 后续实现

## 8. 一句话决策

- 当前不该先“清理所有未提交改动”。
- 当前最合适的是：**先把未提交改动按职责分类，再从 `7-ARTIFACT-HUB-V2` 的文档归类开始做治理归档。**
