# 终审报告 — 49 双决策链 v0.14.2 / 50 v0.2.0 / ADR-0002

> 评审依据：`1-ARCHITECTURE/skills/dream-science-peer-review`（四视角 + Devil's Advocate 让步阈值 + 7 模式阻断清单）
> 评审对象：`49-交易框架协议/SPEC.md`（v0.14.2）、`50-NN主矛盾评估器/SPEC.md`（v0.2.0）、`docs/adr/ADR-0002-dual-decision-chain.md`
> 代码基线：`940bf2275c`（2026-11-08 工作区）；静态核验，未运行生产实例
> 评审性质：AI 终审；最终决策 human-in-the-loop
> 约束：本轮开发仅限本地，不 push / 不部署 / 不改云端

## 评审摘要

- 整体评价：**通过（有条件）**
- P0 阻断：**0**
- P1：**3**（文档口径/验收口径，须在 R0-02 开工前修正）
- P2：**4**（表述一致性，可随 R0 提交一并修）
- 放行结论：**允许进入 R0 本地开发**；MVB-2（运行态 3 日总线）与 MVB-5（真实快照 diff）无法在本地闭环，先交付“本地可复现代理证据”，运行态证据留待云端门禁。
- ADR-0002 维持 `accepted`；本次终审不改变双链架构决策。

## 一、代码事实核验（本轮新增）

| 事实 | 证据 | 与文档一致性 |
|---|---|---|
| `FinalDecisionSignal v1` 的 `source` 为 `const:"23-evolution"` 且 `additionalProperties:false` | `contracts/final_decision_signal.v1.json:23`、`:7` | ✅ 与 §3.10 / ADR Contract Impact 一致 |
| manifest 仍为 `contract-freeze-v1` / `spec_version=v0.11`，仅登记 4 契约 | `contracts/contract_manifest.v1.json:2-3` | ✅ R0-02 待办 |
| `validate_contracts.py` 与 `freeze_contracts.py` 的契约清单均只有 v1 | `scripts/validate_contracts.py:17`、`scripts/freeze_contracts.py:22` | ✅ R0-02 待扩展 |
| `server.py` 仅硬编码 `source="23-evolution"`，无 `from_50_signal` | `mcp_shells/l0_trade_exec/server.py:788`（全库检索仅此 2 处出现该字面量） | ✅ R0-02 待新增 |
| 42 总线运行态仅 `40-cycle` 单源（`signal_count=1`） | `42-神经网络交易协调层/runtime/bus_state.json:6-8` | ✅ MVB-2 未达标属实 |
| `registry.yaml` 注册 8 源，无 `11-bcrm-tactical` | `42-神经网络交易协调层/registry.yaml:5-62` | ✅ R0-03/R0-07 待新增 |
| `_write_subpool_state()` 仅在 `_write_shadow_signal()` 内调用 | `11-易经推理系统/scripts/memory_l4/polling_trader.py:6810` | ✅ M5 结论成立 |
| 执行权默认 `evolution_only`，白名单实现存在 | `polling_trader.py:842-861`、`:6782-6783` | ✅ M5-1 可落地 |
| 47 `execution_rights.json` 无 50 分区 | `47-MCP管理系统/registry/execution_rights.json:10-24` | ✅ R0-08 待办 |

## 二、四视角评审

### 2.1 Journal-Fit Reviewer（架构适配）

- 双链隔离（50 不 import 23、23 零改动）与对照实验目标匹配；ADR Alternatives 已否决“抽取 23 核心为共享库”，理由成立（23 非无状态，含 W6/DB/模块级缓存）。
- 48 作为 40 唯一对接口，避免了 39/9 直连 40 的双写歧义；R4 硬门禁（48 SPEC v0.6 评审）合理。
- **保留意见**：50 的 D3 技术源依赖 R0 新建 `11-bcrm-tactical`，而 `_last_bcrm2_result` 是“最后一币”单值（`polling_trader.py:5825`），不是每币快照；文档已修正为“新增每币持久化”，方向正确，但验收必须落 per-symbol 文件。

### 2.2 方法评审（可执行性）

- evidence→path 合成层的字段（`path_id/source/direction/confidence/expected_return/resistance/continuation_score/metadata`）覆盖 23 `identify/dominance` 的实际消费点；`expected_return` 明确为排序分而非年化，口径无冲突。
- 同源去重键 `(source, symbol, dimension, horizon)` 与 Dominance 同 horizon 两两比较，避免了跨周期伪支配。
- 4 维裁决权重（0.40/0.15/0.25/0.20）、共振 0.6、主导 0.55 沿用 23 设计口径，独立实现，可解释。
- **缺口**：50 必须自建 `SOURCE_DIM_MAP/SOURCE_WEIGHT_MAP/SOURCE_TF_MAP`；若直接复用 23 映射，`11-*` 源全部退化为 C3/0.05/medium（M2-2 已列 R0-07 验收）。

### 2.3 统计评审

- A/B 预注册完整：3 主指标 + 2 安全指标；Sharpe 差值 95%CI 下界 > -0.2；Holm/BH 多重比较；block bootstrap；功效分析最小样本；W6 冷启动披露；差分基线先行。统计口径合格。
- 非劣效边界 `-0.2` 需在 R5 预注册文档给出业务可接受性依据（当前仅声明，未见推导），作为 R5 前置，不阻塞 R0。
- “方向一致率/主矛盾维度一致率”只解释相对分歧率基线的增量，避免把冷启动噪声误判为架构优劣，方法正确。

### 2.4 Devil's Advocate（让步阈值）

| # | 反驳 | 评分 | 让步判定 |
|---|---|---|---|
| D1 | “MVB-2 要求连续 3 日 bus ≥6 源且信号量>0，但本地无法产生真实市场信号；若按字面验收，R0 在本地永远不能完成” | **4** | **让步**：补“本地可复现代理验收”（fixture 9 源 + 3 轮调度 + TTL 过期 + authority 负向），运行态 3 日作为云端门禁。见 P1-2 |
| D2 | “50 §3 仍写复用 v1，而 v1 的 const 会拒绝 50-nn；开发按 v1 写必失败” | **4** | **让步**：R0-02 前统一改为 v1.1。见 P1-1 |
| D3 | “R0-02 声称适配 13/22 的 source 白名单，但 13/22 代码里没有该能力，属于新增而非适配，范围会失控” | **3** | 不推翻；要求明确归属与验收边界。见 P1-3 |
| D4 | “50 自票上限 49 说适用、50 说暂不适用，双份 SSoT 会漂移” | **2** | 不阻塞；统一措辞。P2-2 |
| D5 | “additive 残留说明契约变更形态在文档内仍有冲突，可能误导实现” | **3** | 不阻塞；随 R0-02 一并修。P2-1 |

> 两项评分 4 的反驳均要求修正文档口径后放行；无评分 5 的致命缺陷。

## 三、7 模式阻断清单

| 模式 | 结果 | 说明 |
|---|---|---|
| 1. 幻觉引用 | ⚠️ 部分通过 | “13/22 source 白名单”在代码中不存在（P1-3）；其余引用可复核 |
| 2. 数据造假 | ✅ 通过 | bus_state / registry / execution_rights 均为实读 |
| 3. 方法捏造 | ✅ 通过 | path 字段与 23 消费点可对应 |
| 4. 框架锁定 | ✅ 通过 | ADR Alternatives 已评估共享库/改造 23/不建 50 三种替代 |
| 5. 结果幻觉 | ✅ 通过 | 未宣称 A/B 或运行态成果 |
| 6. 逻辑跳跃 | ⚠️ 部分通过 | MVB-2 的运行态门禁与“本地开发”缺少代理口径（P1-2） |
| 7. 边界忽略 | ✅ 通过 | paper-only、kill-switch、execution_rights 单出口、23 零改动边界均已声明 |

## 四、问题清单

### P0（阻断）

无。

### P1（R0-02 开工前必须修）

| ID | 问题 | 落点 | 修法 |
|---|---|---|---|
| **P1-1** | 契约版本口径冲突：50 输出契约仍写“复用 v1”，而 v1 `source.const` 拒绝 `50-nn`；另有 `additive` 残留 | `50-NN主矛盾评估器/SPEC.md:112`、`:370`；`49-交易框架协议/SPEC.md:1602`、`:1670` | 统一改为“复用 FinalDecisionSignal **v1.1**（source enum 含 50-nn）；新增文件、非 additive、manifest 升 contract-freeze-v2” |
| **P1-2** | MVB-2 验收口径不闭合：源清单 8 vs “8+11-bcrm-tactical”；“连续 3 日信号量>0”依赖真实市场，本地不可复现 | `49…/SPEC.md:1632`、`:1654`；`50…/SPEC.md:79-95`、`:312`、`:352` | ①枚举 9 源；②新增“本地代理验收”：fixture 总线 ≥6 源、3 轮调度、TTL 过期、authority=all 负向；③运行态 3 日显式标注为云端/ops 门禁 |
| **P1-3** | R0-02 受影响代码清单把 13/22 的 source 白名单写成“适配”，但代码中不存在该能力（全库仅 `server.py:788` 出现 `23-evolution`） | `49…/SPEC.md:1631`；`docs/adr/ADR-0002…:Contract Impact` | 明确：13/22 的 source 校验为**新增**，归属 R0-02 仅做契约/路由，13/22 校验在 R3 前生效；R0-02 验收不含 13/22 行为变更 |

### P2（随 R0 提交一并修）

| ID | 问题 | 落点 |
|---|---|---|
| P2-1 | `additive` 残留与 §3.10/DEC-45 冲突 | `49…/SPEC.md:1670`、`:1602`；`50…/SPEC.md:370` |
| P2-2 | 自票上限：49 写“适用”，50 写“暂不适用” | `49…/SPEC.md:1538`；`50…/SPEC.md:211-214` |
| P2-3 | `full_freeze/FREEZE` 未定义来源字段与缺失降级 | `50…/SPEC.md:218` |
| P2-4 | §7 目录结构缺 `core/path_synthesis.py`（R0-07 必建） | `50…/SPEC.md:272-290` |

## 五、终审决议

1. **通过（有条件）**：架构、契约方向、统计设计、回滚边界均成立；无 P0。
2. **放行 R0 本地开发**，顺序：R0-01（50 骨架/基因 registry/隔离测试）→ R0-02（契约 v1.1 + manifest v2 + 路由）→ R0-07（path 合成）→ R0-03（本地 fixture 总线）→ R0-08（执行权骨架）→ R0-04（本地差分代理）。
3. **门禁不变**：MVB 5/5 未全绿不得进 R2；本轮 P1 修正与 R0 代码同一分支本地提交，不 push。
4. **本地-only 边界**：不触云端、不改 47 生产 registry、不启动 live；50 全程 shadow/paper。
5. **认知闭环**：终审结论与“本地-only”约束写入认知库（record + verify）。

## 六、评审局限

- 静态核验，未运行 50（尚未实现）、未执行 differential harness、未做 A/B。
- 23 运行时冻结 commit 未在本轮锁定，DEC-44 的 control 冻结需在 R5 前落实。
- 本文为 AI 终审，不替代 human-in-the-loop 的架构与资源决策。

## 七、修复回填记录（2026-11-08）

| ID | 状态 | 回填内容 |
|---|---|---|
| P1-1 | ✅ 已修 | 49 §3.3/§11.6/附摘要、50 §3/§11 统一为 **v1.1（非 additive）** |
| P1-2 | ✅ 已修 | MVB-2 枚举 9 源；R0-03/MVB-2 增加本地 fixture 代理验收，运行态 3 日标注云端/ops 门禁 |
| P1-3 | ✅ 已修 | R0-02 明确 13/22 source 校验为新增能力、R3 前生效、不计入 R0-02 验收 |
| P2-1 | ✅ 已修 | 清除 `additive` 残留 |
| P2-2 | ✅ 已修 | 自票上限统一为“预留”，当前不适用 |
| P2-3 | ✅ 已修 | 50 §4.10 补 `full_freeze` 来源与缺失降级 |
| P2-4 | ✅ 已修 | 50 §7 目录补 `path_synthesis.py` |

### R0 本地开发进度

| 任务 | 状态 | 证据 |
|---|---|---|
| R0-01 | ✅ | `50-NN主矛盾评估器/genes/registry.json`、`core/`、`adapters/`；隔离测试 `tests/test_r0_01_scaffold.py`（3 passed） |
| R0-02 | ✅ | `contracts/final_decision_signal.v1.1.json` + 样例；manifest `contract-freeze-v2`/`v0.14.2`；`validate_contracts` 5/5；`freeze --check` 5/5；v1 sha256 `6a208a4c…` 不变；`server.py from_50_signal` + `source=50` 路由；契约测试 5 passed，l0_trade_exec 14 passed |
| R0-03 | ◐ | `tools/fixture_bus.py`：9 源、3 轮调度、TTL 过期丢弃、空 bus/authority=all 负向；11 运行态在线待云端 |
| R0-04 | ◐ | `tools/differential_harness.py`：逐字段 diff + divergence_rate；23 冻结快照待补 |
| R0-06 | ✅ | `adapters/bus_reader.py`、`adapters/constraint_loader.py`、`core/shadow_decision.py`、`adapters/audit_logger.py`；真实 42/40 smoke 通过（40-cycle 约束→0 paths→neutral；43 缺失 fail-open） |
| R0-07 | ◐ | `core/path_synthesis.py` + `core/mappings.py`；50 测试 48 passed（公式、去重、TTL、降级、9 源映射、外部权重和=1）；11 每币 BCRM2 持久化待做 |
| R0-08 | ✅ | 47 registry 新增 `fifty_nn_domain` + `adapters/execution_writer.py`；kill-switch / Mandate / paper 默认生效 |
| R0-09 | ✅ | SSoT 升 v4.2（§13.1 双决策链进度行 + §16.1 交易契约域 SSoT 行 + §14 维护记录）；INDEX 升 v2.12（L2 新增 49/50 两节 + 主题索引「双决策链」+ 覆盖率 35 模块/69%）；link_checker 588 链接 / 2 断链均为 archive 存量 |
| 基因复制 | ⏳ | registry 初始版已建；具体基因复制与一致性测试随 R0-07（path/source 映射）落地 |

> 全部改动仅本地工作区，未 commit、未 push、未部署。

