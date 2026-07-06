# QMM Phase 1 — 离线内核设计

**日期**: 2026-05-13
**范围**: V2 仓库 (dream-multiskill-v2)
**依赖**: `math` / `statistics` / `json` / `dataclasses`（零外部依赖）
**执行优先级**: Phase A P0（保守线 — 双轨战略中的 V2 基线）
**收敛判断**: Phase A 完成后，若 V5 原型胜率 >55%，此基线保留为降级路径

---

## 一、目标

在 V2 仓库中实现 QMM 离线量化内核，作为可插拔 Sidecar 模块：
- **只读** L4 产出物（cases/distills/stats/index）
- **不修改**任何现有 L4 代码或文件
- **输出**固定契约信号到独立 `qmm/` 目录
- **纯 math/statistics**，零外部依赖

---

## 二、目录结构

```
scripts/memory_l4/qmm/                ← 新建
├── __init__.py                       ← 空
├── engine.py                         ← 单入口 run_qmm()
├── data_prep.py                      ← 数据准备
├── triple_screen.py                  ← 三屏对齐
├── mrd.py                            ← 阻力最小方向
├── trend_velocity.py                 ← 趋势速度 + 变化点
├── uncertainty.py                    ← 不确定性量化
├── paths.py                          ← 输出路径
└── types.py                          ← 数据类型定义

.workbuddy/memory_l4/qmm/             ← 新建输出目录
├── qmm_snapshot_{ts}.json            ← 完整量化快照
└── signals_index.json                ← 最新信号索引
```

---

## 三、模块设计

### 3.1 types.py — 数据类型

```python
@dataclass
class CleanedEvent:
    event_id: str
    ts: str
    regime: str
    quadrant_x: float
    quadrant_y: float
    pnl_pct: Optional[float]
    is_profit: Optional[bool]
    severity: Optional[float]
    quality: float                    # 0-1
    clean_flags: List[str]

@dataclass
class ScreenResult:
    timeframe: str                    # "long" / "mid" / "short"
    direction: str                    # "UP" / "DOWN" / "FLAT"
    confidence: float                 # 0-1
    x_mean: float
    y_mean: float
    profit_rate: float
    case_count: int

@dataclass
class MDRResult:
    direction: str                    # "UP" / "DOWN" / "NEUTRAL"
    resistance_up: float              # 0-100
    resistance_down: float            # 0-100
    net: float
    confidence: float                 # 0-1

@dataclass
class QMMOutput:
    version: str = "qmm-v1.0"
    snapshot_ts: str = ""
    data_version: str = ""
    feature_def_version: str = ""
    qmm_version: str = "qmm-v1.0"
    trend_state: str = "UNKNOWN"
    trend_change_point: str = "UNKNOWN"
    mrd_vector: Dict = field(default_factory=dict)
    uncertainty: float = 1.0
    triple_screen: Dict = field(default_factory=dict)
    velocity: Dict = field(default_factory=dict)
    acceleration: Dict = field(default_factory=dict)
    reason_codes: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
```

### 3.2 data_prep.py — 数据准备

**职责**：从 L4 cases/distills 提取并清洗时间序列特征。

```python
def prepare_events(cases: List[Dict], distills: List[Dict]) -> List[CleanedEvent]:
    """主入口：提取 + 清洗 + 质量评分。"""
    events = []
    for c in cases:
        ev = _extract_event(c)
        if ev:
            events.append(ev)

    # 排序（时间优先）
    events.sort(key=lambda e: e.ts)

    # 异常值检测（IQR）
    events = _detect_outliers(events)

    # 质量评分
    for ev in events:
        ev.quality = _compute_quality(ev)

    return events

def _extract_event(case: Dict) -> Optional[CleanedEvent]:
    """从单个 TradeCase 提取事件。"""
    do = case.get("decision_outcome") or {}
    q = case.get("quadrant") or {}
    pnl = do.get("pnl_pct")

    return CleanedEvent(
        event_id=case.get("case_id", ""),
        ts=case.get("ts_start", ""),
        regime=(case.get("environment_snapshot") or {}).get("regime", "unknown"),
        quadrant_x=float(q.get("x", 0)),
        quadrant_y=float(q.get("y", 0)),
        pnl_pct=float(pnl) if pnl is not None else None,
        is_profit=(pnl > 0) if pnl is not None else None,
        severity=_compute_severity(pnl, do.get("max_drawdown_pct")),
        quality=0.0,  # computed later
        clean_flags=[],
    )
```

**异常值检测**（IQR）：
- 对 pnl_pct 计算 Q1/Q3/IQR
- 超出 `[Q1 - 1.5*IQR, Q3 + 1.5*IQR]` 的事件标记 `OUTLIER_PNL`，不剔除

**质量评分**：
- `completeness = 非空字段数 / 总字段数`
- `recency = exp(-days_since_event / 90)`（与 L4 现有 90 天半衰期一致）
- `quality = 0.4 * completeness + 0.3 * 1.0 + 0.3 * recency`

**失败语义**：
- case 数量 < 3 → `reason_codes: ["INSUFFICIENT_DATA"]`，返回最小 QMMOutput
- 所有 case 的 quadrant 均为 (0,0) → `reason_codes: ["NO_QUADRANT_DATA"]`

### 3.3 triple_screen.py — 三屏对齐

**职责**：按时间窗口划分事件，计算各屏趋势与对齐度。

```python
@dataclass
class ScreenConfig:
    long_window: int = 20    # 类比周线
    mid_window: int = 10     # 类比日线
    short_window: int = 5    # 类比1h

def compute_triple_screen(events: List[CleanedEvent],
                          config: ScreenConfig) -> Dict:
    """三屏对齐。

    返回:
    {
        "long": ScreenResult, "mid": ScreenResult, "short": ScreenResult,
        "alignment": float,  # -1 ~ 1
        "trend_state": str,
    }
    """
    long_screen = _compute_screen(events[-config.long_window:], "long")
    mid_screen = _compute_screen(events[-config.mid_window:], "mid")
    short_screen = _compute_screen(events[-config.short_window:], "short")

    dirs = [long_screen.direction, mid_screen.direction, short_screen.direction]

    # 对齐度
    if len(set(dirs)) == 1 and dirs[0] != "FLAT":
        alignment = 1.0
    elif dirs.count(dirs[0]) >= 2:
        alignment = 0.3
    else:
        alignment = -0.3

    # 趋势状态
    if alignment > 0.5:
        trend_state = long_screen.direction
    elif alignment > 0:
        trend_state = mid_screen.direction
    else:
        trend_state = "TRANSITIONING"

    return {
        "long": long_screen,
        "mid": mid_screen,
        "short": short_screen,
        "alignment": round(alignment, 4),
        "trend_state": trend_state,
    }

def _compute_screen(window: List[CleanedEvent], timeframe: str) -> ScreenResult:
    """计算单屏趋势。"""
    if not window:
        return ScreenResult(timeframe=timeframe, direction="FLAT", confidence=0,
                            x_mean=0, y_mean=0, profit_rate=0, case_count=0)

    x_mean = sum(e.quadrant_x for e in window) / len(window)
    y_mean = sum(e.quadrant_y for e in window) / len(window)
    profits = sum(1 for e in window if e.is_profit)
    profit_rate = profits / len(window) if window else 0

    # 方向判断
    if x_mean > 0.1:
        direction = "UP"
    elif x_mean < -0.1:
        direction = "DOWN"
    else:
        direction = "FLAT"

    # 置信度
    profit_alignment = 1.0 if (
        (x_mean > 0 and profit_rate > 0.5) or
        (x_mean < 0 and profit_rate < 0.5)
    ) else 0.5
    confidence = y_mean * min(1.0, len(window) / 20) * profit_alignment

    return ScreenResult(
        timeframe=timeframe,
        direction=direction,
        confidence=round(max(0, min(1, confidence)), 4),
        x_mean=round(x_mean, 4),
        y_mean=round(y_mean, 4),
        profit_rate=round(profit_rate, 4),
        case_count=len(window),
    )
```

### 3.4 mrd.py — 阻力最小方向

**职责**：基于象限密度计算 UP/DOWN 方向阻力，输出最小阻力路径。

```python
def compute_mrd(events: List[CleanedEvent],
                threshold: float = 20.0) -> MDRResult:
    """计算阻力最小方向。

    算法:
    1. benefit_density = count(x>0.3 & y>0.5) / N
    2. harm_density = count(x<-0.3 & y>0.5) / N
    3. R_UP = harm_density * 100
    4. R_DOWN = benefit_density * 100
    5. net = R_DOWN - R_UP (正数=UP更容易)
    """
    if not events:
        return MDRResult(direction="NEUTRAL", resistance_up=50, resistance_down=50,
                         net=0, confidence=0)

    n = len(events)
    benefit_count = sum(1 for e in events if e.quadrant_x > 0.3 and e.quadrant_y > 0.5)
    harm_count = sum(1 for e in events if e.quadrant_x < -0.3 and e.quadrant_y > 0.5)

    benefit_density = benefit_count / n
    harm_density = harm_count / n

    r_up = harm_density * 100
    r_down = benefit_density * 100
    net = r_down - r_up

    if net > threshold:
        direction = "UP"
    elif net < -threshold:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"

    total = r_up + r_down
    confidence = abs(net) / max(total, 1) if total > 0 else 0

    return MDRResult(
        direction=direction,
        resistance_up=round(r_up, 2),
        resistance_down=round(r_down, 2),
        net=round(net, 2),
        confidence=round(max(0, min(1, confidence)), 4),
    )
```

**与 A2 的关系**：
- A2 `_least_resistance_path(rsi, funding_rate, fgi)` 基于即时指标
- QMM MRD 基于 L4 历史记忆象限密度
- 两者共存，A2 保持独立降级路径

### 3.5 trend_velocity.py — 趋势速度 + 变化点

**职责**：从 quadrant(x,y) 时间序列计算速度、加速度、变化点。

```python
def compute_trend_velocity(events: List[CleanedEvent]) -> Dict:
    """三维速度 + 加速度 + 变化点检测。

    返回:
    {
        "velocity": {"price": float, "confidence": float},
        "acceleration": {"price": float},
        "change_point": str,  # ACCELERATING / DECELERATING / REVERSING / STABLE
    }
    """
    if len(events) < 2:
        return {
            "velocity": {"price": 0, "confidence": 0},
            "acceleration": {"price": 0},
            "change_point": "STABLE",
        }

    # 速度 = d(x)/dt (按事件顺序，dt=1 step)
    velocities = []
    for i in range(1, len(events)):
        velocities.append(events[i].quadrant_x - events[i-1].quadrant_x)

    # 加速度 = d(v)/dt
    accelerations = []
    for i in range(1, len(velocities)):
        accelerations.append(velocities[i] - velocities[i-1])

    v_latest = velocities[-1] if velocities else 0
    a_latest = accelerations[-1] if accelerations else 0

    # 速度稳定性（最近 3 个速度的平均绝对值倒数）
    recent_v = velocities[-3:] if len(velocities) >= 3 else velocities
    v_confidence = 1.0 / (1.0 + statistics.stdev(recent_v)) if len(recent_v) >= 2 else 0.5

    # 变化点检测
    eps = 0.001
    change_point = _detect_change_point(v_latest, a_latest, velocities, eps)

    return {
        "velocity": {"price": round(v_latest, 4), "confidence": round(v_confidence, 4)},
        "acceleration": {"price": round(a_latest, 4)},
        "change_point": change_point,
    }

def _detect_change_point(v: float, a: float, velocities: List[float], eps: float) -> str:
    """检测趋势变化点。"""
    if abs(v) < eps and abs(a) < eps:
        return "STABLE"
    if v * a > 0 and abs(a) > eps:
        return "ACCELERATING"
    if v * a < 0 and abs(a) > eps:
        return "DECELERATING"
    if len(velocities) >= 3 and _sign(velocities[-1]) != _sign(velocities[-3]):
        return "REVERSING"
    return "STABLE"

def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)
```

### 3.6 uncertainty.py — 不确定性量化

**职责**：综合多因子计算信号不确定性。

```python
def compute_uncertainty(triple_screen: Dict, mrd: MDRResult,
                        velocity: Dict, total_cases: int) -> float:
    """计算综合不确定性。

    因子:
    1. 三屏对齐度: 1 - |alignment| (对齐越低→不确定性越高)
    2. MRD 置信度: 1 - mrd.confidence
    3. 数据量: max(0, 1 - n/20) (< 20 case → 高不确定)
    4. 速度稳定性: 1 - velocity.confidence
    """
    factors = []

    # 对齐度
    alignment = triple_screen.get("alignment", 0)
    factors.append(1.0 - abs(alignment))

    # MRD 置信度
    factors.append(1.0 - mrd.confidence)

    # 数据量
    data_factor = max(0.0, 1.0 - total_cases / 20)
    factors.append(data_factor)

    # 速度稳定性
    v_conf = velocity.get("confidence", 0)
    factors.append(1.0 - v_conf)

    # 等权平均
    uncertainty = sum(factors) / len(factors)
    return round(max(0.0, min(1.0, uncertainty)), 4)
```

### 3.7 engine.py — 单入口

```python
def run_qmm(
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> QMMOutput:
    """QMM 唯一入口。

    执行流程:
    1. 数据准备
    2. 三屏对齐
    3. 阻力方向
    4. 趋势速度 + 变化点
    5. 不确定性
    6. 输出
    """
    from scripts.memory_l4.qmm.paths import qmm_dir

    # 版本三元组
    data_version = _compute_data_version(cases)
    feature_def_version = "qmm-fd-v1.0"
    qmm_version = "qmm-v1.0"

    # Step 1: 数据准备
    events = prepare_events(cases, distills)

    # 失败语义检查
    if len(events) < 3:
        return QMMOutput(
            trend_state="UNKNOWN",
            trend_change_point="STABLE",
            mrd_vector={"direction": "NEUTRAL", "resistance_up": 50,
                        "resistance_down": 50, "confidence": 0},
            uncertainty=1.0,
            reason_codes=["INSUFFICIENT_DATA"],
            evidence_refs=[e.event_id for e in events],
            data_version=data_version,
            feature_def_version=feature_def_version,
            qmm_version=qmm_version,
        )

    # Step 2: 三屏对齐
    screen_config = ScreenConfig(**config) if config else ScreenConfig()
    ts_result = compute_triple_screen(events, screen_config)

    # Step 3: 阻力方向
    mrd_result = compute_mrd(events)

    # Step 4: 趋势速度
    vel_result = compute_trend_velocity(events)

    # Step 5: 不确定性
    unc = compute_uncertainty(ts_result, mrd_result,
                              vel_result["velocity"], len(events))

    # Step 6: 构建输出
    output = QMMOutput(
        snapshot_ts=datetime.now().astimezone().isoformat(timespec="seconds"),
        data_version=data_version,
        feature_def_version=feature_def_version,
        qmm_version=qmm_version,
        trend_state=ts_result["trend_state"],
        trend_change_point=vel_result["change_point"],
        mrd_vector={
            "direction": mrd_result.direction,
            "resistance_up": mrd_result.resistance_up,
            "resistance_down": mrd_result.resistance_down,
            "confidence": mrd_result.confidence,
        },
        uncertainty=unc,
        triple_screen={
            "long": _screen_to_dict(ts_result["long"]),
            "mid": _screen_to_dict(ts_result["mid"]),
            "short": _screen_to_dict(ts_result["short"]),
            "alignment": ts_result["alignment"],
        },
        velocity=vel_result["velocity"],
        acceleration=vel_result["acceleration"],
        reason_codes=_build_reason_codes(ts_result, mrd_result, vel_result),
        evidence_refs=[e.event_id for e in events[-10:]],  # 最近 10 个 case
    )

    # Step 7: 写入输出
    _save_output(output, qmm_dir())

    return output
```

---

## 四、验收标准

| 标准 | 要求 |
|------|------|
| 零行现有代码修改 | 不修改 scripts/memory_l4/ 下任何已有文件 |
| 零外部依赖 | 仅 import math/statistics/json/dataclasses/pathlib/typing/datetime |
| 固定契约输出 | 输出字段严格匹配 QMMOutput dataclass |
| reason_codes 全英文大写 | 如 `INSUFFICIENT_DATA`, `BULLISH_ALIGNMENT`, `HIGH_UNCERTAINTY` |
| fail-closed | 输入不足 → 返回 UNKNOWN + uncertainty=1.0 |
| 版本三元组 | 每个输出包含 data_version / feature_def_version / qmm_version |
| 可复现 | 纯确定性计算，相同输入必然相同输出 |
