# Phase C: 前瞻参数上线 — 实现规划

> 日期: 2026-08-20
> 状态: **待审批 (Draft)**
> 关联 Spec: [2026-08-19-morph-cycle-dynamic-correction-design.md](../specs/2026-08-19-morph-cycle-dynamic-correction-design.md) §五 Phase C
> 方法论: 严格 TDD（Red → Green → Refactor）
> 回滚铁律: `ALPHA_BLEND_ENABLED = False`（默认）且 `alpha_blend = 0.0` 时字节等价 Phase 0

---

## 一、关键决策（已确认）

| 决策项 | 选择 | 理由 |
|---|---|---|
| Phase B 数据积累与 Phase C 关系 | **并行开发** | Phase C 代码默认 α=0 字节等价，开发不被数据积累阻塞；待 Phase B 数据充足后启用回测门禁 |
| α blend 集成层 | **ParameterMapper 层** | 在 `map_global_parameters()` 内部实现 blend，交易层无感知，符合三层架构 |
| AB 影子对比框架 | **扩展现有 baseline_manager** | 复用 `baseline_manager.py` + `run_baseline_comparison.py`，新增双基线评估能力 |
| 贝叶斯优化 | **新建 phase_c_bayes_opt.py** | 专用文件，参数空间={α, FFT_lr, Hermite_m0, Hermite_m1}，复用 Optuna 框架 |

---

## 二、任务总览

7 个任务，4 个阶段，严格 TDD 流程：

| 阶段 | 任务 | 核心交付 |
|---|---|---|
| **A. α blend 核心** | T_C1-T_C2 | ParameterMapper α blend + 超参开关 |
| **B. WalkForward 回测** | T_C3 | 回测脚本扩展（α=0 vs α>0 对比） |
| **C. 贝叶斯优化** | T_C4 | phase_c_bayes_opt.py（Optuna 参数搜索） |
| **D. AB 双基线 + 上线** | T_C5-T_C7 | baseline_manager 双基线扩展 + 渐进上线 + API |

**依赖关系**:
```
T_C1 (α blend) ──→ T_C2 (开关+无偏不变量) ──→ T_C3 (WalkForward)
                                                        ↓
                                                 T_C4 (贝叶斯优化)
                                                        ↓
                                                 T_C5 (AB 双基线)
                                                        ↓
                                          T_C6 (渐进上线) ──→ T_C7 (API)
```

---

## 三、任务详情

### T_C1: ParameterMapper α blend 增强

**文件**: `bcrm2/parameter_mapper.py`
**TDD**: ✓
**优先级**: P0
**验收 ID**: T_C1

**设计**:
在 `map_global_parameters()` 内部实现 α blend。新增 `forecast_L` 和 `forecast_T` 可选参数，当传入时按 α 权重混合：

```python
def map_global_parameters(
    self,
    L: float,
    T: float,
    C: float,
    stats_row: Dict[str, float] | None = None,
    forecast_L: float | None = None,   # NEW: Phase C 前瞻 L
    forecast_T: float | None = None,   # NEW: Phase C 前瞻 T
    alpha_blend: float = 0.0,          # NEW: Phase C 混合权重 [0,1]
) -> Dict[str, Tuple[float, float]]:
    # α blend
    if forecast_L is not None and alpha_blend > 0.0:
        L = (1.0 - alpha_blend) * L + alpha_blend * forecast_L
    if forecast_T is not None and alpha_blend > 0.0:
        T = (1.0 - alpha_blend) * T + alpha_blend * forecast_T
    # ... 原有逻辑不变
```

**无偏不变量**:
- `alpha_blend=0.0`（默认）→ L/T 不变 → 输出与 Phase 0 完全一致 ✅
- `forecast_L=None` 或 `forecast_T=None` → 不 blend → 输出不变 ✅

**同样增强 `map_sector_weights()`**:
```python
def map_sector_weights(
    self, L, T, C, sector_betas,
    forecast_L=None, forecast_T=None, alpha_blend=0.0,
) -> Dict[str, float]:
    # 同样的 α blend 逻辑
```

**测试用例** (test_phase_c_alpha_blend.py):
- T_C1.1: alpha_blend=0.0 时输出与原版完全一致（字节等价）
- T_C1.2: forecast_L=None 时不 blend（输出不变）
- T_C1.3: alpha_blend=1.0 时 L 完全用 forecast_L
- T_C1.4: alpha_blend=0.5 时 L = 0.5*reactive + 0.5*forecast
- T_C1.5: map_sector_weights 同样支持 α blend
- T_C1.6: alpha_blend 超出 [0,1] 被 clip
- T_C1.7: forecast_L 和 forecast_T 同时 blend

---

### T_C2: 超参开关 + 无偏不变量验证

**文件**: `bcrm2/parameter_mapper.py`（模块级超参）+ `polling_trader.py`（集成）
**TDD**: ✓
**优先级**: P0
**验收 ID**: T_C2

**超参**（parameter_mapper.py 模块级）:
```python
ALPHA_BLEND_ENABLED = False          # Phase C 总开关（默认关闭）
DEFAULT_ALPHA_BLEND = 0.0           # 默认 α 值（0=纯反应式）
ALPHA_BLEND_MAX = 0.5               # α 上限（project_memory 硬约束）
ALPHA_BLEND_STEP = 0.1              # 渐进步长
```

**polling_trader.py 集成**:
在 `_init_shadow_logger()` 之后新增 `_init_alpha_blend()`:
```python
def _init_alpha_blend(self):
    """初始化 α blend 参数（若开关开启）。"""
    from bcrm2.parameter_mapper import ALPHA_BLEND_ENABLED, DEFAULT_ALPHA_BLEND
    self._alpha_blend_enabled = ALPHA_BLEND_ENABLED
    self._alpha_blend = DEFAULT_ALPHA_BLEND if ALPHA_BLEND_ENABLED else 0.0
```

在 `_record_shadow_log` 的 actual_params 中记录当前 α 值。

**无偏不变量验证**:
- `ALPHA_BLEND_ENABLED=False` → `self._alpha_blend=0.0` → 字节等价
- `ALPHA_BLEND_ENABLED=True` 但 `DEFAULT_ALPHA_BLEND=0.0` → 仍字节等价

**测试用例** (test_phase_c_switch.py):
- T_C2.1: ALPHA_BLEND_ENABLED 默认为 False
- T_C2.2: DEFAULT_ALPHA_BLEND 默认为 0.0
- T_C2.3: ALPHA_BLEND_MAX = 0.5（硬约束）
- T_C2.4: _init_alpha_blend 开关关闭时 _alpha_blend=0.0
- T_C2.5: _init_alpha_blend 开关开启时 _alpha_blend=DEFAULT_ALPHA_BLEND
- T_C2.6: α=0.0 时 map_global_parameters 输出与无 forecast 参数完全一致

---

### T_C3: WalkForward 回测扩展（α=0 vs α>0 对比）

**文件**: `bcrm2/scripts/eval_walkforward.py`（扩展）
**TDD**: ✓
**优先级**: P0
**验收 ID**: T_C3

**核心功能**:
扩展 `eval_walkforward.py`，新增 `run_alpha_blend_comparison()`:
```python
def run_alpha_blend_comparison(
    symbol: str = "BTCUSDT",
    n_folds: int = 5,
    alpha_values: List[float] = [0.0, 0.1, 0.2, 0.3, 0.5],
    hist_days: int = 60,
    forecast_days: int = 5,
) -> Dict[str, Any]:
    """对比不同 α 值的 WalkForward 回测结果。

    返回:
        {
            "symbol": "BTCUSDT",
            "n_folds": 5,
            "alpha_results": {
                "0.0": {"sharpe": 1.2, "pnl": 0.15, "max_dd": -0.08, ...},
                "0.1": {"sharpe": 1.35, "pnl": 0.18, ...},
                ...
            },
            "best_alpha": 0.2,
            "improvement_vs_baseline": {
                "sharpe_improvement_pct": 12.5,
                "pnl_improvement_pct": 20.0,
            },
        }
    """
```

**回测逻辑**:
1. 对每个 α 值，跑 WalkForward 5 折回测
2. 每折用 `MorphCyclePredictor.predict()` 获取 forecast_L/forecast_T
3. 用 `ParameterMapper.map_global_parameters(L, T, C, forecast_L=..., alpha_blend=α)` 计算参数
4. 汇总各 α 的 sharpe/pnl/max_dd
5. 找出 best_alpha，计算相对 α=0 基线的改善百分比

**验收标准**（project_memory 硬约束）:
- α>0 的 sharpe/pnl 必须 > α=0（前瞻式优于反应式）
- 改善幅度 ≥ 5% 才允许 promote

**测试用例** (test_phase_c_walkforward.py):
- T_C3.1: run_alpha_blend_comparison 函数存在
- T_C3.2: alpha=0.0 时返回有效回测结果（含 sharpe/pnl）
- T_C3.3: 多个 α 值都返回结果
- T_C3.4: best_alpha 是 sharpe 最高的 α
- T_C3.5: improvement_vs_baseline 结构正确
- T_C3.6: α=0 结果与无 forecast 的回测一致（字节等价验证）

---

### T_C4: 贝叶斯优化（phase_c_bayes_opt.py）

**文件**: 新建 `bcrm2/scripts/phase_c_bayes_opt.py`
**TDD**: ✓
**优先级**: P1
**验收 ID**: T_C4

**参数空间**:
```python
search_space = {
    "alpha_blend": (0.0, 0.5),           # α ∈ [0, 0.5]
    "fft_learning_rate": (0.01, 0.3),    # FFT 权重学习率
    "hermite_m0": (0.0, 2.0),            # Hermite 切线 m0
    "hermite_m1": (0.0, 2.0),            # Hermite 切线 m1
}
```

**目标函数**:
```python
def objective(trial) -> float:
    """Optuna 目标函数：最大化 WalkForward 平均 sharpe。"""
    alpha = trial.suggest_float("alpha_blend", 0.0, 0.5)
    fft_lr = trial.suggest_float("fft_learning_rate", 0.01, 0.3)
    m0 = trial.suggest_float("hermite_m0", 0.0, 2.0)
    m1 = trial.suggest_float("hermite_m1", 0.0, 2.0)

    # 用这些参数跑 WalkForward 回测
    result = run_alpha_blend_comparison(
        alpha_values=[alpha],
        fft_lr=fft_lr, hermite_m0=m0, hermite_m1=m1,
    )
    return result["alpha_results"][str(alpha)]["sharpe"]
```

**核心类**:
```python
class PhaseCBayesianOptimizer:
    def __init__(self, n_trials=50, n_folds=5):
        self.n_trials = n_trials
        self.n_folds = n_folds
        self.study = None

    def optimize(self, symbol="BTCUSDT") -> Dict[str, Any]:
        """运行贝叶斯优化，返回最优参数。"""
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.study = optuna.create_study(direction="maximize")
        self.study.optimize(lambda t: self._objective(t, symbol),
                           n_trials=self.n_trials)
        return {
            "best_params": self.study.best_params,
            "best_value": self.study.best_value,
            "n_trials": self.n_trials,
        }

    def _objective(self, trial, symbol) -> float:
        """目标函数。"""
        ...
```

**验收标准**（project_memory 硬约束）:
- 参数收敛（best_params 稳定）
- best_value > α=0 基线

**测试用例** (test_phase_c_bayes_opt.py):
- T_C4.1: PhaseCBayesianOptimizer 类可实例化
- T_C4.2: optimize 方法存在
- T_C4.3: 参数空间包含 4 个参数
- T_C4.4: 目标函数返回 float
- T_C4.5: mock Optuna 验证 optimize 返回 best_params 结构

---

### T_C5: baseline_manager 双基线扩展

**文件**: `bcrm2/baseline_manager.py`（扩展）
**TDD**: ✓
**优先级**: P1
**验收 ID**: T_C5

**新增方法**:
```python
class BaselineManager:
    # ... 现有代码 ...

    def compare_dual_baseline(
        self,
        new_result: dict,
        static_baseline_version: str = "v15_strategy",  # 静态基线（v15策略）
        dynamic_baseline_version: str = "current_best", # 动态基线（当前最优AI版本）
    ) -> Dict[str, Any]:
        """双基线评估（project_memory 硬约束）。

        静态基线评估 AI 整体有效性；
        动态基线评估新版本是否更优。
        双基线均通过才允许版本晋升。

        返回:
            {
                "static_baseline": ComparisonReport,  # vs v15 策略
                "dynamic_baseline": ComparisonReport, # vs 当前最优
                "both_passed": bool,
                "recommendation": "promote" | "hold" | "reject",
            }
        """
```

**bootstrap 逻辑**（首版本无动态基线时）:
```python
# 无动态基线时通过 bootstrap 逻辑自动晋升
if dynamic_baseline is None:
    # 仅需静态基线通过即可 bootstrap 晋升
    # 晋升后自动设为动态基线
    return {
        "both_passed": static_report.passed,
        "recommendation": "promote" if static_report.passed else "reject",
        "bootstrap": True,
    }
```

**验收标准**（project_memory 硬约束）:
- 首版本：无动态基线 → bootstrap 晋升
- 后续版本：双基线均通过才允许 promote

**测试用例** (test_phase_c_dual_baseline.py):
- T_C5.1: compare_dual_baseline 方法存在
- T_C5.2: 静态基线通过 + 无动态基线 → bootstrap 晋升
- T_C5.3: 静态+动态双基线通过 → promote
- T_C5.4: 静态通过 + 动态不通过 → hold
- T_C5.5: 静态不通过 → reject
- T_C5.6: 返回结构包含 both_passed 和 recommendation

---

### T_C6: 渐进上线管理器

**文件**: 新建 `bcrm2/alpha_blend_scheduler.py`
**TDD**: ✓
**优先级**: P1
**验收 ID**: T_C6

**渐进上线方案**（Spec §5.2）:
```
Week 1: α = 0.0  (纯反应式，基线)
Week 2: α = 0.1  (10% 前瞻)
Week 3: α = 0.2  (20% 前瞻)
...
Week N: α = 0.5  (目标值)
```

**核心类**:
```python
class AlphaBlendScheduler:
    """α blend 渐进上线管理器。"""

    def __init__(self, storage: EvolutionStorageSQLite):
        self.storage = storage
        self._state = self._load_state()

    def get_current_alpha(self) -> float:
        """获取当前应使用的 α 值。"""
        ...

    def advance(self) -> float:
        """推进到下一阶段的 α 值（需门禁通过）。"""
        ...

    def _load_state(self) -> dict:
        """从 storage 加载 α 上线状态。"""
        ...

    def _save_state(self, state: dict) -> None:
        """保存 α 上线状态。"""
        ...
```

**状态存储**（新增表 `alpha_blend_state`）:
```sql
CREATE TABLE IF NOT EXISTS alpha_blend_state (
    symbol      TEXT PRIMARY KEY,
    current_alpha    REAL NOT NULL DEFAULT 0.0,
    target_alpha     REAL NOT NULL DEFAULT 0.5,
    stage            INTEGER NOT NULL DEFAULT 0,   -- 0=基线, 1=0.1, 2=0.2, ...
    started_at       TEXT NOT NULL,
    last_advanced_at TEXT,
    gate_passed      INTEGER NOT NULL DEFAULT 0    -- 0=未通过, 1=已通过
);
```

**门禁检查**:
- 推进前必须通过 WalkForward 回测 + AB 双基线
- 门禁未通过时 `advance()` 抛异常或返回当前 α

**测试用例** (test_phase_c_scheduler.py):
- T_C6.1: AlphaBlendScheduler 类可实例化
- T_C6.2: 初始 α=0.0
- T_C6.3: advance 推进 α 增加 0.1
- T_C6.4: α 上限 0.5，超过不推进
- T_C6.5: 门禁未通过时不推进
- T_C6.6: 状态持久化到 alpha_blend_state 表
- T_C6.7: 重启后从 storage 恢复状态

---

### T_C7: /api/alpha/status API

**文件**: `data_server_fixed.py`（扩展）
**TDD**: ✓
**优先级**: P2
**验收 ID**: T_C7

**端点**:
- `GET /api/alpha/status?symbol=BTC` — 返回当前 α blend 状态
- `POST /api/alpha/advance?symbol=BTC` — 手动推进 α（需门禁通过）

**返回结构**:
```json
{
    "ok": true,
    "symbol": "BTC",
    "current_alpha": 0.2,
    "target_alpha": 0.5,
    "stage": 2,
    "gate_passed": true,
    "enabled": true
}
```

**测试用例** (test_phase_c_api.py):
- T_C7.1: get_alpha_status 函数存在
- T_C7.2: 路由 /api/alpha/status 已注册
- T_C7.3: ALPHA_BLEND_ENABLED=False 时返回 ok=False
- T_C7.4: 开关开启时返回 current_alpha 和 stage
- T_C7.5: /api/alpha/advance 路由已注册

---

## 四、测试文件清单

| 测试文件 | 任务 | 测试数 |
|---|---|---|
| `tests/test_phase_c_alpha_blend.py` | T_C1 | 7 |
| `tests/test_phase_c_switch.py` | T_C2 | 6 |
| `tests/test_phase_c_walkforward.py` | T_C3 | 6 |
| `tests/test_phase_c_bayes_opt.py` | T_C4 | 5 |
| `tests/test_phase_c_dual_baseline.py` | T_C5 | 6 |
| `tests/test_phase_c_scheduler.py` | T_C6 | 7 |
| `tests/test_phase_c_api.py` | T_C7 | 5 |
| **合计** | **7 个任务** | **42** |

---

## 五、硬约束兼容性

| 硬约束 | 兼容性 | 说明 |
|---|---|---|
| CLI 默认字节等价 | ✅ | `ALPHA_BLEND_ENABLED=False` 默认关闭，α=0.0 字节等价 |
| 无偏不变量 | ✅ | α=0.0 时 L/T 不变 → 输出与 Phase 0 完全一致 |
| 三层架构 | ✅ | α blend 在 ParameterMapper（前置层），不修改核心层 |
| WalkForward 回测 | ✅ | T_C3 专门验证 α>0 优于 α=0 |
| 贝叶斯优化 | ✅ | T_C4 优化 α/FFT/Hermite 参数 |
| AB 影子对比双基线 | ✅ | T_C5 实现静态+动态双基线评估 |
| α 上限 0.5 | ✅ | `ALPHA_BLEND_MAX=0.5` 硬约束 |
| 渐进上线 | ✅ | T_C6 实现 α 从 0→0.5 渐进 |

---

## 六、验收标准

| 测试 ID | 内容 | 通过标准 |
|---|---|---|
| T_C1 | ParameterMapper α blend | alpha=0 字节等价；alpha=1 完全用 forecast |
| T_C2 | 超参开关 + 无偏不变量 | 开关默认关闭；α=0 输出与无 forecast 一致 |
| T_C3 | WalkForward 回测 | α>0 的 sharpe/pnl > α=0；改善 ≥5% |
| T_C4 | 贝叶斯优化 | 参数收敛；best_value > α=0 基线 |
| T_C5 | AB 双基线 | 静态+动态双基线通过才 promote；bootstrap 逻辑正确 |
| T_C6 | 渐进上线 | α 从 0→0.5 渐进；门禁未通过不推进；状态持久化 |
| T_C7 | /api/alpha/status API | 路由注册 + 返回 α 状态 |

---

## 七、风险与缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| α blend 引入 look-ahead bias | 高 | WalkForward 严格用 t-1 数据预测 t |
| 贝叶斯优化过拟合 | 中 | 5 折交叉验证 + 参数范围约束 |
| Phase B 数据不足导致评估不可靠 | 中 | 并行开发，代码就绪后等数据 |
| α 推进过快导致交易异常 | 中 | 渐进步长 0.1 + 门禁检查 |
| forecast 参数不稳定 | 中 | forecast 带 1h 缓存 + 5 天预测值平滑 |
