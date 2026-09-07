# BDSM ⊥ BCRM 协作技术规格（Spec）

> **版本**: v1.2
> **日期**: 2026-09-01 → 2026-09-02（执行框架修正）
> **状态**: Draft（待评审）
> **定位**: BDSM（基本面战略层）与 BCRM 2.0（K线战术层）双引擎协作，运行于 OKX 易经推理框架（PollingTrader + BCRMEngine + OKXSimulatedClient），资金共享不切分，仓位按子池隔离计数（BCRM≤5 / BDSM≤3）

***

## 0. 背景与目标

### 0.1 设计动机

1. **BDSM 模型输出与巴菲特价值投资高度同构**：七信号（E5 供给缩减/E6 价值捕获/E7 收入可持续性 × 原四信号Artemis）合成的 `fundamental_score` + `rank` + `phase` 三字段，天然匹配"买有价值的、不追高、基本面塌了就跑"的价值投资哲学。但缺少精确的入场时机、止损止盈、风控链路。
2. **BCRM 2.0 时间框架与 BDSM 不冲突**：BCRM 小时/日级 K 线推理（344 L1 + 278 L2 模型）擅长精确入场、动态 SL/TP、方案C 8 开关硬风控。但方向只看 K 线，不考虑基本面拐点。
3. **决策分层而非信号叠加**：不做复杂的乘法/加法/加权融合，只做三个简单操作——方向硬约束、仓位上限、出场 OR 逻辑。FAIL-OPEN 等价于 BDSM 不存在。

### 0.2 核心原则（铁律）

| #  | 铁律                                                                                    | 违反后果                              |
| -- | ------------------------------------------------------------------------------------- | --------------------------------- |
| R1 | **基本面定方向，技术面不定反向**：BDSM score > 0.3 时 BCRM SHORT 信号直接丢弃；score < -0.3 时 BCRM LONG 直接丢弃 | 方向性对冲风险                           |
| R2 | **BDSM 地基塌了优先跑**：基本面出场（B1\~B5）触发时，不与技术面出场商量，先执行减仓/平仓                                  | 基本面崩溃是大周期风险，不能等技术面确认              |
| R3 | **FAIL-OPEN 字节等价无 BDSM**：BDSM 快照缺失/异常 → 方向中性、仓位上限 1.0、强制出场为空                          | 不阻塞 BCRM 2.0 主链路                  |
| R4 | **双引擎代币池对齐为 BDSM 8 币池**：BDSM 覆盖 8 币种，BCRM 池补齐缺失币种后，BDSM 直接借用 BCRM 信号，无冲突              | 币种池不一致会导致 BDSM 有约束但 BCRM 根本不推该币信号 |

***

## 1. 代币池对齐（R4 落地）

### 1.1 BDSM 覆盖币种（8 币，作为权威池）

| 币种   | BDSM 原生数据采集器          | 数据来源                             | 信号可用                                         |
| ---- | --------------------- | -------------------------------- | -------------------------------------------- |
| UNI  | `bdsm_uniswap`        | CoinGecko + Uniswap Trading API  | ✅                                            |
| PUMP | `bdsm_pump`           | pump.fun SSR HTML                | ✅                                            |
| HYPE | `bdsm_hype`           | Hyperliquid API + CoinGecko      | ✅                                            |
| AAVE | `bdsm_aave`           | Aave GraphQL API（21 链聚合）         | ✅                                            |
| SOL  | `bdsm_solana`         | Solana 官方 RPC API（4 方法）          | ✅                                            |
| CRCL | `bdsm_circle`         | circle.com/transparency `data-*` | ✅                                            |
| ETH  | 复用 CoinGecko（DeFi 数据） | DeFiLlama + CoinGecko            | ⚠️（无原生 collector，回退原链路；真钱 SHORT\_BAN 仅做多）    |
| SKY  | 待定                    | 待补原生采集器或回退原链路                    | ❌（**暂从 BDSM 池移除**，保留纯 BCRM 自主；计数走 bcrm≤5 子池） |

### 1.2 代币池差异对照表（补齐前）

| 模块                                                   | 当前代币池                                                                                                        | 缺失 BDSM 币种                                          | 需补齐                              |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------- | -------------------------------- |
| PollingTrader 默认池（`polling_trader.py:584`）           | UNI, PUMP, MU, SKHYNIX, HYPE, BTC, SOL, XAU, XAG, GOOGL, NVDA, AMZN, OKB, SNDK, SPCX, CRCL, COIN, BMNR, MSTR | **AAVE, ETH**（SKY 不进 BDSM 池，保留纯 BCRM）               | +2（BDSM 7 币） + SKY(BCRM)         |
| `p0_backtest_verify.CRYPTO_COINS`（L74）               | BTC, SOL, UNI, OKB, HYPE, PUMP                                                                               | **AAVE, CRCL, ETH**（SKY 由纯 BCRM，缺则按需补）              | +3                               |
| `macro_feature_optimize_v3.COINS`（L55）               | UNI, PUMP, HYPE, ETH, BTC, SOL, XAUT, OKB, BNB                                                               | **AAVE, CRCL**（SKY 由纯 BCRM，缺则按需补）                   | +2                               |
| `market_cap.KNOWN_MCAP`（L165）                        | BTC, ETH, BNB, SOL, XRP, ADA（+其他）                                                                            | **PUMP, HYPE, AAVE, UNI, CRCL** 无显式条目（SKY 按需，回退分类器） | 按需                               |
| CoinSelector `_select_mock` defaults（L115）           | BTC, ETH, SOL                                                                                                | **其余 4 币**（UNI/PUMP/HYPE/AAVE/CRCL）                 | Mock 模式已不关键，真实路径走 persisted pool |
| data\_server `/api/v15-ct/decisions` defaults（L3522） | BTC, ETH, SOL, ARB, OP, UNI, HYPE, OKB                                                                       | **PUMP, AAVE, CRCL**（SKY 由纯 BCRM，缺则按需补）             | +3                               |

### 1.3 补齐方案

**统一引入单一** **`BDSM_COINS`** **常量**，所有模块引用它，避免散落 N 处硬编码；**SKY 暂不在 BDSM 池内，走纯 BCRM 子池计数**：

```python
# 新增文件/或在 coin_fundamental_ranker.py 定义后导出
BDSM_COINS = frozenset({"UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH"})  # 7 币
```

各模块补齐动作：

| 文件                                                           | 改动                                                            | 类型           |
| ------------------------------------------------------------ | ------------------------------------------------------------- | ------------ |
| `polling_trader.py:584` `default_coins` 列表                   | 插入 `AAVE, ETH`（SKY 保留纯 BCRM，不进 BDSM 前端段；子池隔离 bdsm≤3 / bcrm≤5） | 列表扩展 + R5    |
| `p0_backtest_verify.py:74` `CRYPTO_COINS`                    | 添加 `AAVE, CRCL, ETH`（真钱 ETH SHORT\_BAN，仅做多；SKY 纯 BCRM 另算）     | frozenset 扩展 |
| `macro_feature_optimize_v3.py:55` `COINS`                    | 添加 `AAVE, CRCL`（SKY 纯 BCRM，按需补）                               | 列表扩展         |
| `data_server_fixed.py:3522` `/api/v15-ct/decisions` 默认 coins | 将 `PUMP, AAVE, CRCL` 加入默认串（注意 ETH 也在原串，已含；SKY 按需不默认）          | 默认值扩展        |
| `data_server_fixed.py:3089` shadow log 拉取列表                  | 添加 `PUMP, AAVE, CRCL` 到 7 天日志拉取循环（SKY 纯 BCRM，按需补）             | 列表扩展         |

**注意**：`CRYPTO_COINS` 中的 `STATIC_BLACKLIST_COINS` 含 ETH（P0 回测验证 ETH 做空亏损），真钱路径将 ETH 从 `blacklist` 移出并加入 **`SHORT_ONLY_BLACKLIST={ETH, BTC}`**（仅禁做空、做多允许）。SKY 不在 BDSM 权威池，走纯 BCRM 子池（tag=bcrm，≤5 仓），不占用 BDSM 3 仓额度。

***

## 2. 系统架构

### 2.1 协作总览图

```
┌───────────────────────────────────────────────────────────────────────┐
│                    双引擎协作（零耦合叠加，仅硬约束）                    │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ╔══════════════════════════════════════════╗     运行频率             │
│  ║      BDSM 基本面快照层（每日收盘后 1 次）     ║     日级 / 低频       │
│  ╠══════════════════════════════════════════╣                        │
│  ║  1. compute_signal (BDSM 权威池 7 币)      ║                        │
│  ║  2. classify_phase(P1/P2/P3)              ║                        │
│  ║  3. 巴菲特安全边际折扣(score×0.7, Phase3)   ║                        │
│  ║  4. 5 种基本面出场触发检测(B1~B5)          ║                        │
│  ║     ↓                                    ║                        │
│  ║  输出: bdsm_snapshot.json                 ║                        │
│  ╚══════════════════════╤═══════════════════╝                        │
│                         │ 只读                                         │
│                         ▼                                              │
│  ╔══════════════════════════════════════════╗     运行频率             │
│  ║   BCRM 2.0 战术执行层（每 K 线周期）         ║     小时级 / 高频       │
│  ╠══════════════════════════════════════════╣                        │
│  ║  A. 方向约束检查 ──► 丢弃反方向信号         ║                        │
│  ║  B. 仓位上限 min ──► 实际仓位≤BDSM cap     ║                        │
│  ║  C. 信号生成 (344+278)  ► SL/TP 计算       ║                        │
│  ║  D. 出场检查 (OR 逻辑)                     ║                        │
│  ║      ├─ 路径 A: BCRM 技术出场             ║                        │
│  ║      │  (Triple Barrier/Tracking/TSTP)   ║                        │
│  ║      └─ 路径 B: BDSM 基本面出场           ║                        │
│  ║          (B1~B5 任一触发, BDSM优先)       ║                        │
│  ║  E. 方案 C 8 开关风控                     ║                        │
│  ║     ↓                                    ║                        │
│  ║  执行: OKX 易经推理模块                     ║                        │
│  ║     (PollingTrader.run_tick →              ║                        │
│  ║      BCRMEngine → OKXSimulatedClient)      ║                        │
│  ║     · 子池隔离: bcrm≤5 / bdsm≤3           ║                        │
│  ║     · 资金共享(不切分) / 仓位打 tag        ║                        │
│  ╚══════════════════════════════════════════╝                        │
│                                                                       │
│  共享契约: bdsm_snapshot.json（见 §3）                                 │
└───────────────────────────────────────────────────────────────────────┘
```

### 2.2 三个约束操作的精确定义

#### 2.2.1 操作 A：方向硬约束（R1 落地）

BCRM 生成方向信号后，立即执行：

```
输入:
  bdsm_snapshot[symbol].direction_constraint
    = { LONG_ONLY | SHORT_ONLY | NEUTRAL } ← 见 §4.1
  bcrm_direction = { LONG | SHORT | HOLD }

规则:
  IF constraint == LONG_ONLY  AND bcrm_direction == SHORT → DROP → HOLD
  IF constraint == SHORT_ONLY AND bcrm_direction == LONG  → DROP → HOLD
  ELSE → PASS（信号不变）

输出:
  constrained_direction  +  drop_reason (null or "bdsm_long_only" etc.)
```

#### 2.2.2 操作 B：仓位上限取 MIN

BCRM 算出理想仓位（基于 confidence × `default_position_pct`）后，执行：

```
输入:
  bdsm_cap_multiplier = score_cap × rank_cap × data_quality_cap ← 见 §4.2
  bcrm_position_ratio = BCRM 自身计算的仓位 (0~1)

规则:
  actual_position = min(bcrm_position_ratio, max(0.0, bdsm_cap_multiplier))

举例:
  BCRM 想开 70%, BDSM cap=50% → 实际 50%
  BCRM 想开 30%, BDSM cap=50% → 实际 30%（BCRM 自主发挥）
  BDSM cap=0% → 不开仓（等价于 score < -0.3）
```

#### 2.2.3 操作 C：出场 OR 逻辑（R2 落地）

持仓中每次小时级出场检查：

```
输入:
  bdsm_exit_action = { NONE | REDUCE_50 | REDUCE_80 | CLOSE_ALL } ← 见 §4.3
  bcrm_exit_signal = { NONE | SL | TP | TRACKING_STOP | TSTP | REGIME_SWITCH }

规则:
  IF bdsm_exit_action == CLOSE_ALL → 立即执行 CLOSE_ALL（不讨论）
  IF bdsm_exit_action == REDUCE_80  → 先减 80%，剩余 20% 再走 BCRM 出场检查
  IF bdsm_exit_action == REDUCE_50  → 先减 50%，剩余再走 BCRM 出场检查
  ELSE → 完全交给 BCRM 技术面出场

优先级: CLOSE_ALL > REDUCE_80 > REDUCE_50 > BCRM any
```

***

## 3. 数据契约：bdsm\_snapshot.json

### 3.1 文件路径与写入时机

| 项      | 值                                                         |
| ------ | --------------------------------------------------------- |
| 路径     | `11-易经推理系统/.workbuddy/bdsm/bdsm_snapshot_{YYYYMMDD}.json` |
| 写入频率   | 每日收盘后（23:50 UTC+8）运行 1 次                                  |
| 读取方式   | BCRM 每 K 线周期读文件，若当日文件不存在或解析失败，回退 `_neutral_snapshot()`    |
| 文件大小估计 | 8 币 × \~40 字段/币 ≈ 4KB                                     |
| 历史留存   | 保留最近 30 天快照（用于 Phase 序列追踪，见 §4.3 B5）                      |

### 3.2 快照 Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "BDSMSnapshot",
  "type": "object",
  "required": ["snapshot_date", "generated_at", "version", "coins", "neutral_fallback_reason"],
  "properties": {
    "snapshot_date": {"type": "string", "format": "date", "description": "YYYY-MM-DD，快照对应交易日"},
    "generated_at": {"type": "string", "format": "date-time"},
    "version": {"const": "1.0"},
    "neutral_fallback_reason": {"type": "string", "description": "若整体为中性快照，填原因；正常为空字符串"},
    "coins": {
      "type": "object",
      "description": "key = 币种 (UNI/PUMP/HYPE/AAVE/SOL/CRCL/ETH) — BDSM 权威池 7 币；SKY 走纯 BCRM 不进入 BDSM 快照",
      "additionalProperties": {
        "type": "object",
        "required": ["available", "data_quality"],
        "properties": {
          "available": {"type": "boolean", "description": "该币 BDSM 数据是否可用（FALSE→中性兜底）"},
          "data_quality": {"enum": ["sufficient", "partial", "insufficient"]},
          "confidence": {"type": "number", "minimum": 0, "maximum": 1},
          "score": {"type": "number", "minimum": -1, "maximum": 1, "description": "fundamental_score（巴菲特安全边际折扣后）"},
          "score_raw": {"type": "number", "minimum": -1, "maximum": 1, "description": "折扣前的原始七信号合成分"},
          "rank": {"enum": ["S", "A", "B", "C"]},
          "e5": {"type": "number", "minimum": -1, "maximum": 1, "description": "供给缩减强度 (supply_shrinkage_intensity)"},
          "e6": {"type": "number", "minimum": -1, "maximum": 1, "description": "价值捕获质变 (value_capture_delta)"},
          "e7": {"type": "number", "minimum": -1, "maximum": 1, "description": "收入可持续性 (revenue_sustainability)"},
          "bds_score": {"type": "number", "minimum": -1, "maximum": 1, "description": "BDSM 综合 E7*40%+E6*30%+E5*30%"},
          "phase": {"enum": ["P1_EXPECTATION", "P2_REVENUE_EXPANSION", "P3_VALUATION_RECOVERY"]},
          "phase_confidence": {"type": "number", "minimum": 0, "maximum": 1},
          "valuation_percentile": {"type": "number", "minimum": 0, "maximum": 100},
          "direction_constraint": {"enum": ["LONG_ONLY", "SHORT_ONLY", "NEUTRAL"]},
          "cap_multiplier": {"type": "number", "minimum": 0, "maximum": 1},
          "exit_action": {"enum": ["NONE", "REDUCE_50", "REDUCE_80", "CLOSE_ALL"]},
          "exit_triggers": {"type": "array", "items": {"type": "string"}, "description": "例如 [\"B3_score_deterioration\", \"B4_e7_collapse\"]，非空则 exit_action 非 NONE"},
          "buffett_discount_applied": {"type": "boolean", "description": "是否已应用巴菲特安全边际折扣"}
        }
      }
    }
  }
}
```

### 3.3 FAIL-OPEN 中性快照定义（R3 落地）

当 BDSM 计算异常/文件不存在时，`_neutral_snapshot()` 返回：

- 每币：`available=false`, `data_quality="insufficient"`, `confidence=0.0`

- 合成：`score=0.0`, `rank="B"`, `phase="P2_REVENUE_EXPANSION"`（默认中性）

- 约束：`direction_constraint="NEUTRAL"`, `cap_multiplier=1.0`, `exit_action="NONE"`

- **字节等价「BDSM 不存在」**：BCRM 方向、仓位、出场完全不受影响

***

## 4. 单币约束与动作的计算规则

### 4.1 方向硬约束（direction\_constraint）

依据 `score`（已应用安全边际折扣后）：

| score 区间     | constraint  | 说明                                     |
| ------------ | ----------- | -------------------------------------- |
| score > 0.3  | LONG\_ONLY  | 只允许做多，丢弃 BCRM SHORT                    |
| score < -0.3 | SHORT\_ONLY | 只允许做空/规避，丢弃 BCRM LONG（实际通常配合 cap=0 规避） |
| 其余           | NEUTRAL     | 双向自由，BCRM 自主判断                         |

边界处理：

- `data_quality == "insufficient"` → 强制 `NEUTRAL`，即使 score 超阈值

- 币种 `available == false` → 强制 `NEUTRAL`

### 4.2 仓位上限系数（cap\_multiplier）

三层相乘，夹到 \[0, 1]：

```
cap_multiplier = clamp( score_cap × rank_cap × dq_cap , 0.0, 1.0 )
```

| 因子             | 规则                                                          | 值        |
| -------------- | ----------------------------------------------------------- | -------- |
| **score\_cap** | score>0.6→1.0；0.3~~0.6→0.8；0~~0.3→0.5；-0.3\~0→0.2；<-0.3→0.0 | \[0,1]   |
| **rank\_cap**  | S→1.0；A→0.8；B→0.5；C→0.2                                     | \[0,1]   |
| **dq\_cap**    | sufficient→1.0；partial→0.7；insufficient→0.0（数据不可靠不给仓位）      | \[0,0.7] |

**举例**：

- A 级 + score=0.4（>0.3，未达>0.6）+ sufficient → 0.8×0.8×1.0 = 0.64（上限 64%）

- B 级 + score=0.1 + partial → 0.5×0.5×0.7 = 0.175（上限 17.5%）

- C 级 + score=-0.4 + insufficient → 0×0.2×0 = 0（不开仓）

### 4.3 基本面出场触发（exit\_action + exit\_triggers）

5 种触发（B1\~B5）。优先级 CLOSE\_ALL > REDUCE\_80 > REDUCE\_50，多个同时触发取最高优先级动作，trigger 列表累积。

#### B1. Phase P2→P3（盈收转估值修复 → 减持落袋）

- **条件**：`current_phase` 从 P2 变 P3 且 `valuation_percentile > 80` 且 `bds_score >= 0.0`

- **对比**：今日快照 vs 昨日快照的 phase 字段（需读取昨日快照）

- **动作**：REDUCE\_50

- **巴菲特借鉴**：涨多了（估值>80%分位）即使基本面还行也落袋为安，不追高

#### B2. Phase 退化为中性或回 P1（逻辑失效 → 全出）

- **条件**：phase 从 P2/P3 变为「默认中性」（trigger 含 default\_neutral），或从 P2 转 P1 且 bds\_score < 0

- **对比**：今日 vs 昨日 phase + phase\_confidence

- **动作**：CLOSE\_ALL

- **巴菲特借鉴**：投资逻辑失效不硬扛（类似「能力圈之外，看不懂就不持有」）

#### B3. Score 趋势破位（基本面恶化日级确认 → 减半）

- **条件**：连续 2 日 `score` 从 > 0.3 跌破 0，或单日 `score_raw` 跌幅 ≥ 0.4（即当日分数暴跌）

- **对比**：今日 + 昨日 + 前日快照 score 值（需 3 日历史）

- **动作**：REDUCE\_50

- **巴菲特借鉴**：基本面破位（不是暂时波动）是纠错信号

#### B4. E7 收入质量崩溃（地基塌了 → 强减仓 80%）

- **条件**：前日 `e7 > 0` 且今日 `e7 <= 0`（收入质量从正翻负，之前有现在没了）

- **对比**：今日 vs 昨日 e7

- **动作**：REDUCE\_80

- **巴菲特借鉴**：Owner Earnings（收入）是安全边际的地基，地基塌了必须先跑，不要等市场确认

#### B5. Rank 连续降档（3 日内 A→B→C 持续恶化 → 全出）

- **条件**：3 天内 rank 经历 ≥ 2 级下降（如 S→B，或 A→C），或连续 ≥ 3 天 rank 在 C

- **对比**：最近 4 日快照的 rank 序列（S>A>B>C 的序关系）

- **动作**：CLOSE\_ALL

- **巴菲特借鉴**：管理层没变但基本面持续变差 =「滚雪球的山坡变了」，及早退出

**触发检测代码骨架（伪代码）**：

```python
t = today_snapshot[coin]
y = yest_snapshot.get(coin, {})  # 昨日
by = byest_snapshot.get(coin, {})  # 前日
tby = tbyest_snapshot.get(coin, {}) # 大前日

triggers, action = [], "NONE"
# B4 单独最高优先检测（e7 翻负）
if y.get("e7", 0) > 0 and t["e7"] <= 0:
    triggers.append("B4_e7_collapse")
    action = "REDUCE_80"
# B2 / B5 CLOSE_ALL 次之
if _phase_degraded(y, t) or _rank_tumbling([tby, by, y, t]):
    triggers += _b2_triggers(y, t) + _b5_triggers(...)
    action = "CLOSE_ALL"  # 覆盖 REDUCE_80
# B1 / B3 REDUCE_50 最低（若未被更高优先级覆盖）
if action == "NONE":
    if _b1_p2_to_p3(y, t): triggers.append("B1_p2_to_p3")
    if _b3_score_break([by, y, t]): triggers.append("B3_score_deterioration")
    if triggers: action = "REDUCE_50"
```

***

## 5. 巴菲特要素集成点（Phase 3 扩展，默认关闭）

### 5.1 安全边际折扣（`enable_buffett_discount`，默认 False）

在 score 计算末尾，合成后应用折扣：

```python
score_final = score_raw * 0.7  # 30% 安全边际折扣
# 注意：负值进一步打折会更负，这是正确行为（坏的更悲观）
# 若 score_raw < 0, score_final 可能超 -1，所以仍需 clamp
score_final = max(-1.0, min(1.0, score_final))
```

- 效果：原来 score\_raw > 0.3（阈值）需要 score\_raw ≈ 0.43 才能过 → 提高入场门槛，落实「别付太高价」

- 审计：快照里 `score_raw` 和 `score` 都保存，方便对比折扣前后信号差异

### 5.2 E7 负面不对称加权（`enable_e7_negative_bias`，默认 False）

在 `_compute_bdsm_signals` 的 E7 输出后：

```python
if e7 < 0:
    e7 = min(-1.0, e7 * 1.3)  # 负方向 1.3× 放大（与 traditional_finance_analyzer:137 对齐）
```

配合 B4（E7 翻负）形成「坏消息放大权重 + 立即强减仓」的双层保护。

### 5.3 能力圈标记（作为 audit 字段，暂不生效）

```json
"circle_of_competence": {"tag": "DeFi", "confidence": 0.85}  // 仅记录
```

未来可用于：若某币 BDSM data\_quality 长期 insufficient，标记为「圈外」，不建议重仓。

***

## 6. 三冲突场景处理

| ID             | 场景   | BDSM                     | BCRM                  | 处理                                           | 代码位置                                                                                               |
| -------------- | ---- | ------------------------ | --------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **CONFLICT-1** | 方向冲突 | score > 0.3 → LONG\_ONLY | 卦象 SHORT              | 丢弃 SHORT → HOLD，写日志 `bdsm_long_only_dropped` | §2.2.1 方向约束检查点（SignalRouter.route() 内，Step 1 生成信号后立刻）                                              |
| **CONFLICT-2** | 出场冲突 | B4 E7 崩溃 → REDUCE\_80    | TSTP 说继续持有            | 先执行 REDUCE\_80，剩余 20% 走 BCRM 出场逻辑（OR）        | §2.2.3 出场 OR 逻辑（PollingTrader.run\_tick 出场聚合器，先读 BDSM 快照 exit\_action，后执行 BCRM 技术出场）               |
| **CONFLICT-3** | 仓位冲突 | A 级 → cap 0.64           | confidence 0.9 → 0.70 | `actual = min(0.70, 0.64) = 0.64`            | §2.2.2 PollingTrader.\_try\_open\_position 中 `MIN(crm推荐, bdsm_cap_multiplier × subpool_alloc)` 计算后 |

**一致性要求**：三个约束操作必须在同一个 K 线周期内**原子执行**（在单次 route() 调用中完成约束+执行），避免跨周期 BDSM 快照与 BCRM 推理不一致。

***

## 7. 执行频率与时序

| 时间                      | BDSM 侧                                                        | BCRM 侧                                                             | 说明                             |
| ----------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------ |
| **每日 23:50 UTC+8**（收盘后） | ✅ 运行 `compute_all(8 币) + classify_phase`，写当日快照文件，计算 B1\~B5 触发 | —                                                                  | 必须在 BCRM 次日首条 K 线前完成           |
| **每 K 线周期（默认 1H）**      | —                                                             | ①读当日快照；②方向约束检查；③仓位上限 MIN；④K 线推理；⑤SL/TP；⑥出场 OR 逻辑（BDSM + BCRM 任一触发） | 读快照需 100ms 内完成（冷缓存可能 1-2s，可接受） |
| **小时级出场巡检**（持仓中）        | —                                                             | 每小时读当日快照（可复用进程内缓存，5min TTL），检查 exit\_action 是否为 REDUCE/CLOSE       | 无持仓时跳过                         |
| **每周一 09:00**           | ✅ 周级复盘：输出 phase 序列追踪报告（P1→P2→P3 实际流转 vs 预期）                   | —                                                                  | 审计 + 人工 Review                 |

**快照缓存策略**：

- BCRM 进程内缓存 `_snapshot_cache`：dict{date\_str: parsed\_json}

- TTL：5 分钟（即使文件不存在，FAIL-OPEN 兜底也能返回中性）

- 过期检查：`abs(now_ts - cache_load_ts) > 300s` → 重读

***

## 8. Shadow 模式与 A/B 验证（落地路径）

### 8.1 总开关矩阵

| 阶段          | `enable_bdsm_snapshot` | `enable_bdsm_constraints` | `enable_buffett_discount` | 说明                                        |
| ----------- | ---------------------- | ------------------------- | ------------------------- | ----------------------------------------- |
| **Phase 0** | True                   | False                     | False                     | 只写快照 + 记录「若生效会怎样」对比日志，不改 BCRM 实际执行        |
| **Phase 1** | True                   | False                     | True（可选）                  | 跑满 30 交易日 A/B 对比分析（纯 BCRM vs 若启用 BDSM 约束） |
| **Phase 2** | True                   | **True**                  | True（达标后）                 | 正式启用：约束生效，FAIL-OPEN 保证安全                  |
| **Phase 3** | True                   | True                      | True                      | 引入安全边际 + E7 负面加权（默认关闭，独立 PR 开启）           |

### 8.2 A/B 验证指标（Phase 1 必须通过才能进入 Phase 2）

对比两条轨迹：`实际 = 纯 BCRM` vs `反事实 = BDSM+BCRM（若启用）`

| 指标       | 通过门槛（不得显著劣于纯 BCRM）                         | 统计样本要求                     |
| -------- | ------------------------------------------ | -------------------------- |
| 最大回撤 MDD | MDD\_BDSM+BCRM ≤ 1.20 × MDD\_纯BCRM         | ≥ 30 交易日，或 ≥ 100 笔 BCRM 信号 |
| 信号丢弃率    | 被 R1 丢弃的 BCRM 信号 ≤ 15%                     | 同上                         |
| 胜率       | WinRate\_BDSM+BCRM ≥ 0.90 × WinRate\_纯BCRM | 同上                         |
| 方向约束错误丢弃 | 被丢弃但事后该笔盈利 ≥ 3σ 的次数 ≤ 2 次/月                | 同上                         |
| 出场效果     | BDSM 出场的平均 PnL ≥ BCRM 技术出场 0.90 倍          | ≥ 20 次 BDSM 触发出场           |

不达标 → 停留在 Phase 0/1，调参后重新验证。

***

## 9. 代码改动影响面

| 路径                                                             | 改动内容                                                                    | 侵入性        | Phase                        |
| -------------------------------------------------------------- | ----------------------------------------------------------------------- | ---------- | ---------------------------- |
| `coin_fundamental_ranker.py`                                   | 新增 `BDSM_COINS` 常量导出                                                    | 低（新增常量）    | Phase 0                      |
| 新增 `bdsm_snapshot_writer.py`                                   | 每日运行：compute\_all → classify\_phase → 计算约束 → 写 JSON                     | 低（新增脚本）    | Phase 0                      |
| 以上 5 个代币池处（§1.3）                                               | 补齐 AAVE/SKY/CRCL/ETH 等缺失 BDSM 币种                                        | 低（列表/集合扩展） | Phase 0                      |
| `SignalRouter.route()` 或 PollingTrader.\_try\_open\_position 前 | 操作 A：方向约束检查（读快照→DROP 反方向 + SHORT\_BAN ETH/BTC）                          | 中          | Phase 2                      |
| `PollingTrader._try_open_position()`                           | 操作 B：仓位上限 MIN(crm 推荐 × bdsm\_cap × subpool\_alloc)；子池预检 bcrm≤5 / bdsm≤3 | 中          | Phase 2（source\_tag + R5 铁律） |
| `PollingTrader.run_tick()` 出场聚合段                               | 操作 C：出场 OR 逻辑（先 BDSM exit\_action 再 BCRM 技术出场）                          | 中          | Phase 2                      |
| `coin_fundamental_crypto.py`                                   | E7 负面不对称加权（默认关闭）                                                        | 低（受开关保护）   | Phase 3                      |
| `coin_fundamental_ranker._synthesize_score`                    | 安全边际折扣（默认关闭）                                                            | 低（受开关保护）   | Phase 3                      |
| BDSM collector 层                                               | 补 ETH 原生采集器（或确认回退链路 OK）；SKY **暂缓**，等 BDSM 质量通过后再评估是否回归池                 | 中          | Phase 0 或 Phase 2 前完成        |

***

## 10. 测试与验收清单

### 10.1 单元测试

| #     | 用例                                                             | 预期                       |
| ----- | -------------------------------------------------------------- | ------------------------ |
| UT-01 | 中性快照解析 → 约束全为 PASS，cap=1.0                                     | BCRM 完全不被约束              |
| UT-02 | score=0.5, rank=A → constraint=LONG\_ONLY, cap=0.8×0.8=0.64    | 反方向信号丢弃，仓位上限 64%         |
| UT-03 | score=-0.5, rank=C → constraint=SHORT\_ONLY, cap=0             | 不开仓，正方向信号丢弃              |
| UT-04 | B4 E7 前日 +0.2 → 今日 0.0 → exit\_action=REDUCE\_80               | 强减仓 80%，剩余 20% 正常 BCRM   |
| UT-05 | B1 phase P2→P3 + 估值 > 80 → REDUCE\_50                          | 减半                       |
| UT-06 | 快照文件不存在 → FAIL-OPEN 中性快照                                       | 无异常，等价无 BDSM             |
| UT-07 | 方向冲突场景（BDSM LONG\_ONLY vs BCRM SHORT） → HOLD + drop\_reason 记录 | 不执行 SHORT                |
| UT-08 | 仓位冲突（BCRM 70% vs BDSM cap 50% → 实际 50%）                        | 日志记录 cap\_capped\_to\_50 |

### 10.2 集成测试

| #     | 用例                                        | 预期                     |
| ----- | ----------------------------------------- | ---------------------- |
| IT-01 | Phase 0：30 个模拟日，每天写快照后读快照 → 无 BCRM 实际执行改变 | Shadow 日志正常，真实持仓不变     |
| IT-02 | A/B 对比：同一批 100 条历史 BCRM 信号 × 双跑           | 统计指标符合 §8.2 门槛才可上线约束   |
| IT-03 | 故障注入：快照写一半崩了/JSON 格式错误                    | BCRM 读失败 → 中性兜底 → 交易正常 |

### 10.3 E2E 实盘（Phase 2 前必须）

| #      | 用例                                        | 预期                                        |
| ------ | ----------------------------------------- | ----------------------------------------- |
| E2E-01 | 8 币 Shadow 模式跑 7 日                        | 快照生成率 100%，无错误日志                          |
| E2E-02 | 人工模拟 B1/B4 触发（改快照）→ 观察 BCRM 是否正确执行 REDUCE | OKX 模拟端（OKXSimulatedClient）持仓/可用资金变化与日志一致 |
| E2E-03 | 移除 BDSM 环境（临时改路径使文件读不到）→ 跑一轮 BCRM 全链路     | 交易结果与未启用 BDSM 完全一致（R3 字节等价验证）             |

***

## 11. 风险与缓释

| ID    | 风险                                         | 概率 | 影响 | 缓释                                                                 |
| ----- | ------------------------------------------ | -- | -- | ------------------------------------------------------------------ |
| RSK-1 | 基本面滞后于价格（BDSM 日级 vs 价格秒级暴跌）                | 高  | 中高 | BCRM 技术止损（SL/追踪止损）兜底；B3/B4 作为大周期事后确认                               |
| RSK-2 | BDSM 方向约束过度限制，丢弃 BCRM 本可盈利的反向信号            | 中  | 中  | Phase 1 统计「若生效会错过的 PnL」占比 ≤ 15% 才开约束                               |
| RSK-3 | E7 数据更新慢（月级）→ B4 是事后信号                     | 中  | 中  | 配合 B3（score 日级恶化）作为前置预警；E7 负值后若连续 3 日保持则触发 B5 全出                   |
| RSK-4 | 8 币之外的 BDSM 盲区币种（BTC 等）                    | 中  | 低  | 盲区币种走 `available=false → 中性约束`，完全由 BCRM 自主，等价于未接入                  |
| RSK-5 | 快照读取慢或进程缓存 TTL 导致读旧文件                      | 低  | 低  | 5 分钟 TTL 保守设置；文件内容带 `generated_at` 时间戳，BCRM 侧可校验新鲜度                |
| RSK-6 | AAVE 等新增币种缺乏 BCRM 特征工程适配（如 KNOWN\_MCAP 缺失） | 中  | 中  | Phase 0 先补特征工程，确保新增币 BCRM 自身推理质量达标后再跑 A/B；SKY 留纯 BCRM 不接入 BDSM 以规避 |

***

## 12. 决策与开放问题

1. **【已决策】SKY 从 BDSM 权威池暂移除。** SKY 原生 collector 未实现、回退链路质量未知；BDSM 权威池维持 7 币（UNI/PUMP/HYPE/AAVE/SOL/CRCL/ETH）。SKY 保留纯 BCRM 推理，`source_tag=bcrm` 计入 **bcrm≤5** 子池，不占用 BDSM 3 仓额度。后续 collector 补齐 + 质量达标后可提案回归。
2. **巴菲特安全边际折扣系数 0.7 是否过硬？** 可改为 `0.8 - volatility_adjustment`：高波动时折扣更大，低波动时更温和。但 Phase 3 才启用，届时再定。
3. **B2 Phase 退化为中性的判定阈值**：当前默认 `default_neutral` 触发是否过宽？是否应要求 `phase_confidence < 0.3` 才判退化？
4. **币种池统一常量 BDSM\_COINS 是否应提到底层共享包？** 当前在 coin\_fundamental\_ranker.py 定义，若 polling\_trader.py 等多处 import 可能有循环依赖，需设计合理导出路径。

***

## 附录 A：数据流时序（完整 24h 循环）

```
T=23:50  【BDSM每日运行】
          ├─ 读 data_center.db（8 币原生采集器 metrics + raw）
          ├─ compute_all × 8
          ├─ classify_phase × 8
          ├─ 读取近 4 日历史快照 → 计算 B1~B5 触发
          ├─ 可选：巴菲特折扣 (score×0.7) + E7 负面加权
          ├─ 计算 direction_constraint / cap_multiplier / exit_action
          └─ 写 bdsm_snapshot_YYYYMMDD.json + 写 shadow_audit_log.jsonl

T=00:00  【BCRM K线周期开始】
          ├─ 读当日快照（读不到→中性），写入进程缓存（TTL 5min）
          ├─ BDSM 8 币 + 其他币生成信号
          │    ├─ BDSM 币：方向约束检查 (操作 A) → DROP 反向
          │    ├─ K线推理 (344+278)
          │    ├─ 仓位上限 MIN (操作 B) + 子池预检(R5: bcrm≤5/bdsm≤3)
          │    ├─ SL/TP (ATR 动态 + 爆仓安全)
          │    ├─ 方案 C 8 开关
          │    └─ SHORT_BAN(仅做多币): ETH/BTC
          └─ OKXSimulatedClient 下单（source_tag 持久化）

T=每小时  【出场巡检】（持仓中）
          ├─ 复用快照缓存（过期重读）
          ├─ 出场 OR (操作 C): BDSM exit_action → BCRM 技术出场
          └─ 执行减仓/平仓（若触发）
```

