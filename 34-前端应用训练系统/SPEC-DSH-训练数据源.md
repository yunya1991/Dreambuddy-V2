# SPEC-20261012-DSH — DSH 层训练数据源扩展

> **版本**: v0.2 (19-DAL 调研后修订)
> **日期**: 2026-10-12
> **作者**: Trae + User
> **状态**: Draft（待评审）
> **关联**: SPEC-20261011 (双模式学习训练架构), SPL v0.4, SPEC-20261009-SOLUTION-PATTERN-LEARNER
> **方法论**: recall → DSH 架构调研 → 18/19/20 数据模块初步调研 → SPEC v0.1 → 19-DAL 深入调研 → SPEC v0.2
> **目标层**: DSH 层 (ExecutionPathTrainingLoop — 序列模式挖掘 + 路径模板)
> **v0.2 变更**:
> - P3 (19-DAL) 从"待深入调研"修订为"价值极高，已有审计表"
> - 发现 ma_migration_audit 表天然记录 DualWrite/shadow_read 调用链
> - DualWrite 代理层（di.py L109-260）是 5-6 节点的完整执行路径
> - 建议实施顺序改为 P0 + P3 并行（两者都不需要补日志）

---

## 0. Executive Summary

### 0.1 核心命题

DSH 层（Dream OS Subagent Harness）训练器 `ExecutionPathTrainingLoop` 需要 `{"task", "node_sequence", "outcome"}` 三元组作为训练数据。当前 7 个采集器（TDR/Cognitive/Skill/Doc/REA/Trae/Trading）主要服务 S 层（意图识别）和 C 层（反思），**DSH 层训练数据严重不足**——现有采集器产出的 `actions` 字段多为单元素列表，不是真正的"执行路径序列"。

本 SPEC 定义 4 个**原生序列数据源**，直接产出 `node_sequence`（多节点执行路径），专供 DSH 层训练：

| 优先级 | 数据源 | 序列来源 | 现成度 | 预期序列长度 |
|--------|--------|----------|--------|-------------|
| **P0** | 20-数据清洗中心 | `CleaningTrace.actions` | ✅ 已有契约 | 5-7 节点 |
| **P1** | 18-数据获取中心 | dispatcher 路由 + Bronze→Silver→Gold 链 | 🟡 需封装 | 4-6 节点 |
| **P2** | DSH 子 Agent | `reasoning_chain` 执行链 | 🔴 需补日志 | 3-8 节点 |
| **P3** | 19-DAL 统一数据层 | Repo 调用链 + DualWrite 路由 | ⏳ 待深入调研 | 待定 |

### 0.2 设计驱动力

| 编号 | 驱动力 | 来源 |
|------|--------|------|
| F1 | DSH 层 `ExecutionPathTrainingLoop` 需要真正的序列数据，现有采集器产出的 actions 多为单元素 | 调研发现 |
| F2 | 20-数据清洗中心已有 `CleaningTrace` 契约，天然就是 `node_sequence` | 代码调研 `contract.py` |
| F3 | 18-数据获取中心的 dispatcher 路由 + Bronze→Silver→Gold 清洗链是完整的执行路径 | 代码调研 `dispatcher.py` |
| F4 | DSH 子 Agent 的 `SubagentOutput` 契约已定义 `reasoning_chain` 字段，但 heartbeat_monitor 未输出到日志 | 代码调研 `subagent_types.py` + `heartbeat_monitor.py` |
| F5 | 19-DAL 作为统一数据访问层，有 9 个 Repo 协议 + DualWrite + 审计 + 路由逻辑，潜在训练价值高 | User 纠正 + README 调研 |
| F6 | 用户要求 19-DAL 需仔细调研，不能简单评估为"价值低" | User 指令 |

### 0.3 范围边界

**In Scope:**
- 定义 4 个 DSH 层原生序列数据源的采集器设计
- P0 (20-数据清洗中心) 采集器完整实现规格
- P1 (18-数据获取中心) 采集器实现规格
- P2 (DSH 子 Agent) 日志补全规格 + 采集器设计
- P3 (19-DAL) 待深入调研标记 + 初步价值评估
- DSH 层训练数据格式映射（TrainingCase → `{"task", "node_sequence", "outcome"}`）

**Out of Scope:**
- 不修改 `ExecutionPathTrainingLoop` 内部逻辑（只扩展数据源）
- 不修改 20-数据清洗中心的 `DataCleaningPipeline` 核心逻辑（只消费 `CleaningTrace`）
- 不修改 18-数据获取中心的 `DataCenter.fetch()` 核心逻辑（只在出口采集 trace）
- 不修改 DSH 子 Agent 的执行逻辑（只补日志输出）
- 19-DAL 深入调研留作 SPEC 形成后的独立任务

---

## 1. 调研结论（事实清单）

### 1.1 DSH 层训练数据格式（已确认）

**来源**: [run_continual_training.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/scripts/run_continual_training.py#L134-L135) L134-135

```python
elif layer == "DSH":
    return {"task": case.intent, "node_sequence": case.actions, "outcome": outcome}
```

- `task`: 任务标识（intent_type，如 "data_cleaning" / "subagent_dispatch"）
- `node_sequence`: 执行路径节点列表（`List[str]`，每个元素是一个节点描述）
- `outcome`: 结果标识（success/failure/partial，由 `derive_outcome(case)` 派生）

**关键约束**: `node_sequence` 必须是多节点序列（≥2 个节点），单元素列表无法训练序列模式。

### 1.2 现有采集器的 DSH 层覆盖度（不足）

**来源**: [run_continual_training.py](file:///Users/zhangjiango/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/scripts/run_continual_training.py#L95-L103) L95-103

| 采集器 | layer_tags | actions 特征 | DSH 适用性 |
|--------|-----------|-------------|-----------|
| TDR | ["S"] | 单元素 | ❌ 不含 DSH |
| Cognitive | ["S","C"] | 单元素 | ❌ 不含 DSH |
| Skill | ["S","C"] | 单元素 | ❌ 不含 DSH |
| Doc | ["S","C"] | 单元素 | ❌ 不含 DSH |
| REA | ["S","C","G","LLM"] | 多步骤 | 🟡 部分适用 |
| Trae | ["S"] | 单元素 | ❌ 不含 DSH |
| Trading | ["S","C"] | 单元素(msg) | ❌ 不含 DSH |

**结论**: 现有 7 个采集器中，仅 REA 的 actions 是多步骤，但也不含 DSH 层标签。DSH 层需要**原生序列数据源**。

### 1.3 P0 数据源：20-数据清洗中心（已确认 ✅）

**来源**: [contract.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/20-数据清洗中心/data_cleaning/contract.py) + [pipeline.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/20-数据清洗中心/data_cleaning/pipeline.py)

**核心契约**:

```python
@dataclass(slots=True)
class CleanAction:
    step: str              # 算子名（如 "DedupAlign" / "Outlier3LFilter"）
    input_rows: int        # 进入该算子的行数
    output_rows: int       # 离开该算子的行数
    clipped_count: int     # 被裁剪/标记的异常值单元格数
    imputed_count: int     # 被插补的缺失值单元格数
    blocked_count: int     # QualityGate 拒绝的行数
    note: str              # 自由备注

@dataclass(slots=True)
class CleaningTrace:
    actions: list[CleanAction]  # ★ 这就是 node_sequence
    started_at: datetime
    finished_at: datetime | None

@dataclass(slots=True)
class SilverRecord:
    bronze_id: str
    df: pd.DataFrame
    trace: CleaningTrace       # ★ 携带完整执行路径
    gate_passed: bool          # ★ 这就是 outcome
    quality_report: list[Any]
    schema_tag: str
```

**清洗管道顺序** (pipeline.py L98-187):
1. `DedupAlignCleaner` — 去重对齐
2. `Outlier3LFilter` — 3σ + IQR + 动态ATR 三级异常过滤
3. `MissingImputer` — 缺失值插补
4. `UnitNormalizer` — 单位规范化
5. `QualityGate` — 质量门禁

**关键洞察**:
- `CleaningTrace.actions` 天然就是 `node_sequence`，每步算子是一个节点
- `SilverRecord.gate_passed` 天然就是 `outcome`（True=success, False=failure）
- 序列长度 5-7 节点，完美适合 DSH 层序列模式训练
- **现成度最高**——契约已定义，pipeline 已实现，只需写采集器消费 trace

**采集可行性**:
- 20-数据清洗中心运行时产出 `SilverRecord`，含 `trace`
- 采集器需 hook 到 pipeline 出口或读取 trace 日志
- **方案 A（推荐）**: 在 pipeline 出口添加 trace 序列化日志（JSON 行），采集器读日志
- **方案 B**: 直接 import DataCleaningPipeline，跑一遍样本数据采集 trace（侵入性高）

### 1.4 P1 数据源：18-数据获取中心（需封装 🟡）

**来源**: [dispatcher.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心/data_center/core/dispatcher.py) + silver_layer.py + gold_layer.py

**路由逻辑** (dispatcher.py L177-220):
- `DataCenter.fetch(category, source)` 按 category/source 路由到 collector
- `_fetch_monitored()` 包装采集过程，记录监控指标

**清洗链** (silver_layer.py L141-179):
- Bronze → Silver: 去重 → 3σ → IQR → 动态ATR
- 只用 `logging.debug` 记录异常，**未显式记录链路节点序列**

**Gold 层** (gold_layer.py L46-99):
- Schema 验证（Pandera），只有 debug 记录

**关键问题**:
- 18 的清洗链与 20-数据清洗中心有重叠（20 是 18 的 Silver 层独立化）
- 18 的 dispatcher 路由逻辑本身是 node_sequence：`fetch(category,source) → collector → _fetch_monitored → bronze → silver → gold`
- 但 18 **未显式序列化**这个路由链路到日志

**采集方案**:
- 在 dispatcher `_fetch_monitored` 出口添加路由链路日志（JSON 行）
- 采集器读日志，每条 fetch 请求产出一条 TrainingCase
- node_sequence = `["dispatcher.fetch", "collector.{name}", "_fetch_monitored", "bronze.write", "silver.clean", "gold.validate"]`

### 1.5 P2 数据源：DSH 子 Agent（需补日志 🔴）

**来源**: [subagent_registry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/packages/python-server/subagent_registry.py) + [subagent_types.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/packages/python-server/subagent_types.py) + heartbeat_monitor.py + server.py

**8 个子 Agent** (subagent_registry.py L30-112):
| node_id | module | capability_id |
|---------|--------|--------------|
| technical | technical_analysis | ta_indicator |
| sentiment | sentiment_analysis | sa_score |
| macro | macro_analysis | macro_indicator |
| flow | flow_analysis | fund_flow |
| onchain | onchain_analysis | chain_metric |
| valuation | valuation_analysis | val_metric |
| risk | risk_analysis | risk_score |
| portfolio | portfolio_analysis | alloc_advice |
| synthesizer | synthesis | decision_merge |

**SubagentOutput 契约** (subagent_types.py L39-68):
- 含 `reasoning_chain` 字段（设计用于审计）
- **但 heartbeat_monitor.py 只记录调用统计**（subagent_type/耗时/状态/错误数）
- **未输出 `reasoning_chain` 到日志**

**基础设施**:
- `server.py` 的 `_send_stderr` 已有 JSON 行格式输出到 stderr 的基础设施
- 补日志只需在子 Agent 执行后调用 `_send_stderr` 输出 `reasoning_chain`

**采集方案**:
1. **Phase 1（补日志）**: 在每个子 Agent 执行后，将 `reasoning_chain` 序列化为 JSON 行输出到 stderr
2. **Phase 2（写采集器）**: `DshSubagentCollector` 读 stderr 日志，提取 `reasoning_chain` 作为 `node_sequence`
3. task = subagent_type（如 "technical" / "sentiment"）
4. outcome = 执行状态（success/error/timeout）

### 1.6 P3 数据源：19-DAL 统一数据层（已深入调研 ✅ — 价值极高）

**深入调研结论**: 用户纠正完全正确——19-DAL 作为统一调用层，训练价值**极高**，远超之前评估。关键发现：**19-DAL 已有 `ma_migration_audit` 审计表**，天然记录 DualWrite/shadow_read 调用链，不需要补日志。

**5 层可序列化调用链**:

| 层 | 文件 | node_sequence | outcome | 审计表 |
|----|------|---------------|---------|--------|
| **DI 路由层** | [di.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/dreambuddy_dal/di.py) L85-103 | `get_*_repo → _resolve_backend → check_kill_switch → build_factory → _get_instance` | backend 选中值 | — |
| **DualWrite 代理层** ★ | di.py L109-260 `_make_dual_write` | `intercept → classify_method → legacy.execute → new.execute_secondary → shadow_read.compare → audit.write` | MATCH/DIFF | ma_migration_audit |
| **Gate 检查层** | [gate_check.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/dreambuddy_dal/implementations/sqlite_unified/gate_check.py) | `check_g1_dual_write_diff → check_g2_db_locked → check_g3_shadow_read → check_g4_rollback → check_g5_backup` | all_pass | ma_migration_audit |
| **审计汇总层** | [audit_summary.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/dreambuddy_dal/implementations/sqlite_unified/audit_summary.py) | `query_dual_write_audit → query_shadow_read_audit → compute_diff_rate → compute_consistency_rate → return_summary` | g1_pass/g3_pass | ma_migration_audit |
| **Cron 运维层** | [cron_runner.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/dreambuddy_dal/cron_runner.py) | `dispatch(backup/integrity/rotate/checkpoint) → execute → print_result` | OK/FAIL | — |

**核心发现 — ma_migration_audit 审计表**:

`ma_migration_audit` 表是 19-DAL 天然的训练数据源，已记录：
- `category='dual_write'` → 写审计（result=APPLIED/SKIPPED/FAILED）
- `category='shadow_read'` → 读审计（result=MATCH/DIFF）
- `category='migration_script'` → 迁移批次审计

每条审计记录含: `event_name, entity_key, result, severity, details(JSON), latency_ms, run_at`

**DualWrite 代理层训练价值最高**（di.py L175-260 `_DualWrapper`）:
- `__getattr__` 动态拦截所有 Repo 方法调用
- 方法分类路由: WRITE_PREFIXES (`add_/upsert_/close_/create_/...`) vs READ_PREFIXES (`get_/query_/list_/has_/...`)
- 双写执行: legacy 主执行（写失败即抛）→ new 库防御性执行（失败只 warning）
- 影子读比对: `_compare_results()` 浅比对 → 写审计到 ma_migration_audit
- READ_SOURCE 路由: `legacy`(默认) / `shadow`(比对) / `next_gen`(切读新库)

**关键纠正**:
> 用户原话: "19-DAL 逻辑上这是一个统一调用层，价值为什么很低，需要仔细调研"
> 调研结论: 19-DAL 价值不低，是 DSH 层训练数据源中**现成度最高**的（已有审计表，不需要补日志）

---

## 2. 数据源优先级矩阵

| 优先级 | 数据源 | 序列来源 | 现成度 | 序列长度 | 采集器工作量 | 训练价值 |
|--------|--------|----------|--------|---------|-------------|---------|
| **P0** | 20-数据清洗中心 | `CleaningTrace.actions` | ✅ 契约已定义 | 5-7 | 低（写采集器） | 高（完整清洗路径） |
| **P1** | 18-数据获取中心 | dispatcher 路由链 | 🟡 需补日志 | 4-6 | 中（补日志+采集器） | 中高（数据采集路径） |
| **P2** | DSH 子 Agent | `reasoning_chain` | 🔴 需补日志 | 3-8 | 中高（补日志+采集器） | 最高（DSH 原生路径） |
| **P3** | 19-DAL 统一数据层 | ma_migration_audit 审计表 | ✅ 已有审计表 | 5-6 节点 | 低（查询审计表） | 高（DualWrite 路由路径） |

**优先级依据**:
- P0 最高：契约已定义，现成度最高，工作量最低，立即落地
- P3 并列高：**已有审计表 ma_migration_audit**，现成度与 P0 相当，只需写采集器查询表
- P1 次之：路由链已存在但未序列化，需补少量日志
- P2 重要但延后：DSH 原生路径训练价值最高，但需补日志且工作量较大

**优先级修订（19-DAL 调研后）**:
- 原 P3"待调研" → 现已深入调研，**价值极高，现成度与 P0 相当**
- 建议实施顺序: **P0 + P3 并行**（两者都不需要补日志） → P1 → P2

---

## 3. 采集器设计

### 3.1 P0: CleaningTraceCollector（20-数据清洗中心）

**文件**: `34-前端应用训练系统/adapters/cleaning_trace_collector.py`

**采集机制**: 方案 A — 读 trace 序列化日志

**前置条件**: 在 `20-数据清洗中心/data_cleaning/pipeline.py` 出口添加 trace 序列化日志

**pipeline.py 补丁（规格）**:
```python
# 在 DataCleaningPipeline.run() 出口，SilverRecord 产出后:
import json, sys
def _emit_trace_log(silver_record: SilverRecord):
    """将 CleaningTrace 序列化为 JSON 行输出到 stderr，供采集器消费。"""
    trace_obj = {
        "event": "cleaning_trace",
        "bronze_id": silver_record.bronze_id,
        "schema_tag": silver_record.schema_tag,
        "gate_passed": silver_record.gate_passed,
        "node_sequence": [
            {
                "step": a.step,
                "input_rows": a.input_rows,
                "output_rows": a.output_rows,
                "clipped": a.clipped_count,
                "imputed": a.imputed_count,
                "blocked": a.blocked_count,
                "note": a.note,
            }
            for a in silver_record.trace.actions
        ],
        "started_at": silver_record.trace.started_at.isoformat(),
        "finished_at": silver_record.trace.finished_at.isoformat()
        if silver_record.trace.finished_at else None,
    }
    print(json.dumps(trace_obj), file=sys.stderr, flush=True)
```

**采集器规格**:
```python
class CleaningTraceCollector(TrainingDataProvider):
    """从 20-数据清洗中心 stderr 日志采集 CleaningTrace 序列。"""

    def get_source_name(self) -> str:
        return "cleaning_trace"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit=100, since=None) -> List[TrainingCase]:
        # 1. 读取 20-数据清洗中心 stderr 日志文件
        # 2. 过滤 event=="cleaning_trace" 的 JSON 行
        # 3. 增量过滤: started_at > since
        # 4. 转换为 TrainingCase:
        #    - intent = "data_cleaning" (固定)
        #    - actions = [a["step"] for a in node_sequence]  # ["DedupAlign", "Outlier3LFilter", ...]
        #    - outcome_text = "gate_passed" if gate_passed else "gate_failed"
        #    - learned = [a["note"] for a in node_sequence if a["note"]]
        #    - layer_tags = ["DSH"]  # ★ DSH 层专属
        #    - quality = "B" (实践验证的清洗路径)
        #    - confidence = 0.7 (gate_passed=True 高置信)
        #    - source = "cleaning_trace"
        #    - metadata = {bronze_id, schema_tag, 节点数, 裁剪总数, 插补总数}
```

**TrainingCase 映射**:
| TrainingCase 字段 | 来源 | 示例 |
|-------------------|------|------|
| intent | 固定 "data_cleaning" | "data_cleaning" |
| actions | `trace.actions[].step` | ["DedupAlign", "Outlier3LFilter", "MissingImputer", "UnitNormalizer", "QualityGate"] |
| outcome_text | gate_passed | "gate_passed" / "gate_failed" |
| learned | trace.actions[].note | ["3σ 标记5", "IQR clip2"] |
| layer_tags | 固定 | ["DSH"] |
| quality | 固定 | "B" |
| confidence | gate_passed 派生 | 0.7 (passed) / 0.4 (failed) |

### 3.2 P1: DataFetchRouteCollector（18-数据获取中心）

**文件**: `34-前端应用训练系统/adapters/data_fetch_route_collector.py`

**采集机制**: 读 dispatcher 路由日志

**前置条件**: 在 `18-数据获取中心/data_center/core/dispatcher.py` 的 `_fetch_monitored` 出口添加路由链日志

**dispatcher.py 补丁（规格）**:
```python
# 在 _fetch_monitored() 出口:
def _emit_route_log(category, source, collector_name, stages, success, error=None):
    """将 fetch 路由链序列化为 JSON 行输出到 stderr。"""
    route_obj = {
        "event": "data_fetch_route",
        "category": category,
        "source": source,
        "collector": collector_name,
        "node_sequence": stages,  # ["dispatcher.fetch", "collector.{name}", "_fetch_monitored", "bronze.write", "silver.clean", "gold.validate"]
        "outcome": "success" if success else "error",
        "error": error,
    }
    print(json.dumps(route_obj), file=sys.stderr, flush=True)
```

**采集器规格**:
```python
class DataFetchRouteCollector(TrainingDataProvider):
    """从 18-数据获取中心 stderr 日志采集 fetch 路由链。"""

    def get_source_name(self) -> str:
        return "data_fetch_route"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit=100, since=None) -> List[TrainingCase]:
        # 1. 读取 18-数据获取中心 stderr 日志文件
        # 2. 过滤 event=="data_fetch_route" 的 JSON 行
        # 3. 增量过滤
        # 4. 转换为 TrainingCase:
        #    - intent = f"fetch_{category}" (如 "fetch_macro" / "fetch_chain")
        #    - actions = node_sequence  # ["dispatcher.fetch", "collector.xxx", ...]
        #    - outcome_text = outcome
        #    - layer_tags = ["DSH"]
        #    - quality = "B"
        #    - confidence = 0.6 (success) / 0.3 (error)
```

### 3.3 P2: DshSubagentCollector（DSH 子 Agent）

**文件**: `34-前端应用训练系统/adapters/dsh_subagent_collector.py`

**采集机制**: 读 DSH python-server stderr 日志

**前置条件**: 在 DSH 子 Agent 执行后输出 `reasoning_chain` 到 stderr

**server.py 补丁（规格）**:
```python
# 在子 Agent 执行完成后（SubagentOutput 产出后）:
def _emit_reasoning_log(subagent_type: str, output: SubagentOutput):
    """将 reasoning_chain 序列化为 JSON 行输出到 stderr。"""
    log_obj = {
        "event": "subagent_reasoning",
        "subagent_type": subagent_type,
        "node_sequence": output.reasoning_chain,  # List[str]
        "outcome": "success" if output.success else "error",
        "error": output.error,
        "duration_ms": output.duration_ms,
    }
    _send_stderr(log_obj)  # 复用已有的 JSON 行输出基础设施
```

**采集器规格**:
```python
class DshSubagentCollector(TrainingDataProvider):
    """从 DSH python-server stderr 日志采集子 Agent reasoning_chain。"""

    def get_source_name(self) -> str:
        return "dsh_subagent"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit=100, since=None) -> List[TrainingCase]:
        # 1. 读取 DSH python-server stderr 日志文件
        # 2. 过滤 event=="subagent_reasoning" 的 JSON 行
        # 3. 增量过滤
        # 4. 转换为 TrainingCase:
        #    - intent = subagent_type  (如 "technical" / "sentiment" / "macro")
        #    - actions = node_sequence  # reasoning_chain
        #    - outcome_text = outcome
        #    - layer_tags = ["DSH"]
        #    - quality = "A" (DSH 原生路径，训练价值最高)
        #    - confidence = 0.8 (success) / 0.3 (error)
```

**注意**: P2 采集器的 quality 设为 "A"（高于 P0/P1 的 "B"），因为 DSH 子 Agent 的 reasoning_chain 是 DSH 层的原生训练数据，训练价值最高。

### 3.4 P3: DalRouteCollector（19-DAL 统一数据层）— 价值极高 ✅

**文件**: `34-前端应用训练系统/adapters/dal_route_collector.py`

**采集机制**: 直接查询 `ma_migration_audit` 审计表（不需要补日志！）

**核心优势**: 19-DAL 已有 `ma_migration_audit` 审计表，记录所有 DualWrite 和 shadow_read 调用链。**现成度与 P0 相当**——只需写采集器查询审计表。

**采集器规格**:
```python
class DalRouteCollector(TrainingDataProvider):
    """从 19-DAL ma_migration_audit 审计表采集调用链。"""

    def get_source_name(self) -> str:
        return "dal_route"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit=100, since=None) -> List[TrainingCase]:
        # 1. 连接 dreambuddy_core.db
        # 2. 查询 ma_migration_audit 表（按 run_at 增量过滤）
        # 3. 按 category 分类:
        #    a) category='dual_write' → node_sequence = [
        #         "dual_write.intercept", "classify_method",
        #         "legacy.execute", "new.execute_secondary",
        #         "audit.write"
        #       ]
        #       outcome = result (APPLIED/SKIPPED/FAILED)
        #    b) category='shadow_read' → node_sequence = [
        #         "dual_write.intercept", "classify_method",
        #         "legacy.read", "new.read",
        #         "shadow_read.compare", "audit.write"
        #       ]
        #       outcome = result (MATCH/DIFF)
        #    c) category='migration_script' → node_sequence = [
        #         "import_batch.run", "batch.{batch_id}",
        #         "insert_or_ignore", "audit.write"
        #       ]
        #       outcome = result (APPLIED/SKIPPED/FAILED)
        # 4. 转换为 TrainingCase:
        #    - intent = f"dal_{category}"  (如 "dal_dual_write" / "dal_shadow_read")
        #    - actions = node_sequence
        #    - outcome_text = result
        #    - layer_tags = ["DSH"]
        #    - quality = "A" (审计表是已验证的真实调用记录)
        #    - confidence = 0.8 (MATCH/APPLIED) / 0.3 (DIFF/FAILED)
        #    - metadata = {entity_key, severity, latency_ms, details, run_at}
```

**TrainingCase 映射**:
| TrainingCase 字段 | 来源 | 示例 |
|-------------------|------|------|
| intent | `f"dal_{category}"` | "dal_dual_write" / "dal_shadow_read" |
| actions | 按 category 固定模板 | ["dual_write.intercept", "classify_method", "legacy.execute", "new.execute_secondary", "audit.write"] |
| outcome_text | audit result | "MATCH" / "DIFF" / "APPLIED" / "FAILED" |
| learned | details JSON | ["method=add_trade", "entity=trade#xxx"] |
| layer_tags | 固定 | ["DSH"] |
| quality | 固定 | "A"（审计表是真实调用记录） |
| confidence | result 派生 | 0.8 (MATCH/APPLIED) / 0.3 (DIFF/FAILED) |

**Gate 检查采集（附加）**:

除 ma_migration_audit 外，gate_check.py 的 `run_gate_check()` 也产出 `GateCheckResult`（G-1~G-5 五项决策路径），可序列化为:
```json
{
    "task": "dal_gate_check",
    "node_sequence": ["check_g1_dual_write_diff", "check_g2_db_locked", "check_g3_shadow_read", "check_g4_rollback", "check_g5_backup"],
    "outcome": "all_pass"
}
```
采集方式: 在 `run_gate_check()` 出口添加 JSON 行日志输出到 stderr，采集器读日志。

---

## 4. DSH 层训练数据格式映射

### 4.1 统一映射规则

所有 4 个采集器产出的 TrainingCase 通过 `_convert_case_to_training_data(case, "DSH")` 转换为:

```python
{
    "task": case.intent,           # 任务标识
    "node_sequence": case.actions,  # 执行路径节点列表
    "outcome": outcome              # 结果标识 (success/failure/partial)
}
```

### 4.2 各数据源的映射示例

**P0 — 20-数据清洗中心**:
```json
{
    "task": "data_cleaning",
    "node_sequence": ["DedupAlign", "Outlier3LFilter", "MissingImputer", "UnitNormalizer", "QualityGate"],
    "outcome": "success"
}
```

**P1 — 18-数据获取中心**:
```json
{
    "task": "fetch_macro",
    "node_sequence": ["dispatcher.fetch", "collector.fred", "_fetch_monitored", "bronze.write", "silver.clean", "gold.validate"],
    "outcome": "success"
}
```

**P2 — DSH 子 Agent**:
```json
{
    "task": "technical",
    "node_sequence": ["load_kline", "compute_rsi", "compute_macd", "detect_divergence", "score_signal"],
    "outcome": "success"
}
```

**P3 — 19-DAL（已确认）**:
```json
{
    "task": "dal_shadow_read",
    "node_sequence": ["dual_write.intercept", "classify_method", "legacy.read", "new.read", "shadow_read.compare", "audit.write"],
    "outcome": "MATCH"
}
```

---

## 5. 实施计划

### 5.1 Phase 1: P0 落地（20-数据清洗中心）

| 步骤 | 工作项 | 文件 |
|------|--------|------|
| 1.1 | pipeline.py 出口添加 trace 序列化日志 | `20-数据清洗中心/data_cleaning/pipeline.py` |
| 1.2 | 实现 CleaningTraceCollector | `34-前端应用训练系统/adapters/cleaning_trace_collector.py` |
| 1.3 | 注册采集器到 run_continual_training.py | `34-前端应用训练系统/scripts/run_continual_training.py` |
| 1.4 | 测试: 采集 trace → TrainingCase → DSH 层喂入 | — |

### 5.2 Phase 2: P1 落地（18-数据获取中心）

| 步骤 | 工作项 | 文件 |
|------|--------|------|
| 2.1 | dispatcher.py `_fetch_monitored` 出口添加路由日志 | `18-数据获取中心/data_center/core/dispatcher.py` |
| 2.2 | 实现 DataFetchRouteCollector | `34-前端应用训练系统/adapters/data_fetch_route_collector.py` |
| 2.3 | 注册采集器 | run_continual_training.py |
| 2.4 | 测试 | — |

### 5.3 Phase 3: P2 落地（DSH 子 Agent）

| 步骤 | 工作项 | 文件 |
|------|--------|------|
| 3.1 | server.py 子 Agent 执行后输出 reasoning_chain 到 stderr | `1-ARCHITECTURE/dream-harness-bridge/packages/python-server/server.py` |
| 3.2 | 实现 DshSubagentCollector | `34-前端应用训练系统/adapters/dsh_subagent_collector.py` |
| 3.3 | 注册采集器 | run_continual_training.py |
| 3.4 | 测试 | — |

### 5.4 Phase 4: P3 落地（19-DAL — 与 P0 并行）

| 步骤 | 工作项 | 文件 |
|------|--------|------|
| 4.1 | 实现 DalRouteCollector（查询 ma_migration_audit 审计表） | `34-前端应用训练系统/adapters/dal_route_collector.py` |
| 4.2 | 注册采集器到 run_continual_training.py | `34-前端应用训练系统/scripts/run_continual_training.py` |
| 4.3 | 测试: 查询审计表 → TrainingCase → DSH 层喂入 | — |
| 4.4 | （可选）gate_check 出口添加 JSON 行日志，采集 Gate 检查决策路径 | `19-数据访问层/.../gate_check.py` |

---

## 6. 验收标准

| 编号 | 验收项 | 验证方法 |
|------|--------|---------|
| AC1 | P0 采集器产出 ≥3 节点的 node_sequence | 检查 TrainingCase.actions 长度 |
| AC2 | P0 采集器 layer_tags 含 "DSH" | 检查 TrainingCase.layer_tags |
| AC3 | DSH 层 step 增长 > 0（训练触发） | run_continual_training.py 快照对比 |
| AC4 | P1 采集器产出 dispatcher 路由链 | 检查 node_sequence 含 "dispatcher.fetch" |
| AC5 | P2 采集器产出 reasoning_chain | 检查 node_sequence 含子 Agent 推理步骤 |
| AC6 | P3 采集器从 ma_migration_audit 查询审计记录 | 检查 TrainingCase.metadata 含 entity_key |
| AC7 | P3 采集器 layer_tags 含 "DSH" | 检查 TrainingCase.layer_tags |
| AC8 | P3 node_sequence 长度 ≥4 节点 | 检查 dual_write/shadow_read 路径 |

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 20-数据清洗中心未运行，无 trace 日志 | 中 | P0 无法采集 | 手动触发清洗管道生成样本 trace |
| 18-dispatcher 补日志影响采集性能 | 低 | 18 性能下降 | stderr 输出异步，不阻塞主链路 |
| DSH 子 Agent reasoning_chain 为空 | 中 | P2 无数据 | 先检查 SubagentOutput.reasoning_chain 是否被填充 |
| 19-DAL ma_migration_audit 表为空 | 中 | P3 无数据 | 先运行 DualWrite 模式触发审计写入 |
| 19-DAL 深入调研后发现无调用日志 | — | — | ✅ 已调研：有 ma_migration_audit 审计表 |

---

## 8. 关联文档

- [SPEC-20261011 双模式学习训练架构](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/SPEC.md) — 上层 SPEC
- [SPEC-v0.5-continual-training](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/SPEC-v0.5-continual-training.md) — 持续训练机制
- [20-数据清洗中心 contract.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/20-数据清洗中心/data_cleaning/contract.py) — P0 契约
- [20-数据清洗中心 pipeline.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/20-数据清洗中心/data_cleaning/pipeline.py) — P0 管道
- [18-数据获取中心 dispatcher.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心/data_center/core/dispatcher.py) — P1 路由
- [DSH subagent_registry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/packages/python-server/subagent_registry.py) — P2 注册表
- [DSH subagent_types.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/packages/python-server/subagent_types.py) — P2 契约
- [19-DAL di.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/dreambuddy_dal/di.py) — P3 DI 路由 + DualWrite 代理
- [19-DAL gate_check.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/dreambuddy_dal/implementations/sqlite_unified/gate_check.py) — P3 门禁检查
- [19-DAL audit_summary.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/dreambuddy_dal/implementations/sqlite_unified/audit_summary.py) — P3 审计汇总
- [19-DAL README](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/README.md) — P3 架构概述

---

> **调研完成状态**: 19-DAL 已深入调研，价值从"待评估"修订为"极高"。核心发现：`ma_migration_audit` 审计表天然记录 DualWrite/shadow_read 调用链，不需要补日志。建议 P0 + P3 并行实施（两者都不需要补日志），然后 P1 → P2。
