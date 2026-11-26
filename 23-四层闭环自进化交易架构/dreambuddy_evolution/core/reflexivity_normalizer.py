"""R_reflexivity 历史分位归一化（F4.1）。

背景：R_reflexivity 实测长期贴在 0.50 附近（std≈0.002），wait=(1-R_smooth)×R_refl
与方向代价（≈0.45）量纲不可比，calibrated 口径下大量样本被 margin 卡成 WAIT。

做法：用历史样本的经验分布（ECDF）把原始 R_reflexivity 映射到 [0,1] 分位，
再由 wait 侧乘 `EVOLUTION_DSTAR_WAIT_SCALE`（默认 2.0）抬到与方向代价可比区间。
样本不足 50 条时退化为线性映射（0.35→0，0.85→1），保证冷启动可用。

持久化：`runtime/reflexivity_history.json`（保留最近 2000 条，写盘节流）。
环境变量：
  EVOLUTION_DSTAR_REFL_NORM=1   启用（默认 0，保持旧口径）
  EVOLUTION_DSTAR_WAIT_SCALE    缩放系数（默认 2.0）
  EVOLUTION_REFL_HISTORY_PATH   历史文件路径（测试/隔离用）
"""

from __future__ import annotations

import bisect
import json
import logging
import os
import tempfile
import threading

logger = logging.getLogger(__name__)

_DEFAULT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "runtime", "reflexivity_history.json")
)


class ReflexivityNormalizer:
    """ECDF 分位归一化器（线程安全，FAIL-OPEN）。"""

    def __init__(
        self,
        path: str | None = None,
        min_samples: int = 50,
        fallback_lo: float = 0.35,
        fallback_hi: float = 0.85,
        cap: int = 2000,
    ) -> None:
        self._path = path or os.getenv("EVOLUTION_REFL_HISTORY_PATH") or _DEFAULT_PATH
        self._min_samples = int(min_samples)
        self._fallback_lo = float(fallback_lo)
        self._fallback_hi = float(fallback_hi)
        self._cap = int(cap)
        self._lock = threading.Lock()
        self._values: list[float] = []
        self._sorted: list[float] = []
        self._dirty = 0
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            vals = [float(v) for v in data if isinstance(v, (int, float))]
        except (OSError, ValueError, TypeError):
            return
        self._values = vals[-self._cap :]
        self._sorted = sorted(self._values)

    def _save_locked(self) -> None:
        try:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=parent or ".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._values, f)
            os.replace(tmp, self._path)
            self._dirty = 0
        except OSError as e:
            logger.debug("[FO] reflexivity history save fail: %s", e)

    # ------------------------------------------------------------------
    def percentile(self, value: float) -> float:
        """返回 value 在历史样本中的经验分位；样本不足走线性映射。"""
        v = float(value)
        with self._lock:
            n = len(self._sorted)
            if n >= self._min_samples:
                return bisect.bisect_right(self._sorted, v) / n
        span = max(self._fallback_hi - self._fallback_lo, 1e-9)
        return max(0.0, min(1.0, (v - self._fallback_lo) / span))

    def observe(self, value: float) -> None:
        """记录一个样本（保留最近 cap 条），每 20 条或首次达标时落盘。"""
        v = float(value)
        with self._lock:
            self._values.append(v)
            bisect.insort(self._sorted, v)
            if len(self._values) > self._cap:
                old = self._values.pop(0)
                idx = bisect.bisect_left(self._sorted, old)
                if idx < len(self._sorted):
                    self._sorted.pop(idx)
            self._dirty += 1
            if self._dirty >= 20 or len(self._values) == self._min_samples:
                self._save_locked()

    def flush(self) -> None:
        """强制落盘（进程退出前/测试用）。"""
        with self._lock:
            self._save_locked()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._values)

    def reset(self) -> None:
        with self._lock:
            self._values.clear()
            self._sorted.clear()
            self._dirty = 0


_NORMALIZERS: dict[str, ReflexivityNormalizer] = {}
_NORMALIZER_LOCK = threading.Lock()


def get_normalizer(path: str | None = None) -> ReflexivityNormalizer:
    """按路径缓存的单例（同一进程内共享历史）。"""
    key = path or os.getenv("EVOLUTION_REFL_HISTORY_PATH") or _DEFAULT_PATH
    with _NORMALIZER_LOCK:
        inst = _NORMALIZERS.get(key)
        if inst is None:
            inst = ReflexivityNormalizer(path=key)
            _NORMALIZERS[key] = inst
        return inst
