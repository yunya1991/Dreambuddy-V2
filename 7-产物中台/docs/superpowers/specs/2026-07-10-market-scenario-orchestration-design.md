# 市场场景预编排与初始系统记忆设计

> 日期: 2026-07-10
> 状态: 待审核
> 关联模块: Dream OS (1-ARCHITECTURE/dreamos)、经典指标系统 (10-经典指标系统)、进化系统 (3-EVOLUTION)

## 1. 问题背景

当前 Dream OS 的图编排选择存在三个问题：

1. **随机选择**：`stress_test.py` 第98行用 `random.choice(graph_patterns)` 选择编排模式，完全无视市场场景。
2. **硬编码降级**：`auto_trader.py` 第158行降级路径固定使用 `["C1","C2","C3"]`，无场景适配。
3. **场景标签死数据**：压力测试生成的7种场景（bull_trend/crash/rally等）仅作报告元数据，不驱动编排也不生成模拟数据。

只有 TradingAgent 主路径通过 RuleBasedRecognizer 做到了基于真实指标的意图识别和链路映射，但这是隐式的、粒度粗的。

用户需求：**调研市场场景进行分类，通过回测预先形成最佳编排，形成初始系统记忆，避免随机的不可测。后期根据实际交易，通过进化系统进行优化。**

## 2. 设计目标

- **消除随机性**：编排选择由场景驱动，而非 `random.choice`
- **可解释**：每种场景的编排选择有回测数据支撑
- **冷启动可用**：首次回测即可生成初始记忆表，无需训练
- **渐进优化**：通过现有进化系统持续优化编排记忆
- **最小侵入**：复用已有节点能力（A6/C2/screen_engine），核心改动3个文件

## 3. 整体架构

### 两阶段设计

```
【初始化阶段 - 离线】
历史数据(243文件) → 场景切片 → 36场景×5模式回测 → 综合评分 → 编排记忆表(JSON)

【运行时阶段 - 在线】
A6节点识别场景 → 查记忆表选编排 → 三级降级 → GraphExecutor执行
→ 交易结果记录 → 进化引擎分析 → 周期性更新记忆表
```

### 数据流

```
                    ┌──────────────────────┐
                    │  历史数据文件 (243个)  │
                    │  JSON [ts,o,h,l,c,v]  │
                    └──────────┬───────────┘
                               ↓
                    ┌──────────────────────┐
                    │  ScenarioBacktester   │
                    │  滑动窗口切片+分类     │
                    │  36场景×5模式回测      │
                    └──────────┬───────────┘
                               ↓
                    ┌──────────────────────┐
                    │ OrchestrationMemory   │
                    │ orchestration_memory  │
                    │      .json            │
                    └──────────┬───────────┘
                               ↓
┌──────────────────┐    ┌──────┴───────────┐    ┌──────────────────┐
│ ScenarioClassifier│→→→│  AutoTrader       │→→→│  GraphExecutor   │
│ classify(mkt_data)│    │  select+execute   │    │  执行选定编排     │
└──────────────────┘    └──────┬───────────┘    └──────────────────┘
                               ↓
                    ┌──────────────────────┐
                    │  ExecutionFeedback    │
                    │  交易结果记录          │
                    └──────────┬───────────┘
                               ↓
                    ┌──────────────────────┐
                    │  EvolutionEngine      │
                    │  orchestration_       │
                    │  optimization 触发源  │
                    └──────────┬───────────┘
                               ↓
                    (周期性重回测 → 更新记忆表)
```

## 4. 市场场景分类器 (ScenarioClassifier)

### 三维分类

| 维度 | 取值 | 判定依据 | 数据源 |
|------|------|---------|--------|
| 趋势方向 | BULL / BEAR / NEUTRAL | EMA20/50/200排列 + ADX>25确认趋势 | A6节点 `_calculate_trend_score` (a6_regime_monitor.py 第86行) |
| 波动率等级 | LOW / NORMAL / HIGH / EXTREME | ATR%: <1% / 1-2% / 2-4% / >4% | A6节点 `_determine_volatility` (a6_regime_monitor.py 第111行) |
| 动量加速度 | ACCELERATING / DECELERATING / EXHAUSTION | 动量速度+加速度变化+衰竭检测 | C2节点动量 (c2_momentum.py) + screen_engine `_detect_exhaustion` (第310行) |

**总计：3 × 4 × 3 = 36种场景**

### 场景ID格式

`{TREND}_{VOLATILITY}_{MOMENTUM}`

示例：
- `BULL_NORMAL_ACCELERATING` — 正常波动上涨加速
- `BEAR_HIGH_EXHAUSTION` — 高波动下跌衰竭（可能见底）
- `NEUTRAL_LOW_DECELERATING` — 低波动横盘减速

### 动量加速度判定逻辑

复用 screen_engine.py 已有的三维动态指标计算（`_calc_indicator_dynamics` 第581行）和衰竭检测（`_detect_exhaustion` 第310行）：

- **ACCELERATING**：动量速度 > 50 且加速度 > 0
- **DECELERATING**：动量速度 > 30 但加速度 < 0（趋势仍在但减速）
- **EXHAUSTION**：触发衰竭信号（加速度转负 + 短期动量与中期背离）

### 三级降级策略

解决36场景中部分组合样本不足的问题：

| 级别 | 匹配方式 | 场景数 | 触发条件 |
|------|---------|--------|---------|
| L0 | 精确匹配全维度 | 36 | sample_count ≥ 10 且 confidence ≥ medium |
| L1 | 降维：趋势×波动率 | 12 | L0未命中，忽略动量加速度 |
| L2 | 降维：仅趋势方向 | 3 | L1未命中 |
| L3 | 默认 | 1 | L2未命中 → `c_chain` (C1→C2→C3) |

### 新增文件

`1-ARCHITECTURE/dreamos/core/sense/scenario_classifier.py`

```python
@dataclass
class ScenarioResult:
    scenario_id: str        # "BULL_NORMAL_ACCELERATING"
    trend: str              # "BULL"
    volatility: str         # "NORMAL"
    momentum: str           # "ACCELERATING"
    trend_score: float      # 0-1
    volatility_pct: float   # ATR%
    momentum_speed: float   # 0-100
    momentum_accel: float   # 有符号
    exhaustion: bool        # 是否衰竭

class ScenarioClassifier:
    def classify(self, market_data: dict) -> ScenarioResult:
        """输入行情数据，输出场景分类结果"""
        ...
```

## 5. 回测引擎 (ScenarioBacktester)

### 输入

- 243个历史数据文件（`10-经典指标系统/user_data/data/{aggregated,hyperliquid}/futures/`）
- JSON格式：`[ts, open, high, low, close, volume]`
- 5种编排模式（来自 stress_test.py 第90-96行）：
  - `c_chain`: ["C1", "C2", "C3"]
  - `c_f_chain`: ["C1", "C2", "F1", "F3"]
  - `full_chain`: ["C1", "C2", "F2", "G1"]
  - `f_chain`: ["F1", "F2", "F3", "F4"]
  - `c_g_chain`: ["C1", "C3", "G1"]

### 回测流程

1. **数据切片**：遍历历史数据文件，按滑动窗口切片
   - 窗口大小：24根K线（足够计算EMA20/50及动量）
   - 步长：6根K线（约25%重叠）
2. **场景分类**：每个窗口用 ScenarioClassifier 分类
3. **编排模拟**：对每个「场景×编排模式」组合：
   - 用窗口数据跑编排链（调用真实节点获取方向+置信度）
   - 方向为HOLD或置信度<0.45时跳过
   - 模拟开仓 → 持有N根K线（N=12） → 平仓
   - 记录每笔交易的收益、最大回撤
4. **评分计算**：聚合同场景所有交易结果，计算综合评分
5. **选优**：为每个场景选得分最高的编排模式

### 评分公式

```
Score = Sharpe×0.4 + Return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1
```

各指标归一化到 0-1：
- Sharpe：`(min(max(sharpe, -2), 3) + 2) / 5` → 映射 [-2,3] 到 [0,1]
- Return：`(min(max(return_pct, -0.5), 1.0) + 0.5) / 1.5` → 映射 [-0.5,1.0] 到 [0,1]
- MaxDD：`1 - min(max_dd, 1)` → 直接取补
- WinRate：直接使用 0-1

### 样本要求

- 最低样本数 ≥ 10 个交易窗口 → `sparse=false`
- 样本数 < 10 → `sparse=true`，运行时走降级
- confidence 分级：
  - `high`：sample_count ≥ 30 且 score ≥ 0.6
  - `medium`：sample_count ≥ 10 且 score ≥ 0.4
  - `low`：其他

### 新增文件

`1-ARCHITECTURE/dreamos/core/memory/scenario_backtester.py`

## 6. 编排记忆存储 (OrchestrationMemory)

### 存储位置

`1-ARCHITECTURE/dreamos/core/memory/orchestration_memory.json`

### JSON结构

```json
{
  "version": "1.0.0",
  "created_at": "2026-07-10T00:00:00Z",
  "last_backtest": "2026-07-10T00:00:00Z",
  "backtest_period": "2025-01-01_to_2026-06-30",
  "scenarios": {
    "BULL_NORMAL_ACCELERATING": {
      "best_pattern": "c_f_chain",
      "nodes": ["C1", "C2", "F1", "F3"],
      "score": 0.78,
      "metrics": {
        "sharpe": 1.2,
        "return": 0.15,
        "max_dd": 0.08,
        "win_rate": 0.6
      },
      "sample_count": 45,
      "confidence": "high",
      "sparse": false
    },
    "BEAR_HIGH_EXHAUSTION": {
      "best_pattern": "c_g_chain",
      "nodes": ["C1", "C3", "G1"],
      "score": 0.52,
      "metrics": {
        "sharpe": 0.6,
        "return": -0.02,
        "max_dd": 0.12,
        "win_rate": 0.4
      },
      "sample_count": 6,
      "confidence": "low",
      "sparse": true
    }
  },
  "fallback_chain": ["L0_exact", "L1_trend_vol", "L2_trend", "L3_default"],
  "default_pattern": "c_chain",
  "default_nodes": ["C1", "C2", "C3"]
}
```

### 查询方法

`OrchestrationMemory.select(scenario_id: str) -> OrchestrationChoice`

```python
@dataclass
class OrchestrationChoice:
    pattern: str           # "c_f_chain"
    nodes: list[str]       # ["C1", "C2", "F1", "F3"]
    score: float           # 0.78
    confidence: str        # "high"
    fallback_level: str    # "L0" / "L1" / "L2" / "L3"
    source_scenario: str   # 实际命中的场景ID（可能与输入不同）
```

查询逻辑：
1. **L0**：查 `scenarios[scenario_id]`，非sparse且confidence≥medium → 返回
2. **L1**：取趋势×波动率前缀（如 `BULL_NORMAL_*`），找非sparse场景 → 返回
3. **L2**：只按趋势前缀（如 `BULL_*`），找非sparse场景 → 返回
4. **L3**：返回 `default_pattern` (c_chain)

### 更新方法

- `update_from_backtest(results: dict)` — 回测引擎调用，批量更新
- `update_from_evolution(scenario_id, new_pattern, evidence)` — 进化引擎调用，单场景更新
- `save()` / `load()` — JSON文件读写

### 新增文件

`1-ARCHITECTURE/dreamos/core/memory/orchestration_memory.py`

## 7. 运行时集成

### 修改文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `dreamos/core/sense/scenario_classifier.py` | 新增 | 场景分类器 |
| `dreamos/core/memory/orchestration_memory.py` | 新增 | 编排记忆存储 |
| `dreamos/core/memory/scenario_backtester.py` | 新增 | 回测引擎 |
| `dreamos/core/memory/execution_feedback.py` | 新增 | 执行反馈记录 |
| `dreamos/cli/auto_trader.py` | 修改 | 集成场景识别+记忆查询 |
| `dreamos/cli/stress_test.py` | 修改 | 场景驱动替代random.choice |
| `dreamos/evolution/engine.py` | 修改 | 新增orchestration_optimization触发源 |
| `dreamos/cli/orchestration_commands.py` | 新增 | CLI命令（回测/查询/更新记忆表） |

### auto_trader.py 集成

```python
class AutoTrader:
    def __init__(self, ...):
        self.scenario_classifier = ScenarioClassifier()
        self.orchestration_memory = OrchestrationMemory()
        self.orchestration_memory.load()

    def run_full_analysis(self, symbol: str) -> Dict:
        market_data = self._fetch_market_data(symbol)

        # 新增：场景识别 + 编排选择
        scenario = self.scenario_classifier.classify(market_data)
        choice = self.orchestration_memory.select(scenario.scenario_id)

        # 主路径：将推荐编排传给TradingAgent
        if self.get_trading_agent():
            result = agent.run(
                user_input=f"分析 {symbol} 的交易机会",
                market_data=market_data,
                context={
                    "symbol": symbol,
                    "scenario": scenario.__dict__,
                    "recommended_orchestration": choice.__dict__,
                },
            )
            result["_path"] = "full_sacg"
            return result

        # 降级路径：用记忆表选编排，不再硬编码C链
        return self._fallback_classic_analysis(symbol, market_data, scenario, choice)

    def _fallback_classic_analysis(self, symbol, market_data, scenario, choice):
        # 用记忆表选的节点，替代原来的 ["C1", "C2", "C3"]
        chain_nodes = choice.nodes
        graph = SequentialGraph()
        for node_id in chain_nodes:
            node = registry.get(node_id)
            if node:
                graph.add_node(node)
        # ... 执行 + 决策逻辑（原有逻辑不变）
        result["_path"] = "classic_fallback"
        result["_scenario"] = scenario.scenario_id
        result["_orchestration"] = choice.pattern
        return result
```

### stress_test.py 修改

```python
def _test_graph_diversity(self, scenario: Dict) -> Dict:
    # 改为场景驱动选择，替代 random.choice
    market_data = self.trader._fetch_market_data(scenario["symbol"])
    classified = self.scenario_classifier.classify(market_data)
    choice = self.orchestration_memory.select(classified.scenario_id)

    graph = SequentialGraph()
    for node_id in choice.nodes:
        node = self.registry.get(node_id)
        if node:
            graph.add_node(node)
    # ... 执行逻辑不变
```

## 8. 进化闭环

### 新增触发源

在 `3-EVOLUTION/types.ts` 的 `EvolutionTriggerSource` 中新增 `orchestration_optimization`（第10种触发源）。

### 触发条件

| 条件 | 阈值 | 说明 |
|------|------|------|
| 方向准确率 | 连续3笔 < 50% | 编排方向判断不准 |
| 收益偏差 | |actual_sharpe - expected_sharpe| / expected > 30% | 实际表现与回测预期偏差大 |
| 定期审计 | 每月1次 | 全场景巡检 |

### 进化流程（复用现有EvolutionEngine 9阶段）

```
1. discovery（发现）
   - 收集场景交易记录（ExecutionFeedback）
   - 计算实际vs预期偏差

2. learning（学习）
   - 分析偏差原因：市场结构变化？编排不适配？节点失效？
   - 蒸馏教训（LessonDistiller）

3. deep_analysis（深度分析）
   - 生成编排调整提案：
     a) 切换到次优编排模式
     b) 调整节点组合（如增加G1风控节点）
     c) 新增细分场景

4. capability_update（能力更新）
   - 沙箱回测验证：用最近30天数据回测新提案
   - 通过条件：新提案评分 > 现有评分 × 1.1

5. code_development → approval → deployment
   - 审批通过后调用 OrchestrationMemory.update_from_evolution()
   - 更新 orchestration_memory.json
```

### 执行反馈数据结构

`dreamos/core/memory/execution_feedback.py`

```python
@dataclass
class ExecutionFeedback:
    scenario_id: str           # "BULL_NORMAL_ACCELERATING"
    pattern_used: str          # "c_f_chain"
    timestamp: str             # ISO格式
    trades: list[dict]         # 交易记录
    actual_sharpe: float       # 实际夏普
    expected_sharpe: float     # 回测预期夏普
    deviation: float           # 偏差比例
    trigger_evolution: bool    # 是否触发进化

class ExecutionFeedbackCollector:
    def record(self, scenario_id, pattern, trade_result): ...
    def evaluate(self, scenario_id) -> ExecutionFeedback: ...
    def should_trigger_evolution(self, feedback) -> bool: ...
```

### 进化引擎集成

在 `dreamos/evolution/engine.py` 的 `EvolutionEngine.evolve()` 中新增编排优化分支：

```python
def evolve(self, history, node_stats):
    # 原有逻辑...
    lessons = self.distiller.distill(history)

    # 新增：编排优化分支
    feedback = self.feedback_collector.evaluate(current_scenario)
    if feedback.trigger_evolution:
        proposals = self._generate_orchestration_proposals(feedback)
        for proposal in proposals:
            if self._sandbox_backtest(proposal):
                self.orchestration_memory.update_from_evolution(
                    proposal.scenario_id,
                    proposal.new_pattern,
                    evidence=proposal.evidence
                )

    return EvolutionReport(...)
```

## 9. CLI命令

新增 `dreamos/cli/orchestration_commands.py`：

```bash
# 运行回测，生成/更新编排记忆表
python3 -m dreamos.cli orchestration backtest --period 2025-01-01_2026-06-30

# 查看编排记忆表
python3 -m dreamos.cli orchestration memory list
python3 -m dreamos.cli orchestration memory show BULL_NORMAL_ACCELERATING

# 查询某场景的最优编排
python3 -m dreamos.cli orchestration query --scenario BULL_HIGH_EXHAUSTION

# 手动触发进化优化
python3 -m dreamos.cli orchestration evolve --scenario BULL_NORMAL_ACCELERATING

# 查看执行反馈统计
python3 -m dreamos.cli orchestration feedback --scenario BULL_NORMAL_ACCELERATING
```

## 10. 测试策略

### 单元测试

- `ScenarioClassifier`：验证36种场景的分类正确性，边界值测试
- `OrchestrationMemory`：验证三级降级查询逻辑，JSON读写
- `ScenarioBacktester`：验证评分公式计算，样本统计
- `ExecutionFeedback`：偏差计算，触发条件判定

### 集成测试

- 端到端流程：历史数据 → 回测 → 记忆表 → 运行时查询 → 编排执行
- 降级路径：sparse场景 → L1/L2/L3降级
- 进化闭环：反馈收集 → 进化触发 → 记忆更新

### 压力测试

- 500轮场景驱动编排测试（替代原random.choice）
- 验证36场景覆盖率
- 验证降级触发率在合理范围（<30%）

## 11. 实施顺序

1. **ScenarioClassifier** — 场景分类器（复用A6/C2/screen_engine）
2. **OrchestrationMemory** — 记忆表存储+查询（含降级逻辑）
3. **ScenarioBacktester** — 回测引擎（用243个数据文件生成初始记忆表）
4. **auto_trader.py 集成** — 运行时场景识别+记忆查询
5. **stress_test.py 修改** — 场景驱动替代random.choice
6. **ExecutionFeedback** — 执行反馈收集
7. **EvolutionEngine 集成** — 新增orchestration_optimization触发源
8. **CLI命令** — 回测/查询/进化操作

## 12. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 36场景中部分组合样本不足 | 三级降级策略（L0→L1→L2→L3） |
| 回测过拟合 | 沙箱验证要求新评分>现有×1.1；定期重回测 |
| 市场结构变化导致记忆表失效 | 进化闭环：偏差>30%自动触发优化 |
| 节点依赖外部API（F1新闻/F2资金流） | 回测时用fallback模式；运行时try-except |
| 冷启动期间无记忆表 | 默认使用 c_chain；首次回测后立即生成 |

## 13. 与现有系统的关系

| 现有系统 | 关系 |
|---------|------|
| TradingAgent 主路径（S-A-C-G） | 并行增强：场景识别结果作为context传入，推荐编排作为base_chain建议 |
| 降级路径（C链） | 核心改造：从硬编码C链改为记忆表驱动选择 |
| EvolutionEngine（9触发源） | 扩展：新增第10种触发源 orchestration_optimization |
| 知识库（2-KNOWLEDGE） | 可选：将编排记忆蒸馏为知识文档存入知识库 |
| 经典指标系统回测工具 | 复用：数据文件格式和部分回测逻辑 |
| A6节点（市场状态识别） | 复用：趋势得分和波动率分类 |
| C2节点（动量分析） | 复用：动量速度和加速度计算 |
| screen_engine.py（三屏系统） | 复用：衰竭检测逻辑（仅逻辑复用，不引入三屏系统依赖） |
