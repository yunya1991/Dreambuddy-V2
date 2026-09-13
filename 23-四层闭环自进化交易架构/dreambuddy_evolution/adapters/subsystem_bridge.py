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

    # ---------------------------------------------------------- five_scores
    def get_five_scores(self, cls: str = "crypto_usdt") -> dict:
        """获取五计庙算五维原始评分（dao/di/tian/jiang/fa）。FAIL-OPEN → 全50。"""
        try:
            if self._trader is None:
                return {"dao": 50, "di": 50, "tian": 50, "jiang": 50, "fa": 50}
            _fds = (
                getattr(self._trader, "_five_domain_state_shadow", None)
                or getattr(self._trader, "_five_domain_state_cache", None)
            )
            if _fds is None:
                return {"dao": 50, "di": 50, "tian": 50, "jiang": 50, "fa": 50}
            fs = _fds.five_scores if hasattr(_fds, "five_scores") else _fds.get("five_scores", {})
            if isinstance(fs, dict) and cls in fs:
                return dict(fs[cls])
            return {"dao": 50, "di": 50, "tian": 50, "jiang": 50, "fa": 50}
        except Exception:
            return {"dao": 50, "di": 50, "tian": 50, "jiang": 50, "fa": 50}

    # ---------------------------------------------------------- position_cap
    def get_position_cap(self, cls: str = "crypto_usdt") -> float:
        """获取战略层仓位上限。FAIL-OPEN → 1.0。"""
        try:
            if self._trader is None:
                return 1.0
            _fds = (
                getattr(self._trader, "_five_domain_state_shadow", None)
                or getattr(self._trader, "_five_domain_state_cache", None)
            )
            if _fds is None:
                return 1.0
            cap = (
                _fds.aggregate_position_cap_pct
                if hasattr(_fds, "aggregate_position_cap_pct")
                else _fds.get("aggregate_position_cap_pct", {})
            )
            if isinstance(cap, dict) and cls in cap:
                return float(cap[cls])
            return 1.0
        except Exception:
            return 1.0

    # ---------------------------------------------------------- BCRM pattern
    def get_bcrm_pattern(self) -> dict:
        """获取 BCRM2 头肩形态检测结果。FAIL-OPEN → 中性。"""
        try:
            if self._trader is None:
                return {"hs_top": False, "hs_bottom": False, "confidence": 0.0}
            result = getattr(self._trader, "_last_bcrm2_result", None)
            if not result:
                return {"hs_top": False, "hs_bottom": False, "confidence": 0.0}
            next_state = result.get("next_state") if isinstance(result, dict) else None
            if not next_state or not isinstance(next_state, dict):
                return {"hs_top": False, "hs_bottom": False, "confidence": 0.0}
            return next_state.get(
                "pattern", {"hs_top": False, "hs_bottom": False, "confidence": 0.0}
            )
        except Exception:
            return {"hs_top": False, "hs_bottom": False, "confidence": 0.0}

    # ---------------------------------------------------------- btc_regime
    def get_btc_regime(self) -> str:
        """获取战略层 BTC 强弱 regime（STRONG/WEAK/NEUTRAL）。FAIL-OPEN → NEUTRAL。"""
        try:
            if self._trader is None:
                return "NEUTRAL"
            _fds = (
                getattr(self._trader, "_five_domain_state_shadow", None)
                or getattr(self._trader, "_five_domain_state_cache", None)
            )
            if _fds is None:
                return "NEUTRAL"
            br = (
                getattr(_fds, "btc_regime", None)
                if hasattr(_fds, "btc_regime")
                else None
            )
            if isinstance(br, dict):
                return br.get("crypto_usdt", "NEUTRAL")
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    def set_btc_regime(self, regime: str, cls: str = "crypto_usdt") -> None:
        """写回 BTC regime 到战略层 shadow 状态。FAIL-OPEN：trader/状态缺失 → 静默返回。

        NEUTRAL 不写回（避免覆盖已有真实值）。
        """
        try:
            if regime == "NEUTRAL":
                return  # 不覆盖
            if self._trader is None:
                return
            _fds = getattr(self._trader, "_five_domain_state_shadow", None)
            if _fds is None:
                return
            br = getattr(_fds, "btc_regime", None)
            if br is None:
                _fds.btc_regime = {}
                br = _fds.btc_regime
            if isinstance(br, dict):
                br[cls] = regime
        except Exception as e:
            logger.debug("[FO] set_btc_regime fail: %s", e)

    def attach_trader(self, trader: Any) -> None:
        """注入 trader 引用（用于 KlineEventHandler 创建 bridge 后补充注入）。"""
        self._trader = trader

    def get_direction_state(self, cls: str = "crypto_usdt") -> str:
        """获取战略层方向状态（LONG_ONLY/LONG_PREFER/NEUTRAL/SHORT_PREFER/SHORT_ONLY/FREEZE）。FAIL-OPEN → NEUTRAL。"""
        try:
            if self._trader is None:
                return "NEUTRAL"
            _fds = (
                getattr(self._trader, "_five_domain_state_shadow", None)
                or getattr(self._trader, "_five_domain_state_cache", None)
            )
            if _fds is None:
                return "NEUTRAL"
            ds = getattr(_fds, "direction_state", None) if hasattr(_fds, "direction_state") else None
            if isinstance(ds, dict):
                return ds.get(cls, "NEUTRAL")
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    def get_direction_bias(self, cls: str = "crypto_usdt") -> float:
        """获取战略层方向偏置分数（-100~+100，+看多/-看空）。FAIL-OPEN → 0.0。"""
        try:
            if self._trader is None:
                return 0.0
            _fds = (
                getattr(self._trader, "_five_domain_state_shadow", None)
                or getattr(self._trader, "_five_domain_state_cache", None)
            )
            if _fds is None:
                return 0.0
            db = getattr(_fds, "direction_bias", None) if hasattr(_fds, "direction_bias") else None
            if isinstance(db, dict):
                return float(db.get(cls, 0.0))
            return 0.0
        except Exception:
            return 0.0
