#!/usr/bin/env python3
"""temporal_signature_extractor.py — S1 时序签名提取器（S0 窗口 → 定长特征）

SPEC-L0-L1-DOMAIN-DISCOVERY-v0.1 §4.6.3：消费 AgentMailShadow 的每域时序步窗口
（S0 去重/滑窗产物），输出**无 look-ahead**的定长向量，供后续轻量 head 使用。

特征构成（维度 = D×10 + C(D,2)×2）：
  - 每域 10 维：poe_score 路径签名 5 维（depth3）+ latency_ms 路径签名 5 维
    （路径签名用仓库既有 SignatureEngine，numpy 降级；窗口内 z-score 仅用过去点）
  - 每对域 2 维：Lévy area（poe 通道反对称项，编码 lead-lag）+ 最优滞后步数
    （互相关在 ±max_lag_steps 内搜索，重叠不足则滞后记 0）

硬约束：
  - T2 无 look-ahead：只消费已发生的窗口步，归一化统计量在本窗口内计算
  - T1 零训练：纯确定性变换，不加载 torch / 不读 ckpt
  - FAIL-OPEN：窗口不足 / NaN / 引擎异常 → ready=False + 零向量，不抛错

不负责：S3 图接线与 F1/F2 消融判定（见 shadow_gate.py）。
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SIGNATURE_ENGINE_PATH = (
    _REPO_ROOT
    / "23-四层闭环自进化交易架构"
    / "dreambuddy_evolution"
    / "core"
    / "signature_engine.py"
)

DEFAULT_DEPTH = 3
DEFAULT_MAX_LAG_STEPS = 5
DEFAULT_MIN_STEPS = 8

# 签名深度 → 每通道维度（与 SignatureEngine._numpy_signature 的 depth3 输出一致）
_SIG_DIM_BY_DEPTH = {1: 1, 2: 3, 3: 5, 4: 7, 5: 9}

_ENGINE_CACHE: Optional[Any] = None


def _load_engine(depth: int) -> Any:
    """懒加载 SignatureEngine（绕过 23- 包的 __init__，避免重依赖）。"""
    global _ENGINE_CACHE
    if _ENGINE_CACHE is None or _ENGINE_CACHE.depth != depth:
        spec = importlib.util.spec_from_file_location(
            "dreambuddy_signature_engine", _SIGNATURE_ENGINE_PATH
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"signature_engine not loadable: {_SIGNATURE_ENGINE_PATH}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ENGINE_CACHE = mod.SignatureEngine(depth=depth)
    return _ENGINE_CACHE


def _zscore(values: Sequence[float]) -> np.ndarray:
    """窗口内 z-score（仅用本窗口已发生点）；标准差过低 → 全 0（避免放大噪声）。"""
    arr = np.asarray(list(values), dtype=np.float64)
    if arr.size == 0:
        return arr
    std = float(arr.std())
    if not math.isfinite(std) or std < 1e-9:
        return np.zeros_like(arr)
    return (arr - float(arr.mean())) / std


def _levy_area(a: np.ndarray, b: np.ndarray) -> float:
    """Lévy area = 0.5·Σ(a_i·b_{i+1} − a_{i+1}·b_i)，反对称项编码 lead-lag。"""
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a, b = a[:n], b[:n]
    area = 0.5 * float(np.sum(a[:-1] * b[1:] - a[1:] * b[:-1]))
    return area if math.isfinite(area) else 0.0


def _best_lag(a: np.ndarray, b: np.ndarray, max_lag: int, min_overlap: int = 3) -> float:
    """互相关搜索最优滞后（a 领先 b 为正）；重叠不足或退化 → 0。"""
    n = min(len(a), len(b))
    if n < min_overlap + 1:
        return 0.0
    best_lag, best_corr = 0, -math.inf
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x, y = a[: n - lag], b[lag:n]
        else:
            x, y = a[-lag:n], b[: n + lag]
        if len(x) < min_overlap:
            continue
        sx, sy = float(np.std(x)), float(np.std(y))
        if sx < 1e-9 or sy < 1e-9:
            continue
        corr = float(np.mean((x - x.mean()) * (y - y.mean())) / (sx * sy))
        if corr > best_corr:
            best_corr, best_lag = corr, lag
    return float(best_lag) if best_corr > -math.inf else 0.0


def _align_window_steps(
    steps_a: List[Dict[str, Any]], steps_b: List[Dict[str, Any]], signal: str, max_fill: int = 2
) -> Tuple[np.ndarray, np.ndarray]:
    """按 ts 并集对齐两域序列，前向填充（最多 max_fill 步），未覆盖点丢弃。

    返回两条等长数组；无法对齐（重叠 <2）返回空数组。
    """
    merged = sorted(
        [(float(s.get("ts", 0.0)), 0, s) for s in steps_a]
        + [(float(s.get("ts", 0.0)), 1, s) for s in steps_b],
        key=lambda x: x[0],
    )
    if not merged:
        return np.array([]), np.array([])

    last_a: Optional[float] = None
    last_b: Optional[float] = None
    stale_a = stale_b = 0
    out_a: List[float] = []
    out_b: List[float] = []
    for _ts, which, step in merged:
        value = float(step.get(signal, 0.0) or 0.0)
        if which == 0:
            last_a, stale_a = value, 0
        else:
            last_b, stale_b = value, 0
        stale_a += 0 if which == 0 else 1
        stale_b += 0 if which == 1 else 1
        if last_a is None or last_b is None or stale_a > max_fill or stale_b > max_fill:
            continue
        out_a.append(last_a)
        out_b.append(last_b)
    if len(out_a) < 2:
        return np.array([]), np.array([])
    return np.asarray(out_a, dtype=np.float64), np.asarray(out_b, dtype=np.float64)


class TemporalSignatureExtractor:
    """S0 窗口 → 定长签名特征（确定性、可单测、FAIL-OPEN）。"""

    def __init__(
        self,
        depth: int = DEFAULT_DEPTH,
        max_lag_steps: int = DEFAULT_MAX_LAG_STEPS,
        min_steps: int = DEFAULT_MIN_STEPS,
    ) -> None:
        if depth < 1 or depth > 5:
            raise ValueError("depth 必须在 1..5（HC-AGI-11）")
        self.depth = int(depth)
        self.max_lag_steps = max(0, int(max_lag_steps))
        self.min_steps = max(2, int(min_steps))
        self._sig_dim = _SIG_DIM_BY_DEPTH[self.depth]

    def dimension(self, n_domains: int) -> int:
        """给定域数时的特征维度 = D×2×sig_dim + C(D,2)×2。"""
        pairs = n_domains * (n_domains - 1) // 2
        return n_domains * 2 * self._sig_dim + pairs * 2

    def extract(self, windows: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """从每域窗口提取特征。windows: {domain: [step, ...]}（S0 聚合步）。"""
        domains = sorted(
            d for d, steps in (windows or {}).items() if len(steps or []) >= self.min_steps
        )
        dim = self.dimension(len(domains))
        result: Dict[str, Any] = {
            "ready": False,
            "reason": "",
            "domains": domains,
            "dim": dim,
            "vector": [0.0] * dim,
            "per_domain": {},
            "pairs": {},
        }
        if not domains:
            result["reason"] = "insufficient_domains_or_steps"
            return result

        try:
            engine = _load_engine(self.depth)
            vectors: List[float] = []
            z_poe: Dict[str, np.ndarray] = {}
            raw_poe: Dict[str, np.ndarray] = {}

            for domain in domains:
                steps = sorted(windows[domain], key=lambda s: float(s.get("ts", 0.0)))[-128:]
                poe = [float(s.get("poe_score", 0.0) or 0.0) for s in steps]
                lat = [float(s.get("latency_ms", 0.0) or 0.0) for s in steps]
                zp, zl = _zscore(poe), _zscore(lat)
                z_poe[domain], raw_poe[domain] = zp, np.asarray(poe, dtype=np.float64)

                sig_poe = np.asarray(engine.signature(zp), dtype=np.float64)[: self._sig_dim]
                sig_lat = np.asarray(engine.signature(zl), dtype=np.float64)[: self._sig_dim]
                sig_poe = np.resize(sig_poe, self._sig_dim)
                sig_lat = np.resize(sig_lat, self._sig_dim)
                feat = np.concatenate([sig_poe, sig_lat])
                feat = np.where(np.isfinite(feat), feat, 0.0)

                vectors.extend(feat.tolist())
                result["per_domain"][domain] = {
                    "steps": len(steps),
                    "poe_sig": [round(float(x), 6) for x in sig_poe],
                    "latency_sig": [round(float(x), 6) for x in sig_lat],
                }

            for i in range(len(domains)):
                for j in range(i + 1, len(domains)):
                    a, b = domains[i], domains[j]
                    left, right = _align_window_steps(windows[a], windows[b], "poe_score")
                    area = _levy_area(_zscore(left), _zscore(right))
                    lag = _best_lag(raw_poe[a], raw_poe[b], self.max_lag_steps)
                    vectors.extend([area, lag])
                    result["pairs"][f"{a}↔{b}"] = {
                        "levy_area": round(float(area), 6),
                        "lag_steps": lag,
                    }

            vec = np.asarray(vectors, dtype=np.float64)
            vec = np.where(np.isfinite(vec), vec, 0.0)
            if vec.size != dim:
                result["reason"] = f"dim_mismatch:{vec.size}!={dim}"
                return result
            result["vector"] = [round(float(x), 8) for x in vec]
            result["ready"] = True
            return result
        except Exception as e:  # noqa: BLE001 — FAIL-OPEN，不影响壳主链路
            result["reason"] = f"{type(e).__name__}: {e}"
            return result


__all__ = ["TemporalSignatureExtractor", "DEFAULT_DEPTH", "DEFAULT_MIN_STEPS"]
