# Integration Docs

本目录收口 `7-ARTIFACT-HUB-V2` 与上下游系统的集成说明。

## Core Ownership

- [UPSTREAM_DOWNSTREAM_MATRIX.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/integration/UPSTREAM_DOWNSTREAM_MATRIX.md)
  - 用途：冻结 `6-TRADING` / `7-ARTIFACT-HUB-V2` / `3-FRONTEND` 的上下游承接关系
  - 覆盖：上游产出、中游治理承接、下游消费入口，以及 `/feed` `/ops` `/dashboard` 等关键路由归属

## 关键路由归属

- `/feed`：归 `7-ARTIFACT-HUB-V2` 中间层产品面与 feed projection 治理面
- `/ops`：归 `7-ARTIFACT-HUB-V2` 治理控制台与 `api/ops/*` 配套接口
- `/dashboard`：归 `3-FRONTEND` 下游用户入口
- `/chain`、`/board`、`/market`：默认按下游消费视图归 `3-FRONTEND`，由 `7-ARTIFACT-HUB-V2` 提供治理证据与中间层投影
- 共享约束：以 `docs/architecture/SYSTEM_BOUNDARIES.md` 与 `docs/architecture/SOURCE_OF_TRUTH.md` 为准，不在本目录重复定义路径真相源

## 已归档入口

- [FRONTEND_INTEGRATION_DESIGN.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/integration/FRONTEND_INTEGRATION_DESIGN.md)
  - 用途：`7-ARTIFACT-HUB-V2` 与 `3-FRONTEND` 的互联设计
  - 归档副本：`docs/integration/FRONTEND_INTEGRATION_DESIGN.md`
  - 原路径：`FRONTEND_INTEGRATION_DESIGN.md`

- [frontend-hub-trading三端联通.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/integration/frontend-hub-trading三端联通.md)
  - 用途：`3-FRONTEND`、`7-ARTIFACT-HUB-V2`、`6-TRADING` 三端联通规划
  - 归档副本：`docs/integration/frontend-hub-trading三端联通.md`
  - 原路径：`frontend-hub-trading三端联通.md`

- [OPS_UI_README.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/governance/OPS_UI_README.md)
  - 用途：`ops-ui` 与 Hub 的技术边界说明
  - 归档副本：`docs/governance/OPS_UI_README.md`
  - 原路径：`OPS_UI_README.md`
