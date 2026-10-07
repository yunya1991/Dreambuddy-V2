"""市场形态识别网关 — 封装 BTCRegimeDetector 为统一接口

复用自进化系统的 btc_regime_detector.py（k=3 HMM + drawdown 观测），
为 SL/TP 三维分类提供市场形态维度。

市场形态：
  - bull  牛市（drawdown 接近 0，趋势向上）
  - chop  震荡（中等 drawdown，方向不明）
  - bear  熊市（大幅 drawdown，趋势向下）

FAIL-OPEN: HMM 不收敛 / 数据不足 → 返回 "chop"（中性形态）。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# 将自进化系统路径加入 sys.path，确保能导入 BTCRegimeDetector
_EVOLUTION_DIR = Path(__file__).resolve().parents[4] / "23-四层闭环自进化交易架构"
if str(_EVOLUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EVOLUTION_DIR))

# 形态常量
REGIME_BULL = "bull"
REGIME_CHOP = "chop"
REGIME_BEAR = "bear"

_DEFAULT_REGIME = REGIME_CHOP  # FAIL-OPEN 默认形态

# HMM label → 形态映射（0=bull, 1=chop, 2=bear，由 BTCRegimeDetector 保证）
_HMM_LABEL_TO_REGIME = {0: REGIME_BULL, 1: REGIME_CHOP, 2: REGIME_BEAR}


class MarketRegimeGateway:
    """市场形态识别网关。

    封装 BTCRegimeDetector，提供 get_current_regime(closes) 接口。

    Args:
        n_regimes: regime 数（默认 3）
        window: rolling max 窗口（默认 720，1h 数据=30天）
        min_samples: 最小样本数（默认 200）
    """

    def __init__(self, n_regimes: int = 3, window: int = 720, min_samples: int = 200):
        self._detector = None
        self._n_regimes = n_regimes
        self._window = window
        self._min_samples = min_samples
        self._init_detector()

    def _init_detector(self) -> None:
        """懒加载 BTCRegimeDetector，导入失败时 FAIL-OPEN。"""
        try:
            from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector
            self._detector = BTCRegimeDetector(
                n_regimes=self._n_regimes,
                window=self._window,
                min_samples=self._min_samples,
            )
        except Exception as e:
            logger.warning("BTCRegimeDetector 导入失败，降级到阈值法: %s", e)
            self._detector = None

    def get_current_regime(self, closes: np.ndarray) -> str:
        """获取当前市场形态。

        Args:
            closes: BTC close 价格序列（1d array）

        Returns:
            "bull" / "chop" / "bear"
            FAIL-OPEN 返回 "chop"
        """
        closes = np.asarray(closes, dtype=float)
        if closes.size == 0:
            return _DEFAULT_REGIME

        # 优先用 HMM 检测器
        if self._detector is not None:
            try:
                labels = self._detector.detect(closes)
                if labels is not None and len(labels) > 0:
                    last_label = int(labels[-1])
                    return _HMM_LABEL_TO_REGIME.get(last_label, _DEFAULT_REGIME)
            except Exception as e:
                logger.debug("MarketRegimeGateway HMM 检测失败: %s, 降级阈值法", e)

        # 兜底：drawdown 阈值法
        return self._threshold_regime(closes)

    @staticmethod
    def _threshold_regime(closes: np.ndarray) -> str:
        """简单 drawdown 阈值法兜底。"""
        try:
            closes = np.asarray(closes, dtype=float)
            if closes.size < 2:
                return _DEFAULT_REGIME
            rolling_max = np.maximum.accumulate(closes)
            drawdown = (closes[-1] - rolling_max[-1]) / rolling_max[-1] if rolling_max[-1] > 0 else 0.0
            if drawdown > -0.05:
                return REGIME_BULL
            elif drawdown < -0.20:
                return REGIME_BEAR
            else:
                return REGIME_CHOP
        except Exception:
            return _DEFAULT_REGIME

    def get_regime_series(self, closes: np.ndarray) -> list[str]:
        """获取整条序列的形态（用于回测）。"""
        closes = np.asarray(closes, dtype=float)
        if closes.size == 0:
            return []
        if self._detector is not None:
            try:
                labels = self._detector.detect(closes)
                if labels is not None:
                    return [_HMM_LABEL_TO_REGIME.get(int(l), _DEFAULT_REGIME) for l in labels]
            except Exception:
                pass
        # 兜底：对每个点用阈值法（简单实现）
        result = []
        for i in range(len(closes)):
            result.append(self._threshold_regime(closes[: i + 1]))
        return result


# 全局单例（避免重复初始化 HMM）
_gateway: Optional[MarketRegimeGateway] = None


def get_market_regime(closes: np.ndarray) -> str:
    """全局便捷函数：获取当前市场形态。"""
    global _gateway
    if _gateway is None:
        _gateway = MarketRegimeGateway()
    return _gateway.get_current_regime(closes)
