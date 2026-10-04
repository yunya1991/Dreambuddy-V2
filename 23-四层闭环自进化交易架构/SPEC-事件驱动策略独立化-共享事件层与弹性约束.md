# SPEC — 事件驱动策略独立化：共享事件层与弹性约束

> **版本**：v1.3 (2026-10-04)
> **状态**：实施中
> **优先级**：P1（Phase 1 落地 = P0，解决孤立问题）
> **作者**：架构评估沉淀
> **关系**：本文件是 [`SPEC-事件驱动策略P0盲区修复-非农CPI加息预期.md`](./SPEC-事件驱动策略P0盲区修复-非农CPI加息预期.md) v1.0 的**架构升级补丁**。P0 修复了事件驱动策略的盲区（非农/CPI 触发、真实 FedWatch 概率），但事件驱动策略本身仍**孤立于回测脚本**，未接入实盘主链路。本 SPEC 解决"孤立"问题，并规划向共享事件层演进。

**版本历史**：
- v1.0 (2026-10-02)：初始版本
- v1.2 (2026-10-04)：Phase 3 — 独立子交易系统定位 + 5 维评分修订 + 单点脉冲算法
- v1.3 (2026-10-04)：Phase 3.1 — 新增第 6 维 `news_score`，将新闻情感数据纳入事件驱动评分体系

---

## 一、问题陈述

### 1.1 核心问题：事件驱动策略完全孤立

**代码事实**（2026-10-02 核查）：

| 组件 | 实际接入位置 |
|------|-------------|
| `EventDrivenStrategy`（5 维评分） | 仅 `scripts/backtest_macro_event.py` 回测脚本 |
| `ConvictionScorer` | 仅 `scripts/backtest_macro_event.py` 回测脚本 |
| `EventDominanceController` | 仅 `scripts/backtest_macro_event.py` 回测脚本 |
| `PrimaryContradictionDetector`（engines/） | 仅测试文件 |

主链路 `kline_event_handler.py` → `evolution_pipeline.py` 用的是 `PrimaryContradictionIdentifier`（core 层），**与事件驱动 5 维评分策略完全无关**。

**后果**：P0 盲区修复（非农/CPI 触发、真实 FedWatch）的价值**完全无法释放** — 宏观事件信号只在回测脚本里跑，实盘 BCRM2.0/战略层/自进化都收不到。

### 1.2 次要问题：三套事件逻辑各自为政

| 子系统 | 事件逻辑 | 时间尺度 | 数据源 |
|--------|---------|---------|--------|
| 自进化（孤立） | 宏观事件 5 维评分 | 单点脉冲（小时-天） | FOMC/非农/CPI/CESI |
| BCRM2.0 | odaily 币种快讯情感 → Score_B clamp[0,0.10] | 币种级快讯（小时） | odaily_newsflash |
| 战略层 | VIX/利率/美林时钟（趋势代理） | 趋势级（天-周） | 宏观代理指标 |

**没有统一事件总线**，每个子系统各自实现事件逻辑，数据不一致、维护成本高。

### 1.3 用户洞察（核心价值）

事件驱动策略与趋势策略**本质不同**：
- **趋势策略** = 连续价格序列的方向性判断（基底，天-周尺度）
- **事件驱动** = 离散单点事件的冲击响应（脉冲，小时-天尺度）
- **弹性约束关系** = 脉冲对基底的扰动：
  - **顺势**（事件方向 = 趋势方向）→ 共振放大 → 趋势跟随加仓
  - **逆势**（事件方向 ≠ 趋势方向）→ 均值回归 → 反弹后反向入场

```
事件冲击方向 × 趋势方向 = 4 种弹性组合：
  利多事件 × 上升趋势 = 顺势强化（弹性系数 ≈ 1.0）
  利多事件 × 下降趋势 = 逆势反弹 → 做空机会（弹性系数 ≈ -0.7）
  利空事件 × 上升趋势 = 逆势回调 → 做多机会（弹性系数 ≈ -0.7）
  利空事件 × 下降趋势 = 顺势强化（弹性系数 ≈ 1.0）
```

### 1.4 边界澄清（硬约束，来自认知记忆）

- **BCRM2.0 与 V15 完全独立**，本 SPEC 不涉及 V15
- **战略层** `enable_five_domain=False` + `shadow_mode=True`（默认关闭），事件注入战略层前需先解决战略层激活问题
- **BCRM2.0 当前独立测试**，战略层信号未注入或未生效
- **FAIL-OPEN 铁律**：事件层异常时，各子系统必须降级到基线行为，不 crash、不误判
- **HC-1a**：不修改 dreamos/核心

---

## 二、目标与非目标

### 2.1 目标

1. **Phase 1（P0）**：解决孤立 — 将 `EventDrivenStrategy` 接入 `kline_event_handler` 主链路，使宏观事件信号能影响自进化系统实盘决策
2. **Phase 2（P1）**：定义 `EventSignal` 统一契约，事件驱动策略定位为"事件-趋势弹性评估器"
3. **Phase 3（P1）**：战略层接入 — 事件作为"天维度"宏观状态影响 `war_state`
4. **Phase 4（P2）**：BCRM2.0 接入 — 事件作为"反向风险闸门"防止逆势做空
5. **Phase 5（P2）**：自进化适应度函数注入 — 事件作为"环境扰动因子"校准进化方向

### 2.2 非目标

- 不修改趋势策略核心逻辑（L1 R向量、Level0 d*、RippleEngine）
- 不修改 BCRM2.0 技术面分析核心
- 不修改 V15
- 不实现事件驱动策略作为"独立策略"直接下单（它是评估器，不是策略）
- Phase 1 不定义 EventSignal 契约（先用现有 EventDrivenSignal 接入，Phase 2 再标准化）

---

## 三、架构设计

### 3.1 定位修正（v1.2）：事件驱动策略 = 独立子交易系统（初期）

> **修订记录**：v1.2 (2026-10-04) — 基于用户决策，事件驱动策略**初期作为独立子交易系统**运行，而非直接作为评估器接入其他子系统。理由：策略本身不成熟时接入会导致归因灾难（与战略层教训一致）。成熟后再开放接口供其他子系统消费。

**初期定位**：独立子交易系统（与 BCRM2.0、BDSM 平级）

| 维度 | 说明 |
|------|------|
| 核心职责 | 自己产生信号 + 自己开仓/平仓 + 自己管理仓位 |
| 开仓逻辑 | EventSignal → 方向决策 → 仓位计算 → SL/TP 生成 |
| 仓位管理 | 独立仓位 cap（按事件类型/阶段） |
| 离场逻辑 | 脉冲衰减平仓 + 事件窗口结束平仓 + SL/TP |
| 回测路径 | 独立回测脚本验证策略本身 |
| 归因 | 独立运行，归因清晰 |
| 接口保留 | EventSignal 写入 shadow，成熟后 SubSystemBridge 可读取 |

**成熟后定位**：开放接口，EventSignal 可被其他子系统消费：

| 子系统 | 消费方式 | 价值 |
|--------|---------|------|
| 自进化 | 注入路径发现层，调整 d* 方向或仓位 | 进化方向校准 |
| 战略层 | 影响 war_state（天维度） | 方向否决 + 仓位 cap |
| BCRM2.0 | 反向风险闸门（逆势时拦截/减仓） | 逆势风险防护 |

### 3.2 分阶段架构演进

```
Phase 1（已完成）:  解决孤立
  kline_event_handler → EventDrivenStrategy.evaluate(kline_data)
  → EventSignal → 注入 path_info / 调整 d*

Phase 2（已完成）:  契约标准化
  EventSignal 契约定义 + 弹性系数计算

Phase 3（本次）:  独立子交易系统 + 5维评分升级 + 脉冲算法
  EventDrivenTrader 类（同文件）：开仓/仓位/离场
  5 维评分修订：+surprise_score、priced_in 量化、real_rate 变化率、cross_asset 标准化
  单点脉冲算法：指数衰减 IRF（实时）+ SVAR（离线 τ 标定）
  阶段动态阈值：pre(0.70/0.30) / event(0.55/0.40) / repricing(0.60/0.35)
  shadow 写入但不消费（其他子系统暂不接入）

Phase 4（成熟后）:  BCRM2.0 逆势防护接入
  BCRM2.0 通过 SubSystemBridge.get_event_signal() 消费

Phase 5（成熟后）:  自进化适应度函数注入
  事件作为环境扰动因子校准进化方向
```

### 3.3 Phase 1 接入点设计

**接入位置**：`kline_event_handler._run_path_discovery()` 中，路径发现层之后、d* 覆盖之前。

**注入方式**：
1. 从 `kline_data` 读取 `event_context`（T7 已注入：event_type/hike_prob/in_fomc_cycle/cesi 等）
2. 调用 `EventDrivenStrategy().evaluate(kline_data)` 获取 `EventDrivenSignal`
3. 若 `signal != "neutral"` 且 `confidence >= 阈值`，将事件信号注入 `path_info`，作为路径发现的"事件路径"参与竞争
4. 事件路径的方向权重 = `signal`（long/short），置信度 = `confidence`
5. FAIL-OPEN：EventDrivenStrategy 异常 → 跳过事件路径，不影响原有路径发现

**开关控制**：`enable_event_driven_path`（AGI_SWITCHES 新增子开关），默认 True（Phase 1 落地即激活，但置信度阈值保守）。

---

## 四、Phase 1 详细设计（解决孤立问题）

### 4.1 数据流

```
kline_event_handler.on_kline_close(kline_data)
  └─ _run_path_discovery()
       ├─ [现有] EvolutionPipeline._discover_paths() → paths
       ├─ [新增] EventDrivenStrategy.evaluate(kline_data) → event_signal
       │    └─ FAIL-OPEN: 异常 → event_signal = None（跳过）
       ├─ [新增] if event_signal and event_signal.signal != "neutral":
       │    paths.append({
       │      "source": "event_driven",
       │      "direction": event_signal.signal,
       │      "score": event_signal.confidence,
       │      "event_phase": event_signal.event_phase,
       │      "reason": event_signal.reason,
       │    })
       └─ _select_optimal_path(paths) → 最优路径可能来自 event_driven
```

### 4.2 EventDrivenSignal → 路径适配

现有 `EventDrivenSignal` 字段：
- `signal`: "long" / "short" / "neutral"
- `confidence`: float [0, 1]
- `mode`: str
- `scores`: dict（5 维评分明细）
- `event_phase`: str
- `reason`: str

适配为 path dict：
```python
{
    "source": "event_driven",
    "direction": signal,          # "long" / "short"
    "score": confidence,          # 作为路径得分参与竞争
    "validated": confidence >= 0.60,  # 置信度阈值（保守）
    "low_conviction": confidence < 0.50,
    "event_phase": event_phase,
    "reason": reason,
}
```

### 4.3 开关配置（agi_config.py AGI_SWITCHES）

```python
# --- 事件驱动路径发现（Phase 1 解决孤立）---
"enable_event_driven_path": True,   # 事件驱动策略接入路径发现层总开关
"event_driven_confidence_threshold": 0.60,  # 事件信号置信度阈值（低于此值不参与竞争）
```

### 4.4 FAIL-OPEN 策略

| 异常场景 | 处理 |
|----------|------|
| `EventDrivenStrategy.evaluate()` 抛异常 | `logger.debug` 记录，`event_signal = None`，跳过事件路径 |
| `kline_data` 无 `event_context` | `EventDrivenStrategy` 返回 neutral（已有逻辑），不注入路径 |
| `confidence < 阈值` | 不注入路径（信号太弱，不干扰原有决策） |
| AGI 开关关闭 | 不调用 EventDrivenStrategy |

### 4.5 边界约束

- **不修改** `EventDrivenStrategy` 内部逻辑（P0 已修复盲区，Phase 1 只做接入）
- **不修改** `EvolutionPipeline._discover_paths()` 内部逻辑（只在 kline_event_handler 层追加事件路径）
- **不修改** `_select_optimal_path()` 评分逻辑（事件路径以普通路径身份参与竞争）
- **不修改** `EventDrivenSignal` 数据结构（Phase 2 再标准化为 EventSignal）

---

## 五、测试策略（Phase 1）

### 5.1 RED 测试（先写失败测试）

1. `test_event_driven_path_injection.py`:
   - `test_event_driven_signal_injected_as_path`: mock EventDrivenStrategy 返回 long/confidence=0.8 → 验证 paths 中包含 source="event_driven"
   - `test_event_driven_neutral_skipped`: mock 返回 neutral → 验证 paths 中无 event_driven
   - `test_event_driven_low_confidence_skipped`: mock 返回 long/confidence=0.4 → 验证不注入
   - `test_event_driven_fail_open`: mock 抛异常 → 验证不 crash、paths 正常
   - `test_event_driven_switch_off`: 开关关闭 → 验证不调用 EventDrivenStrategy

### 5.2 GREEN 实现

在 `kline_event_handler._run_path_discovery()` 中追加事件路径注入逻辑（约 30 行）。

### 5.3 回归

- `test_kline_event_handler.py` 全量回归
- `test_phase1_integration.py` 全量回归
- 事件层 101 测试零回归

---

## 六、后续阶段规划（不在本次实施范围）

### Phase 2：EventSignal 契约标准化
- 定义 `EventSignal` dataclass：`direction` / `strength` / `elasticity` / `event_type` / `window_start` / `window_end` / `confidence` / `reason`
- `EventDrivenStrategy` 输出 `EventSignal`（替代 `EventDrivenSignal`）
- 弹性系数计算：基于事件方向与趋势方向的关系

### Phase 3：独立子交易系统 + 5维评分升级 + 单点脉冲算法

> **修订记录**：
> - v1.1 (2026-10-03) — 澄清 `shadow_mode=True` 是 BY DESIGN，Phase 3 改为 shadow 旁路注入
> - v1.2 (2026-10-04) — 基于用户决策，事件驱动策略**初期作为独立子交易系统**运行（与 BCRM2.0/BDSM 平级），成熟后再开放接口。Phase 3 新增：EventDrivenTrader 类、5 维评分修订、单点脉冲算法、阶段动态阈值。

#### 3.0 设计定位（v1.2 核心调整）

事件驱动策略**初期作为独立子交易系统**，与 BCRM2.0、BDSM 平级独立运行：

| 维度 | 说明 |
|------|------|
| 核心职责 | 信号生成 + 开仓/平仓 + 仓位管理（独立闭环） |
| 文件位置 | `event_driven_strategy.py` 同文件新增 `EventDrivenTrader` 类 |
| 与其他子系统关系 | EventSignal 写入 shadow，但**其他子系统暂不消费** |
| 成熟后 | SubSystemBridge 开放 `get_event_signal()` 供其他系统消费 |
| 归因 | 独立运行，归因清晰（避免战略层式灾难） |

#### 3.1 EventDrivenTrader 类设计（独立子交易系统）

```python
class EventDrivenTrader:
    """事件驱动独立子交易系统。

    职责：
    1. 调用 EventDrivenStrategy.evaluate() 获取 EventSignal
    2. 开仓决策：signal != neutral + strength ≥ 动态阈值
    3. 仓位计算：按事件类型/阶段/strength 计算名义仓位
    4. SL/TP 生成：ATR 自适应 + 事件窗口约束
    5. 离场管理：脉冲衰减平仓 + 事件窗口结束平仓 + SL/TP
    6. 状态持久化：EventSignal + 持仓状态写入 shadow
    """

    def __init__(self, strategy: EventDrivenStrategy, config: dict):
        self._strategy = strategy
        self._config = config
        self._position = None  # 当前持仓

    def on_kline_close(self, kline_data: dict) -> EventSignal:
        """主入口：每 K 线调用。返回 EventSignal 并执行交易决策。"""
        signal = self._strategy.evaluate(kline_data)
        self._write_shadow(signal)

        # 离场检查优先
        if self._position is not None:
            if self._should_exit(signal, kline_data):
                self._close_position()
            return signal

        # 开仓检查
        if self._should_open(signal):
            self._open_position(signal, kline_data)

        return signal

    def _should_open(self, signal: EventSignal) -> bool:
        """开仓条件：信号非中性 + strength ≥ 阶段阈值 + 无持仓。"""
        if signal.signal == "neutral":
            return False
        if self._position is not None:
            return False
        long_th, short_th = PHASE_THRESHOLDS.get(signal.event_phase, (0.65, 0.35))
        if signal.signal == "long" and signal.strength < long_th:
            return False
        if signal.signal == "short" and signal.strength < (1.0 - short_th):
            return False
        return signal.confidence >= 0.5  # 数据完整度门槛

    def _compute_position_size(self, signal: EventSignal) -> float:
        """仓位计算：基础仓位 × strength × 阶段乘数 × 弹性修正。"""
        base = self._config.get("base_position", 250.0)  # USDT 名义
        phase_mult = PHASE_POSITION_MULT.get(signal.event_phase, 1.0)
        elasticity_mult = 1.0 + signal.elasticity * 0.3  # 顺势+30%，逆势-21%
        return base * signal.strength * phase_mult * elasticity_mult

    def _compute_sl_tp(self, signal: EventSignal, kline_data: dict) -> tuple[float, float]:
        """SL/TP：ATR 自适应（SL=4-6×ATR, TP=3×SL）+ 事件窗口约束。"""
        atr = kline_data.get("atr", 0.0)
        close = kline_data.get("close", [0])[-1] if kline_data.get("close") else 0
        if atr <= 0 or close <= 0:
            return 0.04, 0.12  # FAIL-OPEN：硬编码下限
        sl_pct = max(0.04, min(0.15, 5.0 * atr / close))
        tp_pct = min(0.30, sl_pct * 3.0)
        return sl_pct, tp_pct

    def _should_exit(self, signal: EventSignal, kline_data: dict) -> bool:
        """离场条件：脉冲衰减到阈值 / 事件窗口结束 / SL / TP / 信号反转。"""
        if self._position is None:
            return False
        # 脉冲衰减平仓
        days_since = self._days_since_event(signal)
        tau = EVENT_HALF_LIFE.get(signal.event_type, 1.0)
        if days_since > 3 * tau:
            return True  # 脉冲完全衰减
        # 信号反转
        if signal.signal != "neutral" and signal.signal != self._position["direction"]:
            return True
        # SL/TP 由执行层处理
        return False
```

#### 3.2 6 维评分体系（v1.3 新增 news_score）

**调研依据**：
- v1.2：cme-fedwatch（FedWatch 概率）、macroshock（SVAR IRF）、gs-quant（MarketDataShock）、事件研究法（Andersen 2003、Pinchuk 2023、Smales 黄金 VAR-GARCH）
- v1.3 新增：PEAD.txt（费城联储，文本惊喜漂移是数字惊喜 2 倍）、GDELT+FinBERT+XGBoost（arXiv 2505.16136，Sharpe 5.87）、Vibe-Trading 事件类型分类、Forecite 双维度打分

| 维度 | 权重 | 修订类型 | 核心逻辑 |
|------|------|---------|---------|
| ① surprise_score | 25% | ★ 新增(v1.2) | `(actual-expected)/σ` 标准化，正惊喜→高分 |
| ② priced_in_score | 20% | ✓ 修订(v1.2) | ratio=预期累计涨跌/历史平均反应，ratio>1 反向 |
| ③ real_rate_score | 20% | ✓ 增强(v1.2) | Δreal_rate 变化率，水平60%+变化率40% |
| ④ resilience_score | 15% | ✓ 通用化(v1.2) | 实际跌幅/预期跌幅比率，通用所有事件类型 |
| ⑤ cross_asset_score | 10% | ✓ 权重下调(v1.3) | `tanh(surprise/2)` 标准化，权重 20%→10% |
| ⑥ news_score | 10% | ★ 新增(v1.3) | 新闻情感双维度打分，详见 §3.2.1 |

**新增数据依赖**（v1.3）：
- `news_sentiment_score` ∈ [0,1]（已有，SentimentBridge 从 odaily 快讯计算并注入 kline_data）
- 未来扩展：`news_actionability`、`news_verdict`、`news_event_type`（P1/P2 阶段）

##### 3.2.1 news_score 设计（Phase 3.1）

**设计原则**：
1. **FAIL-OPEN 优先**：新闻数据缺失/异常时，news_score=0.5（中性），不影响信号方向
2. **低权重起步**：10% 权重，避免新闻噪音主导信号（加密市场虚假消息多）
3. **复用现有能力**：直接复用 SentimentBridge 已产出的 `news_sentiment_score`

**P0 实现**（双维度简化版）：
```python
def _score_news(self, data: dict, event_ctx: dict) -> float:
    """新闻情感评分。
    双维度：actionability（有新闻=1，无=0）× verdict（情感方向）
    FAIL-OPEN：无新闻 → 0.5 中性
    """
    sentiment = data.get("news_sentiment_score")
    if sentiment is None:
        return 0.5  # FAIL-OPEN：无新闻数据
    has_news = 1.0  # 有情感分即视为有新闻
    verdict = 2.0 * (sentiment - 0.5)  # [0,1] → [-1,1]
    return float(np.clip(0.5 + 0.5 * verdict * has_news, 0.0, 1.0))
```

**P1 扩展**（事件类型分类 + 时间衰减）：
- 事件类型分类：earnings(1-5d) / macro(5-20d) / policy(20-60d) / sentiment(1-3d) / insider(5-10d) / technical_break(1-5d)
- 时间衰减：`news_score *= exp(-hours_since / half_life[event_type])`

**P2 扩展**（双维度打分 + 背离检测）：
- `news_actionability` ∈ [0,1]：新闻是否可能短期影响价格（噪音过滤）
- `news_verdict` ∈ [-1,1]：方向评分（校准到已实现收益）
- 新闻-价格背离：看多新闻+跌价=谨慎，看空新闻+涨价=机会

#### 3.3 单点脉冲算法

**方案**：方案1（指数衰减 IRF）为主，方案3（SVAR）作为离线 τ 标定工具。

```python
EVENT_HALF_LIFE = {"fomc": 3.0, "cpi": 2.0, "nfp": 1.5, "ppi": 1.0, "none": 0.0}

def compute_impulse(event_type: str, days_since: float, strength: float) -> float:
    """impulse(t) = strength × exp(-t / τ)
    t > 3τ → 趋于 0；FAIL-OPEN → 0.0
    """
    tau = EVENT_HALF_LIFE.get(event_type, 1.0)
    if tau <= 0 or days_since < 0:
        return 0.0
    return strength * math.exp(-days_since / tau)
```

**弹性修正**：
- 顺势（elasticity > 0）：脉冲同向增强 composite（±pulse×0.15）
- 逆势（elasticity < 0）：t < τ 时反向（均值回归预期），t > τ 不调整

**SVAR 离线工具**（不进入热路径）：用 macroshock 库对历史事件做 IRF + FEVD 分析，标定 τ 参数初值和验证脉冲衰减假设。

#### 3.4 阶段动态信号阈值

```python
PHASE_THRESHOLDS = {
    "pre_event":        {"long": 0.70, "short": 0.30},  # 保守：不确定性高
    "expectation_jump": {"long": 0.65, "short": 0.32},  # 跳变期略放宽
    "event":            {"long": 0.55, "short": 0.40},  # 利空出尽，阈值放宽
    "repricing":        {"long": 0.60, "short": 0.35},  # 三阶段权衡
    "neutral":          {"long": 0.65, "short": 0.35},  # 兜底
}
```

#### 3.5 shadow 写入但不消费

- EventDrivenTrader 每轮将 EventSignal 写入 `trader._event_signal_shadow`
- 其他子系统**暂不消费**（SubSystemBridge.get_event_signal() 虽可读取，但无调用方）
- 成熟后（Phase 4+）：BCRM2.0/自进化通过 SubSystemBridge 消费 EventSignal

#### 3.6 边界约束

- 不修改战略层核心（`enable_five_domain` 保持 False）
- 不修改 BCRM2.0 任何代码
- HC-1a：不修改 dreamos/核心
- FAIL-OPEN：所有新数据依赖缺失 → 中性兜底，不 crash
- 独立子系统仓位上限：≤250 USDT 名义（与 BDSM 单币预算一致）

**接入模式**：复用 polling_trader 已有的 `_five_domain_state_shadow` 模式，新增并行 `_event_signal_shadow` 状态对象。事件信号通过 SubSystemBridge 独立流转到下游消费方，**完全不碰 FiveDomainState**。

```
KlineEventHandler.on_kline_close(kline_data)
  └─ _run_path_discovery()
       └─ EventDrivenStrategy.evaluate(kline_data) → EventSignal  (Phase 1-2 已完成)
       └─ trader._event_signal_shadow = event_signal.to_dict()   ★ Phase 3 新增：写 shadow
       └─ [下游消费方通过 SubSystemBridge.get_event_signal() 读取]

evolution_pipeline / exit_engine / position_manager
  └─ bridge.get_event_signal() → EventSignal | None     ★ Phase 3 新增 API
  └─ bridge.get_event_elasticity() → float              ★ Phase 3 新增 API
  └─ 用于：弹性系数 → 仓位 cap / 方向偏置 / 路径竞争得分
```

#### 3.4 SubSystemBridge 新增 API

```python
class SubSystemBridge:
    def get_event_signal(self, cls: str = "crypto_usdt") -> Optional[EventSignal]:
        """读取 polling_trader._event_signal_shadow。
        FAIL-OPEN → None（无 shadow / trader 缺失 / 异常）。"""
        try:
            if self._trader is None:
                return None
            shadow = getattr(self._trader, "_event_signal_shadow", None)
            if not shadow or not isinstance(shadow, dict):
                return None
            return EventSignal.from_dict(shadow)  # FAIL-OPEN：异常返回 neutral
        except Exception:
            return None

    def get_event_elasticity(self, cls: str = "crypto_usdt") -> float:
        """读取事件弹性系数（-1.0~1.0）。FAIL-OPEN → 0.0（无约束）。"""
        sig = self.get_event_signal(cls)
        if sig is None:
            return 0.0
        return float(sig.elasticity)

    def set_event_signal_shadow(self, event_signal: Optional[EventSignal]) -> None:
        """写回事件信号到 trader shadow。FAIL-OPEN：trader 缺失 → 静默返回。"""
        try:
            if self._trader is None:
                return
            if event_signal is None:
                self._trader._event_signal_shadow = None
            else:
                self._trader._event_signal_shadow = event_signal.to_dict()
        except Exception as e:
            logger.debug("[FO] set_event_signal_shadow fail: %s", e)
```

#### 3.5 KlineEventHandler 写入点

在 Phase 1 的 `_inject_event_driven_path()` 之后追加 shadow 写入（约 5 行）：

```python
# Phase 3: 事件信号 shadow 旁路注入（不影响战略层 war_state）
try:
    if hasattr(self, "_subsystem_bridge") and self._subsystem_bridge is not None:
        self._subsystem_bridge.set_event_signal_shadow(event_signal)
except Exception as e:
    logger.debug("[FO] event_signal_shadow write fail: %s", e)
```

#### 3.6 边界约束（硬约束遵守）

- **不修改** `FiveDomainHeuristicScorer`（战略层核心）
- **不修改** `enable_five_domain`（保持 BY DESIGN False）
- **不修改** `war_state` 决策逻辑
- **不修改** `direction_context` 字段（不触发战略层方向偏置重算）
- **不修改** BCRM2.0 任何代码
- **HC-1a**：不修改 dreamos/核心 / polling_trader 核心（只在实例上挂 shadow 属性，不修改类定义）
- **FAIL-OPEN 铁律**：trader 缺失 / shadow 异常 / EventSignal.from_dict 失败 → 全部静默降级，不影响主链路

#### 3.7 测试策略

**RED 测试**（先写失败测试，分 3 组）：

**A. EventDrivenTrader 独立子交易系统（10 个）**：
1. `test_trader_open_position_long`：signal=long + strength≥阈值 → _should_open 返回 True
2. `test_trader_open_position_short`：signal=short + strength≥阈值 → 返回 True
3. `test_trader_no_open_neutral`：signal=neutral → _should_open 返回 False
4. `test_trader_no_open_below_threshold`：strength < 阶段阈值 → 返回 False
5. `test_trader_position_size`：strength=0.8, phase=event → 仓位 = base×0.8×phase_mult×elasticity_mult
6. `test_trader_sl_tp_atr`：atr=100, close=50000 → sl_pct=max(0.04, 5×100/50000)
7. `test_trader_exit_pulse_decay`：days_since > 3τ → _should_exit 返回 True
8. `test_trader_exit_signal_reversal`：signal 反转 → _should_exit 返回 True
9. `test_trader_no_exit_within_window`：days_since < 3τ 且同向 → 返回 False
10. `test_trader_fail_open_no_atr`：atr=0 → sl/tp 返回硬编码下限 0.04/0.12

**B. 5→6 维评分修订（8+4=12 个）**：
11. `test_surprise_score_positive`：actual>expected(利好) → score > 0.5
12. `test_surprise_score_negative`：actual<expected(利空) → score < 0.5
13. `test_surprise_score_fail_open`：actual=None → score=0.5
14. `test_priced_in_overpriced`：ratio>1 → base 向上修正（反向预期）
15. `test_real_rate_with_delta`：real_rate_history 下行 → delta_score > 0.5
16. `test_cross_asset_standardized`：gold_surprise 正 → score += 0.25×tanh
17. `test_resilience_generalized`：expected_drop<0 且 ret_3d/expected_drop<1 → 0.85
18. `test_composite_includes_surprise`：加权包含 surprise_score
19. `test_news_score_bullish`：news_sentiment_score=0.8 → news_score > 0.5
20. `test_news_score_bearish`：news_sentiment_score=0.2 → news_score < 0.5
21. `test_news_score_fail_open`：news_sentiment_score=None → news_score=0.5
22. `test_composite_includes_news`：6 维加权包含 news_score（权重 10%）

**C. 脉冲算法 + 动态阈值（6 个）**：
19. `test_impulse_decay`：t=τ → impulse = strength×exp(-1)
20. `test_impulse_zero_after_3tau`：t>3τ → impulse≈0
21. `test_impulse_fail_open`：event_type=none → 0.0
22. `test_phase_thresholds_event`：event 阶段 long阈值=0.55
23. `test_phase_thresholds_pre`：pre 阶段 long阈值=0.70
24. `test_pulse_elasticity_con顺势`：elasticity>0 + signal=long → composite += pulse×0.15

**GREEN 实现**：
- `EventDrivenTrader` 类（约 100 行）
- `_score_surprise` 新方法 + 修订 4 个评分方法（约 80 行）
- `compute_impulse` + `apply_pulse_decay`（约 40 行）
- `PHASE_THRESHOLDS` + `EVENT_HALF_LIFE` 常量
- SubSystemBridge 3 方法（shadow 写入基础设施）

**REFACTOR 回归**：
- 事件层 101 测试 + 新增 24 测试零回归
- Phase 1-2 集成测试零回归
- `test_subsystem_bridge.py` 全量

#### 3.8 验收标准

- [ ] `EventDrivenTrader` 类存在，包含 on_kline_close/_should_open/_compute_position_size/_compute_sl_tp/_should_exit 方法
- [ ] `surprise_score` 维度加入评分加权
- [ ] `priced_in_score` 包含 ratio=预期累计涨跌/历史平均反应 修正
- [ ] `real_rate_score` 包含 Δreal_rate 变化率（水平60%+变化率40%）
- [ ] `cross_asset_score` 用 tanh(surprise/2) 标准化，权重 10%
- [ ] **`news_score` 维度加入评分加权，权重 10%（v1.3 新增）**
- [ ] **`news_score` FAIL-OPEN：news_sentiment_score=None → 0.5（v1.3 新增）**
- [ ] `compute_impulse` 指数衰减函数存在，τ 按事件类型
- [ ] `PHASE_THRESHOLDS` 阶段动态阈值存在
- [ ] EventSignal 写入 shadow，其他子系统暂不消费（grep 验证无消费方）
- [ ] 战略层 `enable_five_domain` 保持 False（grep 验证未改动）
- [ ] 全量回归零失败

#### 3.9 与后续 Phase 的衔接

- **Phase 4 BCRM2.0 逆势防护**：直接复用 `bridge.get_event_signal()`，BCRM2.0 通过 bridge 读取事件信号作为反向风险闸门。无需再建基础设施。
- **Phase 5 自进化适应度函数**：策略基因在事件冲击下的表现通过 `bridge.get_event_elasticity()` 提取，作为环境扰动因子。

---

### Phase 4：BCRM2.0 逆势防护
- 事件作为"反向风险闸门"
- BCRM2.0 卦象凶→做空时，若事件冲击利多 → 拦截或减仓
- 复用现有 `event_positive_strength` 注入点，但替换为宏观事件信号

### Phase 5：自进化适应度函数注入
- 事件作为"环境扰动因子"
- 策略基因在事件冲击下的表现被选择
- 进化方向校准

---

## 七、风险与缓解

| 风险 | 缓解 |
|------|------|
| 事件信号干扰原有趋势决策 | 置信度阈值保守（0.60），事件路径以普通路径身份竞争，不强制覆盖 |
| EventDrivenStrategy 性能影响 | 延迟初始化 + 只在路径发现层调用（每 K 线一次），FAIL-OPEN 快速失败 |
| 数据缺失（event_context 为空） | EventDrivenStrategy 已有 neutral 兜底逻辑，不影响主链路 |
| ~~战略层未激活导致 Phase 3 阻塞~~ | **修订（v1.1）**：战略层 `enable_five_domain=False` 是 BY DESIGN，Phase 3 改为 shadow 旁路注入，不依赖战略层激活 |
| BCRM2.0 独立测试阶段不接入 | Phase 4 等 BCRM2.0 测试稳定后再接入 |

---

## 八、验收标准

### Phase 1 验收

- [ ] `EventDrivenStrategy` 被 `kline_event_handler` 主链路调用（grep 验证）
- [ ] 事件信号（long/short + confidence ≥ 0.60）作为路径参与 `_select_optimal_path` 竞争
- [ ] 事件信号 neutral 或低置信度时不注入路径
- [ ] EventDrivenStrategy 异常时不 crash、不影响原有路径发现
- [ ] 开关 `enable_event_driven_path=False` 时不调用 EventDrivenStrategy
- [ ] 全量回归零失败
