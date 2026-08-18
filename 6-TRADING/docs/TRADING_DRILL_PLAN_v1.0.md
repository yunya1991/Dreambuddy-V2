# 6-TRADING 邮箱闭环演练规划 v1.0

> **定位**: 以 `6-TRADING` 邮箱为中心的完整交易系统演练
> **账户**: OKX Demo (A5 Profile)
> **范围**: 不涉及前端，纯邮箱+OKX CLI闭环
> **创建**: 2026-05-16
> **目标**: 可重复使用的内部训练规范

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    演练输入（临时任务）                      │
│          "对BTC-USDT-SWAP做一次完整演练"                   │
└────────┬──────────────────┬──────────────────┬──────────────┘
         │                  │                  │
    ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
    │Phase 1  │      │Phase 2  │      │Phase 3  │
    │第一屏   │─────▶│第二屏   │─────▶│第三屏   │
    │方向确定  │      │订单预设  │      │信号触发  │
    └────┬────┘      └────┬────┘      └────┬────┘
         │                  │                  │
         ▼                  ▼                  ▼
  ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/
  ├── screen1/screen1_YYYYMMDD.md
  ├── screen2/screen2_YYYYMMDD.md
  ├── signals/{skill}_signal_YYYYMMDD_HHMM.md
  ├── orders/active_orders.json
  └── execution_log/exec_YYYYMMDD_HHMM.json
         │                  │                  │
         └──────────────────┴──────────────────┘
                            │
                     ┌──────▼──────┐
                     │  Phase 4    │
                     │  邮箱扫描器  │
                     │  = 执行者   │
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │  OKX Demo  │
                     │  A5 Profile │
                     └─────────────┘
```

---

## Phase 1：第一屏周度方向（临时任务）

**触发**: 手动发送临时任务给AI

**提示词模板**:
```
请执行第一屏（Screen1）临时任务：BTC-USDT-SWAP 周度方向分析。

## 执行步骤

### Step 1: 数据采集
1. 用 OKX CLI 获取 BTC-USDT-SWAP 周线K线（最近20根）:
   okx market kline --instId BTC-USDT-SWAP --bar 1W --limit 20 --json
2. 计算技术指标:
   - EMA20/EMA50 排列
   - MACD 金叉/死叉状态
   - RSI(14) 数值
   - 20周波动率
3. 调用 Tavily 搜索本周宏观事件

### Step 2: A1-A3 分析流水线
- 读取 dream-contradiction-theory SKILL → A1 矛盾调查（周线级）
- 读取 dream-first-principles SKILL → A2 第一性原理（周线级）
- 读取 dream-tactical-validator SKILL → A3 沙盘推演（周线级）

### Step 3: 方向决策
- 多空不对称判断
- 双轨策略选择: 合约马丁 vs 现货马丁
- 输出置信度评分 (0-100)

### Step 4: 投递到6-TRADING邮箱
写入文件: ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/screen1/screen1_YYYYMMDD.md

文件格式:
```yaml
---
title: "第一屏周度方向 YYYY-MM-DD"
department: trading
chain_phase: screen1
date: "YYYY-MM-DDTHH:MM:SS+08:00"
type: direction_decision
status: completed
confidence: <评分>
inst_id: "BTC-USDT-SWAP"
---
# 第一屏周度方向分析
## 市场状态
## 方向判断
| 项目 | 值 |
|------|-----|
| 方向 | LONG/SHORT |
| 策略类型 | 合约马丁/现货马丁 |
| 仓位上限 | <X>% |
| 周线评分 | <score> |
| 波动率 | <X.X>% |
```
```

---

## Phase 2：第二屏日线订单预设（临时任务）

**触发**: Phase 1 完成后，手动发送临时任务

**提示词模板**:
```
请执行第二屏（Screen2）临时任务：基于第一屏方向，生成BTC-USDT-SWAP日线订单预设。

## 前置条件检查
1. 读取 ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/screen1/
   找到最新的 screen1_YYYYMMDD.md
2. 确认方向、策略类型、仓位上限有效
3. 如果第一屏报告不存在或过期(>7天) → 报错终止

## 执行步骤

### Step 1: 读取优化报告（硬性前置）
读取 ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/optimization/
- backtest_YYYYMMDD.md（回测报告）
- optimization_YYYYMMDD.md（贝叶斯优化报告）
解析推荐参数: tp_level_1/2/3, base_pos_pct, level_spacing_k

### Step 2: 日线数据采集
1. 用 OKX CLI 获取 BTC-USDT-SWAP 日线K线（最近30根）
2. 获取当前价格、20日波动率、ATR(14)

### Step 3: A1-A3 分析流水线（日线级）
- A1 矛盾调查（日线，继承周线方向框架）
- A2 第一性原理（日线阻力方向+关键价位）
- A3 沙盘推演（关键价位预设概率分布）

### Step 4: 生成三大预设
基于 v3.1 最优参数:

**入场决策矩阵**:
| 信号强度 | 方向 | 仓位% | 入场方式 |
|----------|------|--------|----------|
| 强信号≥70 | 跟随周线 | 100%基础 | 市价单 |
| 中信号50-69 | 跟随周线 | 60%基础 | 限价分批 |
| 弱信号<50 | 默认多头 | 30%基础 | 限价试探 |

**马丁加仓阶梯**（最多3次）:
- Level 1: 入场价 × (1 - 波动率×k)
- Level 2: Level1价 × (1 - 波动率×k)
- Level 3: Level2价 × (1 - 波动率×k)
- k = level_spacing_k (从优化报告读取，默认0.58)

**止损**（硬性约束）:
- 止损价 = 入场价 × 0.80 (亏损20%)
- 无条件执行

**止盈**（分批止盈）:
- TP1: 入场价 × (1 + ATR×tp_level_1)
- TP2: 入场价 × (1 + ATR×tp_level_2)
- TP3: 入场价 × (1 + ATR×tp_level_3) + 移动止盈

### Step 5: 投递到6-TRADING邮箱
写入文件: ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/screen2/screen2_YYYYMMDD.md

文件格式:
```yaml
---
title: "第二屏日线订单设置 YYYY-MM-DD"
department: trading
chain_phase: screen2
date: "YYYY-MM-DDTHH:MM:SS+08:00"
type: order_setup
status: completed
confidence: <评分>
inst_id: "BTC-USDT-SWAP"
parent_screen1_date: "YYYY-MM-DDTHH:MM:SS+08:00"
---
# 第二屏日线订单设置
## 基于第一屏方向: LONG/SHORT
## 四大订单预设
### 1. 入场单
### 2. 加仓单（马丁阶梯）
### 3. 止盈单（分批）
### 4. 止损单（硬性20%）
## 实际仓位计算
```
---

## Phase 3：第三屏信号触发（监控SKILL触发）

**触发方式1**: 手动发送临时任务
**触发方式2**: 等待自动化任务自然触发（A4/A5/A6/A9 自动化）

**提示词模板（手动触发）**:
```
请触发第三屏信号（Phase 3）:
1. 读取 dream-tactical-validator SKILL → 执行 A4 验证（验证第二屏预设是否合理）
2. 读取 dream-tactical-executor SKILL → 执行 A5 决策（是否执行入场）
3. 读取 dream-intelligence-monitor SKILL → 执行 A6 监控（市场状态变化）
4. 读取 dream-exit-skill-v2 SKILL → 执行 A9 离场检查（如有持仓）

对每个信号，生成报告并投递到:
~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/signals/{skill}_signal_YYYYMMDD_HHMM.md
```

**信号报告格式**:
```yaml
---
title: "A{signal} {信号描述} YYYY-MM-DD HH:MM"
department: trading
chain_phase: signal
date: "YYYY-MM-DDTHH:MM:SS+08:00"
type: {signal_type}
status: completed
confidence: <评分>
inst_id: "BTC-USDT-SWAP"
by_a_phase: A{signal}
---
# A{signal} 信号报告
## 信号内容
## 置信度
## 建议操作: EXECUTE/SKIP
```

---

## Phase 4：邮箱扫描器作为执行者（核心新增）

**目标**: 让 `scripts/mailbox_scanner.py` 不仅扫描投递，还负责：
1. 解析 signals/ 目录下的 A4/A5/A6/A9 报告
2. 根据信号置信度和内容，决策是否执行OKX下单
3. 执行马丁策略的加仓/止损/止盈操作
4. 更新 `orders/active_orders.json`
5. 写执行日志到 `execution_log/`

**执行流程**:
```
邮箱扫描器 (Phase 4) 执行逻辑:

1. 扫描 signals/ 目录 → 找最新A4/A5/A6/A9报告
2. 解析报告中的建议操作 (EXECUTE/SKIP/HOLD)
3. 如果建议 EXECUTE 且置信度≥60:
   a. 读取 screen2/ 最新预设
   b. 解析入场价、加仓价、止盈价、止损价
   c. 调用 OKX CLI (A5 profile) 执行:
      - 设置杠杆: okx account set-leverage --profile A5 --instId BTC-USDT-SWAP --lever 5 --mgnMode isolated --posSide long
      - 入场单: okx swap order --profile A5 --instId BTC-USDT-SWAP --side buy --posSide long --ordType limit --px <price> --sz <size>
      - 止损单: okx swap order --profile A5 ... (reduce-only)
      - 止盈单: okx swap order --profile A5 ... (reduce-only)
   d. 更新 orders/active_orders.json
   e. 写 execution_log/exec_YYYYMMDD_HHMM.json
4. 如果建议 HOLD (A9检查结果):
   - 不操作，仅更新执行日志
5. 如果建议 SKIP:
   - 记录原因到执行日志
```

**active_orders.json 格式**:
```json
{
  "status": "active",
  "last_updated": "YYYY-MM-DDTHH:MM:SS",
  "screen1_direction": "LONG",
  "screen1_date": "YYYY-MM-DD",
  "screen2_presets": {
    "entry_price": null,
    "addon_levels": [],
    "tp_levels": [],
    "sl_price": null
  },
  "active_positions": [],
  "pending_orders": [],
  "total_position_pct": 0
}
```

---

## 完整演练提示词（一次性触发全部4个Phase）

```
请执行一次完整的6-TRADING邮箱闭环演练（Demo账户）:

## Phase 1: 第一屏方向
[插入Phase 1提示词]

## Phase 2: 第二屏预设
[插入Phase 2提示词]

## Phase 3: 第三屏信号
[插入Phase 3提示词]

## Phase 4: 扫描器执行
运行: python3 /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING/scripts/mailbox_scanner.py --verbose
检查 signals/ 目录是否有新报告
如果有A5 EXECUTE信号，调用OKX CLI (--profile A5) 执行下单
更新 orders/active_orders.json
```

---

## 后期迭代计划

| 阶段 | 内容 | 目标 |
|------|------|------|
| 当前v1.0 | 邮箱闭环+Demo账户 | 验证三屏数据流 |
| v1.1 | 增强扫描器执行逻辑 | 自动解析信号→下单 |
| v1.2 | 接入前端交易面板 | 可视化订单状态 |
| v1.3 | 实盘账户切换 | 从小资金开始实盘 |
| v2.0 | 完整自动化 | 全链路无人值守 |

---

## 关键文件路径

| 文件 | 路径 |
|------|------|
| 邮箱根目录 | `~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/` |
| 第一屏输出 | `.../6-trading/screen1/screen1_YYYYMMDD.md` |
| 第二屏输出 | `.../6-trading/screen2/screen2_YYYYMMDD.md` |
| 信号输出 | `.../6-trading/signals/{skill}_signal_YYYYMMDD_HHMM.md` |
| 订单状态 | `.../6-trading/orders/active_orders.json` |
| 执行日志 | `.../6-trading/execution_log/exec_YYYYMMDD_HHMM.json` |
| 扫描器脚本 | `.../6-TRADING/scripts/mailbox_scanner.py` |
| OKX CLI配置 | `~/.okx/config.toml` (A5 profile = demo) |
