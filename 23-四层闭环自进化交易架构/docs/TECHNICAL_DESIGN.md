# 23-四层闭环自进化交易架构 — 技术设计

> **版本**: v1.0 | **更新日期**: 2026-09-07
> **定位**: 模块级技术设计文档，对齐 [四层闭环进化架构-最小阻力路径总览.md](../../2-KNOWLEDGE/1-TRADING/四层闭环进化架构-最小阻力路径总览.md)

---

## 1. 架构总览

### 1.1 设计哲学

本模块实现 **四层闭环自进化交易架构**：观察→推断→实验→反思→回馈，对应科学方法闭环：

```
观察（RippleEngine + ReflectionScanner）
  → 推断（Level0 d* + ESS对齐）
    → 实验（三层仓位建仓 + SL/TP兜底）
      → 测量（TP/SL结算）
        → 反思（CS一致性 → ESS奖惩）
          → 学习（ESS delta + gmax更新）
            → 回馈（ESS → 下一轮检测）
```

### 1.2 四层架构

| 层 | 名称 | 代码入口 | 职责 |
|:---|:---|:---|:---|
| L1 | 状态空间层 | `core/resistance_vector.py` | 5维阻力向量 R = (R_up, R_down, R_smooth, R_flow, R_reflexivity) 实时计算 |
| Level0 | 路径代价层 | `core/level0_path_cost.py` | d* = argmin 代价方向（long/short/WAIT） |
| L2 | 策略知识层 | `core/strategy_gene.py` | 策略基因库加载 + ESS排序 + top1方向 |
| L3 | 影子RL层 | `core/shadow_rl.py` | (s,a,R,s') 样本记录 + Sharpe stub |
| L4 | 最优目标层 | `core/bellman_tracker.py` | V(s) TD(0) 时序差分更新 |

### 1.3 双起点触发机制（2026-09-06 增强）

```
起点1: RippleEngine（外察式）         起点2: ReflectionScanner（内省式）
  涟漪检测 → ripple_ri                  历史胜率 → reflection_ri
       │                                    │
       └───────── ri = max(ripple_ri, reflection_ri) ─────────┘
                                  │
                          三层仓位分级
                  probe(0.40) / standard(0.55) / trend(0.70)
```

### 1.4 紧耦合7步闭环

`TightCouplingOrchestrator` 串联7步：

| 步骤 | 方法 | 输入 | 输出 |
|:---|:---|:---|:---|
| ① 观察 | `observe()` | market_data | `{ri, is_ripple_source, ess_top_direction}` |
| ② 推断 | `hypothesize()` | obs | `{inference_formed, ri, cbr_boost, ess_temp_mult}` |
| ③ 实验 | `experiment()` | r_vector, hyp | `{action, u_open, d_star, pre_trade_snapshot}` |
| ④ 测量 | `measure()` | exp, outcome | `{real_direction, real_outcome, u_open}` |
| ⑤ 反思 | `reflect()` | snapshot, measure | `{cs, ess_delta, gmax_mult, cluster_weight_mult}` |
| ⑥ 学习 | `learn()` | refl | `{ess_delta, gmax_mult, anti_pattern_flag}` |
| ⑦ 回馈 | `feedback()` | learned | `{ess_delta, updated_ess_direction, gmax_updated}` |

---

## 2. 核心组件设计

### 2.1 KlineEventHandler — K线事件处理器

**文件**: `engines/kline_event_handler.py`

**核心方法**: `on_kline_close(kline_data, alpha, beta, gamma) -> dict`

**处理流程**:

1. **L1 R向量计算**: `ResistanceVector.calculate(symbol, kline_data)` → 9字段dict
2. **三修饰子应用**: 情绪(α)/资金流(β)/叙事(γ)，权重上限[0, 0.2]
3. **Level0 d* 计算**: `compute_d_star(r_vector)` → long/short/WAIT
4. **起点1 - 涟漪RI**: `RippleEngine.detect_ripple_source()` + `compute_ri()`
5. **起点2 - 反思RI**: `ReflectionScanner.get_coin_stats(symbol)` → reflection_ri
6. **双起点聚合**: `ri = max(ripple_ri, reflection_ri)`
7. **三层仓位分级**:

| 层级 | RI范围 | position_mult | 场景 |
|:---|:---|:---|:---|
| probe | 0.40 ≤ ri < 0.55 | 0.4 | 轻仓试探（探索） |
| standard | 0.55 ≤ ri < 0.70 | 0.7 | 标准仓 |
| trend | ri ≥ 0.70 | 1.0 | 趋势加仓（利用） |

8. **Regime乘数**: STRONG_TREND_BULL ×1.20, TREND_BULL ×1.05, BREAKOUT ×1.10, RANGING ×0.80, CONSOLIDATION ×0.70, STRONG_TREND_BEAR ×0.35, TREND_BEAR ×0.50
9. **Phase2自动执行**: `build_position_callback(symbol, action, u_open, d_star, confidence, tier)`

**输出字段**:

```python
{
    "symbol", "r_vector", "d_star", "action",
    "ri", "ripple_ri", "reflection_ri", "reflection_eligible",
    "signal_source",  # "ripple" | "reflection"
    "tier",           # "probe" | "standard" | "trend" | "none"
    "position_mult", "regime", "regime_position_mult",
    "modifiers_applied", "auto_execute", "inference_formed",
    "is_ripple_source",
}
```

### 2.2 RippleEngine — 涟漪扩散引擎

**文件**: `engines/ripple_engine.py`

**龙头检测** (`detect_ripple_source`):
- 方向一致: R_up < R_down (上涨有利) ↔ ess_dir == "long"
- 放量: vol_5/vol_20 ≥ `vol_ratio_threshold` (默认2.0，训练期1.3)
- 清算上升: liq_index_change ≥ `liq_change_threshold` (默认0.30)
- Scale排除: Quantum级排除

**RI计算** (`compute_ri`):
```
RI = 0.4·score₁ + 0.35·score₂ + 0.25·score₃
score_i = (hits/candidates) · exp(−Δt / τ)
```
FAIL-OPEN: 空ripples → RI=0.50

**RI阈值动作表** (`get_ri_action`):

| RI范围 | cbr_boost | ess_temp_mult | trigger_a2 |
|:---|:---|:---|:---|
| <0.30 | 0.0 | 1.0 | False |
| 0.30-0.55 | 0.10 | 1.0 | False |
| 0.55-0.75 | 0.20 | 1.05 | False |
| ≥0.75 | 0.25 | 1.10 | True |

### 2.3 ReflectionScanner — 反思学习扫描器

**文件**: `engines/reflection_scanner.py`

**数据源**: `TradeIndexBuilder`（系统级交易索引库，自动发现JSONL+SQLite）

**统计逻辑**:
- 按币种分组，只统计最近90天交易
- 计算win_rate, n_trades, avg_pnl_pct, sources分布

**reflection_ri 映射**:
```
base_ri = 0.5 + max(0.0, win_rate - 0.5) × 2 × 0.3  (上限0.80)
sample_discount = 0.72 + (n-1)×0.14  (n<3时), 1.0 (n≥3)
reflection_ri = 0.5 + (base_ri - 0.5) × sample_discount
```

| win_rate | n=1 | n=2 | n≥3 |
|:---|:---|:---|:---|
| 0.5 | 0.50 | 0.50 | 0.50 |
| 0.6 | 0.543 | 0.551 | 0.56 |
| 0.7 | 0.587 | 0.601 | 0.62 |
| 1.0 | 0.716 | 0.747 | 0.80 |

**触发门槛**: `MIN_WIN_RATE=0.55`, `MIN_TRADES=1`

### 2.4 TradeIndexBuilder — 系统级交易索引库

**文件**: `engines/trade_index_builder.py`

**自动发现机制**:
- 扫描项目目录（限深度5层），排除node_modules/.git等
- JSONL: 读首3行，检查含≥4个交易特征字段
- SQLite: 检查trades/closed_trades/trade_history表
- 已知源: `all_trades.jsonl` (bcrm), `all_trades_archived_*.jsonl` (bcrm_archive)

**统一字段**: trade_id, coin, inst_id, direction, entry_price, exit_price, pnl, pnl_pct, source_system

**去重**: 按 trade_id 去重

**索引库路径**: `.workbuddy/trade_index/all_trades_index.jsonl`

**缓存**: 构建缓存TTL=300s，发现缓存TTL=3600s

### 2.5 ResistanceVector — L1 5维阻力向量

**文件**: `core/resistance_vector.py`

**5维定义**:

| 维度 | 含义 | 输入字段 | 计算 |
|:---|:---|:---|:---|
| R_up | 上涨阻力 | okx_positions, liquidation_sell, ma_200, fib | 筹码5:3:2加权 |
| R_down | 下跌阻力 | okx_positions, liquidation_buy, ma_200, fib | 筹码5:3:2加权 |
| R_smooth | 平滑度 | close[] (≥30根) | 波动率归一化 |
| R_flow | 流动性 | close+volume (≥20根) | 量价分析 |
| R_reflexivity | 反身性 | news_sentiment_score, bid_ask_spread_bps | 4:3:3加权(corr:liq:sent) |

**FAIL-OPEN三级**:
- FO-1: 单维NaN → 0.50（quality扣0.15pp）
- FO-2: ≥3维降级 → quality×0.4 + Lark ERROR
- FO-3: 全局崩溃 → stale cache（1h TTL）或全0.50 + Lark CRITICAL

### 2.6 Level0 路径代价

**文件**: `core/level0_path_cost.py`

**公式**:
```
d* = argmin_{d ∈ {long, short, WAIT}} [d^T · g_MVP · d]
  多开代价 = g_up = R_up
  空开代价 = g_down = R_down
  WAIT代价 = R_smooth × R_reflexivity

g_MVP = diag(R_up, R_down, R_smooth, R_flow, R_reflexivity)
```

**confidence** = 1 - (min_cost / sum_costs)

### 2.7 ReflectionEngine — 反思引擎

**文件**: `engines/reflection_engine.py`

**CS一致性得分**:
```
CS = 0.4·cos(d*, real) + 0.3·cos(ESS, real) + 0.3·sign_match(CBR, real)
```
- cos(预测,实际): 同向+1, WAIT=0, 反向-1
- CS ∈ [-1.0, +1.0]

**四维奖惩表**:

| 条件 | ESS delta | gmax mult | cluster mult |
|:---|:---|:---|:---|
| CS≥0.7 & TP | +0.02 | ×1.0 | ×1.0 |
| -0.2≤CS<0.7 | 0.0 | ×1.0 | ×1.0 |
| CS≤-0.2 & SL | -0.05 | ×0.5 | ×0.8 |
| CS≤-0.2 & TP | 0.0 (反例保护) | ×1.0 | ×1.0 |
| CS≥0.7 & SL | 0.0 (假失败) | ×1.2 | ×0.5 |

### 2.8 三修饰子

**文件**: `engines/modifiers.py`

| 修饰子 | 权重 | 公式 | 约束 |
|:---|:---|:---|:---|
| R_sentiment | β∈[0,0.2] | 非线性80/20逆向（极度贪婪减/恐慌加） | crash→原值 |
| R_capital | α∈[0,0.2] | 资金流方向修正 | 三角验证必跑 |
| R_narrative | γ∈[0,0.2] | 叙事驱动力增强 | 不计入g_diag |

**硬约束**: 修饰子不进入 g_diag 对角阵（永久5×5）

### 2.9 TradeSettlementBridge — 平仓反思桥接

**文件**: `engines/trade_settlement_bridge.py`

**流程**:
1. `store_snapshot(symbol, snapshot)` — 开仓时持久化pre_trade_snapshot
2. 平仓时 `on_trade_settled(trade_rec)`:
   - 检索snapshot（或降级重建）
   - 提取real_direction, real_outcome (TP/SL)
   - 调用 `ReflectionEngine.calculate_cs()` → `apply_reward()`
   - 返回 `{cs, ess_delta, gmax_mult, cluster_weight_mult}`

---

## 3. 数据管线架构

### 3.1 DataPipelineAdapter

**文件**: `adapters/data_pipeline.py`

**装配流程** (`assemble(symbol, inst_id) -> dict`):

| 步骤 | 适配器 | 输出字段 | 耗时 |
|:---|:---|:---|:---|
| 1 | OKXMarketAdapter | close[], high[], low[], volume[], ma_200, fib, spread, vol_5/20, okx_positions | ~200-300ms |
| 2 | DataCenterAdapter | liquidation_buy/sell, liq_index_change, open_interest | ~30-50ms |
| 3 | SentimentBridge | news_sentiment_score | ~300-500ms |
| 4 | ESSDirectionProvider | ess_top_direction, ess_top1_id | <1ms（缓存） |
| 5 | SubSystemBridge | scale_class, bcrm_direction, war_state | <1ms |
| 6 | CapitalRotationAdapter | capital_rotation | ~100ms |
| 7 | TraditionalFinanceBridge | regime, trend_strength, vol_scalar, kelly_fraction | ~50ms |
| 8 | RippleDataProvider | ripples (R1/R2/R3) | ~200ms |
| **总计** | | | **~550-850ms** |

**FAIL-OPEN**: 任一适配器异常 → 该字段缺失 → R向量该维度走0.50兜底

### 3.2 CoinScanner — 50币池扫描器

**文件**: `adapters/coin_scanner.py`

- 基础24币 + OKX top 50扫描（去重上限50）
- 美股代币白名单130+支（US_STOCK_COINS）
- 美股配额50%（US_STOCK_RATIO=0.5）
- 美股成交量门槛300K USDT（加密5M USDT）

---

## 4. SL/TP 兜底机制（2026-09-06）

建仓后立即按tier设置止损止盈（在 `polling_trader.py` `_evolution_build_position` 中）:

| Tier | SL% | TP% | 场景 |
|:---|:---|:---|:---|
| probe | 5% | 10% | 轻仓试探，宽SL防噪音 |
| standard | 3% | 6% | 标准仓 |
| trend | 2% | 4% | 趋势加仓，紧SL保护利润 |

**Regime调整**:
- ranging → SL×1.3, TP×0.8（震荡宽容SL，保守TP）
- trend_up → TP×1.2（趋势延长TP）

---

## 5. 权重体系

**文件**: `weights.py` (WEIGHTS_VERSION = "1.0-MVP")

| 权重组 | 比例 | 先验来源 |
|:---|:---|:---|
| ESS | H:S:N = 4:4:2 | Livermore(把握) + Wyckoff(结构) + Schluter(样本) |
| R_REFL | corr:liq:sent = 4:3:3 | Soros反身性(启动) + 流动性(通道) + 情绪(羊群) |
| CS | Level0:ESS:CBR = 0.4:0.3:0.3 | 解析(无过拟合) > 统计 ≈ 案例 |
| CM | ML:Reservoir:CrossVal = 4:3:3 | 美林时钟(长周期) > 蓄水池(月) > 交叉(即期) |

**FAIL-OPEN降级值**: RI=0.29, CMScore=0.45, R_5dim=0.50

---

## 6. 策略基因库

**目录**: `gene_data/`

- **28个条件基因** (CD-*.json): ADX, Bollinger, Donchian, Fibonacci, MACD, RSI, Sentiment, Supertrend等
- **16个动作基因** (AC-*.json): LONG/SHORT + SL/TP组合 + EXIT/STOP/TRAIL
- **组合库** (library.json): 条件×动作组合 + ESS评分
- **Schema**: condition.json, action.json, combination.json

**ESS计算**:
```
ESS = 0.4·H + 0.4·S + 0.2·min(1.0, sqrt(N/500))
```
H=胜率, S=夏普, N=样本量

---

## 7. 稳定性证明

**紧耦合回路增益**: G_open = G₁ · G₂ · G₃ · G₄

| 传递函数 | 含义 | 值 |
|:---|:---|:---|
| G₁ | RI→仓位 | tier加权平均0.0050 |
| G₂ | 仓位→TP/SL概率 | ≈0.55 |
| G₃ | TP/SL→CS | ≈0.70 |
| G₄ | CS→ESS delta | ±0.02/0.05 |

**G_open_max = 0.0197 < 1**，回路绝对稳定（不发散振荡）。

---

## 8. 关联文档

| 文档 | 说明 |
|:---|:---|
| [四层闭环进化架构-最小阻力路径总览.md](../../2-KNOWLEDGE/1-TRADING/四层闭环进化架构-最小阻力路径总览.md) | 蓝图SSoT（§1.7紧耦合流 + §1.13交付物） |
| [SPEC-数据管线打通与能力落地.md](../SPEC-数据管线打通与能力落地.md) | 数据管线详细SPEC |
| [SPEC-金融思维链层FTC设计.md](../SPEC-金融思维链层FTC设计.md) | FTC设计SPEC |
| [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | 工程索引 |
| [API_SPEC.md](./API_SPEC.md) | 接口规格 |
| [CHANGELOG.md](./CHANGELOG.md) | 变更日志 |

---

**文档版本**: v1.0
**最后更新**: 2026-09-07
