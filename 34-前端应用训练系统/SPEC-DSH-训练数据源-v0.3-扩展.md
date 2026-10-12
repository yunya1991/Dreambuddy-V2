# SPEC-20261012-DSH-v0.3 — DSH 层训练数据源扩展（子交易系统 + 逆向工程 + 大认知系统）

> **版本**: v0.3 (子交易系统+逆向工程+大认知系统扩展)
> **日期**: 2026-10-12
> **作者**: Trae + User
> **状态**: Draft（待评审）
> **关联**: SPEC-DSH-训练数据源.md (v0.2 已实现 4 采集器), SPEC-20261011 (双模式学习训练架构), SPL v0.4
> **方法论**: recall → 4 维并行调研 (polling_trader/认知闭环/BCRM-BDSM-战略层/REA-evolution) → SPEC v0.3
> **目标层**: DSH 层 (ExecutionPathTrainingLoop — 序列模式挖掘 + 路径模板)
> **v0.3 变更**:
> - 新增 5 个采集器（P0-P4），叠加子交易系统执行链 + 逆向工程深度数据 + 大认知系统推理链
> - v0.2 已实现 4 采集器（CleaningTrace/DalRoute/DataFetchRoute/DshSubagent）共 80 条 DSH 数据
> - v0.3 预期增量 +220-420 条，DSH 层总数据量 300-500 条
> - node_sequence 复杂度从平均 5 节点提升到 15-30 节点

---

## 0. Executive Summary

### 0.1 核心命题

v0.2 已实现 4 个 DSH 层采集器（CleaningTrace/DalRoute/DataFetchRoute/DshSubagent），验收产出 80 条 DSH 层训练数据。但这 80 条数据**以数据管道调用链为主**，缺少三个关键维度：

1. **交易决策执行链**（完全空白）—— BDSM/BCRM2.0/战略层/exit_engine/polling_trader 的完整交易环
2. **认知推理链**（完全空白）—— cognitive_memory.db 的 recall→record→verify 闭环链
3. **策略进化链**（完全空白）—— evolution 的 Shadow-RL + Bellman V(s) 回馈 + 迭代历史

用户评估指出：**DSH 的 Subagent 可以叠加各子交易系统 + 逆向工程 + 大认知系统，进行更复杂训练**。本 SPEC v0.3 定义 5 个新采集器填补上述三个空白维度。

| 优先级 | 数据源 | 数据域 | 现成度 | 预期序列长度 | 预期条数 |
|--------|--------|--------|--------|-------------|---------|
| **P0** | polling_trader 交易环 | 子交易系统 | ✅ 数据已有 | 8-12 节点 | 60-100 |
| **P1** | 认知闭环链 (recall→record→verify) | 大认知系统 | ✅ schema 已有 | 9-15 节点 | 40-80 |
| **P2** | BCRM/BDSM/战略层执行链 | 子交易系统 | 🟡 需拼接 | 15-25 节点 | 50-100 |
| **P3** | REA 深度报告 | 逆向工程 | ✅ 报告已有 | 8-12 节点 | 30-60 |
| **P4** | evolution 进化链 | 子交易系统+逆向 | 🟡 需映射 | 10-18 节点 | 40-80 |

**预期增量**: DSH 层从 80 条 → 300-500 条 (+220-420 条)  
**node_sequence 复杂度**: 平均 5 节点 → 15-30 节点  
**训练能力跃升维度**:
- 交易决策链：无 → 完整交易环（信号→评分→风控→下单→执行→出场）
- 跨子系统协同：无 → BCRM/BDSM/战略层调用序列
- 认知推理链：无 → recall→record→verify 闭环
- 策略进化链：无 → Shadow-RL→Bellman→迭代链
- 逆向推理：浅层 → 深层 locate→trace→reduce

### 0.2 设计驱动力

| 编号 | 驱动力 | 来源 |
|------|--------|------|
| F1 | v0.2 验收发现 DSH 层 80 条数据全是"数据管道调用链"，缺少"交易决策执行链" | v0.2 验收报告 |
| F2 | polling_trader 的 all_trades.jsonl 已有 37 万条交易记录，天然含交易环节点 | 代码调研 polling_trader.py L111-166 |
| F3 | cognitive_memory.db 的 memories 表 + cognitive_session.py 的 recall→record→verify 闭环是完整推理链 | 代码调研 cognitive_loop_entry.py L340-967 |
| F4 | BCRM2.0 的 ScoreComposer.compose() 是 6 节点合成链 + BDSM ExitManager 链式调用 + ShadowLogger 影子模式 | 代码调研 bcrm2/score_composer.py L98-172 + exit_manager.py L83-172 + shadow_logger.py L36-260 |
| F5 | REA 报告已有 locate→trace→reduce 四阶段逆向调查结构化输出 | 代码调研 run_self_evolution_audit.py L48-141 + reports/self_evolution_rea_report.json |
| F6 | evolution 的 shadow_validation 样本 + L1→L4 闭环 + Bellman V(s) 是策略迭代链 | 代码调研 evolution_pipeline.py L5-19 + shadow_validation/*.jsonl |
| F7 | 用户评估：DSH Subagent 叠加三大数据源域可进行更复杂训练 | User 评估确认 |

### 0.3 范围边界

**In Scope:**
- 定义 5 个新采集器的完整设计规格（P0-P4）
- 各采集器的数据源路径、字段映射、node_sequence 模板
- 采集器与 v0.2 已有采集器的协同关系
- 实施优先级和验收标准

**Out of Scope:**
- 不修改 `ExecutionPathTrainingLoop` 内部逻辑（只扩展数据源）
- 不修改 polling_trader.py / bcrm2/* / cognitive_loop_entry.py 核心逻辑
- 不修改 REA 报告生成逻辑和 evolution pipeline 核心逻辑
- 不新增日志输出点（P0/P1/P3/P4 全部消费已有数据，P2 从代码结构推断调用链）

---

## 1. 调研结论（事实清单）

### 1.1 DSH 层训练数据格式（已确认，同 v0.2）

**来源**: [run_continual_training.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/scripts/run_continual_training.py#L139-L140) L139-140

```python
elif layer == "DSH":
    return {"task": case.intent, "node_sequence": case.actions, "outcome": outcome}
```

- `task`: 任务标识（如 "trade_execution_bcrm2" / "cognitive_loop_verify"）
- `node_sequence`: 执行路径节点列表（`List[str]`，≥2 节点）
- `outcome`: 结果标识（success/failure/partial）

### 1.2 v0.2 已有采集器的 DSH 层覆盖度（基线）

**来源**: v0.2 验收报告 + [run_continual_training.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/scripts/run_continual_training.py#L95-L108) L95-108

| 采集器 | layer_tags | node_sequence 特征 | DSH 条数 | 节点长度 |
|--------|-----------|-------------------|---------|---------|
| CleaningTrace | ["DSH"] | 5-7 算子节点 | 6 | 5-7 |
| DalRoute | ["DSH"] | 5-6 DAL 路由节点 | 1 | 5-6 |
| DataFetchRoute | ["DSH"] | 4-6 获取链节点 | 5 | 4-6 |
| DshSubagent | ["DSH"] | 3-8 推理链节点 | 8 | 3-8 |
| **合计** | — | — | **80** | **平均 5** |

**覆盖特征**: 全部是"数据管道调用链"，**无交易决策链、无认知推理链、无策略进化链**。

### 1.3 P0 数据源：polling_trader 交易环（已确认 ✅）

**数据文件**:
- 主路径: [all_trades.jsonl](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl)
- 归档: `all_trades_archived_20260804.jsonl`
- 统一索引: [all_trades_index.jsonl](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.workbuddy/trade_index/all_trades_index.jsonl)

**交易记录字段** (来源: [trade_index_builder.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/trade_index_builder.py#L335-L346) L335-346):

```
trade_id / coin / inst_id / entry_price / exit_price / direction / pnl / pnl_pct / entry_time / exit_time
```

**Score_B 计算链路** (来源: [polling_trader.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py#L111-L166) L111-166):

```python
def compute_score_b_with_event_boost(continuity, confidence, event):
    # 1. baseline = continuity * confidence
    # 2. event_positive_strength = normalize(event)
    # 3. event_boost = clamp(event_strength, 0, 0.10)
    # 4. score_b_final = baseline + event_boost
    # 5. fail-open: 回退 baseline if event 缺失
    return score_b_final, event_boost_applied
```

**卦冲突乘数** (polling_trader.py L176-220): confidence 调整节点

**node_sequence 模板**:
```json
[
  "signal_scan",           // 信号扫描
  "score_b_baseline",      // Score_B baseline = continuity * confidence
  "event_boost_compute",   // event_boost = clamp(event_strength, 0, 0.10)
  "hex_conflict_adjust",   // 卦冲突乘数调整
  "score_b_final",         // 最终 Score_B
  "risk_check",            // 风控检查
  "order_place",           // 下单
  "fill_confirm",          // 成交确认
  "exit_scan",             // 出场扫描
  "exit_execute"           // 出场执行
]
```

**outcome 派生**:
- `success`: pnl_pct > 0 (盈利交易)
- `failure`: pnl_pct <= 0 (亏损交易)
- `partial`: pnl_pct == 0 或无 exit_price (平局/未平仓)

**采集可行性**: all_trades.jsonl 已有 37 万条交易记录，无需补日志。采集器直接读 jsonl，按交易方向/盈亏/币种采样。

### 1.4 P1 数据源：认知闭环链（已确认 ✅）

**数据库**: [cognitive_memory.db](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/data/cognitive_memory.db)

**memories 表 schema** (来源: [test_cognitive_memory_collector.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/tests/test_cognitive_memory_collector.py#L35-L57) L35-57):

```
id / content / vector / quality_level / confidence / tags / memory_type / 
source / created_at / updated_at / verify_count / level / known_gaps / observations
```

**recall 链路** (来源: [cognitive_loop_entry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_loop_entry.py#L340-L399) L340-399):

```python
def recall(context, top_k=5, min_quality="C"):
    # 1. 查 recall_cache
    # 2. 查 SQLite archival (WHERE quality_level >= min_quality)
    # 3. 按 score 降序排序
    # 4. 合并去重，取 top_k
    # 5. 返回 memories 列表
```

**record 链路** (来源: [cognitive_loop_entry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_loop_entry.py#L787-L865) L787-865):

```python
def record(content, quality_level, tags, ...):
    # 1. 写入 memories 表
    # 2. 生成 Evidence Ledger receipt
    # 3. 返回 memory_id
```

**verify 链路** (来源: [cognitive_loop_entry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_loop_entry.py#L871-L967) L871-967):

```python
def verify(memory_id, success):
    # 1. 贝叶斯置信度更新
    # 2. 计算新质量等级
    # 3. update_quality() + increment_verify()
    # 4. 可能触发蒸馏 → bayesian_memories.json
```

**事后校验闭环** (来源: [cognitive_session.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_session.py#L1445-L1488) L1445-1488):

```python
# recall 建议 vs 实际行为
if followed_advice and success:
    verify(memory_id, success=True)   # 建议有效，置信度升级
elif followed_advice and not success:
    verify(memory_id, success=False)  # 建议无效，置信度降级
```

**node_sequence 模板**:
```json
[
  "recall.query",           // recall(context, top_k, min_quality)
  "recall.cache_check",     // 查 recall_cache
  "recall.db_query",        // 查 SQLite archival
  "recall.rank_by_score",   // 按 score 降序
  "recall.merge_dedup",     // 合并去重取 top_k
  "action.execute",         // 执行动作（编码/调试/分析）
  "outcome.observe",        // 观察结果
  "record.write",           // record() 写入 memories
  "record.ledger",          // 生成 Evidence Ledger receipt
  "verify.bayesian_update", // verify() 贝叶斯更新
  "verify.quality_update",  // update_quality + increment_verify
  "verify.distill_check"    // 可能触发蒸馏
]
```

**outcome 派生**:
- `success`: verify_count > 0 且 confidence >= 0.7
- `failure`: quality_level == "D" (已证伪)
- `partial`: quality_level in ("B","C") 且 verify_count == 0

**采集可行性**: memories 表已有数据，cognitive_session.py 已记录 recall→record→verify 闭环。采集器查询 `verify_count > 0` 的高质量记忆，重构闭环序列。预期 40-80 条（B 级以上 + verify_count > 0）。

### 1.5 P2 数据源：BCRM/BDSM/战略层执行链（需拼接 🟡）

**核心代码路径**: [11-易经推理系统/scripts/memory_l4/bcrm2/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/)

#### 1.5.1 BCRM 2.0 Score_B 合成链

**来源**: [score_composer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/score_composer.py#L98-L172) L98-172

```python
def compose(self, ohlcv):
    # 1. 读取 OHLCV
    # 2. 加权归一化 (level/trend 双维度)
    # 3. 9 格扩展 (9-grid expansion)
    # 4. clamp (钳制极端值)
    # 5. 每日平滑 (daily smoothing)
    # 6. Sperandeo 调整 (市场阶段调整)
    return composed_score
```

**BCRM node_sequence**:
```json
[
  "bcrm.ohlcv_fetch",
  "bcrm.score_composer.normalize",
  "bcrm.score_composer.expand9",
  "bcrm.score_composer.clamp",
  "bcrm.score_composer.smooth",
  "bcrm.score_composer.sperandeo",
  "bcrm.score_b_baseline",
  "bcrm.event_boost_compute",
  "bcrm.hex_conflict_adjust",
  "bcrm.dialectical_ml_map",   // 64卦映射 (dialectical_ml_engine.py L184-260)
  "bcrm.score_b_final",
  "bcrm.gate_decision"
]
```

#### 1.5.2 BDSM 出场巡检链

**来源**: [exit_manager.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/exit_manager.py#L83-L172) L83-172

```python
def evaluate(self, position):
    for strategy in self.strategies:  # 按优先级排序
        decision = strategy.evaluate(position)
        if decision != "pass":
            return decision  # 返回首个非 pass 离场决策
    return "hold"
```

**BDSM node_sequence**:
```json
[
  "bdsm.position_check",
  "bdsm.exit_manager.evaluate",
  "bdsm.strategy_1.evaluate",    // 止损策略
  "bdsm.strategy_2.evaluate",    // 移动止盈
  "bdsm.strategy_3.evaluate",    // 时间止损
  "bdsm.strategy_4.evaluate",    // 信号反转
  "bdsm.strategy_5.evaluate",    // 波动率异常
  "bdsm.exit_decision",
  "bdsm.exit_execute"
]
```

#### 1.5.3 战略层影子模式链

**来源**: [shadow_logger.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/shadow_logger.py#L36-L260) L36-260

```python
def record_polling(self, inference):
    # 1. 提取 level_smooth/trend_smooth/consensus/regime
    # 2. 计算 baseline / AI-injected / effective
    # 3. 记录 FMA
    # 4. 记录战略层 war_state / total_score / 五维评分
    # 5. 不改变交易参数（影子模式）
```

**战略层 node_sequence**:
```json
[
  "strategy.shadow_record",
  "strategy.extract_level_smooth",
  "strategy.extract_trend_smooth",
  "strategy.extract_consensus",
  "strategy.extract_regime",
  "strategy.compute_baseline",
  "strategy.compute_ai_injected",
  "strategy.compute_effective",
  "strategy.record_fma",
  "strategy.extract_war_state",
  "strategy.extract_total_score",
  "strategy.five_dim_score",
  "strategy.compare_baseline_vs_effective",
  "strategy.log_shadow"
]
```

**P2 综合拼接策略**: 采集器不调用实际代码，而是**从代码结构推断调用链模板**，生成多个变体（不同策略组合、不同市场状态）。每条 TrainingCase 的 `actions` = 上述 node_sequence 之一，`intent` = 子系统名（"bcrm2_score_compose" / "bdsm_exit_patrol" / "strategy_shadow"）。

**采集可行性**: 不需要补日志，从代码结构静态推断。预期 50-100 条（3 个子系统 × 15-30 变体）。

### 1.6 P3 数据源：REA 深度报告（已确认 ✅）

**报告路径**: [self_evolution_rea_report.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程/reports/self_evolution_rea_report.json)

**报告生成入口** (来源: [run_self_evolution_audit.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程/run_self_evolution_audit.py#L48-L141) L48-141):

```python
def run_pipeline_investigate():
    # 四阶段逆向调查:
    # 1. locate (定位代码位置)
    # 2. trace (追踪调用链)
    # 3. reduce (还原算法逻辑)
    # 4. evidence_collect (收集证据)
    return {"summary": ..., "phases": [...], "evidence": [...]}

def main():
    report = {
        "pipeline_investigate": run_pipeline_investigate(),
        "engines_dependency": analyze_engines_dependency(),
        "key_engine_algorithms": analyze_key_algorithms(),
        "git_history": analyze_git_history()
    }
    write_to("reports/self_evolution_rea_report.json")
```

**报告字段结构** (来自 self_evolution_rea_report.json 样本):
- `pipeline_investigate.summary`: 定位/追踪/还原/证据数量
- `pipeline_investigate.phases`: 四阶段详细数据
- `pipeline_investigate.trace`: locate→trace→reduce 调用链
- `engines_dependency`: 引擎依赖图
- `key_engine_algorithms`: 关键引擎算法还原
- `git_history`: Git 历史分析

**演化叙事** (来源: [evolution_narrative.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程/core/evolution_narrative.py#L106-L128) L106-128):
- `turning_points`: 转折点
- `tech_debt_timeline`: 技术债时间线
- `evidence`: 证据链

**node_sequence 模板**:
```json
[
  "rea.locate",              // 定位代码位置
  "rea.trace",                // 追踪调用链
  "rea.reduce",               // 还原算法逻辑
  "rea.evidence_collect",     // 收集证据
  "rea.engines_dependency",   // 引擎依赖分析
  "rea.key_algorithms",       // 关键算法还原
  "rea.git_history",          // Git 历史分析
  "rea.turning_points",       // 转折点识别
  "rea.tech_debt_timeline",   // 技术债时间线
  "rea.narrative_generate",   // 演化叙事生成
  "rea.report_write"          // 报告写入
]
```

**outcome 派生**:
- `success`: report 包含 evidence 且 evidence_count > 0
- `partial`: report 存在但 evidence 为空
- `failure`: 报告生成失败

**采集可行性**: reports/ 目录已有 JSON 报告，采集器解析 JSON 提取 phases + evidence。预期 30-60 条（每份报告拆分为多个阶段样本）。

### 1.7 P4 数据源：evolution 进化链（需映射 🟡）

**核心代码**: [evolution_pipeline.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py#L5-L19) L5-19

```python
# L1→L4 闭环:
# L1: 路径发现 (path discovery)
# L2: 统计验证 (statistical validation)
# L3: Shadow-RL (影子强化学习)
# L4: Bellman V(s) 回馈与进化寻优
```

**shadow_validation 样本路径**: [gene_data/shadow_validation/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data/shadow_validation/)

**样本格式** (来自 CD-DONCHIAN-20-BREAK_samples.jsonl):

```json
{
  "entry_time": "...",
  "exit_time": "...",
  "entry_price": 45000,
  "exit_price": 46000,
  "pnl_pct": 0.022,
  "win": true,
  "hold_bars": 12,
  "gene_id": "CD-DONCHIAN-20-BREAK",
  "direction": "LONG"
}
```

**node_sequence 模板**:
```json
[
  "evo.shadow_sample_load",    // 加载 shadow_validation 样本
  "evo.trade_index_query",     // 查询交易索引
  "evo.entry_match",          // 匹配入场
  "evo.exit_match",            // 匹配出场
  "evo.pnl_compute",          // 计算 PnL
  "evo.win_classify",          // 胜负分类
  "evo.gene_evaluate",         // 基因评估
  "evo.statistical_validate",  // L2 统计验证
  "evo.shadow_rl_update",      // L3 Shadow-RL 更新
  "evo.bellman_vs_update",     // L4 Bellman V(s) 更新
  "evo.evolution_iteration",   // 进化迭代
  "evo.gene_pool_update"       // 基因池更新
]
```

**outcome 派生**:
- `success`: win == true 且 pnl_pct > 0
- `failure`: win == false 且 pnl_pct <= 0
- `partial`: hold_bars == 0 或 pnl_pct == 0

**采集可行性**: shadow_validation/ 已有多个基因样本文件（CD-DONCHIAN-20-BREAK 等），采集器解析 jsonl。预期 40-80 条（每个 gene_id 拆分多个样本）。

---

## 2. 采集器设计

### 2.1 采集器清单

| 编号 | 采集器名 | 文件路径 | 数据源 | layer_tags | quality |
|------|---------|---------|--------|-----------|---------|
| P0 | `PollingTraderCollector` | `adapters/polling_trader_collector.py` | all_trades.jsonl | ["DSH"] | B |
| P1 | `CognitiveLoopCollector` | `adapters/cognitive_loop_collector.py` | cognitive_memory.db | ["DSH","C"] | A |
| P2 | `SubTradeChainCollector` | `adapters/sub_trade_chain_collector.py` | bcrm2/* 代码结构 | ["DSH"] | B |
| P3 | `ReaReportCollector` | `adapters/rea_report_collector.py` | reports/*.json | ["DSH","G"] | A |
| P4 | `EvolutionChainCollector` | `adapters/evolution_chain_collector.py` | shadow_validation/*.jsonl | ["DSH"] | B |

### 2.2 共享接口（同 v0.2）

所有采集器实现 `TrainingDataProvider` 接口:

```python
class TrainingDataProvider(ABC):
    def get_source_name(self) -> str: ...
    def get_quality_threshold(self) -> str: ...
    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]: ...
```

`TrainingCase` 字段映射:

| TrainingCase 字段 | P0 polling_trader | P1 认知闭环 | P2 子交易链 | P3 REA | P4 evolution |
|------------------|-------------------|------------|------------|--------|--------------|
| `intent` | `trade_{direction}` | `cognitive_loop` | `{subsystem}_chain` | `rea_audit` | `evo_{gene_id}` |
| `actions` | 交易环 10 节点 | 闭环 12 节点 | 子系统 12-14 节点 | 逆向 11 节点 | 进化 12 节点 |
| `outcome_text` | `pnl={pnl_pct}` | `verify_count={n}` | `{subsystem}_executed` | `evidence={n}` | `win={bool}` |
| `learned` | 方向+币种 | content 摘要 | 子系统名 | 报告摘要 | gene_id+direction |
| `layer_tags` | ["DSH"] | ["DSH","C"] | ["DSH"] | ["DSH","G"] | ["DSH"] |
| `quality` | B | A | B | A | B |

### 2.3 P0: PollingTraderCollector 实现规格

```python
class PollingTraderCollector(TrainingDataProvider):
    """polling_trader 交易环采集器 — 从 all_trades.jsonl 提取交易决策执行链。

    每条交易记录 → TrainingCase:
    - intent = f"trade_{direction}" (如 "trade_LONG" / "trade_SHORT")
    - actions = 交易环 10 节点序列 (signal_scan → ... → exit_execute)
    - outcome_text = f"pnl={pnl_pct}"
    - quality = "B"
    """

    TRADES_PATH = "11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl"
    INDEX_PATH = ".workbuddy/trade_index/all_trades_index.jsonl"

    def fetch_cases(self, limit=100, since=None):
        # 1. 读 all_trades.jsonl (或 all_trades_index.jsonl)
        # 2. 按 direction 盈亏均衡采样 (limit//2 LONG + limit//2 SHORT)
        # 3. 每条交易 → TrainingCase
        # 4. node_sequence 根据方向/盈亏微调 (盈利+出场节点 vs 亏损+止损节点)
```

### 2.4 P1: CognitiveLoopCollector 实现规格

```python
class CognitiveLoopCollector(TrainingDataProvider):
    """认知闭环链采集器 — 从 cognitive_memory.db 提取 recall→record→verify 序列。

    每条 verify_count>0 的记忆 → TrainingCase:
    - intent = "cognitive_loop"
    - actions = 闭环 12 节点序列
    - outcome_text = f"verify_count={verify_count}"
    - quality = quality_level (A/B)
    """

    DB_PATH = "4-MEMORY/data/cognitive_memory.db"

    def fetch_cases(self, limit=100, since=None):
        # 1. 查 memories 表 WHERE verify_count > 0 AND quality_level IN ('A','B')
        # 2. 每条记忆 → TrainingCase
        # 3. node_sequence 根据 verify_count/quality_level 微调
        #    (verify_count>3 → 含 distill_check 节点; quality_level=D → 含 falsify 节点)
```

### 2.5 P2: SubTradeChainCollector 实现规格

```python
class SubTradeChainCollector(TrainingDataProvider):
    """子交易系统执行链采集器 — 从 BCRM/BDSM/战略层代码结构推断调用链。

    3 个子系统 × 多变体 → TrainingCase:
    - BCRM: Score_B 合成链 (12 节点)
    - BDSM: 出场巡检链 (9 节点)
    - 战略层: 影子模式链 (14 节点)
    """

    SUBSYSTEMS = ["bcrm2", "bdsm", "strategy"]

    def fetch_cases(self, limit=100, since=None):
        # 1. 每个子系统有预定义 node_sequence 模板
        # 2. 生成变体 (市场状态/策略组合/置信度高低)
        # 3. 每个变体 → TrainingCase
        # 4. intent = f"{subsystem}_chain"
```

### 2.6 P3: ReaReportCollector 实现规格

```python
class ReaReportCollector(TrainingDataProvider):
    """REA 深度报告采集器 — 从 reports/*.json 提取 locate→trace→reduce 序列。

    每份报告 → 多个 TrainingCase (按 phase 拆分):
    - 整体报告 → 1 条完整 11 节点序列
    - 每个 phase → 1 条子序列
    """

    REPORTS_DIR = "33-REA逆向解析工程/reports"

    def fetch_cases(self, limit=100, since=None):
        # 1. 遍历 reports/*.json
        # 2. 解析 pipeline_investigate.phases
        # 3. 整体报告 → 1 条完整序列
        # 4. 每个 phase → 1 条子序列
        # 5. intent = "rea_audit"
```

### 2.7 P4: EvolutionChainCollector 实现规格

```python
class EvolutionChainCollector(TrainingDataProvider):
    """evolution 进化链采集器 — 从 shadow_validation/*.jsonl 提取进化迭代序列。

    每个基因样本 → TrainingCase:
    - intent = f"evo_{gene_id}"
    - actions = 进化 12 节点序列
    - outcome_text = f"win={win}"
    """

    SHADOW_DIR = "23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data/shadow_validation"

    def fetch_cases(self, limit=100, since=None):
        # 1. 遍历 shadow_validation/*.jsonl
        # 2. 每行样本 → TrainingCase
        # 3. node_sequence 根据 win/loss 微调
        #    (win → 含 bellman_vs_update 节点; loss → 含 gene_penalty 节点)
```

---

## 3. 实施计划

### 3.1 实施优先级

| 阶段 | 采集器 | 理由 | 预期条数 |
|------|--------|------|---------|
| **Phase 1** | P0 + P3 | 数据已有，实现最快 | 90-160 |
| **Phase 2** | P1 + P4 | 数据已有，需 schema 映射 | 80-160 |
| **Phase 3** | P2 | 需从代码结构推断模板 | 50-100 |

### 3.2 实施步骤（每阶段）

1. 创建采集器文件 `adapters/{name}_collector.py`
2. 实现 `fetch_cases()` 方法
3. 在 [run_continual_training.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/scripts/run_continual_training.py#L95-L108) L95-108 注册采集器
4. 运行 `python scripts/run_continual_training.py --limit 100`
5. 验证 DSH 层 step 增长 + bufferStats

### 3.3 验收标准

| 验收项 | 目标 | 验证方法 |
|--------|------|---------|
| 采集器实现 | 5 个采集器全绿 | run_continual_training.py 输出 |
| DSH 层总条数 | >= 300 | 5 层快照 DSH bucketCount |
| node_sequence 平均长度 | >= 10 | 抽样检查 actions 列表长度 |
| DSH 层 step 增长 | >= +3 | before/after step 对比 |
| 覆盖维度 | 5 维全覆盖 | 交易环+认知闭环+子交易链+REA+进化链 |

---

## 4. 与 v0.2 的协同关系

### 4.1 数据互补

| 维度 | v0.2 覆盖 | v0.3 补充 |
|------|----------|----------|
| 数据管道调用链 | CleaningTrace/DalRoute/DataFetchRoute/DshSubagent (80条) | — |
| 交易决策执行链 | — | P0 polling_trader + P2 子交易链 |
| 认知推理链 | — | P1 认知闭环 |
| 逆向推理链 | — | P3 REA 报告 |
| 策略进化链 | — | P4 evolution |

### 4.2 层标签协同

| 采集器 | layer_tags | 协同说明 |
|--------|-----------|---------|
| P0 polling_trader | ["DSH"] | 纯 DSH 层，交易执行路径 |
| P1 认知闭环 | ["DSH","C"] | DSH+C 双层，推理链也服务 C 层反思 |
| P2 子交易链 | ["DSH"] | 纯 DSH 层，子系统调用序列 |
| P3 REA 报告 | ["DSH","G"] | DSH+G 双层，逆向结构也服务 G 层图映射 |
| P4 evolution | ["DSH"] | 纯 DSH 层，进化迭代路径 |

---

## 5. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| P2 子交易链从代码推断，可能与实际运行不一致 | 中 | 标注 quality="B"，后续可通过补日志升级 |
| all_trades.jsonl 37 万条，采样不均 | 低 | 按 direction 盈亏均衡采样 |
| cognitive_memory.db 记忆数少于预期 | 低 | 放宽到 quality_level IN ('A','B','C') |
| shadow_validation 文件数少于预期 | 中 | P4 可扩展到 gene_data/ 其他子目录 |
| node_sequence 模板过于静态 | 中 | 根据交易方向/盈亏/verify_count 等微调变体 |

---

## 6. 后续展望

- **v0.4**: 补日志后 P2 升级为动态采集（从实际运行日志提取调用链）
- **v0.5**: 跨采集器拼接（如 polling_trader 交易环 + BCRM Score_B 合成链 = 20+ 节点超长序列）
- **v0.6**: DSH 层训练效果评估（node_sequence 模式挖掘命中率）

---

**文档结束**
