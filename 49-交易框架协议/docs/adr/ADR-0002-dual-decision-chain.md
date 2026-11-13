# ADR-0002: Dual Decision Chain and 50-NN Contradiction Evaluator

- 状态：accepted（2026-11-07 第二轮复审通过；R0 实施受 MVB 5/5 门禁约束）
- 日期：2026-11-07
- 决策人：49 交易框架协议 owner
- 复审记录：`docs/reviews/REVIEW-2026-11-07-dual-chain-rereview.md`
- 关联：SPEC-49 v0.14；FinalDecisionSignal v1；SignalSchema v1；MacroElasticConstraint v1；48/42/43/50

## Context

23 四层闭环自进化交易架构已稳定运行，并已形成完整的内部链路（SubSystemBridge → `_discover_paths` → 矛盾识别 → 路径选择）。若把 42 协调层的子系统信号直接并入 23，会改变其已验证链路，并让对照实验失去独立基线。

同时，42 已完成 P1-01～P1-07：8 源总线、TTL/去重、路径环境变量、11 子池状态文件、canonical source、参数分发、可观测性、`run_bus` 入口。上游 40→43 已能产出弹性约束（资产偏置/多空数量/仓位/杠杆方向），但尚未字段化落齐。

## Decision

1. **采用双决策链**：
   - **NN 闭环链**：39（L0 MCP）/ 9（纳入 48）+ 全链路交易数据 → **48（40 的唯一对接口）** → 40 → 43 弹性约束 → 42 8 源总线 → **50-NN主矛盾评估器** → 执行层 13（PreTradeGate 阻断式）/ 16（定容上限）/ 22（Gateway 执行）+ 11 执行器 → 结果回 48。OKX 订单 tag = `yijingsim`。
   - **23 自进化链**：保持独立、自行进化，作为对照实验。执行出口走 11-polling_trader 的 **raw 通道**（**不经** 13 拦截 / 16 定容 / 22 执行），OKX 订单 tag = `evo23`，reason 前缀 `[23域]`，持仓记录 `domain_tag="23域"`；13 仅以 `shadow_only` 模式对 23 域订单做**只读影子校验**（判定落 `22-执行引擎中心/audit/gateway.jsonl`，`shadow_only=true` / `executed=false`），不阻断成交。
2. **50 独立实现**：不 import 23 的运行时模块/状态；23 只提供**可参考/可复制的主矛盾架构设计**，不构成持续基因流或运行时依赖。
3. **基因注入方向为 NN → 23**：经原 42→23 shadow 端口，选择性注入 NN 验证过的优质基因（维度口径、置信度校准、证据融合能力）；必须 shadow、可回滚、不破坏 23 主链。
4. **48 升级为 40 的唯一对接口**：39 经 L0 MCP、9 纳入 48 统一口径；全链路交易数据统一进 48；训练建议制，遵守 40 P5/P6 门禁（DEC-29）。
5. **弹性约束四项**：资产偏置（数量）、相关资产多空数量偏置、仓位约束、杠杆约束；只作用于最终仓位/开仓许可，不进入矛盾评分。
6. **契约**：50 输出复用 FinalDecisionSignal 的字段结构，但 `source` 当前 schema 为 `{"const":"23-evolution"}`（非枚举）且 `additionalProperties:false`。落地需 **const→enum 结构变更**（`["23-evolution","50-nn"]`）并升级 manifest（contract-freeze-v2，重算 sha256）；这不是 additive，见 Contract Impact。
7. **执行权**：`execution_rights` 分区；50 初期 paper-only；23 保持 live 现状；同一标的同时刻单出口；live 灰度需评审。

> **对 DEC-02 的修订（M9 修复）**：本 ADR 在**对照期内**将 DEC-02“23 唯一最终决策出口”修订为“23 = 对照链 / 50 = NN 链出口”。对照期结束后由 DEC-43 的预注册数据裁决收敛方向；本修订不改变 13 风控优先与 execution_rights 单出口原则。

## Consequences

- 23 生产链路零改动，对照实验有效；NN 链可独立迭代、独立回滚。
- 运维与治理成本增加：双链并行、双套监控、双套训练数据；需 gene registry 与 A/B 评审。
- 50 需要独立实现 23 的主矛盾架构（可复制后适配），存在代码漂移风险；通过 gene registry + 一致性测试 + 定期评审控制。
- 与 DEC-02“23 唯一最终决策出口”冲突：本 ADR 定义**过渡期**双链架构，最终由 ≥4-8 周对照数据裁决收敛方向（DEC-43）。

## Contract Impact

- **变更形态（修正：非 additive）**：`final_decision_signal.v1.json` 的 `source` 为 `{"type":"string","const":"23-evolution"}`，且 `additionalProperties:false`。`source=50-nn` 的信号会被现有 schema **直接拒绝**。落地必须：
  1. `source` 由 `const` 改为 `enum: ["23-evolution","50-nn"]`（结构变更，非加法）；
  2. 升级 manifest：`contract-freeze-v2`（重算 FinalDecisionSignal 的 sha256 并更新 spec_version），v1 文件保留历史；
  3. 走 ADR + manifest 更新流程（DEC-03），禁改 v1 其余必填字段与语义。
- **落地文件策略（M8 修复，二选一已定）**：**新增** `contracts/final_decision_signal.v1.1.json`（`source` 为 enum），**v1 文件保持 frozen 不变**；manifest 同时登记 v1（历史/frozen）与 v1.1（生效/frozen）；`validate_contracts.py` / `freeze_contracts.py` 的 CONTRACTS 列表扩展 v1.1；`server.py` 过渡期同时接受 v1/v1.1，R5 后只接受 v1.1。禁止直接改 v1 文件（会破坏已发布 sha256 与消费方）。
- **受影响代码清单（R0 必须逐项适配，缺一不可）**：
  - `mcp_shells/l0_trade_exec/server.py`（`from_23_signal` 硬编码 `source="23-evolution"`，需新增 `from_50_signal` 适配器与 source 路由）；
  - 13 通用风控（消费 source 的审计字段）；
  - 22 执行引擎 / OrderPort（source 白名单）；
  - 47 `execution_rights.json`（新增 50 paper/live 分区）；
  - 49 `validate_contracts.py` / `freeze_contracts.py`（enum 化后重校验、重冻结）。
- 不改：SignalSchema v1 / MacroElasticConstraint v1 / UpperLayerContext v1。

## Alternatives

1. 直接改造 23 承接 42 信号：侵入已验证链路，对照实验失效，回滚成本高。
2. 50 直接 import 23 模块：运行时耦合，23 重构会传导，且共享全局状态/W6 存储，违背隔离目标。
3. 不建 50，仅保留 23：无法形成独立 NN 闭环，也无法对照验证。
4. **抽取 23 矛盾核心为无状态纯函数共享库（评估后否决）**：形式上消除了双份代码，但 (a) 共享库成为代码级单一事实源，23 侧任何演进会即时改变 50 行为，对照实验的变量独立性失效；(b) 23 的核心模块并非无状态（W6 样本/权重存储、DB 路径、模块级缓存如 `_LAST_ATTN_WEIGHTS`），抽纯函数需先重构 23，违背"零改动"边界；(c) 共享库的版本治理等于把 gene registry 变成硬依赖。**替代控制**：短期用 differential harness（固定快照逐字段 diff + 分歧率基线）约束漂移；若对照期结束收敛为单链，再重评共享库方案。

## Verification Design

- **Differential harness（R0 硬验收）**：固定 10-20 组历史快照，同输入跑 23 与 50，逐字段 diff（维度排序 / 主矛盾 / dominance 矩阵 / 置信度），产出**分歧率基线**。R2 的 A/B 只解释"相对基线的增量"，不解释绝对值——否则 W6 冷启动噪声会主导前 4-8 周结论。
- **对照隔离（M1 修复）**：23 control **冻结在固定 commit + 固定配置**，对照窗口内不注入任何基因；treatment 使用独立实例；NN→23 基因注入另开实验，**不与主对照混用**。A/B 只比较 frozen control vs 50。
- **对照预注册（R5 前锁定）**：3 项主指标（方向一致率 / 主矛盾维度一致率 / paper 风险调整收益差）+ 2 项安全指标（最大回撤 / 单标的双出口次数）；非劣效边界：**Sharpe 差值 95%CI 下界 > -0.2**；多重比较校正（Holm 或 BH，预注册族错误率）；先注册后运行；预注册最小成交笔数与最小周数（功效分析），block bootstrap 处理自相关。

## Rollback

- 50 全部开关默认关闭（`ENABLE_50_* = 0`）；置 0 即回 23 单链。
- 删除/停用 50 不影响 23、40、42、48。
- 执行侧回滚优先 `execution_rights=disabled` + 13 风控拦截。
- 验证：50 shadow 报告 + 49 rollback drill（扩展 50 开关后）。