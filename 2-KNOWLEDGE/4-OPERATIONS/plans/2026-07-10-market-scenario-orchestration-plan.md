# 实施计划：市场场景预编排与初始系统记忆

> 设计文档: `docs/superpowers/specs/2026-07-10-market-scenario-orchestration-design.md`
> 日期: 2026-07-10

## 概要

8个实施步骤，按依赖顺序排列。每步包含：文件路径、函数签名、关键逻辑、验证方法。

---

## 步骤1：ScenarioClassifier — 场景分类器

**目标：** 输入行情数据，输出36种场景之一的分类结果

**新建文件：** `1-ARCHITECTURE/dreamos/core/sense/scenario_classifier.py`

**数据结构：**
```python
@dataclass
class ScenarioResult:
    scenario_id: str        # "BULL_NORMAL_ACCELERATING"
    trend: str              # "BULL" / "BEAR" / "NEUTRAL"
    volatility: str         # "LOW" / "NORMAL" / "HIGH" / "EXTREME"
    momentum: str           # "ACCELERATING" / "DECELERATING" / "EXHAUSTION"
    trend_score: float      # 0-1
    volatility_pct: float   # ATR%
    momentum_speed: float   # 0-100
    momentum_accel: float   # 有符号
    exhaustion: bool
```

**核心方法：**
```python
class ScenarioClassifier:
    # 复用A6节点阈值（a6_regime_monitor.py 第28-37行）
    VOLATILITY_THRESHOLDS = {"EXTREME": 0.04, "HIGH": 0.02, "NORMAL": 0.01}

    def classify(self, market_data: dict) -> ScenarioResult:
        trend = self._classify_trend(market_data)
        volatility = self._classify_volatility(market_data)
        momentum = self._classify_momentum(market_data)
        scenario_id = f"{trend}_{volatility}_{momentum}"
        return ScenarioResult(scenario_id, trend, volatility, momentum, ...)

    def _classify_trend(self, mkt: dict) -> str:
        """复用A6 _calculate_trend_score逻辑（a6_regime_monitor.py 第86行）
        BULL: price>ema20>ema50>ema200 且 trend_score>=0.6
        BEAR: price<ema20<ema50<ema200 且 trend_score>=0.6
        NEUTRAL: 其他
        """

    def _classify_volatility(self, mkt: dict) -> str:
        """复用A6 _determine_volatility逻辑（a6_regime_monitor.py 第111行）
        EXTREME: atr_pct>=0.04, HIGH: >=0.02, NORMAL: >=0.01, LOW: <0.01
        """

    def _classify_momentum(self, mkt: dict) -> str:
        """复用C2动量计算 + screen_engine衰竭检测逻辑
        ACCELERATING: speed>50 且 accel>0
        DECELERATING: speed>30 且 accel<0
        EXHAUSTION: 衰竭信号(加速度转负 + 短期与中期动量背离)
        """
```

**关键实现细节：**
- 趋势判定：直接复用A6的EMA排列逻辑，不依赖ADX（market_data中可能没有ADX）
- 动量速度计算：`(change_24h*0.5 + change_4h*0.3 + change_1h*0.2)` 归一化到0-100
- 动量加速度：`当前速度 - 前一窗口速度`（需要至少2个时间点的数据，回测时有窗口数据，运行时用change_1h vs change_4h近似）
- 衰竭检测：复用screen_engine `_detect_exhaustion`（第310行）的核心逻辑：加速度转负 + 短期动量与中期背离

**验证方法：**
```bash
python3 -c "
from dreamos.core.sense.scenario_classifier import ScenarioClassifier
c = ScenarioClassifier()
# 模拟牛市加速场景
mkt = {'price':100, 'ema20':95, 'ema50':90, 'ema200':80, 'change_24h':5, 'change_4h':2, 'change_1h':0.5, 'atr_pct':0.015}
r = c.classify(mkt)
assert r.trend == 'BULL', f'Expected BULL, got {r.trend}'
assert r.volatility == 'NORMAL', f'Expected NORMAL, got {r.volatility}'
print(f'Scenario: {r.scenario_id}')  # BULL_NORMAL_ACCELERATING
"
```

**依赖：** 无（首个模块）

---

## 步骤2：OrchestrationMemory — 编排记忆存储

**目标：** JSON记忆表的读写 + 三级降级查询

**新建文件：** `1-ARCHITECTURE/dreamos/core/memory/orchestration_memory.py`
**新建目录：** `1-ARCHITECTURE/dreamos/core/memory/`（需创建 `__init__.py`）
**数据文件：** `1-ARCHITECTURE/dreamos/core/memory/orchestration_memory.json`（首次运行回测时生成）

**数据结构：**
```python
@dataclass
class OrchestrationChoice:
    pattern: str           # "c_f_chain"
    nodes: list            # ["C1", "C2", "F1", "F3"]
    score: float           # 0.78
    confidence: str        # "high" / "medium" / "low"
    fallback_level: str    # "L0" / "L1" / "L2" / "L3"
    source_scenario: str   # 实际命中的场景ID
```

**核心方法：**
```python
class OrchestrationMemory:
    def __init__(self, path: str = None):
        # 默认路径: core/memory/orchestration_memory.json
        self.path = path or self._default_path()
        self._data = self._empty_structure()

    def load(self) -> bool:
        """加载JSON，不存在则返回False"""

    def save(self) -> None:
        """写入JSON"""

    def select(self, scenario_id: str) -> OrchestrationChoice:
        """三级降级查询"""
        # L0: 精确匹配 scenarios[scenario_id]，非sparse且confidence>=medium
        # L1: 降维 趋势_波动率_* 模糊匹配
        # L2: 降维 趋势_* 模糊匹配
        # L3: 默认 c_chain

    def update_from_backtest(self, results: dict) -> None:
        """回测结果批量更新"""

    def update_from_evolution(self, scenario_id: str, new_pattern: str,
                              nodes: list, score: float, evidence: dict) -> None:
        """进化引擎单场景更新"""

    def get_stats(self) -> dict:
        """统计：场景覆盖率、降级率等"""
```

**三级降级查询逻辑：**
```python
def select(self, scenario_id: str) -> OrchestrationChoice:
    parts = scenario_id.split("_")  # ["BULL", "NORMAL", "ACCELERATING"]

    # L0: 精确匹配
    entry = self._data["scenarios"].get(scenario_id)
    if entry and not entry.get("sparse", True) and entry.get("confidence") in ("high", "medium"):
        return OrchestrationChoice(..., fallback_level="L0")

    # L1: 趋势×波动率 (前两段)
    if len(parts) >= 2:
        prefix = f"{parts[0]}_{parts[1]}_"
        for sid, entry in self._data["scenarios"].items():
            if sid.startswith(prefix) and not entry.get("sparse", True):
                return OrchestrationChoice(..., fallback_level="L1", source_scenario=sid)

    # L2: 仅趋势 (第一段)
    prefix = f"{parts[0]}_"
    for sid, entry in self._data["scenarios"].items():
        if sid.startswith(prefix) and not entry.get("sparse", True):
            return OrchestrationChoice(..., fallback_level="L2", source_scenario=sid)

    # L3: 默认
    return OrchestrationChoice(
        pattern="c_chain", nodes=["C1","C2","C3"],
        score=0, confidence="default", fallback_level="L3", source_scenario="DEFAULT"
    )
```

**验证方法：**
```bash
python3 -c "
from dreamos.core.memory.orchestration_memory import OrchestrationMemory
m = OrchestrationMemory()
# 空记忆表查询应走L3默认
c = m.select('BULL_NORMAL_ACCELERATING')
assert c.fallback_level == 'L3', f'Expected L3, got {c.fallback_level}'
assert c.pattern == 'c_chain'
print('OK: empty memory → L3 default')
"
```

**依赖：** 无

---

## 步骤3：ScenarioBacktester — 回测引擎

**目标：** 用243个历史数据文件生成初始编排记忆表

**新建文件：** `1-ARCHITECTURE/dreamos/core/memory/scenario_backtester.py`

**核心方法：**
```python
class ScenarioBacktester:
    GRAPH_PATTERNS = {
        "c_chain":     ["C1", "C2", "C3"],
        "c_f_chain":   ["C1", "C2", "F1", "F3"],
        "full_chain":  ["C1", "C2", "F2", "G1"],
        "f_chain":     ["F1", "F2", "F3", "F4"],
        "c_g_chain":   ["C1", "C3", "G1"],
    }

    def __init__(self, data_dir: str = None):
        # 默认: 10-经典指标系统/user_data/data/
        self.classifier = ScenarioClassifier()
        self.registry = get_default_registry()
        register_all(self.registry)

    def run(self, window_size: int = 24, step: int = 6, hold_periods: int = 12) -> dict:
        """完整回测，返回 {scenario_id: {pattern: metrics}}"""

    def _load_data_files(self) -> list:
        """扫描 data_dir 下所有 JSON文件"""

    def _process_window(self, window_data: list, symbol: str) -> dict:
        """处理单个窗口：分类场景 + 对5种模式跑编排"""

    def _simulate_trade(self, nodes: list, market_data: dict, future_prices: list) -> dict:
        """模拟单笔交易：跑编排链→开仓→持有→平仓"""

    def _calc_score(self, trades: list) -> dict:
        """计算综合评分: Sharpe×0.4 + Return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1"""

    def _normalize_sharpe(self, sharpe: float) -> float:
        """(min(max(sharpe, -2), 3) + 2) / 5"""

    def _normalize_return(self, ret: float) -> float:
        """(min(max(ret, -0.5), 1.0) + 0.5) / 1.5"""
```

**关键实现细节：**
- 数据文件路径：`10-经典指标系统/user_data/data/{aggregated,hyperliquid}/futures/`
- 数据格式：JSON数组 `[ts, open, high, low, close, volume]`
- 窗口切片：每24根K线一个窗口，步长6
- 编排模拟：用窗口数据构造 `market_data` dict（需从K线计算ema/rsi/atr等），调用真实节点获取方向
- 交易模拟：方向非HOLD且置信度≥0.45时开仓，持有12根K线后用收盘价平仓
- 评分聚合：同场景同模式的所有交易结果聚合后计算夏普/收益/回撤/胜率

**market_data 构造逻辑（从K线窗口计算）：**
```python
def _build_market_data(self, window: list, symbol: str) -> dict:
    closes = [k[4] for k in window]
    highs = [k[2] for k in window]
    lows = [k[3] for k in window]
    volumes = [k[5] for k in window]
    price = closes[-1]
    return {
        "symbol": symbol,
        "price": price,
        "ema20": self._ema(closes, 20),
        "ema50": self._ema(closes, 50),
        "ema200": self._ema(closes, min(200, len(closes))),
        "change_1h": (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) > 1 else 0,
        "change_4h": (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) > 4 else 0,
        "change_24h": (closes[-1] - closes[-24]) / closes[-24] * 100 if len(closes) > 23 else 0,
        "atr_pct": self._atr_pct(highs, lows, closes, 14),
        "rsi14": self._rsi(closes, 14),
        "macd": self._macd(closes),
        "macd_signal": self._macd_signal(closes),
        "macd_hist": self._macd_hist(closes),
        "vol_ratio": volumes[-1] / (sum(volumes[-20:]) / 20) if len(volumes) >= 20 else 1.0,
    }
```

**输出到OrchestrationMemory：**
```python
def run(self, ...) -> dict:
    results = {}  # {scenario_id: {pattern: {sharpe, return, max_dd, win_rate, trades}}}
    for file_path in self._load_data_files():
        data = self._load_json(file_path)
        symbol = self._extract_symbol(file_path)
        for i in range(0, len(data) - window_size - hold_periods, step):
            window = data[i:i+window_size]
            future = data[i+window_size:i+window_size+hold_periods]
            market_data = self._build_market_data(window, symbol)
            scenario = self.classifier.classify(market_data)
            for pattern_name, nodes in self.GRAPH_PATTERNS.items():
                trade = self._simulate_trade(nodes, market_data, future)
                # 累积到 results[scenario.scenario_id][pattern_name]
    # 评分选优
    return self._select_best(results)
```

**验证方法：**
```bash
python3 -c "
from dreamos.core.memory.scenario_backtester import ScenarioBacktester
from dreamos.core.memory.orchestration_memory import OrchestrationMemory
bt = ScenarioBacktester()
results = bt.run(window_size=24, step=6, hold_periods=12)
mem = OrchestrationMemory()
mem.update_from_backtest(results)
mem.save()
stats = mem.get_stats()
print(f'场景覆盖: {stats[\"covered_scenarios\"]}/36')
print(f'sparse场景: {stats[\"sparse_scenarios\"]}')
"
```

**依赖：** 步骤1 (ScenarioClassifier)、步骤2 (OrchestrationMemory)

---

## 步骤4：auto_trader.py 集成

**目标：** 运行时场景识别 + 记忆表驱动编排选择

**修改文件：** `1-ARCHITECTURE/dreamos/cli/auto_trader.py`

**改动点1 — __init__ 新增成员（第37-46行后）：**
```python
def __init__(self, agent_id: str = "b", dry_run: bool = True, exchange: str = "hyperliquid"):
    # ... 原有初始化 ...
    self._scenario_classifier = None
    self._orchestration_memory = None

def get_scenario_classifier(self):
    if self._scenario_classifier is None:
        from dreamos.core.sense.scenario_classifier import ScenarioClassifier
        self._scenario_classifier = ScenarioClassifier()
    return self._scenario_classifier

def get_orchestration_memory(self):
    if self._orchestration_memory is None:
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory
        self._orchestration_memory = OrchestrationMemory()
        self._orchestration_memory.load()  # 不存在则用空结构
    return self._orchestration_memory
```

**改动点2 — run_full_analysis 新增场景识别（第109-132行）：**
```python
def run_full_analysis(self, symbol: str) -> Dict[str, Any]:
    agent = self.get_trading_agent()
    market_data = self._fetch_market_data(symbol)  # 提前获取，两条路径都用

    # 新增：场景识别 + 编排选择
    classifier = self.get_scenario_classifier()
    memory = self.get_orchestration_memory()
    scenario = classifier.classify(market_data)
    choice = memory.select(scenario.scenario_id)

    if not agent:
        logger.warning(f"TradingAgent不可用，降级到经典指标分析 | 场景={scenario.scenario_id} 编排={choice.pattern}")
        return self._fallback_classic_analysis(symbol, market_data, scenario, choice)

    try:
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
        result["_scenario"] = scenario.scenario_id
        result["_orchestration"] = choice.pattern
        return result
    except Exception as e:
        logger.error(f"TradingAgent分析失败: {e}，降级到经典指标分析 | 场景={scenario.scenario_id}")
        return self._fallback_classic_analysis(symbol, market_data, scenario, choice)
```

**改动点3 — _fallback_classic_analysis 签名和逻辑修改（第134-258行）：**
```python
def _fallback_classic_analysis(self, symbol: str, market_data: dict = None,
                                scenario=None, choice=None) -> Dict[str, Any]:
    # ... 原有导入和registry初始化 ...

    if market_data is None:
        market_data = self._fetch_market_data(symbol)

    # 用记忆表选的节点，替代硬编码 ["C1", "C2", "C3"]
    chain_nodes = choice.nodes if choice else ["C1", "C2", "C3"]
    pattern_name = choice.pattern if choice else "c_chain"

    # ... 原有State构建和Graph执行逻辑不变 ...

    # 结果中新增场景和编排信息
    return {
        # ... 原有字段不变 ...
        "_path": "classic_fallback",
        "_scenario": scenario.scenario_id if scenario else "UNKNOWN",
        "_orchestration": pattern_name,
        "_fallback_level": choice.fallback_level if choice else "L3",
    }
```

**验证方法：**
```bash
python3 -c "
from dreamos.cli.auto_trader import AutoTrader
t = AutoTrader(dry_run=True)
r = t.run_full_analysis('BTC')
print(f'Path: {r.get(\"_path\")}')
print(f'Scenario: {r.get(\"_scenario\", \"N/A\")}')
print(f'Orchestration: {r.get(\"_orchestration\", \"N/A\")}')
print(f'Action: {r.get(\"action\")}')
"
```

**依赖：** 步骤1、步骤2

---

## 步骤5：stress_test.py 修改

**目标：** 场景驱动编排替代 random.choice

**修改文件：** `1-ARCHITECTURE/dreamos/cli/stress_test.py`

**改动点1 — __init__ 新增分类器和记忆表（第56-59行后）：**
```python
def __init__(self, rounds: int = 500):
    # ... 原有初始化 ...
    from dreamos.core.sense.scenario_classifier import ScenarioClassifier
    from dreamos.core.memory.orchestration_memory import OrchestrationMemory
    self.scenario_classifier = ScenarioClassifier()
    self.orchestration_memory = OrchestrationMemory()
    self.orchestration_memory.load()
```

**改动点2 — _test_graph_diversity 改为场景驱动（第84-121行）：**
```python
def _test_graph_diversity(self, scenario: Dict) -> Dict:
    symbol = scenario["symbol"]
    market_data = self.trader._fetch_market_data(symbol)

    # 场景驱动选择，替代 random.choice
    classified = self.scenario_classifier.classify(market_data)
    choice = self.orchestration_memory.select(classified.scenario_id)
    pattern_name = choice.pattern
    chain_nodes = choice.nodes

    cycle_id = f"stress_test_{symbol}_{scenario['round']}"
    state = new_state(cycle_id=cycle_id)
    state.market_data = market_data
    state.inputs = {"mkt": market_data, "symbol": symbol}

    graph = SequentialGraph()
    for node_id in chain_nodes:
        node = self.registry.get(node_id)
        if node:
            graph.add_node(node)

    executor = GraphExecutor()
    start_time = time.time()
    report = executor.execute(graph, state)
    latency_ms = (time.time() - start_time) * 1000

    return {
        "graph_pattern": pattern_name,
        "nodes": chain_nodes,
        "scenario_id": classified.scenario_id,
        "fallback_level": choice.fallback_level,
        # ... 其余字段不变 ...
    }
```

**改动点3 — _update_stats 新增场景统计（第240行后）：**
```python
def _update_stats(self, result: Dict):
    # ... 原有统计 ...
    # 新增：场景和降级统计
    graph_div = result["tests"].get("graph_diversity", {})
    sid = graph_div.get("scenario_id", "UNKNOWN")
    self.stats.setdefault("scenario_distribution", {})[sid] = \
        self.stats["scenario_distribution"].get(sid, 0) + 1
    fl = graph_div.get("fallback_level", "L3")
    self.stats.setdefault("fallback_distribution", {})[fl] = \
        self.stats["fallback_distribution"].get(fl, 0) + 1
```

**验证方法：**
```bash
python3 -c "
from dreamos.cli.stress_test import StressTestFramework
f = StressTestFramework(rounds=10)
r = f.run_single_test(1)
gd = r['tests']['graph_diversity']
print(f'Pattern: {gd[\"graph_pattern\"]} (was random, now scenario-driven)')
print(f'Scenario: {gd.get(\"scenario_id\", \"N/A\")}')
print(f'Fallback: {gd.get(\"fallback_level\", \"N/A\")}')
"
```

**依赖：** 步骤1、步骤2、步骤4

---

## 步骤6：ExecutionFeedback — 执行反馈收集

**目标：** 记录实际交易结果，计算与回测预期的偏差

**新建文件：** `1-ARCHITECTURE/dreamos/core/memory/execution_feedback.py`

**数据结构：**
```python
@dataclass
class ExecutionFeedback:
    scenario_id: str
    pattern_used: str
    timestamp: str
    trades: list          # 交易记录列表
    actual_sharpe: float
    expected_sharpe: float
    deviation: float      # (actual - expected) / |expected|
    trigger_evolution: bool

class ExecutionFeedbackCollector:
    def __init__(self, memory: OrchestrationMemory):
        self.memory = memory
        self._records = {}  # {scenario_id: [{"pattern":..., "trade":...}]}

    def record(self, scenario_id: str, pattern: str, trade_result: dict) -> None:
        """记录单笔交易结果"""

    def evaluate(self, scenario_id: str) -> ExecutionFeedback:
        """评估某场景的执行反馈"""
        # 计算最近N笔的实际夏普
        # 对比记忆表中的预期夏普
        # 判定是否触发进化

    def should_trigger_evolution(self, feedback: ExecutionFeedback) -> bool:
        """触发条件：
        1. 连续3笔方向准确率 < 50%
        2. |deviation| > 0.3
        """

    def get_all_feedbacks(self) -> list:
        """获取所有场景的反馈摘要"""
```

**反馈记录存储：** `1-ARCHITECTURE/dreamos/core/memory/execution_feedback.json`

**验证方法：**
```bash
python3 -c "
from dreamos.core.memory.execution_feedback import ExecutionFeedbackCollector
from dreamos.core.memory.orchestration_memory import OrchestrationMemory
c = ExecutionFeedbackCollector(OrchestrationMemory())
c.record('BULL_NORMAL_ACCELERATING', 'c_f_chain', {'direction':'LONG','result':0.03})
c.record('BULL_NORMAL_ACCELERATING', 'c_f_chain', {'direction':'LONG','result':-0.02})
fb = c.evaluate('BULL_NORMAL_ACCELERATING')
print(f'Deviation: {fb.deviation:.2%}')
print(f'Trigger: {fb.trigger_evolution}')
"
```

**依赖：** 步骤2 (OrchestrationMemory)

---

## 步骤7：EvolutionEngine 集成

**目标：** 新增 orchestration_optimization 触发源，编排优化闭环

**修改文件：** `1-ARCHITECTURE/dreamos/evolution/engine.py`
**修改文件：** `3-EVOLUTION/types.ts`（TS侧触发源枚举）

**改动点1 — engine.py evolve() 新增编排优化分支（第59-93行后）：**
```python
class EvolutionEngine:
    def __init__(self, min_occurrences: int = 2):
        # ... 原有初始化 ...
        self._feedback_collector = None  # 延迟初始化

    def get_feedback_collector(self):
        if self._feedback_collector is None:
            from dreamos.core.memory.execution_feedback import ExecutionFeedbackCollector
            from dreamos.core.memory.orchestration_memory import OrchestrationMemory
            self._feedback_collector = ExecutionFeedbackCollector(OrchestrationMemory())
        return self._feedback_collector

    def evolve(self, history=None, node_stats=None) -> EvolutionReport:
        # ... 原有逻辑（第75-92行）不变 ...

        # 新增：编排优化分支
        orchestration_updates = self._check_orchestration_optimization()

        return EvolutionReport(
            # ... 原有字段 ...
            orchestration_updates=orchestration_updates,
        )

    def _check_orchestration_optimization(self) -> list:
        """检查所有场景的执行反馈，触发编排优化"""
        collector = self.get_feedback_collector()
        updates = []
        for scenario_id in collector.get_all_scenario_ids():
            feedback = collector.evaluate(scenario_id)
            if feedback.trigger_evolution:
                proposal = self._generate_orchestration_proposal(feedback)
                if self._sandbox_validate(proposal):
                    collector.memory.update_from_evolution(
                        scenario_id, proposal.new_pattern,
                        proposal.nodes, proposal.score, proposal.evidence
                    )
                    updates.append({
                        "scenario_id": scenario_id,
                        "old_pattern": feedback.pattern_used,
                        "new_pattern": proposal.new_pattern,
                        "score_improvement": proposal.score - feedback.expected_sharpe,
                    })
        return updates

    def _generate_orchestration_proposal(self, feedback: ExecutionFeedback):
        """生成编排调整提案：切换到次优模式"""

    def _sandbox_validate(self, proposal) -> bool:
        """沙箱回测验证：新评分 > 现有 × 1.1"""
```

**改动点2 — types.ts 新增触发源（第1-10行）：**
```typescript
export type EvolutionTriggerSource =
  | 'execution_failure'
  | 'low_confidence'
  | 'chain_disagreement'
  | 'user_feedback'
  | 'governance_alert'
  | 'scheduled_audit'
  | 'lesson_distilled'
  | 'a8_reflection'
  | 'dream_oneirology'
  | 'orchestration_optimization';  // 新增
```

**验证方法：**
```bash
python3 -c "
from dreamos.evolution.engine import EvolutionEngine
e = EvolutionEngine()
# 无反馈数据时不应触发
updates = e._check_orchestration_optimization()
print(f'Updates: {updates}')  # 应为空列表
print('OK: evolution integration works')
"
```

**依赖：** 步骤2、步骤6

---

## 步骤8：CLI命令

**目标：** 提供回测/查询/进化操作的命令行接口

**新建文件：** `1-ARCHITECTURE/dreamos/cli/orchestration_commands.py`

**命令列表：**
```python
class OrchestrationBacktestCommand(Command):
    """orchestration backtest --period 2025-01-01_2026-06-30"""
    def run(self, args) -> int:
        # 调用 ScenarioBacktester.run() + OrchestrationMemory.save()

class OrchestrationMemoryListCommand(Command):
    """orchestration memory list"""
    def run(self, args) -> int:
        # 列出所有场景及其最优编排

class OrchestrationMemoryShowCommand(Command):
    """orchestration memory show BULL_NORMAL_ACCELERATING"""
    def run(self, args) -> int:
        # 显示某场景的详细回测指标

class OrchestrationQueryCommand(Command):
    """orchestration query --scenario BULL_HIGH_EXHAUSTION"""
    def run(self, args) -> int:
        # 查询某场景的最优编排（含降级路径）

class OrchestrationEvolveCommand(Command):
    """orchestration evolve --scenario BULL_NORMAL_ACCELERATING"""
    def run(self, args) -> int:
        # 手动触发进化优化

class OrchestrationFeedbackCommand(Command):
    """orchestration feedback --scenario BULL_NORMAL_ACCELERATING"""
    def run(self, args) -> int:
        # 查看执行反馈统计
```

**注册到CLI主应用：** 修改 `dreamos/cli/app.py` 注册新命令组

**验证方法：**
```bash
# 查询（空记忆表应显示L3默认）
python3 -m dreamos.cli orchestration query --scenario BULL_NORMAL_ACCELERATING

# 运行回测生成记忆表
python3 -m dreamos.cli orchestration backtest

# 列出记忆表
python3 -m dreamos.cli orchestration memory list
```

**依赖：** 步骤1-7全部完成

---

## 执行顺序与依赖关系

```
步骤1 (ScenarioClassifier) ──────────────┐
                                          ├──→ 步骤3 (Backtester) ──┐
步骤2 (OrchestrationMemory) ──────────────┤                         │
                                          ├──→ 步骤4 (auto_trader) ─┤
                                          ├──→ 步骤5 (stress_test) ─┤
                                          ├──→ 步骤6 (Feedback) ────┤
                                          │                         ├──→ 步骤8 (CLI)
                                          └──→ 步骤7 (Evolution) ───┘
```

**并行机会：** 步骤1和2可并行；步骤4和5可并行；步骤6和7可并行

## 验收标准

| 标准 | 验证方法 |
|------|---------|
| 场景分类正确 | 36种场景ID格式正确，边界值测试通过 |
| 记忆表生成 | 回测后JSON文件存在，场景覆盖率≥60% |
| 降级逻辑有效 | sparse场景正确走L1/L2/L3 |
| random.choice消除 | stress_test.py 第98行不再出现random.choice |
| 硬编码C链消除 | auto_trader.py 第158行不再硬编码["C1","C2","C3"] |
| 进化触发有效 | 偏差>30%时正确触发orchestration_optimization |
| 端到端可用 | `python3 -m dreamos.cli orchestration query` 正常返回 |
| 500轮压测通过 | 场景驱动编排，降级率<30%，成功率≥95% |
