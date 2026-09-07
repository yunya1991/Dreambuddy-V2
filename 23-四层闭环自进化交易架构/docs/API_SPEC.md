# 23-四层闭环自进化交易架构 — 接口规格

> **版本**: v1.0 | **更新日期**: 2026-09-07
> **定位**: 模块级接口规格，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md)

---

## 1. KlineEventHandler

**文件**: `engines/kline_event_handler.py`

### 1.1 构造函数

```python
KlineEventHandler(
    mode: str = "MVP",                    # "MVP" | "Phase2"
    build_position_callback: Any = None,   # Phase2 建仓回调
    settlement_bridge: Any = None,          # TradeSettlementBridge
    ripple_kwargs: dict | None = None,     # RippleEngine 门槛参数
    reflection_scanner: Any = None,        # ReflectionScanner
    project_root: str | None = None,        # 项目根目录
)
```

### 1.2 on_kline_close

```python
def on_kline_close(
    kline_data: dict[str, Any],
    alpha: float = 0.0,   # 资金流修饰子权重 [0, 0.2]
    beta: float = 0.0,    # 情绪修饰子权重 [0, 0.2]
    gamma: float = 0.0,   # 叙事修饰子权重 [0, 0.2]
) -> dict[str, Any]
```

**输入 `kline_data` 字段**:

| 字段 | 类型 | 来源 | 必需 |
|:---|:---|:---|:---|
| symbol | str | DataPipelineAdapter | ✅ |
| close | list[float] | OKXMarketAdapter | ✅ |
| high | list[float] | OKXMarketAdapter | ✅ |
| low | list[float] | OKXMarketAdapter | ✅ |
| volume | list[float] | OKXMarketAdapter | ✅ |
| ma_200 | float | OKXMarketAdapter | R_up/down |
| fib_retrace_0786 | float | OKXMarketAdapter | R_up/down降级 |
| bid_ask_spread_bps | float | OKXMarketAdapter | R_reflexivity |
| vol_5 | float | OKXMarketAdapter | RippleEngine |
| vol_20 | float | OKXMarketAdapter | RippleEngine |
| okx_positions | dict{long,short} | OKXMarketAdapter | R_up/down |
| liquidation_buy | list[float] | DataCenterAdapter | R_up/down |
| liquidation_sell | list[float] | DataCenterAdapter | R_up/down |
| liq_index_change | float | DataCenterAdapter | RippleEngine |
| news_sentiment_score | float [0,1] | SentimentBridge | R_reflexivity |
| sentiment | float [0,1] | SentimentBridge | 修饰子 |
| ess_top_direction | str "long"/"short"/"" | ESSDirectionProvider | RippleEngine |
| scale_class | str "Classical"/"Meso"/"Quantum" | SubSystemBridge | RippleEngine |
| ripples | dict{R1,R2,R3} | RippleDataProvider | RippleEngine RI |
| regime | str | TraditionalFinanceBridge | 仓位乘数 |
| capital_flow | float [-1,1] | CapitalRotationAdapter | 修饰子 |
| capital_rotation | float [-1,1] | CapitalRotationAdapter | 修饰子增强 |

**输出**:

```python
{
    "symbol": str,
    "r_vector": dict,           # 9字段: R_up, R_down, R_smooth, R_flow, R_reflexivity, quality_score, ...
    "d_star": str,              # "long" | "short" | "WAIT"
    "action": str,              # "long" | "short" | "WAIT"
    "ri": float,                # [0, 1] 最终RI
    "ripple_ri": float,         # 涟漪RI
    "reflection_ri": float,     # 反思RI
    "reflection_eligible": bool,
    "signal_source": str,       # "ripple" | "reflection"
    "tier": str,                # "probe" | "standard" | "trend" | "none"
    "position_mult": float,     # base_tier × regime_mult
    "regime": str,
    "regime_position_mult": float,
    "modifiers_applied": bool,
    "auto_execute": bool,        # Phase2 only
    "inference_formed": bool,
    "is_ripple_source": bool,
}
```

### 1.3 建仓回调签名

```python
build_position_callback(
    symbol: str,
    action: str,        # "long" | "short"
    u_open: float,      # 仓位乘数 (0.4/0.7/1.0 × regime_mult)
    d_star: str,        # Level0 方向
    confidence: float,  # = ri
    tier: str,          # "probe" | "standard" | "trend"
)
```

---

## 2. RippleEngine

**文件**: `engines/ripple_engine.py`

### 2.1 构造函数

```python
RippleEngine(
    vol_ratio_threshold: float = 2.0,    # 放量倍数门槛
    liq_change_threshold: float = 0.30,  # 清算变化率门槛
)
```

### 2.2 detect_ripple_source

```python
def detect_ripple_source(source: dict[str, Any]) -> bool
```

**输入**:
```python
{
    "symbol": str,
    "r_vector": dict,               # R_up, R_down, ...
    "ess_top_direction": str,       # "long" | "short" | ""
    "vol_5": float,
    "vol_20": float,
    "liq_index_change": float,
    "scale_class": str,             # "Classical" | "Meso" | "Quantum"
}
```

### 2.3 compute_ri

```python
def compute_ri(ripples: dict[str, Any]) -> float
```

**输入**:
```python
{
    "R1": {"hits": int, "candidates": int, "delta_t_hours": float, "tau": float},
    "R2": {"hits": int, "candidates": int, "delta_t_hours": float, "tau": float},
    "R3": {"hits": int, "candidates": int, "delta_t_hours": float, "tau": float},
}
```

**返回**: RI ∈ [0, 1]，空ripples → 0.50

### 2.4 get_ri_action

```python
def get_ri_action(ri: float) -> dict[str, Any]
```

**返回**: `{"cbr_boost": float, "ess_temp_mult": float, "trigger_a2": bool}`

---

## 3. ReflectionScanner

**文件**: `engines/reflection_scanner.py`

### 3.1 构造函数

```python
ReflectionScanner(
    trades_path: str | None = None,     # 已废弃，保留兼容
    project_root: str | None = None,     # 项目根目录
)
```

### 3.2 scan

```python
def scan(force: bool = False) -> dict[str, dict[str, Any]]
```

**返回**:
```python
{
    "BTC": {
        "win_rate": float,
        "n_trades": int,
        "avg_pnl_pct": float,
        "reflection_ri": float,        # [0.50, 0.80]
        "eligible": bool,
        "sources": {"bcrm": int, "evolution": int, ...},
    },
    ...
}
```

### 3.3 get_coin_stats

```python
def get_coin_stats(symbol: str, force: bool = False) -> dict[str, Any]
```

**返回**: 同scan单个币种结果，无数据时返回默认值

---

## 4. TradeIndexBuilder

**文件**: `engines/trade_index_builder.py`

### 4.1 构造函数

```python
TradeIndexBuilder(
    project_root: str | Path | None = None,
    index_path: str | Path | None = None,  # 默认 .workbuddy/trade_index/all_trades_index.jsonl
)
```

### 4.2 get_trades

```python
def get_trades(force: bool = False) -> list[dict[str, Any]]
```

**返回**: 交易记录列表，每条含:
```python
{
    "trade_id": str,
    "coin": str,
    "inst_id": str,
    "direction": str,
    "entry_price": float,
    "exit_price": float,
    "pnl": float,
    "pnl_pct": float,
    "source_system": str,
    "entry_time": str,
    "exit_time": str,
}
```

### 4.3 build_index

```python
def build_index(force: bool = False) -> dict[str, Any]
```

**返回**: `{"total_trades": int, "sources": list, "coins": int}`

---

## 5. ReflectionEngine

**文件**: `engines/reflection_engine.py`

### 5.1 create_snapshot

```python
def create_snapshot(
    symbol: str, u_open: float, action: str,
    level0_dstar: str, ess_id: str, ess_dir: str,
    cbr_sim: float, cbr_top1_outcome: str, cluster_id: str,
) -> dict[str, Any]
```

### 5.2 calculate_cs

```python
def calculate_cs(snapshot: dict, outcome: dict) -> float
```

**outcome输入**: `{"real_direction": str, "real_outcome": str}` (TP/SL)

**返回**: CS ∈ [-1.0, +1.0]

### 5.3 apply_reward

```python
def apply_reward(cs: float, outcome: str, cluster_id: str, ess_id: str, gmax: float) -> dict[str, Any]
```

**返回**: `{"ess_delta": float, "gmax_mult": float, "cluster_weight_mult": float, "anti_pattern_flag": bool}`

---

## 6. TradeSettlementBridge

**文件**: `engines/trade_settlement_bridge.py`

### 6.1 store_snapshot

```python
def store_snapshot(symbol: str, snapshot: dict) -> None
```

### 6.2 retrieve_snapshot

```python
def retrieve_snapshot(symbol: str) -> dict | None
```

### 6.3 on_trade_settled

```python
def on_trade_settled(trade_rec: Any) -> dict[str, Any]
```

**trade_rec属性**: `direction`, `pnl`, `symbol`/`inst_id`

**返回**: `{"cs": float, "ess_delta": float, "gmax_mult": float, "cluster_weight_mult": float, "anti_pattern_flag": bool}`

---

## 7. DataPipelineAdapter

**文件**: `adapters/data_pipeline.py`

### 7.1 构造函数

```python
DataPipelineAdapter(
    okx_client: Any,
    trader: Any = None,
    data_center_db: str | None = None,
    gene_data_root: str | None = None,
    sentiment_engine: Any = None,
    min_sample: int = 0,           # Phase0 降级
    cognitive_db: str | None = None,
    cognitive_enabled: bool = False, # Phase3 解冻
)
```

### 7.2 assemble

```python
def assemble(symbol: str, inst_id: str) -> dict[str, Any]
```

**返回**: KlineEventHandler.on_kline_close 所需的 kline_data dict

---

## 8. CoinScanner

**文件**: `adapters/coin_scanner.py`

### 8.1 scan_top_coins

```python
def scan_top_coins(top_n: int = 50) -> list[dict[str, Any]]
```

**返回**: `[{"symbol": str, "inst_id": str, "volume_usdt": float, "is_us_stock": bool}, ...]`

**常量**:
- `US_STOCK_COINS`: 130+ 美股代币白名单
- `US_STOCK_RATIO = 0.5`: 美股配额50%
- 美股成交量门槛: 300K USDT
- 加密成交量门槛: 5M USDT

---

## 9. ResistanceVector

**文件**: `core/resistance_vector.py`

### 9.1 calculate

```python
def calculate(symbol: str, data: dict[str, Any]) -> dict[str, Any]
```

**返回**:
```python
{
    "R_up": float,           # [0, 1]
    "R_down": float,         # [0, 1]
    "R_smooth": float,        # [0, 1]
    "R_flow": float,          # [0, 1]
    "R_reflexivity": float,   # [0, 1]
    "quality_score": float,   # [0, 1]
    "flags": dict,            # 降级标记
}
```

---

## 10. Level0 路径代价

**文件**: `core/level0_path_cost.py`

### 10.1 compute_d_star

```python
def compute_d_star(r_vector: dict) -> dict[str, Any]
```

**返回**:
```python
{
    "d_star": str,         # "long" | "short" | "WAIT"
    "costs": dict,          # {"long": float, "short": float, "wait": float}
    "confidence": float,   # [0, 1]
}
```

### 10.2 compute_g_diag

```python
def compute_g_diag(r_vector: dict) -> np.ndarray  # 5×5 对角阵
```

---

## 11. 策略基因库 API

**文件**: `core/strategy_gene.py`

### 11.1 load_gene_library

```python
def load_gene_library(root: str | Path) -> dict[str, Any]
```

**返回**: `{"conditions": list, "actions": list, "combinations": list, "counts": dict}`

### 11.2 calculate_ess

```python
def calculate_ess(combination_meta: dict) -> float  # [0, 1]
```

### 11.3 top_combinations_by_ess

```python
def top_combinations_by_ess(library: dict, min_sample: int = 30) -> list[dict]
```

### 11.4 search_genes_by_category

```python
def search_genes_by_category(root: str | Path, category: str) -> list[str]
```

---

## 12. 紧耦合编排器

**文件**: `engines/tight_coupling_orchestrator.py`

```python
TightCouplingOrchestrator(mode: str = "MVP")
```

| 方法 | 输入 | 输出 |
|:---|:---|:---|
| `observe(market_data)` | dict | `{ri, is_ripple_source, ess_top_direction}` |
| `hypothesize(obs)` | dict | `{inference_formed, ri, cbr_boost, ess_temp_mult}` |
| `experiment(r_vector, hyp, symbol, ess_id, cbr_sim, cluster_id)` | dict | `{action, u_open, d_star, pre_trade_snapshot}` |
| `measure(exp, outcome_direction, outcome_result)` | dict | `{real_direction, real_outcome, u_open}` |
| `reflect(snapshot, measure)` | dict | `{cs, ess_delta, gmax_mult, cluster_weight_mult}` |
| `learn(refl)` | dict | `{ess_delta, gmax_mult, anti_pattern_flag}` |
| `feedback(learned)` | dict | `{ess_delta, updated_ess_direction, gmax_updated}` |

---

## 13. EvolutionPipeline

**文件**: `evolution_pipeline.py`

```python
EvolutionPipeline(gene_root: Path | str | None = None)
```

### run_symbol

```python
def run_symbol(symbol: str, market_data: dict, rv=None) -> dict[str, Any]
```

**返回**:
```python
{
    "symbol": str,
    "l1_r_vector": dict,
    "level0_d_star": str,
    "level0_confidence": float,
    "level0_costs": dict,
    "l2_top_combo": dict | None,
    "aligned": bool,
    "action": str,
    "l3_sample_count": int,
    "l4_v": float,
}
```

---

**文档版本**: v1.0
**最后更新**: 2026-09-07
