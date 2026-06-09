---
name: dream-strategy-parser
description: 战略解析器v2.0 - 读取strategy_library.yaml v3.0，按7种Regime匹配策略+工具组合，输出战略指令到评分系统。触发词：战略解析、strategy parse、战略匹配、战略指令、strategy directive、Step0路由、Regime匹配、策略选择。
license: Internal
version: 2.0.0
created: "2026-04-20"
updated: "2026-04-27"
---

# Dream-Strategy-Parser v2.0: 战略解析器

## v1.0→v2.0 核心变化

| 维度 | v1.0(旧) | v2.0(新) |
|:---|:---|:---|
| 数据源 | strategy_library v2.2(22条概念策略) | strategy_library v3.0(35条实战策略) |
| Regime | 6种(手动映射) | 7种(YAML内置regimes定义) |
| 策略匹配 | 逐条检查trigger_conditions | 先按regime筛选→再按priority排序 |
| 输出 | 单策略匹配 | 多策略组合(总仓位≤20%) |
| 工具 | 无工具命令 | 每策略带tool_commands可直接执行 |
| 命名 | 孙子兵法(以逸待劳) | 直白描述(趋势跟随做多) |
| 费率 | 笼统提及 | 三层(套利/信号/增收) |
| 跨资产 | 无 | 5种跨资产组合 |

## 目标
- 在交易主流程 Step0 之前，读取 `strategy_library.yaml` v3.0
- 根据当前Regime匹配策略组合(非单策略)
- 输出结构化战略指令，含工具命令可直接执行
- 总仓位硬限20%

## 输入（建议字段）
- `market_state`（来自 `technical-analyst` / `dream_main_v4.py`）
  - `trend_direction`: "BULL" | "BEAR" | "NEUTRAL_UP" | "NEUTRAL_DOWN" | "UNCLEAR"
  - `resistance_minimum`: "UP" | "DOWN" | "NEUTRAL"
  - `trend_continuation`: boolean
  - `rsi_state`: "oversold" | "overbought" | "neutral"
  - `rsi_1h`: number
  - `vol_regime`: "high" | "low" | "unknown"
  - `price`: number
  - `atr_pct`: number (ATR/Price*100)
  - `ema7_w`: number (周线MA7)
  - `ema25_w`: number (周线MA25)
  - `ema99_w`: number (周线MA99)
  - `ema7_d`: number (日线MA7)
  - `ema25_d`: number (日线MA25)
- `funding_rate`: number（来自 OKX）
- `funding_rate_history`: number[]（近7天费率）
- `open_interest_delta_pct`: number（来自 OKX）
- `fgi`: number (Fear & Greed Index)
- `macro_sentiment`: "risk_on" | "risk_off" | "neutral"（来自 tavily）
- `gold_trend`: "UP" | "DOWN" | "FLAT"（来自宏观监控）
- `coin_stock_trend`: "UP" | "DOWN" | "FLAT"（来自宏观监控）
- `eth_btc_ratio`: number（ETH/BTC比率）
- `inst_id`: string（默认 "BTC-USDT-SWAP"）
- `current_positions`: object（当前持仓状态）
- `current_equity`: number（账户权益）

## 执行流程

### Step1: Regime识别
根据输入market_state，匹配7种Regime之一：

```yaml
TREND_STRONG_UP:
  条件: "周线多 + 日线多 + 1H多 + MA7>MA25>MA99 + ATR扩张 + trend_continuation==true"
  si_range: [35, 80]

TREND_UP:
  条件: "日线多 + 1H偏多 + MA7>MA25 + ATR正常 + trend_direction==BULL"
  si_range: [20, 34]

RANGE_BOUND:
  条件: "三屏分化 + MA7≈MA25 + ATR收缩 + 支撑阻力明确 + trend_direction IN [NEUTRAL_*, UNCLEAR]"
  si_range: [15, 25]

COMPRESSION:
  条件: "ATR持续收窄至历史低位 + 布林带收窄 + OI增加 + atr_pct<历史20%分位"
  si_range: [10, 20]

TRANSITION:
  条件: "Regime刚切换(3日内) + 旧趋势衰减+新趋势未确认 + 信号矛盾"
  si_range: [10, 25]

TREND_DOWN:
  条件: "日线空 + 1H偏空 + MA7<MA25<MA99 + 价格低于EMA60 + trend_direction==BEAR"
  si_range: [5, 15]

EXTREME:
  条件: "单日涨跌>5% OR FGI<15 OR FGI>85 + 费率极端"
  si_range: [0, 100]
```

### Step2: 策略筛选
1. 从YAML的`strategies`中筛选`regime`字段匹配当前Regime的所有策略
2. 跨Regime策略(`regime`为数组)也纳入筛选
3. 按`priority`排序(1=最高优先级=收益预期最高)
4. 检查每条策略的`trigger`条件是否满足

### Step3: 仓位组合
1. 从P1策略开始，逐个累加仓位
2. 总仓位不超过20%
3. 同一Regime下可选1-4个策略组合
4. 输出组合及各策略仓位占比

### Step4: 工具命令生成
1. 从匹配策略的`command`字段提取OKX CLI命令模板
2. 用当前行情参数填充`{instId}`, `{sz}`, `{lever}`等占位符
3. 计算sz: equity × position_pct × lever / (price × contract_size)

### Step5: 输出战略指令

## 输出结构（v2.0）

```json
{
  "strategy_directive": {
    "current_regime": "RANGE_BOUND",
    "regime_confidence": 0.85,
    "regime_signals": ["MA7≈MA25", "ATR收缩", "支撑阻力明确"],
    "previous_regime": "TREND_UP",
    "regime_changed": true,
    "regime_change_hours": 6,
    "strategies": [
      {
        "id": "range_neutral_grid",
        "name": "中性双向网格",
        "priority": 1,
        "expected_return": "中(稳定)",
        "tool": "grid",
        "position": "5%",
        "leverage": "1-2x",
        "trigger_met": true,
        "trigger_details": "regime==RANGE_BOUND AND 区间宽度>3%",
        "command": "okx bot grid create --instId BTC-USDT-SWAP ...",
        "risk_notes": "区间突破后单边亏损"
      },
      {
        "id": "range_farming_income",
        "name": "费率+网格双重收入",
        "priority": 2,
        "expected_return": "中(双重叠加)",
        "tool": "farming+grid",
        "position": "5%",
        "leverage": "2x",
        "trigger_met": true,
        "trigger_details": "regime==RANGE_BOUND AND funding_rate<0",
        "risk_notes": "费率翻转+破位双重亏损"
      },
      {
        "id": "range_dca_bottom",
        "name": "区间下部DCA低吸",
        "priority": 3,
        "expected_return": "中低",
        "tool": "dca",
        "position": "5%",
        "leverage": "2x",
        "trigger_met": true,
        "trigger_details": "regime==RANGE_BOUND AND price<区间中轴",
        "command": "okx bot dca create ...",
        "risk_notes": "跌破区间下沿"
      }
    ],
    "cross_asset_strategies": [
      {
        "id": "cross_asset_mean_revert",
        "name": "BTC空+COIN多(均值回归)",
        "applicable_regimes": ["RANGE_BOUND", "TRANSITION"],
        "trigger_met": false,
        "reason": "COIN未相对BTC走强"
      }
    ],
    "total_position": "15%",
    "position_cap": "20%",
    "position_available": "5%",
    "directive_bias": "NEUTRAL",
    "funding_layer": {
      "current_rate": -0.0024,
      "layer_1_arb": false,
      "layer_1_reason": "费率同向持续不足3天",
      "layer_2_signal": false,
      "layer_2_reason": "费率未达2σ极端",
      "layer_3_income": true,
      "layer_3_reason": "负费率+多头持仓=同向增收"
    }
  },
  "meta": {
    "parser_version": "2.0.0",
    "library_version": "3.0.0",
    "timestamp": "2026-04-27T18:00:00Z",
    "trace_id": "string"
  }
}
```

## Regime→策略速查矩阵（A4快速索引）

| Regime | P1策略 | P2策略 | P3策略 | 总仓位 |
|:---|:---|:---|:---|:---:|
| TREND_STRONG_UP | 趋势跟随做多(swap) | 看涨期权(option) | 趋势定投(dca) | 18% |
| TREND_UP | 温和做多(swap) | 偏多网格(grid) | 逢低定投(dca) | 18% |
| RANGE_BOUND | 中性网格(grid) | 费率+网格(farming) | DCA低吸(dca) | 15% |
| COMPRESSION | 跨式期权(option) | 双向挂单(swap) | 窄网格(grid) | 11% |
| TRANSITION | 多策略试探(multi) | 费率观察(farming) | 小仓跨式(option) | 9% |
| TREND_DOWN | 趋势做空(swap) | 马丁摊薄(dca) | 看跌期权(option) | 15% |
| EXTREME | 恐慌抄底(swap) | 期权对冲(option) | 全面降仓 | 5% |

## 评分注入规则（对接 dream-signal-scoring-spec）

### 第7维度: strategy_match (0-10)
- 匹配到Regime + P1策略 + trigger全部满足 → 9-10
- 匹配到Regime + P1策略 + trigger部分满足 → 7-8
- 匹配到Regime + P2策略 → 5-7
- Regime不确定(TRANSITION/COMPRESSION) → 3-5
- 无匹配Regime → 1-3

### directive_bias 影响
| directive_bias | 行为 |
|:---|:---|
| LONG + 评分>35 | 强化买入信号 |
| SHORT + 评分<15 | 强化做空信号 |
| NEUTRAL | 评分系统正常工作 |
| WAIT → 评分达标 | `SOFT_WARN_STRATEGY_DIRECTS_WAIT`(允许覆盖) |
| CONTRARIAN | 逆向信号，需额外确认 |
| REDUCE | 强制降级 `DEGRADE_STRATEGY_REDUCED_RISK` |

### position_modifier 影响
- 传入 `dream-risk-position-sizing` 作为最大仓位系数
- 多策略组合总仓位 ≤ 20%
- leverage_cap 覆盖默认杠杆设置

## 门禁校验规则（对接 dream-pretrade-gatekeeper）

| 条件 | 门禁结果 |
|:---|:---|
| 策略trigger未满足 | `HARD_FAIL_STRATEGY_TRIGGER_NOT_MET` |
| 策略被排除条件命中 | `HARD_FAIL_STRATEGY_EXCLUDED` |
| 总仓位>20% | `HARD_FAIL_POSITION_CAP_EXCEEDED` |
| directive=REDUCE + 有持仓 | `DEGRADE_STRATEGY_REDUCED_RISK` |
| directive=WAIT + 评分>35 | `SOFT_WARN_STRATEGY_DIRECTS_WAIT` |
| 无匹配 + regime=EXTREME | `HARD_FAIL_NO_STRATEGY_EXTREME_REGIME` |
| Regime=COMPRESSION + 期权策略 | `SOFT_WARN_OPTION_LIQUIDITY_CHECK` |

## 费率三层注入逻辑

```yaml
layer_1_arb_check:
  trigger: "abs(funding_rate) > 0.0003 AND funding_same_sign_days >= 3"
  action: "标记套利层可用"
  position_add: "3-5%"

layer_2_signal_check:
  trigger: "abs(funding_rate) > historical_2sigma"
  action: "标记信号层触发(极端→反转)"
  direction: "费率极端正→偏空，费率极端负→偏多"

layer_3_income_check:
  trigger: "持仓方向与费率付费方向一致"
  action: "标记增收层可用(额外收息)"
  position_add: "0%(已在持仓中)"
```

## 跨资产策略匹配逻辑

```yaml
cross_asset_check:
  safe_haven:
    trigger: "FGI<30 AND gold_trend==UP AND crypto_trend==DOWN"
    action: "推荐BTC空+XAUT多(避险对冲)"
    regimes: [TREND_DOWN, EXTREME, TRANSITION]

  industry_resonance:
    trigger: "crypto_trend==UP AND coin_stock_trend==UP"
    action: "推荐BTC多+COIN多(行业共振)"
    regimes: [TREND_STRONG_UP, TREND_UP]

  mean_revert:
    trigger: "coin_outperform_btc == true"
    action: "推荐BTC空+COIN多(均值回归)"
    regimes: [RANGE_BOUND, TRANSITION]

  gold_btc_corr:
    trigger: "correlation_break == true"
    action: "推荐做多弱势+做空强势"
    regimes: [RANGE_BOUND, COMPRESSION]

  eth_rotation:
    trigger: "eth_btc_ratio_breakout == true"
    action: "推荐多强势+空弱势"
    regimes: [TREND_UP, RANGE_BOUND]
```

## sz计算规则

```yaml
sz_calculation:
  formula: "sz = floor(equity * position_pct * leverage / (price * contract_size))"
  contract_size:
    BTC-USDT-SWAP: 0.01  # 1张=0.01BTC
    ETH-USDT-SWAP: 0.1   # 1张=0.1ETH
    SOL-USDT-SWAP: 1     # 1张=1SOL
  examples:
    - equity=5800, position_pct=0.05, leverage=2, price=78000, cs=0.01
    - sz = floor(5800 * 0.05 * 2 / (78000 * 0.01)) = floor(580/780) = 0 → 最少1张
    - 实际保证金 = 1 * 78000 * 0.01 / 2 = $390
```

## Fail-Safe
- YAML解析失败 → 默认WAIT + `strategy_match=3`，不阻断交易
- 无法判定Regime → 默认TRANSITION + `strategy_match=5`
- 多Regime同时匹配 → 选confidence最高的，标记regime_conflict=true
- 仓位计算<1张 → 最少1张 + 标记position_warning=true
- 跨资产策略触发但资产不可用 → 跳过该策略 + 标记asset_unavailable=true

## Integration
- 上游：`technical-analyst`、OKX 行情 API、`tavily` 宏观数据、`ontology` 记忆
- 下游：`dream-signal-scoring-spec`（第7维度注入）、`dream-pretrade-gatekeeper`（战略校验）、`dream-risk-position-sizing`（仓位系数）
- 数据源：`strategy_library.yaml` v3.0（项目根目录）
- 知识库：`.knowledge_base/2_classic_strategies/by_regime/STRATEGY_TOOLBOX_v3.md`

## 约束
- 不负责下单、不改参数；只做战略解析与指令输出
- 输出必须可序列化，便于注入评分系统和门禁
- 总仓位硬限20%，不可覆盖
- 期权策略仅限BTC，ETH需额外确认
- 排除条件优先级高于触发条件（排除条件一票否决）
- 无匹配战略时不阻断交易流程（默认 WAIT），但在 EXTREME regime 下阻断

---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将工作总结写入指定邮箱目录。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 战略解析器 |
| **目标邮箱** | 调研部邮箱 (research) |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/research/` |
| **投递方式** | 直接复制/写入Markdown文件到指定目录 |
