"""
Shadow 激活门禁 — Shadow 验证 ≥7 天且出现态A → 自动放量
SPEC-Shadow验证自动放量门禁.md §3-§9

设计要点：
  - 状态唯一入口，O(1) 读文件，无 DML（DML 在 evaluator 子进程）
  - 原子写（tempfile + os.replace）；损坏/缺失 → 空状态（FAIL-OPEN，不激活）
  - 唯一入口 maybe_activate: 惰性每日 spawn evaluator + 满足条件 set_switch(True)
  - reconcile_from_disk: 启动恢复（activated_at 已存在 → 放量），补齐 set_switch 不落盘缺口

硬约束: HC-AGI-02（异常→中性兜底）、HC-AGI-07（满足条件才放量）、HC-AGI-08（min_n=500 不得下调）。
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

logger = logging.getLogger(__name__)

# core/ → dreambuddy_evolution/ → 23-四层闭环自进化交易架构/
_MODULE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = _MODULE_DIR / "data" / "shadow_activation"
DEFAULT_EVAL_SCRIPT = _MODULE_DIR / "scripts" / "shadow_ate_eval.py"

_GATE_SWITCH = "enable_shadow_auto_activation"
# 无效观测的 method 白名单外集合（SPEC §8）
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
