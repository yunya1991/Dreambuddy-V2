# 7-ARTIFACT-HUB-V2 Ops UI 说明

> 版本：v1.1  
> 更新日期：2026-05-16  
> 状态：已落地（持续迭代中）  
> 作用：说明 `ops-ui` 的目标定位、物理位置、技术栈假设、接口边界与演进方向。

## 0. 当前实现状态

`ops-ui` 当前已是主仓内可运行子服务，本文档同时描述现状与后续演进方向。

| 项目 | 状态 | 说明 |
|---|---|---|
| `7-ARTIFACT-HUB-V2/src/ops-ui/` 目录 | 已实现 | 当前主仓已存在该目录并可构建运行 |
| `3457` 端口服务 | 已实现 | 作为当前本地开发默认端口，可通过 `OPS_UI_PORT` 覆盖 |
| `GET /`、`GET /ui-map` | 已实现 | 当前已有治理控制台主页与 `ui-map` 页面 |
| `GET /api/ops/*` | 部分已实现 | 已有 health / queues / strategy / route / traces 等接口，后续继续扩展 |

## 1. 定位

`ops-ui` 的目标定位是 `7-ARTIFACT-HUB-V2` 的治理控制台前台。

它不是终端用户页面，而是：

- 治理部主视角页面；
- Route / Trace / Queue / Strategy / Archive 的操作台；
- AI 黑箱治理的控制界面；
- 公司中枢中的治理入口。

## 2. 物理位置与技术栈

为避免实现层级混乱，本文档明确以下默认方案：

- 物理位置：`7-ARTIFACT-HUB-V2/src/ops-ui/`
- 技术归属：`7-ARTIFACT-HUB-V2` 包内子服务
- 技术栈：Node.js + TypeScript
- 页面形态：治理控制台 Web 页面，可先采用服务端渲染或模板输出
- 服务角色：承接治理页面与 `/api/ops/*` 代理接口

它当前明确不是：

- 独立 React 应用；
- `3-FRONTEND/dream-universal-gateway/` 内现成路由；
- 主仓已经落地并可直接运行的页面。

## 3. 目标职责

`ops-ui` 第一阶段的目标职责是：

- 聚合 Hub / Gateway / Queue 健康状态；
- 展示 tasks / results 队列快照；
- 提供 Route Sandbox；
- 提供 Trace 查询与回放入口；
- 提供策略库浏览与统计；
- 提供治理结构原型页 `ui-map`。

这些职责中已有部分落地，其余仍作为演进目标持续推进。

## 4. 目标页面组成

### 4.1 `/`

目标主页定位为治理控制台，建议包含：

- `Aggregated Health`
- `Queues Snapshot`
- `Strategy Stats`
- `Route Sandbox`
- `Classic Strategy Library`

### 4.2 `/ui-map`

目标定位为设计与治理结构原型页，建议包含：

- Feed / Ops / Hub / Data 页面架构图；
- AI 黑箱治理总图；
- 双中台页面结构图；
- 治理对象模型图；
- 若干关键页面原型预览。

## 5. 目标接口边界

### 5.1 当前本地页面接口

以下接口中大部分已在主仓实现，少数为后续扩展目标：

- `GET /health`
- `GET /`
- `GET /ui-map`
- `GET /api/ops/health`
- `GET /api/ops/queues`
- `GET /api/ops/strategy-library`
- `GET /api/ops/strategy-library/file?id=...`
- `GET /api/ops/strategy-stats`
- `POST /api/ops/route/decide`
- `POST /api/ops/route/execute`
- `GET /api/ops/traces/:traceId`

### 5.2 上游依赖

目标形态下，`ops-ui` 依赖：

- Artifact Hub：默认 `127.0.0.1:8787`
- Gateway：默认 `127.0.0.1:3000`
- `dreambuddy/artifacts`
- `dreambuddy/meta`

### 5.3 安全边界

默认治理控制台约束如下：

- 以内网或本机使用为主；
- 不直接暴露公网入口；
- 敏感令牌由服务端代持；
- 高风险动作只允许通过服务端治理接口访问。

## 6. 与其他页面的关系

### 6.1 与研究中台的关系

- 研究中台以遗留 `/feed` 设计为基线；
- 在目标关系中，`ops-ui` 将负责解释研究产物背后的 route / trace / audit。

### 6.2 与 `/chain` 的关系

- `/chain` 以遗留交易监控页为设计基线；
- 在目标关系中，`ops-ui` 将从 route、trace、task / result、审计层解释其执行过程。

### 6.3 与市场化中台的关系

- 在目标关系中，市场化中台将负责内容路由、用户分层、推送分发、投放管理；
- `ops-ui` 将提供治理证据链、风控边界和审计追踪。

### 6.4 与董事会总览台的关系

- 在目标关系中，董事会总览台将负责跨部门管理视角；
- `ops-ui` 将提供治理底座和证据入口。

## 7. 当前限制

当前阶段，`ops-ui` 仍有这些明确限制：

- 审批待办区、董事会议案区、外部分发审计区尚未实现；
- `/chain` 双交易工作流尚未正式接入；
- 研究中台、市场化中台、董事会总览台之间的联动仍待实现。

## 8. 演进方向

### Phase 1

- 接入 Trace 详情、Queue 深度视图、Strategy 审计、Archive 治理；
- 提供 `/chain` 联动入口。

### Phase 2

- 增加重大事项待审批列表；
- 增加决策原因区；
- 增加风险与红线告警区；
- 增加审批票据与回滚入口。

### Phase 3

- 与市场化中台联动；
- 与董事会总览台联动；
- 与 HR / 市场部信号联动；
- 成为公司中枢治理控制台主入口。

## 9. 一句话结论

`ops-ui` 在当前主仓中的准确定义是：

> 一个已落地在 `7-ARTIFACT-HUB-V2/src/ops-ui/` 的 Node/TypeScript 子服务，用于承接治理控制台页面与治理代理接口，并持续向更完整的治理控制台演进。
