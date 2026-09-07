# BDSM 板块横向估值 + 战术小仓策略技术文档

> **版本**: v0.2 | **日期**: 2026-09-06 | **状态**: Phase 0 已落地（E8 信号 + value\_exit 双门控），Phase 1 待启动
> **作者**: AI辅助 | **关联**: bdsm-value-scaling-spec.md v1.4, coin-fundamental-ranker-design.md
>
> **核心问题**：BDSM 当前估值框架仅使用「自身历史百分位」（`valuation_percentile`），在板块普涨的牛市初期会因所有币纵向百分位偏高而**过早触发 full\_exit，错失整个板块趋势机会**。以 2026-09-04 UNI 快照为例：`bds_score=0.4976`（池内最强）、`cvs=0.3586`（低估区）、`phase=P2_REVENUE_EXPANSION`，但 `valuation_percentile=100` 触发 `value_exit=full_exit`，被前置检查拦截。
>
> **本 Spec 解决两件事**：
>
> 1. 新增 **E8 板块横向估值信号**（Cross-Sector Valuation Percentile），与纵向百分位交叉验证，区分「自身高估」与「板块共振」。
> 2. 新增 **战术小仓策略框架**（Tactical Micro-Position Framework），融合彼得·林奇 tenbagger、威廉·欧奈尔 CANSLIM、斯坦利·德鲁肯米勒主动风险预算三大传统流派，作为 BDSM 价值框架的**补充策略**（非替代）。

***

## 目录

1. [问题定义与设计目标](#一问题定义与设计目标)
2. [传统金融三大策略映射](#二传统金融三大策略映射)
3. [E8 板块横向估值信号设计](#三e8-板块横向估值信号设计)
4. [战术小仓策略框架](#四战术小仓策略框架)
5. [与现有 BDSM 的集成点](#五与现有-bdsm-的集成点)
6. [数据来源与 FAIL-OPEN](#六数据来源与-fail-open)
7. [验收标准](#七验收标准)
8. [落地任务分解](#八落地任务分解)

***

## 一、问题定义与设计目标

### 1.1 当前 BDSM 估值盲区

现有 `_compute_value_exit`（`bdsm_snapshot_writer.py:451`）仅依赖 `valuation_percentile`（自身 MC/Fees 或 mcap 历史百分位）：

```python
pf_bubble = valuation_percentile > 90.0   # → full_exit
pf_overvalued = valuation_percentile > 80.0  # → reduce30
```

**盲区**：当整个板块（如 DEX、L1、L2）因资金面共振普涨时，所有币的纵向百分位都会 >90，BDSM 会全部触发 `full_exit`，**在牛市初期过早退出**。

### 1.2 UNI 实证（2026-09-04 快照）

| 指标                    | 值      | 纵向信号         | 横向信号（待补）    |
| --------------------- | ------ | ------------ | ----------- |
| bds\_score            | 0.4976 | 强            | —           |
| cvs                   | 0.3586 | 低估           | —           |
| valuation\_percentile | 100.0  | full\_exit ❌ | DEX 板块百分位待算 |
| rsi\_14               | 82.92  | 超买           | —           |

**矛盾**：纵向说泡沫，基本面说低估。缺少横向维度判断"是 UNI 自身贵，还是整个 DEX 板块都贵"。

### 1.3 设计目标

1. **E8 板块横向估值**：新增信号，与纵向百分位交叉验证，避免牛市初期过早退出。
2. **战术小仓框架**：为"底部沉淀多年 + 资金流入 + 基本面强"的标的提供小仓试错路径，退出条件提前写死。
3. **不破坏现有 BDSM**：E8 为可选增强信号，战术小仓为独立子策略，两者均可通过开关独立关断，关断后字节等价「不存在」。

***

## 二、传统金融三大策略映射

### 2.1 彼得·林奇 "tenbagger" 思路

**核心**：找被市场忽视、底部盘整多年、基本面正在改善的公司，小仓建立观察仓，基本面持续验证后加仓。

| 林奇原则   | BDSM 映射                                          |
| ------ | ------------------------------------------------ |
| 底部盘整多年 | `ma200_deviation` 长期在 0 附近横盘 + `phase` 从 P1 转 P2 |
| 基本面改善  | `bds_score` 连续 2 周 > 0.3 + `e6`（价值捕获）持续为正        |
| 小仓观察仓  | 战术小仓：标准 BDSM 仓的 1/3（约 50-80U）                    |
| 验证后加仓  | 连续 2 周 `bds_score` 上升 + E8 板块百分位 < 70 → 加仓至标准仓   |

### 2.2 威廉·欧奈尔 CANSLIM 趋势跟踪

**核心**：不猜底，等"杯柄形态"突破后跟随，7-8% 硬止损。

| 欧奈尔原则    | BDSM 映射                                     |
| -------- | ------------------------------------------- |
| 杯柄突破     | 价格突破近 20 日高点 + 成交量放大（`volume_ratio > 1.5`）  |
| 7-8% 硬止损 | 战术小仓止损：跌破 MA50 或亏 15%（取先到者）                 |
| 不扛亏损     | `_compute_value_exit` 触发 `full_exit` → 立即离场 |
| 跟随趋势     | `ma200_slope > 0` 且价格在 MA50 上方              |

### 2.3 斯坦利·德鲁肯米勒 "主动风险预算"

**核心**：高确信度才重仓，低确信度小仓试错，错了砍。

| 德鲁肯米勒原则 | BDSM 映射                                                  |
| ------- | -------------------------------------------------------- |
| 高确信度重仓  | BDSM 标准仓（167U）：`cvs ≥ 0.3` + `bds_score ≥ 0.3` + E8 < 70 |
| 低确信度小仓  | 战术小仓（50-80U）：`bds_score ≥ 0.3` 但 E8 ≥ 70（板块共振高估）         |
| 错了砍     | 触发任一退出条件 → 全平，不摊平                                        |
| 主动风控    | 单币小仓预算硬上限（`--bdsm-budget-per-coin` 已实现）                  |

### 2.4 三策略融合的战术小仓决策树

```
入场前提（全部满足）：
  ① bds_score ≥ 0.3（基本面过关）
  ② phase ∈ {P1_UNDERVALUED_RECOVERY, P2_REVENUE_EXPANSION}
  ③ trend_stop.action == "none"（趋势未破）
  ④ 非 value_exit.full_exit（纵向未到泡沫顶，或 E8 显示板块共振）

仓位决策：
  if cvs ≥ 0.3 AND E8 < 70:
      → BDSM 标准仓（167U）  [德鲁肯米勒：高确信度重仓]
  elif bds_score ≥ 0.3 AND (E8 ≥ 70 OR rsi_14 > 70):
      → 战术小仓（50-80U）  [林奇观察仓 + 欧奈尔不追高]
  else:
      → 不建仓

退出条件（任一触发即全平）：
  ① 跌破 MA50                          [欧奈尔硬止损]
  ② 亏损 ≥ 15%                         [欧奈尔 7-8% 放宽到 15%，加密波动大]
  ③ value_exit.action == "full_exit"    [BDSM 价值出场]
  ④ E8 板块百分位 > 85                  [板块整体高估]
  ⑤ bds_score 连续 2 周环比下滑 > 0.1   [基本面恶化，林奇逻辑止损]
  ⑥ 资金面连续 3 日净流出               [资金面止损，需新增信号]
```

***

## 三、E8 板块横向估值信号设计

### 3.1 信号定义

**E8 = 1 - (该币 MC/Fees 比率在所属板块中的百分位)**

- 取值范围：\[-1, +1]（与 e5/e6/e7 对齐）

- E8 > 0：该币在板块中相对便宜（横向低估）

- E8 < 0：该币在板块中相对贵（横向高估）

- E8 = 0：板块中位或数据不足

### 3.2 板块定义

按 `CRYPTO_MAP` 中 `defillama_slug` 是否为 None 区分 L1 / DeFi，再按业务细分：

| 板块       | 成员（BDSM 池内 + 竞对扩展）           | 估值锚            |
| -------- | ---------------------------- | -------------- |
| DEX      | UNI, CRV, 1INCH, CAKE, SUSHI | MC/Fees        |
| Lending  | AAVE, COMP, MKR              | MC/Fees        |
| L1       | BTC, ETH, SOL, BNB, ADA      | NVT（市值/链上日交易量） |
| L2       | OP, ARB, MATIC, STX          | MC/Fees        |
| Meme     | PUMP, DOGE, SHIB, PEPE       | MC/Fees        |
| Perp DEX | HYPE, GMX, GNS, DYDX         | MC/Fees        |

**注**：板块成员表为可配置常量，初始用 BDSM 池内币 + 主流竞对，后续可扩展。

### 3.3 计算逻辑

```python
def compute_e8_cross_sector_valuation(coin: str, db_path: str) -> float:
    """E8 板块横向估值：1 - (该币 MC/Fees 在板块中的百分位)。
    
    步骤：
    1. 确定 coin 所属板块（查 SECTOR_MAP）
    2. 获取板块内所有币的 MC/Fees 比率（或 L1 用 NVT）
    3. 计算该币在板块中的百分位 pct ∈ [0, 100]
    4. E8 = 1 - (pct / 50 - 1) = 2 - pct/50，映射到 [-1, +1]
       - pct=0 → E8=+1（板块最便宜）
       - pct=50 → E8=0（板块中位）
       - pct=100 → E8=-1（板块最贵）
    
    FAIL-OPEN：板块成员 < 3 或该币无估值数据 → 返回 0.0（中性）
    """
```

### 3.4 与 value\_exit 的集成

修改 `_compute_value_exit`，引入 **双门控**：

```python
def _compute_value_exit(bds_score, valuation_percentile, e8_cross_sector=None):
    pf_bubble = valuation_percentile > 90.0
    pf_overvalued = valuation_percentile > 80.0
    bds_collapse = bds_score < 0.0
    
    # E8 交叉验证：纵向泡沫但横向不贵 → 降级为 reduce30（板块共振，非自身泡沫）
    if pf_bubble and e8_cross_sector is not None and e8_cross_sector > 0.0:
        pf_bubble = False          # 降级
        pf_overvalued = True       # 仍高估但非泡沫
    
    action = "none"
    if pf_bubble or bds_collapse:
        action = "full_exit"
    elif pf_overvalued:
        action = "reduce30"
```

**效果**：UNI 当前 `valuation_percentile=100` 但如果 DEX 板块中 UNI 的 MC/Fees 百分位 < 50（E8 > 0），则从 `full_exit` 降级为 `reduce30`，不再被前置检查拦截。

***

## 四、战术小仓策略框架

### 4.1 定位

战术小仓是 BDSM 价值框架的**补充策略**，适用于：

- 标的基本面强（`bds_score ≥ 0.3`）但纵向估值偏高（`valuation_percentile > 80`）

- 或技术面超买（`rsi_14 > 70`）但板块横向估值不贵（E8 > 0）

- 或资金面信号强（如 Robinhood 持仓连续流入）但 BDSM 框架未覆盖

**不替代** BDSM 标准仓（`cvs ≥ 0.3` + E8 < 70 的标的仍走标准仓路径）。

### 4.2 开关设计

```python
# 总开关（默认 False，Shadow 模式只计算不执行）
ENABLE_TACTICAL_MICRO_POSITION = os.environ.get(
    "ENABLE_TACTICAL_MICRO_POSITION", ""
).lower() in ("1", "true")

# 小仓预算（U），默认 60U（BDSM 标准仓 167U 的 ~36%）
TACTICAL_MICRO_BUDGET_USDT = float(os.environ.get("TACTICAL_MICRO_BUDGET_USDT", "60"))

# 单币止损百分比
TACTICAL_STOP_LOSS_PCT = float(os.environ.get("TACTICAL_STOP_LOSS_PCT", "0.15"))

# 板块高估退出阈值
TACTICAL_E8_EXIT_THRESHOLD = float(os.environ.get("TACTICAL_E8_EXIT_THRESHOLD", "-0.3"))
```

### 4.3 入场条件（全部满足）

```python
def tactical_entry_check(signal) -> bool:
    return (
        signal.bds_score >= 0.3
        and signal.phase in ("P1_UNDERVALUED_RECOVERY", "P2_REVENUE_EXPANSION")
        and signal.trend_stop.action == "none"
        and signal.value_exit.action != "full_exit"
        and (signal.cvs < 0.3 or signal.valuation_percentile > 80 or signal.rsi_14 > 70)
        # 排除 BDSM 标准仓已覆盖的场景
    )
```

### 4.4 退出条件（任一触发）

| 条件              | 阈值                                 | 来源        |
| --------------- | ---------------------------------- | --------- |
| 跌破 MA50         | `price < ma50`                     | 欧奈尔       |
| 亏损 ≥ 15%        | `unrealized_pnl < -15%`            | 欧奈尔（加密放宽） |
| BDSM full\_exit | `value_exit.action == "full_exit"` | BDSM      |
| E8 板块高估         | `e8_cross_sector < -0.3`           | E8 新增     |
| BDS 恶化          | `bds_score` 连续 2 周环比下滑 > 0.1       | 林奇逻辑止损    |
| 资金面流出           | 连续 3 日净流出（待资金面信号落地）                | 新增        |

### 4.5 仓位上限

- 战术小仓**不占用** BDSM 标准仓的 3 仓配额

- 战术小仓独立配额：最多 2 仓，单仓 ≤ `TACTICAL_MICRO_BUDGET_USDT`

- 总战术小仓敞口 ≤ 120U（2 × 60U）

***

## 五、与现有 BDSM 的集成点

### 5.1 信号层：`coin_fundamental_crypto.py` → `compute_all`

在 `sub_signals` 中新增 `e8_cross_sector_valuation` 字段：

```python
# 在 compute_all 返回前
e8 = compute_e8_cross_sector_valuation(coin, db_path)  # FAIL-OPEN → 0.0
result["e8_cross_sector_valuation"] = e8
```

### 5.2 阶段层：`coin_fundamental_ranker.py` → `compute_signal`

在调用 `classify_phase` 时传入 E8：

```python
# 现有
phase_classification = classify_phase(
    coin=coin, sub_signals=sub_signals,
    valuation_percentile=valuation_percentile,
    event_timeline=event_timeline,
)
# 新增：把 e8 透传给 phase_classifier（可选参数，FAIL-OPEN）
```

### 5.3 出场层：`bdsm_snapshot_writer.py` → `_compute_value_exit`

修改签名，新增 `e8_cross_sector` 参数（默认 None，兼容现有调用）：

```python
def _compute_value_exit(bds_score, valuation_percentile, e8_cross_sector=None):
    ...
```

### 5.4 快照层：`bdsm_snapshot_writer.py` → `_build_coin_entry`

在快照 JSON 中新增：

- `e8_cross_sector_valuation`: float（\[-1, +1]）

- `cross_sector_percentile`: float（\[0, 100]）

- `tactical_position_eligibility`: bool（是否符合战术小仓入场条件）

### 5.5 执行层：`polling_trader.py` → `_apply_bdsm_scaling`

在 BDSM 标准仓路径之后，新增战术小仓路径（开关控制）：

```python
if ENABLE_TACTICAL_MICRO_POSITION and tactical_entry_check(signal):
    budget = min(TACTICAL_MICRO_BUDGET_USDT, remaining_tactical_budget)
    # 走战术小仓下单 + 独立止损监控
```

***

## 六、数据来源与 FAIL-OPEN

### 6.1 板块估值数据

- **MC/Fees**：复用 `coin_fundamental_crypto.py` 中 `_fetch_protocol_fees` + `_fetch_coin_info`

- **L1 NVT**：复用 `_fetch_L1_chain_metrics` 中的 `nvt_ratio`

- **竞对币数据**：需要为非 BDSM 池币（CRV, 1INCH, GMX 等）补充 `CRYPTO_MAP` 条目

### 6.2 资金面数据（后续 Phase 2）

- **Robinhood 持仓**：需新增数据采集（Robinhood 加密持仓 API 或第三方）

- **交易所净流入**：OKX/币安现货净流入（已有 `panewslab` 链上资金数据）

### 6.3 FAIL-OPEN 铁律

| 失败场景                     | 兜底行为                         |
| ------------------------ | ---------------------------- |
| 板块成员 < 3                 | E8 = 0.0（中性，不影响 value\_exit） |
| 该币无估值数据                  | E8 = 0.0                     |
| 竞对币数据缺失                  | 用已有成员计算百分位（≥3 才有效）           |
| `_compute_value_exit` 异常 | 走原逻辑（仅纵向百分位）                 |
| 战术小仓开关关                  | 完全不执行，字节等价「不存在」              |

***

## 七、验收标准

### 7.1 E8 信号

- [ ] `compute_e8_cross_sector_valuation("UNI")` 返回非零值（DEX 板块 ≥ 4 成员）

- [ ] 板块成员 < 3 时返回 0.0

- [ ] 该币 MC/Fees 在板块最低 → E8 接近 +1

- [ ] 该币 MC/Fees 在板块最高 → E8 接近 -1

- [ ] UNI 快照中 `e8_cross_sector_valuation` 字段存在

- [ ] `_compute_value_exit` 在 `valuation_percentile=100` 且 `e8 > 0` 时返回 `reduce30`（非 `full_exit`）

- [ ] `_compute_value_exit` 在 `valuation_percentile=100` 且 `e8=None` 时返回 `full_exit`（兼容旧行为）

### 7.2 战术小仓

- [ ] 开关关时，战术小仓路径完全不执行

- [ ] `bds_score ≥ 0.3` + `valuation_percentile > 80` + `e8 > 0` → 战术小仓 eligible

- [ ] 退出条件任一触发 → 立即全平

- [ ] 战术小仓不占用 BDSM 标准仓 3 仓配额

- [ ] 单仓预算 ≤ `TACTICAL_MICRO_BUDGET_USDT`

### 7.3 回归

- [ ] 现有 70+ crypto/ranker UT 零回归

- [ ] 现有 phase0 snapshot UT 零回归

- [ ] `_compute_value_exit` 旧调用签名（不传 e8）行为不变

***

## 八、落地任务分解

### Phase 0：E8 信号（独立可验证）

| Task | 内容                                                                     | 依赖     | 状态 |
| ---- | ---------------------------------------------------------------------- | ------ | -- |
| T1   | 定义 `SECTOR_MAP` 板块成员常量（DEX/Lending/L1/L2/Meme/Perp）                    | 无      | ✅  |
| T2   | 实现 `compute_e8_cross_sector_valuation(coin, db_path)` 纯函数 + 8 UT       | T1     | ✅  |
| T3   | 集成到 `compute_all`，sub\_signals 新增 `e8_cross_sector_valuation`          | T2     | ✅  |
| T4   | 修改 `_compute_value_exit` 加 e8 参数 + 双门控逻辑                               | T2     | ✅  |
| T5   | 快照 JSON 新增 `e8_cross_sector_valuation` + value\_exit.e8\_cross\_sector | T3, T4 | ✅  |

### Phase 1：战术小仓框架

| Task | 内容                                                    | 依赖         |
| ---- | ----------------------------------------------------- | ---------- |
| T6   | 定义战术小仓开关 + 预算常量                                       | 无          |
| T7   | 实现 `tactical_entry_check(signal)` 纯函数 + 4 UT          | T5         |
| T8   | 实现 `tactical_exit_check(position, signal)` 纯函数 + 6 UT | T5         |
| T9   | 集成到 `polling_trader._apply_bdsm_scaling`（开关控制）        | T6, T7, T8 |
| T10  | 快照新增 `tactical_position_eligibility` 字段               | T7         |

### Phase 2：资金面信号（可选）

| Task | 内容                                           | 依赖   |
| ---- | -------------------------------------------- | ---- |
| T11  | 新增 `e9_capital_flow` 资金面信号（Robinhood/交易所净流入） | 数据采集 |
| T12  | 战术小仓退出条件加入资金面流出                              | T11  |

### 验收门槛

- Phase 0 完成后：跑 3 天影子快照，验证 UNI 的 E8 能正确区分"自身高估"vs"板块共振"

- Phase 1 完成后：10 笔战术小仓实盘测试，胜率 ≥ 60%，最大单笔亏损 ≤ 15%

***

## 附录 A：板块成员初始表

```python
SECTOR_MAP = {
    "DEX": ["UNI", "CRV", "1INCH", "CAKE", "SUSHI"],
    "Lending": ["AAVE", "COMP", "MKR"],
    "L1": ["BTC", "ETH", "SOL", "BNB", "ADA"],
    "L2": ["OP", "ARB", "MATIC", "STX"],
    "Meme": ["PUMP", "DOGE", "SHIB", "PEPE"],
    "Perp_DEX": ["HYPE", "GMX", "GNS", "DYDX"],
}
```

CRCL 暂不归入板块（主网未上线，无费用数据），E8 = 0.0。

## 附录 B：与 v1.4 spec 的关系

- 本 Spec **不修改** v1.4 的任何现有规则

- E8 为 v1.4 `valuation_percentile` 的**增强维度**（交叉验证），关断后 v1.4 行为字节不变

- 战术小仓为 v1.4 标准仓路径的**并行补充**，独立开关、独立配额、独立止损

