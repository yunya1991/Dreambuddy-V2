"""限频 + 熔断护栏 — SPEC §3.2 红线 2/3（P1-A）。

规则：
  1. 每个源独立护栏：请求最小间隔（`min_interval`）+ 可识别 UA（见 `_http.py`）
  2. 熔断：滑动窗口内失败率 > 30%（且样本 ≥ `min_samples`）→ 打开熔断，
     冷却期内该源所有请求直接 `CircuitOpen`（调用方 FAIL-OPEN → 返回空结果，
     降级到已有的 Tavily/GDELT 兜底）
  3. 状态持久化到 `18-数据获取中心/data/tradefin_cache/circuit_<source>.json`，
     进程重启后熔断仍生效、且失败率可审计
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_DIR = Path(__file__).resolve().parents[3] / "data" / "tradefin_cache"


class CircuitOpen(RuntimeError):
    """熔断打开，本次请求被拒绝。"""


class SourceGuard:
    """单源限频 + 滑动窗口失败率熔断。"""

    def __init__(
        self,
        source: str,
        *,
        min_interval: float = 1.0,
        window: int = 20,
        failure_threshold: float = 0.3,
        min_samples: int = 4,
        cooldown_s: float = 1800.0,
        state_dir: Path | str | None = None,
        clock=time.time,
        sleep=time.sleep,
    ):
        self.source = source
        self.min_interval = float(min_interval)
        self.window = int(window)
        self.failure_threshold = float(failure_threshold)
        self.min_samples = int(min_samples)
        self.cooldown_s = float(cooldown_s)
        self.state_dir = Path(state_dir or _STATE_DIR)
        self._clock = clock
        self._sleep = sleep
        self._last_call = 0.0
        self._outcomes: deque[bool] = deque(maxlen=self.window)
        self._opened_until = 0.0
        self._load()

    # ── 状态文件 ──────────────────────────────────────────────
    @property
    def state_path(self) -> Path:
        return self.state_dir / f"circuit_{self.source}.json"

    def _load(self) -> None:
        if not self.state_path.is_file():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for ok in data.get("outcomes", [])[-self.window :]:
            self._outcomes.append(bool(ok))
        self._opened_until = float(data.get("opened_until") or 0.0)

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": self.source,
            "outcomes": list(self._outcomes),
            "opened_until": self._opened_until,
            "updated_at": self._clock(),
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # ── 请求前 ────────────────────────────────────────────────
    def before_request(self) -> None:
        now = self._clock()
        if self._opened_until > now:
            raise CircuitOpen(
                f"{self.source} 熔断中（剩余 {self._opened_until - now:.0f}s，"
                f"失败率 {self.failure_rate:.0%}）"
            )
        wait = self.min_interval - (now - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = self._clock()

    # ── 记录结果 ──────────────────────────────────────────────
    def record(self, success: bool) -> None:
        self._outcomes.append(bool(success))
        if (
            len(self._outcomes) >= self.min_samples
            and self.failure_rate > self.failure_threshold
            and self._opened_until <= self._clock()
        ):
            self._opened_until = self._clock() + self.cooldown_s
            logger.warning(
                "[circuit] %s 打开熔断：失败率 %.0f%%（窗口 %d）> %.0f%%，冷却 %.0fs",
                self.source,
                self.failure_rate * 100,
                len(self._outcomes),
                self.failure_threshold * 100,
                self.cooldown_s,
            )
        self._save()

    # ── 观测 ──────────────────────────────────────────────────
    @property
    def requests(self) -> int:
        return len(self._outcomes)

    @property
    def failures(self) -> int:
        return sum(1 for ok in self._outcomes if not ok)

    @property
    def failure_rate(self) -> float:
        return self.failures / len(self._outcomes) if self._outcomes else 0.0

    @property
    def is_open(self) -> bool:
        return self._opened_until > self._clock()

    def stats(self) -> dict:
        return {
            "source": self.source,
            "requests": self.requests,
            "failures": self.failures,
            "failure_rate": round(self.failure_rate, 4),
            "circuit_open": self.is_open,
            "opened_until": self._opened_until,
        }
