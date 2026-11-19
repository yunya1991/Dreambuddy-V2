# 架构评审意见：P0-D3D 脑暴决策闭环 v0.1

- **版本**: v0.1 ｜ **日期**: 2026-11-19 ｜ **评审角色**: 架构评审
- **评审对象**: [SPEC-P0-D3D](SPEC-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)
- **评审依据**: [评审清单](REVIEW-CHECKLIST-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)、46 ADR、3+3 映射、GateFlow/GateGovernance、53 外部运行时治理
- **评审范围**: 仅 Blocker 项；Major/Minor 另行评审
- **总体结论**: **有条件接受（Conditional Accept）**

---

## 一、总体结论

| 结论 | 数量 |
|---|---|
| ✅ 通过（SPEC 层面，Phase 1 需测试固化） | 30 |
| ⚠️ 有条件通过（需补契约/强制机制） | 23 |
| ❌ 不通过（Phase 1 前必须修复） | 1 |

**判断**：D3D 的分层方向成立，没有根本性架构冲突；但当前 SPEC 多处是“原则正确、强制机制不足”。Phase 1 前必须关闭 **E8 + B1/B2 + H1/H6 + A6/A7 + C1 + E5/E7 + L2**，否则会出现“FactLock 不可验证、Hermes 可绕道、审批双账本”三类结构性风险。

---

## 二、A. 总体架构与边界

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| A2 | 执行/提案/决策/授权四分 | ✅ | §1 权责表、§0.3 闭环清晰 | Phase 1 用角色常量固化，禁止跨角色复用 |
| A4 | 不违反 ADR-6（Worker 不自证） | ✅ | §6.2 采纳门禁 + A 层终验 | 单测：Hermes 自签必须被拒 |
| A5 | A 层不拥有执行 | ✅ | A 层只立案，`BrainstormDispatcher` 派发 | 代码检查：A 层不得 import dispatcher |
| A6 | 不影响 DSH 主链路确定性 | ⚠️ | `AssistRequest` 默认同步会阻塞 hot path | 增加 `blocking=false` 默认、超时/预算；超限返回 partial |
| A7 | 不引入第二套 Ticket/审批真相 | ⚠️ | 新增 BrainstormTicket/DecisionRecord，状态归属未明确 | 补“状态所有权矩阵”：GateFlow=审批，Ticket=决策过程，DecisionRecord=结果，Feishu=通道 |
| A8 | 不冲突 49/live 边界 | ✅ | §6.2 T3 人工、§7.3 live 永不自动 | 加入 live/不可逆硬排除清单测试 |

## 三、B. 指挥权与角色分离

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| B1 | Hermes 不能直连 DSH | ⚠️ | SPEC 只写“不得”，没有技术隔离 | 独立 OS 用户、无 DSH 凭证、网络隔离；Router 拒绝 `source=hermes`；G11 测试 |
| B2 | DSH 重做必须引用 adopted DecisionRecord | ⚠️ | 规则已写，Router 未定义强制校验 | Router 增加 `decision_id` 必填与 `status=adopted`、`expires_at` 校验 |
| B3 | AssistRequest 只能 DSH→Hermes | ✅ | §2.4 方向明确 | 增加反向调用 403 测试 |
| B4 | Hermes 不能改 Gate/标准 | ✅ | §1.1 禁止清单 | 47/53 权限测试 |
| B5 | Hermes 不能审批自己 | ⚠️ | 四眼原则已写，但 `gate-governance` 的 Agent 席位仍可能被配置 | 新增 `hermes_secretary` 非投票角色；高风险禁止 Agent 席位 |

## 四、C. 立案与分级

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| C1 | 立案标准可判定 | ⚠️ | §2.1 是定性表，无法机器判定 | 新增 `TierPolicy`：risk/reversibility/blast_radius/evidence_gap/option_count/uncertainty 阈值 + `tier_reason` |

## 五、D. AssistRequest（外援）

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| D1 | 默认只读 | ✅ | §2.4 `read_only: true` | 单测：缺省必须只读 |
| D2 | 写操作必须带 Grant | ✅ | §2.4/§7.4 | 单测：无 Grant 写操作拒绝 |
| D7 | 防 DSH↔Hermes 乒乓 | ⚠️ | 只有单次 `max_attempts`，无跨请求上限 | 每 Ticket `assist_count ≤ 2`；同 `need_hash` 不得重复；超限转 BrainstormTicket |
| D8 | 外援结果仍需 A 层验收 | ✅ | §2.4 硬约束 | 单测：Hermes 结果不得绕过 A 层 |

## 六、E. Presentation Assist / FactLock

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| E1 | Core Facts 冻结 | ✅ | §2.5 `CanonicalFactBundle` + hash | 单测：bundle 不可变 |
| E2 | Hermes 只能引用 fact_id | ⚠️ | 有 `fact_refs`，但未定义“未映射数字”如何处理 | 增加 `FactUsageManifest`；`unmapped_claims` 非空即 fail |
| E5 | 图表数据来自 FactBundle | ⚠️ | 未定义图表数据契约 | 强制 `ChartSpec + chart_data.json`；纯图片图表 fail |
| E7 | 删除核心结论/风险可发现 | ⚠️ | 未定义 caveat/risk 清单 | 增加 `CaveatManifest` + 必需章节校验；缺失重大风险 fail |
| E8 | 四类成品事实提取方案 | ❌ | **SPEC 没有可执行的提取方案**，FactGate 无法落地 | 见下方“E8 专项修复”；Phase 1 前必须给出 |
| E10 | 未过门禁只能 DRAFT | ⚠️ | 状态位已写，交付 API 未定义 | `status=DRAFT/VERIFIED`；交付 API 只服务 VERIFIED |
| E11 | 对外发布强制人工授权 | ✅ | §7.5 | 发布 API 强制检查 ApprovalGrant |
| E14 | 敏感数据不外传 | ⚠️ | 只有原则，无 egress 策略 | 域名白名单 + 网络隔离 + 脱敏 + 禁止原始 FactBundle 外发 |

### E8 专项修复（Phase 1 前必须关闭）

**问题**：从 docx/pdf/pptx/xlsx 成品中反推事实，语义提取不可靠；仅靠 LLM 比对会引入新的幻觉。

**修复**：渲染器必须同时输出 `FactUsageManifest`，FactGate 以 manifest 为主、抽取为辅。

```json
{
  "artifact_id": "PA-1",
  "fact_usages": [
    {"fact_id": "F-1", "location": "docx:paragraph:12", "rendered_value": "12.3%", "transform": "identity"},
    {"fact_id": "F-2", "location": "pptx:slide:3:chart:1", "rendered_value": [1, 2, 3], "transform": "none"}
  ],
  "chart_specs": [
    {"chart_id": "C-1", "chart_type": "bar", "source_fact_ids": ["F-1"], "axis": {"unit": "%"}}
  ],
  "caveats": [
    {"caveat_id": "CV-1", "location": "docx:paragraph:30", "text": "样本外未验证"}
  ]
}
```

逐格式方案：

| 格式 | 主方案 | 辅方案 | 拒绝条件 |
|---|---|---|---|
| docx | `word/document.xml` 段落/表格 + manifest 定位 | 文本抽取抽查 | 无 manifest 且数字 token 无法映射 |
| pptx | slide XML + chart XML + 内嵌 workbook | 文本抽取抽查 | 只有图片、无 chart_data |
| xlsx | 单元格值/公式 + 命名区域 | 公式复算 | 公式不可复算 |
| pdf | **仅文本层 PDF**，PyMuPDF/pdftotext | 要求同时提供 docx/pptx 源文件 | 扫描件、纯图片 PDF |

**关闭标准**：docx/pptx/xlsx/pdf 四种格式各有一个 fixture，FactGate 能稳定复现 pass/fail。

## 七、F. 脑暴 Council / 实验 / 统计

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| F1 | Council 只是建议 | ✅ | §6.2 Adoption Gate | 单测：Council 通过但门禁失败 → 不 adopted |
| F2 | 主席规则/人工 | ✅ | §4.1 | 配置校验：Hermes 不得为主席 |
| F6 | T2/T3 至少 1 个实验 | ⚠️ | 未定义“无法实验”的例外清单 | 增加例外类型 + `judgment` + 人工签核 |
| F7 | 实验要素完整 | ⚠️ | `ExperimentPlan` 未定义 schema | 补 hypothesis/control/treatment/sample_size/metrics/thresholds/run_id |
| F9 | 无法实验转人工 | ✅ | §5.2 | 单测：judgment 必须带人工确认 |

## 八、G. DecisionRecord / Adoption Gate

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| G1 | 只有 adopted 可被 DSH 消费 | ✅ | §6.3/§8 | Router 单测 |
| G2 | 采纳以回测/正常推进为准 | ✅ | §6.2 | 45/CI 门禁集成测试 |
| G3 | 无适用门禁强制人工 | ✅ | §6.2 默认分支 | 单测：缺门禁 → 人工 |
| G4 | T3 人工终审 | ✅ | §6.2 | 权限测试 |
| G7 | 不允许原地改写 | ✅ | §6.3 | 单测：update 应被拒 |

## 九、H. 飞书授权 / 超时 / 通知

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| H1 | 飞书只是通道，GateFlow 唯一真相 | ⚠️ | 原则已写，但未定义唯一写入者 | 新增 `ApprovalBridge` 为唯一写 GateFlow 的组件；Hermes 不得直写 |
| H2 | Grant 有 scope/TTL/签名 | ⚠️ | 字段有，签名算法/密钥管理未定义 | 定义 Ed25519/HMAC、nonce、key rotation、grant_hash |
| H3 | 审批回写幂等 | ⚠️ | 未定义去重存储 | `request_id` 唯一约束 + 幂等表 + 重复 webhook 测试 |
| H4 | Hermes 不能审批自己 | ✅ | §7.2 四眼原则 | 单测：自审拒绝 |
| H5 | Gate/高风险超时永不自动通过 | ✅ | §7.3 + gate-flow 红线 | 单测：超时 → block |
| H6 | 紧急运维自动审批可控 | ⚠️ | “预授权”未定义策略注册表 | 新增 `UrgentPolicy`：class/risk/reversibility/TTL/budget/audit；Gate/live 排除 |
| H7 | live/不可逆永不自动 | ✅ | §7.3 | 硬排除测试 |
| H9 | 对外发布强制审批 | ✅ | §7.5 | 发布 API 校验 |

## 十、I. 安全 / 审计 / 可观测

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| I1 | 独立用户/沙箱 | ⚠️ | 未定义部署形态 | systemd 独立用户 + `NoNewPrivileges/ProtectSystem/PrivateTmp` + 网络白名单 |
| I2 | 禁止生产写/凭据/下单 | ✅ | §1.1 + 47 工具面 | 工具黑名单测试 |
| I6 | 敏感信息脱敏 | ⚠️ | 无字段级规则 | 定义 PII/secret 规则 + 产物前扫描 + 日志脱敏 |
| I7 | kill switch/撤销 | ⚠️ | 未定义撤销路径 | `revoke_grant(grant_id)` + 运行时 kill switch + 异常自动撤销 |

## 十一、K. 契约 / 模块 / 测试

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| K4 | 幂等键完整 | ⚠️ | 只覆盖部分场景 | 统一键：event/(decision_id,task_index)/request_id/assist_id；统一去重表 |
| K5 | 不直接写 GateRun/Ticket | ✅ | §11 模块职责 | 代码检查 + 依赖方向测试 |

## 十二、L. 3+3 / 46 / 53 / 47 / 49 对齐

| ID | 检查项 | 结论 | 依据/问题 | 修复建议（关闭标准） |
|---|---|---|---|---|
| L2 | 53 外部运行时治理 | ⚠️ | Hermes 尚未登记 `external_runtimes` | Phase 2 前登记：`allowed_roles/allowed_shells/deny_by_default/sandbox_profile` |
| L3 | 能力 ID 只来自 47 | ✅ | §10/§11 | registry 引用检查 |
| L4 | 53 ADR-2 不替代 MCP | ✅ | §10 | 调用路径检查 |
| L5 | L2 对 L1 只读 | ✅ | §1.1 | 工具集检查 |
| L6 | 49 实盘永不 MCP | ✅ | §6.2/§7.3 | 硬排除测试 |
| L7 | 46 ADR-9 Worker 只读 | ✅ | §2.4 默认只读 | 单测 |

---

## 十三、Phase 1 前必须关闭的 8 项

| 优先级 | ID | 事项 | 关闭标准 |
|---|---|---|---|
| P0 | E8 | 事实提取方案 | 四格式 fixture + `FactUsageManifest` 通过 |
| P0 | B1 | Hermes 技术隔离 | 独立用户/无凭证/网络隔离 + G11 |
| P0 | B2 | Router 强制 decision_id | 缺 decision_id 100% 拒绝 |
| P0 | H1 | ApprovalBridge 唯一写入 | 双写/直写测试失败 |
| P0 | H6 | UrgentPolicy 预授权 | Gate/live 排除 + 审计 |
| P1 | A6 | AssistRequest 异步化 | 默认非阻塞 + 超时/预算 |
| P1 | A7 | 状态所有权矩阵 | 四类状态无交叉写入 |
| P1 | C1 | TierPolicy 可判定 | 给定输入稳定输出 T0–T3 |

## 十四、评审结论

**有条件接受。** D3D 的架构方向正确，但当前版本不足以直接进入 Phase 1。建议先出 **SPEC v0.2**，补齐：

1. `FactUsageManifest` / `ChartSpec` / `CaveatManifest`；
2. `AssistRequest` 异步与防乒乓；
3. `ApprovalBridge` 唯一写入 + `UrgentPolicy`；
4. `TierPolicy` 与 `state_owner` 矩阵；
5. 53 `external_runtimes` 登记计划。

以上关闭后，可进入 Phase 1 契约实现。
