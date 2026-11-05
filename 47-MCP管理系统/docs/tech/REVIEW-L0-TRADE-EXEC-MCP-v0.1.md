# REVIEW — SPEC-L0-TRADE-EXEC-MCP v0.1 评审报告

- 评审对象：[SPEC-L0-TRADE-EXEC-MCP-v0.1.md](./SPEC-L0-TRADE-EXEC-MCP-v0.1.md)
- 评审日期：2026-11-05
- 评审依据：47-MCP 现有契约注册表（registry/mcp_capabilities.yaml v0.3）、SPEC-L0-MCP-PACKAGING-v0.3、TECH-L0-MCP-v0.1、48-涌现架构 SPEC、13/16/22/11 域实证代码
- 评审结论：**有条件通过（P0 阻断项 2 项须先解决，方可进入阶段一）**

---

## §0 评审结论摘要

| 维度 | 评级 | 说明 |
|---|---|---|
| 架构定位合理性 | ⚠️ 存疑 | 与 47-MCP 奠基性硬约束"实盘链路永不暴露 MCP"正面冲突 |
| 契约完整性 | ⚠️ 有缺口 | 四 Port 契约清晰，但工具→L0 port/domain 映射、调用方身份未定义 |
| 事实准确性 | ❌ 有错误 | 48 域"七关门禁"与实际"三关"不符；13 域"孤岛"描述不准确 |
| 可实施性 | ✅ 基础好 | 13/16/22 域存量代码可复用，paper_adapter 已存在 |
| 风控严谨性 | ✅ 设计到位 | fail-closed 风控、单实例单模式、定容不暴露为独立 Port 均合理 |

**总体判定**：P0 阻断项 2 项，P1 重要缺口 5 项，P2 优化建议 4 项。P0 解决后可进入阶段一（Port 契约冻结）。

---

## §1 P0 阻断项（必须先解决）

### P0-1 与"实盘链路永不暴露 MCP"硬约束的根本冲突

**冲突原文**（47-MCP SPEC-L0-MCP-PACKAGING-v0.3 §0 硬约束 / §1）：

> 实盘交易链路（11/yijing/v15/止损）**永不暴露 MCP**
> 热路径（L1 判定、实盘链路）**永不走 MCP**（零 token 与低延迟承诺）

本 SPEC §0.1 明确将 trade-exec MCP 定位为"**唯一真实执行出口**——所有实盘下单经此 MCP"，§2.2 工具集包含 `place_order`（实盘下单）。这是对 47-MCP 奠基性边界红线的**直接违反**，而非细节偏差。

新 SPEC §5 声称"不放宽既有门禁"，但实际上恰恰放宽了最核心的边界约束。

**两种解决路径（需用户/架构组决策）**：

| 路径 | 做法 | 影响 |
|---|---|---|
| A. 修订硬约束 | 在 SPEC-L0-MCP-PACKAGING 中增补例外条款：trade-exec MCP 为唯一获准接触实盘的 MCP，须经 R8 终审签发 | 需修订奠基性 SPEC，改动面大；但与本 SPEC 定位一致 |
| B. 重新定位 | trade-exec MCP **仅承载 paper 模式**（模拟盘/策略验证），实盘仍走 11 域直连；MCP 不接触真实下单 | 保留硬约束不变；但"唯一真实执行出口"定位需改写为"唯一模拟执行出口 + 实盘网关旁路" |

**建议**：路径 B 风险更低。理由：47-MCP 硬约束的存在理由是"零 token 与低延迟承诺"，即使是 300 秒级轮询，MCP stdio 进程拉起 + 信封序列化的额外开销（10-50ms）在极端行情下仍可能导致滑点失控；而 paper 模式无此风险。

### P0-2 48 域"七关门禁"事实错误

本 SPEC §0.3、§5 均提到"48 域 §5 七关门禁"。

**实证**：48-涌现架构 SPEC-EMERGENCE-EVOLUTION-v0.1 §5 明确为"**双度量+OOD+稳健性三关**（§5 门禁）"，不是七关。

**影响**：门禁数量错误会导致实施阶段对齐错误——若按"七关"设计强制点，会多出 4 道不存在的门禁；若按"三关"设计，又与本 SPEC 引用矛盾。

**修复**：将本 SPEC 中"48 域 §5 七关门禁"统一改为"48 域 §5 三关门禁（双度量+OOD+稳健性）"。

---

## §2 P1 重要缺口（阶段一前必须明确）

### P1-1 工具→L0 port/domain 枚举映射未定义

**现状**：注册表 enums 为：
- `port`: [memory, collector, search, store, analysis, event]
- `domain`: [cognition, search, semantic, data, eval, rea, store-admin]

本 SPEC 的四 Port（OrderPort/RiskCheckPort/PositionPort/AccountPort）是**交易执行域内的接口契约**，不是 L0 port 枚举。但 trade-exec 壳在注册表登记时，其工具（place_order/cancel_order/get_positions/get_balance）必须映射到现有 port/domain 枚举之一。

**缺口**：SPEC 未说明映射关系。可选方案：
1. 复用 `event` port（当前 6 壳中无任何壳使用 event port），domain 新增 `trade-exec`
2. 新增 `execution` port（但 port 上限 6 已满，需先修订 SPEC-L0 §3.1）
3. 归到 `analysis` port（语义牵强）

**建议**：方案 1——复用 event port + 新增 trade-exec domain。理由：event port 语义为"事件触发"，交易信号→执行可视为事件流；domain 新增 trade-exec 不占 port 上限（壳不计入 port 上限，见 SPEC-L0-MCP-PACKAGING §3）。

### P1-2 调用方身份未定义

**现状**：注册表 worker_roles 三角色（research/engineer/verifier）均为只读，ADR-9/H7 硬约束："requires_mandate=true 的写工具禁止出现在任何 Worker 角色工具集中"。

trade-exec 壳的 place_order/cancel_order 是写操作（且是破坏性的——真金白银），requires_mandate 必须为 true，因此**不能分配给任何 Worker 角色**。

**缺口**：SPEC 未说明谁来调用 trade-exec 壳。可选方案：
1. 编排侧（orchestrator）持 Mandate 直接调用（不经 Worker）
2. 新增 `executor` 角色（唯一获准调用写工具的角色，需 Mandate）
3. Verifier 角色在验收场景下调用（仅限 paper 模式）

**建议**：方案 2——新增 `executor` 角色，工具集仅含 trade-exec 壳的 4 个工具，且 place_order/cancel_order 强制 requires_mandate=true。

### P1-3 信封 schema 的 mode/cost 字段未与 envelope_wrap 对齐

**现状**：`mcp_shells/_shared/envelope_wrap.py` 的信封 schema 为：
`{ok, data, source, timestamp, degraded, meta, version, trace_id, idempotency_key, error_code}`

本 SPEC §2.1 提出信封含 `mode`（paper/live）和 `cost`（latency_ms, slippage_bps）字段，声称"对齐既有 6 壳"，但实际这两个字段是**新增的**。

**缺口**：
- `mode` 和 `cost` 不在 envelope_wrap.wrap() 的参数中
- 若直接在 data 内承载则不算信封字段，SPEC 的"信封 schema"表述不成立
- 若要作为信封顶层字段，需升级 envelope_wrap（影响既有 6 壳，违反 H1 壳 diff=0）

**建议**：将 `mode` 和 `cost` 放入 `meta` 字段（信封已有 meta 槽位），不改 envelope_wrap 签名。这样既满足 H1 壳 diff=0，又能承载模式与成本信息。SPEC §2.1 应改为"meta 承载 mode/cost"。

### P1-4 paper 模式实现路径歧义

**现状**：22-执行引擎中心已有 `tee_core/adapters/paper_adapter.py`，基于 V15PaperClient 的状态转换（live→filled/canceled）。

本 SPEC §1.1 描述 paper 模式为"下单意图落盘 + K 线撮合模拟成交"。这与现有 paper_adapter 的实现路径**不同**：
- 现有 paper_adapter：模拟订单状态机，不依赖 K 线
- SPEC 描述：基于 K 线的撮合引擎

**缺口**：未明确是复用现有 paper_adapter 还是新建 K 线撮合模块。

**建议**：阶段二先复用现有 paper_adapter（快速验证管道），K 线撮合作为阶段二后期的增强项单独评估。SPEC 应明确这一分层。

### P1-5 13 域"孤岛，无生产引用"描述不准确

**现状**：本 SPEC §0.2 称 13-通用风控模块为"孤岛，无生产引用"。

**实证**：
- `42-神经网络交易协调层/param_governor.py` L15："13 系统门禁优先：任何参数不得放宽或绕过 13-通用风控模块门禁"
- `4-MEMORY/9-工具与接口/auto_update_trigger.py`：13 域在更新触发映射中
- 13 域自身有 tests/test_risk_engine.py（2 测试）

**影响**：若 13 域已有生产引用，"激活存量"的表述需要调整——不是从 0 到 1，而是从隐式引用到显式契约化。

**建议**：将"孤岛，无生产引用"改为"无显式 Port 契约引用，仅有文档级/常量级引用"。

---

## §3 P2 优化建议

### P2-1 执行权注册表形式未定义
本 SPEC §6 提到"执行权注册表 + 分标的灰度"，但未定义注册表的载体（文件？DB？配置中心？）和读写权限。建议参照 47 域 `registry/mcp_capabilities.yaml` 的模式，定义 `execution_authority.yaml`。

### P2-2 TEE 审计下沉方案不具体
§6 风险表提到"TEE 双轨模式随执行器下沉进 MCP，审计语义不变"，但未说明 TEE（Trusted Execution Environment？还是 22 域 tee_core？）的具体所指和下沉路径。建议明确术语并给出审计链迁移步骤。

### P2-3 定容步骤接口契约缺失
§1.5 规定定容是 RiskCheck 与 Order 之间的固定步骤，但未给出定容的输入输出契约（输入：信号+风控结果？输出：调整后 size？）。建议补充 `size_position(signal, check_result) -> adjusted_size` 的最小契约。

### P2-4 OOD 隔离的"默认不进"过于保守
§5 规定 paper 成交数据默认不进案例库/记忆升级。建议增加白名单机制：经过人工标注为"有教学价值"的 paper 成交（如极端行情下的风控拦截案例）可选择性入库，避免完全隔离导致案例库缺乏负样本。

---

## §4 实证核对清单

| SPEC 声称 | 实证核对 | 结论 |
|---|---|---|
| 13 域 19 py（engine/exit_engine/position_sizer/l1_assessor） | core/ 9 py + rules/ 3 py = 12，加 tests/memory 约 19 | ✅ 数量级准确 |
| 16 域 capital_allocator/capital_control | `16-调控系统/core/capital_allocator/` + `capital_control/` 存在 | ✅ 准确 |
| 22 域 tee_core adapters/algorithms/core/estimators | tee_core 下 4 子目录均存在，含 okx_adapter/paper_adapter | ✅ 准确 |
| 22 域 41 py | tee_core 约 20 py + tests 12 + scripts 3 ≈ 35，加 docs 接近 41 | ✅ 数量级准确 |
| 11 域 okx_client 唯一实盘出口 | data_server_fixed.py 有 OKXSimulatedClient；polling_trader 为实盘主路径 | ✅ 基本准确 |
| 48 域七关门禁 | 实际为三关（双度量+OOD+稳健性） | ❌ 错误（P0-2） |
| envelope 对齐既有 6 壳 | mode/cost 为新增字段，需放 meta | ⚠️ 部分偏差（P1-3） |

---

## §5 评审决议

### 必须修复（P0，阻断阶段一）
1. **P0-1**：解决"实盘链路永不暴露 MCP"冲突——选择路径 A（修订硬约束）或路径 B（MCP 仅 paper + 实盘旁路），由架构组决策
2. **P0-2**：修正"48 域七关门禁"为"三关门禁"

### 必须明确（P1，阶段一前完成）
3. P1-1：工具→port/domain 映射（建议 event port + trade-exec domain）
4. P1-2：调用方身份（建议新增 executor 角色）
5. P1-3：mode/cost 放入 meta，不改 envelope_wrap
6. P1-4：paper 模式先复用 paper_adapter，K 线撮合后置
7. P1-5：修正 13 域"孤岛"描述

### 建议优化（P2，不阻断）
8. P2-1 ~ P2-4

**通过条件**：P0 两项解决 + P1 七项明确后，本 SPEC 可进入阶段一（Port 契约冻结 + 信封 schema 定稿）。

---

## §6 附录：同步状态

- 文档来源：云端 `/home/luke/dreambuddy/47-MCP管理系统/docs/tech/SPEC-L0-TRADE-EXEC-MCP-v0.1.md`（2026-11-05 12:40 创建）
- 本地同步路径：`47-MCP管理系统/docs/tech/SPEC-L0-TRADE-EXEC-MCP-v0.1.md`
- 云端 git 状态：SPEC 文件未出现在 git status（可能已提交或被 ignore），待确认
- 本评审文档：`47-MCP管理系统/docs/tech/REVIEW-L0-TRADE-EXEC-MCP-v0.1.md`
