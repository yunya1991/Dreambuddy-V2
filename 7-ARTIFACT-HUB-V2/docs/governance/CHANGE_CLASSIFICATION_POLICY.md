# Change Classification Policy

本文件冻结 `7-ARTIFACT-HUB-V2` 当前工作树改动的分类规则，用于回答“哪些改动可以一起提交，哪些必须分离审查”。

## 1. Change Classes

| Class | Includes | Commit Policy |
|---|---|---|
| Product implementation | `src/feed`, `src/ops-ui`, feature-specific docs | can ship together when same feature |
| Hub core evolution | `artifact-store`, `meta-store`, `router-engine`, `work-order` | separate review line |
| Upstream trading | `6-TRADING/*` | never mix with middle-layer feature commits |
| Downstream frontend | `3-FRONTEND/*` | never mix with middle-layer feature commits |
| Runtime assets | `dreambuddy/artifacts/*` | treat as data, not normal code diff |
| Shared config | `dreambuddy/config/*` | separate review line |

## 2. Separation Rules

- `7-ARTIFACT-HUB-V2` 的产品功能改动只与同一功能线的文档一起提交，不与 Hub 核心演进混提。
- `artifact-store`、`meta-store`、`router-engine`、`work-order` 等中间层核心能力单独审查，避免被页面级功能掩盖。
- `6-TRADING/*` 归上游生产层，必须与中间层功能提交分离。
- `3-FRONTEND/*` 归下游消费层，必须与中间层功能提交分离。
- `dreambuddy/artifacts/*` 视为运行态证据与状态，不按普通代码 diff 处理。
- `dreambuddy/config/*` 视为共享配置，任何修改都应走单独审查线。

## 3. Review Intent

- 本规则只冻结改动分类与提交流水线边界。
- 本规则不要求立即移动文件或重组代码目录。
- 更细的运行态资产约束以 `RUNTIME_ASSET_GOVERNANCE.md` 为准。
