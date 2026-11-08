# 同行评审报告 — 49 双决策链架构 v0.14.1

> 评审依据：`1-ARCHITECTURE/skills/dream-science-peer-review`（四视角 + Devil's Advocate 让步阈值 + 7 模式阻断清单）
> 评审对象：SPEC-49 v0.14.1、ADR-0002、50 SPEC v0.1.1、42/48 集成文档
> 评审维度：架构 / 数据流 / 实际代码实现可行性
> 日期：2026-11-07
> 性质：AI 评审报告；最终决策 human-in-the-loop

## 评审摘要

- 整体评价：**修改后接受（Major 9 / Minor 12）**
- 结论：架构方向成立（双链隔离、23 对照、48 统一接口），但**当前文档尚不足以支撑 R0 开工**；50 的核心算法输入形态、执行接线依赖、控制实验纯净性、契约落地方式存在结构性缺口。
- 已确认 v0.14.1 修复了上一轮评审的硬错误（开关名、const→enum、R0 重定义、R1 拆分、R4 门禁、A/B 预注册）；本轮聚焦**仍未闭合的开发可行性问题**。

---

## 一、Journal-Fit Reviewer（架构适配性）

**结论：修改后接受。**

1. 双链隔离符合用户“不破坏 23、保留对照”的核心约束；23 零改动边界（DEC-34）已精化。
2. **50 作为新增顶级域，未进入系统架构 SSoT**：`1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` 未更新；50 只在 49 SPEC 文件索引中出现。开发排期前需补 SSoT 与文档索引（Major）。
3. **48 扩域与其 §8 边界冲突**：48 SPEC 明写“本域不做生产链路变更”；R4 已加 v0.6 评审硬门禁，但 R0/R1 的数据 schema 工作仍可能触碰 48，需在 R0 任务中明确“只读/不改 48 生产行为”。
4. **47 治理未覆盖 50**：`execution_rights.json` 仅有 `eleven_domain` 与 BTC/ETH，无 50 paper/live 分区；R1c 0.5 周低估了 47 的双人审批/变更治理成本。
5. **DEC-02 与 DEC-31 的正式冲突未修正**：§12.5 DEC-02 仍写“23 唯一最终决策出口”，v0.14 仅在增补节声明覆盖；需在 DEC-02 行加“已被 DEC-31 在对照期修订”或升 DEC 版本，否则文档内部自相矛盾（Major）。

## 二、方法评审（架构与数据流）

**结论：修改后接受。**

### 2.1 50 的算法输入形态不成立（Major，最致命）

23 的矛盾识别 / DominanceResolver / W6 都以 **paths** 为输入：`path_id/source/direction/expected_return/resistance/confidence/continuation_score`。50 SPEC 的输入是 **evidence/signals**（42 总线），但 §4.3 写“D3 由路径共振传入”、§4.5 写“成对支配”，**没有定义 50 如何把 evidence 合成为 paths**：
- 谁生成 path_id/expected_return/resistance？
- D3 的“路径共振”来自哪些路径？
- 时间紧迫性（4 维之一）与市场影响权重如何从信号映射？
- DominanceResolver 对什么集合做两两比较？

**结论：按当前文档，50 的 core/contradiction、core/dominance、core/dimension_forces 无法直接实现。** 必须新增 `core/path_synthesis.py`（evidence → 候选 path/维度向量）并在 SPEC 定义字段映射与缺失降级。

### 2.2 控制实验被基因注入污染（Major）

DEC-34 允许 NN→23 基因注入（可选模块/开关），但 A/B 的“23 对照组”若被注入，行为已改变，不再是基线。文档未定义：
- 对照组是“冻结 SHA 的 23 实例”还是“双实例（control/treatment）”？
- 注入发生在对照窗口前还是窗口中？
- 如何证明 23 对照组在窗口内未变？

建议：**对照组冻结在固定 commit + 固定配置**；treatment 组单独实例；A/B 只比较 control vs 50，gene injection 另开实验，不与主对照混用。

### 2.3 R3 执行接线依赖未列入路线（Major）

R3 假设 `50 → 13→16→22 paper MCP`，但 v0.13 §12.6 已核验：13 已接线；**16/22 未 import，OrderPort 为自包含 OKXPaperLedger**；16/22 接入是 P3 的 R-L0-02，不在 R0-R5。R3 的 2 周验收不可达。需：
- R3 前置显式引用 R-L0-02，或
- R3 先用 13 + 自包含 ledger，16/22 后续替换（并在验收中声明）。

### 2.4 50 的执行权/安全契约缺失（Major）

50 直接向执行层出信号，但 SPEC 未定义：
- 执行权限模型（Mandate / EXECUTION_AUTHORITY / 50 的 source 白名单）；
- 47 registry 的 50 分区与双人审批；
- kill-switch / fail-closed / 日限额 / 审计字段；
- 同一标的同时刻“paper 与 live 是否算双出口”的判定。
这是安全红线，不能留到 R3 才发现。

### 2.5 42 数据可用性依赖 11 执行权拦截（Major，数据流）

代码取证：`polling_trader._write_subpool_state()` 只在 `_write_shadow_signal()` 内调用（`polling_trader.py:6785,6810`），而后者仅用于“**被执行权限拦截的开仓意图**”。若 11 对 washout/event-arbitrage 子池有 live 执行权，信号会被执行而不是写 shadow → 42 无状态文件 → 50 无输入。
- R0 “bus ≥6 源”在 11 live 执行权开启时可能不可达；
- 需在 R0 明确 11 子池的 signal-only/authority 配置，或接受 50 在某些标的上的输入缺失（fail-open）。

### 2.6 40 切换到 48 唯一接口缺少迁移任务（Major）

SPEC 要求 39/9 不直连 40、统一经 48；但 40 当前直接读取 39/9（v0.13 §2.2），且 40 的 P5/P6 门禁锁定。R4 只写了 48 网关，没有：
- 40 侧输入适配器/兼容层；
- 双读校验（48 vs 直读）与切换开关；
- 40 P5/P6 不受影响的验收。
缺此任务，R4 无法验证“唯一对接口”。

### 2.7 40/43 约束语义未定义（Major）

四项约束中：
- “相关资产”需要相关性矩阵/资产分组定义；40/43 均未提供；
- 资产偏置（数量）/多空数量偏置无字段；
- `leverage_cap` 在 43 `a3_strategy_adapter` 已计算但**未发布进 strategic_extension**；
- 16 `capital_allocator` 存在（`16-调控系统/core/capital_allocator/component.py:86`），但**无 long/short count cap**，R1b 是新建能力而非参数化。
需先定义数据模型与来源，否则 R1a/R1b 无法验收。

### 2.8 契约落地文件策略不明确（Major）

v0.14.1 已确认 const→enum + manifest v2，但未决定：
- 修改 `final_decision_signal.v1.json` 还是新增 `final_decision_signal.v1.1.json`；
- `validate_contracts.py` / `freeze_contracts.py` 硬编码 v1 文件名与 4 份契约列表，需同步改造；
- `contract_manifest` 的 `spec_version` 仍 v0.11，需升级。
ADR 受影响清单列出了代码，但没列“契约文件与校验脚本”的改造步骤与验收。

### 2.9 29-event / 23-contradiction 自环与输入依赖

已在 v0.14.1 标注 29-event 为自环/审计；但 50 的事件轨完整性仍依赖 23 的写行为。建议 R0 起 50 **完全不消费** 29-event/23-contradiction（连审计也从 48 侧读取），避免任何输入依赖对照方。

## 三、统计评审

**结论：修改后接受（条件）。**

1. **预注册已补**：3 主 + 2 安全指标、Sharpe 95%CI 下界 > -0.2、多重比较校正——方向正确。
2. **缺少功效分析/最小样本量**：4-8 周 paper 交易样本可能不足以让 Sharpe 差值 CI 收敛；需预注册最小成交笔数/最小周数，并用 block bootstrap（处理自相关）或 Deflated Sharpe。
3. **非劣效边界 -0.2 未论证**：为何是 -0.2？需给出业务可接受性依据；否则评审无法判断“差不多”是否可接受。
4. **多重比较方法未指定**：建议 Holm 或 BH（FDR），并预注册族错误率。
5. **W6 冷启动**已披露；但 A/B 的“相对分歧率基线增量”需要 R0-04 harness 的置信区间，不只是点估计。

## 四、Devil's Advocate（让步阈值协议）

| # | 反驳 | 评分 | 让步判定 |
|---|---|---|---|
| D1 | “50 可直接按 SPEC 实现” | **5** | 必须让步：evidence→path 合成层缺失（§2.1） |
| D2 | “23 对照组有效” | **5** | 必须让步：基因注入/冷启动污染（§2.2） |
| D3 | “R0 bus ≥6 源可达” | **4** | 必须修改：11 执行权拦截决定状态文件是否写入（§2.5） |
| D4 | “R3 两周完成执行接线” | **5** | 必须让步：16/22 未接线（§2.3） |
| D5 | “契约变更只是文档” | **5** | 必须让步：const→enum + 下游硬编码（已在 v0.14.1 部分修复，但文件策略未定，§2.8） |
| D6 | “48 R4 可排期” | **4** | 必须修改：40 迁移缺失 + 48 v0.6 评审（§2.6） |

> 评分 ≥4 的反驳，作者必须修改；无 3/4 边界争议。

## 五、代码实现评审（取证）

| 事实 | 证据 | 影响 |
|---|---|---|
| bus 运行态未达 8 源 | `42/runtime/bus_state.json`：2026-10-29、10 条、`sources=['bdsm']`；评审运行时 11-07 仅 `40-cycle` | R0 门槛必须硬 |
| 契约 source 为 const | `final_decision_signal.v1.json`：`{"const":"23-evolution"}`，`additionalProperties:false` | 50-nn 会被拒绝 |
| 下游硬编码 | `mcp_shells/l0_trade_exec/server.py:788` `"source":"23-evolution"`；无 from_50 | R0-02 必须改 |
| 开关名双形态 | `agi_config.py:95` `enable_cd_shadow`；`contradiction_identifier.py:55` `ENABLE_CD_SHADOW`；SPEC 原写 `ENABLE_C_D_SHADOW` | v0.14.1 已修 |
| 11 子池状态写入条件 | `polling_trader.py:6785/6810`：仅 `_write_shadow_signal`（执行权拦截）内写 | 42 输入依赖 11 执行权 |
| 16 定容模块 | `16-调控系统/core/capital_allocator/component.py:86` 存在；无 long/short count cap | R1b 为新建 |
| 47 执行权 schema | `execution_rights.json`：`eleven_domain` + BTC/ETH，无 50 分区 | R1c 需 schema/治理变更 |
| 43 约束字段 | `43/runtime/` 不存在；`leverage_cap` 未发布进 strategic_extension | R1a 前置不足 |
| 50 路径合成缺失 | 50 SPEC §1 core 无 path_synthesis；§4.3 D3“路径共振”无来源 | 50 核心不可实现 |
| 16/22 未接线 | v0.13 §12.6；server.py OrderPort 自包含 | R3 依赖 R-L0-02 |
| 48 边界 | 48 SPEC §8“本域不做生产链路变更” | R4 需硬门禁 |

## 六、7 模式阻断清单

| 模式 | 结果 | 说明 |
|---|---|---|
| 1. 幻觉引用 | ⚠️ 部分不通过 | v0.14 曾把“P1 完成/8 源”当既成事实；v0.14.1 §6.2 已修正，但 §13.5 仍写 P1 全部完成，需加“code-complete ≠ runtime online” |
| 2. 数据造假 | ✅ 通过 | 数据均为真实快照，未编造 |
| 3. 方法捏造 | ⚠️ 部分不通过 | 算法借用 23；differential harness 已补规范但未实现 |
| 4. 框架锁定 | ❌ 不通过 | 仅评估双链；“23 + 薄适配器”方案未评估；共享库选项已补否决 |
| 5. 结果幻觉 | ✅ 通过 | 未宣称 A/B 结果 |
| 6. 逻辑跳跃 | ❌ 不通过 | 50 evidence→path、R3 16/22、40→48 迁移均存在跳跃 |
| 7. 边界忽略 | ⚠️ 部分不通过 | 23 零改动边界已精化；50/47/48 边界仍有缺口 |

## 七、Major 意见（必须修改）

| ID | 意见 | 建议 |
|---|---|---|
| M1 | 23 对照组被基因注入污染 | 冻结 control SHA+配置；treatment 独立；注入另开实验 |
| M2 | 50 缺 evidence→path 合成层 | 新增 `core/path_synthesis.py` + 字段映射/降级规范 |
| M3 | R3 依赖 16/22 未接线 | R3 显式前置 R-L0-02，或先用 13+自包含 ledger |
| M4 | 50 执行权/Mandate/kill-switch 缺失 | 补 50 execution_rights 分区、Mandate、fail-closed、审计 |
| M5 | 11 子池状态依赖执行权拦截 | R0 明确 11 signal-only 配置；否则接受输入缺失 |
| M6 | 40→48 唯一接口迁移缺失 | 新增 40 输入适配器/双读校验/切换开关/R4 验收 |
| M7 | 40/43 约束语义未定义 | 定义相关资产分组、数量字段、leverage 发布 |
| M8 | 契约文件策略未定 | 明确 v1 修改 vs v1.1 新文件；改 validate/freeze/loader |
| M9 | DEC-02 与 DEC-31 未正式修订 | 在 §12.5 标注 DEC-02 被对照期修订，或升 DEC 版本 |

## 八、Minor 意见（建议修改）

1. W6 样本 schema/阈值/冷启动策略未定义。
2. A/B 缺功效分析、最小成交样本、block bootstrap/Deflated Sharpe；多重比较方法未指定。
3. 50 自票上限在“50 不生成候选”的前提下不适用，需明确或删除。
4. `execution_rights` 的“单标的单出口”未区分 paper/live。
5. `run_bus` 的调度/部署/监控未写入 R0。
6. 48 数据 schema 的保留期/访问控制/敏感字段未定义。
7. R0 资源基线缺具体阈值（CPU/内存/磁盘/负载）。
8. `bdsm`/`11-bdsm` 别名在 50 去重前需归一化。
9. §13.5 “P1 全部完成”需标注 code-complete vs runtime online。
10. 1-ARCHITECTURE 架构 SSoT 未收录 50。
11. 50 的 fail-open/fail-closed、崩溃恢复、状态持久化未定义。
12. 50 的文档索引/47 注册表/45 评测接入未列任务。

## 九、综合决议与修改顺序

**决议：修改后接受。** 不建议在 M1-M9 闭合前启动 R0。

建议修改顺序：
1. **M2 + M1**：先定 50 的 path 合成与对照实验隔离——这两项决定 R0 是否有意义。
2. **M3 + M4 + M5**：执行接线与数据可用性——决定 R3/R0 门槛是否可达。
3. **M6 + M7**：40/48 迁移与约束语义——决定 R4/R1 可实施。
4. **M8 + M9**：契约文件策略与 DEC 修订——决定 R0-02 可落地。
5. Minor 批量修订（统计/W6/别名/文档）。

## 十、评审局限

- 本报告为 AI 评审，未运行生产 A/B；统计结论需真实样本验证。
- 未覆盖 48/40/43/16/47 的内部实现细节到函数级；R0-04 harness 需另做代码级盘点。
- 最终决策与资源排期由 human-in-the-loop 作出。

---

## 十一、修订响应（2026-11-07，SPEC v0.14.2 / 50 v0.2.0）

| 意见 | 状态 | 落点 |
|---|---|---|
| M1 对照污染 | ✅ 已修 | DEC-44；ADR Verification Design 对照隔离 |
| M2 evidence→path | ✅ 已修 | 50 SPEC §4.1a + `core/path_synthesis.py`；D3 源 `11-bcrm-tactical`；R0-07 |
| M3 R3 依赖 16/22 | ✅ 已修 | SPEC §7.1 R3 + §13.10 R3-01：显式依赖 R-L0-02，先用 13+自包含 ledger |
| M4 50 执行权 | ✅ 已修 | 50 SPEC §3.1；R0-08；47 分区 |
| M5 11 子池写入条件 | ✅ 已修 | SPEC §6.2；42 集成文档 §6；50 SPEC §2.1；R0-03 |
| M6 40→48 迁移 | ✅ 已修 | SPEC §7.1 R4 / R4-01；48 网关文档 §3.1（适配器+双读+开关） |
| M7 约束语义 | ✅ 已修 | 50 SPEC §4.10（asset_groups/count caps/leverage）；SPEC §6.2 |
| M8 契约文件策略 | ✅ 已修 | ADR Contract Impact：新增 v1.1 文件、v1 frozen、双登记；DEC-45；R0-02 |
| M9 DEC-02 修订 | ✅ 已修 | §12.5 DEC-02 行 + ADR Decision 注记 |
| Minor 1-12 | ✅ 大部分已修 | W6 schema/冷启动、统计效力、自票上限澄清、别名归一化、SSoT 收录（R0-09）、状态恢复等 |

> 复审建议：重点复核 M2（path 合成字段映射是否足以让 23 算法运行）与 M5（11 authority 配置能否在云端同时满足 42 供源与 11 执行）。

---

## 十二、第二轮复审结果（2026-11-07）

**结论：通过（有条件）。** M2/M5 主体闭合；3 项 Minor（M2-1 / M2-2 / M5-1）转入 R0-03/R0-07 验收，不阻塞 ADR-0002。ADR-0002 已转 `accepted`；R0 仍受 MVB 5/5 门禁约束。

详见 [REVIEW-2026-11-07-dual-chain-rereview.md](REVIEW-2026-11-07-dual-chain-rereview.md)。