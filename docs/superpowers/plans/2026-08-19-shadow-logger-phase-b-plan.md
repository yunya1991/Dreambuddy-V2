# Phase B: ShadowLogger 影子模式 — 实现规划

> 日期: 2026-08-19
> 状态: **待审批 (Draft)**
> 关联 Spec: [2026-08-19-morph-cycle-dynamic-correction-design.md](../specs/2026-08-19-morph-cycle-dynamic-correction-design.md) §四 Phase B
> 关联 Spec: [2026-08-18-regime-predictor-design.md](../specs/2026-08-18-regime-predictor-design.md) §10.6 与核心层交互接口
> 方法论: 严格 TDD（Red → Green → Refactor）
> 回滚铁律: `SHADOW_LOGGER_ENABLED = False` 时 polling_trader 行为 100% 等价

---

## 一、任务总览

6 个任务，3 个阶段，严格 TDD 流程：

| 阶段 | 任务 | 核心交付 |
|---|---|---|
| **A. 存储与骨架** | T_B1-T_B2 | shadow_param_log 表 + ShadowLogger 类骨架 |
| **B. 核心逻辑** | T_B3-T_B4 | record_polling() 记录 + get_comparison_report() 评估 |
| **C. 集成与API** | T_B5-T_B6 | polling_trader 集成 + /api/shadow/report |

---

## 二、任务详情

### T_B1: shadow_param_log 表 + CRUD（storage.py 扩展）

**文件**: `11-易经推理系统/scripts/memory_l4/bcrm2/storage.py`
**TDD**: ✓
**优先级**: P0
**验收 ID**: T_B1

**表结构**:
```sql
CREATE TABLE IF NOT EXISTS shadow_param_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    timestamp       TEXT NOT NULL,          -- ISO 8601 UTC
    -- reactive 参数（现状用的）
    reactive_L      REAL,
    reactive_T      REAL,
    reactive_C      REAL,
    reactive_regime TEXT,                  -- 8 态名称
    reactive_pos_mult  REAL,
    reactive_tp_mult   REAL,
    reactive_sl_mult   REAL,
    reactive_threshold REAL,
    -- forecast 参数（Phase A 预测的）
    forecast_L      REAL,
    forecast_T      REAL,
    forecast_global_ranges   TEXT,         -- JSON: 6参数 (lo,hi)
    forecast_sector_weights  TEXT,          -- JSON: 5板块权重
    -- 实际交易参数
    actual_direction    TEXT,
    actual_confidence   REAL,
    actual_position_usdt REAL,
    actual_tp_px        REAL,
    actual_sl_px        REAL,
    actual_threshold    REAL
);
CREATE INDEX IF NOT EXISTS idx_shadow_symbol_ts ON shadow_param_log(symbol, timestamp);
```

**CRUD 方法**:
- `save_shadow_log(symbol, record: dict) -> int` — 插入一条记录，返回 id
- `get_shadow_log(symbol, days=7) -> List[dict]` — 查询最近 N 天记录
- `get_shadow_log_count(symbol) -> int` — 记录总数
- `clear_shadow_log(symbol) -> None` — 清除某 symbol 的所有记录

**测试用例** (test_shadow_logger_storage.py):
- T_B1.1: save_shadow_log 方法存在
- T_B1.2: 保存后能查询到记录
- T_B1.3: 查询最近 7 天返回正确数量
- T_B1.4: get_shadow_log_count 返回正确总数
- T_B1.5: clear_shadow_log 清除后查询返回空
- T_B1.6: 字段完整性（reactive/forecast/actual 三组字段都存在）

---

### T_B2: ShadowLogger 类骨架（bcrm2/shadow_logger.py）

**文件**: 新建 `11-易经推理系统/scripts/memory_l4/bcrm2/shadow_logger.py`
**TDD**: ✓
**优先级**: P0
**验收 ID**: T_B2

**类结构**:
```python
class ShadowLogger:
    """Phase B 影子模式：记录 reactive vs forecast 参数差异，不改变交易。

    Spec: 2026-08-19-morph-cycle-dynamic-correction-design.md §四 Phase B
    """

    def __init__(self, storage: EvolutionStorageSQLite,
                 morph_predictor: MorphCyclePredictor,
                 param_mapper: ParameterMapper):
        self.storage = storage
        self.predictor = morph_predictor
        self.mapper = param_mapper
        self._forecast_cache: Dict[str, Tuple[float, dict]] = {}  # symbol → (ts, forecast_result)

    def record_polling(self, symbol: str, inference: dict,
                       actual_params: dict) -> Optional[int]:
        """记录一次轮询的参数对比快照。返回记录 id 或 None。"""
        ...

    def get_comparison_report(self, symbol: str, days: int = 7) -> dict:
        """生成 N 天的参数差异报告。"""
        ...

    def _compute_forecast_params(self, symbol: str, C: float) -> dict:
        """计算 forecast 参数（L_forecast, T_forecast, global_ranges, sector_weights）。"""
        ...
```

**超参** (在 shadow_logger.py 模块级):
```python
SHADOW_LOGGER_ENABLED = False          # 总开关（默认关闭，保持字节等价）
SHADOW_FORECAST_DAYS = 5               # forecast 天数（用预测的第 5 天值）
SHADOW_FORECAST_CACHE_TTL = 3600       # forecast 缓存 TTL（秒），同 symbol 1h 内复用
SHADOW_SECTOR_BETAS_DEFAULT = {        # 默认 identity betas（Phase B 不依赖真实 betas）
    "defi": (1.0, 0.0, 0.5),
    "ai": (1.0, 0.0, 0.5),
    "rwa": (1.0, 0.0, 0.5),
    "meme": (1.0, 0.0, 0.5),
    "l2": (1.0, 0.0, 0.5),
}
```

**测试用例** (test_shadow_logger_class.py):
- T_B2.1: ShadowLogger 类可实例化
- T_B2.2: record_polling 方法存在
- T_B2.3: get_comparison_report 方法存在
- T_B2.4: _compute_forecast_params 方法存在
- T_B2.5: SHADOW_LOGGER_ENABLED 默认为 False

---

### T_B3: record_polling() 记录逻辑

**文件**: `bcrm2/shadow_logger.py`
**TDD**: ✓
**优先级**: P0
**验收 ID**: T_B3

**核心逻辑**:
```python
def record_polling(self, symbol: str, inference: dict,
                   actual_params: dict) -> Optional[int]:
    """记录一次轮询的参数对比快照。

    参数:
        symbol: 币种（如 "BTC"）
        inference: BCRM 2.0 推理结果 dict（含 snapshot, _regime_multipliers 等）
        actual_params: 实际交易参数
            {
                "direction": str, "confidence": float,
                "position_usdt": float, "tp_px": float, "sl_px": float,
                "threshold": float
            }
    返回: 记录 id 或 None（开关关闭时）
    """
    if not SHADOW_LOGGER_ENABLED:
        return None

    # 1. 提取 reactive 参数
    snapshot = inference.get("snapshot", {}) or {}
    reactive_L = float(snapshot.get("level_smooth", 0.0))
    reactive_T = float(snapshot.get("trend_smooth", 0.0))
    reactive_C = float(snapshot.get("consensus", 0.0))
    reactive_regime = inference.get("_regime_pred") or snapshot.get("regime")
    reg_mult = inference.get("_regime_multipliers", {})

    # 2. 计算 forecast 参数（带缓存）
    forecast_params = self._compute_forecast_params(symbol, reactive_C)

    # 3. 组装记录
    record = {
        "reactive_L": reactive_L,
        "reactive_T": reactive_T,
        "reactive_C": reactive_C,
        "reactive_regime": reactive_regime,
        "reactive_pos_mult": reg_mult.get("position_mult", 1.0),
        "reactive_tp_mult": reg_mult.get("tp_mult", 1.0),
        "reactive_sl_mult": reg_mult.get("sl_mult", 1.0),
        "reactive_threshold": reg_mult.get("threshold_mult", 1.0),
        "forecast_L": forecast_params["L"],
        "forecast_T": forecast_params["T"],
        "forecast_global_ranges": forecast_params["global_ranges"],
        "forecast_sector_weights": forecast_params["sector_weights"],
        "actual_direction": actual_params.get("direction"),
        "actual_confidence": actual_params.get("confidence"),
        "actual_position_usdt": actual_params.get("position_usdt"),
        "actual_tp_px": actual_params.get("tp_px"),
        "actual_sl_px": actual_params.get("sl_px"),
        "actual_threshold": actual_params.get("threshold"),
    }

    # 4. 存储
    return self.storage.save_shadow_log(symbol, record)


def _compute_forecast_params(self, symbol: str, C: float) -> dict:
    """计算 forecast 参数（L_forecast, T_forecast, global_ranges, sector_weights）。

    使用 MorphCyclePredictor.predict() 的 forecast 曲线末尾值。
    带 1h 缓存避免每次轮询都重算。
    """
    import time
    cache_key = symbol
    now = time.time()
    cached = self._forecast_cache.get(cache_key)
    if cached and (now - cached[0]) < SHADOW_FORECAST_CACHE_TTL:
        return cached[1]

    # 调用 MorphCyclePredictor 预测
    full_symbol = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
    result = self.predictor.predict(full_symbol, hist_days=60,
                                     forecast_days=SHADOW_FORECAST_DAYS)
    if not result.get("ok"):
        # 预测失败 → 用 reactive 值兜底
        return {"L": 0.0, "T": 0.0, "global_ranges": "{}", "sector_weights": "{}"}

    forecast_series = result.get("series", {}).get("forecast", [])
    if not forecast_series:
        return {"L": 0.0, "T": 0.0, "global_ranges": "{}", "sector_weights": "{}"}

    L_forecast = float(forecast_series[-1])  # 5 天后预测值

    # T_forecast: 从 forecast 曲线的斜率推算（首尾差分）
    if len(forecast_series) >= 2:
        T_forecast = float(forecast_series[-1] - forecast_series[0])
    else:
        T_forecast = 0.0

    # 用 ParameterMapper 计算全局参数范围
    global_ranges = self.mapper.map_global_parameters(L_forecast, T_forecast, C)

    # 用 ParameterMapper 计算板块权重
    sector_weights = self.mapper.map_sector_weights(
        L_forecast, T_forecast, C, SHADOW_SECTOR_BETAS_DEFAULT
    )

    import json
    params = {
        "L": L_forecast,
        "T": T_forecast,
        "global_ranges": json.dumps(
            {k: [round(v[0], 4), round(v[1], 4)] for k, v in global_ranges.items()},
            ensure_ascii=False),
        "sector_weights": json.dumps(
            {k: round(v, 4) for k, v in sector_weights.items()},
            ensure_ascii=False),
    }

    self._forecast_cache[cache_key] = (now, params)
    return params
```

**测试用例** (test_shadow_logger_record.py):
- T_B3.1: 开关关闭时返回 None
- T_B3.2: 开关开启时返回记录 id（int）
- T_B3.3: 记录的 reactive_L 来自 inference.snapshot.level_smooth
- T_B3.4: 记录的 forecast_L 来自 predictor.predict().forecast[-1]
- T_B3.5: forecast 缓存命中（同 symbol 1h 内不重算）
- T_B3.6: 预测失败时用 0.0 兜底
- T_B3.7: actual_params 字段完整写入

---

### T_B4: get_comparison_report() 评估报告

**文件**: `bcrm2/shadow_logger.py`
**TDD**: ✓
**优先级**: P1
**验收 ID**: T_B4

**返回结构**:
```python
def get_comparison_report(self, symbol: str, days: int = 7) -> dict:
    """生成 N 天的参数差异报告。

    返回:
      {
        "symbol": "BTC",
        "days": 7,
        "total_records": 168,           # 总记录数
        "param_diff_stats": {           # 各参数差异统计
          "L": {"mean_diff": 0.12, "std_diff": 0.08, "max_diff": 0.45},
          "T": {"mean_diff": 0.05, ...},
        },
        "would_change_decision": {      # forecast 参数会导致多少次不同决策
          "direction_changes": 3,       # 方向变化次数
          "threshold_changes": 12,      # 阈值变化次数
          "position_changes": 8,        # 仓位变化次数
        },
        "direction_consistency": 0.95,  # 方向预测一致率
        "regime_distribution": {        # reactive regime 分布
          "TREND_UP_STRONG": 45,
          "RANGE_BOUND": 80,
          ...
        },
      }
    """
```

**核心计算逻辑**:
1. 从 storage 查询最近 N 天记录
2. 对每条记录计算 reactive_L vs forecast_L 的差异
3. 统计差异的 mean/std/max
4. 判断 forecast 参数是否会导致不同决策：
   - 方向变化：forecast_L 符号 vs reactive_L 符号不同
   - 阈值变化：forecast 的 threshold_mult vs reactive 的 threshold_mult 差异 > 0.1
   - 仓位变化：forecast 的 position_mult vs reactive 的 position_mult 差异 > 0.1
5. 方向一致率 = 方向相同的记录数 / 总记录数

**测试用例** (test_shadow_logger_report.py):
- T_B4.1: 无记录时返回 total_records=0
- T_B4.2: 有记录时返回正确的 param_diff_stats
- T_B4.3: L 差异 mean/std/max 计算正确
- T_B4.4: would_change_decision 统计正确
- T_B4.5: direction_consistency 计算正确
- T_B4.6: regime_distribution 统计正确

---

### T_B5: polling_trader 集成 + 开关

**文件**: `11-易经推理系统/scripts/memory_l4/polling_trader.py`
**TDD**: ✓
**优先级**: P1
**验收 ID**: T_B5

**集成点**: 在轮询主循环的 `_execute_trade` 调用后插入 ShadowLogger 记录。

**修改位置**: `polling_trader.py` 的 `_poll_cycle` 方法中，第二阶段（持仓管理）和第三阶段（新开仓）的 `_execute_trade` 调用之后。

```python
# polling_trader.py 新增

# 顶部导入
from bcrm2.shadow_logger import ShadowLogger, SHADOW_LOGGER_ENABLED

class PollingTrader:
    # ... 现有代码 ...

    def _init_shadow_logger(self):
        """初始化 ShadowLogger（若开关开启）。"""
        if not SHADOW_LOGGER_ENABLED:
            self._shadow_logger = None
            return
        try:
            from bcrm2.morph_cycle_predictor import MorphCyclePredictor
            from bcrm2.parameter_mapper import ParameterMapper
            from bcrm2.run_evolution_pipeline import get_storage
            storage = get_storage()
            predictor = MorphCyclePredictor(storage)
            mapper = ParameterMapper()
            self._shadow_logger = ShadowLogger(storage, predictor, mapper)
            self._log("ShadowLogger 已初始化（影子模式运行中）", "INFO")
        except Exception as e:
            self._shadow_logger = None
            self._log(f"ShadowLogger 初始化失败: {e}", "WARN")

    def _record_shadow_log(self, coin: str, inference: dict,
                            actual_params: dict):
        """记录一条 Shadow 日志（若开关开启）。"""
        if not SHADOW_LOGGER_ENABLED or not self._shadow_logger:
            return
        try:
            self._shadow_logger.record_polling(coin, inference, actual_params)
        except Exception as e:
            self._log(f"[{coin}] Shadow 记录失败: {e}", "DEBUG")
```

**在 _execute_trade 调用后插入**:
```python
# 第二阶段：持仓管理
for coin, inference in all_inferences.items():
    try:
        pos_info = self._check_positions(coin)
        if pos_info.get("has_position"):
            self._execute_trade(inference, confidence_threshold=effective_threshold,
                                all_inferences=all_inferences)
            # ── ShadowLogger 记录（NEW）──
            self._record_shadow_log(coin, inference, {
                "direction": inference.get("direction"),
                "confidence": inference.get("confidence"),
                "position_usdt": inference.get("position_usdt"),
                "tp_px": inference.get("take_profit_px"),
                "sl_px": inference.get("stop_loss_px"),
                "threshold": effective_threshold,
            })
    except Exception as e:
        ...
```

**开关关闭时的字节等价保证**:
- `_init_shadow_logger()` 检查 `SHADOW_LOGGER_ENABLED`，关闭时 `self._shadow_logger = None`
- `_record_shadow_log()` 检查 `self._shadow_logger`，为 None 时直接 return
- 不影响任何现有交易逻辑

**测试用例** (test_shadow_logger_integration.py):
- T_B5.1: SHADOW_LOGGER_ENABLED=False 时 _shadow_logger 为 None
- T_B5.2: _record_shadow_log 开关关闭时不执行
- T_B5.3: _record_shadow_log 开关开启时调用 record_polling
- T_B5.4: _record_shadow_log 异常时不影响主流程
- T_B5.5: _init_shadow_logger 失败时降级为 None

---

### T_B6: /api/shadow/report API

**文件**: `11-易经推理系统/data_server_fixed.py`
**TDD**: ✓
**优先级**: P2
**验收 ID**: T_B6

**API 端点**:
- `GET /api/shadow/report?symbol=BTC&days=7` — 返回 Shadow 评估报告

**实现**:
```python
# data_server_fixed.py

def get_shadow_report(symbol: str = "BTC", days: int = 7):
    """返回 Shadow 影子模式评估报告。"""
    try:
        from bcrm2.shadow_logger import ShadowLogger, SHADOW_LOGGER_ENABLED
        if not SHADOW_LOGGER_ENABLED:
            return {"ok": False, "error": "ShadowLogger 未启用"}

        predictor = _get_predictor()
        storage = predictor.storage
        from bcrm2.parameter_mapper import ParameterMapper
        mapper = ParameterMapper()

        logger = ShadowLogger(storage, predictor, mapper)
        report = logger.get_comparison_report(symbol, days)
        return {"ok": True, "report": report}
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}

# 路由注册（在 do_GET 中）
elif path == "/api/shadow/report":
    symbol = (self._get_query_param("symbol") or "BTC").upper()
    days = int(self._get_query_param("days") or "7")
    self._json(get_shadow_report(symbol, days))
```

**测试用例** (test_shadow_logger_api.py):
- T_B6.1: get_shadow_report 函数存在
- T_B6.2: 路由 /api/shadow/report 已注册
- T_B6.3: SHADOW_LOGGER_ENABLED=False 时返回 ok=False
- T_B6.4: 开关开启时返回 ok=True 和 report 结构

---

## 三、测试文件清单

| 测试文件 | 任务 | 测试数 |
|---|---|---|
| `tests/test_shadow_logger_storage.py` | T_B1 | 6 |
| `tests/test_shadow_logger_class.py` | T_B2 | 5 |
| `tests/test_shadow_logger_record.py` | T_B3 | 7 |
| `tests/test_shadow_logger_report.py` | T_B4 | 6 |
| `tests/test_shadow_logger_integration.py` | T_B5 | 5 |
| `tests/test_shadow_logger_api.py` | T_B6 | 4 |
| **合计** | 6 个任务 | **33** |

---

## 四、依赖关系

```
T_B1 (storage 表) ──→ T_B2 (ShadowLogger 骨架) ──→ T_B3 (record_polling)
                                                           ↓
                                                    T_B4 (get_report)
                                                           ↓
                                                    T_B5 (polling 集成)
                                                           ↓
                                                    T_B6 (API)
```

- T_B1 和 T_B2 可并行（T_B2 的测试可 mock storage）
- T_B3 依赖 T_B1 + T_B2
- T_B4 依赖 T_B3（需要记录才能报告）
- T_B5 依赖 T_B3
- T_B6 依赖 T_B4 + T_B5

---

## 五、硬约束兼容性

| 硬约束 | 兼容性 | 说明 |
|---|---|---|
| CLI 默认字节等价 | ✅ | `SHADOW_LOGGER_ENABLED = False` 默认关闭，不影响交易 |
| 无偏不变量 | ✅ | 开关关闭时 `_record_shadow_log` 直接 return |
| 三层架构 | ✅ | ShadowLogger 在 Phase A 前置层，不修改 BCRM 2.0 核心层代码 |
| 不影响实际交易 | ✅ | Shadow 只记录，不改变任何交易参数 |
| 异常隔离 | ✅ | ShadowLogger 异常被 catch，不影响主流程 |

---

## 六、验收标准

| 测试 ID | 内容 | 通过标准 |
|---|---|---|
| T_B1 | shadow_param_log 表 CRUD | 保存/查询/清除/计数全部正确 |
| T_B2 | ShadowLogger 类骨架 | 可实例化，3 个核心方法存在 |
| T_B3 | record_polling 记录逻辑 | 开关关闭返回 None；开启时正确记录 reactive/forecast/actual |
| T_B4 | get_comparison_report 评估 | param_diff_stats/would_change/direction_consistency 正确 |
| T_B5 | polling_trader 集成 | 开关关闭字节等价；开启时记录；异常不阻断主流程 |
| T_B6 | /api/shadow/report API | 路由注册 + 开关关闭返回 ok=False + 开启返回报告 |
