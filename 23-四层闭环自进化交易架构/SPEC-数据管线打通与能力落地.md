# SPEC: 数据管线打通 — 自进化系统识别最优路径与计算最小阻力

> **状态：** Spec（待评审）
> **创建：** 2026-09-05
> **目标：** 将分散的数据源/知识库/认知系统/子交易系统打通为统一数据管线，使 ResistanceVector 5 维全部接收真实数据，Level0 d* 计算脱离退化态，RippleEngine/ReflectionEngine 闭环真正运转。
> **约束：** FAIL-OPEN 铁律不可破坏；工业级代码标准；不新增不必要文件。

***

## 零 · 问题总结（上一轮评估结论）

### 0.1 当前生产退化路径

```
_check_evolution_kline_signal()
  └─ kline_data = {symbol, close, high, low, volume}  ← 仅 5 字段
      └─ KlineEventHandler.on_kline_close()
          ├─ ResistanceVector.calculate()  →  R_up=R_down=0.5, R_refl≤0.66  (3/5 维退化)
          ├─ compute_d_star()              →  d* ≈ WAIT  (wait < 0.5 几乎必然胜出)
          └─ RippleEngine.detect_ripple_source()  →  ess_dir="" → is_source=False → RI=0.50

结果: 0 笔建仓, 0 份 snapshot, 0 次反思 → 闭环空转
```

### 0.2 缺口全景

| R 向量维度 | 所需字段 | 生产提供 | 可获取来源 | 距离 |
|:--|:--|:--|:--|:--|
| R_up/R_down | okx_positions | ❌ | OKX get_positions / panewslab | 1 层适配 |
| R_up/R_down | liquidation_buy/sell | ❌ | panewslab (long/short liq 24h) | 1 层适配 |
| R_up/R_down | ma_200 | ❌ | K线滚动计算 (limit≥200) | 参数调整 |
| R_up/R_down | fib_retrace_0786 | ❌ | K线计算或降级 | 1 层计算 |
| R_smooth | close (≥30根) | ✅ | K线 | 已就绪 |
| R_flow | close + volume (≥20根) | ✅ | K线 | 已就绪 |
| R_reflexivity | news_sentiment_score | ❌ | SentimentEngine.analyze_text() | 1 层桥接 |
| R_reflexivity | bid_ask_spread_bps | ❌ | OKX get_ticker (bid/ask) | 1 层计算 |
| RippleEngine | ess_top_direction | ❌ | strategy_gene.top_combinations_by_ess | 1 层加载 |
| RippleEngine | vol_5 / vol_20 | ❌ | K线尾部 5/20 根均量 | 1 层计算 |
| RippleEngine | liq_index_change | ❌ | panewslab 清算 24h 变化 | 1 层适配 |
| RippleEngine | scale_class | ❌ | 市值分类 (静态映射表) | 1 层映射 |
| RippleEngine | ripples (R1/R2/R3) | ❌ | 关联币构造 | 1 层构造 |
| 修饰子 | sentiment | ❌ | SentimentEngine | 1 层桥接 |
| 修饰子 | capital_flow | ❌ | OKX OI 变化 / panewslab | 1 层计算 |
| 修饰子 | narrative | ❌ | odaily 快讯提取 | 1 层桥接 |

***

## 一 · 架构设计：DataPipelineAdapter

### 1.1 核心新增组件

```
                          ┌─────────────────────────────────────────────────┐
                          │           DataPipelineAdapter                   │
                          │  (新增: dreambuddy_evolution/adapters/)          │
                          ├─────────────────────────────────────────────────┤
                          │                                                  │
  OKX API ──────────────→ │  OKXMarketAdapter                                │
  get_ticker (bid/ask)    │  → bid_ask_spread_bps                            │
  get_kline (limit=200)   │  → close/high/low/volume + ma_200 + vol_5/20    │
  get_positions           │  → okx_positions (long/short ratio)              │
                          │                                                  │
  data_center.db ────────→ │  DataCenterAdapter                               │
  panewslab derivatives   │  → liquidation_buy, liquidation_sell            │
                         │  → liq_index_change, open_interest               │
                          │                                                  │
  SentimentEngine ───────→ │  SentimentBridge                                │
  analyze_text()          │  → news_sentiment_score ∈ [0,1]                  │
                          │                                                  │
  StrategyGene ──────────→ │  ESSDirectionProvider                            │
  load_gene_library()     │  → ess_top_direction (long/short/"")             │
  top_combinations_by_ess │                                                  │
                          │                                                  │
  CognitiveLoopEntry ───→ │  CognitiveBridge (Phase 3)                       │
  recall()                │  → cbr_sim, cbr_top1_outcome                     │
                          │                                                  │
  polling_trader ────────→ │  SubSystemBridge                                 │
  _five_domain_state_cache│  → war_state → scale_temperature T               │
  _infer_bcrm2 direction  │  → bcrm_direction → cross_validate               │
                          │                                                  │
                          └──────────────────┬──────────────────────────────┘
                                             │
                                             ▼
                          assembled kline_data dict (全字段)
                                             │
                                             ▼
                          KlineEventHandler.on_kline_close(kline_data)
```

### 1.2 文件布局

```
23-四层闭环自进化交易架构/dreambuddy_evolution/
├── adapters/                          ← 新增目录
│   ├── __init__.py
│   ├── data_pipeline.py               ← 主装配器 DataPipelineAdapter
│   ├── okx_market.py                  ← OKX 行情适配
│   ├── data_center.py                 ← data_center.db 适配
│   ├── sentiment_bridge.py            ← SentimentEngine 桥接
│   ├── ess_provider.py                ← 策略基因 ESS 方向提供器
│   └── subsystem_bridge.py            ← 子交易系统桥接 (war_state/BCRM)
├── core/
│   ├── resistance_vector.py           (不改)
│   ├── level0_path_cost.py            (不改)
│   └── strategy_gene.py               (不改)
├── engines/
│   ├── kline_event_handler.py         (不改)
│   ├── ripple_engine.py               (不改)
│   ├── reflection_engine.py           (不改)
│   ├── modifiers.py                   (不改)
│   ├── tight_coupling_orchestrator.py  (不改)
│   └── trade_settlement_bridge.py     (不改)
└── tests/
    ├── test_data_pipeline.py          ← 新增
    ├── test_okx_market.py             ← 新增
    ├── test_data_center_adapter.py    ← 新增
    ├── test_sentiment_bridge.py       ← 新增
    ├── test_ess_provider.py           ← 新增
    └── test_subsystem_bridge.py       ← 新增
```

### 1.3 修改清单（最小侵入）

| 文件 | 修改 | 原因 |
|:--|:--|:--|
| `polling_trader.py` `_check_evolution_kline_signal()` | 替换手工 kline_data 构造为 DataPipelineAdapter.assemble() | 核心管线接入点 |
| `polling_trader.py` `__init__` | 懒初始化 DataPipelineAdapter 实例 | 避免每轮重建 |
| `polling_trader.py` K线 limit | 100→200 | ma_200 需要 200 根 |

**不修改任何 evolution 引擎/core 代码。** 所有适配在 adapters 层完成。

***

## 二 · 各适配器详细 Spec

### 2.1 OKXMarketAdapter (`adapters/okx_market.py`)

**职责：** 从 OKX REST API 获取实时行情数据，计算 R 向量所需字段。

**输入：** okx_client 实例（复用 polling_trader 已有的 self.okx_client）

**输出 dict 字段：**

| 输出字段 | 来源 | 计算方式 | 对应 R 向量维度 |
|:--|:--|:--|:--|
| `close` | get_kline(bar=1H, limit=200) | candles[].c 反转为升序 | R_smooth, R_flow |
| `high` | 同上 | candles[].h | (辅助) |
| `low` | 同上 | candles[].l | (辅助) |
| `volume` | 同上 | candles[].vol | R_flow |
| `ma_200` | close 数组计算 | np.mean(close[-200:]) 若 len≥200 否则 NaN | R_up/R_down |
| `fib_retrace_0786` | close 数组计算 | min(close[-200:]) + 0.786×(max-min) | R_up/R_down (降级用) |
| `bid_ask_spread_bps` | get_ticker(inst_id) | (ask-bid)/mid×10000 | R_reflexivity |
| `vol_5` | volume 尾部 5 根 | np.mean(volume[-5:]) | RippleEngine |
| `vol_20` | volume 尾部 20 根 | np.mean(volume[-20:]) | RippleEngine |
| `okx_positions` | get_positions() 或 get_ticker | 见下文 | R_up/R_down |

**okx_positions 获取策略（3 级降级）：**

```
Level 1: self.okx_client.get_positions(inst_id)
         → 解析 long/short 持仓量 → {long: L, short: S}
         ⚠️ OKX get_positions 仅返回当前账户持仓，非全市场持仓

Level 2 (推荐): 从 OKX public API 获取全市场持仓比
         GET /api/v5/public/long-short-ratio?instId={inst_id}&period=1H
         → 解析 longAccount/shortAccount → {long: ratio, short: 1-ratio}
         ⚠ 需在 okx_client 新增方法或 macro_data_fetcher 复用

Level 3 (降级): 从 panewslab fut_coins 提取 long/short liq 比作为代理
         → DataCenterAdapter 提供

FAIL-OPEN: 全部失败 → okx_positions = None → R_up=R_down=0.5 (现状不变)
```

**关键约束：**
- `limit=200` 硬约束（ma_200 计算）
- 每个 API 调用 try/except，失败字段设 None
- 全模块 FAIL-OPEN：不抛异常，返回已获取字段的子集 dict
- K线数据格式转换：OKX candles 降序 → 升序（已有逻辑在 polling_trader 中，抽出为公共方法）

**新增 okx_client 方法（如需）：**

```python
# 在 okx_client.py 新增（或直接在 adapter 内调用 _get）
def get_long_short_ratio(self, inst_id: str, period: str = "1H") -> Dict:
    """OKX 公开多空持仓比接口"""
    r = self._get("/api/v5/public/long-short-ratio",
                  {"instId": inst_id, "period": period}, auth=False)
    # 返回 {ok: True, long_ratio: float, short_ratio: float, ts: str}
```

### 2.2 DataCenterAdapter (`adapters/data_center.py`)

**职责：** 从 data_center.db 查询 panewslab 采集的衍生品数据（清算、OI）。

**输入：** data_center.db 路径（默认 `18-数据获取中心/data_center.db`）

**查询逻辑：**

```python
# 从 data_center.db records 表查询最新 panewslab derivatives 记录
# 表结构: DataRecord(source, category, sub_category, timestamp, metrics, timeseries)
# 查询: SELECT metrics FROM records
#        WHERE source='panewslab' AND sub_category='derivatives_spot'
#        ORDER BY timestamp DESC LIMIT 1
```

**输出 dict 字段：**

| 输出字段 | 来源 | 计算方式 | 对应 R 向量维度 |
|:--|:--|:--|:--|
| `liquidation_buy` | panewslab fut_liq_long_24h_usd | float → 归一化数组 [value] | R_up/R_down |
| `liquidation_sell` | panewslab fut_liq_short_24h_usd | float → 归一化数组 [value] | R_up/R_down |
| `liq_index_change` | panewslab fut_liq_total_24h_usd | 当前 vs 上次查询的变化比 | RippleEngine |
| `open_interest` | panewslab fut_open_interest_usd | float | (修饰子 capital_flow 代理) |

**per-coin 清算数据查询：**

```python
# timeseries 字段含 futures_markets items
# 每项: {symbol, open_interest_usd, liquidation_usd_24h,
#         long_liq_usd_24h, short_liq_usd_24h}
# 按 symbol 匹配 BTC/ETH/SOL → 提取 per-coin 数据
```

**FAIL-OPEN：** 查询失败/表不存在/无数据 → 返回空 dict，R 向量该维度走 0.5 兜底。

**关键约束：**
- DB 查询超时 2s（避免阻塞热路径）
- 查询频率：每轮轮询 1 次（300s 间隔足够）
- 数据新鲜度：panewslab 数据可能有 5-15min 延迟，可接受（24h 累计数据）

### 2.3 SentimentBridge (`adapters/sentiment_bridge.py`)

**职责：** 桥接 SentimentEngine.analyze_text() 输出为 R_reflexivity 所需的 `news_sentiment_score`。

**输入：** odaily 快讯文本（最近 N 条）或直接调用 SentimentEngine

**调用链：**

```
1. 从 data_center.db 查询最近 5 条 odaily_newsflash 快讯文本
   (或从 11-易经推理系统/data/macro_cache/ 查询已缓存的新闻)

2. 对每条文本调用 SentimentEngine.analyze_text(text)
   → {score: float ∈ [-1,+1], sentiment: str, ...}

3. 时间加权聚合:
   score_agg = Σ(score_i × time_decay_weight(age_hours_i)) / Σ(weights)
   → 归一化到 [0, 1]: news_sentiment_score = (score_agg + 1) / 2

4. 输出: news_sentiment_score ∈ [0, 1]
```

**FAIL-OPEN 三级（对齐已有硬约束 VM-1788443193342）：**

```
L0: USE_FINBERT=0 → 规则引擎模式 → score 仍有效，quality 扣 0.15
L1: SentimentEngine 加载失败 → news_sentiment_score = 0.5 (中性)
L2: 单条文本异常 → 该条 score=0.0，其他条继续
L3: data_center.db 查询失败 → news_sentiment_score = 0.5 (中性)
```

**关键约束：**
- SentimentEngine 实例单例化（避免每轮重复加载模型）
- 情绪延迟 >2h 时降级为 0.5（蓝图 §1.10.2 时滞噪音硬约束）
- 不单独驱动 d*，只作为 g_ij 修正项

### 2.4 ESSDirectionProvider (`adapters/ess_provider.py`)

**职责：** 加载策略基因库，计算 ESS 排序，输出 top1 方向。

**这是激活 RippleEngine 的关键——ess_top_direction 为空导致龙头检测和涟漪扩散全部失效。**

**调用链：**

```
1. from dreambuddy_evolution.core.strategy_gene import (
       load_gene_library, top_combinations_by_ess
   )

2. library = load_gene_library(GENE_DATA_ROOT)
   GENE_DATA_ROOT = "23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data"

3. top_combos = top_combinations_by_ess(library, min_sample=30)
   → list of {combo_id, ess, n_samples, condition_ids, action_ids, strategy_type}

4. 从 top_combos[0] 的 action_ids 查找 action gene → 读取 direction 字段
   action JSON schema 含 "direction" ∈ {"long", "short", "neutral"}

5. ess_top_direction = top1_action.direction  ("long"/"short"/"")
```

**输出：**
- `ess_top_direction: str` — "long" / "short" / "" (空=无足够样本或方向中性)
- `ess_top1_id: str` — combo_id
- `ess_top1_score: float` — ESS 值

**关键约束：**
- 基因库加载结果缓存（每 6h 刷新一次，不每轮重载）
- min_sample=30 硬约束（蓝图 §1.4 已冻结）
- 无有效组合 → ess_top_direction="" → RippleEngine 不触发（安全降级）

**当前 gene_data 状态：**
- 28 个 condition + 16 个 action + library.json 组合
- 组合的 n_samples 字段需要填充实际值（当前可能为 0 → min_sample=30 过滤后为空）
- **Phase 0 先用 min_sample=0 降级**：允许样本不足的组合参与排序，ess_top_direction 不为空
- **Phase 1 回填 n_samples**：从 bcrm_trades.db 统计历史交易匹配 condition→action 的频次

### 2.5 SubSystemBridge (`adapters/subsystem_bridge.py`)

**职责：** 桥接 polling_trader 中已有的子交易系统输出。

**这部分不需要新建采集器——polling_trader 已在 run_once 中计算了大量信号，只是没有传递给进化架构。**

**桥接的信号：**

| 信号 | 来源（polling_trader 内） | 用途 | 对应蓝图 |
|:--|:--|:--|:--|
| `war_state` | `self._five_domain_state_cache.war_state["crypto_usdt"]` | Level2 温度 T | §1.5.5 |
| `bcrm_direction` | `_infer_bcrm2()` 输出 `next_state.direction` | d* 交叉验证 | §1.6.3 CS |
| `bcrm_confidence` | `_infer_bcrm2()` 输出 `next_state.confidence` | CBR boost | §0.7.3 |
| `bdsm_valuation` | `_apply_bdsm_scaling` 的 valuation_percentile | R_capital 代理 | §1.9.4 |
| `scale_class` | 静态映射 (BTC=Classical, ETH=Classical, SOL=Meso) | RippleEngine | §0.6 |

**实现方式：**

```python
class SubSystemBridge:
    """从 polling_trader 实例提取子交易系统信号"""

    def __init__(self, trader):
        """trader = PollingTrader 实例（复用其已计算的状态）"""
        self._trader = trader

    def get_war_state(self) -> str:
        """获取五计庙算 war_state → 映射 Level2 温度"""
        try:
            _fds = getattr(self._trader, "_five_domain_state_shadow", None) \
                or getattr(self._trader, "_five_domain_state_cache", None)
            if _fds is None:
                return "ALLOW"
            return _fds.war_state.get("crypto_usdt", "ALLOW")
        except Exception:
            return "ALLOW"  # FO

    def get_ess_temperature(self) -> float:
        """war_state → Feynman 温度 T (蓝图 §1.5.5)"""
        ws = self.get_war_state()
        return {"ALLOW": 1.0, "COOLDOWN": 0.5, "RESTRICT": 0.2,
                "FREEZE": 0.1}.get(ws, 1.0)

    def get_bcrm_direction(self) -> str:
        """获取 BCRM2 最新推理方向"""
        try:
            # 从最近一次 _infer_bcrm2 结果缓存读取
            result = getattr(self._trader, "_last_bcrm2_result", None)
            if result and result.get("next_state"):
                d = result["next_state"].get("direction", "FLAT")
                return {"UP": "long", "DOWN": "short", "FLAT": ""}.get(d, "")
            return ""
        except Exception:
            return ""

    @staticmethod
    def get_scale_class(symbol: str) -> str:
        """市值尺度分类 (蓝图 §0.6)"""
        CLASSICAL = {"BTC", "ETH", "BNB"}
        MESO = {"SOL", "XRP", "ADA", "AVAX", "DOT", "LINK",
                "MATIC", "UNI", "LTC", "NEAR", "ARB", "OP"}
        if symbol in CLASSICAL:
            return "Classical"
        if symbol in MESO:
            return "Meso"
        return "Quantum"
```

**关键约束：**
- 所有读取均 try/except，返回安全默认值
- war_state 影子模式优先读 `_five_domain_state_shadow`（真实计算值）
- BCRM direction 从缓存读取，不触发新推理（避免热路径开销）
- SubSystemBridge 不实例化任何新子系统——只读已有状态

### 2.6 CognitiveBridge (`adapters/cognitive_bridge.py`) — Phase 3

**职责：** 桥接认知记忆系统，实现 CBR 案例检索和经验记录。

**当前 Phase 不实现（Phase 3 ≥2000 样本后解冻），但预留接口。**

**预留接口：**

```python
class CognitiveBridge:
    """认知系统桥接（Phase 3 解冻）"""

    def recall_similar(self, r_vector: dict, action: str) -> dict:
        """从认知记忆库检索相似案例 → cbr_sim, cbr_top1_outcome"""
        # Phase 3: recall(context=f"R_up={r_vector['R_up']}, action={action}")
        return {"cbr_sim": 0.5, "cbr_top1_outcome": "TP"}

    def record_trade(self, snapshot: dict, outcome: dict) -> None:
        """交易结算后记录经验"""
        # Phase 3: record(content=..., quality_level="B", tags=["trade","evolution"])
        pass

    def verify_prediction(self, memory_id: str, success: bool) -> None:
        """验证预测准确性"""
        # Phase 3: verify(memory_id=memory_id, success=success)
        pass
```

***

## 三 · 主装配器 DataPipelineAdapter

### 3.1 接口定义

```python
class DataPipelineAdapter:
    """统一数据管线装配器 — 将所有数据源组装为 KlineEventHandler 所需的 kline_data dict"""

    def __init__(
        self,
        okx_client: Any,                    # polling_trader.okx_client
        trader: Any = None,                 # polling_trader 实例（SubSystemBridge 用）
        data_center_db: str = None,         # data_center.db 路径
        gene_data_root: str = None,         # gene_data 路径
        sentiment_engine: Any = None,       # SentimentEngine 实例（可选注入）
    ):
        ...

    def assemble(self, symbol: str, inst_id: str) -> dict[str, Any]:
        """
        组装完整 kline_data dict。

        返回字典包含以下字段组（任一组失败不影响其他组）:
          - 基础 OHLCV + ma_200 + fib + vol_5/20 (OKXMarketAdapter)
          - bid_ask_spread_bps (OKXMarketAdapter)
          - okx_positions (OKXMarketAdapter)
          - liquidation_buy/sell + liq_index_change (DataCenterAdapter)
          - news_sentiment_score (SentimentBridge)
          - ess_top_direction + ess_top1_id (ESSDirectionProvider)
          - scale_class (SubSystemBridge)
          - bcrm_direction (SubSystemBridge, 交叉验证用)
          - war_state_temperature (SubSystemBridge)
          - ripples (Phase 2: 关联币简化构造)

        FAIL-OPEN: 任一适配器异常 → 该字段缺失 → R 向量该维度走 0.5 兜底
        """
```

### 3.2 装配流程

```
DataPipelineAdapter.assemble(symbol="BTC", inst_id="BTC-USDT-SWAP")
│
├── 1. OKXMarketAdapter.fetch(symbol, inst_id, limit=200)
│      → close[], high[], low[], volume[], ma_200, fib, spread, vol_5, vol_20, okx_positions
│      ⚠ OKX API 调用 ~200ms (get_kline + get_ticker)，可并行
│
├── 2. DataCenterAdapter.query_latest_derivatives()
│      → liquidation_buy, liquidation_sell, liq_index_change, open_interest
│      ⚠ SQLite 查询 <50ms
│
├── 3. SentimentBridge.get_sentiment_score(symbol)
│      → news_sentiment_score
│      ⚠ SentimentEngine.analyze_text() ~100ms/text × 5 texts = ~500ms
│      ⚠ 可降级为缓存模式（每 6h 更新一次情绪）
│
├── 4. ESSDirectionProvider.get_top_direction()
│      → ess_top_direction, ess_top1_id
│      ⚠ 基因库缓存，6h 刷新
│
├── 5. SubSystemBridge.get_*()
│      → scale_class, bcrm_direction, war_state
│      ⚠ 纯内存读取 <1ms
│
├── 6. 构造 ripples (Phase 2 简化版)
│      → {"R1": {"hits": 0, "candidates": 1, "delta_t_hours": 1, "tau": 1.0},
│           "R2": {"hits": 0, "candidates": 1, "delta_t_hours": 4, "tau": 4.0},
│           "R3": {"hits": 0, "candidates": 1, "delta_t_hours": 12, "tau": 12.0}}
│      ⚠ MVP: 全 0 hits → RI=0 → 不触发涟漪（安全）
│      ⚠ Phase 3: 从关联币 K 线计算真实 hits/candidates
│
└── 7. 合并为 kline_data dict → return
```

### 3.3 性能预算

| 步骤 | 耗时（预期） | 频率 | 备注 |
|:--|:--|:--|:--|
| OKXMarketAdapter (kline+ticker) | ~200-300ms | 每 300s | 2 个 API 调用 |
| DataCenterAdapter (DB query) | ~30-50ms | 每 300s | 1 次 SQLite 查询 |
| SentimentBridge | ~300-500ms | 每 300s 或 6h 缓存 | FinBERT 模型推理 |
| ESSDirectionProvider | <1ms（缓存） | 6h 刷新 | 内存读取 |
| SubSystemBridge | <1ms | 每 300s | 内存读取 |
| **总计** | **~550-850ms** | 每 300s | **<1s，不阻塞 300s 轮询** |

**并行优化（可选）：** OKXMarketAdapter 和 DataCenterAdapter 可用 `concurrent.futures.ThreadPoolExecutor` 并行，总耗时降至 ~350ms。

***

## 四 · polling_trader.py 集成改造

### 4.1 改造 `_check_evolution_kline_signal()`

**当前代码（7528-7587 行）：**

```python
# 现状：手工构造 kline_data，仅 5 字段
_kline_data = {
    "symbol": _coin,
    "candles": _candles,
    "close": [c["c"] for c in _candles_asc],
    "high": [c["h"] for c in _candles_asc],
    "low": [c["l"] for c in _candles_asc],
    "volume": [c["vol"] for c in _candles_asc],
}
self._kline_handler.on_kline_close(_kline_data, alpha=0.2, beta=0.2, gamma=0.0)
```

**改造后：**

```python
# 改造：通过 DataPipelineAdapter 装配全字段
_kline_data = self._data_pipeline.assemble(
    symbol=_coin,
    inst_id=f"{_coin}-USDT-SWAP",
)
# kline_data 已包含全部 R 向量所需字段
self._kline_handler.on_kline_close(
    _kline_data,
    alpha=0.2,   # R_narrative 权重（γ=0 因 narrative 数据未就绪）
    beta=0.2,    # R_sentiment 权重
    gamma=0.0,   # R_capital 权重（OKX OI 接入后激活）
)
```

### 4.2 改造 `__init__`

```python
# 在 __init__ 中懒初始化 DataPipelineAdapter
self._data_pipeline = None  # 延迟初始化

def _init_data_pipeline(self):
    """懒初始化数据管线适配器"""
    if self._data_pipeline is not None:
        return
    try:
        import sys as _sys
        _evo_root = str(_PROJECT_ROOT / "23-四层闭环自进化交易架构")
        if _evo_root not in _sys.path:
            _sys.path.insert(0, _evo_root)
        from dreambuddy_evolution.adapters.data_pipeline import DataPipelineAdapter
        self._data_pipeline = DataPipelineAdapter(
            okx_client=self.okx_client,
            trader=self,
            data_center_db=str(_PROJECT_ROOT / "18-数据获取中心" / "data_center.db"),
            gene_data_root=str(_PROJECT_ROOT / "23-四层闭环自进化交易架构"
                               / "dreambuddy_evolution" / "gene_data"),
        )
    except Exception as _e:
        self._log(f"[P2-S4b] DataPipelineAdapter init crash: {_e}", "WARN")
```

### 4.3 不修改的部分

- `KlineEventHandler.on_kline_close()` — 不改，它已设计为接收全字段 dict
- `ResistanceVector.calculate()` — 不改，它已能处理缺失字段（0.5 兜底）
- `_evolution_build_position()` — 不改
- `_trigger_evolution_reflection()` — 不改
- `TradeSettlementBridge` — 不改

***

## 五 · 修饰子激活路线

### 5.1 当前修饰子状态

```
on_kline_close(alpha=0.2, beta=0.2, gamma=0.0)
                               ↑          ↑          ↑
                    R_narrative  R_sentiment  R_capital
                    (narrative)   (sentiment)  (capital_flow)
                    未就绪        部分就绪      未就绪
```

### 5.2 激活时间线

| 阶段 | α (narrative) | β (sentiment) | γ (capital) | 前置条件 |
|:--|:--|:--|:--|:--|
| Phase 0 | 0.0 | 0.0 | 0.0 | 管线打通，验证不 crash |
| Phase 1 | 0.0 | 0.1 | 0.0 | SentimentBridge 1 周 shadow 验证 |
| Phase 2 | 0.0 | 0.2 | 0.1 | OKX OI 接入 + 1 周 shadow |
| Phase 3 | 0.1 | 0.2 | 0.2 | odaily 叙事标签库建设 |

**Phase 0 安全策略：** 即使 DataPipelineAdapter 装配了全字段，alpha=beta=gamma=0.0 意味着修饰子不生效，5 维 R 向量原始值直接进入 d* 计算。这验证管线不引入震荡。

***

## 六 · 涟漪引擎激活策略

### 6.1 Phase 2 涟漪简化

当前 `ripples` 字段为空 → `compute_ri` 返回 0.50 → `inference_formed=False`。

**Phase 2 简化方案（不构建完整涟漪链）：**

```python
# 在 DataPipelineAdapter 中构造简化 ripples
ripples = {
    "R1": {
        "hits": _compute_r1_hit(kline_data),  # 同币 1H 方向一致 = 1
        "candidates": 1,
        "delta_t_hours": 1,
        "tau": 1.0,
    },
    "R2": {
        "hits": _compute_r2_hit(kline_data),  # 关联币 4H 方向一致
        "candidates": 1,
        "delta_t_hours": 4,
        "tau": 4.0,
    },
    "R3": {
        "hits": 0,  # Phase 3 补充板块扩散
        "candidates": 1,
        "delta_t_hours": 12,
        "tau": 12.0,
    },
}
```

**R1 hit 计算：** 当前 K 线收盘方向（close > prev_close）与 d* 方向一致 → hits=1
**R2 hit 计算：** 关联币（BTC→ETH, BTC→SOL）4H 方向一致 → hits=1

**注意：** 即使 hits=1，`RI = 0.4×1×exp(-1/1) + 0.35×0 + 0.25×0 = 0.4×0.368 = 0.147 < 0.55`，仍不触发推断。这是**安全的**——Phase 2 只验证管线不 crash，不期望自动建仓。

### 6.2 龙头检测激活

`detect_ripple_source` 需要 4 个条件同时满足：

| 条件 | Phase 2 可满足？ | 说明 |
|:--|:--|:--|
| ess_dir 一致 | ✅ (ESSDirectionProvider 提供) | 需 ess_top_direction 不为空 |
| vol_5/vol_20 ≥ 2.0 | ✅ (OKXMarketAdapter 计算) | 自然波动时偶尔满足 |
| liq_change ≥ 30% | ⚠️ (panewslab 24h 数据) | 需剧烈行情 |
| scale ≠ Quantum | ✅ (BTC=Classical) | 静态映射 |

Phase 2 预期：龙头检测在极端行情时偶尔触发，RI 在 0.3-0.55 之间，cbr_boost=0.10，不触发 auto_execute。这验证涟漪引擎数据通路正确。

***

## 七 · 认知系统对接（Phase 3 预留）

### 7.1 对接点

| 蓝图位置 | 认知系统操作 | 时机 | 接口 |
|:--|:--|:--|:--|
| §0.7 涟漪写入 | record(趋势涟漪原型) | RI≥0.75 持续 24h | CognitiveBridge.record_ripple() |
| §1.6.3 CBR 先验 | recall(相似案例) | 开仓前 | CognitiveBridge.recall_similar() |
| §1.6.3 反思后 | verify(预测准确性) | 平仓后 CS 计算 | CognitiveBridge.verify_prediction() |
| §1.10 自动标注 | record(带标签样本) | 交易结算 | CognitiveBridge.record_trade() |

### 7.2 接口预留

```python
# adapters/cognitive_bridge.py (Phase 3)
class CognitiveBridge:
    def __init__(self, db_path: str = "4-MEMORY/data/cognitive_memory.db"):
        self._db_path = db_path
        self._entry = None  # CognitiveLoopEntry 实例

    def _ensure_entry(self):
        if self._entry is None:
            from cognitive_loop_entry import CognitiveLoopEntry
            self._entry = CognitiveLoopEntry(storage_path=self._db_path)

    def recall_similar(self, r_vector: dict, action: str) -> dict:
        self._ensure_entry()
        context = f"R_up={r_vector.get('R_up')}, R_down={r_vector.get('R_down')}, action={action}"
        results = self._entry.recall(context, top_k=3, min_quality="C")
        # 提取最相似案例的 outcome 作为 cbr_top1_outcome
        ...

    def record_trade(self, snapshot: dict, outcome: dict) -> None:
        self._ensure_entry()
        content = f"[trade] symbol={snapshot['symbol']} d*={snapshot['level0_dstar']} "
                  f"outcome={outcome.get('real_outcome')} CS={outcome.get('cs')}"
        self._entry.record(content, quality_level="B",
                          tags=["trade", "evolution", "l1-reflection"])
```

***

## 八 · 测试策略

### 8.1 单元测试

| 测试文件 | 覆盖 | 关键用例 |
|:--|:--|:--|
| test_okx_market.py | OKXMarketAdapter | ① kline 200 根获取+格式转换 ② ticker bid/ask spread 计算 ③ ma_200 正确性 ④ API 失败 FO 降级 ⑤ vol_5/vol_20 计算 |
| test_data_center.py | DataCenterAdapter | ① panewslab 查询返回清算数据 ② DB 不存在 FO 降级 ③ 数据过期处理 ④ per-coin 匹配 |
| test_sentiment_bridge.py | SentimentBridge | ① 5 条快讯情绪聚合 ② score[-1,+1]→[0,1] 归一化 ③ SentimentEngine 加载失败 FO ④ USE_FINBERT=0 降级 ⑤ 空快讯 FO |
| test_ess_provider.py | ESSDirectionProvider | ① 基因库加载+ESS 排序 ② top1 direction 提取 ③ n_samples=0 时降级 ④ 库刷新缓存 ⑤ 空 library FO |
| test_subsystem_bridge.py | SubSystemBridge | ① war_state 读取+温度映射 ② BCRM direction 读取 ③ scale_class 映射 ④ 五计庙算 shadow 优先 ⑤ trader=None FO |
| test_data_pipeline.py | DataPipelineAdapter | ① 全字段装配 ② 部分失败降级 ③ 性能 <1s ④ symbol 传递 ⑤ ripples 构造 |

### 8.2 集成测试

```python
def test_pipeline_end_to_end():
    """端到端：DataPipeline → KlineEventHandler → d* ≠ WAIT"""
    adapter = DataPipelineAdapter(okx_client=MockOKXClient(...), ...)
    kline_data = adapter.assemble("BTC", "BTC-USDT-SWAP")

    # 断言：至少 3 个 R 维度脱离 0.5 退化态
    rv = ResistanceVector().calculate("BTC", kline_data)
    non_degraded = sum(1 for d in ["R_up","R_down","R_smooth","R_flow","R_reflexivity"]
                       if abs(rv[d] - 0.5) > 0.01)
    assert non_degraded >= 3, f"仅 {non_degraded}/5 维脱离退化态"

    # 断言：d* 不恒为 WAIT
    d_star = compute_d_star(rv)
    # d* 可能是 long/short/WAIT，但不应在数据充分时恒为 WAIT
    # 至少验证 confidence > 0（非平凡解）
    assert d_star["confidence"] > 0.0
```

### 8.3 Shadow 验证（1 周）

- Phase 0 上线后 1 周内，记录每次 `assemble()` 输出的 R 向量和 d*
- 统计指标：
  - R_up/R_down 脱离 0.5 的比例（目标 >80%）
  - d* ≠ WAIT 的比例（目标 >30%）
  - DataPipelineAdapter crash 次数（目标 0）
  - 平均装配耗时（目标 <1s）
- 不触发 auto_execute（alpha=beta=gamma=0.0 + RI<0.55）

***

## 九 · 分阶段实施

### Phase 0：管线打通（最小可用）

| 任务 | 产出 | 验证标准 |
|:--|:--|:--|
| 新建 adapters/ 目录 + __init__.py | 目录结构 | import 不报错 |
| 实现 OKXMarketAdapter | okx_market.py | kline+ticker+ma_200+spread+vol_5/20 |
| 实现 DataCenterAdapter | data_center.py | liquidation+OI 查询 |
| 实现 SubSystemBridge | subsystem_bridge.py | war_state+bcrm_direction+scale_class |
| 实现 ESSDirectionProvider | ess_provider.py | ess_top_direction 不为空 |
| 实现 SentimentBridge (缓存模式) | sentiment_bridge.py | news_sentiment_score ∈[0,1] |
| 实现 DataPipelineAdapter | data_pipeline.py | assemble() 全字段输出 |
| 改造 polling_trader._check_evolution_kline_signal | polling_trader.py | 调用 adapter.assemble() |
| 单元测试 6 个 | tests/test_*.py | 全绿 |
| Shadow 运行 1 周 | 日志统计 | R 维度退化率 <20%，crash=0 |

### Phase 1：修饰子激活

| 任务 | 前置条件 |
|:--|:--|
| 激活 beta=0.1 (R_sentiment) | Phase 0 shadow 验证通过 |
| 接入 OKX long-short-ratio API | okx_client 新增方法 |
| 激活 gamma=0.1 (R_capital) | OKX OI 数据接入 + 1 周 shadow |

### Phase 2：涟漪激活

| 任务 | 前置条件 |
|:--|:--|
| 实现 R1/R2 hit 计算 | Phase 1 稳定 |
| 实现 ripples 字段构造 | 关联币 K 线获取 |
| 观察 RI 分布 | 1 周统计 |
| 激活 alpha=0.1 (R_narrative) | odaily 叙事标签库 |

### Phase 3：认知系统对接

| 任务 | 前置条件 |
|:--|:--|
| 实现 CognitiveBridge | ≥2000 交易样本 |
| CBR 案例检索 | cognitive_memory.db 对接 |
| 涟漪原型写入知识库 | RI≥0.75 事件 ≥3 次 |
| 自动标注闭环 | L3/L4 解冻 |

***

## 十 · 硬约束清单

1. **FAIL-OPEN 铁律**：DataPipelineAdapter 及所有子适配器**永不抛异常**。任一数据源失败 → 该字段缺失 → R 向量该维度走 0.5 兜底。绝不阻塞交易主循环。

2. **不修改 evolution core/engines**：所有适配在 adapters/ 层完成。KlineEventHandler/ResistanceVector/RippleEngine/ReflectionEngine/Level0PathCost 代码不动。

3. **K 线 limit=200 硬约束**：ma_200 计算需要 200 根 K 线。limit=100 导致 ma_200=NaN → fib 降级 → trend_bias 可能失效。

4. **修饰子权重上限 [0, 0.2]**：alpha/beta/gamma 不得超过 0.2（蓝图 §1.9.6 已冻结）。

5. **ESS min_sample=30 不可降低**（Phase 0 降级用 min_sample=0 除外，需标注为临时降级）。

6. **war_state=FREEZE 时探索自动停止**（蓝图 §0.5.3 已冻结）。

7. **认知系统 Phase 3 解冻**：L3 ShadowRL/L4 Bellman 需 ≥2000 (s,a,R,s') 样本（蓝图 §1.5.5 已冻结）。

8. **性能预算 <1s**：assemble() 总耗时不得超过 1s（300s 轮询间隔的 0.3%）。

9. **SentimentEngine 三层 FAIL-OPEN 对齐**（VM-1788443193342 硬约束）：L0 USE_FINBERT=0 → quality 扣 0.15；L1 加载失败 → 持续降级；L2 单条异常 → sent=0.5。

10. **不新建不必要文件**：adapters/ 目录下仅 6 个 .py + 1 个 __init__.py + 6 个 test 文件 = 13 个新文件，每个都有明确职责。

***

## 十一 · 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|:--|:--|:--|:--|
| OKX long-short-ratio API 未在 okx_client 中 | 高 | R_up/R_down 仍退化 | Phase 0 用 panewslab 代理；Phase 1 补 API |
| SentimentEngine 模型加载慢 (>2s) | 中 | 装配超 1s 预算 | 缓存模式：6h 更新一次 score |
| gene_data 组合 n_samples=0 | 高 | ESS 排序为空 | Phase 0 降级 min_sample=0；Phase 1 回填 |
| panewslab 数据延迟 >15min | 低 | 清算数据不够实时 | 24h 累计数据，延迟可接受 |
| data_center.db 表结构变更 | 低 | 查询失败 | DataCenterAdapter FO 降级 |
| 装配耗时 >1s | 低 | 阻塞轮询 | 并行优化 + 缓存 |
| 修饰子引入震荡 | 中 | d* 不稳定 | Phase 0 alpha=beta=gamma=0 验证 |
| R_up/R_down 仍恒为 0.5 | 中 | d* 仍为 WAIT | 需验证 okx_positions 数据通路 |

***

## 十二 · 验收标准

### Phase 0 验收（Shadow 运行 1 周后）

| 指标 | 目标 | 统计方法 |
|:--|:--|:--|
| DataPipelineAdapter crash 次数 | 0 | 日志 grep "DataPipeline.*crash" |
| assemble() 平均耗时 | <1s | 日志 timing 统计 |
| R_up 脱离 0.5 的比例 | >70% | 采样 R 向量输出 |
| R_down 脱离 0.5 的比例 | >70% | 同上 |
| R_reflexivity 脱离 0.5 的比例 | >50% | 同上（sentiment 数据依赖） |
| R_smooth 正常分布 | 均值 ∈[0.2, 0.8] | 采样统计 |
| R_flow 正常分布 | 均值 ∈[0.2, 0.8] | 采样统计 |
| d* ≠ WAIT 的比例 | >20% | Level0 输出统计 |
| ess_top_direction 不为空 | 100% | 每次装配日志 |
| auto_execute 触发次数 | 0 | Phase 0 安全验证 |
| 单元测试 | 6/6 文件全绿 | pytest |

### 能力落地验收

| 能力 | 验收标准 | 对应核心目的 |
|:--|:--|:--|
| **识别最优路径** | d* 在数据充分时输出 long/short 而非恒 WAIT | 从多数据源中识别方向 |
| **计算最小阻力** | R 向量 5 维至少 3 维脱离 0.5 退化态 | 阻力场可计算 |
| **数据库连接** | DataCenterAdapter 成功查询 panewslab 数据 | 数据库 → R 向量 |
| **知识库连接** | ESSDirectionProvider 输出非空 ess_top_direction | 知识库 → 涟漪引擎 |
| **认知系统连接** | (Phase 3) CognitiveBridge recall/record 可用 | 认知系统 → CBR |
| **子交易系统连接** | SubSystemBridge 输出 war_state + bcrm_direction | 子系统 → 交叉验证 |
| **闭环运转** | RI ≥ 0.55 偶尔触发 + snapshot 持久化 | 涟漪 → 建仓 → 反思 → 学习 |
