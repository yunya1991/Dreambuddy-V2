# 7-ARTIFACT-HUB-V2

`7-ARTIFACT-HUB-V2` 当前不再只是“产物中台 + 路由服务”，而是正在升级为一个由公司治理架构驱动的 AI 中枢系统。

它统一承接：

- 研究中台；
- 市场化中台；
- 交易链路监控；
- 治理控制台；
- HR 绩效与组织优化；
- 市场情报与外部竞争；
- 董事会（治理委员会）总览与人工审批。

详细设计见：

- [治理中枢化设计](../docs/superpowers/specs/2026-05-16-artifact-hub-v2-governance-central-design.md)
- [公司中枢设计](../1-ARCHITECTURE/中台设计/COMPANY_CENTRAL_HUB.md)
- [Ops UI 说明](./OPS_UI_README.md)
- [市场化中台设计](./MARKET_CONSOLE_DESIGN.md)
- [董事会总览台设计](./BOARD_CONSOLE_DESIGN.md)

详细治理与归档边界见：

- [架构边界](./docs/architecture/SYSTEM_BOUNDARIES.md)
- [单一真相源](./docs/architecture/SOURCE_OF_TRUTH.md)

## 架构治理入口

建议先阅读：

1. [SYSTEM_BOUNDARIES.md](./docs/architecture/SYSTEM_BOUNDARIES.md)
2. [SOURCE_OF_TRUTH.md](./docs/architecture/SOURCE_OF_TRUTH.md)
3. [UPSTREAM_DOWNSTREAM_MATRIX.md](./docs/integration/UPSTREAM_DOWNSTREAM_MATRIX.md)
4. [CHANGE_CLASSIFICATION_POLICY.md](./docs/governance/CHANGE_CLASSIFICATION_POLICY.md)
5. [EXECUTION_ORDER.md](./docs/recovery/EXECUTION_ORDER.md)

## 0. 当前实现状态

下表区分“主仓当前实现”“遗留实现”和“规划目标”，避免把目标形态误写成现状。

| 项目 | 状态 | 位置 / 说明 |
|---|---|---|
| Hub 核心服务 | 已实现 | `7-ARTIFACT-HUB-V2/src/` 下已有 `index.ts`、`artifact-store.ts`、`meta-store.ts`、`router-engine.ts`、`work-order.ts` |
| `route/decide` / `route/execute` / `traces` / `events` | 已实现 | 属于当前 Node/TypeScript Hub 服务 |
| 研究中台 `/feed` | 已实现 | 已在当前 Hub 服务中恢复 `GET /feed`、`GET /feed/:category`、`GET /feed/:category/:artifactId` 三段真实入口，继续以仓内 `src/feed/` 为主线演进 |
| 交易链路页 `/chain` | 已实现 | 已在当前 Hub 服务中恢复 `GET /chain`、`GET /chain/:workflowType` 真实入口，并以仓内 `src/chain/` 持续演进链路监控与交叉跳转 |
| `ops-ui` 子服务 | 已实现 | 已落地于 `7-ARTIFACT-HUB-V2/src/ops-ui/`，提供治理控制台页面与 `/api/ops/*` 接口 |
| 市场化中台 | 规划中 | 目标为同仓双入口中的运营部分发入口，当前主仓尚无实现 |
| 董事会总览台 | 规划中 | 目标为治理委员会管理视图，当前主仓尚无实现 |

## 1. 系统定位

当前阶段，`7-ARTIFACT-HUB-V2` 的系统定位是：

- 一个共享底层能力的中枢方向；
- 当前已实现 Hub 核心服务；
- 当前已恢复研究中台 `/feed` 与交易链路页 `/chain`；
- 后续以同仓双入口方式扩展研究中台与市场化中台；
- 用 route/trace/event/task/result/audit 逐步统一治理 AI 黑箱。

## 2. 核心治理目标

系统需要统一解决四类黑箱：

- `决策黑箱`：为什么这样判断、推荐、路由；
- `执行黑箱`：调用了什么链路、写了什么任务、产出了什么结果；
- `分发黑箱`：为什么把哪些内容推给哪些人；
- `审计黑箱`：如何回放、复盘、问责。

## 3. 组织模型

第一版按 6 个部门建模：

- `研究部`
- `交易部`
- `治理部`
- `运营部`
- `HR`
- `市场部`

并在其上增加由 6 位部长 Agent 组成的“六人董事会（治理委员会）”：

- 作为目标组织模型中的治理委员会；
- 规划中用于处理小问题；
- 规划中用于协调中问题并将重大事项上报人工审批。

## 4. 双中台与链路页面

### 研究中台

- 已恢复同仓真实 `/feed` 入口，并以该实现为后续增强基线；
- 保留旧版产物中台的内容治理与 Feed/详情页心智。

### 市场化中台

- 面向内部销售/运营；
- 重点做内容路由、用户分层、推送分发、投放管理、分发审计。

### 交易链路监控

- 已恢复同仓真实 `/chain` 入口，并以该实现承接链路监控首页与工作流视图；
- 保留现有交易闭环工作流设计；
- 逐步新增基于 `6-TRADING` 的第二套交易工作流；
- 用可视化工作流展示检测链路畅通性，并与 `/feed` 详情页双向跳转。

### 治理控制台

- 目标形态：独立 `ops-ui` 子服务
- 第一阶段规划技术形态：`7-ARTIFACT-HUB-V2` 包内的 Node/TypeScript 子服务，而不是独立 React 应用
- 用于健康检查、Route Sandbox、Trace 回放、策略库、归档治理。

## 5. 单一真相源

系统正式以以下路径为共享底座：

- Artifacts root: `../dreambuddy/artifacts`
- Meta DB: `../dreambuddy/meta/artifact_hub.sqlite`
- Config root: `../dreambuddy/config`

所有双中台、双交易工作流、治理对象、队列与归档，都应优先收敛到这一套 repo-local 路径，不继续扩散旧 `~/.workbuddy` 目录心智。

## 6. 运行方式

### Hub 服务

```bash
cd 7-ARTIFACT-HUB-V2
npm install
npm run build
node dist/index.js
```

### Feed + Chain 当前访问方式

当前 `/feed` 与 `/chain` 都由 Hub 服务直接承载，最小可用入口包括：

- `GET /feed`
- `GET /feed/:category`
- `GET /feed/:category/:artifactId`
- `GET /chain`
- `GET /chain/:workflowType`

本地默认访问示例：

- `http://127.0.0.1:3456/feed`
- `http://127.0.0.1:3456/feed/trading`
- `http://127.0.0.1:3456/feed/research/intel-report-001`
- `http://127.0.0.1:3456/chain`
- `http://127.0.0.1:3456/chain/legacy_chain`

### Feed P0 最小闭环

- 首页固定显示 `交易部 / 做梦部 / 治理部 / 知识库` 四个部门入口。
- 首页固定显示 `A0-A9` 十个阶段入口，即使当前阶段没有数据也会展示并显示 `0`。
- 当前仓内真数据阶段为 `A1 / A3 / A9`，其中 `A1` 来自研究产物、`A3` 来自研究策略、`A9` 来自交易执行。
- `A0 / A2 / A4 / A5 / A6 / A7 / A8` 当前属于空态阶段，入口可访问但会显示明确空态文案。
- `做梦部` 当前先由 `research` 类目中的临时映射承接：标题或标签命中 `dream / oneirology` 时归入 `做梦部`；若当前真实数据里没有显式做梦信号，则 `research` 下的 `A3 strategy` 产物临时承接 `做梦部` 入口，其余研究内容默认归入 `知识库`。
- 详情页固定展示中文分类字段：`部门 / 阶段 / 类型 / 标签`，并保留跳转 `链路监控` 的治理上下文入口。

P0 运行态重点验证入口：

- `http://127.0.0.1:3456/feed`
- `http://127.0.0.1:3456/feed?department=%E5%81%9A%E6%A2%A6%E9%83%A8`
- `http://127.0.0.1:3456/feed?chainPhase=A1`
- `http://127.0.0.1:3456/feed?chainPhase=A0`
- `http://127.0.0.1:3456/feed/research/intel-report-001`

说明：

- `/feed` 与 `/chain` 当前都由 `src/server.ts` 装配并由 `src/index.ts` 启动。
- 详情页优先读取真实 markdown/json 文件；若真实产物只有分类 `index.json`，则会退回索引元数据生成最小详情内容，避免直接 `404`。
- `/feed` 详情页会暴露链路治理上下文，并提供跳转到 `/chain/:workflowType` 的入口。
- `/chain` 工作流视图会保留回跳 `/feed/:category/:artifactId` 的真实入口，便于做研究内容与执行链路闭环排查。

### Ops UI

```bash
cd 7-ARTIFACT-HUB-V2
npm install
npm run build
OPS_UI_PORT=3457 node dist/ops-ui/server.js
```

如果 `ops-ui` 以独立端口运行，建议同时显式指定 Hub 基址：

```bash
cd 7-ARTIFACT-HUB-V2
npm install
npm run build
OPS_UI_PORT=3457 HUB_URL=http://127.0.0.1:3456 node dist/ops-ui/server.js
```

说明：

- `ui-map` 中的 `feed` 与 `chain` implemented 入口都会优先指向 `HUB_URL`。
- 如需单独覆盖 `/feed` 入口，也可以设置 `OPS_UI_FEED_BASE_URL`。
- `ops-ui` 不直接承载 `/feed` 或 `/chain` 页面内容，只负责导航到 Hub 真实页面。

## 7. 核心 API

### Hub API

- `GET /health`
- `POST /route/decide`
- `POST /route/execute`
- `GET /traces/:traceId`
- `GET /events/stream?traceId=...` (SSE)

### Ops UI

当前主仓已落地 `ops-ui` 子服务，当前可用接口包括：

- `GET /`
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

## 8. 验证方式

### 8.1 构建与测试

```bash
cd 7-ARTIFACT-HUB-V2
npm run build
npm test
```

### 8.2 Hub 本地运行态验证

```bash
cd 7-ARTIFACT-HUB-V2
npm run build
node dist/index.js
```

然后验证：

- `http://127.0.0.1:3456/feed`
- `http://127.0.0.1:3456/chain`
- `http://127.0.0.1:3456/feed/trading`
- `http://127.0.0.1:3456/feed/research/intel-report-001`
- `http://127.0.0.1:3456/chain/legacy_chain`

### 8.3 独立 Ops UI -> Hub 页面验证

```bash
cd 7-ARTIFACT-HUB-V2
npm run build
node dist/index.js
OPS_UI_PORT=3457 HUB_URL=http://127.0.0.1:3456 node dist/ops-ui/server.js
```

然后验证：

- `http://127.0.0.1:3457/ui-map?node=feed`
- 在 Feed 节点 Drawer 中点击 `/feed`
- 在 Feed 节点 Drawer 或全局链接中点击 `/chain`
- 应跳转到 Hub 服务的 `/feed` 与 `/chain`，而不是 `ops-ui` 自身端口

### 8.4 HTTP + 浏览器闭环验证

```bash
cd 7-ARTIFACT-HUB-V2
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

浏览器侧建议检查：

- 打开 `http://127.0.0.1:3457/ui-map?node=feed`
- 确认 Drawer 中 `/feed` 与 `/chain` 都是 `http://127.0.0.1:3456` 下的真实链接
- 进入 `/feed` 后可继续跳转到 `/chain/:workflowType`
- 进入 `/chain/:workflowType` 后可回跳对应 `/feed/:category/:artifactId`

## 9. Producer Contract (tasks/results)

### Task file

Path: `dreambuddy/artifacts/tasks/task_<taskId>.json`

建议字段：

- `trace_id`
- `task_id`
- `created_at`
- `intent`
- `routing_plan`

### Result file

Path: `dreambuddy/artifacts/results/result_<taskId>.json`

当前最小字段：

```json
{ "trace_id": "...", "task_id": "...", "status": "completed" }
```

后续建议统一扩展：

- `workflow_id`
- `workflow_type`
- `department`
- `schema_version`
- `policy_version`
- `producer`
- `timestamp`

## 10. 下一步文档化方向

当前已补齐：

- [GOVERNANCE_SPEC.md](./GOVERNANCE_SPEC.md)
- [OBJECT_MODEL.md](./OBJECT_MODEL.md)
- [CHAIN_WORKFLOWS.md](./CHAIN_WORKFLOWS.md)
- [OPS_UI_README.md](./OPS_UI_README.md)
- [MARKET_CONSOLE_DESIGN.md](./MARKET_CONSOLE_DESIGN.md)
- [BOARD_CONSOLE_DESIGN.md](./BOARD_CONSOLE_DESIGN.md)
- [SYSTEM_BOUNDARIES.md](./docs/architecture/SYSTEM_BOUNDARIES.md)
- [SOURCE_OF_TRUTH.md](./docs/architecture/SOURCE_OF_TRUTH.md)

建议继续补齐：

- 审批票据与 proposal schema 设计文档
- 研究中台 `/feed` 恢复与增强设计文档
- `/chain` 页面实现改造计划
