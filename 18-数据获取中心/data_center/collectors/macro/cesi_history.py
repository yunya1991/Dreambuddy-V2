"""CESI 历史滚动窗口 — 维护每个宏观指标的最近 12 次 surprise 值。

SPEC-事件驱动策略P0盲区修复 §3.1.3 — CESI 标准化：Surprise=(Actual-Forecast)/σ_history
σ 维护：滚动窗口最近 12 次发布的 surprise 标准差，至少 6 次才能算 σ。

存储：JSON 文件 ~/.workbuddy/cesi_history.json
格式：{"cpi": [0.2, -0.1, ...], "nfp": [17.0, -5.0, ...], ...}
窗口大小：12（FIFO 滚动）

FAIL-OPEN：所有异常被捕获，返回空列表或不追加（不抛异常）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 滚动窗口大小：最近 12 次发布
WINDOW_SIZE = 12

# σ 计算的最小历史：至少 6 次才能算标准差
MIN_HISTORY_FOR_SIGMA = 6

# 默认存储路径：~/.workbuddy/cesi_history.json
_DEFAULT_PATH = Path.home() / ".workbuddy" / "cesi_history.json"


def _load_history(path: Path | None = None) -> dict:
    """加载完整历史字典。文件不存在或损坏时返回空 dict。"""
    p = path or _DEFAULT_PATH
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning("[CESI] 历史文件加载失败，FAIL-OPEN 返回空: %s", e)
    return {}


def _save_history(history: dict, path: Path | None = None) -> None:
    """保存完整历史字典。失败时 FAIL-OPEN 跳过（不抛异常）。"""
    p = path or _DEFAULT_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("[CESI] 历史文件保存失败，FAIL-OPEN 跳过: %s", e)


def get_surprise_history(indicator: str, path: Path | None = None) -> list[float]:
    """获取指定指标的最近 12 次 surprise 值。

    Args:
        indicator: 指标名，如 "cpi" / "nfp" / "ppi"
        path: 自定义存储路径（测试用），默认 ~/.workbuddy/cesi_history.json

    Returns:
        surprise 值列表，新指标返回空列表
    """
    history = _load_history(path)
    return list(history.get(indicator, []))


def append_surprise(
    indicator: str, surprise: float, path: Path | None = None
) -> None:
    """追加新 surprise 值，保持窗口大小 12（FIFO）。

    Args:
        indicator: 指标名，如 "cpi" / "nfp" / "ppi"
        surprise: surprise = actual - forecast
        path: 自定义存储路径（测试用）
    """
    history = _load_history(path)
    buf = history.get(indicator, [])
    buf.append(float(surprise))
    # 保持窗口大小（FIFO）
    if len(buf) > WINDOW_SIZE:
        buf = buf[-WINDOW_SIZE:]
    history[indicator] = buf
    _save_history(history, path)


def compute_cesi(
    actual: float, forecast: float, history: list[float]
) -> float | None:
    """计算 CESI = (actual - forecast) / σ_history。

    Args:
        actual: 实际值
        forecast: 预期值
        history: 最近 12 次 surprise 值列表

    Returns:
        CESI 标准化值（round 3 位小数），历史不足或 σ=0 时返回 None
    """
    if len(history) < MIN_HISTORY_FOR_SIGMA:
        return None
    try:
        import numpy as np

        sigma = float(np.std(history))
    except Exception as e:
        logger.warning("[CESI] σ 计算失败，FAIL-OPEN 返回 None: %s", e)
        return None
    if sigma < 1e-9:
        # σ 接近 0（浮点误差或历史值全相同），无法标准化
        return None
    return round((actual - forecast) / sigma, 3)
