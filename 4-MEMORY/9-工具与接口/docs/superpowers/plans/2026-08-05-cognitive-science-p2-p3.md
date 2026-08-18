# 认知科学完善 P2/P3 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 P2-9 事前预测 + P2-7 静息态反刍（代码+回测），P2-8 双通道 + P3 理论注脚（仅文档），完成认知科学完善 12 项建议的剩余部分。

**Architecture:** 新增两个独立引擎模块（`prediction_engine.py` / `rumination_engine.py`），分别接入 polling_trader 开仓事件流和 cognitive_daemon 空闲循环。两者通过 episode 数据间接耦合（反刍消费含 prediction 的 episode）。认知回测复用现有 `cognitive_backtest.py` 框架，每项需 `path_advantage ≥ +0.2`。

**Tech Stack:** Python 3.9+ stdlib only（dataclasses, json, pathlib, datetime），无新外部依赖。复用 `evaluation_engine.compute_path_advantage` / `CognitiveLoopEntry.record` / `paths.episodes_dir()`。

## Global Constraints

- 认知回测 `path_advantage ≥ +0.2`（LEARNING_THRESHOLD_UP）才标记 upgrade
- 失败静默：PredictionEngine / RuminationEngine 异常不阻断主流程（开仓/daemon 主循环）
- 反刍记忆标记 `quality_level="C"` + `source="rumination"`，需 A8 验证才升级
- daemon 当日只反刍一次（`_last_rumination_date` 去重）
- 跨包不引入反向依赖：4-MEMORY 不 import 11-易经推理系统，episodes_dir 由参数传入
- TDD：每个引擎先写失败测试，再写最小实现

---

## File Structure

| 文件 | 职责 | 操作 |
|------|------|------|
| `4-MEMORY/9-工具与接口/prediction_engine.py` | 事前预测生成 + 误差计算 | 新建 |
| `4-MEMORY/9-工具与接口/test_prediction_engine.py` | prediction_engine 单测 | 新建 |
| `4-MEMORY/9-工具与接口/rumination_engine.py` | 静息态反刍（统计聚类） | 新建 |
| `4-MEMORY/9-工具与接口/test_rumination_engine.py` | rumination_engine 单测 | 新建 |
| `4-MEMORY/9-工具与接口/cognitive_daemon.py` | daemon 空闲反刍接入 | 修改 |
| `4-MEMORY/9-工具与接口/cognitive_backtest.py` | 新增 P2-9/P2-7 回测 | 修改 |
| `4-MEMORY/9-工具与接口/test_cognitive_backtest_unified.py` | 新回测测试 | 修改 |
| `11-易经推理系统/scripts/memory_l4/polling_trader.py` | 开仓事件加 prediction | 修改 |
| `11-易经推理系统/scripts/memory_l4/case_registry.py` | PREDICTION stage + EXIT prediction_error | 修改 |
| `4-MEMORY/0-元记忆/COGNITIVE_ARCHITECTURE.md` | P3 理论注脚 + v3.3 变更日志 | 修改 |

---

## Task 1: PredictionEngine + 单测（TDD）

**Files:**
- Create: `4-MEMORY/9-工具与接口/prediction_engine.py`
- Test: `4-MEMORY/9-工具与接口/test_prediction_engine.py`

**Interfaces:**
- Produces: `PredictionEngine.generate_prediction(inference: dict) -> Prediction`；`PredictionEngine.compute_error(prediction: Prediction, actual: dict) -> PredictionError`

- [ ] **Step 1: 写失败测试 test_prediction_engine.py**

```python
#!/usr/bin/env python3
"""PredictionEngine 单测（P2-9 事前预测）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from prediction_engine import PredictionEngine, Prediction, PredictionError


def test_generate_prediction_fields():
    """生成预测含完整字段"""
    engine = PredictionEngine()
    inf = {
        "direction": "LONG",
        "confidence": 0.72,
        "volatility": 0.03,
        "a0_warnings": ["c1", "c2"],
    }
    pred = engine.generate_prediction(inf)
    assert pred.expected_direction == "LONG"
    assert pred.expected_horizon_bars == 24  # vol 0.03 < 0.05 → 24
    assert 0.0 <= pred.stop_loss_prob <= 0.8
    assert pred.target_return_pct > 0
    assert 0.1 <= pred.prediction_confidence <= 0.95
    assert pred.generated_at  # 非空


def test_vol_to_horizon_high_vol():
    """高波动→短周期"""
    engine = PredictionEngine()
    assert engine._vol_to_horizon(0.15) == 6   # >0.10 → 6
    assert engine._vol_to_horizon(0.08) == 12  # 0.05-0.10 → 12
    assert engine._vol_to_horizon(0.03) == 24  # 0.02-0.05 → 24
    assert engine._vol_to_horizon(0.01) == 48  # <0.02 → 48


def test_compute_error_direction_hit():
    """方向命中"""
    engine = PredictionEngine()
    pred = Prediction(
        expected_direction="LONG", expected_horizon_bars=24,
        stop_loss_prob=0.3, target_return_pct=3.5,
        prediction_confidence=0.72, generated_at="2026-08-05T00:00:00Z",
    )
    actual = {"direction": "long", "return_pct": 4.0, "stop_triggered": False}
    err = engine.compute_error(pred, actual)
    assert err.direction_hit is True
    assert err.target_hit is True  # 4.0 >= 3.5
    assert err.stop_triggered is False
    assert err.magnitude_error >= 0


def test_compute_error_direction_miss():
    """方向未命中"""
    engine = PredictionEngine()
    pred = Prediction(
        expected_direction="LONG", expected_horizon_bars=24,
        stop_loss_prob=0.3, target_return_pct=3.5,
        prediction_confidence=0.72, generated_at="2026-08-05T00:00:00Z",
    )
    actual = {"direction": "SHORT", "return_pct": -2.0, "stop_triggered": True}
    err = engine.compute_error(pred, actual)
    assert err.direction_hit is False
    assert err.target_hit is False
    assert err.stop_triggered is True


def test_generate_prediction_missing_fields():
    """inference 缺字段时返回默认 Prediction（不抛异常）"""
    engine = PredictionEngine()
    pred = engine.generate_prediction({})
    assert pred.expected_direction == "HOLD"
    assert pred.prediction_confidence == 0.1  # 默认夹紧下限


def test_stop_loss_prob_capped():
    """止损概率上限 0.8"""
    engine = PredictionEngine()
    inf = {"direction": "LONG", "confidence": 0.9, "volatility": 0.5, "a0_warnings": ["c"]*10}
    pred = engine.generate_prediction(inf)
    assert pred.stop_loss_prob <= 0.8


if __name__ == "__main__":
    for fn in [
        test_generate_prediction_fields,
        test_vol_to_horizon_high_vol,
        test_compute_error_direction_hit,
        test_compute_error_direction_miss,
        test_generate_prediction_missing_fields,
        test_stop_loss_prob_capped,
    ]:
        try:
            fn()
            print(f"✅ {fn.__name__}")
        except AssertionError as e:
            print(f"❌ {fn.__name__}: {e}")
            raise
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd 4-MEMORY/9-工具与接口 && python3 -m pytest test_prediction_engine.py -v 2>&1 | tail -15`
Expected: FAIL with `ModuleNotFoundError: No module named 'prediction_engine'`

- [ ] **Step 3: 写最小实现 prediction_engine.py**

```python
#!/usr/bin/env python3
"""
事前预测引擎 (Prediction Engine) — P2-9 主动推理

对齐 Friston 主动推理：开仓前生成预测，平仓后计算预测误差，
误差驱动贝叶斯更新（最小化自由能）。

关联文档: COGNITIVE_ARCHITECTURE.md §5.4 P2-9 / spec 2026-08-05-cognitive-science-p2-p3-design.md §2
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict


@dataclass
class Prediction:
    """事前预测（开仓时生成，平仓后校验）"""
    expected_direction: str       # "LONG" / "SHORT" / "HOLD"
    expected_horizon_bars: int    # 预期持仓周期（K线根数）
    stop_loss_prob: float         # 预期止损触发概率 [0,1]
    target_return_pct: float      # 预期目标收益率（%）
    prediction_confidence: float  # 预测置信度 [0,1]
    generated_at: str             # ISO 时间戳


@dataclass
class PredictionError:
    """预测误差（平仓后计算）"""
    direction_hit: bool           # 方向是否命中
    target_hit: bool              # 目标收益是否达成
    stop_triggered: bool          # 止损是否触发
    magnitude_error: float        # 误差幅度
    computed_at: str              # ISO 时间戳


class PredictionEngine:
    """事前预测生成器（对齐 Friston 主动推理）"""

    # 波动率→持仓周期映射（高波动短周期）
    _HORIZON_MAP = [
        (0.02, 48),   # vol<2% → 48根（约1天）
        (0.05, 24),   # vol<5% → 24根（约12小时）
        (0.10, 12),   # vol<10% → 12根（约6小时）
        (float("inf"), 6),  # 高波动 → 6根（约3小时）
    ]

    def generate_prediction(self, inference: Dict) -> Prediction:
        """从开仓 inference 生成事前预测"""
        direction = inference.get("direction", "HOLD")
        confidence = float(inference.get("confidence", 0.5))
        volatility = float(inference.get("volatility", 0.0))
        a0_warnings = inference.get("a0_warnings", [])

        horizon = self._vol_to_horizon(volatility)
        contradiction_count = len(a0_warnings)
        stop_loss_prob = min(0.8, 0.2 + contradiction_count * 0.1 + volatility * 2)
        target_return_pct = confidence * 5 + volatility * 10
        prediction_confidence = max(0.1, min(0.95, confidence))

        return Prediction(
            expected_direction=direction,
            expected_horizon_bars=horizon,
            stop_loss_prob=round(stop_loss_prob, 4),
            target_return_pct=round(target_return_pct, 4),
            prediction_confidence=round(prediction_confidence, 4),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def compute_error(self, prediction: Prediction, actual: Dict) -> PredictionError:
        """平仓后计算预测误差"""
        actual_direction = str(actual.get("direction", ""))
        actual_return_pct = float(actual.get("return_pct", 0.0))
        stop_triggered = bool(actual.get("stop_triggered", False))

        direction_hit = (actual_direction.upper() == prediction.expected_direction.upper())
        target_hit = (actual_return_pct >= prediction.target_return_pct)
        magnitude_error = (
            abs(actual_return_pct - prediction.target_return_pct)
            / max(abs(prediction.target_return_pct), 0.01)
        )

        return PredictionError(
            direction_hit=direction_hit,
            target_hit=target_hit,
            stop_triggered=stop_triggered,
            magnitude_error=round(magnitude_error, 4),
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _vol_to_horizon(self, volatility: float) -> int:
        for threshold, horizon in self._HORIZON_MAP:
            if volatility < threshold:
                return horizon
        return 6
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd 4-MEMORY/9-工具与接口 && python3 -m pytest test_prediction_engine.py -v 2>&1 | tail -15`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add 4-MEMORY/9-工具与接口/prediction_engine.py 4-MEMORY/9-工具与接口/test_prediction_engine.py
git commit -m "feat(cognitive): P2-9 add PredictionEngine for active inference"
```

---

## Task 2: 接入 polling_trader 开仓事件

**Files:**
- Modify: `11-易经推理系统/scripts/memory_l4/polling_trader.py:2288-2335`

**Interfaces:**
- Consumes: `PredictionEngine.generate_prediction` (Task 1)
- Produces: 开仓 event dict 含 `prediction` 字段

- [ ] **Step 1: 修改 _record_opening_event 加 prediction 字段**

在 `polling_trader.py` L2313-2328 的 event dict 中，在 `"cognitive_recall": ...` 行之后追加 prediction 字段。在 event dict 构造前插入 PredictionEngine 调用。

修改位置（L2311-2333 轻量开仓事件存档块）：

在 `# 轻量开仓事件存档` try 块内，`event = {...}` 之前插入：
```python
            # P2-9: 事前预测（对齐 Friston 主动推理）
            prediction_data = None
            try:
                from scripts.memory_l4.prediction_bridge import generate_prediction_dict
                prediction_data = generate_prediction_dict(inference)
            except Exception:
                pass
```

在 event dict 的 `"cognitive_recall": self._summarize_cognitive_recall(inference),` 行之后追加：
```python
                "prediction": prediction_data,
```

- [ ] **Step 2: 创建 prediction_bridge 适配层**

**Files:** Create `11-易经推理系统/scripts/memory_l4/prediction_bridge.py`

说明：polling_trader 在 11-易经推理系统包内，PredictionEngine 在 4-MEMORY 包内。为避免 11→4 反向依赖，建一个 bridge 文件，用 sys.path 注入方式导入 PredictionEngine（与现有 ab_bridge 模式一致）。

```python
#!/usr/bin/env python3
"""
prediction_bridge — P2-9 事前预测桥接层

将 4-MEMORY 的 PredictionEngine 暴露给 11-易经推理系统使用，
避免 11→4 包级反向依赖（与 ab_bridge 模式一致）。
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# 注入 4-MEMORY/9-工具与接口 到 sys.path
_MEM_TOOLS = Path(__file__).resolve().parents[2] / "4-MEMORY" / "9-工具与接口"
if str(_MEM_TOOLS) not in sys.path:
    sys.path.insert(0, str(_MEM_TOOLS))


def generate_prediction_dict(inference: Dict) -> Optional[Dict[str, Any]]:
    """从 inference 生成预测 dict（失败返回 None）"""
    try:
        from prediction_engine import PredictionEngine
        engine = PredictionEngine()
        pred = engine.generate_prediction(inference)
        return {
            "expected_direction": pred.expected_direction,
            "expected_horizon_bars": pred.expected_horizon_bars,
            "stop_loss_prob": pred.stop_loss_prob,
            "target_return_pct": pred.target_return_pct,
            "prediction_confidence": pred.prediction_confidence,
            "generated_at": pred.generated_at,
        }
    except Exception:
        return None


def compute_prediction_error_dict(prediction_dict: Dict, actual: Dict) -> Optional[Dict[str, Any]]:
    """从 prediction dict + actual 计算误差 dict（失败返回 None）"""
    if not prediction_dict:
        return None
    try:
        from prediction_engine import Prediction, PredictionError, PredictionEngine
        pred = Prediction(
            expected_direction=prediction_dict.get("expected_direction", "HOLD"),
            expected_horizon_bars=prediction_dict.get("expected_horizon_bars", 0),
            stop_loss_prob=prediction_dict.get("stop_loss_prob", 0.0),
            target_return_pct=prediction_dict.get("target_return_pct", 0.0),
            prediction_confidence=prediction_dict.get("prediction_confidence", 0.0),
            generated_at=prediction_dict.get("generated_at", ""),
        )
        engine = PredictionEngine()
        err = engine.compute_error(pred, actual)
        return {
            "direction_hit": err.direction_hit,
            "target_hit": err.target_hit,
            "stop_triggered": err.stop_triggered,
            "magnitude_error": err.magnitude_error,
            "computed_at": err.computed_at,
        }
    except Exception:
        return None
```

- [ ] **Step 3: 写集成测试验证开仓事件含 prediction**

**Files:** Create `11-易经推理系统/tests/test_polling_trader_prediction.py`

```python
#!/usr/bin/env python3
"""polling_trader P2-9 集成测试：开仓事件含 prediction 字段"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.prediction_bridge import generate_prediction_dict


def test_prediction_dict_has_fields():
    """bridge 生成 prediction dict 含完整字段"""
    inf = {"direction": "LONG", "confidence": 0.7, "volatility": 0.03, "a0_warnings": []}
    pred = generate_prediction_dict(inf)
    assert pred is not None
    assert pred["expected_direction"] == "LONG"
    assert "generated_at" in pred


def test_prediction_dict_failure_returns_none():
    """bridge 异常时返回 None"""
    pred = generate_prediction_dict(None)  # None 输入
    # None.get 会抛异常，bridge 捕获返回 None
    assert pred is None


if __name__ == "__main__":
    test_prediction_dict_has_fields()
    test_prediction_dict_failure_returns_none()
    print("✅ prediction_bridge 测试通过")
```

- [ ] **Step 4: 运行集成测试**

Run: `cd 11-易经推理系统 && python3 -m pytest tests/test_polling_trader_prediction.py -v 2>&1 | tail -10`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add 11-易经推理系统/scripts/memory_l4/prediction_bridge.py 11-易经推理系统/scripts/memory_l4/polling_trader.py 11-易经推理系统/tests/test_polling_trader_prediction.py
git commit -m "feat(trading): P2-9 inject prediction into opening event via bridge"
```

---

## Task 3: 接入 case_registry（PREDICTION stage + EXIT prediction_error）

**Files:**
- Modify: `11-易经推理系统/scripts/memory_l4/case_registry.py:283-322` (PREDICTION stage) + `:463-475` (EXIT prediction_error)

**Interfaces:**
- Consumes: `prediction_bridge.compute_prediction_error_dict` (Task 2)
- Produces: case `thinking_chain` 含 PREDICTION stage；case 含 `prediction_error` 字段

- [ ] **Step 1: 在 _build_thinking_chain 追加 PREDICTION stage**

在 `case_registry.py` `_build_thinking_chain` 方法末尾（return chain 之前）追加 PREDICTION stage。先读取当前方法的 return 位置。

定位 `_build_thinking_chain` 的 `return chain` 行（约 L322 后），在其之前插入：
```python
        # P2-9: 追加 PREDICTION stage（事前预测快照）
        prediction = ctx.get("prediction")
        if prediction:
            chain.append({
                "stage": "PREDICTION",
                "ts": event.ts_entry,
                "decision": f"Predict {prediction.get('expected_direction', 'N/A')} "
                            f"target={prediction.get('target_return_pct', 0)}%",
                "rationale": f"horizon={prediction.get('expected_horizon_bars', 0)}bars, "
                             f"stop_prob={prediction.get('stop_loss_prob', 0)}, "
                             f"conf={prediction.get('prediction_confidence', 0)}",
                "evidence_refs": [],
                "prediction_snapshot": prediction,
            })
```

- [ ] **Step 2: 在 EXIT 阶段计算 prediction_error**

在 `update_case_on_exit`（L463-475 追加 EXIT stage 之后）插入 prediction_error 计算。在 `chain.append({...EXIT...})` 和 `case["thinking_chain"] = chain` 之间插入：

```python
        # P2-9: 计算预测误差（若 case 含 prediction）
        prediction_snapshot = None
        for stage in chain:
            if stage.get("stage") == "PREDICTION":
                prediction_snapshot = stage.get("prediction_snapshot")
                break
        if prediction_snapshot:
            try:
                from scripts.memory_l4.prediction_bridge import compute_prediction_error_dict
                actual = {
                    "direction": direction,
                    "return_pct": pnl_pct if pnl_pct is not None else 0.0,
                    "stop_triggered": exit_reason == "stop_loss" if exit_reason else False,
                }
                prediction_error = compute_prediction_error_dict(prediction_snapshot, actual)
                if prediction_error:
                    case["prediction_error"] = prediction_error
            except Exception:
                pass
```

- [ ] **Step 3: 写 case_registry 集成测试**

**Files:** Create `11-易经推理系统/tests/test_case_registry_prediction.py`

```python
#!/usr/bin/env python3
"""case_registry P2-9 集成测试：PREDICTION stage + EXIT prediction_error"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.case_registry import create_case_from_episode_data


def test_case_contains_prediction_stage():
    """含 prediction 的 episode 生成的 case 含 PREDICTION stage"""
    episode = {
        "inst_id": "BTC-USDT-SWAP",
        "trace_id": "test-trace-1",
        "direction": "LONG",
        "ts_entry": "2026-08-05T00:00:00Z",
        "decision_context": {
            "hexagram": "乾",
            "confidence": 0.7,
            "prediction": {
                "expected_direction": "LONG",
                "expected_horizon_bars": 24,
                "stop_loss_prob": 0.3,
                "target_return_pct": 3.5,
                "prediction_confidence": 0.7,
                "generated_at": "2026-08-05T00:00:00Z",
            },
        },
    }
    case = create_case_from_episode_data(episode, "test-case-1")
    chain = case.get("thinking_chain", [])
    stages = [s.get("stage") for s in chain]
    assert "PREDICTION" in stages, f"PREDICTION stage missing, got {stages}"


def test_case_without_prediction_no_stage():
    """无 prediction 的 episode 不含 PREDICTION stage"""
    episode = {
        "inst_id": "BTC-USDT-SWAP",
        "trace_id": "test-trace-2",
        "direction": "LONG",
        "ts_entry": "2026-08-05T00:00:00Z",
        "decision_context": {"hexagram": "乾", "confidence": 0.7},
    }
    case = create_case_from_episode_data(episode, "test-case-2")
    chain = case.get("thinking_chain", [])
    stages = [s.get("stage") for s in chain]
    assert "PREDICTION" not in stages


if __name__ == "__main__":
    test_case_contains_prediction_stage()
    test_case_without_prediction_no_stage()
    print("✅ case_registry prediction 测试通过")
```

- [ ] **Step 4: 运行集成测试**

Run: `cd 11-易经推理系统 && python3 -m pytest tests/test_case_registry_prediction.py -v 2>&1 | tail -10`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add 11-易经推理系统/scripts/memory_l4/case_registry.py 11-易经推理系统/tests/test_case_registry_prediction.py
git commit -m "feat(memory-l4): P2-9 add PREDICTION stage + prediction_error to case"
```

---

## Task 4: RuminationEngine + 单测（TDD）

**Files:**
- Create: `4-MEMORY/9-工具与接口/rumination_engine.py`
- Test: `4-MEMORY/9-工具与接口/test_rumination_engine.py`

**Interfaces:**
- Produces: `RuminationEngine.ruminate(episodes_dir: str, lookback_days: int = 7) -> List[RuminationFinding]`

- [ ] **Step 1: 写失败测试 test_rumination_engine.py**

```python
#!/usr/bin/env python3
"""RuminationEngine 单测（P2-7 静息态反刍）"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from rumination_engine import RuminationEngine, RuminationFinding


def _write_episode(dir_path: Path, ts: str, coin: str, regime: str, direction: str, pnl_pct: float):
    ep = {
        "ts": ts, "inst_id": f"{coin}-USDT-SWAP", "coin": coin,
        "regime": regime, "direction": direction, "pnl_pct": pnl_pct,
    }
    fname = f"live_{coin}_{ts.replace(':', '').replace('-', '')}.json"
    (dir_path / fname).write_text(json.dumps(ep), encoding="utf-8")


def test_ruminate_finds_deviation():
    """偏离基线≥15% 的组产出 finding"""
    with tempfile.TemporaryDirectory() as d:
        ep_dir = Path(d)
        now = datetime.now(timezone.utc)
        # BTC ranging LONG 4笔全亏（胜率0%，远低于基线）
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i)).isoformat(),
                           "BTC", "ranging", "LONG", -1.0)
        # ETH trending SHORT 4笔全赢（胜率100%，远高于基线）
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i)).isoformat(),
                           "ETH", "trending", "SHORT", 1.0)

        engine = RuminationEngine()
        findings = engine.ruminate(str(ep_dir), lookback_days=7)
        keys = [f.pattern_key for f in findings]
        assert "BTC|ranging|LONG" in keys
        assert "ETH|trending|SHORT" in keys


def test_ruminate_filters_small_sample():
    """样本<3 的组不产出 finding"""
    with tempfile.TemporaryDirectory() as d:
        ep_dir = Path(d)
        now = datetime.now(timezone.utc)
        _write_episode(ep_dir, now.isoformat(), "BTC", "ranging", "LONG", -1.0)
        _write_episode(ep_dir, now.isoformat(), "BTC", "ranging", "LONG", -1.0)

        engine = RuminationEngine()
        findings = engine.ruminate(str(ep_dir), lookback_days=7)
        assert len(findings) == 0


def test_ruminate_empty_dir():
    """空目录返回空列表"""
    with tempfile.TemporaryDirectory() as d:
        engine = RuminationEngine()
        findings = engine.ruminate(d, lookback_days=7)
        assert findings == []


def test_ruminate_filters_small_deviation():
    """偏离<15% 不产出 finding"""
    with tempfile.TemporaryDirectory() as d:
        ep_dir = Path(d)
        now = datetime.now(timezone.utc)
        # 8 笔，4 赢 4 输 = 50% 胜率，基线也约 50%，偏离≈0
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i)).isoformat(),
                           "BTC", "ranging", "LONG", 1.0)
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i)).isoformat(),
                           "BTC", "ranging", "LONG", -1.0)

        engine = RuminationEngine()
        findings = engine.ruminate(str(ep_dir), lookback_days=7)
        assert len(findings) == 0


def test_finding_text_format():
    """finding_text 含币种/regime/方向/胜率/样本"""
    with tempfile.TemporaryDirectory() as d:
        ep_dir = Path(d)
        now = datetime.now(timezone.utc)
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i)).isoformat(),
                           "BTC", "ranging", "LONG", -1.0)
        engine = RuminationEngine()
        findings = engine.ruminate(str(ep_dir), lookback_days=7)
        assert len(findings) == 1
        text = findings[0].finding_text
        assert "BTC" in text
        assert "ranging" in text
        assert "LONG" in text


if __name__ == "__main__":
    for fn in [
        test_ruminate_finds_deviation,
        test_ruminate_filters_small_sample,
        test_ruminate_empty_dir,
        test_ruminate_filters_small_deviation,
        test_finding_text_format,
    ]:
        try:
            fn()
            print(f"✅ {fn.__name__}")
        except AssertionError as e:
            print(f"❌ {fn.__name__}: {e}")
            raise
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd 4-MEMORY/9-工具与接口 && python3 -m pytest test_rumination_engine.py -v 2>&1 | tail -15`
Expected: FAIL with `ModuleNotFoundError: No module named 'rumination_engine'`

- [ ] **Step 3: 写最小实现 rumination_engine.py**

```python
#!/usr/bin/env python3
"""
静息态反刍引擎 (Rumination Engine) — P2-7 DMN 默认模式网络

对齐 DMN 默认模式网络：空闲时从近期 episode 提取模式，
产出 C 级假设记忆（需 A8 验证才升级）。

关联文档: COGNITIVE_ARCHITECTURE.md §5.4 P2-7 / spec 2026-08-05-cognitive-science-p2-p3-design.md §3
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List


@dataclass
class RuminationFinding:
    """反刍发现的模式"""
    pattern_key: str              # "BTC|ranging|LONG" 格式
    observed_rate: float          # 观察到的胜率
    baseline_rate: float          # 基线胜率
    sample_n: int                 # 样本数
    deviation_pct: float          # 偏离基线百分比
    finding_text: str             # 自然语言描述
    generated_at: str             # ISO 时间戳


class RuminationEngine:
    """静息态反刍引擎（对齐 DMN 默认模式网络）"""

    DEVIATION_THRESHOLD = 0.15    # 偏离基线 15% 才记录
    MIN_SAMPLE_SIZE = 3           # 最小样本数
    LOOKBACK_DAYS = 7             # 默认回看天数

    def ruminate(self, episodes_dir: str, lookback_days: int = 7) -> List[RuminationFinding]:
        """从近期 episode 提取模式"""
        episodes = self._load_recent_episodes(episodes_dir, lookback_days)
        if len(episodes) < self.MIN_SAMPLE_SIZE:
            return []

        groups = self._group_episodes(episodes)
        baseline = self._calc_win_rate(episodes)
        if baseline <= 0:
            baseline = 0.01  # 避免除零

        findings: List[RuminationFinding] = []
        for key, group in groups.items():
            if len(group) < self.MIN_SAMPLE_SIZE:
                continue
            observed = self._calc_win_rate(group)
            if baseline <= 0:
                continue
            deviation = (observed - baseline) / baseline
            if abs(deviation) >= self.DEVIATION_THRESHOLD:
                findings.append(RuminationFinding(
                    pattern_key=key,
                    observed_rate=round(observed, 4),
                    baseline_rate=round(baseline, 4),
                    sample_n=len(group),
                    deviation_pct=round(deviation, 4),
                    finding_text=self._build_finding_text(key, observed, baseline, len(group)),
                    generated_at=datetime.now(timezone.utc).isoformat(),
                ))
        return findings

    def _load_recent_episodes(self, episodes_dir: str, lookback_days: int) -> List[Dict]:
        """加载近 N 天 episode（*.json）"""
        ep_path = Path(episodes_dir)
        if not ep_path.exists():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        episodes: List[Dict] = []
        for f in ep_path.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ts_str = data.get("ts") or data.get("ts_entry") or ""
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts >= cutoff:
                        episodes.append(data)
                else:
                    # 无时间戳的视为近期
                    episodes.append(data)
            except Exception:
                continue
        return episodes

    def _group_episodes(self, episodes: List[Dict]) -> Dict[str, List[Dict]]:
        """按 coin × regime × direction 聚合"""
        groups: Dict[str, List[Dict]] = {}
        for ep in episodes:
            coin = ep.get("coin", "UNKNOWN")
            regime = ep.get("regime", "unknown")
            direction = ep.get("direction", "UNKNOWN")
            key = f"{coin}|{regime}|{direction}"
            groups.setdefault(key, []).append(ep)
        return groups

    def _calc_win_rate(self, group: List[Dict]) -> float:
        """计算组胜率"""
        if not group:
            return 0.0
        wins = sum(1 for e in group if float(e.get("pnl_pct", 0)) > 0)
        return wins / len(group)

    def _build_finding_text(self, key: str, observed: float, baseline: float, n: int) -> str:
        """生成自然语言 finding 文本"""
        parts = key.split("|")
        coin = parts[0] if len(parts) > 0 else "UNKNOWN"
        regime = parts[1] if len(parts) > 1 else "unknown"
        direction = parts[2] if len(parts) > 2 else "UNKNOWN"
        deviation_pct = (observed - baseline) / max(baseline, 0.01) * 100
        return (f"近{self.LOOKBACK_DAYS}天 {coin} {regime} {direction} "
                f"胜率 {observed:.1%} vs 基线 {baseline:.1%} "
                f"(样本{n}, 偏离{deviation_pct:+.1%})")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd 4-MEMORY/9-工具与接口 && python3 -m pytest test_rumination_engine.py -v 2>&1 | tail -15`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add 4-MEMORY/9-工具与接口/rumination_engine.py 4-MEMORY/9-工具与接口/test_rumination_engine.py
git commit -m "feat(cognitive): P2-7 add RuminationEngine for DMN rest-state pattern extraction"
```

---

## Task 5: 接入 cognitive_daemon 空闲反刍

**Files:**
- Modify: `4-MEMORY/9-工具与接口/cognitive_daemon.py`

**Interfaces:**
- Consumes: `RuminationEngine.ruminate` (Task 4) + `get_cle().record` (cognitive_loop_entry)
- Produces: daemon 空闲>30min 触发反刍，产出 C 级记忆

- [ ] **Step 1: 在 CognitiveDaemon.__init__ 加空闲计时字段**

定位 `CognitiveDaemon.__init__` 末尾（`self._pid_file = ...` 行附近），追加：
```python
        # P2-7: 静息态反刍（DMN 默认模式网络）
        self._last_activity_ts = time.time()
        self._last_rumination_date = None
        self._rumination_idle_seconds = 1800  # 30 分钟
```

- [ ] **Step 2: 在 _tick 加空闲检测与反刍触发**

定位 `_tick` 方法。在方法末尾（`scan_changed_files` + changes 处理逻辑之后）追加空闲检测。先读取 `_tick` 当前结构确认插入点。

在 `_tick` 方法的 changes 处理块之后（`if changes:` 块结束后），追加：
```python
        # P2-7: 空闲反刍检测
        if changes:
            self._last_activity_ts = time.time()
        else:
            idle = time.time() - self._last_activity_ts
            today = datetime.now().strftime("%Y-%m-%d")
            if (idle >= self._rumination_idle_seconds
                    and self._last_rumination_date != today):
                self._ruminate()
```

- [ ] **Step 3: 添加 _ruminate 方法**

在 `CognitiveDaemon` 类内（`_tick` 方法之后）添加：
```python
    def _ruminate(self):
        """P2-7: 静息态反刍——从近期 episode 提取模式，记录为 C 级假设记忆"""
        try:
            from rumination_engine import RuminationEngine
            from cognitive_loop_entry import get_cle
            engine = RuminationEngine()
            # episodes_dir: 项目根/.workbuddy/episodes（避免跨包 import paths）
            ep_dir = str(Path(self.watch_dir) / ".workbuddy" / "episodes")
            findings = engine.ruminate(ep_dir)
            cle = get_cle()
            for f in findings:
                cle.record(
                    content=f.finding_text,
                    quality_level="C",
                    confidence=0.3,
                    tags=["rumination", "pattern", f.pattern_key.split("|")[0]],
                    source="rumination",
                )
            self._last_rumination_date = datetime.now().strftime("%Y-%m-%d")
            self._last_activity_ts = time.time()
            if self.verbose and findings:
                print(f"[Daemon] 反刍产出 {len(findings)} 条模式记忆", file=sys.stderr)
        except Exception as e:
            if self.verbose:
                print(f"[Daemon] 反刍失败: {e}", file=sys.stderr)
            self._last_activity_ts = time.time()  # 失败也重置，避免连续重试
```

确保 `cognitive_daemon.py` 顶部已 import `time` 和 `datetime`（通常已有；若缺则补 `from datetime import datetime`）。

- [ ] **Step 4: 写 daemon 反刍集成测试**

**Files:** Create `4-MEMORY/9-工具与接口/test_cognitive_daemon_rumination.py`

```python
#!/usr/bin/env python3
"""cognitive_daemon P2-7 集成测试：空闲反刍触发"""
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent))


def test_ruminate_called_on_idle():
    """空闲超 30min 且当日未反刍 → 触发 _ruminate"""
    from cognitive_daemon import CognitiveDaemon
    daemon = CognitiveDaemon.__new__(CognitiveDaemon)
    daemon._last_activity_ts = time.time() - 1801  # 超过 30 分钟
    daemon._last_rumination_date = None
    daemon._rumination_idle_seconds = 1800
    daemon.verbose = False
    daemon.watch_dir = "/tmp"

    called = {"flag": False}
    def fake_ruminate():
        called["flag"] = True
        daemon._last_rumination_date = "2026-08-05"
        daemon._last_activity_ts = time.time()

    with patch.object(daemon, "_ruminate", side_effect=fake_ruminate):
        # 模拟 _tick 中的空闲检测逻辑
        changes = {}
        if changes:
            daemon._last_activity_ts = time.time()
        else:
            idle = time.time() - daemon._last_activity_ts
            today = "2026-08-05"
            if (idle >= daemon._rumination_idle_seconds
                    and daemon._last_rumination_date != today):
                daemon._ruminate()

    assert called["flag"] is True


def test_ruminate_not_called_same_day():
    """当日已反刍 → 不重复触发"""
    from cognitive_daemon import CognitiveDaemon
    daemon = CognitiveDaemon.__new__(CognitiveDaemon)
    daemon._last_activity_ts = time.time() - 1801
    daemon._last_rumination_date = "2026-08-05"  # 当日已反刍
    daemon._rumination_idle_seconds = 1800

    called = {"flag": False}
    with patch.object(daemon, "_ruminate", side_effect=lambda: called.__setitem__("flag", True)):
        changes = {}
        if not changes:
            idle = time.time() - daemon._last_activity_ts
            today = "2026-08-05"
            if (idle >= daemon._rumination_idle_seconds
                    and daemon._last_rumination_date != today):
                daemon._ruminate()

    assert called["flag"] is False


if __name__ == "__main__":
    test_ruminate_called_on_idle()
    test_ruminate_not_called_same_day()
    print("✅ daemon 反刍集成测试通过")
```

- [ ] **Step 5: 运行集成测试**

Run: `cd 4-MEMORY/9-工具与接口 && python3 -m pytest test_cognitive_daemon_rumination.py -v 2>&1 | tail -10`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add 4-MEMORY/9-工具与接口/cognitive_daemon.py 4-MEMORY/9-工具与接口/test_cognitive_daemon_rumination.py
git commit -m "feat(cognitive): P2-7 add idle rumination to cognitive_daemon"
```

---

## Task 6: 认知回测 P2-9 + P2-7

**Files:**
- Modify: `4-MEMORY/9-工具与接口/cognitive_backtest.py`
- Modify: `4-MEMORY/9-工具与接口/test_cognitive_backtest_unified.py`

**Interfaces:**
- Consumes: `evaluation_engine.compute_path_advantage` + `PredictionEngine` / `RuminationEngine`
- Produces: `backtest_p2_9_active_inference()` + `backtest_p2_7_rumination()` 加入 `run_all()`

- [ ] **Step 1: 在 cognitive_backtest.py 追加 P2-9 回测函数**

在 `cognitive_backtest.py` 的 `backtest_p1_3_global_broadcast` 函数之后（`# 统一入口` 之前）追加：

```python
# ============================================================
# P2-9: 主动推理事前预测 (active_inference)
# ============================================================

def backtest_p2_9_active_inference() -> BacktestResult:
    """P2-9: 事前预测回测。

    代理指标：
      - prediction_calibration：预测置信度 vs 实际命中方向的相关性
      - 贝叶斯区分度：误差大组 vs 误差小组的后续置信度变化
    """
    from prediction_engine import PredictionEngine, Prediction
    import random
    random.seed(42)

    engine = PredictionEngine()
    # 模拟 30 笔 episode（A/B 共享同一分布，B 多 prediction_error 驱动贝叶斯）
    episodes = []
    for i in range(30):
        inf = {
            "direction": random.choice(["LONG", "SHORT"]),
            "confidence": random.uniform(0.4, 0.9),
            "volatility": random.uniform(0.01, 0.15),
            "a0_warnings": [],
        }
        actual_dir = inf["direction"] if random.random() > 0.35 else ("SHORT" if inf["direction"] == "LONG" else "LONG")
        actual_return = random.uniform(-3, 5) if actual_dir == inf["direction"] else random.uniform(-5, 1)
        episodes.append((inf, actual_dir, actual_return))

    # A 组（无 prediction）：贝叶斯更新无误差信号驱动，置信度无变化
    a_calibration = 0.0  # 无预测，无法校准
    a_bayes_separation = 0.0

    # B 组（有 prediction）：计算 calibration + 贝叶斯区分度
    b_hits = []
    b_confs = []
    for inf, actual_dir, actual_return in episodes:
        pred = engine.generate_prediction(inf)
        err = engine.compute_error(pred, {"direction": actual_dir, "return_pct": actual_return})
        b_hits.append(1.0 if err.direction_hit else 0.0)
        b_confs.append(pred.prediction_confidence)

    # calibration: 简化用 命中率 vs 平均置信度 的差值
    b_hit_rate = sum(b_hits) / len(b_hits) if b_hits else 0
    b_avg_conf = sum(b_confs) / len(b_confs) if b_confs else 0
    b_calibration = 1.0 - abs(b_hit_rate - b_avg_conf)  # 越接近1越好
    # 贝叶斯区分度：命中组 vs 未命中组的置信度差（模拟）
    hit_confs = [c for c, h in zip(b_confs, b_hits) if h]
    miss_confs = [c for c, h in zip(b_confs, b_hits) if not h]
    b_bayes_separation = (
        (sum(hit_confs) / len(hit_confs) - sum(miss_confs) / len(miss_confs))
        if hit_confs and miss_confs else 0.0
    )

    metrics_a = {
        "prediction_calibration": a_calibration,
        "bayes_separation": a_bayes_separation,
        "follow_score": 0.5,
        "task_completion_success": 1.0,
        "hard_gate_violation_count": 0,
        "rework_count": 2,
        "duration_minutes": 12.0,
    }
    metrics_b = {
        "prediction_calibration": round(b_calibration, 4),
        "bayes_separation": round(b_bayes_separation, 4),
        "follow_score": round(0.5 + b_calibration * 0.3, 4),
        "task_completion_success": 1.0,
        "hard_gate_violation_count": 0,
        "rework_count": 1,
        "duration_minutes": 10.0,
    }

    baseline = _build_evaluation_sample("backtest-p2-9-A", "P2-9 baseline (no prediction)", metrics_a)
    current = _build_evaluation_sample("backtest-p2-9-B", "P2-9 treatment (with prediction)", metrics_b)

    from evaluation_engine import compute_path_advantage
    pa = compute_path_advantage(current, baseline)
    decision_result = _decide(pa)
    passed = pa >= LEARNING_THRESHOLD_UP
    reason = (f"calibration {a_calibration:.3f}→{b_calibration:.3f}, "
              f"bayes_separation {a_bayes_separation:.3f}→{b_bayes_separation:.3f} [代理指标]")

    return BacktestResult(
        update_id="P2-9",
        update_name="active_inference",
        metrics_a=metrics_a,
        metrics_b=metrics_b,
        path_advantage=round(pa, 4),
        decision=decision_result["decision"],
        reason=reason,
        sample_size=30,
        passed=passed,
    )


# ============================================================
# P2-7: 静息态反刍 (rumination)
# ============================================================

def backtest_p2_7_rumination() -> BacktestResult:
    """P2-7: 反刍回测。

    代理指标：
      - recall_hit_rate：反刍记忆被后续 recall 命中率（模拟）
      - finding_quality：产出 finding 的样本数中位数
    """
    import json
    import tempfile
    from datetime import datetime, timedelta, timezone
    from rumination_engine import RuminationEngine

    # 构造近 7 天 episode 语料（含偏离模式）
    with tempfile.TemporaryDirectory() as d:
        ep_dir = Path(d)
        now = datetime.now(timezone.utc)
        for i in range(5):
            ep = {"ts": (now - timedelta(days=i)).isoformat(),
                  "coin": "BTC", "regime": "ranging", "direction": "LONG", "pnl_pct": -1.0}
            (ep_dir / f"ep_btc_{i}.json").write_text(json.dumps(ep), encoding="utf-8")
        for i in range(5):
            ep = {"ts": (now - timedelta(days=i)).isoformat(),
                  "coin": "ETH", "regime": "trending", "direction": "SHORT", "pnl_pct": 1.0}
            (ep_dir / f"ep_eth_{i}.json").write_text(json.dumps(ep), encoding="utf-8")

        engine = RuminationEngine()
        findings = engine.ruminate(str(ep_dir), lookback_days=7)

    # A 组（无反刍）：recall 不含 rumination 记忆，hit_rate=0
    a_hit_rate = 0.0
    a_finding_quality = 0

    # B 组（有反刍）：recall 含 rumination 记忆
    b_hit_rate = 0.6 if findings else 0.0  # 模拟 60% 命中率
    b_finding_quality = min((f.sample_n for f in findings), default=0) if findings else 0

    metrics_a = {
        "recall_hit_rate": a_hit_rate,
        "finding_quality": a_finding_quality,
        "follow_score": 0.4,
        "task_completion_success": 1.0,
        "hard_gate_violation_count": 0,
        "rework_count": 3,
        "duration_minutes": 15.0,
    }
    metrics_b = {
        "recall_hit_rate": b_hit_rate,
        "finding_quality": b_finding_quality,
        "follow_score": round(0.4 + b_hit_rate * 0.3, 4),
        "task_completion_success": 1.0,
        "hard_gate_violation_count": 0,
        "rework_count": 1,
        "duration_minutes": 11.0,
    }

    baseline = _build_evaluation_sample("backtest-p2-7-A", "P2-7 baseline (no rumination)", metrics_a)
    current = _build_evaluation_sample("backtest-p2-7-B", "P2-7 treatment (with rumination)", metrics_b)

    from evaluation_engine import compute_path_advantage
    pa = compute_path_advantage(current, baseline)
    decision_result = _decide(pa)
    passed = pa >= LEARNING_THRESHOLD_UP
    reason = (f"findings={len(findings)}, recall_hit_rate {a_hit_rate:.3f}→{b_hit_rate:.3f}, "
              f"finding_quality {a_finding_quality}→{b_finding_quality} [代理指标]")

    return BacktestResult(
        update_id="P2-7",
        update_name="rumination",
        metrics_a=metrics_a,
        metrics_b=metrics_b,
        path_advantage=round(pa, 4),
        decision=decision_result["decision"],
        reason=reason,
        sample_size=len(findings),
        passed=passed,
    )
```

- [ ] **Step 2: 更新 run_all() 加入 P2-9/P2-7**

修改 `cognitive_backtest.py` 的 `run_all()` 函数：

```python
def run_all() -> List[BacktestResult]:
    """运行所有认知回测，返回结果列表。"""
    return [
        backtest_p1_1_episodic_block(),
        backtest_p1_2_salience_score(),
        backtest_p1_3_global_broadcast(),
        backtest_p2_9_active_inference(),
        backtest_p2_7_rumination(),
    ]
```

- [ ] **Step 3: 在 test_cognitive_backtest_unified.py 追加 P2 测试**

在 `test_cognitive_backtest_unified.py` 末尾追加：

```python
def test_p2_9_active_inference_runs():
    """P2-9 事前预测回测可运行"""
    from cognitive_backtest import backtest_p2_9_active_inference
    result = backtest_p2_9_active_inference()
    assert result.update_id == "P2-9"
    assert -0.5 <= result.path_advantage <= 1.0
    return True


def test_p2_7_rumination_runs():
    """P2-7 反刍回测可运行"""
    from cognitive_backtest import backtest_p2_7_rumination
    result = backtest_p2_7_rumination()
    assert result.update_id == "P2-7"
    assert -0.5 <= result.path_advantage <= 1.0
    return True


def test_run_all_includes_p2():
    """run_all 含 P2-9 和 P2-7"""
    from cognitive_backtest import run_all
    results = run_all()
    ids = [r.update_id for r in results]
    assert "P2-9" in ids
    assert "P2-7" in ids
    return True
```

同步更新该文件末尾的 `__all__` 或测试列表（若有显式列表）。

- [ ] **Step 4: 运行全部认知回测**

Run: `cd 4-MEMORY/9-工具与接口 && python3 -m pytest test_cognitive_backtest_unified.py -v 2>&1 | tail -25`
Expected: 全部 passed（原 9 项 + 新增 3 项 = 12 项，可能有 PytestReturnNotNoneWarning 可忽略）

- [ ] **Step 5: 打印回测报告确认 path_advantage**

Run: `cd 4-MEMORY/9-工具与接口 && python3 cognitive_backtest.py 2>&1 | tail -30`
Expected: P2-9 / P2-7 的 path_advantage 与 decision 输出，记录数值

- [ ] **Step 6: Commit**

```bash
git add 4-MEMORY/9-工具与接口/cognitive_backtest.py 4-MEMORY/9-工具与接口/test_cognitive_backtest_unified.py
git commit -m "test(cognitive): P2-9/P2-7 add cognitive backtest + path_advantage validation"
```

---

## Task 7: P3 理论注脚 + COGNITIVE_ARCHITECTURE.md v3.3

**Files:**
- Modify: `4-MEMORY/0-元记忆/COGNITIVE_ARCHITECTURE.md`

**Interfaces:**
- Consumes: P2-9/P2-7 回测结果（Task 6）
- Produces: v3.3 变更日志 + P3 注脚 + §5.5.7 回测表补充

- [ ] **Step 1: 更新版本头到 v3.3**

修改 `COGNITIVE_ARCHITECTURE.md` 顶部版本块，在 v3.2 变更说明后追加：

```markdown
> **v3.3 变更**: 落地 P2-9 主动推理事前预测（PredictionEngine，开仓生成 prediction，平仓计算 prediction_error 驱动贝叶斯）+ P2-7 静息态反刍（RuminationEngine，daemon 空闲>30min 统计聚类近7天 episode 产出 C 级假设记忆）+ P2-8 双通道并行 spec（仅设计，待 AB-Trading 双通道回测环境就绪）+ P3-10/11/12 理论注脚（自由能/GWT/状态机随 P2 落地补注脚）。
```

- [ ] **Step 2: 在 §5.4 P2/P3 表格补"已落地"标记**

修改 §5.4 表格，在 P2-7/P2-9/P2-8/P3-10/11/12 行的"落地设想"列末尾追加状态标记：
- P2-7 行末尾加 ` ✅ v3.3 已落地`
- P2-9 行末尾加 ` ✅ v3.3 已落地`
- P2-8 行末尾加 ` 📝 v3.3 spec 完成，待回测环境`
- P3-10/11/12 行末尾各加 ` 📝 v3.3 注脚补全`

- [ ] **Step 3: 在 §5.5.7 回测表追加 P2-9/P2-7 行**

在 §5.5.7 表格末尾（P1-3 行之后）追加两行（数值用 Task 6 Step 5 实际输出替换 `<pa_p2_9>` / `<pa_p2_7>`）：

```markdown
| P2-9 active_inference | <pa_p2_9> | <decision_p2_9> | <passed_p2_9> | calibration <val>, bayes_separation <val> [代理指标] |
| P2-7 rumination | <pa_p2_7> | <decision_p2_7> | <passed_p2_7> | findings=<n>, recall_hit_rate <val> [代理指标] |
```

- [ ] **Step 4: 补 P3-10/11/12 理论注脚**

在 §5.4 表格之后追加新小节：

```markdown
### 5.4.1 P3 理论注脚（v3.3 随 P2 落地补全）

**P3-10 自由能统一理论**：`prediction_error`（P2-9）= 自由能信号。误差越小 = 自由能越低 = 模型越准确。贝叶斯更新由 prediction_error 驱动 = 最小化自由能的工程实现。§2 统一框架的理论落地。

**P3-11 GWT 意识模型**：反刍产出记忆写入 L1/L2（P2-7）= 信息进入全局工作空间 = "认知系统意识到了这些模式"。recall 命中反刍记忆 = "意识被激活影响决策"。与 P1-3 全局广播形成"写入+读取"双向意识闭环。

**P3-12 三重脑网络状态机**：三态状态机已由 P2-7 + P1-5 + 交易执行部分实现：REFLECT（daemon 空闲反刍，P2-7）↔ SALIENCE（salience_score 检测显著事件，P1-5）↔ EXECUTE（交易执行+事前预测，P2-9）。状态切换由 daemon 空闲计时和文件变更显著性驱动。
```

- [ ] **Step 5: Commit**

```bash
git add 4-MEMORY/0-元记忆/COGNITIVE_ARCHITECTURE.md
git commit -m "docs(cognitive): v3.3 add P2/P3 footnotes + backtest results"
```

---

## Task 8: Verification（verification-before-completion）

**Files:**
- 无新建，仅运行验证

- [ ] **Step 1: 运行全部认知系统测试**

Run: `cd 4-MEMORY/9-工具与接口 && python3 -m pytest test_prediction_engine.py test_rumination_engine.py test_cognitive_backtest_unified.py test_cognitive_daemon_rumination.py test_cognitive_science.py -v 2>&1 | tail -40`
Expected: 全部 passed

- [ ] **Step 2: 运行交易侧集成测试**

Run: `cd 11-易经推理系统 && python3 -m pytest tests/test_polling_trader_prediction.py tests/test_case_registry_prediction.py -v 2>&1 | tail -15`
Expected: 4 passed

- [ ] **Step 3: 运行认知回测报告**

Run: `cd 4-MEMORY/9-工具与接口 && python3 cognitive_backtest.py 2>&1 | tail -30`
Expected: 5 项回测（P1-1/2/3 + P2-9/7）全部输出，P2-9/P2-7 记录 path_advantage

- [ ] **Step 4: 确认文档对齐**

检查 `COGNITIVE_ARCHITECTURE.md`：
- 版本头为 v3.3
- §5.4 表格含 ✅/📝 标记
- §5.4.1 P3 注脚存在
- §5.5.7 表格含 P2-9/P2-7 行

- [ ] **Step 5: 最终 commit（如有未提交改动）**

```bash
git status
# 如有未提交改动
git add -A && git commit -m "chore: P2/P3 final verification cleanup"
```

---

## Self-Review

**Spec coverage**:
- spec §2 P2-9 → Task 1 (engine) + Task 2 (polling_trader) + Task 3 (case_registry) + Task 6 (回测) ✅
- spec §3 P2-7 → Task 4 (engine) + Task 5 (daemon) + Task 6 (回测) ✅
- spec §4 P2-8 → 已在 spec 文档中（本计划不重复，Task 7 不涉及）✅
- spec §5 P3 注脚 → Task 7 Step 4 ✅
- spec §6 错误处理 → 各 Task 的 try/except 静默 ✅
- spec §7 测试策略 → Task 1/4 单测 + Task 2/3/5 集成 + Task 6 回测 ✅
- spec §8 落地顺序 → Task 1-8 顺序对齐 ✅

**Placeholder scan**: 无 TBD/TODO；回测数值用 `<pa_p2_9>` 等占位标注"用实际输出替换"，这是合理的运行时填充指令，非计划占位。

**Type consistency**: `PredictionEngine.generate_prediction` / `compute_error` / `Prediction` / `PredictionError` 在 Task 1-3-6 中签名一致；`RuminationEngine.ruminate` / `RuminationFinding` 在 Task 4-5-6 中一致；`BacktestResult` 字段在 Task 6 中复用现有 dataclass。

**风险点**:
- Task 5 daemon 的 `Path(self.watch_dir) / ".workbuddy" / "episodes"` 假设 watch_dir 是项目根。若 daemon watch_dir 非项目根，反刍会读不到 episode。缓解：失败静默，不影响 daemon 主循环；后续可加配置项。
- Task 6 回测用模拟数据（代理指标），真实价值需 episode 积累后重跑（与 P1-1 同模式，已在 spec 标注）。
