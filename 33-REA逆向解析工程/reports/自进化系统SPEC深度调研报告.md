# 自进化系统 SPEC v0.2 深度调研报告 — 科研级交叉验证

> **版本**: v1.0 (2026-10-12)
> **方法**: dream-science-orchestrator 路由 → dream-science-peer-review (Devil's Advocate) + dream-science-hypothesis-verification
> **目标**: 对 SPEC v0.2 做 4 维交叉验证，确保改进项无遗漏、无副作用、无硬约束冲突
> **输入文档**: SPEC v0.2 + 反思报告 + TECHNICAL_DESIGN.md + ENGINEERING_INDEX.md + API_SPEC.md + SPEC-金融逆向推导子系统.md + SPEC-矛盾论实现断裂修复与阻力场升级.md + README.md
> **原则**: 只读不改（调研阶段）

---

## 0. 执行摘要

对 SPEC v0.2 的 6 维度改进（A-F）+ P0-P3 路线图做了科研级 4 维交叉验证。**总体评价: SPEC v0.2 工程质量良好，但存在 3 个重大遗漏 + 5 个副作用未充分评估 + 2 个硬约束边界模糊**。建议升级为 v0.3。

### 5 维评分（dream-science-orchestrator 门控）

| 维度 | 评分 | 说明 |
|------|:---:|------|
| 完整性 | 6.5 | 遗漏"与矛盾论断裂修复SPEC的交互分析"重大依赖 |
| 可落地性 | 7.5 | 有TDD前置+验收标准，但API契约迁移方案缺失 |
| 工程适配性 | 7.0 | FAIL-OPEN适配好，但ring buffer自身FAIL-OPEN未设计 |
| 风险识别 | 6.0 | 拆分原子性风险/Jaccard误报/依赖注入连锁未充分识别 |
| 创新性 | 8.0 | P3架构自进化方向有新视角 |
| **综合** | **7.0** | 标注改进项，可生成开发任务（P1优先级） |

---

## 1. 维度一：改进项是否真能优化自进化

### 1.1 D (FAIL-OPEN 登记制) — 优化"感知"非"执行"

**Devil's Advocate 质疑**: 登记了 known_gap，然后呢？

- ✅ **可见性提升**: 565 处隐性豁口 → 显性 known_gap + verify SLA，自进化系统首次能"看到"自己的债务
- ⚠️ **缺少 gap→fix 自动管线**: SPEC 只设 30 天 SLA + verify，但未定义"逾期未 verify 触发什么"。D 级降级后呢？是否自动开 issue？是否阻塞新 feat？
- ⚠️ **缺少"偿还"动作定义**: known_gap 从 C→B→A 需要人工修复代码，但 SPEC 未定义"谁还、怎么还、还完如何标记"

**判定**: D 优化了自进化的**感知能力**（necessary），但缺少**执行能力**（sufficient）。SPEC 应增加"逾期处理"子方案。

### 1.2 F+P3 (REA 接入闭环 = 架构自进化) — 有愿景但未 grounded

**Devil's Advocate 质疑**: P3-1 "ReverseDeriver 扩展到架构证据" — 当前 ReverseDeriver 设计不支持架构域。

- ⚠️ **Scope 扩张**: SPEC-金融逆向推导子系统.md §10 明确 ReverseDeriver 是"从交易结果反推维度判断错"（交易域）。P3-1 要求扩展到"从架构证据反推设计债务"（架构域）——这是**新能力**，非现有设计的延伸。
- ⚠️ **缺少独立 SPEC**: P3-1 应有独立的"架构级 ReverseDeriver"SPEC，定义 derive_architecture_debt(evidence_list) 的输入/输出/FAIL-OPEN。

**判定**: F+P3 是**唯一直接优化自进化能力的方向**（方向正确），但当前 SPEC 的 P3 描述过于 aspirational。应标注"requires new SPEC"。

### 1.3 A/B/C/E (工程治理) — 不直接优化自进化但有副作用

**Hypothesis**: 拆分主入口→代码健康→间接支持自进化。

- ⚠️ **A 副作用 — 四层闭环原子性风险**: API_SPEC.md §12 定义 TightCouplingOrchestrator 7 步闭环(observe→hypothesize→experiment→measure→reflect→learn→feedback)。若 EvolutionPipeline 拆分为 Orchestrator+WeightStore+PathDiscovery+LoggingContext，7 步闭环可能失去状态一致性（如 reflect 步骤读 WeightStore，但 WeightStore 被 reflect 修改，跨组件状态共享）。
  - **缺失验收点**: SPEC 应增加"拆分后 7 步闭环状态一致性测试"
- ⚠️ **B 副作用 — 概念内聚破坏风险**: deep_reasoning_engine 的"签名+SDE+MonteCarlo"可能是统一的"路径积分计算"——签名(signature)是路径表征，SDE 是路径生成，MonteCarlo 是路径积分。三者形成计算流水线，拆分可能破坏计算内聚。
  - **反证**: 但 C-B2 证据显示有"GARCH fallback"——这更像 3 个独立算法的 fallback 链，非统一流水线。拆分有一定合理性。
- ✅ **E (债务阈值触发器)**: 直接有效——量化触发器是"减法演化"的起点

**判定**: 工程治理是健康的，但 SPEC 应增加 A 的"原子性保持"和 B 的"概念内聚性评估"验收点。

---

## 2. 维度二：遗漏架构问题

### 2.1 【重大遗漏】与矛盾论断裂修复 SPEC 的执行顺序冲突

SPEC v0.2 将 SPEC-矛盾论实现断裂修复作为**debt evidence**（D-E1："断裂修复出现在 SPEC 名"），但**未作为 dependency 分析**。

**矛盾论断裂修复 SPEC 的 5 个改造**:

| 改造 | 文件 | 与 SPEC v0.2 冲突点 |
|------|------|-------------------|
| 改造1 (P0) | resistance_vector.py | 无直接冲突 |
| 改造2 (P1) | evolution_pipeline.py `_select_optimal_path` L652-L813 | **与维度A拆分冲突**: 拆分后 `_select_optimal_path` 可能迁移到 PathDiscoveryService |
| 改造3 (P1) | resistance_vector.py `calculate()` | 无直接冲突，但矛盾调制改变 R_up/R_down 值 |
| 改造4 (P2) | evolution_pipeline.py L544-L555 | **与维度A拆分冲突**: FREEZE 逻辑在拆分目标文件内 |
| 改造5 (P3) | bellman_tracker.py | 无直接冲突 |

**执行顺序冲突**:
- 矛盾论 SPEC 要求: 改造1→改造3→改造2→(改造4‖改造5)
- SPEC v0.2 要求: P0-0 TDD→P0-3 触发器→P0-1 拆分→P0-4 登记制→P0-2 废单例
- **冲突**: 改造2/改造4 修改 evolution_pipeline.py，而 P0-1 要拆分该文件。若拆分先，改造2/4 的目标代码位置变化；若改造2/4 先，拆分需适配已修改的代码。

**建议**: SPEC v0.3 增加"与矛盾论断裂修复 SPEC 的执行顺序协调"章节，定义联合执行序列。

### 2.2 DataPipelineAdapter.cognitive_enabled 依赖

API_SPEC.md §7.1 显示 DataPipelineAdapter 有 `cognitive_enabled: bool = False`（Phase3 解冻）。

- SPEC v0.2 维度 D 的登记制依赖认知记忆系统（record known_gap）
- 若 `cognitive_enabled=False`，登记制无法写入
- **遗漏**: SPEC 未定义 cognitive_enabled=False 时的 fallback

**建议**: 增加冷路径 safe_call 的 fallback——认知记忆不可用时降级为本地 JSON 日志。

### 2.3 ReverseDeriver 集成增加 except pass

SPEC-金融逆向推导子系统.md §3.2 ReverseDeriver.derive() 有 `try/except → return neutral_result`。这是新的 except pass。

- SPEC v0.2 当前 except pass 统计: 565 处
- ReverseDeriver 集成后: +1 处（derive 方法）+ 可能的子方法 except pass
- **遗漏**: SPEC v0.2 的验收标准"全目录 except pass ≤ 500(P0)/≤ 150(P2)"未考虑 ReverseDeriver 集成的增量

### 2.4 测试基线数据不一致

- SPEC v0.2: "基线 816/958 passed"（审计报告）
- ENGINEERING_INDEX.md §6: "692 个测试用例"
- **差异原因**: 可能是不同时间点，但 SPEC 应使用最新数据

### 2.5 agi_config.py 开关交互未分析

README.md §快速开始 显示 agi_config.py 有三个总开关:
- ENABLE_EVOLUTION_PIPELINE
- ENABLE_CONTRADICTION_DRIVEN
- ENABLE_SHADOW_VALIDATION

SPEC v0.2 未分析改进项与这些开关的交互:
- 若 ENABLE_CONTRADICTION_DRIVEN=False，拆分 EvolutionPipeline 时矛盾驱动路径是否受影响？
- 若 ENABLE_SHADOW_VALIDATION=False，FAIL-OPEN 登记制的影子验证豁口是否仍登记？

---

## 3. 维度三：修复方案副作用

### 3.1 拆分 EvolutionPipeline 破坏 API 契约

**API_SPEC.md §13 定义公开契约**:
```python
EvolutionPipeline(gene_root: Path | str | None = None)
def run_symbol(symbol, market_data, rv=None) -> dict
```

拆分后:
- `EvolutionOrchestrator` + `WeightStore` + `PipelineLoggingContext` + `PathDiscoveryService`
- 公开 API 从 1 类变为 4 类，或需要 Facade 模式保持兼容

**副作用**:
- 所有 `EvolutionPipeline` 调用方需更新
- SPEC v0.2 只提到 trade_settlement_bridge L197，但**可能有其他调用方**（test_evolution_pipeline.py、scripts/、adapters/）

**建议**: SPEC 应增加"API 契约迁移方案"——Facade 模式保持 `EvolutionPipeline.run_symbol()` 向后兼容，内部委托给拆分组件。

### 3.2 热路径 ring buffer 数据丢失风险

SPEC v0.2 维度 D 修复方案 4: "KnownGapRingBuffer 达到阈值或定时 flush"

- **风险**: 进程 crash 时未 flush 的 gap 记录丢失
- **影响**: 热路径豁口约 111 处，若 ring buffer 容量 50，crash 时最多丢失 50 条
- **遗漏**: SPEC 未设计 ring buffer 的持久化

**建议**: ring buffer 使用 mmap 或 WAL（write-ahead log），crash 恢复时可重放。

### 3.3 Jaccard 相似度 false positive

SPEC v0.2 维度 C 修复方案 3: "Jaccard 相似度 > 0.7 告警"

- **风险**: 两引擎 import 相同基础模块（numpy/logging/dataclasses）会高 Jaccard，即使功能完全不同
- **示例**: `trend_following_engine.py` 和 `grid_trading_engine.py` 都 import numpy+logging+dataclasses，Jaccard 可能 > 0.7，但功能完全不同（趋势跟踪 vs 网格交易）
- **遗漏**: 纯结构 Jaccard 不区分基础库和领域模块

**建议**: Jaccard 计算时排除标准库和基础第三方库（numpy/pandas/logging），只计算领域模块的 import 集+call 集。或加权 Jaccard（领域模块权重高）。

### 3.4 废单例的依赖注入连锁

SPEC v0.2 维度 A P1: "trade_settlement_bridge.py L197 改为构造函数接收 IEvolutionPipeline"

**依赖注入连锁**:
1. `TradeSettlementBridge.__init__` 增加 `pipeline: IEvolutionPipeline` 参数
2. API_SPEC.md §1.1: `KlineEventHandler(settlement_bridge: Any)` — KlineEventHandler 构造函数接收 settlement_bridge
3. KlineEventHandler 的构造方（DataPipelineAdapter 或上层编排器）需传入修改后的 TradeSettlementBridge
4. 连锁波及 adapters/ 层

**遗漏**: SPEC 只分析了 1 处外部位（trade_settlement_bridge L197），但未分析构造链的 ripple change。

**建议**: SPEC 应增加"依赖注入迁移路径"——定义从单例到构造注入的迁移步骤，标注所有受影响构造函数。

---

## 4. 维度四：硬约束冲突

### 4.1 策略知识不进 CS 公式 — 边界模糊

**硬约束**: CS = 0.4·cos(d*) + 0.3·cos(ESS) + 0.3·sign_match(CBR)

- ✅ SPEC v0.2 不直接触 CS 公式
- ⚠️ **间接影响**: SPEC-金融逆向推导 §3.3 `apply_reward_with_derive` 增加 `factor_adjustments`。若 factor_adjustments 改变因子权重 → 影响未来 ESS 计算 → ESS 是 CS 公式的 cos(ESS) 项 → 策略知识**间接进入 CS**
- **判定**: SPEC v0.2 应标注"ReverseDeriver 的 factor_adjustments 只影响 future trades 的因子权重，不影响 current CS 计算"

### 4.2 不改变 BCRM2/力向量决策条件 — 改造3 边界

**硬约束**: 不改变 BCRM2/力向量决策条件

- ✅ SPEC v0.2 不触 BCRM2
- ⚠️ **矛盾论断裂修复改造3**: `resistance_vector.py calculate()` 增加 `primary_contradiction` 参数，调制 R_up/R_down。这改变了"力向量值"（R_up/R_down 是阻力向量的输出）
- **区分**: "决策条件"（阈值 PROBE_THRESHOLD=0.40 等）不变，但"力向量值"被调制
- **判定**: 改造3 不是 SPEC v0.2 的改进项，但 SPEC v0.2 应增加"与改造3 的交互评估"——确认调制只改值不改阈值

### 4.3 FAIL-OPEN 铁律 — ring buffer 自身需 FAIL-OPEN

**硬约束**: 基因准入全链路异常不阻塞交易

- ✅ SPEC v0.2 维度 D 强化 FAIL-OPEN
- ⚠️ **ring buffer 自身**: KnownGapRingBuffer 溢出时怎么办？若 ring buffer 满，新 gap 是丢弃还是阻塞？
- **判定**: ring buffer 需 FAIL-OPEN 设计——溢出时丢弃最旧记录 + 日志告警，不阻塞热路径

### 4.4 影子模式红线 — ReverseDeriver 案例入库边界

**硬约束**: 影子验证区基因只记录不干预参数

- ✅ SPEC v0.2 不触影子模式
- ⚠️ **SPEC-金融逆向推导 §5.2**: "错误案例入库 CBR/KNN" — 若影子基因的错误案例进入 CBR 库，可能影响实盘 CBR 评分
- **判定**: SPEC v0.2 应标注"ReverseDeriver 错误案例入库时，shadow 来源案例需标记 `source=shadow`，实盘 CBR 检索时过滤 shadow 案例"

---

## 5. 新发现问题汇总（SPEC v0.3 修订建议）

### 5.1 重大遗漏（P0 级）

| # | 遗漏 | 影响 | 修订建议 |
|---|------|------|---------|
| O-1 | 与矛盾论断裂修复 SPEC 的执行顺序冲突 | 改造2/4 修改 evolution_pipeline.py，与 P0-1 拆分冲突 | 增加"联合执行序列"章节 |
| O-2 | cognitive_enabled=False 时登记制 fallback | 登记制无法写入认知记忆 | 增加本地 JSON fallback |
| O-3 | 拆分后 API 契约迁移方案缺失 | 所有调用方需更新 | 增加 Facade 模式兼容方案 |

### 5.2 副作用未评估（P1 级）

| # | 副作用 | 影响 | 修订建议 |
|---|--------|------|---------|
| S-1 | 四层闭环 7 步原子性风险 | 拆分后状态一致性 | 增加"7步闭环状态一致性测试"验收点 |
| S-2 | ring buffer crash 数据丢失 | gap 记录丢失 | 使用 mmap/WAL 持久化 |
| S-3 | Jaccard false positive | 误报引擎相似 | 排除基础库+加权 Jaccard |
| S-4 | 依赖注入连锁 | adapters 层 ripple | 增加迁移路径分析 |
| S-5 | ReverseDeriver 集成增加 except pass | 豁口数增量 | 验收标准考虑 +N 增量 |

### 5.3 硬约束边界模糊（P2 级）

| # | 约束 | 模糊点 | 修订建议 |
|---|------|--------|---------|
| H-B1 | CS 公式 | factor_adjustments 间接影响 ESS | 标注"只影响 future 不影响 current" |
| H-B2 | 力向量决策条件 | 改造3 调制 R 值 | 增加"与改造3 交互评估" |
| H-B3 | FAIL-OPEN 铁律 | ring buffer 溢出 | 增加 ring buffer FAIL-OPEN 设计 |
| H-B4 | 影子模式红线 | shadow 案例入 CBR | 标注"shadow 案例标记+过滤" |

---

## 6. SPEC v0.3 修订建议清单

### 新增章节

1. **§8 与矛盾论断裂修复 SPEC 的联合执行序列**
   - 定义 P0-1 拆分 vs 改造2/4 的顺序（建议: 改造2/4 先于拆分，或拆分时同步迁移改造2/4 代码）
   - 联合执行: 改造1→改造3→P0-0 TDD→改造2→改造4→P0-1 拆分→P0-4 登记制

2. **§9 API 契约迁移方案**
   - Facade 模式: `EvolutionPipeline` 保持为 Facade，内部委托给 Orchestrator/WeightStore/PathDiscovery/LoggingContext
   - 向后兼容: `run_symbol()` 签名不变，内部实现重构
   - 调用方影响清单: test_evolution_pipeline.py + scripts/ + adapters/

3. **§10 依赖注入迁移路径**
   - TradeSettlementBridge → KlineEventHandler → DataPipelineAdapter 的连锁迁移步骤
   - IEvolutionPipeline Protocol 定义

### 修订现有章节

4. **维度 A 增加验收点**: "拆分后 TightCouplingOrchestrator 7 步闭环状态一致性测试通过"
5. **维度 D 增加 fallback**: "cognitive_enabled=False 时，safe_call 降级为本地 JSON 日志（路径: logs/known_gaps_local.jsonl），待 Phase3 解冻后同步"
6. **维度 D 增加 ring buffer 设计**: "KnownGapRingBuffer 使用 mmap 持久化，crash 恢复重放；溢出时丢弃最旧记录 + 告警日志"
7. **维度 C Jaccard 修订**: "排除标准库+基础第三方库（numpy/pandas/logging/dataclasses），只计算领域模块；加权 Jaccard（领域模块权重 3x）"
8. **维度 D 验收标准修订**: "except pass 增量考虑 ReverseDeriver 集成（+N 处），目标值调整为 565+ReverseDeriver_count → ≤ 500 → ≤ 150"
9. **维度 F P3-1 标注**: "requires new SPEC for architecture-level ReverseDeriver — 当前 SPEC-金融逆向推导子系统.md 的 ReverseDeriver 是交易域，架构域需独立设计"
10. **硬约束清单增加**: H-7 "ring buffer 溢出时 FAIL-OPEN（丢弃最旧+告警，不阻塞）"
11. **测试基线更新**: "692 测试用例（ENGINEERING_INDEX v1.5），非 816/958"
12. **硬约束边界标注**: H-B1 "factor_adjustments 只影响 future trades 因子权重，不影响 current CS"；H-B4 "shadow 案例标记 source=shadow，实盘 CBR 检索过滤"

---

## 7. 调研结论

### SPEC v0.2 的核心判断成立

- ✅ **"自进化是单调加法演化"** — git log 零 refactor 证据确凿
- ✅ **"FAIL-OPEN 被异化为债务累积"** — 565 处豁口 + "补漏12项"证据确凿
- ✅ **"D 和 F+P3 是唯一直接优化自进化能力的方向"** — 但 F+P3 需独立 SPEC
- ✅ **"工程治理(A/B/C/E)不直接优化自进化但改善代码健康"** — 成立，但有副作用

### 需要补充的 3 个重大维度

1. **与矛盾论断裂修复 SPEC 的交互** — 当前完全遗漏
2. **API 契约 + 依赖注入迁移方案** — 拆分的基础设施保障
3. **ring buffer 自身的 FAIL-OPEN 设计** — 登记制的递归 FAIL-OPEN

### 最终判定

SPEC v0.2 **无根本性错误**，但有 **3 个重大遗漏 + 5 个副作用 + 4 个硬约束边界** 需补充。建议升级为 v0.3 后再进入实施。

5 维评分 7.0/10 — 达到 dream-science-orchestrator 的开发任务生成门槛（≥ 7.0），但需先补充修订建议 1-12。

---

## 附录: 调研方法说明

### 调研路径

```
recall(硬约束) → 读取6份技术文档 → dream-science-orchestrator路由
  → dream-science-peer-review (Devil's Advocate 4维)
  → dream-science-hypothesis-verification (改进项假设验证)
  → 交叉验证 → 新发现问题 → SPEC v0.3修订建议
```

### 证据基础

- 技术文档: TECHNICAL_DESIGN.md + ENGINEERING_INDEX.md + API_SPEC.md + SPEC-金融逆向推导子系统.md + SPEC-矛盾论实现断裂修复与阻力场升级.md + README.md
- 代码: evolution_pipeline.py(1777行) + deep_reasoning_engine.py(518行) + kline_event_handler.py(1288行) + reflection_engine.py
- 日志: evolution_pipeline.log + audit_reports/
- REA JSON: self_evolution_rea_report.json (8 Evidence / 11 known_gaps)
