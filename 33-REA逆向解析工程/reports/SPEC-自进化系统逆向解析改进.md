# SPEC — 自进化系统逆向解析改进

> **版本**: v0.3 (2026-10-12, 修订基于深度调研报告12条修订建议)
> **状态**: 草案（深度调研修订版）
> **修订记录**:
> - v0.2: 应用了评审1-7的调研结论与设计修改——单例危害修正、TDD前置、阈值三阶标定、DSH契约验证、safe_call分层、准入自动化、证据补全
> - v0.3: 应用了深度调研报告12条修订建议——新增§8联合执行序列/§9 API契约迁移/§10依赖注入迁移；维度A增加7步闭环一致性验收点；维度D增加ring buffer mmap持久化+cognitive_enabled fallback+ReverseDeriver增量；维度C Jaccard排除基础库+加权；维度F P3-1标注requires new SPEC；硬约束增加H-7+H-B1/H-B4边界标注；测试基线更新为692
> **来源**: [自进化系统逆向解析反思报告](自进化系统逆向解析反思报告.md) 六维度深化 + [深度调研报告](自进化系统SPEC深度调研报告.md) 12条修订建议
> **原则**: Evidence-First — 每条改进引用三源证据（技术文档 / 代码实现 / 运行日志）

---

## 0. 文档定位

本文档是 **33-REA逆向解析工程** 对 **23-四层闭环自进化交易架构** 做四阶段逆向解析（Locate→Trace→Reduce→Annotate + 依赖图 + git 溯源）后，基于 6 维度反思问题，结合**技术文档+代码实现+运行日志**三重证据深化形成的改进 SPEC。

**核心命题**: 自进化系统的"进化"目前是单调加法演化——功能持续膨胀（engines 40 文件/8130 行）、主入口过载（1777 行/65 处 except pass）、FAIL-OPEN 豁口累积（全目录 565 处），但缺少周期性"减法"重构与债务偿还机制。本 SPEC 提出量化触发器+结构性拆分+债务登记制三条主线修复。

**与反思报告的关系**: 反思报告（[自进化系统逆向解析反思报告.md](自进化系统逆向解析反思报告.md)）是 Evidence 层；本 SPEC 是 Action 层——每条改进可追溯到反思证据编号（A-F）+ 三源证据。

---

## 1. 证据基础（三源汇总）

### 1.1 技术文档证据（设计意图）

| 编号 | 来源 | 章节 | 证据 | 对应维度 |
|---|---|---|---|---|
| D-A1 | ENGINEERING_INDEX.md | L13-L17 | EvolutionPipeline + KlineEventHandler 标为系统主入口，列出上下游依赖 | A |
| D-A2 | ENGINEERING_INDEX.md | L101-L123 | 引擎层职责清单定义 KlineEventHandler/DeepReasoningEngine/ReflectionEngine 边界 | B |
| D-A3 | API_SPEC.md | L466-L493 | EvolutionPipeline 构造函数+run_symbol 返回结构=对外契约 | A |
| D-D1 | SPEC-金融逆向推导子系统.md | L166-L200 | ReverseDeriver FAIL-OPEN 行为+中性结果结构+触发条件 | D/F |
| D-E1 | SPEC-矛盾论实现断裂修复与阻力场升级.md | 全文 | "断裂修复"出现在 SPEC 名=实现与设计已断裂到需专门修复 | E |

### 1.2 代码实现证据（耦合热点）

| 编号 | 来源 | 行号 | 证据 | 对应维度 |
|---|---|---|---|---|
| C-A1 | evolution_pipeline.py | L80, L104 | `_instance: EvolutionPipeline | None = None` + `EvolutionPipeline._instance = self` 单例注册 | A |
| C-A2 | trade_settlement_bridge.py | L197 | `pipe = EvolutionPipeline._instance` 外部组件直接抓取单例（全目录唯一外部位） | A |
| C-A3 | evolution_pipeline.py | L37-L66 | `_setup_logging` `except Exception: pass` 明确标注 FAIL-OPEN | A/D |
| C-A4 | evolution_pipeline.py | L85-L120 | `__init__` 初始化 L3/L4/权重/ShadowRL/RegimeGate 等多模块+except pass | A |
| C-A5 | evolution_pipeline.py | L152-L177 | `_agi_enhance`/`_get_deep_reasoning`/`_get_ftc_evolution_bridge` 统一访问点 | A |
| C-B1 | deep_reasoning_engine.py | L30-L68 | 导入 TimesFM/signatory/torch，失败降级 [FO-AGI-03] | B/D |
| C-B2 | deep_reasoning_engine.py | L76-L95 | 签名+路径积分+NeuralSDE+GARCH fallback+FAIL-OPEN 计数器 | B |
| C-B3 | kline_event_handler.py | L34-L39 | event_driven 导入失败置 None（延迟耦合） | B/D |
| C-D1 | reflection_engine.py | L271-L317 | `except Exception: pass` + `_maybe_auto_adjust_weight` 失败记录 [FO] | D |
| C-D2 | **except pass 统计** | 全目录 | evolution_pipeline.py **65 处**; kline_event_handler.py **38 处**; deep_reasoning_engine.py **17 处**; reflection_engine.py **6 处**; **全目录 565 处 across 100 文件** | D |
| C-E1 | engines/*.py | Glob | 40 个引擎文件（含子目录），总 8130 行 | C/E |
| C-E2 | git log | evolution_pipeline.py | 12 次提交：10 feat + 2 fix，**0 refactor** | E |
| C-E3 | git log | reflection_engine.py | 6 次提交：5 feat + 1 fix，含 "9ab2196967 feat: 方向3 补漏落地 — 按SPEC审计12项未落地全部实现" | D/E |

### 1.3 运行日志证据（FAIL-OPEN 异化运行时表现）

| 编号 | 来源 | 行号 | 证据 | 对应维度 |
|---|---|---|---|---|
| L-D1 | logs/evolution_pipeline.log | L2-L30 | `[FO-AGI-02] evaluate failed` + ATE 样本不足 warning 反复出现=FAIL-OPEN 降级路径实际触发 | D |
| L-D2 | evolution_pipeline.py | L151-L163 | `_agi_enhance` 异常 warning+fallback 运行时路径 | D |
| L-D3 | evolution_pipeline.py | L1101-L1143 | Granger 管道 `except Exception: pass` 注释 `FAIL-OPEN: Granger 失败则降级` | D |
| L-D4 | evolution_pipeline.py | L1257-L1272 | shift points 计算异常静默置 None（认知债务） | D |
| L-D5 | evolution_pipeline.py | L1283-L1317 | HJB+认知函数异常 debug 置 None（策略债务） | D |
| L-D6 | audit_reports/audit_20260912_0013.md | L11-L20 | 审计结论：8 小时无 FAIL-OPEN 铁律触发、无 crash | D |
| L-D7 | audit_reports/model_validation_20260915_0011.md | L131-L134 | FAIL-OPEN 全关 30/30 时 get_feedback() 仍返回 4 字段，记录 P2 开关恢复缺陷 | D |

---

## 2. 六维度问题逐条结构化

### 维度 A — 主入口过载（多职责扇出）+ 单例隐式耦合【严重度: 高 / 优先级: P0(拆分) + P1(废单例)】

> **v0.2 修订（评审1）**: 调研 Grep `_instance` 在 evolution_pipeline.py 全文，仅 2 处命中：L80 类变量定义 `_instance: EvolutionPipeline | None = None` + L104 注册 `EvolutionPipeline._instance = self`。**内部方法无 self._instance 访问**——全连接根因不是单例本身，而是内部多职责扇出（_agi_enhance/_get_deep_reasoning/_get_ftc_evolution_bridge 统一访问点 L152-177）。单例外部位仅 trade_settlement_bridge.py L197 一处。故：维度A的P0聚焦"多职责拆分"，单例废除降级为 P1（与维度B热点拆分同期落地）。

> **v0.3 修订（深度调研建议1/4/11）**: ①增加 §8 联合执行序列——P0-1 拆分与矛盾论断裂修复改造2/4 存在目标文件冲突，需定义联合顺序（见 §8）；②增加 §9 API 契约迁移方案——Facade 模式保持 `EvolutionPipeline.run_symbol()` 向后兼容（见 §9）；③增加 §10 依赖注入迁移路径——标注 TradeSettlementBridge→KlineEventHandler→DataPipelineAdapter 连锁（见 §10）；④增加验收点"拆分后 TightCouplingOrchestrator 7 步闭环状态一致性测试通过"（API_SPEC.md §12 定义 observe→hypothesize→experiment→measure→reflect→learn→feedback 7 步，拆分后跨组件状态共享需验证原子性）；⑤测试基线更新为 692（ENGINEERING_INDEX v1.5），非 816/958。

**问题**: EvolutionPipeline 1777 行，同时承担四层闭环编排+日志配置+单例持有+权重持久化+路径发现+AGI 增强(F/G/H/I)多职责。内部统一访问点（_agi_enhance/_get_deep_reasoning 等 L152-177）让任何外部组件通过 `EvolutionPipeline._instance` 反向触达 pipeline 全部方法。

**三源证据**:
- 文档: D-A1(主入口标定) + D-A3(对外契约)
- 代码: C-A1(单例定义 L80/L104) + C-A2(trade_settlement_bridge L197 唯一外部位) + C-A4(__init__ 多职责 L85-120) + C-A5(统一访问点 L152-177) + C-D2(65 处 except pass)
- 日志: 无直接单例竞态证据（单线程运行），但 65 处 except pass 是入口过载的债务映射
- **v0.2 补充**: Grep `_instance` 在 evolution_pipeline.py 仅 2 处（L80 定义 + L104 注册），无内部 self._instance 访问——全连接根因是内部扇出而非单例

**根因**: 调用图退化为"全连接"的根因有二，且**内部扇出是主因**：
1. **内部扇出（主因）**: `_agi_enhance`/`_get_deep_reasoning`/`_get_ftc_evolution_bridge` 等统一访问点（L152-177）将四层闭环编排+AGI增强+路径发现+权重持久化多职责压在一个类，任何方法调用都能横向触达其他职责的方法。
2. **单例（次因，1处）**: `_instance` 让外部组件（trade_settlement_bridge L197）绕过分层直接抓取 pipeline，但外部位仅 1 处，影响面有限。

单例选择的动机是"避免外部组件重复构造 pipeline"（便利性），替代方案"依赖注入+接口抽象"未被采用——这是**便利性压倒分层纪律**的权衡，但不是全连接的主因。

**DSH 契约验证（v0.2 评审4）**: Grep `EvolutionPipeline` 全目录 + 检查 DSH 节点注册表（`33-REA逆向解析工程/dsh_nodes.py` 注册 `S33_rea_*` 系列、`1-ARCHITECTURE/dreamos/registry/node_registry.py` 未注册 evolution）。**结论: EvolutionPipeline 未注册为 DSH 节点**，外部访问仅 trade_settlement_bridge L197 通过 `_instance`。故废除单例**不破坏 DSH 契约**，无需"DSH 契约迁移"子步骤。

**修复方案**:
1. **P0 — 拆分 EvolutionPipeline 为四个内聚组件**（主入口降载）：
   - `EvolutionOrchestrator` — 纯四层闭环编排（run_symbol 主流程）
   - `WeightStore` — 权重持久化（load/save/atomic_update）
   - `PipelineLoggingContext` — 日志配置（从 _setup_logging 抽出）
   - `PathDiscoveryService` — 路径发现（从 _get_* 抽出）
2. **P1 — 废除 `_instance` 单例类变量**，改用构造函数注入 + 接口抽象（`IEvolutionPipeline` Protocol）；trade_settlement_bridge.py L197 改为构造函数接收 `IEvolutionPipeline` 参数

**验收标准**:
- [ ] evolution_pipeline.py（或拆分后的 Orchestrator）行数 ≤ 800（P0）
- [ ] 四个拆分组件各有独立单元测试（P0）
- [ ] 全量回归测试通过（现有 test_evolution_pipeline.py + 引擎测试，**基线 692 passed**（ENGINEERING_INDEX v1.5），见审计报告 L-D6/§1.3）（P0）
- [ ] **拆分后 TightCouplingOrchestrator 7 步闭环状态一致性测试通过**（observe→hypothesize→experiment→measure→reflect→learn→feedback，验证跨组件状态共享原子性）**（v0.3 新增）**（P0）
- [ ] `_instance` 类变量删除，grep `_instance` 在 dreambuddy_evolution/ 返回 0 行（排除注释）（P1）
- [ ] trade_settlement_bridge.py 不再直接引用 `EvolutionPipeline._instance`（P1）

---

### 维度 B — 模块耦合热点：deep_reasoning_engine + kline_event_handler【严重度: 中高 / 优先级: P1】

**问题**: deep_reasoning_engine 518 行/出度 12/17 处 except pass——是"签名计算+SDE+蒙特卡洛+最小阻力路径"多算法缝合体。kline_event_handler 1288 行/出度 11/38 处 except pass——是"事件接收+路由+引擎调用+结果聚合"扇出枢纽。

**三源证据**:
- 文档: D-A2(职责清单定义边界)
- 代码: C-B1(TimesFM/signatory/torch 依赖 L30-68) + C-B2(签名+SDE+GARCH L76-95) + C-B3(event_driven 置 None L34-39) + C-D2(except pass 17+38 处)
- 日志: L-D1([FO-AGI-02] 触发) + L-D3(Granger 降级)

**根因**: deep_reasoning_engine 的"深度推理"概念边界过宽——签名、SDE、蒙特卡洛是三个独立算法领域，被一个"深度"概念打包。这是**概念缝合**而非内聚。kline_event_handler 把事件接收+路由+引擎调用+结果聚合压在一个文件。

**修复方案**:
1. deep_reasoning_engine 拆为三个内聚模块：
   - `SignatureComputer` — 签名计算（TimesFM/signatory）
   - `SDESolver` — NeuralSDE + GARCH fallback
   - `MonteCarloPathFinder` — 最小阻力路径积分
2. kline_event_handler 拆为：
   - `EventReceiver` — K 线事件接收+模式维护
   - `EngineRouter` — 引擎调度路由
   - `ResultAggregator` — 结果聚合+bridge 回调
3. 每个拆分模块的 except pass 收敛为统一 `safe_call(fn, fallback, gap_id)` 辅助函数，集中登记

**验收标准**:
- [ ] deep_reasoning_engine.py（或拆分后主文件）行数 ≤ 400
- [ ] kline_event_handler.py（或拆分后主文件）行数 ≤ 500
- [ ] 三个 SDE/Signature/MonteCarlo 模块各有独立测试
- [ ] except pass 数量在两个文件合计 ≤ 15（从 55 降至 15）
- [ ] REA dependency_graph 重跑：deep_reasoning_engine 出度 ≤ 6，kline_event_handler 出度 ≤ 6

---

### 维度 C — 引擎爆炸 + 胶水多于算法【严重度: 中 / 优先级: P2】

> **v0.2 修订（评审6/7）**: 
> - 评审6: "准入评审"与代码驱动偏好冲突，改为**自动化检查**——REA dependency_graph 跑时自动检测"新引擎与现有引擎的 Jaccard 相似度 > 0.7 则告警"，写入 CI 脚本而非人工评审。
> - 评审7: 补充审计证据——`model_validation_20260915_0011.md §3 F` 列出 DeepReasoningEngine 打包 NeuralSDE+TimesFM+签名+路径积分（佐证"概念缝合"）；`audit_20260912_0806.md` 列出 AGI F/G/H/I 模块实现度（佐证引擎边界模糊）。

> **v0.3 修订（深度调研建议7）**: Jaccard 相似度存在 false positive——两引擎 import 相同基础模块（numpy/logging/dataclasses）会高 Jaccard，即使功能完全不同（如 trend_following vs grid_trading）。修订为：①排除标准库+基础第三方库（numpy/pandas/logging/dataclasses），只计算领域模块的 import 集+call 集；②加权 Jaccard（领域模块权重 3x），降低基础库同质化干扰。

**问题**: engines/ 40 文件/8130 行，但 REA algorithm_reducer 只识别 3 种基础控制流模式（条件分支/迭代/累加器）——大量代码是胶水和编排，而非可还原的领域算法。short 系列 4 文件概念碎片化，factor 系列边界模糊。

**三源证据**:
- 文档: D-A2(引擎层职责清单)
- 代码: C-E1(40 文件 Glob) + REA E2(algorithm_reducer 仅 3 模式)
- 日志: **v0.2 补充** — `model_validation_20260915_0011.md §3 F` DeepReasoningEngine 打包 NeuralSDE+TimesFM+签名+路径积分（概念缝合佐证）；`audit_20260912_0806.md` AGI F/G/H/I 模块实现度表（引擎边界模糊佐证）

**根因**: 引擎数量爆炸的动机是"每个新需求开一个引擎文件"，缺少"合并同类项"的周期。这是**加法演化无减法**在模块层的体现。short 系列（three_factor_short/layered_short_exemption/direction_state_short_expansion/dynamic_short_blacklist）三个"short"文件边界模糊。

**修复方案**:
1. short 系列概念合并：评估三个 short 文件是否可合并为 `ShortStrategyCoordinator`（按策略模式区分），或明确边界文档
2. factor 系列评估：three_factor_long vs factor_pool_expansion vs factor_head_mask_fine_tuner 边界
3. **自动化引擎准入检查（评审6+v0.3修订）**——替代原"人工准入评审"：
   - REA dependency_graph 运行时自动计算"新引擎与现有引擎的 Jaccard 相似度"
   - **v0.3 修订**: Jaccard 计算排除标准库+基础第三方库（numpy/pandas/logging/dataclasses），只计算领域模块的 import 集+call 集；使用**加权 Jaccard**（领域模块权重 3x）降低基础库同质化干扰
   - 相似度 > 0.7 → CI 告警"建议并入现有引擎 X"（非阻塞，但写入 PR 检查报告）
   - 脚本路径: `33-REA逆向解析工程/scripts/engine_similarity_check.py`，接入 pre-commit 或 GitHub Action
4. REA algorithm_reducer 模式库扩展（见维度 F）

**验收标准**:
- [ ] short 系列合并或边界文档化（每个文件职责一句话可描述且不重叠）
- [ ] engine_similarity_check.py 脚本实现，接入 CI（**加权 Jaccard > 0.7 告警，排除基础库**）（v0.3 修订）
- [ ] engines/ 文件数 ≤ 35（从 40 降）
- [ ] REA algorithm_reducer 重跑：识别模式数 ≥ 6（新增梯度更新/相似性检索/贝叶斯/状态机）

---

### 维度 D — FAIL-OPEN 异化：设计精神 vs 实现偏离【严重度: 中 / 优先级: P0】

> **v0.2 修订（评审5/7）**: 
> - 评审5: kline_event_handler.on_kline_close 是热路径（每根K线收盘触发，含 L3 ShadowRL record + L4 Bellman td_update + AGI F/G/H/I 增强）。record_known_gap 若同步写认知记忆库（sqlite + MCP RPC）会引入延迟。修复方案增加"分层策略"：热路径豁口只登记到内存 ring buffer（异步 flush），冷路径才用 safe_call 同步写记忆。
> - 评审7: 删除"单例与 FAIL-OPEN 冲突"推测性论断（原根因③）——单例是便利性权衡，与 FAIL-OPEN"无副作用"理想无直接冲突，属推测非证据。

> **v0.3 修订（深度调研建议5/6/8）**: ①cognitive_enabled fallback——API_SPEC.md §7.1 DataPipelineAdapter 有 `cognitive_enabled: bool = False`（Phase3 解冻），当认知记忆不可用时 safe_call 降级为本地 JSON 日志（`logs/known_gaps_local.jsonl`），待 Phase3 解冻后同步；②ring buffer 持久化——KnownGapRingBuffer 使用 mmap 持久化，crash 恢复重放未 flush 记录；溢出时丢弃最旧记录+告警（FAIL-OPEN 递归设计）；③except pass 验收增量——ReverseDeriver 集成新增 except pass（derive() 方法 try/except→neutral_result），目标值调整为 565+ReverseDeriver_count → ≤ 500 → ≤ 150。

**问题**: FAIL-OPEN 设计精神是"异常不阻塞交易"（交易域正确铁律）。但实践中：①全目录 565 处 except pass 形成巨大豁口；②reflection_engine 有"补漏12项未落地全部实现"提交——FAIL-OPEN 被异化为"先记上以后补"的债务累积机制。

**三源证据**:
- 文档: README.md(FAIL-OPEN 铁律声明) + D-D1(ReverseDeriver FAIL-OPEN SPEC)
- 代码: C-A3(_setup_logging L37-66) + C-D1(reflection_engine L271-317) + C-D2(**565 处 except pass**) + C-E3(补漏12项提交 9ab2196967)
- 日志: L-D1([FO-AGI-02] 实际触发) + L-D3(Granger 降级) + L-D4(shift points 置 None) + L-D5(HJB 置 None) + L-D6(审计无 crash) + L-D7(全关验证)
- **v0.2 补充（评审3热冷分布）**: 热路径 except pass: evolution_pipeline 65 + kline_event_handler 37 + deep_reasoning_engine 9 ≈ 111 处；冷路径 ≈ 454 处。热路径豁口优先登记。

**根因**: FAIL-OPEN 是交易域正确选择，但缺少"债务登记+偿还"机制。现在有了认知记忆系统，FAIL-OPEN 的每处豁口应 record 为 known_gap，并设 verify 闭环+还款 SLA。当前 565 处豁口是"补漏"模式累积的结果——功能以 FAIL-OPEN 名义先留口子，后续补漏成为独立提交（如 9ab2196967）。

**修复方案**:
1. **FAIL-OPEN 豁口登记制（分层策略，评审5+v0.3修订）**:
   - **热路径豁口**（on_kline_close/run_symbol 等每K线触发的方法）: 只登记到进程内 `KnownGapRingBuffer`（内存 deque，异步 flush 到认知记忆库），**不阻塞交易**
   - **冷路径豁口**（_setup_logging/_get_*/初始化等一次性路径）: 用 `safe_call(fn, fallback, gap_id, sla_days=30)` 同步写认知记忆
   - **v0.3 fallback**: 当 `cognitive_enabled=False`（Phase3 未解冻）时，safe_call 降级为本地 JSON 日志（`logs/known_gaps_local.jsonl`），待 Phase3 解冻后批量同步到认知记忆库
   - 分层依据: Grep except pass 所在函数是否被 on_kline_close/run_symbol 调用链触达
2. **还款 SLA**: 每个登记的 known_gap 设 30 天 SLA——30 天内必须 verify(success=True) 升级或显式降级为 D 级
3. **统一 safe_call 辅助**: 提供 `safe_call(fn, fallback, gap_id, sla_days=30, hot_path=False, cognitive_enabled=True)` 辅助函数，hot_path=True 时只写 ring buffer，hot_path=False 时同步写认知记忆；cognitive_enabled=False 时降级写本地 JSON
4. **异步 flush + mmap 持久化（v0.3 修订）**: KnownGapRingBuffer 达到阈值（如 50 条）或定时（如每 6h）批量 flush 到认知记忆库，避免热路径延迟
   - **v0.3 mmap 持久化**: ring buffer 使用 mmap 持久化，进程 crash 后重启可重放未 flush 的 gap 记录
   - **v0.3 溢出处理**: ring buffer 满时丢弃最旧记录 + 日志告警（FAIL-OPEN 递归——ring buffer 自身异常不阻塞交易，见硬约束 H-7）

**验收标准**:
- [ ] 热路径 except pass 改用 `safe_call(hot_path=True)`，只写 ring buffer 不阻塞
- [ ] 冷路径 except pass 改用 `safe_call(hot_path=False)`，同步写认知记忆
- [ ] **cognitive_enabled=False 时 safe_call 降级为本地 JSON 日志**（`logs/known_gaps_local.jsonl`），待 Phase3 解冻后同步**（v0.3 新增）**
- [ ] 认知记忆系统中 known_gap 类记忆数：P0 ≥ 100（热路径豁口约 111 处优先登记），P2 ≥ 500（全量登记）
- [ ] 30 天后 known_gap verify 率：P0 ≥ 30%（热路径优先偿还），P2 ≥ 50%
- [ ] 新增豁口数 / 月 ≤ 5（控制增量）
- [ ] logs/evolution_pipeline.log 中 [FO-*] 标记的降级事件可追溯到 known_gap_id
- [ ] KnownGapRingBuffer flush 机制实现，热路径延迟增加 < 1ms（基准对比）
- [ ] **KnownGapRingBuffer 使用 mmap 持久化，crash 恢复重放验证通过**（v0.3 新增）
- [ ] **KnownGapRingBuffer 溢出时丢弃最旧记录+告警，不阻塞热路径**（v0.3 新增，H-7）
- [ ] **except pass 增量考虑 ReverseDeriver 集成**：目标值 565+ReverseDeriver_count → P0 ≤ 500 → P2 ≤ 150（v0.3 修订）

---

### 维度 E — 加法演化无重构【严重度: 高 / 优先级: P0】

> **v0.2 修订（评审7）**: 补充审计证据——`audit_20260912_0806.md §1.2` 列出 v1.8 修复 3 个"断裂点"（断裂1: HJB lagrangian 矛盾调制从未生效；断裂2: TrendContinuationScorer 从未接入 pipeline；断裂3: ContradictionFeedback 回流未闭环），印证"断裂修复"模式累积。

**问题**: git log 是纯粹加法演化——evolution_pipeline.py 12 次提交全 feat/fix 零 refactor；reflection_engine.py 6 次提交含"补漏12项"；SPEC 文档反复出现"断裂修复"（SPEC-矛盾论实现断裂修复与阻力场升级.md）。功能膨胀速率 > 重构速率，技术债务单调增长。

**三源证据**:
- 文档: D-E1("断裂修复"出现在 SPEC 名)
- 代码: C-E2(12 次提交零 refactor) + C-E3(6 次提交零 refactor) + C-D2(565 处豁口累积)
- 日志: **v0.2 补充** — `audit_20260912_0806.md §1.2` v1.8 修复 3 个断裂点（HJB lagrangian 从未生效/TrendContinuationScorer 从未接入/ContradictionFeedback 回流未闭环），印证"断裂修复"模式累积；测试基线 816 passed

**根因**: 团队偏好"加法优先"（user_profile 记录"延迟 commit 直到统一优化"），但"统一优化"的时机从未到来——因为没有触发条件。需要引入"债务阈值触发器"。

**修复方案**:
1. **债务阈值触发器**（量化强制 refactor 窗口）:
   - 文件行数 > 800 → 强制 refactor 提交窗口
   - 模块出度 > 10 → 强制拆分评估
   - FAIL-OPEN 豁口数（文件级）> 20 → 强制 safe_call 改造
   - 全目录豁口数 > 500 → 暂停新 feat，优先还债
2. **refactor 预算**: 每个 sprint 预留 20% 时间给 refactor（从加法预算中扣除）
3. **断裂修复 SPEC 审计**: 现有 SPEC-矛盾论实现断裂修复与阻力场升级.md 完成后归档，禁止新增"断裂修复"SPEC（断裂应在引入时修复，不应累积）

**验收标准**:
- [ ] 债务阈值触发器实现为 CI 检查脚本（pre-commit 或 GitHub Action）
- [ ] 触发器规则写入 CONTRIBUTING.md 或 ENGINEERING_INDEX.md
- [ ] evolution_pipeline.py 行数 ≤ 800（触发 refactor）
- [ ] 下一个 sprint 有 ≥ 1 次 refactor 提交
- [ ] 不再出现新的"断裂修复"SPEC 文件

---

### 维度 F — REA 工具自身反思：逆向工程的逆向【严重度: 中(工具层) / 优先级: P2】

**问题**: 用 REA 解析自进化系统的过程，暴露了 REA 自身局限：
1. evidence 去重 bug: investigate 的 _phase_annotate 聚合所有 phase 的 evidence 未去重（8 条显示为 16 条）
2. git_history 路径解析: trace_git_history 对中文嵌套路径静默返回空，违反 Provider 确定性原则
3. algorithm_reducer 模式库过基础: 只识别条件分支/迭代/累加器，无法识别交易领域算法

**三源证据**:
- 文档: 33-REA逆向解析工程/SPEC.md §2.1 Evidence-First 原则 + §2.3 Provider 确定性选择 + P1 声称"关键算法还原已完成"
- 代码: investigation_workflow.py _phase_annotate(L109-117 聚合但未去重) + git_history.py trace_git_history(对中文路径返回空) + algorithm_reducer.py(模式库仅 3 模式)
- 日志: REA 运行时 self_evolution_rea_report.json 显示 evidence 重复

**根因**: REA 借鉴 morluto/rea 的 Evidence-First，但落地时"evidence 去重"和"工具自身的 known_gaps 标注"两处没做到位。algorithm_reducer 的 SPEC P1 声称"关键算法还原已完成"但实际能力不足——这是 **REA 的自我证伪**。

**修复方案**:
1. 修复 _phase_annotate evidence 去重：按 evidence_id 去重（`seen_ids = set(); [ev for ev in all if ev.evidence_id not in seen_ids and not seen_ids.add(ev.evidence_id)]`）
2. git_history 路径失败时返回 `Evidence(level=unknown, known_gaps=["路径解析失败: 原因"])` 而非静默空
3. algorithm_reducer 模式库扩展，增加领域算法模式:
   - 梯度更新模式（`grad = loss.backward(); param -= lr * grad`）
   - 相似性检索模式（`cosine_sim(query, keys); top_k = argsort(...)[-k:]`）
   - 贝叶斯更新模式（`posterior ∝ likelihood × prior`）
   - 状态机模式（`state = transition(state, event)`）
4. **REA 自解析**: 把 REA 工具自身作为 target 跑一次 investigate，让工具反思工具

**验收标准**:
- [ ] _phase_annotate 输出 evidence 数 = 去重后数量（无重复 evidence_id）
- [ ] git_history 对不存在路径返回 Evidence(level=unknown) 而非空列表
- [ ] algorithm_reducer 模式库 ≥ 7 模式（3 基础 + 4 领域）
- [ ] REA 自解析报告产出（target=33-REA逆向解析工程/core/）
- [ ] 33-REA逆向解析工程/SPEC.md P1 声明与实际能力一致（更新或降级声明）

---

## 3. P0-P3 路线图

### P0 — 立即执行（债务止血+结构性拆分）

> **v0.2 修订（评审2）**: 在 P0-1 拆分前插入 P0-0 TDD 前置步骤——先跑现有测试建立基线覆盖率，补齐4组件接口契约的 RED 测试，再拆分。避免无测试保护下拆分 1777 行主入口的回归风险。

> **v0.3 修订（深度调研建议11）**: 测试基线更新为 **692 测试用例**（ENGINEERING_INDEX v1.5），非 816/958。816/958 数据来自审计报告（可能不同时间点），692 是 ENGINEERING_INDEX 最新统计。所有引用测试基线处统一使用 692。

| 序号 | 行动 | 对应维度 | 预期产出 | 验收 |
|---|---|---|---|---|
| **P0-0** | **TDD 前置**: 跑现有 test_evolution_pipeline.py 建立基线覆盖率（**基线 692 passed**，ENGINEERING_INDEX v1.5）；补齐 EvolutionOrchestrator/WeightStore/PipelineLoggingContext/PathDiscoveryService 四组件接口契约的 RED 测试（断言 ModuleNotFoundError 或接口签名） | A | 基线覆盖率报告 + 4 组件 RED 测试（红） | RED 测试存在且失败 |
| P0-1 | 拆分 EvolutionPipeline 为 Orchestrator+WeightStore+LoggingContext+PathDiscovery | A | 4 文件，主文件 ≤ 800 行 | RED 测试转绿 + 回归通过 |
| P0-2 | 废除 _instance 单例，改接口注入 | A | trade_settlement_bridge 构造注入 | 回归通过 |
| P0-3 | 债务阈值触发器实现（CI 脚本） | E | pre-commit/Action 检查 | 触发器生效 |
| P0-4 | FAIL-OPEN 豁口登记制 + safe_call 分层辅助（热路径 ring buffer mmap 持久化/冷路径同步/ cognitive_enabled fallback 本地 JSON）**（v0.3 增强）** | D | known_gap 记忆 ≥ 100（热路径优先） | 30 天 verify 率 ≥ 30% + mmap crash 恢复验证 |

### P1 — 下次改动时（热点拆分）

| 序号 | 行动 | 对应维度 | 预期产出 | 验收 |
|---|---|---|---|---|
| P1-1 | 拆分 deep_reasoning_engine 为 Signature+SDE+MonteCarlo | B | 3 文件，主文件 ≤ 400 行 | 出度 ≤ 6 |
| P1-2 | 拆分 kline_event_handler 为 Receiver+Router+Aggregator | B | 3 文件，主文件 ≤ 500 行 | 出度 ≤ 6 |
| P1-3 | except pass 收敛为 safe_call（两个热点文件） | B/D | except pass 合计 ≤ 15 | grep 验证 |

### P2 — 下一迭代（引擎治理+REA 自身修复）

| 序号 | 行动 | 对应维度 | 预期产出 | 验收 |
|---|---|---|---|---|
| P2-1 | short/factor 系列概念合并或边界文档化 | C | engines/ ≤ 35 文件 | 职责不重叠 |
| P2-2 | engine_similarity_check.py 自动化准入检查（Jaccard>0.7 告警） | C | CI 脚本接入 | 相似度告警生效 |
| P2-3 | REA evidence 去重修复 | F | investigate 输出无重复 | evidence_id 唯一 |
| P2-4 | REA git_history 路径失败返回 unknown | F | 不再静默空 | Provider 确定性 |
| P2-5 | REA algorithm_reducer 模式库扩展 | F | ≥ 7 模式 | 领域算法可识别 |
| P2-6 | REA 自解析报告 | F | target=core/ 报告 | 工具反思工具 |

### P3 — 长期（架构自进化）

| 序号 | 行动 | 对应维度 | 预期产出 | 验收 |
|---|---|---|---|---|
| P3-1 | ReverseDeriver 扩展到架构证据 **（v0.3: requires new SPEC — 当前 ReverseDeriver 是交易域，架构域需独立设计，见 §4）** | 元层 | 从架构 Evidence 反推设计债务 | 架构自进化闭环 |
| P3-2 | REA 接入自进化闭环（定期自动跑） | 元层 | cron 触发 REA→known_gap→verify | 闭环运行 |
| P3-3 | 架构健康度 reflection_engine | 元层 | 反思交易+反思架构双能力 | 健康度报告 |

---

## 4. 与 REA 方向3的衔接（架构自进化）

反思报告元层洞察：**自进化系统有 reflection_engine 反思交易决策，却无反思架构健康度能力**。REA 接入闭环后，ReverseDeriver 可扩展到"从架构证据反推设计债务"=架构自进化。

**衔接路径**:
1. **短期（P2）**: REA 修复自身局限（维度 F），成为可信的架构证据源
2. **中期（P3-1）**: ReverseDeriver 扩展 `derive_architecture_debt(evidence_list)` 方法——输入 REA 产出的架构 Evidence（文件行数/出度/豁口数/git 演化类型），输出"设计债务推断"（哪些维度债务增长/哪些 refactor 窗口已触发）
3. **长期（P3-2/3）**: REA 定期自动跑（cron 或 post-commit 触发），产出架构 Evidence → ReverseDeriver 推断债务 → 认知记忆 record → reflection_engine 架构健康度反思 → 触发 refactor 窗口

**与 SPEC-金融逆向推导子系统.md 的关系**: 该 SPEC 定义的 ReverseDeriver 当前从"交易结果"反推"矛盾维度判断错"（类比反向传播）。P3-1 扩展为从"架构证据"反推"设计债务"——同一组件，两个反推域（交易域+架构域），共享 Evidence 数据结构。

> **v0.3 标注（深度调研建议9）**: P3-1 **requires new SPEC for architecture-level ReverseDeriver**。当前 SPEC-金融逆向推导子系统.md §10 明确 ReverseDeriver 是交易域（"从交易结果反推维度判断错"）。P3-1 要求扩展到架构域（"从架构证据反推设计债务"）——这是**新能力**，非现有设计的延伸。需独立设计 `derive_architecture_debt(evidence_list)` 的输入/输出/FAIL-OPEN 行为，不能直接复用交易域 ReverseDeriver 的 `derive()` 接口。P3-1 的实施前置条件：产出独立的"架构级 ReverseDeriver"SPEC。

---

## 5. 硬约束清单（项目决策规则）

以下规则在用户确认后应 record 为 B 级硬约束记忆：

| 编号 | 规则 | 来源 | 触发关键词 |
|---|---|---|---|
| H-1 | 文件行数 > 800 必须触发 refactor 窗口 | 维度E修复方案 | "必须"(阈值) |
| H-2 | 模块出度 > 10 必须触发拆分评估 | 维度E修复方案 | "必须"(阈值) |
| H-3 | except Exception: pass 必须附带 known_gap 登记 | 维度D修复方案 | "必须" |
| H-4 | known_gap 设 30 天还款 SLA | 维度D修复方案 | "下限"(SLA) |
| H-5 | 新引擎创建必须通过自动化相似度检查（**加权 Jaccard > 0.7 告警，排除基础库**）（v0.3 修订） | 维度C修复方案(v0.2→v0.3) | "必须"(阈值) |
| H-6 | 禁止新增"断裂修复"SPEC（断裂应在引入时修复） | 维度E修复方案 | "禁止" |
| **H-7** | **ring buffer 溢出时 FAIL-OPEN（丢弃最旧记录+告警，不阻塞热路径）**（v0.3 新增） | 维度D修复方案4 | "必须"(FAIL-OPEN 递归) |

### v0.3 新增：硬约束边界标注（与 ReverseDeriver/矛盾论 SPEC 交互）

> 以下标注非新增硬约束，而是对现有硬约束与 ReverseDeriver/矛盾论断裂修复 SPEC 交互边界的明确化，防止跨 SPEC 改进时误触红线。

| 编号 | 边界标注 | 涉及硬约束 | 说明 |
|---|---|---|---|
| **H-B1** | **factor_adjustments 只影响 future trades 的因子权重，不影响 current CS 计算**（v0.3 新增） | CS 公式（README 硬约束） | ReverseDeriver 的 `apply_reward_with_derive` 增加 `factor_adjustments`，若改变因子权重 → 影响未来 ESS 计算。但 CS 公式的 `cos(ESS)` 项使用 current trade 的 ESS，不受 future factor_adjustments 影响。**标注：策略知识不间接进入 current CS。** |
| **H-B2** | 改造3 调制 R 值不改阈值（力向量值变但决策条件不变）（v0.3 新增） | BCRM2/力向量决策条件 | 矛盾论断裂修复改造3 在 `resistance_vector.py calculate()` 增加 `primary_contradiction` 参数调制 R_up/R_down。**区分**："决策条件"（PROBE_THRESHOLD=0.40 等阈值）不变，"力向量值"被调制。**标注：不是 SPEC v0.3 的改进项，但需确认调制只改值不改阈值。** |
| **H-B3** | ring buffer 自身需 FAIL-OPEN 设计（=H-7）（v0.3 新增） | FAIL-OPEN 铁律 | KnownGapRingBuffer 溢出时丢弃最旧+告警，不阻塞热路径。**标注：登记制的递归 FAIL-OPEN。** |
| **H-B4** | **shadow 案例标记 source=shadow，实盘 CBR 检索过滤**（v0.3 新增） | 影子模式红线 | ReverseDeriver 错误案例入库 CBR/KNN 时，shadow 来源案例需标记 `source=shadow`，实盘 CBR 检索时过滤 shadow 案例。**标注：影子验证区基因只记录不干预参数，shadow 案例不污染实盘 CBR 评分。** |

---

## 6. 验收标准矩阵（汇总）

> **v0.2 修订（评审3）**: 阈值改为三阶"当前值→P0 目标→P2 目标"，基于实际数据标定。当前值来自 Grep/审计报告/认知 stats 调研。
> **v0.3 修订**: 测试基线统一为 692；except pass 增量考虑 ReverseDeriver 集成；新增 7 步闭环一致性/ring buffer mmap/cognitive_enabled fallback 验收点。

| 维度 | 优先级 | 核心验收点 | 当前值 | P0 目标 | P2 目标 |
|---|---|---|---|---|---|
| A | P0 | 主入口行数 | 1777 | ≤ 800 | ≤ 600 |
| A | P1 | _instance 引用数 | 2(1 外部位) | 2(P1 未处理) | 0 |
| A | P0 | 拆分组件独立测试 | 0 | 4 组件 RED→GREEN | 覆盖率 ≥ 70% |
| A | P0 | **7 步闭环状态一致性测试**（v0.3 新增） | 无 | 测试通过 | 测试通过 |
| A | P0 | 全量回归测试基线 | **692**（v0.3 更新） | 692 passed | 692 passed |
| B | P1 | deep_reasoning 出度 | 12 | 12(P1 未处理) | ≤ 6 |
| B | P1 | kline_event_handler 出度 | 11 | 11(P1 未处理) | ≤ 6 |
| B | P1 | 两热点 except pass 合计 | 46(37+9) | 46(P1 未处理) | ≤ 15 |
| C | P2 | engines/ 文件数 | 40 | 40 | ≤ 35 |
| C | P2 | algorithm_reducer 模式数 | 3 | 3 | ≥ 7 |
| C | P2 | 引擎相似度检查脚本 | 无 | 无 | **加权 Jaccard>0.7 告警，排除基础库**（v0.3 修订） |
| D | P0 | known_gap 登记数 | 0(登记制未实施) | ≥ 100(热路径优先) | ≥ 500(全量) |
| D | P0 | 30 天 verify 率 | N/A | ≥ 30% | ≥ 50% |
| D | P0 | 全目录 except pass | **565+ReverseDeriver_count**（v0.3 修订） | ≤ 500(热路径改 safe_call) | ≤ 150 |
| D | P0 | 热路径延迟增加 | N/A | < 1ms(ring buffer) | < 1ms |
| D | P0 | **ring buffer mmap crash 恢复**（v0.3 新增） | 无 | 实现并验证 | 持续运行 |
| D | P0 | **ring buffer 溢出 FAIL-OPEN**（v0.3 新增，H-7） | 无 | 丢弃+告警不阻塞 | 持续运行 |
| D | P0 | **cognitive_enabled=False fallback**（v0.3 新增） | 无 | 本地 JSON 日志 | Phase3 解冻后同步 |
| E | P0 | refactor 提交/sprint | 0 | ≥ 1 | ≥ 2 |
| E | P0 | 债务阈值触发器 | 无 | CI 生效 | CI 生效 |
| F | P2 | evidence 去重 | 无 | 无 | evidence_id 唯一 |
| F | P2 | git_history 路径失败 | 静默空 | 静默空 | 返回 unknown |
| F | P2 | REA 自解析报告 | 无 | 无 | 产出 |

---

## 7. 执行顺序建议

> **v0.2 修订（评审2）**: 插入 P0-0 TDD 前置为第一步，确保拆分有测试保护。
> **v0.3 修订**: 本节是 SPEC v0.3 内部 P0-P3 的顺序。与矛盾论断裂修复 SPEC 的联合执行序列见 **§8**——两 SPEC 存在目标文件冲突（改造2/4 修改 evolution_pipeline.py，P0-1 要拆分该文件），必须按 §8 联合序列执行。

1. **P0-0 TDD 前置**（最先，建立测试基线 692+RED 测试）
2. **P0-3 债务阈值触发器**（自动强制后续 P0）
3. **P0-1 拆分主入口**（RED 测试保护下，触发器会持续报警直到完成；**与矛盾论改造2/4 的顺序见 §8**）
4. **P0-4 FAIL-OPEN 登记制+safe_call 分层**（与新拆分组件同步落地；含 ring buffer mmap+cognitive_enabled fallback）
5. **P0-2 废单例**（P1，拆分完成且热点拆分时同期落地；**依赖注入连锁见 §10**）
6. **P1-1/P1-2 热点拆分**（下次改动这两个文件时）
7. **P2 系列**（下一迭代，REA 自身修复可与引擎治理并行）
8. **P3 架构自进化**（长期，依赖 P2 REA 修复完成；**P3-1 requires new SPEC，见 §4**）

---

## 8. 与矛盾论断裂修复 SPEC 的联合执行序列（v0.3 新增）

> **来源**: 深度调研报告建议1 — 重大遗漏 O-1
> **问题**: 矛盾论断裂修复 SPEC 的改造2/4 修改 `evolution_pipeline.py`，与 SPEC v0.3 的 P0-1 拆分该文件存在目标文件冲突。若拆分先，改造2/4 的目标代码位置变化；若改造2/4 先，拆分需适配已修改代码。

### 8.1 矛盾论断裂修复 SPEC 的 5 个改造

| 改造 | 优先级 | 目标文件 | 与 SPEC v0.3 冲突点 |
|------|--------|---------|-------------------|
| 改造1 (P0) | P0 | resistance_vector.py | 无直接冲突 |
| 改造2 (P1) | P1 | evolution_pipeline.py `_select_optimal_path` L652-L813 | **与 P0-1 拆分冲突**: 拆分后 `_select_optimal_path` 迁移到 PathDiscoveryService |
| 改造3 (P1) | P1 | resistance_vector.py `calculate()` | 无直接冲突，但矛盾调制改变 R_up/R_down 值（见 H-B2） |
| 改造4 (P2) | P2 | evolution_pipeline.py L544-L555 | **与 P0-1 拆分冲突**: FREEZE 逻辑在拆分目标文件内 |
| 改造5 (P3) | P3 | bellman_tracker.py | 无直接冲突 |

### 8.2 联合执行序列

```
改造1 (resistance_vector.py 微观阻力向量)
  ↓
改造3 (resistance_vector.py 矛盾调制 R 值)
  ↓
P0-0 TDD 前置 (建立测试基线 692 + 4 组件 RED 测试)
  ↓
改造2 (evolution_pipeline.py _select_optimal_path — 拆分前在同一文件内完成)
  ↓
改造4 (evolution_pipeline.py FREEZE 双候选 — 拆分前在同一文件内完成)
  ↓
P0-1 拆分主入口 (改造2/4 代码随拆分迁移到 PathDiscoveryService)
  ↓
P0-4 登记制 (safe_call 分层 + ring buffer mmap + cognitive_enabled fallback)
  ↓
P0-2 废单例 (依赖注入连锁，见 §10)
```

### 8.3 冲突解决原则

1. **改造2/4 先于 P0-1 拆分**: 在 evolution_pipeline.py 未拆分时完成改造2/4，避免拆分后跨组件修改
2. **改造2/4 代码随拆分迁移**: P0-1 拆分时，改造2/4 的代码随 `_select_optimal_path` 和 FREEZE 逻辑迁移到 PathDiscoveryService
3. **改造1/3 独立执行**: resistance_vector.py 不受 P0-1 拆分影响，可并行执行
4. **改造5 独立执行**: bellman_tracker.py 不受拆分影响，可并行执行

---

## 9. API 契约迁移方案（v0.3 新增）

> **来源**: 深度调研报告建议2 — 重大遗漏 O-3
> **问题**: 拆分 EvolutionPipeline 后，公开 API 从 1 类变为 4 类，所有调用方需更新。SPEC v0.2 只提到 trade_settlement_bridge L197，但可能有其他调用方（test_evolution_pipeline.py、scripts/、adapters/）。

### 9.1 Facade 模式兼容方案

```python
# EvolutionPipeline 保持为 Facade，内部委托给拆分组件
class EvolutionPipeline:
    """Facade — 保持向后兼容，内部委托给 Orchestrator/WeightStore/PathDiscovery/LoggingContext"""

    def __init__(self, gene_root: Path | str | None = None):
        self._logging = PipelineLoggingContext()
        self._weight_store = WeightStore(gene_root)
        self._path_discovery = PathDiscoveryService()
        self._orchestrator = EvolutionOrchestrator(
            weight_store=self._weight_store,
            path_discovery=self._path_discovery,
            logging_ctx=self._logging
        )
        # 向后兼容: 不再注册 _instance 单例

    def run_symbol(self, symbol, market_data, rv=None) -> dict:
        """对外契约不变 — 内部委托给 Orchestrator"""
        return self._orchestrator.run_symbol(symbol, market_data, rv)
```

### 9.2 调用方影响清单

| 调用方 | 当前用法 | 迁移方案 | 优先级 |
|--------|---------|---------|--------|
| trade_settlement_bridge.py L197 | `EvolutionPipeline._instance` | 构造函数注入 `IEvolutionPipeline`（见 §10） | P1 |
| test_evolution_pipeline.py | `EvolutionPipeline()` 构造 | Facade 兼容，无需修改 | P0 验证 |
| scripts/*.py | `EvolutionPipeline()` 构造 | Facade 兼容，无需修改 | P0 验证 |
| adapters/*.py | 可能引用 `_instance` | Grep 确认后按需迁移 | P1 |

### 9.3 迁移原则

1. **Facade 保持 `run_symbol()` 签名不变** — 所有 `EvolutionPipeline()` 构造方无需修改
2. **`_instance` 单例废除后** — 仅 trade_settlement_bridge 需改构造注入（见 §10）
3. **内部组件可独立测试** — Orchestrator/WeightStore/PathDiscovery/LoggingContext 各有独立测试
4. **渐进迁移** — Facade 模式允许调用方按需切换到直接使用拆分组件

---

## 10. 依赖注入迁移路径（v0.3 新增）

> **来源**: 深度调研报告建议3 — 副作用 S-4
> **问题**: 废除 `_instance` 单例后，trade_settlement_bridge.py L197 改为构造函数接收 `IEvolutionPipeline`。但这是依赖注入连锁的起点——API_SPEC.md §1.1 显示 `KlineEventHandler(settlement_bridge: Any)`，KlineEventHandler 构造函数接收 settlement_bridge，其构造方（DataPipelineAdapter 或上层编排器）需传入修改后的 TradeSettlementBridge。

### 10.1 IEvolutionPipeline Protocol 定义

```python
from typing import Protocol

class IEvolutionPipeline(Protocol):
    """EvolutionPipeline 接口契约 — 废除单例后外部组件通过此接口注入"""

    def run_symbol(self, symbol: str, market_data: dict, rv=None) -> dict:
        """四层闭环主流程"""
        ...

    def get_feedback(self) -> dict:
        """L4 反馈获取"""
        ...
```

### 10.2 依赖注入连锁迁移步骤

```
Step 1: 定义 IEvolutionPipeline Protocol
  ↓
Step 2: TradeSettlementBridge.__init__ 增加 pipeline: IEvolutionPipeline 参数
  (trade_settlement_bridge.py L197: pipe = EvolutionPipeline._instance → self._pipeline)
  ↓
Step 3: KlineEventHandler.__init__ 传入修改后的 TradeSettlementBridge
  (API_SPEC.md §1.1: KlineEventHandler(settlement_bridge: Any) — 已有参数，仅需传入修改后的实例)
  ↓
Step 4: DataPipelineAdapter 或上层编排器构造修改后的 KlineEventHandler
  (API_SPEC.md §7: DataPipelineAdapter 构造 KlineEventHandler)
  ↓
Step 5: adapters/ 层按需适配（Grep 确认实际影响范围）
```

### 10.3 迁移验收

- [ ] `IEvolutionPipeline` Protocol 定义完成
- [ ] `EvolutionPipeline` 实现 `IEvolutionPipeline`（Facade 模式，见 §9）
- [ ] `trade_settlement_bridge.py` 不再引用 `EvolutionPipeline._instance`，改为构造注入
- [ ] `KlineEventHandler` 构造函数接收修改后的 `TradeSettlementBridge`
- [ ] Grep `EvolutionPipeline._instance` 全目录返回 0 行（排除注释）
- [ ] 全量回归测试通过（基线 692 passed）

### 10.4 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 构造链 ripple change | adapters 层需适配 | Facade 模式保持兼容，仅 _instance 引用方需改 |
| 循环依赖 | TradeSettlementBridge→IEvolutionPipeline→... | Protocol 抽象打破循环，EvolutionPipeline 不反向依赖 Bridge |
| 测试 Mock 困难 | test_evolution_pipeline.py 需适配 | IEvolutionPipeline Protocol 便于 Mock 注入 |

---

## 附录 A: 三源证据完整索引

### 技术文档
- [ENGINEERING_INDEX.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/ENGINEERING_INDEX.md) L13-17, L101-123
- [API_SPEC.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/API_SPEC.md) L466-493
- [SPEC-金融逆向推导子系统.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/SPEC-金融逆向推导子系统.md) L166-200
- [SPEC-矛盾论实现断裂修复与阻力场升级.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/SPEC-矛盾论实现断裂修复与阻力场升级.md)

### 代码实现
- [evolution_pipeline.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py) L37-66, L72-105, L152-177, L1101-1143, L1257-1317
- [trade_settlement_bridge.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/trade_settlement_bridge.py) L195-199
- [deep_reasoning_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/deep_reasoning_engine.py) L30-95, L162-179
- [kline_event_handler.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/kline_event_handler.py) L34-95
- [reflection_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/reflection_engine.py) L271-317
- [investigation_workflow.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程/core/investigation_workflow.py) L109-117
- [git_history.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程/core/git_history.py)
- [algorithm_reducer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程/core/algorithm_reducer.py)

### 运行日志
- [evolution_pipeline.log](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/logs/evolution_pipeline.log) L2-30
- [audit_20260912_0013.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/audit_reports/audit_20260912_0013.md) L11-20
- [model_validation_20260915_0011.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/audit_reports/model_validation_20260915_0011.md) L131-134

### git 证据
- evolution_pipeline.py: `git log --oneline` → 12 feat/fix, 0 refactor
- reflection_engine.py: `git log --oneline` → 含 9ab2196967 "补漏12项未落地全部实现"
- 全目录: `565 except pass across 100 files`

---

## 附录 B: 与反思报告的映射

| 反思报告维度 | 本 SPEC 章节 | 优先级 | 三源证据覆盖 |
|---|---|---|---|
| A 主入口过载+单例耦合 | §2.A | P0(拆分)+P1(废单例) | 文档✓ 代码✓ 日志△ |
| B 模块耦合热点 | §2.B | P1 | 文档✓ 代码✓ 日志✓ |
| C 引擎爆炸 | §2.C | P2 | 文档✓ 代码✓ 日志✓(v0.2 补) |
| D FAIL-OPEN 异化 | §2.D | P0 | 文档✓ 代码✓ 日志✓ |
| E 加法演化无重构 | §2.E | P0 | 文档✓ 代码✓ 日志✓(v0.2 补) |
| F REA 自身局限 | §2.F | P2 | 文档✓ 代码✓ 日志✓ |
| 元层 架构自进化 | §4 | P3 | 推导性 |

### v0.3 新增章节（来自深度调研报告，非反思报告维度）

| 章节 | 来源 | 深度调研建议# | 内容 |
|------|------|-------------|------|
| §8 | 深度调研报告 O-1 | 建议1 | 与矛盾论断裂修复 SPEC 的联合执行序列 |
| §9 | 深度调研报告 O-3 | 建议2 | API 契约迁移方案（Facade 模式） |
| §10 | 深度调研报告 S-4 | 建议3 | 依赖注入迁移路径（IEvolutionPipeline Protocol） |
