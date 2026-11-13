"""
SubSystemBridge — 桥接 polling_trader 中已有的子交易系统输出
SPEC §2.5

不新建采集器——polling_trader 已在 run_once 中计算了大量信号，
本桥接器只读已有状态，不触发新推理。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 42 神经网络交易协调层 bus_state.json 路径（多源信号汇聚总线）
_REPO_ROOT = Path(__file__).resolve().parents[3]
_42_BUS_STATE_PATH = _REPO_ROOT / "42-神经网络交易协调层" / "runtime" / "bus_state.json"

# 43 战略承接推演层 strategic_extension_signal.json 路径（42 bus 不可用时的 fallback）
_43_STRATEGIC_PATH = (
    _REPO_ROOT / "43-战略承接推演层" / "runtime" / "strategic_extension_signal.json"
)

# 43 war_state（ACTIVE/FREEZE）→ 11 五域 war_state（ALLOW/COOLDOWN/RESTRICT/FREEZE）归一映射
# 43 signal_publisher 用 ACTIVE/FREEZE；strategic_mapper 用 ALLOW/COOLDOWN/FREEZE
_43_TO_CANONICAL_WAR_STATE: dict[str, str] = {
    "ACTIVE": "ALLOW",
    "ALLOW": "ALLOW",
    "COOLDOWN": "COOLDOWN",
    "RESTRICT": "RESTRICT",
    "FREEZE": "FREEZE",
}

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
    "SOL",
    "XRP",
    "ADA",
    "AVAX",
    "DOT",
    "LINK",
    "MATIC",
    "UNI",
    "LTC",
    "NEAR",
    "ARB",
    "OP",
}

# BCRM direction → 进化架构 direction 映射
_BCRM_DIR_MAP: dict[str, str] = {
    "UP": "long",
    "DOWN": "short",
    "FLAT": "",
}


class SubSystemBridge:
    """从 polling_trader 实例提取子交易系统信号"""

    def __init__(self, trader: Any = None, bus_state_path: str | Path | None = None) -> None:
        self._trader = trader
        self._bus_state_path = Path(bus_state_path) if bus_state_path else _42_BUS_STATE_PATH

    # ---------------------------------------------------------- 42 总线
    def _load_bus_state(self) -> dict:
        """读取 42 bus_state.json（多源信号汇聚）。FAIL-OPEN → 空结构。"""
        try:
            if not self._bus_state_path.exists():
                return {"signals": []}
            with open(self._bus_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.debug("[FO] load 42 bus_state fail: %s", e)
        return {"signals": []}

    def get_bus_signals(self, source: str | None = None) -> list[dict]:
        """从 42 总线获取信号列表，可按 source 过滤。"""
        state = self._load_bus_state()
        signals = state.get("signals", []) if isinstance(state, dict) else []
        if source:
            return [s for s in signals if s.get("source") == source]
        return signals

    # ---------------------------------------------------------- 43 战略承接
    def get_strategic_extension(self, cls: str = "crypto_usdt") -> dict:
        """读取 43 战略承接推演层的 per_asset_class 约束（war_state / tier / position_band 等）。

        优先级：42 bus（source=strategic_extension）→ 43 直读文件 → {}（FAIL-OPEN）。
        返回 payload.per_asset_class[cls] 字典；缺失/异常返回 {}。

        注：仅当使用默认 42 bus 路径时才回退到 43 直读文件；
        自定义 bus_state_path（隔离测试环境）不回退，避免读到线上 43 stale 信号。
        """
        try:
            # 1) 42 bus
            for sig in self.get_bus_signals():
                if str(sig.get("source", "")) == "strategic_extension":
                    pac = (sig.get("payload") or {}).get("per_asset_class", {})
                    if isinstance(pac, dict) and cls in pac:
                        return dict(pac[cls])
            # 2) 43 直读文件 fallback（仅默认 bus 路径时）
            if self._bus_state_path == _42_BUS_STATE_PATH and _43_STRATEGIC_PATH.exists():
                with open(_43_STRATEGIC_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                pac = (data.get("payload") or {}).get("per_asset_class", {})
                if isinstance(pac, dict) and cls in pac:
                    return dict(pac[cls])
        except Exception as e:
            logger.debug("[FO] get_strategic_extension fail: %s", e)
        return {}

    def get_position_band_upper_pct(self, cls: str = "crypto_usdt") -> float:
        """43 position_band 上限（0.0~1.0）。"0-20%"→0.20, "0%"→0.0, "80-100%"→1.0。FAIL-OPEN→1.0。"""
        try:
            ext = self.get_strategic_extension(cls)
            band = str(ext.get("position_band", "") or "")
            if not band:
                return 1.0
            # 取最后一个百分号前的数值作为上限
            import re as _re

            nums = [float(x) for x in _re.findall(r"(\d+(?:\.\d+)?)", band)]
            if not nums:
                return 1.0
            return max(0.0, min(1.0, nums[-1] / 100.0))
        except Exception:
            return 1.0

    def get_macro_mult(self, cls: str = "crypto_usdt") -> float:
        """宏观仓位乘数 = 43 position_band 上限（0.0~1.0）。
        乘数链：position_mult = base × regime_mult × macro_mult（13 position_modifier 最终钳位）。
        FAIL-OPEN → 1.0（不收紧）。
        """
        return self.get_position_band_upper_pct(cls)

    # ---------------------------------------------------------- war_state
    def get_war_state(self) -> str:
        """获取 war_state。

        优先级（T7：11 五域已实质废弃，43 为唯一事实源）：
        1. 43 strategic_extension.war_state（经 42 bus 或直读文件），归一化为 canonical 值
        2. 11 五域 _five_domain_state_shadow（仅当 43 不可用时的 fallback）
        3. FAIL-OPEN → "ALLOW"
        """
        try:
            # 1) 43 战略承接（唯一事实源）
            ext = self.get_strategic_extension()
            ws_43 = str(ext.get("war_state", "") or "").upper()
            if ws_43:
                return _43_TO_CANONICAL_WAR_STATE.get(ws_43, "ALLOW")
            # 2) 11 五域 fallback（已废弃，仅兼容）
            if self._trader is not None:
                _fds = getattr(self._trader, "_five_domain_state_shadow", None) or getattr(
                    self._trader, "_five_domain_state_cache", None
                )
                if _fds is not None:
                    ws = _fds.war_state if hasattr(_fds, "war_state") else _fds.get("war_state", {})
                    if isinstance(ws, dict):
                        return ws.get("crypto_usdt", "ALLOW")
        except Exception:
            pass
        return "ALLOW"

    def get_ess_temperature(self) -> float:
        """war_state → Feynman 温度 T"""
        return _WAR_STATE_TEMP.get(self.get_war_state(), 1.0)

    # ---------------------------------------------------------- BCRM direction
    def get_bcrm_direction(self) -> str:
        """获取 BCRM2 最新推理方向（优先 trader 状态，回退 42 总线）"""
        try:
            if self._trader is not None:
                result = getattr(self._trader, "_last_bcrm2_result", None)
                if result:
                    next_state = result.get("next_state") if isinstance(result, dict) else None
                    if next_state:
                        d = (
                            next_state.get("direction", "FLAT")
                            if isinstance(next_state, dict)
                            else "FLAT"
                        )
                        return _BCRM_DIR_MAP.get(d, "")
            # 回退 42 总线（source=bcrm / 11-bcrm）
            for sig in self.get_bus_signals():
                src = str(sig.get("source", ""))
                if "bcrm" in src.lower():
                    return str(sig.get("direction", "")).lower()
        except Exception:
            pass
        return ""

    def get_bcrm_confidence(self) -> float:
        """获取 BCRM2 最新推理置信度（优先 trader 状态，回退 42 总线）"""
        try:
            if self._trader is not None:
                result = getattr(self._trader, "_last_bcrm2_result", None)
                if result:
                    next_state = result.get("next_state") if isinstance(result, dict) else None
                    if next_state:
                        return float(next_state.get("confidence", 0.0))
            for sig in self.get_bus_signals():
                if "bcrm" in str(sig.get("source", "")).lower():
                    return float(sig.get("confidence", 0.0))
        except Exception:
            pass
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
        """获取 BDSM 估值分位（R_capital 代理）（优先 trader，回退 42 总线）"""
        try:
            if self._trader is not None:
                snapshot = getattr(self._trader, "_last_bdsm_snapshot", None)
                if snapshot:
                    return float(snapshot.get("valuation_percentile", 0.5))
            for sig in self.get_bus_signals():
                if "bdsm" in str(sig.get("source", "")).lower():
                    return float(sig.get("confidence", 0.5))
        except Exception:
            pass
        return 0.5

    # ---------------------------------------------------------- five_scores
    def get_five_scores(self, cls: str = "crypto_usdt") -> dict:
        """获取五计庙算五维原始评分（dao/di/tian/jiang/fa）。

        优先级：43 strategic_extension.five_scores → 11 五域 fallback → 全50（FAIL-OPEN）。
        """
        try:
            # 1) 43 战略承接（唯一事实源）
            ext = self.get_strategic_extension(cls)
            fs_43 = ext.get("five_scores")
            if isinstance(fs_43, dict) and fs_43:
                return {
                    "dao": int(fs_43.get("dao", 50)),
                    "di": int(fs_43.get("di", 50)),
                    "tian": int(fs_43.get("tian", 50)),
                    "jiang": int(fs_43.get("jiang", 50)),
                    "fa": int(fs_43.get("fa", 50)),
                }
            # 2) 11 五域 fallback（已废弃，仅兼容）
            if self._trader is not None:
                _fds = getattr(self._trader, "_five_domain_state_shadow", None) or getattr(
                    self._trader, "_five_domain_state_cache", None
                )
                if _fds is not None:
                    fs = (
                        _fds.five_scores
                        if hasattr(_fds, "five_scores")
                        else _fds.get("five_scores", {})
                    )
                    if isinstance(fs, dict) and cls in fs:
                        return dict(fs[cls])
        except Exception:
            pass
        return {"dao": 50, "di": 50, "tian": 50, "jiang": 50, "fa": 50}

    # ---------------------------------------------------------- position_cap
    def get_position_cap(self, cls: str = "crypto_usdt") -> float:
        """获取战略层仓位上限。

        优先级：43 position_band 上限 → 11 五域 aggregate_position_cap_pct → 1.0（FAIL-OPEN）。
        """
        try:
            # 1) 43 position_band 上限
            cap_43 = self.get_position_band_upper_pct(cls)
            if cap_43 < 1.0:
                return cap_43
            # 2) 11 五域 fallback（已废弃，仅兼容）
            if self._trader is not None:
                _fds = getattr(self._trader, "_five_domain_state_shadow", None) or getattr(
                    self._trader, "_five_domain_state_cache", None
                )
                if _fds is not None:
                    cap = (
                        _fds.aggregate_position_cap_pct
                        if hasattr(_fds, "aggregate_position_cap_pct")
                        else _fds.get("aggregate_position_cap_pct", {})
                    )
                    if isinstance(cap, dict) and cls in cap:
                        return float(cap[cls])
        except Exception:
            pass
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
            _fds = getattr(self._trader, "_five_domain_state_shadow", None) or getattr(
                self._trader, "_five_domain_state_cache", None
            )
            if _fds is None:
                return "NEUTRAL"
            br = getattr(_fds, "btc_regime", None) if hasattr(_fds, "btc_regime") else None
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
            _fds = getattr(self._trader, "_five_domain_state_shadow", None) or getattr(
                self._trader, "_five_domain_state_cache", None
            )
            if _fds is None:
                return "NEUTRAL"
            ds = (
                getattr(_fds, "direction_state", None) if hasattr(_fds, "direction_state") else None
            )
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
            _fds = getattr(self._trader, "_five_domain_state_shadow", None) or getattr(
                self._trader, "_five_domain_state_cache", None
            )
            if _fds is None:
                return 0.0
            db = getattr(_fds, "direction_bias", None) if hasattr(_fds, "direction_bias") else None
            if isinstance(db, dict):
                return float(db.get(cls, 0.0))
            return 0.0
        except Exception:
            return 0.0
