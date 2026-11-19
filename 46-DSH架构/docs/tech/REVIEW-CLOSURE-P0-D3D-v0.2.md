# 复审报告：P0-D3D v0.2 八项关闭项

- **版本**: v0.1 ｜ **日期**: 2026-11-19 ｜ **评审角色**: 架构复审
- **评审对象**: [SPEC-P0-D3D v0.2](SPEC-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.2.md)
- **复审范围**: 架构评审报告中的 8 项 Phase 1 前关闭项
- **复审方法**: 逐项核对 SPEC 条款、契约、验收门禁与关闭标准
- **总体结论**: **有条件通过**（3 项关闭 / 5 项有条件关闭 / 0 项不通过）

---

## 一、结论总表

| # | 关闭项 | 结论 | 依据 | 剩余缺口 |
|---|---|---|---|---|
| 1 | E8 事实提取 | ⚠️ 有条件关闭 | §2.5.2、§2.5.3、§6.4、G15 | `chart_data.json` schema、四格式 fixture、容差规则 |
| 2 | B1 Hermes 技术隔离 | ⚠️ 有条件关闭 | §8.1、§10.1、G18 | systemd unit、网络策略、隔离测试 |
| 3 | B2 Router 强制 decision_id | ✅ 关闭 | §8.1、G2 | 无架构缺口；实现测试即可 |
| 4 | H1 ApprovalBridge 唯一写入 | ✅ 关闭 | §7.1、§7.4、G16 | 无架构缺口；实现测试即可 |
| 5 | H6 UrgentPolicy 预授权 | ⚠️ 有条件关闭 | §7.3、§7.6、G19 | 策略注册表示例、强制排除测试 |
| 6 | A6 AssistRequest 异步化 | ⚠️ 有条件关闭 | §2.4、G11 | 异步结果投递机制、`assist_count` 存储 |
| 7 | A7 状态所有权矩阵 | ✅ 关闭 | §2.6 | 无架构缺口；交叉写测试即可 |
| 8 | C1 TierPolicy 可判定 | ⚠️ 有条件关闭 | §2.2.1、G17 | `risk_level`/`uncertainty_score` 的产出方与标定 |

**判断**：没有遗留的架构级 Blocker；5 项有条件关闭都可以在 Phase 1 内以“契约 + 测试”关闭，但不能直接进入生产接线。

---

## 二、逐项复审

### 1. E8 事实提取（⚠️ 有条件关闭）

**已关闭部分**

- 新增 `FactUsageManifest`，强制随成品交付（§2.5.2）；
- 明确 `unmapped_claims` 非空 → fail；
- docx/pptx/xlsx/pdf 四格式提取方案（§2.5.3）；
- 扫描件、纯图片 PDF 明确拒绝；
- FactGate 与 G15 已挂接。

**剩余缺口**

1. `chart_data.json` 只有名称，没有 schema；
2. 没有四格式 fixture 与期望输出；
3. 没有数值容差规则（四舍五入、单位换算、百分比/小数）；
4. 没有 docx 表格、页眉页脚、pptx 备注页的覆盖说明。

**关闭动作（Phase 1）**

- 定义 `ChartData` schema：`chart_id/series/x/y/unit/source_fact_ids`；
- 四种格式各 1 个 fixture，覆盖 pass/fail；
- 定义容差：默认相对误差 ≤ 0.1%，单位换算必须显式 `transform`；
- 明确“只校验正文 + 表格 + 图表 + 必需章节”，页眉页脚不参与事实校验。

**关闭标准**：四格式 fixture 全部可复现 pass/fail；`chart_data` 与 `ChartSpec` 不一致 100% fail。

---

### 2. B1 Hermes 技术隔离（⚠️ 有条件关闭）

**已关闭部分**

- 独立 `hermes-runtime` 用户；
- systemd 加固项已列；
- 文件系统、凭证、网络、资源、沙箱要求已列；
- Router 拒绝 `source=hermes`；
- G18 已定义。

**剩余缺口**

1. 没有具体 systemd unit 文件；
2. 没有网络策略落地方式（iptables/nftables/network namespace）；
3. 没有 `ApprovalBridge` 短期 token 的签发/轮换机制；
4. 没有隔离测试脚本。

**关闭动作（Phase 1）**

- 提交 `hermes-runtime.service` 模板；
- 明确网络策略：默认 deny egress，仅允许 47/ApprovalBridge/代理；
- 定义 token：`scope=approval_bridge`、TTL ≤ 15min、可撤销；
- 增加测试：Hermes 访问 DSH 内部 API → 连接失败/403 + 告警。

**关闭标准**：隔离测试 100% 通过，且无生产凭证泄露。

---

### 3. B2 Router 强制 decision_id（✅ 关闭）

**已关闭部分**

- Router 校验表完整：`source=brainstorm`、`decision_id` 必填、`adopted`、`expires_at`、`decision_hash`、`task_index`；
- 错误码明确；
- G2 已定义；
- `DecisionRecord` 已补 `decision_hash`。

**结论**：SPEC 层面关闭。Phase 1 只需按表实现并加单测。

---

### 4. H1 ApprovalBridge 唯一写入（✅ 关闭）

**已关闭部分**

- §7.1/§7.4 明确 `ApprovalBridge` 是 GateFlow 唯一写入者；
- Hermes 只能调用 Bridge，不得直写；
- Bridge 校验签名、`request_id`、`scope`、`nonce`；
- Bridge 失败 → block；
- 直写路径必须拒绝并告警；
- G16 已定义。

**结论**：SPEC 层面关闭。Phase 1 需实现“直写 GateFlow 必须失败”的测试。

---

### 5. H6 UrgentPolicy 预授权（⚠️ 有条件关闭）

**已关闭部分**

- `UrgentPolicy` 字段完整：`policy_id/task_class/risk/reversible/max_scope/max_budget/ttl_s/audit`；
- 硬排除：Gate/高风险、live、不可逆、安全、策略上线、生产写、权限变更；
- §7.6 明确 Gate 超时不自动通过；
- G19 已定义。

**剩余缺口**

1. 没有策略注册表示例；
2. 没有 `SYSTEM_GRANT` 的审计字段；
3. 没有“Gate/live 不得进入 UrgentPolicy”的编译期或运行期校验；
4. 没有超时自动审批的消息模板与回执。

**关闭动作（Phase 1）**

- 提供 2 条示例策略（低风险重启、日志轮转）；
- 定义 `SYSTEM_GRANT`：`policy_id/grant_id/scope/ttl/audit_ref`；
- 增加校验：`task_class` 含 gate/live/irreversible → 拒绝登记；
- 增加测试：Gate 超时 → block；Urgent 超时 → 仅白名单类自动。

**关闭标准**：Gate/live/不可逆 0 自动；白名单类自动审批 100% 可审计。

---

### 6. A6 AssistRequest 异步化（⚠️ 有条件关闭）

**已关闭部分**

- `blocking=false` 默认；
- `deadline_s`、预算、超时 `partial` 已写；
- 每 Ticket `assist_count ≤ 2`、`need_hash` 去重、无新信息不得重试；
- G11 已定义。

**剩余缺口**

1. 非阻塞后，`AssistResult` 如何回到 DSH 未定义（callback/event/poll）；
2. `assist_count` 与 `need_hash` 存在哪里未定义；
3. DSH 主循环如何处理“稍后返回的 partial”未定义；
4. 没有超时后 DSH 继续执行的状态机分支。

**关闭动作（Phase 1）**

- 定义投递方式：优先事件 `assist.completed`，DSH 订阅；备选 poll `GET /assist/{id}`；
- `assist_count/need_hash` 存在 Ticket 级状态存储；
- DSH 状态机增加 `waiting_assist → continued/partial` 分支；
- 增加测试：Hermes 超时 → DSH 继续且不重复。

**关闭标准**：非阻塞请求不拖慢主链路；超时/partial 可被 DSH 正确消费；无重复外援。

---

### 7. A7 状态所有权矩阵（✅ 关闭）

**已关闭部分**

- §2.6 明确六类状态的唯一所有者；
- 禁止跨模块写状态；
- 跨状态只引用 ID；
- 双写路径必须测试失败。

**结论**：SPEC 层面关闭。Phase 1 需加“交叉写必须失败”的测试。

---

### 8. C1 TierPolicy 可判定（⚠️ 有条件关闭）

**已关闭部分**

- 字段完整：`risk_level/reversible/blast_radius/evidence_gap_count/option_count/uncertainty_score`；
- 判定顺序明确（T3 → T2 → T1 → T0）；
- `tier_reason`、`policy_version` 必填；
- G17 已定义。

**剩余缺口**

1. `risk_level` 由谁产出未定义（A 层？Gate？人工？）；
2. `uncertainty_score` 的计算方式未定义；
3. `option_count` 来自 ProposalBundle 还是立案时？未定义；
4. 没有边界用例测试。

**关闭动作（Phase 1）**

- 定义输入来源：
  - `risk_level`：A 层/Gate 风险分类；
  - `uncertainty_score`：证据缺口 + 方案分歧 + 历史失败率的加权；
  - `option_count`：ProposalBundle 提交后回填，立案时允许 `null`；
- 提供 8 个边界用例：critical、irreversible、cross_domain、evidence_gap=2、uncertainty=0.7/0.4、option=2、全低；
- 增加测试：同输入稳定输出同一 tier。

**关闭标准**：8 个边界用例全部通过；无 `tier_reason` 不得立案。

---

## 三、复审结论

| 结论 | 数量 |
|---|---|
| ✅ 关闭 | 3（B2/H1/A7） |
| ⚠️ 有条件关闭 | 5（E8/B1/H6/A6/C1） |
| ❌ 不通过 | 0 |

**建议**：

1. 可以启动 Phase 1，但 5 项有条件关闭必须先落“契约 + 测试”，再进入 GateFlow/ApprovalBridge 生产接线；
2. Phase 1 的出口条件更新为：E8 fixture、B1 隔离测试、H6 策略注册表、A6 异步投递、C1 边界用例全部通过；
3. 5 项关闭后，再启动 Phase 2 的 GateFlow/ApprovalBridge/53 登记。

**复审判定：有条件通过，进入 Phase 1。**

---

## 四、Phase 1 落地回填（2026-11-19）

- 新增 14 个契约模块 + 1 个运行时隔离策略：`assist_request`、`presentation_contract`、`fact_lock`、`presentation_gate`、`brainstorm_ticket`、`proposal_bundle`、`d3d_evidence_bundle`、`experiment_result`、`decision_record`、`feishu_authorization_bridge`、`approval_bridge`、`urgent_policy`、`tier_policy`、`brainstorm_dispatcher`、`runtime_isolation`。
- 新增 `tests/test_d3d_contracts.py`，**38 项单测全绿**。
- E8：四格式提取 + `ChartData`/`ChartSpec` 一致性校验已落地；
- B1：`RuntimeIsolation.validate()` 已覆盖独立用户、systemd、网络、凭证、路径；
- H6：`UrgentPolicyRegistry` 已覆盖 Gate/live/irreversible 硬排除；
- A6：`AssistInbox` 已覆盖异步 partial 投递与去重；
- C1：`TierPolicy` 已覆盖 8 个边界用例。
- 关联回归：`evidence_bundle`、D3C 5 模块、A 层、45 门禁、Worker/Mandate 等测试全绿；`test_worker_roles.py::test_registry_has_eight_readonly_roles` 为既有失败（注册表 12 vs 断言 8），单独运行同样失败，与本次变更无关。
- 尚未接线：GateFlow 事件、真实 Hermes 运行时、53 登记、Presentation 渲染器。

---

## 五、Phase 2 接线回填（2026-11-19）

- 新增 `gateflow_brainstorm_bridge.py`：消费 `node.rejected` JSONL → 幂等立案；`node.rewound` 只记录不重复立案。
- 扩展 `brainstorm_dispatcher.py`：`ReworkTask.to_inbox_record()` + `enqueue_tasks()` → `dsh_worker_inbox.jsonl`。
- 扩展 `approval_bridge.py`：新增 `JsonlGateFlowSink`，审批事件落盘为 append-only JSONL。
- 新增 `53-DSH插件模块/external_runtimes.yaml`：`hermes` 当前 `enabled: false`、仅 sandbox、角色限 research/engineer。
- 新增 `tests/test_d3d_phase2_wiring.py`，**6 项单测全绿**；关联回归（Phase 1、evidence、Worker、Ticket、A 层、45、事件消费者）全绿。
- 前端已接：`/api/task/[id]/gate` 驳回后调用 `gateflow-event-export.ts` 写入 `.data/gateflow/*.jsonl`；新增 3 项 Jest 测试，`src/lib/task-board` 104 项测试全绿，`tsc --noEmit` 通过。
- 仍待接：真实飞书审批 API、真实 Hermes 运行时、Presentation 渲染器。
- 既有失败（未改相关文件，单独运行同样失败）：`test_worker_roles.py::test_registry_has_eight_readonly_roles`（12 vs 8）、`test_router_loop.py` 两条 `unassigned` 期望缺 `required_capabilities` 字段。
