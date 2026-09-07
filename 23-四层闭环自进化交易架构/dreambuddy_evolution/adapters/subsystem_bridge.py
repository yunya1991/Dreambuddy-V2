"""
SubSystemBridge — 桥接 polling_trader 中已有的子交易系统输出
SPEC §2.5

不新建采集器——polling_trader 已在 run_once 中计算了大量信号，
本桥接器只读已有状态，不触发新推理。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# war_state → Feynman 温度 T 映射 (蓝图 §1.5.5)
_WAR_STATE_TEMP: dict[str, float] = {
    "ALLOW": 1.0,
    "COOLDOWN": 0.5,
    "RESTRICT": 0.2,
    "FREEZE": 0.1,
}

# 市值尺度分类 (蓝图 §0.6)
_CLASSICAL = {"BTC", "ETH", "BNB"}
_MESO = {
    "SOL", "XRP", "ADA", "AVAX", "DOT", "LINK",
    "MATIC", "UNI", "LTC", "NEAR", "ARB", "OP",
}

# BCRM direction → 进化架构 direction 映射
_BCRM_DIR_MAP: dict[str, str] = {
    "UP": "long",
    "DOWN": "short",
    "FLAT": "",
}


class SubSystemBridge:
    """从 polling_trader 实例提取子交易系统信号"""

    def __init__(self, trader: Any = None) -> None:
        self._trader = trader

    # ---------------------------------------------------------- war_state
    def get_war_state(self) -> str:
        """获取五计庙算 war_state"""
        try:
            if self._trader is None:
                return "ALLOW"
            # 影子模式优先（真实计算值）
            _fds = (
                getattr(self._trader, "_five_domain_state_shadow", None)
                or getattr(self._trader, "_five_domain_state_cache", None)
            )
            if _fds is None:
                return "ALLOW"
            ws = _fds.war_state if hasattr(_fds, "war_state") else _fds.get("war_state", {})
            if isinstance(ws, dict):
                return ws.get("crypto_usdt", "ALLOW")
            return "ALLOW"
        except Exception:
            return "ALLOW"

    def get_ess_temperature(self) -> float:
        """war_state → Feynman 温度 T"""
        return _WAR_STATE_TEMP.get(self.get_war_state(), 1.0)

    # ---------------------------------------------------------- BCRM direction
    def get_bcrm_direction(self) -> str:
        """获取 BCRM2 最新推理方向"""
        try:
            if self._trader is None:
                return ""
            result = getattr(self._trader, "_last_bcrm2_result", None)
            if not result:
                return ""
            next_state = result.get("next_state") if isinstance(result, dict) else None
            if not next_state:
                return ""
            d = next_state.get("direction", "FLAT") if isinstance(next_state, dict) else "FLAT"
            return _BCRM_DIR_MAP.get(d, "")
        except Exception:
            return ""

    def get_bcrm_confidence(self) -> float:
        """获取 BCRM2 最新推理置信度"""
        try:
            if self._trader is None:
                return 0.0
            result = getattr(self._trader, "_last_bcrm2_result", None)
            if not result:
                return 0.0
            next_state = result.get("next_state") if isinstance(result, dict) else None
            if not next_state:
                return 0.0
            return float(next_state.get("confidence", 0.0))
        except Exception:
            return 0.0

    # ---------------------------------------------------------- scale_class
    @staticmethod
    def get_scale_class(symbol: str) -> str:
        """市值尺度分类"""
        sym = symbol.upper()
        if sym in _CLASSICAL:
            return "Classical"
        if sym in _MESO:
            return "Meso"
        return "Quantum"

    # ---------------------------------------------------------- BDSM valuation
    def get_bdsm_valuation(self) -> float:
        """获取 BDSM 估值分位（R_capital 代理）"""
        try:
            if self._trader is None:
                return 0.5
            snapshot = getattr(self._trader, "_last_bdsm_snapshot", None)
            if not snapshot:
                return 0.5
            return float(snapshot.get("valuation_percentile", 0.5))
        except Exception:
            return 0.5
