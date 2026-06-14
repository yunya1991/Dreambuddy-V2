# 4-OPERATIONS — 运营治理知识

> 运营治理域覆盖系统元认知架构、索引体系、OKR管理、审批工作流等系统治理知识。
> L3 领域知识层 — 上层：[0-SCHEMA/](../0-SCHEMA/) |
> 同层：其他L3域 [1-TRADING/](../1-TRADING/)、[2-TECHNICAL/](../2-TECHNICAL/)、[3-THEORY/](../3-THEORY/) → 下层：[5-METHODOLOGY/](../5-METHODOLOGY/)
> 源：`governance-meta-chain`, `index-ops`, `lark-okr`, `lark-approval`

## 文件列表

| 文件 | 说明 | 来源 Skill |
|:---|---|:---|
| [三段式门禁](./三段式门禁.md) | 链路1→Spec→链路2 三段门禁规则与回滚约束 | governance-meta-chain |
| [索引体系](./索引体系.md) | Z轴层级索引架构、51 INDEX/README、每日审计 | index-ops |
| [OKR管理](./OKR管理.md) | OKR 结构、进展更新方法、API 命令 | lark-okr, feishu-orchestrator |
| [审批工作流](./审批工作流.md) | 审批创建、超时自动批准、OKR-Base同步链 | lark-approval, approval-timeout-check |
|
## 治理核心原则

1. **先调查后执行** — 链路1（脑暴）先搞清楚问题，不默认理解用户意图
2. **三段门禁强制** — 链路1未完成→不写Spec；Spec 6要素不全→不进链路2
3. **索引优先** — 遇事先查INDEX.md定位问题领域
4. **四组件同步** — 本地变更后必须同步 OKR + Base + 审批 + 知识库
5. **自进化闭环** — 每日归档需包含 A0矛盾分析 + A8知行检验

_最后更新：2026-06-13 | 来源：governance-meta-chain, index-ops_
