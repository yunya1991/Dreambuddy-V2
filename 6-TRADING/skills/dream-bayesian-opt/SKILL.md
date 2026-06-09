---
title: "贝叶斯参数优化 SKILL v2.0"
summary: "基于贝叶斯推断进行200轮参数寻优，支持独立运行(3AM自动化)或被Screen2调用，输出优化报告到邮箱"
trigger:
  - "贝叶斯"
  - "bayesian"
  - "参数优化"
  - "parameter optimization"
  - "贝叶斯优化"
  - "200轮寻优"
---

# 贝叶斯参数优化 SKILL (dream-bayesian-opt)

> **SKILL 定位**: 独立参数优化模块，同时支持 Screen2 内部调用和 3AM 自动化独立运行
>
> **核心职责**: 200轮贝叶斯寻优，搜索最优策略参数，输出推荐值和置信区间
>
> **调用方式**: (1) 3AM 自动化独立运行 (基于回测报告) (2) 被 dream-screen2-second 内部调用
>
> **版本**: v2.0 | 最后更新: 2026-05-16

---

## 一、SKILL 概览

### 1.1 架构定位

```
┌──────────────────────────────────────────────────────────────┐
│              dream-bayesian-opt (本SKILL) v2.0               │
│                                                              │
│  调用方式 A: 3AM 自动化独立运行 (★ v2.0新增)                  │
│    输入: 读取邮箱中的回测报告 (backtest_{date}.md)            │
│    执行: 200轮贝叶斯寻优                                      │
│    输出: 优化报告写入邮箱 optimization/ 目录                   │
│                                                              │
│  调用方式 B: 被 dream-screen2-second 内部调用                 │
│    输入: 当前参数 + 回测基准线                                │
│    输出: recommended_params + status                          │
│                                                              │
│  优化参数空间 (8维):                                          │
│    θ₁: entry_threshold [50, 80]       # 入场阈值              │
│    θ₂: level_spacing_k  [0.3, 0.8]    # 间隔系数             │
│    θ₃: stop_loss_mult   [1.5, 3.0]    # 止损ATR倍数          │
│    θ₄: tp_level_1       [2.0, 4.0]    # 止盈档1 ATR倍数      │
│    θ₅: tp_level_2       [3.0, 6.0]    # 止盈档2 ATR倍数      │
│    θ₆: tp_level_3       [5.0, 8.0]    # 止盈档3 ATR倍数      │
│    θ₇: weak_pos_pct     [10, 40]      # 弱信号仓位%          │
│    θ₈: strong_pos_pct   [60, 100]     # 强信号仓位%          │
│                                                              │
│  依赖:                                                        │
│    • dream-backtest → 提供似然函数(回测采样)                  │
│    • Python scipy >= 1.15, numpy >= 2.4                     │
│    • 回测报告 (邮箱 optimization/ 目录)                       │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 v2.0 核心变更

| 变更项 | v1.0 | v2.0 |
|--------|------|------|
| 调用方式 | 仅被Screen2内部调用 | **独立运行 + Screen2调用** |
| 寻优轮次 | 20-50轮 | **200轮** |
| 输入源 | 运行时参数 | **读取邮箱回测报告** |
| 报告输出 | 内存返回JSON | **写入邮箱 optimization/ 目录** |
| 自动化支持 | 无 | **3AM 自动化任务联动** |

---

## 二、200轮贝叶斯寻优流程

### 2.1 独立运行流程 (3AM 自动化)

```yaml
贝叶斯优化 200轮寻优流程 (standalone):

  ┌──────────────────────────────────────────────────┐
  │ Step 1: 读取回测报告 (前置条件)                    │
  ├──────────────────────────────────────────────────┤
  │ 路径: ~/.workbuddy/skills/boss-secretary/        │
  │        reports/trading/6-trading/optimization/    │
  │ 文件: backtest_{YYYYMMDD}.md (当日)               │
  │                                                  │
  │ 提取字段:                                        │
  │  • backtest_status: PASS/WARN/FAIL               │
  │  • max_drawdown, win_rate, profit_factor         │
  │  • sharpe_ratio, total_return                    │
  │                                                  │
  │ ⚠️ 如果报告不存在 → 报错终止                      │
  │ ⚠️ 如果 backtest_status == FAIL → 输出REJECT报告  │
  └────────────────────┬─────────────────────────────┘
                       │
                       ▼
  ┌──────────────────────────────────────────────────┐
  │ Step 2: 定义参数空间 + 先验分布                    │
  ├──────────────────────────────────────────────────┤
  │ 8维参数空间 (基于当前策略参数 ±30%):              │
  │                                                  │
  │ θ₁: entry_threshold ~ Uniform(50, 80)            │
  │ θ₂: level_spacing_k  ~ Uniform(0.3, 0.8)         │
  │ θ₃: stop_loss_mult   ~ Uniform(1.5, 3.0)         │
  │ θ₄: tp_level_1       ~ Uniform(2.0, 4.0)         │
  │ θ₅: tp_level_2       ~ Uniform(3.0, 6.0)         │
  │ θ₆: tp_level_3       ~ Uniform(5.0, 8.0)         │
  │ θ₇: weak_pos_pct     ~ Uniform(10, 40)           │
  │ θ₈: strong_pos_pct   ~ Uniform(60, 100)          │
  │                                                  │
  │ 优化目标函数 (可配置):                             │
  │   Option A (默认): 最大化 Sharpe Ratio            │
  │   Option B: 最大化 profit_factor                  │
  │   Option C: 最大化 Calmar (return/max_dd)         │
  │                                                  │
  │ 硬约束: max_drawdown < 20%                        │
  │   → 违反约束的采样点直接标记为不可行               │
  └────────────────────┬─────────────────────────────┘
                       │
                       ▼
  ┌──────────────────────────────────────────────────┐
  │ Step 3: 200轮贝叶斯寻优                           │
  ├──────────────────────────────────────────────────┤
  │ 使用 scipy.optimize.differential_evolution 或     │
  │ scipy.optimize.minimize (L-BFGS-B) 结合贝叶斯    │
  │ 代理模型进行全局搜索。                              │
  │                                                  │
  │ 实现方案:                                        │
  │   import numpy as np                             │
  │   from scipy.optimize import minimize             │
  │   from scipy.stats import norm                    │
  │                                                  │
  │   # 目标函数: 对每组参数运行回测采样               │
  │   def objective(params):                         │
  │       result = run_quick_backtest(params)        │
  │       if result['max_drawdown'] > 20:            │
  │           return 1e6  # 惩罚不可行解               │
  │       return -result['sharpe_ratio']             │
  │                                                  │
  │   # 多起点随机搜索 (200轮)                        │
  │   best_results = []                              │
  │   for i in range(200):                           │
  │       x0 = random_sample_within_bounds()         │
  │       res = minimize(objective, x0,              │
  │                      method='L-BFGS-B',          │
  │                      bounds=bounds)              │
  │       best_results.append(res)                   │
  │                                                  │
  │   # 选最优                                        │
  │   best = min(best_results, key=lambda r: r.fun)  │
  │                                                  │
  │ 统计:                                            │
  │   total_rounds: 200                              │
  │   feasible_rounds: N (max_dd<20%)                 │
  │   infeasible_rounds: M (max_dd>=20%)              │
  │   best_sharpe: X.XX                              │
  │   baseline_sharpe: X.XX (当前参数)               │
  └────────────────────┬─────────────────────────────┘
                       │
                       ▼
  ┌──────────────────────────────────────────────────┐
  │ Step 4: 敏感性分析 + 置信区间                     │
  ├──────────────────────────────────────────────────┤
  │ 对每个参数计算:                                    │
  │   • 影响度: 固定其他参数，变化该参数时的目标函数    │
  │     方差 / 目标函数总方差                          │
  │   • 置信区间: 基于所有可行解的分位数               │
  │                                                  │
  │ sensitivity_ranking:                              │
  │   1. stop_loss_mult → 影响度: 高                  │
  │   2. level_spacing_k → 影响度: 中                 │
  │   3. tp_level_2 → 影响度: 中                      │
  │   4. weak_pos_pct → 影响度: 低                    │
  │   ...                                            │
  └────────────────────┬─────────────────────────────┘
                       │
                       ▼
  ┌──────────────────────────────────────────────────┐
  │ Step 5: 决策 + 生成报告                            │
  ├──────────────────────────────────────────────────┤
  │ 决策逻辑:                                        │
  │   improvement = best_sharpe - baseline_sharpe     │
  │   if improvement > 0.3 AND best_dd < 15:         │
  │       status = ADOPT                             │
  │   elif improvement > 0:                          │
  │       status = ADJUST                            │
  │   else:                                          │
  │       status = REJECT                            │
  │                                                  │
  │ 生成报告并写入邮箱:                               │
  │   路径: optimization/optimization_{YYYYMMDD}.md  │
  └──────────────────────────────────────────────────┘
```

### 2.2 输出报告格式

```yaml
优化报告 (Markdown, 写入邮箱):

  ---
  type: bayesian_optimization
  category: optimization
  date: {YYYY-MM-DDTHH:MM:SS+08:00}
  source: dream-bayesian-opt
  version: "2.0"
  optimization_status: ADOPT|ADJUST|REJECT|ERROR
  backtest_ref: backtest_{YYYYMMDD}.md
  total_rounds: 200
  feasible_rounds: N
  ---

  # 贝叶斯参数优化报告 {YYYY-MM-DD}

  ## 寻优概况
  - 总寻优轮次: 200
  - 可行解: N (max_dd<20%)
  - 不可行解: M (max_dd>=20%)
  - 基准Sharpe: X.XX (当前参数)
  - 最优Sharpe: X.XX (优化后)
  - 预期提升: +X%

  ## 推荐参数变更
  | 参数 | 当前值 | 推荐值 | 变化幅度 | 置信区间(95%) |
  |------|--------|--------|----------|---------------|
  | level_spacing_k | 0.50 | 0.55 | +10% | [0.42, 0.68] |
  | stop_loss_mult | 2.0 | 2.2 | +10% | [1.7, 2.8] |
  | tp_level_1 | 3.0 | 2.8 | -7% | [2.2, 3.5] |
  | tp_level_2 | 4.5 | 5.0 | +11% | [3.8, 6.2] |
  | tp_level_3 | 7.0 | 7.5 | +7% | [5.5, 8.5] |
  | weak_pos_pct | 30 | 25 | -17% | [15, 35] |
  | strong_pos_pct | 100 | 100 | 0% | [80, 100] |

  ## 敏感性排名
  1. stop_loss_mult (高影响) — 对max_drawdown影响最显著
  2. level_spacing_k (中影响) — 影响加仓频率和总仓位
  3. tp_level_2 (中影响) — 影响中等盈利交易的利润锁定
  4. weak_pos_pct (低影响) — 影响弱信号仓位
  5. tp_level_3 (低影响) — 仅在高盈利时触发

  ## 决策
  optimization_status: ADOPT
  建议: 采用推荐参数，预期Sharpe提升X%，最大回撤维持X%以下
  风险评估: 低风险 (所有推荐值在95%CI内)

  ## 回测参考
  基于回测报告: backtest_{YYYYMMDD}.md
  回测状态: PASS
```

---

## 三、被 Screen2 调用模式 (保留)

### 3.1 调用时序

```yaml
在 dream-screen2-second 中的调用位置:

  Phase 3 (回测+贝叶斯优化):
    Step 3a: dream-backtest → backtest_status + metrics
    Step 3b: dream-bayesian-opt ★
      输入: 当前参数 + 回测基准线
      输出: recommended_params + status
    Step 3c: 结果融合

  ★ v2.0变更: Step 3b 优先读取邮箱中的优化报告
    如果 optimization_{date}.md 存在且当日:
      → 直接使用报告中的推荐参数
    如果不存在:
      → 降级为实时计算 (原v1.0逻辑)
```

### 3.2 决策矩阵

```yaml
回测状态 \ 贝叶斯状态 |  ADOPT (采用)    | ADJUST (调整)   | REJECT (拒绝)
---------------------|------------------|-----------------|---------------
PASS (通过)          | 全部采用推荐      | 保守采用中值      | 保持原参数
WARN (警告)          | 部分采用+降仓     | 小幅调整+降仓     | 保持+强警告
FAIL (失败)          | 不采用            | 不采用           | 终止生成预设
```

---

## 四、3AM 独立运行协议 (★ v2.0)

```yaml
3AM 自动化调用协议:

  调用者: automation (每日03:00)
  工作目录: /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING
  前置条件: 回测报告已生成 (由同一自动化任务的回测步骤完成)

  执行步骤:
    1. 读取回测报告
       路径: ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/optimization/backtest_{date}.md
       提取: backtest_status, max_drawdown, win_rate, profit_factor, sharpe_ratio

    2. 如果 backtest_status == FAIL:
       生成 REJECT 报告，注明回测未通过，无需优化

    3. 如果 backtest_status in (PASS, WARN):
       执行200轮贝叶斯寻优:
         a. 定义8维参数空间和边界
         b. 设定优化目标 (默认: Sharpe Ratio)
         c. 运行200轮搜索 (scipy + numpy)
         d. 收集可行解统计
         e. 计算敏感性和置信区间
         f. 做出 ADOPT/ADJUST/REJECT 决策

    4. 生成优化报告并写入邮箱:
       路径: ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/optimization/
       文件: optimization_{YYYYMMDD}.md

  注意事项:
    - 贝叶斯寻优计算量大，预计3-10分钟完成
    - 200轮是固定值，不随回测结果变化
    - 硬约束 max_drawdown < 20% 贯穿始终
    - 如果 scipy/numpy 版本不兼容，报告标注 ERROR
```

---

## 五、邮箱报告路径

```yaml
报告存储:
  目录: ~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/optimization/
  文件:
    backtest_{YYYYMMDD}.md       (回测报告)
    optimization_{YYYYMMDD}.md   (优化报告)
  格式: Markdown + YAML frontmatter

  Frontmatter 必填字段 (优化报告):
    type: bayesian_optimization
    category: optimization
    date: ISO-8601 北京时间
    source: dream-bayesian-opt
    version: "2.0"
    optimization_status: ADOPT|ADJUST|REJECT|ERROR
    backtest_ref: backtest_{YYYYMMDD}.md
    total_rounds: 200
```

---

## 六、依赖关系

| 依赖 | 说明 |
|:------|:------|
| **dream-backtest** | 提供回测采样(似然函数) |
| **scripts/backtest_engine.py** | 回测引擎 |
| **scripts/backtest_strategy.py** | 策略逻辑 |
| Python scipy >= 1.15 | 贝叶斯优化 |
| Python numpy >= 2.4 | 数值计算 |

---

## 七、版本历史

| 版本 | 日期 | 修改内容 |
|:------|:------|:---------|
| v2.0 | 2026-05-16 | 新增200轮独立寻优模式；邮箱报告投递；前置回测报告依赖；支持3AM自动化联动 |
| v1.0 | 2026-05-16 | 初始版本；定义参数空间、贝叶斯流程、输出格式、集成协议 |

---

**SKILL结束**
