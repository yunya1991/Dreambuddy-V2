# V15 双基线 AB 影子对比框架技术文档

> 版本: 1.0.0 | 更新日期: 2026-08-19 | 作者: Dreambuddy-V2 DreamOS

## 1. 概述

### 1.1 设计目标

AI/算法进化存在劣化风险。新训练的模型版本可能在回测中表现优异，但在实盘交易中劣于旧版本。为防止迭代劣化，本框架实现双基线评估机制，确保每次模型迭代只能单向变好。

### 1.2 核心原则

- **新版本必须优于动态基线才能上线**，劣化版本永远不会进入实盘
- **首版本通过回测即可晋升**（无历史基线可比），后续版本需通过双重评估
- **所有新版本注册为 shadow**，不跳过评估直接上线

## 2. 双基线体系

### 2.1 静态基线（Static Baseline）

| 属性 | 值 |
|---|---|
| 定义 | V15 基线策略（不含 AI 闸门的原始马丁策略） |
| 变更频率 | 永不变 |
| 评估对象 | AI 闸门整体是否有效（Phase D BiLSTM + PatchTST） |
| 数据来源 | AB 对比器 records 中 `baseline_pnl` vs `ai_predicted_pnl` |
| 状态机 | SHADOW → LIVE → SHADOW（AI 闸门是否实盘生效） |

### 2.2 动态基线（Dynamic Baseline）

| 属性 | 值 |
|---|---|
| 定义 | 当前最优 AI 模型版本 |
| 变更频率 | 每次有更优版本上线时更新 |
| 评估对象 | 新训练版本是否优于当前线上版本 |
| 数据来源 | 回测指标快照（PnL、胜率、最大回撤） |
| 存储位置 | `ab_comparator_state.json` 的 `dynamic_baseline_version` / `dynamic_baseline_metrics` |

### 2.3 两条基线的协作关系

```
静态基线 ──── 评估 AI 闸门整体是否值得信任（宏观）
    │
    ↓ 通过（SHADOW→LIVE）
    │
动态基线 ──── 评估新版本是否优于当前线上版本（微观）
    │
    ↓ 通过（should_promote=True）
    │
promote_shadow + hot_swap_models + 更新动态基线
```

## 3. 决策矩阵

### 3.1 完整决策表

| 条件 | 动态基线对比 | AB transition | 执行动作 | 版本状态 | 热切换 |
|---|---|---|---|---|---|
| 首版本 bootstrap | 通过（无基线，auto） | 任意 | `promoted` | shadow→live | ✅ 执行 |
| 新版本劣化 | **不通过** | 任意 | `disabled_inferior` | shadow→disabled | ❌ 不执行 |
| 新版本更优 + AB 通过 | 通过 | `SHADOW→LIVE` | `promoted` | shadow→live | ✅ 执行 |
| 新版本更优 + AB 不够样本 | 通过 | `None` | `keep_collecting` | 保持 shadow | ❌ 不执行 |
| 新版本更优 + AB 否定 | 通过 | `SHADOW→DISABLED` | `disabled` | shadow→disabled | ❌ 不执行 |
| 线上版本退化 | — | `LIVE→SHADOW` | `rollback` | live→shadow | ✅ 切到回滚版本 |

### 3.2 动态基线对比评分规则

`evaluate_version_comparison()` 采用 3 项指标打分：

| 指标 | 比较方向 | 权重 |
|---|---|---|
| 总 PnL (total_pnl) | candidate > baseline → +1 | 1/3 |
| 胜率 (win_rate) | candidate > baseline → +1 | 1/3 |
| 最大回撤 (max_drawdown) | candidate < baseline → +1 | 1/3 |

**晋升判定**：`score >= 2` 且 `pnl_delta_pct >= -2.0%`

- 至少 2/3 项指标优于动态基线
- PnL 劣化幅度不超过 2%（容忍微波动）

### 3.3 首版本 Bootstrap 逻辑

首版本无动态基线可比，AB 对比器也无交易记录（transition=None）。此时：

```
条件: has_dynamic_baseline=False AND version_comparison.should_promote=True
动作: promote_shadow(v1) + hot_swap_models + set_dynamic_baseline(v1)
transition 标记: BOOTSTRAP_FIRST_VERSION
```

首版本回测通过即可晋升，不依赖 AB transition 检查。

## 4. 完整调用链

### 4.1 增量训练主流程

```
auto_retrain_if_needed()
│
├─ Step 1: check_new_trades()
│   trade_history.json 中新增交易数 >= min_new_trades (默认5)?
│   否 → return skipped
│
├─ Step 2: run_retrain_cycle(trigger=THRESHOLD)
│   │
│   ├─ 2.1: collect_recent_data()
│   │   采集近 window_days (默认30天) K线 + 交易历史
│   │
│   ├─ 2.2: _run_training(out_dir, collection)
│   │   SMOTE 过采样 → 数据增强 → BiLSTM + PatchTST 训练
│   │   保存到 data/phase_d_models/v{N}/bilstm.pt + patchtst.pt
│   │
│   ├─ 2.3: register_version(bilstm_path, patchtst_path, ...)
│   │   新版本始终注册为 shadow（不跳过评估）
│   │
│   ├─ 2.4: evaluate_and_promote()  ← 双基线评估核心
│   │   │
│   │   ├─ AB 静态基线评估
│   │   │   comp.evaluate() → transition
│   │   │
│   │   ├─ 动态基线对比
│   │   │   _backtest_model(shadow_paths) → candidate_metrics
│   │   │   comp.evaluate_version_comparison(candidate, dynamic_baseline)
│   │   │   → should_promote, score, pnl_delta_pct
│   │   │
│   │   ├─ 决策分发（见 3.1 决策矩阵）
│   │   │
│   │   └─ 动作执行:
│   │       promote_shadow / disable_shadow / rollback_live
│   │       + _hot_swap_to_live() → gateway.hot_swap_models(strict=True)
│   │       + set_dynamic_baseline(new_version, metrics)
│   │
│   └─ 2.5: 输出日志
│       Version / Action / New status / Version comparison / Hot-swap / Dynamic baseline
│
└─ Step 3: 更新 _last_trade_count
```

### 4.2 热切换流程

```
_hot_swap_to_live()
│
├─ get_live_paths() → (bilstm_path, patchtst_path)
│
├─ 获取运行中 gateway 单例
│   import core.v15_trader as vt
│   gw = vt._get_phase_d_gateway()
│
├─ gw.hot_swap_models(bilstm_path, patchtst_path, strict=True)
│   │
│   ├─ _probe_load_model() 预检
│   │   空模型 load 确认 state_dict 结构匹配
│   │   strict 模式下任一失败 → 整体回滚，不污染缓存
│   │
│   ├─ 原子替换路径
│   │   self.bilstm_model_path = new_path
│   │   self.patchtst_model_path = new_path
│   │
│   └─ _invalidate_model_cache()
│       清除 @lru_cache 缓存，下次推理自动加载新权重
│
└─ 返回 {ok, reason, bilstm_path, patchtst_path}
```

## 5. AB 影子对比器状态机

### 5.1 状态定义

| 状态 | 含义 | AI 闸门行为 |
|---|---|---|
| SHADOW | AI 闸门只记录不干预 | 决策不生效，仅记录 paired decision |
| LIVE | AI 闸门实盘生效 | BiLSTM/PatchTST 闸门真正参与开仓/加仓判断 |
| DISABLED | AI 闸门被禁用 | 不记录不干预 |

### 5.2 状态转移条件

```
SHADOW → LIVE
  条件: paired samples >= 20
        AND t-test p-value < 0.05
        AND AI PnL 改善 >= 2%
        AND bootstrap CI 下界 > 0

SHADOW → DISABLED
  条件: paired samples >= 20
        AND t-test p-value < 0.05
        AND AI PnL 劣化 >= 1%

LIVE → SHADOW (auto-rollback)
  条件: 7天窗口内 paired samples >= 20
        AND t-test p-value < 0.10
        AND AI PnL 劣化 >= 1%
```

### 5.3 PnL 回填机制

决策时 `baseline_pnl` 和 `ai_predicted_pnl` 均为占位 0。平仓时通过 `backfill_trade_result` 回填真实收益：

```
v15_trader._save_trade_to_history(平仓)
  → comp.backfill_trade_result(symbol, entry_timestamp, baseline_pnl_usdt, ...)
      │
      ├─ 匹配策略（3级回退）:
      │   1. position_ref 精确匹配 (symbol|entry_time_floor_1min)
      │   2. symbol + timestamp 模糊匹配 (±5分钟)
      │   3. symbol + 空 position_ref 兜底
      │
      ├─ 估算 AI 路径 PnL:
      │   ba=OPEN, aa=SKIP → ai_pnl = 0 (AI 否决了开仓)
      │   ba==aa           → ai_pnl = baseline_pnl (同动作同盈亏)
      │   aa=ADDON         → ai_pnl = baseline_pnl * (1 + addon_delta_ratio)
      │
      └─ 更新 record: baseline_pnl + ai_predicted_pnl + pnl_backfilled=True
```

## 6. 版本迭代示例

### 6.1 正常迭代（持续进化）

```
v1 训练 → shadow → 回测通过 → BOOTSTRAP晋升 → live + 动态基线=v1
v2 训练 → shadow → 回测 vs v1: PnL+50%, 胜率+10%, MDD-20% → score=3
         AB: 30笔配对样本, p=0.02, gain=3% → SHADOW→LIVE
         → promoted + hot_swap(v2) + 动态基线=v2
v3 训练 → shadow → 回测 vs v2: PnL+15%, 胜率+5%, MDD-10% → score=3
         AB: 30笔配对样本, p=0.04, gain=2.5% → SHADOW→LIVE
         → promoted + hot_swap(v3) + 动态基线=v3
```

### 6.2 劣化版本被拒

```
v2(live) → v3 训练 → shadow → 回测 vs v2: PnL-30%, 胜率-15%, MDD+50% → score=0
         → disabled_inferior (v3 不上线, v2 继续服务)
v4 训练 → shadow → 回测 vs v2(动态基线仍为v2): PnL+20%, 胜率+8%, MDD-5% → score=3
         AB: SHADOW→LIVE
         → promoted + hot_swap(v4) + 动态基线=v4
```

### 6.3 线上版本退化回滚

```
v4(live) → AB 7天窗口: AI PnL 劣化 2%, p=0.08 → LIVE→SHADOW
         → rollback_live → v2(最近 promoted_at) 恢复为 live
         → hot_swap(v2) → gateway 切回 v2 权重
         → 动态基线保持 v2（回滚不更新动态基线）
```

## 7. 配置参数

### 7.1 AB 对比器参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| MIN_SAMPLES_FOR_TEST | 20 | 触发 t 检验的最小配对样本数 |
| SHADOW_TO_LIVE_PVALUE | 0.05 | SHADOW→LIVE 的 p 值阈值 |
| SHADOW_TO_LIVE_MIN_GAIN | 0.02 | SHADOW→LIVE 的最小 PnL 改善（2%） |
| LIVE_TO_SHADOW_PVALUE | 0.10 | LIVE→SHADOW 的 p 值阈值（更宽松） |
| LIVE_TO_SHADOW_MAX_LOSS | -0.01 | LIVE→SHADOW 的最大 PnL 劣化（-1%） |
| EVALUATION_WINDOW_DAYS | 30 | SHADOW 模式评估窗口 |
| LIVE_EVALUATION_WINDOW_DAYS | 7 | LIVE 模式评估窗口 |

### 7.2 动态基线对比参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| 最小晋升 score | 2 | 3 项指标中至少 2 项优于动态基线 |
| 最大 PnL 劣化容忍 | -2.0% | PnL 劣化不超过 2% 仍可晋升 |

### 7.3 增量训练参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| window_days | 30 | 滚动窗口天数 |
| min_new_trades | 5 | 触发重训的最小新交易数 |
| max_versions | 10 | 保留最大版本数（超出 archive） |

## 8. 文件清单

| 文件 | 职责 |
|---|---|
| `ab_shadow_comparator.py` | AB 影子对比器：决策记录、PnL 回填、t 检验、状态机、动态基线管理 |
| `incremental_trainer.py` | 增量训练器：数据采集、滚动窗口、模型重训、版本注册、双基线评估、热切换 |
| `lib/phase_d_gateway.py` | Phase D 闸门：BiLSTM/PatchTST 推理、should_skip_open_with_baseline、hot_swap_models |
| `core/v15_trader.py` | 交易主循环：信号→Phase D 闸门→风控→开仓→平仓→PnL 回填 |
| `data/ab_comparator_state.json` | AB 对比器持久化状态（records、state、dynamic_baseline） |
| `data/incremental_trainer_state.json` | 增量训练器状态（versions、current_live/shadow、retrain 历史） |
| `tests/test_ab_comparator.py` | AB 对比器单测（12 用例） |
| `tests/test_incremental_trainer.py` | 增量训练器单测（11 用例） |

## 9. 单测覆盖

### 9.1 AB 对比器（test_ab_comparator.py）

| 用例 | 覆盖点 |
|---|---|
| T1 | DecisionRecord 字段完整性 |
| T2 | position_ref 分钟级截断稳定性 |
| T3 | 精确 t-CDF 数值正确性 |
| T4 | PnL 回填 3 级匹配 |
| T5 | AI 路径 PnL 估算 5 场景 |
| T6 | 状态机 SHADOW→LIVE→SHADOW 闭环 |
| T7 | 损坏 JSON 恢复 |
| T8 | 动态基线设置 + generate_report |
| T9 | 版本对比：新版本优于动态基线 → should_promote=True |
| T10 | 版本对比：新版本劣于动态基线 → should_promote=False |
| T11 | 版本对比：无动态基线（首次）→ 自动通过 |
| T12 | 版本对比：2/3 优于基线 + PnL 微差 → 通过 |

### 9.2 增量训练器（test_incremental_trainer.py）

| 用例 | 覆盖点 |
|---|---|
| T1 | register_version 首版本 shadow（不再直接 live） |
| T2 | promote_shadow 旧 live 降级 |
| T3 | rollback_live 候选筛选 |
| T4 | disable_shadow / max_versions archive |
| T5 | check_new_trades 4 场景 |
| T6 | auto_retrain_if_needed 阈值 |
| T7 | evaluate_and_promote 三种转移 |
| T8 | hot_swap_models strict 成功/失败/跳过 |
| T9 | 首版本 bootstrap 全链路（shadow→promoted→live+动态基线初始化） |
| T10 | 劣版本拒绝（v2 劣于 v1 → disabled_inferior，v1 继续服务） |
| T11 | 优版本评估（v2 优于 v1 → score=3/3 + should_promote=True） |

## 10. 监控指标

运行 `generate_report()` 可获取：

```json
{
  "current_state": "SHADOW",
  "total_records": 10,
  "total_evaluations": 0,
  "dynamic_baseline_version": null,
  "dynamic_baseline_metrics": null,
  "evaluation": {
    "n_paired": 0,
    "transition": null,
    "t_test": {"p_value": null, "significant": false}
  },
  "baseline_action_distribution": {"OPEN": 5, "ADDON": 5},
  "ai_action_distribution": {"OPEN": 5, "ADDON": 5},
  "ai_model_stats": {"p_bust_mean": 0.12, "drawdown_mean": 0.03}
}
```

关键监控点：
- `current_state`：AI 闸门当前状态（SHADOW/LIVE/DISABLED）
- `dynamic_baseline_version`：当前动态基线版本
- `evaluation.transition`：最近评估的状态转移
- `version_comparison.score`：新版本 vs 动态基线的得分
- `hot_swap_result.ok`：热切换是否成功
