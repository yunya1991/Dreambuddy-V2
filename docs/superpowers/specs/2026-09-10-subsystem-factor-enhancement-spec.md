# 子系统因子增强 + 自进化权重消费 技术规格（Spec）

> **版本**: v1.1
> **日期**: 2026-09-11
> **状态**: Draft（待评审）
> **定位**: 在子系统（战略层/BCRM2.0/BDSM）内实现用户成熟经验因子（头肩形态、ETF流出、BTC强弱regime），自进化系统通过 SubSystemBridge 消费输出做权重优化，不在基因层重复实现因子逻辑。
>
> **v1.1 变更**（2026-09-11）：
> - R5 铁律修订：BDSM 技术面（RSI/volume_ratio/ATR/ts_score）**保留**，用于 CVS 公式驱动精准分批加仓，不属于职责蔓延。BDSM 定位为「基本面选股 + 技术面择时加仓」，趋势止损和加仓择时均属 BDSM 职责范围。

***

## 0. 背景与目标

### 0.1 设计动机

1. **用户经验因子需落地**：头肩顶/底（技术面）、ETF 滞涨后流出（基本面）、BTC 强弱决定与美股相关性（宏观）三条经验，应在对应子系统实现，而非自进化基因层重复造轮子。
2. **自进化系统定位为权重优化中枢**：BCRM2.0 已接入（方向+置信度），战略层/BDSM 仅浅接入（war_state/方向约束），需扩展消费深度。
3. **P0 Bug 阻塞技术面信号**：BDSM K 线拉取 `limit=290` 但 OKX `history-candles` 单次最多 100 根，导致 `_compute_technical_assessment` 因 `len(klines)<200` 全线返回中性值，趋势止损失灵。
4. **BDSM 技术面定位澄清**：`technical_assessment` 含 RSI/volume_ratio/ATR/ts_score，这些指标用于 CVS 公式驱动精准分批加仓（基本面选股 + 技术面择时加仓），不属于范围蔓延。趋势止损（MA200/MA128/斜率/死叉）和加仓择时（RSI/成交量/ATR/ts_score）均属 BDSM 职责分工的一部分。

### 0.2 核心原则（铁律）

| #  | 铁律 | 违反后果 |
| -- | ---- | -------- |
| R1 | **因子实现在子系统，自进化只消费+权重优化**：头肩→BCRM，ETF/BTC regime→战略层，禁止在基因层重复实现 | 因子逻辑多处维护、口径不一致 |
| R2 | **战略层不直接生成买卖信号**：ETF/BTC regime 只影响 five_scores→war_state→position_cap，挂钩权重/状态/熔断 | 宏观噪音直接触发交易 |
| R3 | **FAIL-OPEN 字节等价无此功能**：任何子系统因子计算异常→中性兜底，不阻塞主链路 | 因子 Bug 导致交易中断 |
| R4 | **接口契约稳定**：SubSystemBridge 扩展字段必须带默认值，旧调用方零改动 | 下游 KeyError |
| R5 | **BDSM 技术面保留用于精准加仓**：RSI/volume_ratio/ATR/ts_score 参与 CVS 公式（BDS×0.6 + TS×0.4），驱动分批建仓节奏；MA200/MA128/斜率/死叉负责趋势止损。两者分工不同，均属 BDSM 职责（基本面选股 + 技术面择时加仓） | 技术面信号缺失导致 CVS 退化为纯基本面，加仓节奏失准 |

***

## 1. P0：BDSM K 线分页拉取修复

### 1.1 问题定位

[bdsm_snapshot_writer.py:100](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/force_vector/bdsm_snapshot_writer.py#L100)
```python
params = {"instId": inst_id, "bar": "1D", "limit": str(_KLINE_FETCH_LIMIT)}  # 290
```
OKX `/api/v5/market/history-candles` 单次 `limit` 上限为 **100**，超出被截断。`_compute_technical_assessment` 要求 `len(klines) >= ma_long=200`（[L298](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/force_vector/bdsm_snapshot_writer.py#L298)），100<200 → 全部中性。

### 1.2 修复方案

改用 OKX 分页参数 `before`（返回更早的数据），循环拉取直到 ≥200 根或无更多数据：

```python
def _fetch_snapshot_klines(coin: str) -> list:
    cache_key = (coin or "").upper()
    if cache_key in _KLINE_CACHE:
        return _KLINE_CACHE[cache_key]
    try:
        import requests
    except Exception:
        return []
    inst_id = f"{cache_key}-USDT-SWAP"
    url = "https://www.okx.com/api/v5/market/history-candles"
    proxies = {"http": _SNAPSHOT_PROXY, "https": _SNAPSHOT_PROXY}
    all_klines = []
    before_ts = None
    target = max(_KLINE_FETCH_LIMIT, 200)  # 确保 ≥200
    try:
        while len(all_klines) < target:
            params = {"instId": inst_id, "bar": "1D", "limit": "100"}
            if before_ts is not None:
                params["before"] = str(before_ts)
            r = requests.get(url, params=params, proxies=proxies, timeout=12)
            data = r.json()
            if data.get("code") != "0":
                break
            raw = data.get("data", []) or []
            if not raw:
                break
            for k in raw:
                all_klines.append({
                    "ts": int(k[0]), "o": float(k[1]), "h": float(k[2]),
                    "l": float(k[3]), "c": float(k[4]), "v": float(k[5]),
                })
            before_ts = int(raw[-1][0])  # 用最早一根的 ts 作为 before
            if len(raw) < 100:
                break  # 已到最早
        # 按时间升序排列
        all_klines.sort(key=lambda x: x["ts"])
        _KLINE_CACHE[cache_key] = all_klines
        return all_klines
    except Exception as _exc:
        logger.warning("BDSM K线拉取失败 coin=%s: %s", coin, _exc)
        return []
```

### 1.3 验证标准
- 拉取返回 ≥200 根 K 线
- `technical_assessment.rsi_14` 不再恒为 50.0
- `trend_stop.ma200_price` 不再恒为 0.0

***

## 2. 战略层升级

### 2.1 ETF 流出权重提升

[five_domain_feature_computer.py:436](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py#L436)
```python
# 改前
deltas.append(float(flow_norm) * 0.05)
# 改后
deltas.append(float(flow_norm) * 0.15)
```
- 影响范围：`_pn_dao_boost` 的 dao 维度 delta，最终影响 `five_scores[cls]["dao"]` → war_state → position_cap
- 约束：`_pn_dao_boost` 最终 clamp 在 [-0.2, 0.2]，权重提升后仍受此约束

### 2.2 BTC 强弱 Regime 检测

**新增字段**：在 `FiveDomainState` 中新增 `btc_regime: Dict[str, str]`（按类），取值 `STRONG`/`WEAK`/`NEUTRAL`。

**判定逻辑**（基于 BTC 日线数据，日级计算）：

| Regime | 条件 | 含义 |
|--------|------|------|
| STRONG | 价格 > MA200 AND MA200 斜率 > 0 AND (价格-MA200)/MA200 > 2% | BTC 独立强势，与美股脱钩 |
| WEAK | 价格 < MA200 OR MA200 斜率 < 0 | BTC 弱势，类风险资产，美股关联增强 |
| NEUTRAL | 其他 | 中性 |

**实现位置**：`five_domain_feature_computer.py` 新增 `_compute_btc_regime(coin_data)` 方法，BTC 的 `coin_data` 需包含 `ma200_price`、`ma200_slope`、`current_price`。

**消费方式**：
- `btc_regime=WEAK` 时，`sp500_7d_break` 对 dao 维度的影响权重 ×2（美股下跌→dao 扣分加倍）
- `btc_regime=STRONG` 时，`sp500_7d_break` 影响权重 ×0.5（BTC 独立强势，美股影响减弱）
- `btc_regime=NEUTRAL` 时，权重 ×1.0（默认）

### 2.3 BTC-美股动态相关性

在 `_pn_dao_boost` 中新增 P6 项：
```python
# P6：美股 7 日突破 × BTC regime 动态权重
sp500_break = coin_data.get("pn_sp500_7d_break")
btc_regime = coin_data.get("btc_regime", "NEUTRAL")
if isinstance(sp500_break, (int, float)):
    regime_mult = {"WEAK": 2.0, "STRONG": 0.5, "NEUTRAL": 1.0}.get(btc_regime, 1.0)
    deltas.append(float(sp500_break) * 0.06 * regime_mult)
```

### 2.4 验证标准
- ETF 连续大额流出时，dao 评分下降幅度增大
- BTC 弱势 + 美股下跌时，war_state 更易偏向 COOLDOWN/FREEZE
- BTC 强势时，美股下跌对 war_state 影响减弱

***

## 3. BCRM2.0：头肩顶/底形态识别

### 3.1 实现位置

BCRM2.0 技术面分析模块，输出到 `_last_bcrm2_result["next_state"]` 新增字段 `pattern`。

### 3.2 检测逻辑（复用进化系统已有实现）

参考 [shadow_backtest.py:267-309](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/scripts/shadow_backtest.py#L267-L309) 的头肩顶检测，适配 BCRM2.0 的 K 线数据结构。

**头肩顶（hs_top）**：
1. 55 bar 窗口找最高点（头部），头部在窗口中部
2. 头部左右 5-20 bar 内有次高点（左右肩），两肩均在头部 85%-100%
3. 颈线 = min(左肩前低点, 右肩后低点)
4. 当前收盘 < 颈线 × 0.998 且量比 < 0.8

**头肩底（hs_bottom）**：镜像逻辑（找最低点、左右肩在底部 100%-115%、突破颈线）。

### 3.3 输出结构

在 BCRM result 的 `next_state` 中新增：
```python
"pattern": {
    "hs_top": bool,      # 头肩顶
    "hs_bottom": bool,   # 头肩底
    "confidence": float, # 0.0~1.0
}
```

### 3.4 验证标准
- BTC 近期高位盘整后若形成头肩顶，`pattern.hs_top=True`
- FAIL-OPEN：K 线不足或计算异常 → `pattern={"hs_top": False, "hs_bottom": False, "confidence": 0.0}`

***

## 4. SubSystemBridge 扩展

### 4.1 新增方法

在 [subsystem_bridge.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/subsystem_bridge.py) 中新增：

| 方法 | 返回 | 来源 |
|------|------|------|
| `get_five_scores(cls="crypto_usdt")` | `Dict[str, int]` | `_five_domain_state_shadow.five_scores[cls]` |
| `get_position_cap(cls="crypto_usdt")` | `float` | `_five_domain_state_shadow.aggregate_position_cap_pct[cls]` |
| `get_btc_regime()` | `str` | `_five_domain_state_shadow.btc_regime.get("crypto_usdt", "NEUTRAL")` |
| `get_bcrm_pattern()` | `Dict` | `_last_bcrm2_result["next_state"]["pattern"]` |
| `get_bdsm_valuation()` | `float` | `_last_bdsm_snapshot["valuation_percentile"]`（已有方法，补充注入） |

### 4.2 data_pipeline 注入

在 [data_pipeline.py:127-133](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/data_pipeline.py#L127-L133) 中注入新字段到 `kline_data`：
```python
kline_data["five_scores"] = self._subsystem.get_five_scores()
kline_data["position_cap"] = self._subsystem.get_position_cap()
kline_data["btc_regime"] = self._subsystem.get_btc_regime()
kline_data["bcrm_pattern"] = self._subsystem.get_bcrm_pattern()
kline_data["bdsm_valuation"] = self._subsystem.get_bdsm_valuation()
```

### 4.3 FAIL-OPEN
所有新方法异常时返回中性默认值（scores=50, cap=1.0, regime=NEUTRAL, pattern={}, valuation=0.5）。

***

## 5. 自进化系统权重消费

### 5.1 现有权重框架

[weights.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/weights.py) 的四组权重：
- `ESS`: H:S:N_ratio = 4:4:2
- `R_REFL`: corr:liq:sent = 4:3:3
- `CS`: Level0:ESS_top:CBR_top = 4:3:3
- `CM`: ML:Reservoir:CrossVal = 4:3:3

### 5.2 新信号消费方式

| 新信号 | 消费位置 | 作用 |
|--------|---------|------|
| `five_scores` | CM 权重组 | 五维评分作为宏观环境先验，调节 ESS 温度 |
| `position_cap` | 仓位计算 | 自进化仓位 × position_cap（战略层仓位上限） |
| `btc_regime` | R_REFL corr 权重 | WEAK 时提高美股相关性权重，STRONG 时降低 |
| `bcrm_pattern` | ESS H 权重 | hs_top/hs_bottom 作为形态确认，调节把握度 |
| `bdsm_valuation` | ESS S 权重 | 低估时提高结构性权重 |

### 5.3 实现原则
- 不在自进化系统内实现因子计算逻辑
- 仅通过 bridge 消费子系统输出
- ESS/ReflectionEngine 负责学习各信号权重
- 所有新字段带默认值，FAIL-OPEN 等价无此信号

***

## 6. 执行顺序与验收

| 阶段 | 任务 | 验收标准 |
|------|------|---------|
| P0 | BDSM K 线分页修复 | BTC technical_assessment 非全中性，trend_stop 有值 |
| P1a | ETF 权重 0.05→0.15 | dao boost 对 ETF 流出敏感度提升 |
| P1b | BTC regime + 动态相关性 | BTC 弱势时美股下跌更易触发 war_state 收紧 |
| P2 | BCRM 头肩形态 | BTC 高位盘整后能检测 hs_top |
| P3 | Bridge 扩展 + 自进化消费 | kline_data 含新字段，权重优化链路正常 |

### 6.1 回归测试
- BDSM 快照生成测试：technical_assessment 非中性
- 战略层 five_domain_state：ETF 流出场景 dao 评分下降
- BCRM pattern：构造头肩 K 线序列能检测
- SubSystemBridge：所有新方法返回正确类型
- 自进化 data_pipeline：kline_data 含新字段

***

## 7. 硬约束一致性检查

| 硬约束 | 本 Spec 影响 | 一致性 |
|--------|-------------|--------|
| FAIL-OPEN 铁律 | 所有新因子异常→中性兜底 | ✅ |
| 战略层开关关断→中性默认 | 新字段在 enable_five_domain=False 时返回默认 | ✅ |
| BDSM 方向约束不变 | 不改 `_apply_bdsm_direction_constraint` | ✅ |
| SHORT_ONLY_BLACKLIST | 本 Spec 不改动禁空名单 | ✅ |
| min_position_usdt ≥250 | 不涉及仓位下限 | ✅ |
