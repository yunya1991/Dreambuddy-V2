# PROP-20260809 Z2/Z3 实施规划（门禁2 待批）

> **链状态**: D链✅(产出=已批准提案) → Z1✅代码扫描 → Z2✅架构设计 → Z3 本文档 → 待 Gate 2 → E链
> **扫描范围**: self_evolution_engine.py 全文 + walk_forward.py + bayesian_optimize.py + bcrm/engine.py + ab_bridge.py + polling_trader.py + 全仓库参数消费点

---

## 一、Z1 扫描关键发现（含 1 个重大发现）

### 🔴 重大发现：7/8 白名单参数是"影子参数"

全仓库（py/ts/json）grep 证实：`velocity_threshold` / `sentiment_weight` / `force_action_after_n_holds` / `high_uncertainty_threshold` / `volume_ratio_min` 等 7 个白名单参数**无任何引擎消费点**——进化它们只写入 constraints/releases 快照，不影响任何行为。唯一有真实消费链路的是：

```
min_confidence_threshold → config.json[confidence_threshold] → polling_trader._load_evolution_config (L2902) 热重载
                       └→ BCRMEngine.min_confidence_threshold 实例字段（dataclass，可注入）
```

**对 PROP-002 的范围修正**（收紧而非扩大，不超批准范围）：Optuna 只对**有真实消费路径的参数**做数据驱动寻优；影子参数保留默认值并标注 `value_source: "shadow_no_consumer"`。影子参数接线（让它们真正生效）属于独立后续提案，本次不做。

### 其他关键事实

| 事实 | 证据 | 影响 |
|:---|:---|:---|
| `WalkForwardEngine.run(data: List[Dict], train=50, test=10, step=10)` 需要 market bars（含 close/price），不是 decisions | walk_forward.py:327,419 | PROP-001 需从本地 klines 构造 bars |
| **本地 kline 缓存可用**: `scripts/data/klines/BTC_1H.csv`(396KB)+ETH/SOL 等 8 文件（8/8 更新） | ls 确认 | 回测不依赖外网（交易所 API 本被封锁） |
| BCRMEngine 是 `@dataclass`，`min_confidence_threshold: float = 0.25` 为实例字段 | engine.py:53,65 | 参数注入 = 构造两个引擎实例对比 |
| 正确性判定: `default_direction_label` 用 bar.close → next_bar.close 实际涨跌 | walk_forward.py:408,417-423 | predict_fn 契约明确 |
| snapshot 构造先例: momentum/volatility 从 close 序列计算 | bcrm2/walk_forward_backtester.py:1113-1127 | PROP-001 复用该模式 |
| Optuna 框架已就位（objective/trial.suggest_float），但原 `load_klines` 拉交易所（本机被封） | bayesian_optimize.py:26,124 | PROP-002 objective 改用本地 CSV |
| regime 词汇表: BULL/TRENDING_UP/UPTREND \| BEAR/TRENDING_DOWN/DOWNTREND \| SIDEWAYS/RANGE/UNCERTAIN/UNKNOWN | ab_bridge.py:259-290 | PROP-003 映射表键集 |
| regime 读取先例: AB 日志 JSON 含 `market_regime` 字段；`AB_LOG_DIR` 环境变量可覆盖（默认是 macOS 残留路径） | ab_bridge.py:41-44,106 | PROP-003 需 env 覆盖 + 缺失降级 |
| config.json 尚不存在（首次进化时创建） | ls 确认 | 降级路径必须覆盖此情况 |

---

## 二、Z2 架构设计

### 文件变更清单

| 文件 | 操作 | 说明 |
|:---|:---|:---|
| `memory_l4/evolution_backtest.py` | **新增** | PROP-001 核心：本地 klines→bars→双引擎 walk-forward 对比 |
| `memory_l4/evolution_optimize.py` | **新增** | PROP-002 核心：Optuna 方向约束寻优（本地数据 objective） |
| `config/regime_quadrant_map.json` | **新增** | PROP-003：regime→四象限概率调整映射表（人工审定初始值） |
| `memory_l4/self_evolution_engine.py` | 修改 | 3 处接入点（采纳门禁/提案值精化/四象限概率） |
| `memory_l4/test_evolution_upgrade.py` | **新增** | 验收测试（降级/影子标注/regime fallback/概率和断言） |

### 保护范围（绝不动）

- ❌ V9 基线规则、8 参数白名单集合、4 个 config 进化键
- ❌ `_apply_adopted_to_config` / `_emit_constraint_release` 固化链
- ❌ polling_trader 热重载协议、停滞检测触发条件
- ❌ a8/dream/online 三层反思的检测逻辑（只动提案值的产生方式）

---

## 三、Z3 任务拆解（E1 执行清单，按依赖顺序）

### T1: `evolution_backtest.py`（PROP-001 基础设施）
```python
load_local_bars(symbol="BTC", timeframe="1H", max_bars=300) -> List[Dict]
    # 读 scripts/data/klines/{symbol}_{timeframe}.csv → bar dicts (close/open/high/low/volume/ts)
build_snapshot(bar, history) -> Dict
    # momentum/volatility 代理字段（复用 bcrm2 L1113-1127 模式）
walk_forward_validate(param_key, proposed_value, max_bars=300) -> Dict
    # 影子参数 → 单引擎跑一次, affected_engine=False, validated=True（行为不变，诚实记录）
    # 引擎参数 → baseline=BCRMEngine() vs proposed=BCRMEngine(**{field: value})
    #   各自 WalkForwardEngine(predict_fn).run(bars) → 对比 direction_accuracy
    #   采纳条件: proposed_acc >= baseline_acc - 0.02（容忍带）
    # 返回 {validated, method:"walk_forward", baseline:{...}, proposed:{...}, delta:{...}, affected_engine}
```
窗口参数: train=50, test=10, step=20（控成本：~250 infer/引擎，双引擎 ≈ 10-30s）

### T2: `_backtest_and_adopt` 接入（PROP-001）
- 白名单检查保留（第一道门）→ walk_forward_validate（第二道门，AND 关系）
- **降级规则**: bars < 60 或 CSV 缺失 → `{"validated": True, "method": "rule_check", "degraded": true, "reason": "insufficient_bars"}`（保持现行为+诚实标注）
- `backtest_result` 记录完整指标（baseline/proposed/delta）

### T3: `evolution_optimize.py`（PROP-002 基础设施）
```python
optimize_proposal_value(param_key, direction, current_value, n_trials=30, timeout_s=120) -> (value, value_source)
    # 影子参数 → 直接返回 (current_value, "shadow_no_consumer")
    # 无 optuna 包 → (default, "default_fallback")
    # 方向约束搜索空间:
    #   direction="lower" → [current*0.5, current)  | "raise" → (current, min(1.0, current*1.5)] | "around" → ±20%
    # objective = 本地 klines walk-forward 得分（direction_accuracy 主 + avg_confidence 辅）
    #   （max_bars=150, train=30, test=5, step=15 → ~40 infer/trial × 30 trials ≈ 1-2min，仅停滞触发后运行）
    # 超时/异常 → (default, "default_fallback")
```

### T4: 提案值精化接入（PROP-002）
- `run_full_cycle` 三层聚合后、采纳门禁前，新增 `_refine_proposal_values(proposals)`：
  - 方向推断: rationale 含"降低/下调"→lower，"提高/上调"→raise，否则 around
  - 调用 optimize_proposal_value 替换 param_value，附 `value_source` 字段
- 6 个提案生成位点（L218-254 a8 × 3，L318-348 dream × 3）**不改动**（收敛在单一精化入口，最小侵入）

### T5: regime 四象限（PROP-003）
- `config/regime_quadrant_map.json` 初始映射（人工审定）：
  - BULL 系: optimistic +0.08, neutral -0.05, pessimistic -0.05, ignored +0.02（防踏空主升浪）
  - BEAR 系: optimistic -0.05, neutral -0.03, pessimistic +0.08, ignored 0.00（防趋势反转）
  - SIDEWAYS 系: optimistic 0.00, neutral +0.05, pessimistic -0.03, ignored -0.02（维持区间判断）
  - UNKNOWN/缺失: 全 0（等于静态基线）
  - 单象限调整硬上限 ±0.10，概率和归一化断言
- `_get_current_regime()`: 读 AB_LOG_DIR（env 覆盖）最新日志的 market_regime；目录不存在/无日志/日志 >48h → None
- `_run_dream_analysis` 四象限段改用调整后概率，附 `prob_source: "regime"|"static_fallback"`

### T6: 验收测试 `test_evolution_upgrade.py`
1. bars 不足 → 降级 rule_check + degraded:true
2. 影子参数 → affected_engine=False，不跑双引擎
3. 劣化提案（人为构造 proposed 远差于 baseline）→ 被拒绝
4. 无 optuna/影子参数 → value_source 正确标注，流程不中断
5. regime 缺失 → 四象限 = 静态基线值；regime=BULL → optimistic 升高且四值之和=1.0

### T7: 集成验证
- 构造停滞 stats（win_rate=0.35, total_trades=10）强制触发 `run_full_cycle`，端到端跑通三层→精化→门禁→固化

---

## 四、Z4 风险评估

| 风险 | 等级 | 对策 |
|:---|:---|:---|
| 本地 klines 时效性（8/8 缓存） | 低 | walk-forward 只做同期 baseline vs proposed **相对对比**，绝对值无意义也不使用 |
| BCRMEngine.infer 慢 | 中 | 窗口参数收敛 + max_bars 上限 + Optuna timeout 硬切 120s |
| Optuna 未安装 | 低 | import 失败自动降级 default_fallback（与 LLM 降级同模式） |
| AB 日志不存在（本机无运行时数据） | 低 | _get_current_regime 全路径降级静态值 = 现行为 |
| 影子参数发现引发范围争议 | 中 | 已在 §一 明示：本次收紧范围，接线问题另立提案 |

---

## 五、E2/E3 验收门禁

- E2: 独立上下文 delegate_task 代码审查（T1-T7 全部产出）
- E3: 单测全绿 → git 分支 `feat/self-evolution-upgrade-prop-20260809` → commit → PR（gh CLI via api.github.com）

*Z链规划: 云涯Hermes ｜ 2026-08-09 01:50 UTC ｜ 依据: PROP-20260809-self-evolution-three-point-upgrade.md（已批准）*
