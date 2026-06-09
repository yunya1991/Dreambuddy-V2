---
title: "回测引擎 SKILL v2.0"
summary: "独立回测能力：支持被Screen2调用或3AM自动化独立运行，输出结构化报告到邮箱"
trigger:
  - "回测"
  - "backtest"
  - "回测验证"
  - "参数验证"
  - "历史表现"
  - "运行回测"
  - "执行回测"
---

# 回测引擎 SKILL (dream-backtest)

> **SKILL 定位**: 独立回测模块，同时支持 Screen2 内部调用和 3AM 自动化独立运行
>
> **核心职责**: 运行策略回测，输出统计指标与结构化报告
>
> **调用方式**: (1) 被 dream-screen2-second 内部调用 (2) 3AM 自动化独立运行
>
> **版本**: v2.0 | 最后更新: 2026-05-16

---

## 一、SKILL 概览

### 1.1 架构定位

```
┌──────────────────────────────────────────────────────────┐
│               dream-backtest (本SKILL) v2.0              │
│                                                          │
│  调用方式 A: 3AM 自动化独立运行 (★ v2.0新增)              │
│    → 完整回测 → 输出报告到 optimization/ 邮箱             │
│    → 报告被第二屏 Screen2 读取                            │
│                                                          │
│  调用方式 B: 被 dream-screen2-second 内部调用              │
│    → screen1_mode / screen2_mode                        │
│    → 返回回测指标供融合决策                                │
│                                                          │
│  核心脚本:                                               │
│  • scripts/backtest_engine.py    (回测引擎主程序)          │
│  • scripts/backtest_strategy.py  (三屏策略逻辑)           │
│  • scripts/backtest_data_fetcher.py (数据获取)            │
│  • scripts/backtest_report.py    (HTML报告生成)           │
│                                                          │
│  数据目录:                                               │
│  • data/backtest/*.csv          (K线缓存)                │
│  • reports/*.json               (回测结果)               │
└──────────────────────────────────────────────────────────┘
```

### 1.2 v2.0 核心变更

| 变更项 | v1.0 | v2.0 |
|--------|------|------|
| 调用方式 | 仅被Screen2内部调用 | **独立运行 + Screen2调用** |
| 报告输出 | 内存返回JSON | **写入邮箱 optimization/ 目录** |
| 运行模式 | screen1/screen2/full | 保留 + **standalone (独立模式)** |
| 自动化支持 | 无 | **3AM 自动化任务联动** |

---

## 二、运行模式

### 2.1 Mode: standalone (独立运行，★ v2.0 新增)

```yaml
Mode: standalone

用途:
  3AM 自动化调用，生成完整回测报告投递到邮箱
  第二屏(Screen2)在9AM读取此报告

执行:
  Step 1: 获取最新历史K线数据 (自动检测缓存)
    python3 scripts/backtest_engine.py \
      --inst BTC-USDT-SWAP \
      --capital 200 \
      --output reports/backtest_{date}.json

  Step 2: 解析回测结果
    读取 reports/backtest_{date}.json

  Step 3: 判定回测状态
    通过条件 (全部满足):
      ✓ max_drawdown < 20% (硬性约束)
      ✓ win_rate > 40% (基本要求)
      ✓ profit_factor > 1.5 (正期望)

    警告条件 (任一触发):
      ⚠ max_drawdown > 15% → WARN
      ⚠ win_rate < 50% → WARN

  Step 4: 生成结构化报告并写入邮箱
    路径: ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/optimization/
    文件: backtest_{YYYYMMDD}.md

输出 (Markdown报告):
  ---
  type: backtest
  category: optimization
  date: {YYYY-MM-DDTHH:MM:SS+08:00}
  source: dream-backtest
  version: "2.0"
  backtest_status: PASS|WARN|FAIL
  ---

  # 回测报告 {YYYY-MM-DD}

  ## 回测参数
  - 交易对: BTC-USDT-SWAP
  - 时间范围: {start} ~ {end} ({days}天)
  - 初始资金: $200.00

  ## 性能指标
  | 指标 | 值 | 通过标准 | 判定 |
  |------|-----|---------|------|
  | 总收益率 | X% | > 0 | PASS/FAIL |
  | 最大回撤 | X% | < 20% | PASS/WARN/FAIL |
  | 夏普比率 | X.XX | > 1.0 | PASS/WARN |
  | 胜率 | X% | > 40% | PASS/FAIL |
  | 盈亏比 | X.X | > 1.5 | PASS/WARN |
  | 交易次数 | N | - | INFO |

  ## 信号强度分析
  | 信号 | 次数 | 胜率 |
  |------|------|------|
  | strong | N | X% |
  | medium | N | X% |
  | weak | N | X% |
  | none | N | X% |

  ## 第一屏正确率: X%
  ## 最终权益: $XXX.XX

  ## 结论
  backtest_status: {PASS/WARN/FAIL}
  修正系数: {1.0/0.7} (PASS=1.0, WARN=0.7)
  备注: {分析说明}
```

### 2.2 Mode: screen1_mode (第一屏快速扫描)

```yaml
Mode: screen1_mode

用途:
  为第一屏提供"哪个方向在历史上表现最好"的数据支撑

输入:
  symbol: BTC-USDT-SWAP
  lookback_weeks: 12
  current_price: $XX,XXX

执行:
  Step 1: 获取近12周周线数据
  Step 2: 分别模拟三种方向的持仓收益
  Step 3: 统计各方向的总收益率、最大回撤、波动率、夏普比率

输出 (JSON):
  {
    "mode": "screen1",
    "symbol": "BTC-USDT-SWAP",
    "lookback_weeks": 12,
    "results": {
      "long": {"return_pct": 15.2, "max_dd": 8.3, "sharpe": 1.8},
      "short": {"return_pct": -12.5, "max_dd": 18.1, "sharpe": -0.9},
      "wait": {"return_pct": 0, "opportunity_cost": 15.2}
    },
    "recommendation": "long",
    "confidence": 78
  }
```

### 2.3 Mode: screen2_mode (第二屏完整验证)

```yaml
Mode: screen2_mode

用途:
  验证第二屏输出的预设参数在历史上的表现

输入:
  symbol, strategy_type, direction, params_to_validate, lookback_days

执行:
  Step 1: 获取60个交易日数据
  Step 2: 用当前参数运行完整马丁策略回测
  Step 3: 变体测试 (参数±20%范围)

输出 (JSON):
  {
    "mode": "screen2",
    "status": "PASS",
    "summary": {
      "total_return": 8.5,
      "max_drawdown": 12.3,
      "win_rate": 66.7,
      "profit_factor": 2.1
    },
    "checks": {
      "drawdown_ok": true,
      "win_rate_ok": true,
      "profit_factor_ok": true
    },
    "recommendation": "参数可接受"
  }
```

---

## 三、执行协议

### 3.1 3AM 独立运行协议 (★ v2.0)

```yaml
3AM 自动化调用协议:

  调用者: automation (每日03:00)
  工作目录: /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING

  执行步骤:
    1. cd scripts/
    2. python3 backtest_engine.py \
         --inst BTC-USDT-SWAP \
         --capital 200 \
         --output ../reports/backtest_{date}.json

    3. 读取回测结果 JSON

    4. 判定 backtest_status:
       PASS: max_dd<20% AND win_rate>40% AND profit_factor>1.5
       WARN: max_dd 15-20% OR win_rate 40-50% OR profit_factor 1.2-1.5
       FAIL: max_dd>20% OR win_rate<40% OR profit_factor<1.2

    5. 生成报告并写入邮箱:
       路径: ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/optimization/
       文件: backtest_{YYYYMMDD}.md

  注意事项:
    - 回测引擎需要K线数据，首次运行会自动从OKX获取
    - 日线数据每日自动刷新缓存
    - 如回测失败(数据获取异常)，报告标注 ERROR 并写入邮箱
    - 报告 frontmatter 必须包含 backtest_status 字段供 Screen2 读取
```

### 3.2 数据缓存策略

```yaml
数据缓存:
  缓存目录: data/backtest/
  文件命名: {SYMBOL}_{BAR}_{START}_{END}.csv

  刷新规则:
    - 日线数据: 每日刷新
    - 周线数据: 每周刷新
    - 手动强制: --force 参数

  缓存有效期:
    - 日线: 24小时
    - 周线: 7天
```

---

## 四、输出指标说明

| 指标 | 含义 | 通过标准 | 警告阈值 |
|:------|:------|:---------|:---------|
| **total_return** | 总收益率 | > 0 | < 5% |
| **max_drawdown** | 最大回撤 | **< 20%** (硬性) | ≥ 15% |
| **win_rate** | 胜率 | > 40% | < 50% |
| **profit_factor** | 盈亏比 | > 1.5 | < 1.2 |
| **sharpe_ratio** | 夏普比率 | > 1.0 | < 0.5 |
| **annual_return** | 年化收益率 | > 0 | < 5% |

---

## 五、邮箱报告路径

```yaml
报告存储:
  目录: ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/optimization/
  命名: backtest_{YYYYMMDD}.md
  格式: Markdown + YAML frontmatter

  Frontmatter 必填字段:
    type: backtest
    category: optimization
    date: ISO-8601 北京时间
    source: dream-backtest
    version: "2.0"
    backtest_status: PASS|WARN|FAIL|ERROR
```

---

## 六、依赖关系

| 依赖 | 说明 |
|:------|:------|
| **scripts/backtest_engine.py** | 回测引擎主程序 |
| **scripts/backtest_strategy.py** | 三屏策略逻辑 |
| **scripts/backtest_data_fetcher.py** | K线数据获取 |
| Python 3.12+ | 运行环境 |
| OKX API (TAVILY_KEY) | 数据源 |

---

## 七、版本历史

| 版本 | 日期 | 修改内容 |
|:------|:------|:---------|
| v2.0 | 2026-05-16 | 新增 standalone 独立运行模式；邮箱报告投递；支持3AM自动化联动 |
| v1.0 | 2026-05-16 | 初始版本；封装现有回测脚本为统一SKILL；定义3种调用模式 |

---

**SKILL结束**
