"""HMM 3-state 适配器 — regime label → (sl, tp, atr) 建议

依赖: 23-四层闭环自进化交易架构/dreambuddy_evolution/core/btc_regime_detector.py
输出: regime (0=bull/1=chop/2=bear) → 转换为参数建议
"""
from __future__ import annotations

from typing import Optional

from ..aggregator import AlgoObservation, SL_FLOOR, TP_FLOOR, ATR_MULT_DEFAULT
from .base import BaseAdapter

# regime → 参数建议映射
_REGIME_PARAMS = {
    0: {"sl_floor": 0.04, "tp_floor": 0.15, "atr_mult": 4.5},   # bull: 紧SL宽TP
    1: {"sl_floor": 0.05, "tp_floor": 0.15, "atr_mult": 4.5},   # chop: 均衡
    2: {"sl_floor": 0.06, "tp_floor": 0.12, "atr_mult": 5.0},   # bear: 宽SL紧TP
}


class HmmAdapter(BaseAdapter):
    name = "hmm"

    def _observe_impl(
        self,
        symbol: str,
        market_data: Optional[dict] = None,
    ) -> Optional[AlgoObservation]:
        # market_data 应包含 closes 字段
        if not market_data or "closes" not in market_data:
            # 无数据时返回 None，聚合器自动跳过
            return None

        closes = market_data["closes"]
        if len(closes) < 50:
            return None

        try:
            # 延迟导入避免循环依赖
            import sys
            from pathlib import Path
            _proj_root = Path(__file__).resolve().parents[4]
            _evo = _proj_root / "23-四层闭环自进化交易架构"
            if str(_evo) not in sys.path:
                sys.path.insert(0, str(_evo))
            from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector
            detector = BTCRegimeDetector()
            regimes = detector.detect(closes)
            regime = int(regimes[-1])  # 取最新 regime
        except Exception:
            # 算法不可用时返回 None
            return None

        params = _REGIME_PARAMS.get(regime, _REGIME_PARAMS[1])
        return AlgoObservation(
            algo_name=self.name,
            params=params,
            confidence=0.7,  # HMM 后验置信度（简化）
        )
