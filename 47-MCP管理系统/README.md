# 47-MCP管理系统

> **定位**: MCP（Model Context Protocol）能力封装域的**纯文档统筹层** — 收纳 L0 各能力域 MCP 壳的 SPEC、契约注册表、映射规范、评审与影响报告索引。
> 不含壳代码实现（壳代码在 `mcp_shells/` 与各域内），只做 MCP 域协作设计的 SSoT（Single Source of Truth）。

## 为什么需要这个模块

L0 六域 MCP 化封装（用户决策 2026-11-02，D1-D6）涉及跨域契约（统一信封映射、写工具治理、能力集矩阵、契约注册表），相关文档散落在 46-DSH架构、4-MEMORY、45-评测系统 等处。本模块把 MCP 域的**设计与契约文档**收敛为单一事实源，便于统一管理、评审与后续训练优化的按需取用。

## 核心原则

- **纯文档统筹**: 只管 SPEC/契约/注册表/评审，不移动壳代码实现层
- **壳不计入 port**: MCP 壳是 L0-P 的对外协议面，不占 SPEC-L0 §3.1 的 port 上限 6
- **先契约后扩面**: 新壳必须先在契约注册表登记（SPEC §3 P0），未注册不得上线
- **边界**: 实盘交易链路（11/yijing/v15/止损）永不暴露 MCP；库管（38）只读

## 文档清单

| 文档 | 职责 | 状态 |
|---|---|---|
| [docs/tech/SPEC-L0-MCP-PACKAGING-v0.3.md](./docs/tech/SPEC-L0-MCP-PACKAGING-v0.3.md) | L0 六域 MCP 封装实施 SPEC：契约映射/写工具治理/P0-P3 路线/D1-D6 决策记录 | **v0.3 决议落定**（B1-B6/G1-G3），可开工；R8 终审待云端签发 |
| [docs/tech/ALIGNMENT-46-47-v1.0.md](./docs/tech/ALIGNMENT-46-47-v1.0.md) | 与 46-DSH 升级文档的对齐审查：6 冲突 + 3 架构缺口 + 合并开工顺序 + Go/No-Go | 开工前终审输入 |
| [docs/tech/ASSESSMENT-L0-MCP-GENERALITY-v0.1.md](./docs/tech/ASSESSMENT-L0-MCP-GENERALITY-v0.1.md) | L0 MCP 通用性评估：八维评分、六个硬障碍、三件套、A→B 路线；P3 拆 P3a/P3b + P4 共享沉淀草案（暂不开发） | 🟢 **P0-P3b 已落地（2026-11-08）**；P3a 的 SDK/wheel 后置；G1-b 全局软上限 80 |
| [docs/tech/SPEC-L0-MCP-GATEWAY-v0.1.md](./docs/tech/SPEC-L0-MCP-GATEWAY-v0.1.md) | L0 角色能力网关协议：角色投影、forbidden 语义、失败分型、壳生命周期、单条接入、G1 已决 | ✅ P1 已落地（2026-11-08） |
| [docs/tech/SPEC-L0-MCP-DISCOVERY-v0.1.md](./docs/tech/SPEC-L0-MCP-DISCOVERY-v0.1.md) | L0 能力发现：Agent Card schema、静态索引、运行时 `_meta`、协议版本协商、未做边界 | ✅ P3b 已落地（2026-11-08） |
| [docs/tech/TECH-L0-MCP-v0.1.md](./docs/tech/TECH-L0-MCP-v0.1.md) | MCP 技术设计：壳层 envelope、工具注册表、能力集、已落地工具测试方法；§6.4 `mcpctl`、§6.5 网关、§6.6 发现/协商、§6.7 Docker、§10.1 云端审计（v0.1.5） | ✅ M1①-④ 已落地；P0-P3 控制面/网关/运行时/发现/分发已接线 |
| [docs/tech/SPEC-L0-DOMAIN-AGENTS-v0.2.md](./docs/tech/SPEC-L0-DOMAIN-AGENTS-v0.2.md) | 域内 agent SPEC：Phase A-E 路线 + Dream-RSI `V_new(π,T)` α 分量 | ✅ v0.2；Phase A 已落地 |
| [docs/tech/SPEC-L0-DATA-AGENT-v0.1.md](./docs/tech/SPEC-L0-DATA-AGENT-v0.1.md) | 数据域 agent L0 底层能力管理协议：六子 agent 独立子协议（[data-agents/](./docs/tech/data-agents/)）+ DAL 查询面扩展 + P0-P3 路线 | ✅ v0.1；P0/P1/P2 已落地（macro/chain/flow/breadth/capital_flow/sentiment 六子协议文件已登记） |
| [docs/tech/SPEC-L0-AGENT-TRAIN-BASE-v0.1.md](./docs/tech/SPEC-L0-AGENT-TRAIN-BASE-v0.1.md) | 训练基座 SPEC：TB1 PSI / TB2 Beta verify / TB3 AlphaPareto 七维 / TB4 Thompson / TB5 GRPO | ✅ TB1-TB5 + Phase A **48/48 TDD**，影子验证 PASS |
| [docs/tech/SPEC-L0-L1-DOMAIN-DISCOVERY-v0.1.md](./docs/tech/SPEC-L0-L1-DOMAIN-DISCOVERY-v0.1.md) | L0/L1 域发现 SPEC：静态 domain_transmission、observe() 消费、P4 沙箱（§4.5）、窗口化采集（§3.3 / §4.6.12） | ✅ Phase 0 + Phase E 已落地：`mcp_shells/_shared/assets/domain_transmission_static.json` + `agent_mail_shadow.py`（19 测试）+ `collect_windowed` 窗口化采集（18 测试，云端每小时定时任务；当前仅 bear 单桶） |
| [docs/tech/SPEC-L0-AGENT-COMM-SHADOW-v0.1.md](./docs/tech/SPEC-L0-AGENT-COMM-SHADOW-v0.1.md) | COMM-SHADOW SPEC：第二观察点旁路 + §5.6 四类 payload（domain_hypothesis / transmission_evidence / validation_receipt / cross_domain_coupling） | 🟡 Phase 0 已落地（静态旁路 observe）；shadow 双跑等 bcrm2 切流窗口 |
| [docs/tech/ROADMAP-L0-L1-CLOSED-LOOP-v0.1.md](./docs/tech/ROADMAP-L0-L1-CLOSED-LOOP-v0.1.md) | L0/L1 闭环路线图：12 里程碑 + 4 阻塞（B1/B2 已消解，B3 GPU / B4 bcrm2 仍阻塞） | ✅ 状态已按实测回填（三端 HEAD 一致） |
| [docs/tech/PLAN-L0-MCP-P0-P3-v0.1.md](./docs/tech/PLAN-L0-MCP-P0-P3-v0.1.md) | MCP 封装 P0-P3 实施计划（任务拆解 + 依赖 + 验收） | ✅ 计划文档 |
| [docs/tech/REVIEW-AGENT-ARCH-v0.1.md](./docs/tech/REVIEW-AGENT-ARCH-v0.1.md) | Agent 架构评审记录（争议点 + 结论 + 待办） | ✅ 评审归档 |
| [docs/tech/SPEC-L0-TRADE-EXEC-MCP-v0.1.md](./docs/tech/SPEC-L0-TRADE-EXEC-MCP-v0.1.md) | L0 交易执行 MCP SPEC：四 Port 契约 + paper 主出口 + 实盘旁路（遵守实盘链路永不暴露 MCP） | 🟢 v0.5 阶段一~七已落地（2026-11-06 补 ExitCheckPort/`check_exit` + 定容钳位 + 13/16/22/11 域对标矩阵 §11） |
| [docs/tech/REVIEW-L0-TRADE-EXEC-MCP-v0.1.md](./docs/tech/REVIEW-L0-TRADE-EXEC-MCP-v0.1.md) | trade-exec MCP SPEC 评审报告（2 P0 / 5 P1 / 4 P2） | ✅ v0.1 已出；v0.5 P0 已封口（16/22 域分层不并入，见 SPEC §11） |
| [docs/tech/SHADOW-REPORT-L0-REA-M3.md](./docs/tech/SHADOW-REPORT-L0-REA-M3.md) | REA 域 M3 影子报告（观察点对比 + 门槛值） | ✅ 影子归档 |

## 外部关联文档（原位保留，本模块登记索引）

| 文档 | 位置 | 关系 |
|---|---|---|
| REPORT-L0-MCP-DSH-IMPACT v1.1 | `46-DSH架构/docs/tech/` | 影响评估（本 SPEC 上游，评估归档，已勘误 F1/F2/F6/F7） |
| ANALYSIS-L0-MCP-ENCAPSULATION | `46-DSH架构/docs/tech/` | 评估底稿 |
| SPEC-L0-three-layer-architecture | `44-三端协作架构系统/docs/tech/` | 六 port + 统一信封（内层不动） |
| COLLABORATION-CONTRACT.md | `35-广义认知系统协作模块/` | 认知 MCP 工具面协作契约（待按 SPEC §6.3 更新 scope/写门禁） |

## 存量 MCP 面登记（契约注册表 P0 前过渡）

> **状态说明**: 契约注册表 `registry/mcp_capabilities.yaml` 与顶层 `mcp_shells/` 目录**已建成**（M1①-④ 落地，壳含 l0_data / l0_eval / l0_rea / l0_store_admin）；下表为注册表落地前的过渡时登记，现由注册表为唯一事实源。

| 面 | 类型 | 工具数 | 位置 |
|---|---|---|---|
| 认知（含检索聚合） | stdio server（ssh 云端默认 + 本地只读降级，D5） | 7 | `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` |
| 39 金融语义 | stdio server（归 Search 语义面，D6） | 4 | `39-金融语义蒸馏系统/scripts/mcp_server.py` |
| REA | MCP client（调外部 npm rea-agents，非本域 server） | — | `33-REA逆向解析工程/adapters/rea_mcp_adapter.py` |

## 维护

- 新增/修订 MCP 相关 SPEC、契约、注册表时更新本 README 文档清单
- 由 `0-系统文档管理/4-工具与自动化/doc_coverage.py` + `link_checker` 校验断链
