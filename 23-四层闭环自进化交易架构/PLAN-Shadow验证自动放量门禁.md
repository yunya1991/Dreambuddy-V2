# Shadow 验证自动放量门禁 Implementation Plan

> **For agentic workers:** 按 task 逐条执行，步骤用 `- [ ]` 跟踪。对应 SPEC：[SPEC-Shadow验证自动放量门禁.md](./SPEC-Shadow验证自动放量门禁.md) v1.0。

**Goal:** 目标开关（`enable_causal_historical_samples`）在影子期（False）每日评估 A2 门禁态；满足「≥7 个自然日且出现过态A」→ 自动 `set_switch(True)` 放量，重启可恢复、一键可回滚。

**Architecture:** 门禁状态唯一入口 `ShadowActivationGate`（O(1) 读文件、无 DML）；证据产出 `evaluate_and_record`（含 DML）跑在独立子进程（`scripts/shadow_ate_eval.py`）；主链路只在 `EvolutionPipeline.__init__` 做 reconcile、在 `PrimaryContradictionIdentifier.identify()` 头部做 O(1) `maybe_activate`。

**Tech Stack:** Python 3 / pytest / 既有 `agi_config.get_switch/set_switch`、`CausalSampleStore.build_ate_samples`、`CausalEngine.estimate_ate`、`classify_ate_state`、`subprocess` 隔离、原子写（tempfile + os.replace）。

## Global Constraints

- HC-AGI-02：任何异常 → 中性兜底，**不抛**（FAIL-OPEN）。
- HC-AGI-07：新模块默认关 / **满足条件才放量**；`enable_causal_historical_samples` 默认值保持 `False`（不得改）。
- HC-AGI-08：`min_n = 500`，**不得下调**。
- 门禁总开关 `enable_shadow_auto_activation` 默认 **True**（治理设施，本身不改交易行为）。
- 主链路零 DML：`ShadowActivationGate` 不 import evaluator / causal 相关模块；spawn 用脚本文本。
- 测试路径：`dreambuddy_evolution/tests/`；`tests/conftest.py` 有 autouse `_reset_agi_switches`（自动恢复开关，测试可自由 `set_switch`）。
- **测试绝不起真实评估子进程**（DML≈35s）：统一 monkeypatch `ShadowActivationGate._spawn_evaluator`。

## File Structure

| 文件 | 责任 |
|------|------|
| `dreambuddy_evolution/core/shadow_activation_gate.py`（新建） | 状态唯一入口：`record/evaluate/maybe_activate/reconcile_from_disk/is_activated`，原子写、FAIL-OPEN、无 DML |
| `dreambuddy_evolution/core/shadow_ate_evaluator.py`（新建） | 产出当日证据（含 DML）：`evaluate_and_record(gate, switch_name=None)` |
| `dreambuddy_evolution/scripts/shadow_ate_eval.py`（新建） | 子进程入口：`--switch <name>` |
| `dreambuddy_evolution/agi_config.py`（改） | 新增 `enable_shadow_auto_activation=True` |
| `dreambuddy_evolution/evolution_pipeline.py`（改） | `__init__` → `gate.reconcile_from_disk()` |
| `dreambuddy_evolution/core/contradiction_identifier.py`（改） | `identify()` 头部 → `gate.maybe_activate()` |
| `dreambuddy_evolution/tests/test_shadow_activation_gate.py`（新建） | #1-#12 + spawn 正/反向 |
| `dreambuddy_evolution/tests/test_shadow_ate_evaluator.py`（新建） | #13-#14 |

---

### Task 1: 门禁状态唯一入口 `ShadowActivationGate`

**Files:**
- Create: `dreambuddy_evolution/core/shadow_activation_gate.py`
- Test: `dreambuddy_evolution/tests/test_shadow_activation_gate.py`

**Interfaces (Produces):**
- `ShadowActivationGate(switch_name, state_dir=None, min_days=7, min_n=500, eval_script=None, spawn_timeout=300)`
- `record(obs: dict) -> bool`（obs 含 `date, gate_state, ate, lb, ub, source, n, method`；仅当 `method ∉ {insufficient_samples,error}` 且 `n>=min_n` 才写入；同 date 保留最后一条；持久化时**剥离 method**）
- `evaluate() -> {"eligible": bool, "valid_days": int, "has_positive": bool, "min_days": int}`
- `maybe_activate() -> bool`；`reconcile_from_disk() -> bool`；`is_activated() -> bool`
- `today_has_valid_obs() -> bool`；`last_eval_attempt_date() -> str|None`
- 状态文件：`<state_dir>/<switch>.json`，默认为 `dreambuddy_evolution/data/shadow_activation/`

- [ ] **Step 1: 写失败测试**（下方 Task 2 的测试文件；此处先建最小 RED 断言 #12 默认值）

```python
# tests/test_shadow_activation_gate.py
from __future__ import annotations

import json
from datetime import date

import pytest

SWITCH = "enable_causal_historical_samples"
GATE_SWITCH = "enable_shadow_auto_activation"


@pytest.fixture(autouse=True)
def _no_real_spawn(monkeypatch):
    """禁止测试起真实评估子进程（DML≈35s）；返回调用计数 spy。"""
    from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
    calls = {"n": 0}

    def _fake(self):
        calls["n"] += 1
        return True

    monkeypatch.setattr(ShadowActivationGate, "_spawn_evaluator", _fake, raising=True)
    return calls


def _gate(tmp_path, switch=SWITCH):
    from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
    return ShadowActivationGate(switch, state_dir=tmp_path)


def _obs(date_s, gate_state="B", n=1000, method="causalml_dml",
         ate=0.0, lb=-0.01, ub=0.01):
    return {"date": date_s, "gate_state": gate_state, "ate": ate, "lb": lb,
            "ub": ub, "source": "bootstrap", "n": n, "method": method}


def _seed_days(gate, days, gate_state="B"):
    for i in range(days):
        assert gate.record(_obs(f"2026-01-{i + 1:02d}", gate_state=gate_state))


def test_defaults():
    from dreambuddy_evolution.agi_config import AGI_SWITCHES
    assert AGI_SWITCHES["enable_causal_historical_samples"] is False
    assert AGI_SWITCHES["enable_shadow_auto_activation"] is True
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest dreambuddy_evolution/tests/test_shadow_activation_gate.py -q`
Expected: FAIL（`ImportError: ... shadow_activation_gate`）

- [ ] **Step 3: 写最小实现** `dreambuddy_evolution/core/shadow_activation_gate.py`

```python
"""
Shadow 激活门禁 — Shadow 验证 ≥7 天且出现态A → 自动放量
SPEC-Shadow验证自动放量门禁.md §3-§9

设计要点：
  - 状态唯一入口，O(1) 读文件，无 DML（DML 在 evaluator 子进程）
  - 原子写（tempfile + os.replace）；损坏/缺失 → 空状态（FAIL-OPEN，不激活）
  - 维一入口 maybe_activate: 惰性每日 spawn evaluator + 满足条件 set_switch(True)
  - reconcile_from_disk: 启动恢复（activated_at 已存在 → 放量），补齐 set_switch 不落盘缺口
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# core/ → dreambuddy_evolution/ → 23-四层闭环自进化交易架构/
_MODULE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = _MODULE_DIR / "data" / "shadow_activation"
DEFAULT_EVAL_SCRIPT = _MODULE_DIR / "scripts" / "shadow_ate_eval.py"

_GATE_SWITCH = "enable_shadow_auto_activation"
_VALID_METHODS_EXCLUDED = ("insufficient_samples", "error")


class ShadowActivationGate:
    """目标开关的 Shadow 自动放量门禁（状态唯一入口，O(1)，无 DML）."""

    def __init__(
        self,
        switch_name: str,
        state_dir: str | Path | None = None,
        min_days: int = 7,
        min_n: int = 500,
        eval_script: str | Path | None = None,
        spawn_timeout: int = 300,
    ) -> None:
        self.switch_name = switch_name
        self.min_days = int(min_days)
        self.min_n = int(min_n)  # HC-AGI-08: 500，不得下调
        self._state_dir = Path(state_dir) if state_dir else DEFAULT_STATE_DIR
        self._state_path = self._state_dir / f"{switch_name}.json"
        self._eval_script = Path(eval_script) if eval_script else DEFAULT_EVAL_SCRIPT
        self._spawn_timeout = int(spawn_timeout)
        self._cache: tuple[float, dict] | None = None

    # ---------------------------------------------------------------- 时间
    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    # ---------------------------------------------------------------- 状态
    def _empty_state(self) -> dict:
        return {
            "switch": self.switch_name,
            "shadow_started_at": self._now_iso(),
            "min_days": self.min_days,
            "min_n": self.min_n,
            "last_eval_attempt_date": None,
            "activated_at": None,
            "observations": [],
        }

    def _load(self) -> dict:
        """读状态文件（mtime 缓存）；缺失/损坏 → 空状态（FAIL-OPEN）."""
        try:
            if not self._state_path.exists():
                return self._empty_state()
            mtime = self._state_path.stat().st_mtime
            if self._cache is not None and self._cache[0] == mtime:
                return self._cache[1]
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("state root is not dict")
            data.setdefault("observations", [])
            data.setdefault("activated_at", None)
            data.setdefault("last_eval_attempt_date", None)
            self._cache = (mtime, data)
            return data
        except Exception as e:  # noqa: BLE001  HC-AGI-02
            logger.debug("[FO] shadow gate load: %s", e)
            return self._empty_state()

    def _save(self, state: dict) -> None:
        """原子写（tempfile 同目录 + os.replace，FAIL-OPEN）."""
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self._state_dir), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._state_path)
            self._cache = None
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO] shadow gate save: %s", e)

    def _invalidate_cache(self) -> None:
        self._cache = None

    # ---------------------------------------------------------------- 证据
    def is_valid_observation(self, obs: dict | None) -> bool:
        """有效观测：method ∉ {insufficient_samples, error} 且 n ≥ min_n."""
        try:
            if not isinstance(obs, dict):
                return False
            method = str(obs.get("method", ""))
            n = int(obs.get("n", 0))
            return method not in _VALID_METHODS_EXCLUDED and n >= self.min_n
        except Exception:  # noqa: BLE001
            return False

    def record(self, obs: dict) -> bool:
        """写入一条观测（无效 → 不落库；同 date 保留最后一条）."""
        try:
            if not self.is_valid_observation(obs):
                return False
            state = self._load()
            persisted = {
                "date": str(obs.get("date") or self._today()),
                "gate_state": str(obs.get("gate_state", "C")),
                "ate": float(obs.get("ate", 0.0)),
                "lb": float(obs.get("lb", 0.0)),
                "ub": float(obs.get("ub", 0.0)),
                "source": str(obs.get("source", "")),
                "n": int(obs.get("n", 0)),
            }
            kept = [o for o in (state.get("observations") or [])
                    if str(o.get("date")) != persisted["date"]]
            kept.append(persisted)
            state["observations"] = kept
            state["switch"] = self.switch_name
            state.setdefault("min_days", self.min_days)
            state.setdefault("min_n", self.min_n)
            if not state.get("shadow_started_at"):
                state["shadow_started_at"] = self._now_iso()
            self._save(state)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO] shadow gate record: %s", e)
            return False

    def evaluate(self) -> dict:
        """O(1) 读状态算 eligible（无 DML）."""
        obs = self._load().get("observations") or []
        valid_days = len({str(o.get("date")) for o in obs})
        has_positive = any(str(o.get("gate_state")) == "A" for o in obs)
        return {
            "eligible": valid_days >= self.min_days and has_positive,
            "valid_days": valid_days,
            "has_positive": has_positive,
            "min_days": self.min_days,
        }

    def today_has_valid_obs(self) -> bool:
        t = self._today()
        return any(str(o.get("date")) == t
                   for o in (self._load().get("observations") or []))

    def last_eval_attempt_date(self) -> str | None:
        return self._load().get("last_eval_attempt_date")

    # ---------------------------------------------------------------- 放量
    def _mark_activated(self) -> None:
        state = self._load()
        state["activated_at"] = self._now_iso()
        if not state.get("shadow_started_at"):
            state["shadow_started_at"] = self._now_iso()
        self._save(state)

    def _mark_eval_attempt(self, date_s: str) -> None:
        state = self._load()
        state["last_eval_attempt_date"] = date_s
        self._save(state)

    def _spawn_evaluator(self) -> bool:
        """起独立评估子进程（隔离 DML）；失败返回 False（FAIL-OPEN）."""
        try:
            subprocess.run(
                [sys.executable, str(self._eval_script), "--switch", self.switch_name],
                timeout=self._spawn_timeout, check=False, capture_output=True,
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO] shadow gate spawn: %s", e)
            return False

    def maybe_activate(self) -> bool:
        """惰性每日评估 + 满足条件自动放量（O(1)；FAIL-OPEN）."""
        try:
            from dreambuddy_evolution.agi_config import get_switch, set_switch
        except Exception:  # noqa: BLE001
            return False
        try:
            if not get_switch(_GATE_SWITCH, False):
                return False
            if get_switch(self.switch_name, False):
                return False  # 已开（或已被外部开启）— 幂等
            state = self._load()
            if state.get("activated_at"):
                set_switch(self.switch_name, True)  # 状态已标记但开关未开 → 补齐
                return True
            today = self._today()
            if not self.today_has_valid_obs() and str(state.get("last_eval_attempt_date")) != today:
                self._mark_eval_attempt(today)  # 先落盘（失败也保留，避免反复起进程）
                self._spawn_evaluator()
                self._invalidate_cache()
            ev = self.evaluate()
            if ev["eligible"]:
                set_switch(self.switch_name, True)
                self._mark_activated()
                self._cognitive_record(ev)
                return True
            return False
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO] shadow gate maybe_activate: %s", e)
            return False

    def reconcile_from_disk(self) -> bool:
        """启动恢复：activated_at 已存在且开关未开 → 放量（FAIL-OPEN）."""
        try:
            from dreambuddy_evolution.agi_config import get_switch, set_switch
        except Exception:  # noqa: BLE001
            return False
        try:
            if not get_switch(_GATE_SWITCH, False):
                return False
            state = self._load()
            if state.get("activated_at") and not get_switch(self.switch_name, False):
                set_switch(self.switch_name, True)
                logger.info("[ShadowGate] reconcile: %s → True (activated_at=%s)",
                            self.switch_name, state.get("activated_at"))
                return True
            return False
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO] shadow gate reconcile: %s", e)
            return False

    def is_activated(self) -> bool:
        try:
            from dreambuddy_evolution.agi_config import get_switch
            return bool(get_switch(self.switch_name, False))
        except Exception:  # noqa: BLE001
            return False

    # ---------------------------------------------------------------- 认知
    def _cognitive_record(self, detail: dict) -> None:
        """自动放量事件 → 认知记忆（B 级，FAIL-OPEN，best-effort）."""
        try:
            from dreambuddy_evolution.adapters.cognitive_bridge import CognitiveBridge
            entry = CognitiveBridge()._get_entry()
            if entry is None:
                return
            entry.record(
                content=(
                    f"[Shadow自动放量] {self.switch_name}: valid_days="
                    f"{detail.get('valid_days')}, has_positive={detail.get('has_positive')}, "
                    f"min_days={self.min_days}, min_n={self.min_n}"
                ),
                quality_level="B",
                confidence=0.5,
                tags=["硬约束", "自进化", "治理", "自动放量", "Shadow验证"],
                source="shadow-activation-gate",
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO] shadow gate cognitive record: %s", e)
```

- [ ] **Step 4: 跑测试确认绿**

Run: `python -m pytest dreambuddy_evolution/tests/test_shadow_activation_gate.py -q`
Expected: PASS（当前仅 #12 默认值 + 可导入）

- [ ] **Step 5: Commit**

```bash
git add dreambuddy_evolution/core/shadow_activation_gate.py dreambuddy_evolution/tests/test_shadow_activation_gate.py
git commit -m "feat(evolution): ShadowActivationGate 状态入口（自动放量门禁 T1）"
```

---

### Task 2: 门禁全部用例 #1-#12 + spawn 正/反向

**Files:**
- Modify: `dreambuddy_evolution/tests/test_shadow_activation_gate.py`（在 Task 1 骨架后追加）

- [ ] **Step 1: 追加用例**（在文件末尾追加 `class TestShadowActivationGate:`）

```python
class TestShadowActivationGate:
    def test_1_insufficient_days_no_activation(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True); set_switch(SWITCH, False)
        g = _gate(tmp_path)
        _seed_days(g, 6, "A")
        assert g.maybe_activate() is False
        assert get_switch(SWITCH, False) is False

    def test_2_seven_days_no_positive_no_activation(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True); set_switch(SWITCH, False)
        g = _gate(tmp_path)
        _seed_days(g, 7, "B")
        assert g.maybe_activate() is False
        assert get_switch(SWITCH, False) is False

    def test_3_seven_days_with_positive_activates(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True); set_switch(SWITCH, False)
        g = _gate(tmp_path)
        _seed_days(g, 6, "B")
        assert g.record(_obs("2026-01-07", "A", ate=0.06, lb=0.03, ub=0.09))
        assert g.maybe_activate() is True
        assert get_switch(SWITCH, False) is True
        state = json.loads((tmp_path / f"{SWITCH}.json").read_text(encoding="utf-8"))
        assert state["activated_at"]

    def test_4_same_date_dedup(self, tmp_path):
        g = _gate(tmp_path)
        assert g.record(_obs("2026-01-01", "B"))
        assert g.record(_obs("2026-01-01", "A"))
        ev = g.evaluate()
        assert ev["valid_days"] == 1
        assert ev["has_positive"] is True

    def test_5_small_n_rejected(self, tmp_path):
        g = _gate(tmp_path)
        assert g.record(_obs("2026-01-01", "A", n=499)) is False
        assert g.evaluate()["valid_days"] == 0

    def test_6_invalid_method_rejected(self, tmp_path):
        g = _gate(tmp_path)
        assert g.record(_obs("2026-01-01", method="error")) is False
        assert g.record(_obs("2026-01-02", method="insufficient_samples")) is False
        assert g.evaluate()["valid_days"] == 0

    def test_7_reconcile_activates(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True); set_switch(SWITCH, False)
        state = {"switch": SWITCH, "activated_at": "2026-10-14T18:00:00+08:00",
                 "min_days": 7, "min_n": 500, "observations": []}
        (tmp_path / f"{SWITCH}.json").write_text(json.dumps(state), encoding="utf-8")
        g = _gate(tmp_path)
        assert g.reconcile_from_disk() is True
        assert get_switch(SWITCH, False) is True

    def test_8_corrupt_state_failopen(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True); set_switch(SWITCH, False)
        (tmp_path / f"{SWITCH}.json").write_text("{not json", encoding="utf-8")
        g = _gate(tmp_path)
        assert g.maybe_activate() is False
        assert get_switch(SWITCH, False) is False

    def test_9_gate_switch_off_no_spawn(self, tmp_path, _no_real_spawn):
        from dreambuddy_evolution.agi_config import set_switch
        set_switch(GATE_SWITCH, False); set_switch(SWITCH, False)
        g = _gate(tmp_path)
        assert g.maybe_activate() is False
        assert _no_real_spawn["n"] == 0

    def test_10_no_spawn_when_today_has_obs(self, tmp_path, _no_real_spawn):
        from dreambuddy_evolution.agi_config import set_switch
        set_switch(GATE_SWITCH, True); set_switch(SWITCH, False)
        g = _gate(tmp_path)
        assert g.record(_obs(date.today().isoformat(), "B"))
        g.maybe_activate()
        assert _no_real_spawn["n"] == 0

    def test_10b_spawns_once_when_no_obs_today(self, tmp_path, _no_real_spawn):
        from dreambuddy_evolution.agi_config import set_switch
        set_switch(GATE_SWITCH, True); set_switch(SWITCH, False)
        g = _gate(tmp_path)
        g.maybe_activate()
        assert _no_real_spawn["n"] == 1
        g.maybe_activate()  # last_eval_attempt_date 已是今天 → 不再 spawn
        assert _no_real_spawn["n"] == 1

    def test_11_target_already_on_idempotent(self, tmp_path):
        from dreambuddy_evolution.agi_config import set_switch
        set_switch(GATE_SWITCH, True); set_switch(SWITCH, True)
        g = _gate(tmp_path)
        _seed_days(g, 7, "A")
        assert g.maybe_activate() is False
```

- [ ] **Step 2: 跑测试确认全绿**

Run: `python -m pytest dreambuddy_evolution/tests/test_shadow_activation_gate.py -q`
Expected: PASS（13 项）

- [ ] **Step 3: Commit**

```bash
git add dreambuddy_evolution/tests/test_shadow_activation_gate.py
git commit -m "test(evolution): ShadowActivationGate #1-#12 + spawn 正/反向"
```

---

### Task 3: 评估器 `evaluate_and_record` + 子进程脚本 + 门禁总开关

**Files:**
- Create: `dreambuddy_evolution/core/shadow_ate_evaluator.py`
- Create: `dreambuddy_evolution/scripts/shadow_ate_eval.py`
- Modify: `dreambuddy_evolution/agi_config.py`（新增开关）
- Test: `dreambuddy_evolution/tests/test_shadow_ate_evaluator.py`

**Interfaces (Consumes):** `ShadowActivationGate`（Task 1）；`CausalSampleStore.build_ate_samples()`；`CausalEngine.estimate_ate(X,treatment,y,method="dml")`；`classify_ate_state(result, tau)`。

- [ ] **Step 1: 写失败测试** `tests/test_shadow_ate_evaluator.py`

```python
"""
Shadow ATE 评估器 TDD 测试（RED）
SPEC-Shadow验证自动放量门禁.md §10 #13-#14
"""
from __future__ import annotations

import numpy as np
import pytest


class _FakeStore:
    def build_ate_samples(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(800, 2))
        treatment = (X[:, 0] > 0).astype(np.int32)
        y = 0.08 * treatment + rng.normal(scale=0.1, size=800)
        return {"X": X, "treatment": treatment, "y": y, "source": "bootstrap"}


class _EmptyStore:
    def build_ate_samples(self):
        return None


class _FakeEngine:
    def __init__(self, *a, **k):
        pass

    def estimate_ate(self, X, treatment, y, method="dml"):
        return {"ate": 0.08, "lower_bound": 0.03, "upper_bound": 0.13,
                "method": "causalml_dml", "ci_method": "block_bootstrap",
                "significant": True}


def _gate(tmp_path):
    from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
    return ShadowActivationGate("enable_causal_historical_samples", state_dir=tmp_path)


def test_13_evaluator_records_state_a(tmp_path, monkeypatch):
    from dreambuddy_evolution.core import causal_sample_store as css
    from dreambuddy_evolution.core import causal_engine as ce
    from dreambuddy_evolution.core import shadow_ate_evaluator as ev
    monkeypatch.setattr(css, "CausalSampleStore", lambda *a, **k: _FakeStore())
    monkeypatch.setattr(ce, "CausalEngine", _FakeEngine)
    obs = ev.evaluate_and_record(_gate(tmp_path))
    assert obs is not None
    assert obs["gate_state"] == "A"
    assert obs["n"] == 800


def test_14_evaluator_no_obs_when_no_samples(tmp_path, monkeypatch):
    from dreambuddy_evolution.core import causal_sample_store as css
    from dreambuddy_evolution.core import shadow_ate_evaluator as ev
    monkeypatch.setattr(css, "CausalSampleStore", lambda *a, **k: _EmptyStore())
    assert ev.evaluate_and_record(_gate(tmp_path)) is None


def test_script_module_importable():
    import dreambuddy_evolution.scripts.shadow_ate_eval as s
    assert callable(s.main)
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest dreambuddy_evolution/tests/test_shadow_ate_evaluator.py -q`
Expected: FAIL（`ModuleNotFoundError: shadow_ate_evaluator`）

- [ ] **Step 3: 实现评估器 + 脚本 + 改 agi_config**

`dreambuddy_evolution/core/shadow_ate_evaluator.py`：

```python
"""
Shadow ATE 评估器（含 DML）— 影子期每日产出 A2 门禁态证据
SPEC-Shadow验证自动放量门禁.md §3-§5

仅由子进程 scripts/shadow_ate_eval.py 调用；FAIL-OPEN：任何异常 → None，不抛。
注意：本模块 import DML 相关（causal），**不得**被门禁主链路 import。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def evaluate_and_record(gate, switch_name: str | None = None) -> dict | None:
    """评估目标开关当日 A2 门禁态并写入 gate 状态文件.

    Returns: 观测 dict（已 record 成功）或 None（无有效观测）。FAIL-OPEN。
    """
    try:
        from dreambuddy_evolution.core.causal_sample_store import CausalSampleStore
        from dreambuddy_evolution.core.causal_engine import CausalEngine
        from dreambuddy_evolution.core.contradiction_identifier import (
            SESOI_TAU_DEFAULT, classify_ate_state,
        )
        from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
        from dreambuddy_evolution.agi_config import get_switch

        name = switch_name or getattr(gate, "switch_name", None)
        g = gate if gate is not None else ShadowActivationGate(name)

        triplet = CausalSampleStore().build_ate_samples()
        if not triplet:
            return None
        X = triplet["X"]
        treatment = triplet["treatment"]
        y = triplet["y"]
        n = int(len(y))

        result = CausalEngine().estimate_ate(X, treatment, y, method="dml")
        if not isinstance(result, dict):
            return None
        state = classify_ate_state(result, SESOI_TAU_DEFAULT)
        obs = {
            "date": __import__("datetime").date.today().isoformat(),
            "gate_state": state,
            "ate": float(result.get("ate", 0.0)),
            "lb": float(result.get("lower_bound", 0.0)),
            "ub": float(result.get("upper_bound", 0.0)),
            "source": str(triplet.get("source", "bootstrap")),
            "n": n,
            "method": str(result.get("method", "error")),
        }
        if not g.record(obs):
            return None
        return obs
    except Exception as e:  # noqa: BLE001  HC-AGI-02
        logger.debug("[FO] shadow ate eval fail: %s", e)
        return None
```

`dreambuddy_evolution/scripts/shadow_ate_eval.py`：

```python
"""Shadow ATE 评估子进程入口（隔离 DML）.
用法: python -m dreambuddy_evolution.scripts.shadow_ate_eval --switch <name>
"""
from __future__ import annotations

import sys
from pathlib import Path

for _p in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--switch", required=True)
    args = parser.parse_args(argv)

    from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
    from dreambuddy_evolution.core.shadow_ate_evaluator import evaluate_and_record

    gate = ShadowActivationGate(args.switch)
    obs = evaluate_and_record(gate, args.switch)
    return 0 if obs else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

`agi_config.py` 新增（插在 `enable_causal_historical_samples` 行之后）：

```python
    # --- Shadow 自动放量门禁（治理设施；默认 True，本身不改交易行为）---
    "enable_shadow_auto_activation": True,      # Shadow 验证 ≥7 天且出现态A → 自动放量目标开关
```

- [ ] **Step 4: 跑测试确认绿**

Run: `python -m pytest dreambuddy_evolution/tests/test_shadow_ate_evaluator.py dreambuddy_evolution/tests/test_shadow_activation_gate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dreambuddy_evolution/core/shadow_ate_evaluator.py dreambuddy_evolution/scripts/shadow_ate_eval.py dreambuddy_evolution/agi_config.py dreambuddy_evolution/tests/test_shadow_ate_evaluator.py
git commit -m "feat(evolution): Shadow ATE evaluator + 子进程脚本 + enable_shadow_auto_activation 开关 (T3)"
```

---

### Task 4: 接线（reconcile + maybe_activate）

**Files:**
- Modify: `dreambuddy_evolution/evolution_pipeline.py`（`__init__`，ShadowRLTrainer 块后）
- Modify: `dreambuddy_evolution/core/contradiction_identifier.py`（`__init__` 加字段 + `identify()` 头部）

**Interfaces (Consumes):** `ShadowActivationGate`（Task 1）。

- [ ] **Step 1: 写失败测试** `tests/test_shadow_gate_wiring.py`

```python
"""Shadow 门禁接线测试（RED）. SPEC §7"""
from __future__ import annotations

import json


def test_pipeline_init_reconciles(tmp_path, monkeypatch):
    from dreambuddy_evolution.agi_config import get_switch, set_switch
    set_switch("enable_shadow_auto_activation", True)
    set_switch("enable_causal_historical_samples", False)
    # 把默认状态目录重定向到 tmp_path
    from dreambuddy_evolution.core import shadow_activation_gate as sag
    monkeypatch.setattr(sag, "DEFAULT_STATE_DIR", tmp_path, raising=False)
    (tmp_path / "enable_causal_historical_samples.json").write_text(
        json.dumps({"switch": "enable_causal_historical_samples",
                    "activated_at": "2026-10-14T18:00:00+08:00",
                    "min_days": 7, "min_n": 500, "observations": []}),
        encoding="utf-8")
    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
    EvolutionPipeline(gene_root=tmp_path)
    assert get_switch("enable_causal_historical_samples", False) is True


def test_identify_calls_maybe_activate(monkeypatch):
    from dreambuddy_evolution.core import shadow_activation_gate as sag
    called = {"n": 0}
    monkeypatch.setattr(sag.ShadowActivationGate, "maybe_activate",
                        lambda self: called.__setitem__("n", called["n"] + 1), raising=True)
    from dreambuddy_evolution.core.contradiction_identifier import (
        PrimaryContradictionIdentifier,
    )
    ident = PrimaryContradictionIdentifier()
    ident.identify(paths=[])  # <2 路径 → neutral，门禁仍须被调用
    assert called["n"] >= 1
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest dreambuddy_evolution/tests/test_shadow_gate_wiring.py -q`
Expected: FAIL

- [ ] **Step 3: 接线实现**

`evolution_pipeline.py`：在 `ShadowRLTrainer` 块（`self.shadow_rl_trainer = None`）之后插入：

```python
        # Shadow 自动放量门禁：启动恢复（activated_at 已存在 → 放量）FAIL-OPEN
        try:
            from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
            self._shadow_activation_gate = ShadowActivationGate(
                "enable_causal_historical_samples")
            self._shadow_activation_gate.reconcile_from_disk()
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO] shadow activation reconcile fail: %s", e)
            self._shadow_activation_gate = None
```

`contradiction_identifier.py`：`__init__` 在 `self._ate_cache: dict = {}` 之后加：

```python
        # Shadow 自动放量门禁（懒加载；O(1)；FAIL-OPEN）
        self._shadow_gate = None
```

`identify()` 在 `try:` 之后、`MIN_PATHS` 判断之前插入：

```python
            # Shadow 自动放量门禁：惰性每日评估 + 满足条件放量（O(1)；FAIL-OPEN）
            try:
                if self._shadow_gate is None:
                    from dreambuddy_evolution.core.shadow_activation_gate import (
                        ShadowActivationGate,
                    )
                    self._shadow_gate = ShadowActivationGate(
                        "enable_causal_historical_samples")
                self._shadow_gate.maybe_activate()
            except Exception as e:  # noqa: BLE001
                logger.debug("[FO-AGI][ShadowGate] fail: %s", e)
```

- [ ] **Step 4: 跑测试确认绿 + 定向非回归**

Run: `python -m pytest dreambuddy_evolution/tests/test_shadow_gate_wiring.py dreambuddy_evolution/tests/test_shadow_activation_gate.py dreambuddy_evolution/tests/test_shadow_ate_evaluator.py dreambuddy_evolution/tests/test_contradiction_identifier.py dreambuddy_evolution/tests/test_primary_contradiction_detector.py dreambuddy_evolution/tests/test_contradiction_feedback.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dreambuddy_evolution/evolution_pipeline.py dreambuddy_evolution/core/contradiction_identifier.py dreambuddy_evolution/tests/test_shadow_gate_wiring.py
git commit -m "feat(evolution): Shadow 门禁接线 reconcile + maybe_activate (T4)"
```

---

### Task 5: REFACTOR + 全量非回归（消费面）

**Files:** 无新增。

- [ ] **Step 1: 定向全量非回归**

Run: `python -m pytest dreambuddy_evolution/tests/test_phase2_causal.py dreambuddy_evolution/tests/test_causal_engine.py dreambuddy_evolution/tests/test_causal_sample_store.py dreambuddy_evolution/tests/test_contradiction_identifier.py dreambuddy_evolution/tests/test_primary_contradiction_detector.py dreambuddy_evolution/tests/test_contradiction_feedback.py dreambuddy_evolution/tests/test_counterfactual_transfer.py dreambuddy_evolution/tests/test_shadow_activation_gate.py dreambuddy_evolution/tests/test_shadow_ate_evaluator.py dreambuddy_evolution/tests/test_shadow_gate_wiring.py -q`
Expected: PASS（在 A2 的 114 passed 基础上 +新增用例）

- [ ] **Step 2: 端到端真跑子进程（1 次，验证隔离链路）**

Run: `python -m dreambuddy_evolution.scripts.shadow_ate_eval --switch enable_causal_historical_samples`
Expected: 退出码 0/1 均可；状态文件 `dreambuddy_evolution/data/shadow_activation/enable_causal_historical_samples.json` 出现当日观测（真实源B → 预期态B）

- [ ] **Step 3: Commit（如有 REFACTOR 改动）**

---

### Task 6: 验收报告 + INDEX/CHANGELOG + 认知闭环

**Files:**
- Create: `docs/audit_reports/shadow_activation_<ts>.md`
- Modify: `docs/ENGINEERING_INDEX.md`、`docs/CHANGELOG.md`

- [ ] **Step 1: 写验收报告**（门禁规则逐条复现证据：#3 放量、#7 reconcile、#8 FAIL-OPEN、对照注入 7天态B/6天+第7天态A）
- [ ] **Step 2: 更新 ENGINEERING_INDEX（core/ 表加 3 行：`shadow_activation_gate.py` / `shadow_ate_evaluator.py`；scripts 表加 `shadow_ate_eval.py`）+ CHANGELOG**
- [ ] **Step 3: 认知闭环**

```
record(content="[硬约束][自进化/治理] Shadow 自动放量门禁: 7 自然日+出现态A→自动 set_switch(True)+activated_at 持久化+reconcile; 门禁总开关 enable_shadow_auto_activation 默认 True; 评估子进程隔离; FAIL-OPEN 不激活", quality_level="B", tags="硬约束,HC-AGI-07,自进化,治理,自动放量,Shadow验证")
```

- [ ] **Step 4: Commit**

```bash
git add docs/audit_reports/ docs/ENGINEERING_INDEX.md docs/CHANGELOG.md
git commit -m "docs(evolution): Shadow 自动放量门禁验收报告 + INDEX/CHANGELOG (T6)"
```

---

## Self-Review

**1. Spec coverage:** §4 schema → T1 `record`/`_load`/`_save`；§5 规则 → T1 `evaluate`/`maybe_activate`；§7 触发点 → T4；§8 FAIL-OPEN → T1（损坏/缺失/子进程失败）；§9 持久化 → T1 `reconcile_from_disk` + T4；§10 测试 #1-#14 → T2/T3；§11 验收 → T6；§13 T1-T6 → 本计划 6 个 task。

**2. Placeholder scan:** 无 TBD/TODO；每个代码步骤含完整代码。

**3. Type consistency:** `ShadowActivationGate(switch, state_dir=...)`、`record(obs)->bool`、`evaluate()->dict`、`maybe_activate()->bool`、`reconcile_from_disk()->bool`、`evaluate_and_record(gate, switch_name=None)->dict|None`、`main(argv)->int` 全计划一致。`_spawn_evaluator` 为 patch 目标，签名 `(self)`.

**Known deviations from SPEC（已确认）:** SPEC §12.1 源B 静态 → 恒态B → 单靠源B 永不触发；本计划不制造效应，只保证「真实态A 出现即自动放量」。
