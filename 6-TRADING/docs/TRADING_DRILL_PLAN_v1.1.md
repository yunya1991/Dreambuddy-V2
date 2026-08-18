# 6-TRADING 邮箱闭环演练规划 v1.1

> **定位**: 以 `6-TRADING` 邮箱为中心的完整交易系统演练
> **账户**: OKX Demo (A5 Profile)
> **范围**: 不涉及前端，纯邮箱+OKX CLI闭环
> **创建**: 2026-05-16
> **更新**: 2026-05-16 v1.1 (修正执行流程：第二屏完成即触发执行，第三屏为调控角色)
> **目标**: 可重复使用的内部训练规范

---

## 核心流程修正 (v1.0 → v1.1)

**v1.0 错误理解**: 第一屏 → 第二屏 → 第三屏(信号) → 第四屏(扫描器执行)
**v1.1 正确流程**:

```
第一屏(方向) → 第二屏(预设) → 扫描器立即执行挂单 → 第三屏(信号调控)
                                  ↑                        ↑
                              初始执行                   持续调控
```

| 层级 | 角色 | 触发条件 |
|------|------|----------|
| **第二屏完成** | **执行者** — 扫描器读取预设→OKX CLI下单 | 预设文件写入邮箱即触发 |
| **第三屏信号** | **调控者** — A4/A5/A6/A9调整仓位/止盈止损/紧急离场 | 信号到达邮箱即触发 |

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    演练输入（临时任务）                        │
│          "对BTC-USDT-SWAP做一次完整演练"                     │
└─────────────────────────────────────────────────────────────────┘
         │
    ┌────▼──────────────────────────────────────────────────────┐
    │ Phase 1: 第一屏 (Screen1) — 方向确定                     │
    │ → 写入 screen1/screen1_YYYYMMDD.md                       │
    └────┬──────────────────────────────────────────────────────┘
         │
    ┌────▼──────────────────────────────────────────────────────┐
    │ Phase 2: 第二屏 (Screen2) — 日线订单预设                 │
    │ → 写入 screen2/screen2_YYYYMMDD.md                       │
    │ → 包含: 入场价/加仓阶梯/止盈分批/止损                    │
    └────┬──────────────────────────────────────────────────────┘
         │
    ┌────▼──────────────────────────────────────────────────────┐
    │ Phase 3: 扫描器执行 — 读取预设 → OKX Demo下单           │
    │ → 解析 screen2 预设 → 调用 OKX CLI (--profile A5)        │
    │ → 更新 orders/active_orders.json                          │
    │ → 写入 execution_log/exec_YYYYMMDD_HHMM.json             │
    └────┬──────────────────────────────────────────────────────┘
         │
    ┌────▼──────────────────────────────────────────────────────┐
    │ Phase 4: 第三屏信号 — 持续调控                           │
    │ A4 验证: 验证持仓合理性                                   │
    │ A5 决策: 是否加仓/减仓                                   │
    │ A6 监控: 市场状态变化警报                                 │
    │ A9 离场: 紧急止盈止损/风险事件                           │
    │ → 写入 signals/{skill}_signal_YYYYMMDD_HHMM.md           │
    │ → 扫描器读取信号 → 执行调控操作                           │
    └───────────────────────────────────────────────────────────┘
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

### Step 4: 生成四大预设
基于 v3.1 最优参数:

**入场决策矩阵**:
| 信号强度 | 方向 | 仓位% | 入场方式 |
|----------|------|--------|----------|
| 强信号>=70 | 跟随周线 | 100%基础 | 市价单 |
| 中信号50-69 | 跟随周线 | 60%基础 | 限价分批 |
| 弱信号<50 | 默认多头 | 30%基础 | 限价试探 |

**马丁加仓阶梯**（最多3次）:
- Level 1: 入场价 x (1 - 波动率 x k)
- Level 2: Level1价 x (1 - 波动率 x k)
- Level 3: Level2价 x (1 - 波动率 x k)
- k = level_spacing_k (从优化报告读取，默认0.58)

**止损**（硬性约束）:
- 止损价 = 入场价 x 0.80 (亏损20%)
- 无条件执行

**止盈**（分批止盈）:
- TP1: 入场价 x (1 + ATR x tp_level_1)
- TP2: 入场价 x (1 + ATR x tp_level_2)
- TP3: 入场价 x (1 + ATR x tp_level_3) + 移动止盈

### Step 5: 投递到6-TRADING邮箱
写入文件: ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/screen2/screen2_YYYYMMDD.md

文件格式:
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

## Phase 3：扫描器执行挂单（核心执行阶段）

**触发**: Phase 2 预设文件写入邮箱后立即触发

**扫描器职责**:
1. 扫描 `screen2/` 目录 → 找到最新未执行的预设文件
2. 解析预设中的入场价/加仓阶梯/止盈/止损参数
3. 调用 OKX CLI (`--profile A5` demo账户) 执行挂单
4. 更新 `orders/active_orders.json`
5. 写执行日志到 `execution_log/`

**执行流程**:
```
扫描器执行逻辑:

1. 扫描 screen2/ → 找最新 screen2_YYYYMMDD.md
2. 解析 frontmatter:
   - status == "completed" 且未在 active_orders 中标记为 executed
3. 解析预设内容:
   - entry_price, direction, position_size
   - addon_levels[0/1/2], tp_levels[0/1/2], sl_price
4. 读取 screen1/ 确认方向一致
5. 如果数据完整且有效:
   a. 调用 OKX CLI (A5 profile):
      - 设置杠杆:
        okx account set-leverage --profile A5 --instId BTC-USDT-SWAP \
          --lever 5 --mgnMode isolated --posSide long
      - 入场单:
        okx swap order --profile A5 --instId BTC-USDT-SWAP \
          --side buy --posSide long --ordType limit --px <entry_price> --sz <size>
      - 加仓单 x3 (addon_levels):
        okx swap order --profile A5 --instId BTC-USDT-SWAP \
          --side buy --posSide long --ordType limit --px <addon_price> --sz <size>
      - 止盈单 x3 (tp_levels, reduce-only):
        okx swap order --profile A5 --instId BTC-USDT-SWAP \
          --side sell --posSide long --ordType limit --px <tp_price> --sz <tp_size> --reduceOnly
      - 止损单 (reduce-only):
        okx swap order --profile A5 --instId BTC-USDT-SWAP \
          --side sell --posSide long --ordType limit --px <sl_price> --sz <total_size> --reduceOnly
   b. 更新 active_orders.json:
      - 标记预设为 executed: true
      - 记录所有挂单的 orderId
      - 更新 total_position_pct
   c. 写执行日志:
      execution_log/exec_YYYYMMDD_HHMM.json
6. 如果数据不完整:
   - 记录缺失字段到执行日志
   - 不执行，等待下次扫描
```

**active_orders.json 格式**:
```json
{
  "status": "active",
  "last_updated": "YYYY-MM-DDTHH:MM:SS",
  "drill_id": "DRILL-YYYYMMDD-001",
  "screen1_direction": "LONG",
  "screen1_date": "YYYY-MM-DD",
  "screen2_presets": {
    "entry_price": null,
    "addon_levels": [],
    "tp_levels": [],
    "sl_price": null,
    "executed": false
  },
  "active_positions": [],
  "pending_orders": [],
  "total_position_pct": 0
}
```

---

## Phase 4：第三屏信号调控（持续运行）

**定位**: 挂单后的持续监控与调整，不是执行前置条件

**触发方式**:
- 自动化任务自然触发（A4/A5/A6/A9）
- 或手动发送临时任务触发

**信号与调控动作映射**:

| 信号来源 | 触发条件 | 调控动作 |
|----------|----------|----------|
| **A4 验证** | 入场后首次运行 | 验证持仓合理性，如不合理建议减仓 |
| **A5 决策** | 日线信号变化 | 加仓/减仓/调止盈止损 |
| **A6 监控** | 异常市场事件 | 调整仓位/收紧止损 |
| **A9 离场** | 风险事件/L2反转/L1止盈止损 | 紧急平仓/移动止盈 |

**提示词模板（手动触发）**:
```
请触发第三屏信号（Phase 4）:
1. 读取 dream-tactical-validator SKILL → 执行 A4 验证（验证持仓合理性）
2. 读取 dream-tactical-executor SKILL → 执行 A5 决策（是否加仓/调仓）
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
## 建议操作: EXECUTE/SKIP/HOLD
## 调控动作: 加仓/减仓/调止盈/紧急离场
```

**扫描器调控逻辑**（Phase 4 对应的扫描器增强）:
```
信号调控执行逻辑:

1. 扫描 signals/ → 找新信号报告（未处理的）
2. 解析建议操作:
   - EXECUTE + 加仓 → 调用 OKX CLI 补单
   - EXECUTE + 减仓 → 调用 OKX CLI 平仓（部分）
   - HOLD → 不操作，记录日志
   - SKIP → 记录原因
   - EXECUTE + 紧急离场 → 调用 OKX CLI 全部平仓
   - EXECUTE + 调止盈 → 撤单重挂止盈单
   - EXECUTE + 调止损 → 撤单重挂止损单
3. 更新 active_orders.json
4. 写 execution_log
5. 标记信号为 processed
```

---

## 完整演练提示词（一次性触发）

```
请执行一次完整的6-TRADING邮箱闭环演练（Demo账户）:

## Phase 1: 第一屏方向
[插入Phase 1提示词模板]

## Phase 2: 第二屏预设
[插入Phase 2提示词模板]

## Phase 3: 扫描器执行
运行: python3 /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING/scripts/mailbox_scanner.py --execute
检查 screen2/ 目录是否有新预设
如果有未执行预设，调用OKX CLI (--profile A5) 挂单:
  - 入场单 + 3个加仓单 + 3个止盈单 + 1个止损单
更新 orders/active_orders.json

## Phase 4: 第三屏信号调控
[插入Phase 4提示词模板]
等待信号到达 → 扫描器执行调控
```

---

## 训练归档体系

> **定位**: 演练产物（非真实环境），与6-TRADING邮箱真实产物隔离
> **路径**: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING/training/`
> **规则**: 自动化任务继续走秘书邮箱→产物中台归档；演练产物仅存于此

### 目录结构

```
/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING/training/
├── plans/                         # 演练规划文档
│   └── TRADING_DRILL_PLAN_v1.1.md
├── drills/                        # 每次演练的完整产物
│   └── DRILL-YYYYMMDD-001/        # 按演练编号归档
│       ├── plan_ref.md            # 使用的规划版本引用
│       ├── phase1_screen1.md      # 第一屏产物
│       ├── phase2_screen2.md      # 第二屏产物
│       ├── phase3_exec_log.json   # 执行日志
│       ├── phase4_signals/        # 第三屏信号
│       └── active_orders.json     # 订单状态快照
└── reviews/                       # 四份复盘报告
    └── REVIEW-YYYYMMDD-001/
        ├── 01_backtest_review.md      # 回测验证复盘
        ├── 02_bayesian_review.md     # 贝叶斯参数优化复盘
        ├── 03_theory_practice.md     # 理论与实践结合(A8)复盘
        └── 04_dream_review.md        # 做梦部复盘
```

### 归档规范

每次演练结束后，将以下文件**复制**到对应的 `drills/DRILL-YYYYMMDD-NNN/`:
1. `screen1/screen1_YYYYMMDD.md` → `drills/DRILL-.../phase1_screen1.md`
2. `screen2/screen2_YYYYMMDD.md` → `drills/DRILL-.../phase2_screen2.md`
3. `execution_log/exec_*.json` → `drills/DRILL-.../phase3_exec_log.json`
4. `signals/*.md` → `drills/DRILL-.../phase4_signals/`
5. `orders/active_orders.json` → `drills/DRILL-.../active_orders.json`

---

## 自动复盘体系（演练完成后自动触发）

> **触发时机**: 演练Phase 4（信号调控）结束或手动结束演练时
> **触发方式**: 自动发送临时任务，依次调用4个SKILL生成独立复盘报告
> **输出位置**: `training/reviews/REVIEW-YYYYMMDD-NNN/`

### 复盘提示词模板（一次性触发4份报告）

```
演练 DRILL-YYYYMMDD-NNN 已结束，请依次执行以下4份复盘报告。
所有报告写入: /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING/training/reviews/REVIEW-YYYYMMDD-NNN/

## 复盘1: 回测验证 (dream-backtest SKILL)
读取: dream-backtest SKILL (6-TRADING/skills/dream-backtest/SKILL.md)
基于演练产物（drills/DRILL-YYYYMMDD-NNN/），执行回测验证:
1. 用演练的入场/加仓/止盈止损参数，在历史数据上回测
2. 对比演练实际结果 vs 回测预期结果
3. 评估参数在历史数据中的表现
4. 输出: reviews/REVIEW-YYYYMMDD-NNN/01_backtest_review.md

## 复盘2: 贝叶斯参数优化 (dream-bayesian-opt SKILL)
读取: dream-bayesian-opt SKILL (6-TRADING/skills/dream-bayesian-opt/SKILL.md)
基于演练数据和回测结果，执行参数优化:
1. 以演练参数为基线，运行贝叶斯寻优
2. 对比优化参数 vs 演练参数
3. 给出参数调整建议（ADOPT/ADJUST/REJECT）
4. 输出: reviews/REVIEW-YYYYMMDD-NNN/02_bayesian_review.md

## 复盘3: 理论与实践结合 (A8 SKILL)
读取: A8-theory-practice-verification SKILL (用户级SKILL)
检查本轮演练的理论与实践结合情况:
1. 检查三屏分析（A1矛盾论/A2第一性原理/A3沙盘推演）是否被实际执行
2. 检查v3.1最优参数是否被正确应用
3. 检查止损止盈是否按规范执行
4. 识别理论与实践的偏差，敦促系统进化
5. 输出: reviews/REVIEW-YYYYMMDD-NNN/03_theory_practice.md

## 复盘4: 做梦部复盘 (dream-oneirology SKILL)
读取: dream-oneirology SKILL (用户级SKILL)
分析交易系统的"梦境"——被压制的判断和矛盾:
1. 分析本轮演练中是否有被忽视的风险信号
2. 检查是否存在强迫性重复（反复犯同类错误）
3. 矛盾图谱分析（方向判断与实际走势的矛盾）
4. 反事实推演（如果当时反向操作会怎样）
5. 输出: reviews/REVIEW-YYYYMMDD-NNN/04_dream_review.md
```

### 四份复盘报告定位

| # | 报告 | SKILL | 路径 | 核心问题 |
|---|------|-------|------|----------|
| 1 | 回测验证 | dream-backtest | `01_backtest_review.md` | 演练参数在历史数据上表现如何？ |
| 2 | 参数优化 | dream-bayesian-opt | `02_bayesian_review.md` | 参数能否优化？给出ADOPT/ADJUST/REJECT |
| 3 | 理论实践 | A8-theory-practice-verification | `03_theory_practice.md` | 理论设计是否被忠实执行？偏差在哪？ |
| 4 | 做梦部 | dream-oneirology | `04_dream_review.md` | 有什么被忽视的风险和矛盾？ |

### 复盘报告通用frontmatter

```yaml
---
title: "{报告类型}复盘 DRILL-YYYYMMDD-NNN"
review_type: backtest|bayesian|theory_practice|dream
drill_id: "DRILL-YYYYMMDD-NNN"
date: "YYYY-MM-DDTHH:MM:SS+08:00"
plan_version: "v1.1"
inst_id: "BTC-USDT-SWAP"
account: "OKX Demo (A5)"
---
```

### 复盘自动化触发

在演练结束后，通过以下方式自动触发复盘：
1. **手动触发**: 发送上述复盘提示词模板
2. **演练最后一步**: Phase 4调控结束后，在提示词末尾追加复盘触发指令
3. **后续版本**: 创建独立的"演练+复盘"一次性自动化任务

---

## 后期迭代计划

| 阶段 | 内容 | 目标 |
|------|------|------|
| **当前v1.1** | 邮箱闭环+Demo账户+训练归档 | 验证二屏即执行+三屏调控流程 |
| v1.2 | 增强扫描器执行逻辑 | 自动解析预设→OKX CLI挂单 |
| v1.3 | 接入前端交易面板 | 可视化订单状态+余额 |
| v1.4 | 实盘账户切换 | 从小资金开始实盘 |
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
| 训练规划 | `6-TRADING/training/plans/TRADING_DRILL_PLAN_v1.1.md` |
| 演练归档 | `6-TRADING/training/drills/DRILL-YYYYMMDD-NNN/` |
| 复盘报告 | `6-TRADING/training/reviews/REVIEW-YYYYMMDD-NNN/` (4份) |
| 扫描器脚本 | `.../6-TRADING/scripts/mailbox_scanner.py` |
| OKX CLI配置 | `~/.okx/config.toml` (A5 profile = demo) |
