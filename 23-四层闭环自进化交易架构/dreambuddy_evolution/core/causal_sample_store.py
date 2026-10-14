"""
CausalSampleStore — A2 双源历史因果样本库（非 LLM·数据驱动）

蓝本：SPEC-A2-因果ATE历史样本接入.md §2
目标：为 CausalEngine.estimate_ate 接入 ≥500 条历史已标注样本，
      使 ATE 从「永远 insufficient_samples 中性降级」变为可估计。

双源设计（两源独立估计、绝不混合）：
  源A（live·保真优先）：ContradictionWeightLearner 持久化的实时矛盾样本
     X=[power,time,consistency,market_weight]，treatment=power>median(power)，
     y=actual_return（延迟标注，仅已标注样本）
  源B（bootstrap·批量引导）：gene_data/shadow_rl_samples.jsonl
     X=[R_down,R_smooth,R_flow,R_reflexivity]（去 R_up 防共线、去 quality_score 防退化），
     treatment=R_up>median(R_up)，y=reward

优先级：源A 已标注数 ≥ min_n → 独用源A；否则独用源B；两源均不足/退化 → 返回 None。

硬约束：
  - HC-AGI-08: 最小样本量 ≥500（不在此处下调，守门见 CausalEngine.MIN_SAMPLES）
  - HC-AGI-02: 异常 → 中性兜底（返回 None，上层 insufficient_samples no-op）
FAIL-OPEN：任何装载/解析异常 → 返回 None，不 crash。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# 源B 协变量：state 6 维去掉 R_up（treatment 定义变量）与 quality_score（退化解）
BOOT_COVARS = ["R_down", "R_smooth", "R_flow", "R_reflexivity"]
# 源A 协变量：4 维矛盾分数
LIVE_COVARS = ["power", "time", "consistency", "market_weight"]

# 源B 内存缓存（单例语义）：path -> ((mtime, size), {"rup":ndarray,"X":ndarray,"y":ndarray})
_BOOT_CACHE: dict[str, tuple[tuple[float, int], dict[str, np.ndarray]]] = {}
_BOOT_LOCK = threading.Lock()


class CausalSampleStore:
    """双源历史因果样本库.

    Args:
        shadow_path: 源B shadow_rl_samples.jsonl 路径（默认 gene_data 下）
        live_path:   源A contradiction_samples.json 路径（默认 data 下）
        min_n:       最小样本量（默认 500，对齐 HC-AGI-08）
        degenerate_ratio: 退化保护阈值比例（默认 0.1，即每类样本 ≥ min_n*0.1）
    """

    def __init__(
        self,
        shadow_path: str | None = None,
        live_path: str | None = None,
        min_n: int = 500,
        degenerate_ratio: float = 0.1,
    ) -> None:
        self._shadow_path = shadow_path or self._default_shadow_path()
        self._live_path = live_path or self._default_live_path()
        self._min_n = int(min_n)
        self._degenerate_ratio = float(degenerate_ratio)

    # ------------------------------------------------------------------
    # 默认路径
    # ------------------------------------------------------------------
    @staticmethod
    def _default_shadow_path() -> str:
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "gene_data", "shadow_rl_samples.jsonl")
        )

    @staticmethod
    def _default_live_path() -> str:
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "data", "contradiction_samples.json")
        )

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def build_ate_samples(
        self,
        min_n: int | None = None,
        live_samples: list[dict] | None = None,
    ) -> Optional[dict[str, Any]]:
        """构造 ATE 估计三元组 (X, treatment, y).

        返回 {"source": "live"|"bootstrap", "n": int, "X": ndarray2D,
              "treatment": ndarray, "y": ndarray}；无有效样本 → None。
        """
        try:
            n = int(min_n or self._min_n)

            # 源A 优先（保真）
            live = self._collect_live(live_samples)
            triplet = self._build_live_triplet(live, n)
            if triplet is not None:
                return triplet

            # 源B 兜底（批量引导）
            return self._build_bootstrap_triplet(n)
        except Exception as e:  # noqa: BLE001
            logger.debug("[A2] build_ate_samples FAIL-OPEN: %s", e)
            return None

    # ------------------------------------------------------------------
    # 源A：实时矛盾样本
    # ------------------------------------------------------------------
    def _collect_live(self, live_samples: list[dict] | None) -> list[dict]:
        """获取源A 样本：显式传入优先；否则从 live_path 读回（FAIL-OPEN）."""
        if live_samples is not None:
            return live_samples
        try:
            if not os.path.exists(self._live_path):
                return []
            with open(self._live_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("samples", []) or []
        except Exception as e:  # noqa: BLE001
            logger.debug("[A2] live load FAIL-OPEN: %s", e)
            return []

    def _build_live_triplet(self, samples: list[dict], min_n: int) -> Optional[dict[str, Any]]:
        labeled = [
            s for s in samples
            if s.get("actual_return") is not None
        ]
        if len(labeled) < min_n:
            return None

        rows, ys = [], []
        for s in labeled:
            try:
                rows.append([float(s[c]) for c in LIVE_COVARS])
                ys.append(float(s["actual_return"]))
            except (KeyError, TypeError, ValueError):
                continue
        if len(ys) < min_n:
            return None

        X = np.asarray(rows, dtype=np.float64)
        y = np.asarray(ys, dtype=np.float64)
        if not (np.all(np.isfinite(X)) and np.all(np.isfinite(y))):
            return None

        power = X[:, 0]
        treatment = (power > np.median(power)).astype(np.int32)
        if not self._validate_treatment(treatment, min_n):
            return None

        return {
            "source": "live",
            "n": int(X.shape[0]),
            "X": X,
            "treatment": treatment,
            "y": y,
        }

    # ------------------------------------------------------------------
    # 源B：Shadow RL 样本（单例缓存 + mtime/size 失效）
    # ------------------------------------------------------------------
    def _load_bootstrap(self) -> Optional[dict[str, np.ndarray]]:
        path = self._shadow_path
        try:
            if not os.path.exists(path):
                return None
            st = os.stat(path)
            key = (float(st.st_mtime), int(st.st_size))
        except OSError as e:
            logger.debug("[A2] bootstrap stat FAIL-OPEN: %s", e)
            return None

        with _BOOT_LOCK:
            cached = _BOOT_CACHE.get(path)
            if cached is not None and cached[0] == key:
                return cached[1]

        parsed = self._parse_bootstrap(path)
        if parsed is None:
            return None
        with _BOOT_LOCK:
            _BOOT_CACHE[path] = (key, parsed)
        return parsed

    def _parse_bootstrap(self, path: str) -> Optional[dict[str, np.ndarray]]:
        rup, rows, ys = [], [], []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        state = rec.get("state") or {}
                        reward = rec.get("reward")
                        if reward is None:
                            continue
                        r = [float(state[c]) for c in BOOT_COVARS]
                        u = float(state["R_up"])
                        yy = float(reward)
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if not (np.all(np.isfinite(r)) and np.isfinite(u) and np.isfinite(yy)):
                        continue
                    rup.append(u)
                    rows.append(r)
                    ys.append(yy)
        except OSError as e:
            logger.debug("[A2] bootstrap read FAIL-OPEN: %s", e)
            return None

        if not ys:
            return None
        return {
            "rup": np.asarray(rup, dtype=np.float64),
            "X": np.asarray(rows, dtype=np.float64),
            "y": np.asarray(ys, dtype=np.float64),
        }

    def _build_bootstrap_triplet(self, min_n: int) -> Optional[dict[str, Any]]:
        data = self._load_bootstrap()
        if data is None:
            return None
        y = data["y"]
        if y.shape[0] < min_n:
            return None

        rup = data["rup"]
        treatment = (rup > np.median(rup)).astype(np.int32)
        if not self._validate_treatment(treatment, min_n):
            return None

        return {
            "source": "bootstrap",
            "n": int(y.shape[0]),
            "X": data["X"],
            "treatment": treatment,
            "y": y,
        }

    # ------------------------------------------------------------------
    # 退化保护（评审 M1）
    # ------------------------------------------------------------------
    def _validate_treatment(self, treatment: np.ndarray, min_n: int) -> bool:
        """校验 treatment 非退化：≥2 水平 且 每类样本数 ≥ min_n*degenerate_ratio."""
        uniq = np.unique(treatment)
        if len(uniq) < 2:
            return False
        floor = min_n * self._degenerate_ratio
        for u in uniq:
            if int(np.sum(treatment == u)) < floor:
                return False
        return True
