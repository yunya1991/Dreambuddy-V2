---
title: "A3 应急预案 — 2026-04-28"
department: trading
type: strategy
date: "2026-04-28T00:00:00"
status: completed
tags: ["EP006"]
chain_phase: A3
ep: "EP006"
---

# A3 应急预案 — 2026-04-28

**版本**: A3 v3.0 应急预案
**EP**: EP006
**关联战略**: a3_strategy_20260428_0230.md
**Regime**: RANGE_BOUND_DOWNSIDE

---

## 1. 应急总则

### 1.1 风险等级定义

| 等级 | 触发条件 | 响应速度 | 决策权 |
|:---|:---|:---|:---|
| 🔴 **P0 紧急** | 系统性风险/账户安全 | 立即(5min内) | 自动执行 |
| 🟠 **P1 高** | 重大事件/破位确认 | 30min内 | A5综合判断 |
| 🟡 **P2 中** | 常规事件/区间波动 | 4h内 | A4验证后执行 |
| 🟢 **P3 低** | 预防性/观察性 | 下一轮循环 | A3重新评估 |

### 1.2 核心原则

1. **本金第一**: $5,845 Equity → 最大可承受亏损 $584(10%)
2. **熔断红线**: Equity < $5,000 → 全部平仓+暂停交易24h
3. **杠杆红线**: MAX = 2x，任何新开仓不得超过2x
4. **净持仓红线**: |净持仓| > 0.5张 → 减仓至0.3张以下

---

## 2. 黑天鹅预案

### BS-001: 美伊局势突变

| 项目 | 内容 |
|:---|:---|
| **触发条件** | 美伊谈判破裂/霍尔木兹封锁/军事冲突升级 |
| **触发时间** | 2026-04-28 全天 |
| **概率** | 15-20% |
| **预期影响** | BTC暴跌5-15%，油价暴涨至$120+ |
| **响应等级** | 🔴 P0 |
| **响应行动** | ① 全平LONG 0.25张(市价) ② 加仓SHORT至0.5张 ③ 设置移动止损 |
| **止损** | SHORT SL@$78,500(距预期入场~3%) |
| **目标** | $72,000(极端情景) → $74,000(保守) |
| **最大亏损** | ~$100(1.7%账户) |

**OKX CLI执行**:
```bash
# 紧急平多
okx swap close --instId BTC-USDT-SWAP --posSide long --sz 0.25 --profile dreamdemo

# 加空
okx swap place --instId BTC-USDT-SWAP --side sell --ordType market \
  --sz 0.19 --posSide short --tdMode cross --lever 2 --profile dreamdemo

# 移动止损
okx swap algo trail --instId BTC-USDT-SWAP --side buy --sz 0.5 \
  --posSide short --callbackRatio 0.03 --tdMode cross --profile dreamdemo
```

### BS-002: FOMC超鹰派

| 项目 | 内容 |
|:---|:---|
| **触发条件** | 加息/Fed暗示2027年前不降息/CPI超4% |
| **触发时间** | 2026-04-29 凌晨 |
| **概率** | 25% |
| **预期影响** | BTC下跌3-8%，测试$74,766 |
| **响应等级** | 🔴 P0 |
| **响应行动** | ① 确认跌破$76,500后加空 ② 设置条件委托 |
| **止损** | $78,000(收复即止损) |
| **目标** | $74,000-$75,000 |

**OKX CLI执行**:
```bash
# 条件委托: 跌破$76,500追空
okx swap algo place --instId BTC-USDT-SWAP --side sell --sz 0.05 \
  --posSide short --slTriggerPx 76500 --slOrdPx=-1 \
  --tdMode isolated --profile dreamdemo
```

### BS-003: FOMC超鸽派

| 项目 | 内容 |
|:---|:---|
| **触发条件** | 降息信号/鸽派措辞/暗示2026年降息 |
| **触发时间** | 2026-04-29 凌晨 |
| **概率** | 20% |
| **预期影响** | BTC上涨3-8%，测试$80,000 |
| **响应等级** | 🔴 P0 |
| **响应行动** | ① 平SHORT 0.31张 ② $78,000确认后加多 |
| **止损** | $76,000 |
| **目标** | $80,000→$82,000 |

**OKX CLI执行**:
```bash
# 平空
okx swap close --instId BTC-USDT-SWAP --posSide short --sz 0.31 --profile dreamdemo

# 条件委托: 站稳$78,000追多
okx swap algo place --instId BTC-USDT-SWAP --side buy --sz 0.05 \
  --posSide long --tpTriggerPx 78000 --tpOrdPx=-1 \
  --tdMode isolated --profile dreamdemo
```

---

## 3. 极端行情预案

### EXT-001: 1H急涨/急跌>5%

| 项目 | 内容 |
|:---|:---|
| **触发条件** | 1小时内涨跌超过5%($76,659±$3,833) |
| **响应等级** | 🟠 P1 |
| **响应行动** | 反向对冲: 急涨→加空0.05张 / 急跌→加多0.05张 |
| **止损** | 1.5% |
| **目标** | 2% |
| **最大亏损** | ~$15(0.3%账户) |

### EXT-002: 假突破确认

| 项目 | 内容 |
|:---|:---|
| **触发条件** | 突破关键位后4h内收回(如$79,490模式) |
| **响应等级** | 🟠 P1 |
| **响应行动** | SKIP — 不追突破，等回踩确认 |
| **经验教训** | 04-28 $79,490 Bull Trap = 经典假突破模式 |

### EXT-003: 费率极端翻转

| 项目 | 内容 |
|:---|:---|
| **触发条件** | 费率从正转负/从负转正(振幅>0.02%) |
| **当前状态** | 费率刚从48天负值→微正+0.008% |
| **响应等级** | 🟡 P2 |
| **响应行动** | 费率转正持续3期(12h)=空头回补信号=偏多 |
| **历史参考** | 04-28首次转正，需观察08:00结算后是否维持 |

---

## 4. 事件驱动预案

### EVT-001: 美伊谈判结果

| 结果 | 概率 | 市场反应 | 应对 |
|:---|:---:|:---|:---|
| 谈判成功/停火重启 | 30% | BTC +3~8% | BS-003模式: 平空+追多 |
| 谈判僵持/无结果 | 40% | BTC ±1~2% | 维持SKIP |
| 谈判破裂/升级 | 30% | BTC -5~15% | BS-001模式: 平多+加空 |

### EVT-002: FOMC决议

| 结果 | 概率 | 市场反应 | 应对 |
|:---|:---:|:---|:---|
| 鸽派(降息暗示) | 20% | BTC +3~8% | BS-003: 追多 |
| 中性(维持不变) | 50% | BTC ±2% | 维持SKIP |
| 鹰派(加息/推迟) | 30% | BTC -3~8% | BS-002: 追空 |

### EVT-003: 费率结算(08:00)

| 结果 | 概率 | 含义 | 应对 |
|:---|:---:|:---|:---|
| 费率维持正值 | 40% | 空头持续回补=偏多 | 提高SI_Index+10 |
| 费率回落负值 | 50% | 空头重新入场=偏空 | 维持当前判断 |
| 费率大幅转正>0.02% | 10% | 空头踩踏=强多信号 | 重新评估→可能转BUY |

---

## 5. 持仓管理预案

### POS-001: $76,500破位

| 项目 | 内容 |
|:---|:---|
| **触发条件** | BTC跌破$76,500 + 4h收盘确认 |
| **响应等级** | 🟠 P1 |
| **响应行动** | LONG 0.25张 → 评估是否止损 / SHORT 0.31张 → 加仓至0.5张 |
| **LONG止损判断**: 04-26锤子线低点$77,035已破，$76,500是最后防线。跌破→止损LONG |
| **净持仓调整**: 目标净空头0.3-0.5张 |

**执行命令**:
```bash
# 平LONG(止损)
okx swap close --instId BTC-USDT-SWAP --posSide long --sz 0.25 --profile dreamdemo

# 加SHORT
okx swap place --instId BTC-USDT-SWAP --side sell --ordType market \
  --sz 0.19 --posSide short --tdMode cross --lever 2 --profile dreamdemo
```

### POS-002: ETH降杠杆

| 项目 | 内容 |
|:---|:---|
| **触发条件** | 当前5x杠杆违反MAX=2x规定 |
| **响应等级** | 🔴 P0 |
| **响应行动** | A4验证时执行: 降杠杆5x→2x 或 平仓 |
| **风险**: 5x杠杆下ETH波动1%=$23.18亏损 |
| **建议**: 平仓ETH LONG 0.1张(浮亏-$0.34)，避免杠杆风险 |

**执行命令**:
```bash
# 平ETH LONG
okx swap close --instId ETH-USDT-SWAP --posSide long --sz 0.1 --profile dreamdemo
```

### POS-003: algo重建

| 项目 | 内容 |
|:---|:---|
| **触发条件** | algo-pending为空(已确认) |
| **响应等级** | 🔴 P0 |
| **响应行动** | A4立即重建所有SL/TP委托 |
| **BTC LONG SL**: $76,200 (核心支撑破位) |
| **BTC LONG TP**: $78,500 (MA20阻力) |
| **BTC SHORT SL**: $77,500 (反弹回破) |
| **BTC SHORT TP**: $75,000 (弱支撑) |

**执行命令**:
```bash
# BTC LONG SL
okx swap algo place --instId BTC-USDT-SWAP --side sell --sz 0.25 \
  --posSide long --slTriggerPx 76200 --slOrdPx=-1 \
  --tdMode cross --profile dreamdemo

# BTC LONG TP  
okx swap algo place --instId BTC-USDT-SWAP --side sell --sz 0.25 \
  --posSide long --tpTriggerPx 78500 --tpOrdPx=-1 \
  --tdMode cross --profile dreamdemo

# BTC SHORT SL
okx swap algo place --instId BTC-USDT-SWAP --side buy --sz 0.31 \
  --posSide short --slTriggerPx 77500 --slOrdPx=-1 \
  --tdMode isolated --profile dreamdemo

# BTC SHORT TP
okx swap algo place --instId BTC-USDT-SWAP --side buy --sz 0.31 \
  --posSide short --tpTriggerPx 75000 --tpOrdPx=-1 \
  --tdMode isolated --profile dreamdemo
```

---

## 6. 熔断预案

### CIRCUIT-001: Equity熔断

| 触发条件 | Equity < $5,000 | Equity < $4,500 | Equity < $4,000 |
|:---|:---|:---|:---|
| **亏损幅度** | -14.5% | -23% | -31.6% |
| **响应** | 全部平仓+暂停8h | 全部平仓+暂停24h | 全部平仓+暂停72h |
| **通知** | A6告警+日志 | A6告警+秘书通知 | A6告警+秘书通知+人工确认 |

### CIRCUIT-002: PTSD熔断

| 项目 | 内容 |
|:---|:---|
| **创伤记录** | 04-23强熊日(FGI暴跌至15) |
| **PTSD系数** | 0.5x (30天有效) |
| **影响** | 所有仓位自动减半 |
| **解除条件** | 30天无新创伤 或 5次连续盈利交易 |

### CIRCUIT-003: 连续亏损熔断

| 连续亏损次数 | 响应 |
|:---|:---|
| 3次 | 减仓50% + 仅限SKIP/WATCH |
| 5次 | 全部平仓 + 暂停24h |
| 7次 | 暂停72h + A8全面复盘 |

---

## 7. 预案执行检查清单

| # | 预案 | 触发条件 | 执行状态 |
|:---|:---|:---|:---|
| 1 | BS-001 美伊突变 | 谈判破裂/军事冲突 | ⏳ 等待(今日) |
| 2 | BS-002 FOMC鹰派 | 加息/推迟降息 | ⏳ 等待(明日) |
| 3 | BS-003 FOMC鸽派 | 降息信号 | ⏳ 等待(明日) |
| 4 | EXT-001 急涨急跌 | 1H>5% | ⏳ 监控中 |
| 5 | EXT-002 假突破 | 突破后4h收回 | ⏳ 监控中 |
| 6 | POS-001 破位 | 跌破$76,500 | ⏳ 测试中 |
| 7 | POS-002 ETH降杠杆 | 当前5x违规 | 🔴 **需立即执行** |
| 8 | POS-003 algo重建 | algo-pending为空 | 🔴 **需立即执行** |

---

**预案生成**: 2026-04-28 02:30 CST
**版本**: A3 v3.0 应急预案
**关联**: a3_strategy_20260428_0230.md
**总预案数**: 14个 (3黑天鹅 + 3极端 + 3事件 + 3持仓 + 2熔断)
**紧急待办**: POS-002(ETH降杠杆) + POS-003(algo重建)
