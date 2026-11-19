# 评审清单：P0-D3D 脑暴决策闭环 v0.1

- **版本**: v0.1 ｜ **日期**: 2026-11-19 ｜ **状态**: 待评审
- **评审对象**: [SPEC-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md](SPEC-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)
- **评审目标**: 判断是否可进入 Phase 1 契约实现；识别必须在实现前关闭的架构/安全/可验证性缺口
- **使用方式**: 逐项标记 `✅ 通过 / ⚠️ 有条件 / ❌ 不通过`，`❌` 必须给出证据与修复建议

---

## 一、评审角色

| 角色 | 关注点 |
|---|---|
| 架构评审 | 分层、指挥权、与 46/53/3+3 的一致性 |
| 治理/安全评审 | 审批真相、权限边界、审计、数据泄露 |
| 工程评审 | 契约可实现性、事实提取、幂等、失败恢复 |
| 业务/产品评审 | 脑暴效率、交付体验、责任归属 |
| 运维/飞书评审 | 审批超时、告警、值班与升级 |

## 二、严重度定义

| 级别 | 含义 | 处理 |
|---|---|---|
| **Blocker** | 会导致指挥权失守、审批失效、事实失真或无法验收 | Phase 1 前必须关闭 |
| **Major** | 会导致返工、成本失控或验收不可执行 | Phase 2 前必须关闭 |
| **Minor** | 文档/体验/优化项 | 可排期 |

---

## 三、检查项

### A. 总体架构与边界

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| A1 | D3D 是否新增了不必要的层？ | Major | 对照 3+3 映射，确认归入 L2-K/L2-E，不新增层 |
| A2 | 是否保持“DSH 执行、Hermes 提案、Council 决策、人授权”？ | Blocker | 逐条核对 §1 权责表与 §0.3 闭环 |
| A3 | 是否与 P0-D3C 场外助手职责重叠或冲突？ | Major | 对照 D3C §2/§5，确认 D3D 只承接决策层 |
| A4 | 是否违反 ADR-6（Worker 不自证）？ | Blocker | 确认终审为 A 层 + 门禁 + 人工，Hermes 无终审 |
| A5 | 是否违反 A 层“不拥有执行”？ | Blocker | 确认 A 层只立案，不派工、不设计重做方案 |
| A6 | 是否影响 DSH 主链路的强规则与确定性？ | Blocker | 确认 D3D 是旁路，不进入 hot path |
| A7 | 是否引入第二套 Ticket/审批事实源？ | Blocker | 确认 GateFlow 唯一审批真相，DecisionRecord 只做决策记录 |
| A8 | 是否与 49 交易协议/live 边界冲突？ | Blocker | 确认 live/不可逆永不自动，T3 人工终审 |

### B. 指挥权与角色分离

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| B1 | Hermes 是否可能直接调用 DSH task/worker/dispatch？ | Blocker | 检查凭证与接口白名单；G11 测试 |
| B2 | DSH 是否只能通过 DecisionRecord.adopted 重做？ | Blocker | 检查 Router 是否强制 decision_id；G2 测试 |
| B3 | AssistRequest 是否只能 DSH→Hermes？ | Blocker | 检查方向校验与反向派工拒绝；G11 |
| B4 | Hermes 是否能修改 Gate/GatePolicy/验收标准？ | Blocker | 检查权限与 API；应为只读 |
| B5 | Hermes 是否能审批自己的提案？ | Blocker | 检查四眼原则与席位规则 |
| B6 | Council 主席是否可能由 Hermes 担任？ | Major | 检查席位配置与规则 |
| B7 | Hermes 的 dissent 是否会被摘要删除？ | Major | 检查 DecisionRecord 结构与 G5 测试 |
| B8 | DSH 是否可能借 AssistRequest 绕过 A 层？ | Major | 检查 A 层硬门禁不豁免；R7 对策 |

### C. 立案与分级

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| C1 | 哪些缺口立案、哪些直接重做，是否可判定？ | Blocker | 对照 §2.1 表，逐类给例子 |
| C2 | T0–T3 分级是否可机器判定？ | Major | 检查 risk/uncertainty/evidence_gap 字段 |
| C3 | 是否存在“所有事都开 Council”的风险？ | Major | 检查 T0/T1 默认路径 |
| C4 | 同一 gap_key 是否幂等？ | Major | 并发/重复事件测试 |
| C5 | 状态机是否有超时与升级？ | Major | 检查 §2.3 时间盒 |
| C6 | 缺口消失/重复时能否取消？ | Minor | 检查 cancelled 分支 |
| C7 | 立案是否引用原始失败证据？ | Major | 检查 evidence_refs 必填 |
| C8 | 是否区分“能力缺口”与“标准不清”？ | Major | 标准不清应回 S 层，不应脑暴 |

### D. AssistRequest（外援）

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| D1 | AssistRequest 是否默认只读？ | Blocker | 检查 read_only 默认值与写操作授权 |
| D2 | 写操作是否必须带 AutonomyGrant/ApprovalGrant？ | Blocker | 检查授权绑定与超范围拒绝 |
| D3 | 是否有次数/TTL/成本上限？ | Major | 检查 budget 字段与超限转立案 |
| D4 | AssistResult 是否可被 DSH 直接消费？ | Major | 检查 schema 与 status 分支 |
| D5 | Hermes 失败时是否升级而不是静默？ | Major | 检查 partial/needs_brainstorm/rejected |
| D6 | 是否记录 assist_id + trace_id？ | Major | 检查审计日志 |
| D7 | 是否可能出现 DSH↔Hermes 乒乓？ | Blocker | 检查次数上限与防重复 |
| D8 | 外援结果是否仍需 A 层验收？ | Blocker | 检查硬门禁不豁免 |

### E. Presentation Assist / FactLock

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| E1 | Core Facts 是否冻结且不可变？ | Blocker | 检查 CanonicalFactBundle hash 与版本 |
| E2 | Hermes 是否只能引用 fact_id，不能自造核心事实？ | Blocker | 检查 Artifact 与 FactBundle 映射 |
| E3 | 派生数字是否必须给公式与输入 fact_id？ | Major | 检查 DerivedFact 结构 |
| E4 | 补充信息是否强制标注来源？ | Major | 检查 supplementary_refs 与冲突检测 |
| E5 | 图表数据是否必须来自 FactBundle？ | Blocker | 要求 renderer 输出 chart_data.json/spec，禁止纯图片 |
| E6 | 轴/刻度/单位是否可能误导？ | Major | 检查图表规范与人工抽查 |
| E7 | 核心结论/风险/免责声明被删是否能发现？ | Blocker | 检查 missing 与 material caveat 校验 |
| E8 | 四类成品（docx/pdf/pptx/xlsx）如何提取事实？ | **Blocker** | 必须给出逐格式提取方案；扫描 PDF 不接受 |
| E9 | Fact Gate 是否能识别四舍五入/单位换算？ | Major | 检查容差规则与单位归一 |
| E10 | 未过门禁是否只能标 DRAFT？ | Blocker | 检查交付 API 与状态位 |
| E11 | 对外发布是否强制人工授权？ | Blocker | 检查 §7.5 与发布流程 |
| E12 | 事实更新后旧成品是否失效？ | Major | 检查 fact_bundle_hash 与 superseded |
| E13 | 模板版本是否固定？ | Major | 检查 template 版本与 section 校验 |
| E14 | 敏感数据是否可能外传？ | Blocker | 检查沙箱、白名单、脱敏 |

### F. 脑暴 Council / 实验 / 统计

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| F1 | Council 是否只是建议，不是采纳票？ | Blocker | 检查 §6.2 Adoption Gate |
| F2 | 主席是否由规则/人工担任？ | Blocker | 检查席位配置 |
| F3 | 是否有反方席位与最强反驳要求？ | Major | 检查 32 辩论接入 |
| F4 | 时间盒与最大轮次是否明确？ | Major | 检查 §4.2 |
| F5 | 无新证据是否禁止重复辩论？ | Major | 检查 progress ledger |
| F6 | T2/T3 是否强制至少 1 个对照实验？ | Blocker | 检查 ExperimentResult 必填 |
| F7 | 实验是否有对照组、样本量、指标、阈值？ | Blocker | 检查 ExperimentPlan |
| F8 | 统计是否要求效应量/CI/多重比较？ | Major | 检查 45 统计门 |
| F9 | 无法实验时是否标记 judgment 并人工确认？ | Blocker | 检查 judgment 分支 |
| F10 | 实验成本/算力是否可控？ | Major | 检查 SLA 与预算（Q3） |

### G. DecisionRecord / Adoption Gate

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| G1 | 只有 adopted 可被 DSH 消费？ | Blocker | 检查 Router 校验 |
| G2 | 采纳是否以回测/正常推进为准？ | Blocker | 检查 §6.2 表 |
| G3 | 无适用门禁是否强制人工？ | Blocker | 检查默认分支 |
| G4 | T3 是否人工终审？ | Blocker | 检查权限 |
| G5 | dissent 是否原样保留？ | Major | 检查 schema 与 G5 |
| G6 | 决策过期/证据失效是否 superseded？ | Major | 检查 expires_at 与版本 |
| G7 | 是否允许原地改写 DecisionRecord？ | Blocker | 应禁止，只能新记录 |
| G8 | 全链路是否可回放到 evidence/experiment？ | Major | 检查 trace_id + refs |

### H. 飞书授权 / 超时 / 通知

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| H1 | 飞书是否只是授权通道，GateFlow 仍是唯一真相？ | Blocker | 检查回写路径与双账本测试 |
| H2 | ApprovalGrant 是否有 scope/TTL/签名？ | Blocker | 检查 §7.2 |
| H3 | 审批回写是否幂等？ | Blocker | 用 request_id 重复回写测试 |
| H4 | Hermes 是否能审批自己的请求？ | Blocker | 检查四眼原则 |
| H5 | Gate/高风险门超时是否永不自动通过？ | Blocker | 检查 §7.3 与 gate-flow 红线 |
| H6 | 紧急运维超时自动审批是否有预授权策略/预算/审计？ | Blocker | 检查分类与例外清单 |
| H7 | live/不可逆/安全事件是否永不自动审批？ | Blocker | 检查硬排除 |
| H8 | 常规只读/非代码/脑暴参与是否只通知？ | Major | 检查 §7.5 与 G12 |
| H9 | 对外发布研报/图表是否强制审批？ | Blocker | 检查 §7.5 |
| H10 | 审批超时升级路径是否明确？ | Major | 检查 remind/escalate/block |

### I. 安全 / 审计 / 可观测

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| I1 | Hermes 是否运行在独立系统用户/沙箱？ | Blocker | 检查部署与权限 |
| I2 | 是否禁止生产库写/凭据变更/下单？ | Blocker | 检查工具黑名单与网关 |
| I3 | 所有动作是否带 trace_id/assist_id/decision_id？ | Major | 检查日志与 G10 |
| I4 | 审计日志是否 append-only？ | Major | 检查存储与权限 |
| I5 | 是否记录模型版本/prompt_hash？ | Major | 检查 ProposalBundle/DecisionRecord |
| I6 | 敏感信息是否脱敏？ | Blocker | 检查日志/证据/成品 |
| I7 | 是否有 kill switch/撤销授权？ | Blocker | 检查 AutonomyGrant/ApprovalGrant 撤销 |
| I8 | 是否有异常检测（越权/异常成本）？ | Major | 检查告警规则 |

### J. 效率 / 成本 / SLA

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| J1 | T0/T1 是否避免完整 Council？ | Major | 检查分级路径 |
| J2 | 相似缺口是否批量？ | Minor | 检查 gap_key 聚合 |
| J3 | 证据/决策是否可复用？ | Major | 检查缓存与有效期 |
| J4 | 是否有单次成本/时延上限？ | Major | 检查 budget/SLA |
| J5 | 审批是否异步、不阻塞主链路？ | Major | 检查架构 |
| J6 | 是否有 intervention_rate 指标防止 Hermes 变影子主链路？ | Major | 检查度量与季度目标 |

### K. 契约 / 模块 / 测试

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| K1 | 11 个模块职责是否单一、无循环依赖？ | Major | 依赖图检查 |
| K2 | 非法输入是否 FAIL-OPEN？ | Major | 单测 |
| K3 | 是否线程安全/可并发？ | Major | 并发测试 |
| K4 | 幂等键是否覆盖重复事件/重复派发/重复回写？ | Blocker | 单测 |
| K5 | 是否不直接写 GateRun/Ticket？ | Blocker | 代码检查 |
| K6 | 是否与 D3C 模块兼容（bounded_autonomy/dual_acceptance/deadletter）？ | Major | 集成测试 |
| K7 | 是否有契约样例与 schema 校验？ | Major | JSON Schema/单测 |
| K8 | 是否有失败恢复与重试策略？ | Major | 故障注入测试 |

### L. 3+3 / 46 / 53 / 47 / 49 对齐

| # | 检查项 | 严重度 | 验证方法/证据 |
|---|---|---|---|
| L1 | 是否归入 L2-K/L2-E，不新增层？ | Major | 3+3 映射 |
| L2 | Hermes 是否按 53 外部运行时治理、deny-by-default？ | Blocker | 53 白名单 |
| L3 | 能力 ID 是否只来自 47？ | Blocker | 检查 registry 引用 |
| L4 | 是否遵守 53 ADR-2（不替代 MCP）？ | Blocker | 检查调用路径 |
| L5 | 是否遵守 3+3 “L2 对 L1 只读”？ | Blocker | 检查工具集 |
| L6 | 是否遵守 49 “实盘永不 MCP”？ | Blocker | 检查 T3/工具 |
| L7 | 是否与 46 ADR-9（Worker 只读）一致？ | Blocker | 检查 AssistRequest 默认只读 |
| L8 | 文档索引是否同步（46/53）？ | Minor | 检查 README |

---

## 四、必须回答的开放问题

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| Q1 | T1 是否允许全自动采纳？ | 决策风险 | 仅低风险、可逆、有门禁时允许 |
| Q2 | Council 是否常设？ | 成本/效率 | 按需组建，常设只保留主席与记录 |
| Q3 | 实验 SLA 与算力预算？ | 可行性 | 由 45/48 给出分级 SLA |
| Q4 | “重要决策可正常推进”的边界？ | 审批有效性 | 明确为非高风险、可逆；高风险仍审批 |
| Q5 | 四类成品的 Fact Gate 提取方案？ | 可验证性 | docx/pptx 用 XML，xlsx 用单元格，pdf 用文本层；扫描件不接受 |

---

## 五、Go / No-Go 标准

### 可以进入 Phase 1

- 所有 **Blocker** 已关闭或有明确修复方案与负责人；
- G0–G14 均有可执行测试或验证方法；
- Q1/Q4/Q5 有明确结论；
- 46/53 索引已同步。

### 不可以进入 Phase 1

- 存在未关闭的指挥权/审批真相/事实失真 Blocker；
- Fact Gate 无法对至少 docx/pdf/pptx 三种格式给出可执行提取方案；
- live/不可逆仍可能被自动审批；
- Hermes 仍可能直接调用 DSH 派工接口。

---

## 六、评审结论模板

```text
评审结论：接受 / 有条件接受 / 不接受
Blocker：x 项（列出编号）
Major：x 项（列出编号）
Minor：x 项（列出编号）
必须修改：...
建议修改：...
负责人/截止：...
是否进入 Phase 1：是 / 否
```
