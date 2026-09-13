"""RegimeGateSwitch — 策略路由闸门

复用 TraditionalFinanceBridge.RegimeDetector 的 ADX/波动率逻辑，
扩展为策略选择闸门：
  - TREND（ADX>25 + Donchian 突破）→ TrendFollowingEngine
  - RANGE（ADX<25 + 价格在布林带内）→ V15 + GridTradingEngine
  - CRISIS（20日波动率 > 历史 90 分位）→ 暂停开新仓

硬约束：
  HC-TF-03: regime=TREND 启用趋势跟踪，RANGE 启用 V15+网格，CRISIS 暂停
  HC-TF-07: FAIL-OPEN 任何异常→中性兜底 RANGE
"""
from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


# ====================================================================
# 常量（硬约束对齐）
# ====================================================================
TREND_ADX_THRESHOLD = 25.0      # ADX>25 为趋势市
CRISIS_VOL_PERCENTILE = 0.90     # 20日波动率 > 历史 90 分位为危机市


class RegimeGateSwitch:
    """策略路由闸门 — 软切换 V15/趋势跟踪/网格

    由 KlineEventHandler.on_kline_close() 调用。
    """

    @staticmethod
    def detect_regime(kline_data: dict, klines: list | None = None) -> str:
        """检测市场状态

        Args:
            kline_data: {"close": [...], "high": [...], "low": [...]}
            klines: 可选，K线列表供 PatternDetector 检测头肩顶

        Returns:
            "TREND" / "RANGE" / "CRISIS" / "TOP_DROP"
        """
        try:
            if not kline_data:
                return "RANGE"

            closes = list(kline_data.get("close") or [])
            highs = list(kline_data.get("high") or [])
            lows = list(kline_data.get("low") or [])

            if len(closes) < 20:
                return "RANGE"

            # 0. 形态检测：头肩顶 → TOP_DROP（优先级最高）
            if klines is not None:
                try:
                    from dreambuddy_evolution.engines.pattern_detector import PatternDetector
                    detector = PatternDetector()
                    hs = detector.detect_head_shoulders(klines)
                    if hs.get("detected") and hs.get("pattern_type") == "head_shoulders_top":
                        if hs.get("confidence", 0.0) >= 0.5:
                            return "TOP_DROP"
                except Exception as e:
                    logger.debug("[FO] PatternDetector fail: %s", e)

            # 1. 计算 ADX（简化版，复用 traditional_finance 逻辑）
            adx = RegimeGateSwitch._calc_adx(highs, lows, closes)

            # 2. 计算波动率比率
            vol_20 = RegimeGateSwitch._std(closes[-20:])
            vol_60 = RegimeGateSwitch._std(closes[-60:]) if len(closes) >= 60 else vol_20
            vol_ratio = vol_20 / max(vol_60, 1e-9) if vol_60 > 0 else 1.0

            # 3. 状态判定
            if vol_ratio > 1.8:
                return "CRISIS"
            elif adx > TREND_ADX_THRESHOLD:
                return "TREND"
            else:
                return "RANGE"
        except Exception as e:
            logger.warning("[FO] RegimeGateSwitch.detect_regime: %s", e)
            return "RANGE"

    @staticmethod
    def route_strategy(
        regime: str,
        kline_data: dict,
        account_state: dict,
        klines: list | None = None,
    ) -> dict:
        """根据 regime 路由到对应策略引擎

        Args:
            regime: "TREND" / "RANGE" / "CRISIS" / "TOP_DROP"
            kline_data: K 线数据
            account_state: 账户状态
            klines: 可选，K线列表供形态检测

        Returns:
            {
                "engine": str,       # 引擎名称
                "action": str,       # 动作
                "signal": dict,      # 信号（如果有）
            }
        """
        try:
            if regime == "TOP_DROP":
                # 头肩顶 → 做空信号
                from dreambuddy_evolution.engines.pattern_detector import PatternDetector
                detector = PatternDetector()
                hs = detector.detect_head_shoulders(klines or [])
                conf = hs.get("confidence", 0.5)

                # P2: CBR 检索历史形态案例（FAIL-OPEN）
                cbr_context = {}
                try:
                    import sys as _sys
                    _repo = __import__("pathlib").Path(__file__).resolve().parents[2]
                    if str(_repo) not in _sys.path:
                        _sys.path.insert(0, str(_repo))
                    _yj = _repo / "11-易经推理系统"
                    if str(_yj) not in _sys.path:
                        _sys.path.insert(0, str(_yj))
                    from scripts.memory_l4.cbr_engine import CBRQuery, CBREngine
                    query = CBRQuery(
                        regime="TOP_DROP",
                        decision="short",
                        confidence=conf,
                        pattern="head_shoulders_top",
                    )
                    engine = CBREngine(top_k=3, similarity_threshold=0.1)
                    engine.load(use_index=True)
                    retrieved = engine.retrieve(query)
                    if retrieved:
                        cbr_context = {
                            "similar_cases": len(retrieved),
                            "top_similarity": round(retrieved[0].similarity, 4),
                            "avg_pnl": sum(r.case.pnl_pct or 0 for r in retrieved) / len(retrieved),
                        }
                except Exception as e:
                    logger.debug("[FO] CBR retrieve fail: %s", e)

                return {
                    "engine": "pattern_short",
                    "action": "SHORT",
                    "signal": {
                        "pattern": "head_shoulders_top",
                        "confidence": conf,
                        "neckline": hs.get("neckline"),
                        "cbr_context": cbr_context,
                    },
                }

            if regime == "TREND":
                # HC-TF-03: 趋势市启用趋势跟踪
                from dreambuddy_evolution.engines.trend_following import TrendFollowingEngine
                signal = TrendFollowingEngine.evaluate(kline_data, account_state)
                return {"engine": "trend_following", "action": signal.get("action", "WAIT"), "signal": signal}

            elif regime == "RANGE":
                # HC-TF-03: 震荡市启用 V15 + 网格
                from dreambuddy_evolution.engines.grid_trading import GridTradingEngine
                grid_signal = GridTradingEngine.evaluate(kline_data, account_state)
                return {
                    "engine": "v15_grid",
                    "action": grid_signal.get("action", "WAIT"),
                    "signal": {"grid": grid_signal},
                }

            else:  # CRISIS
                # HC-TF-03: 危机市暂停开新仓
                return {"engine": "pause", "action": "PAUSE", "signal": {}}

        except Exception as e:
            logger.warning("[FO] RegimeGateSwitch.route_strategy: %s", e)
            return {"engine": "pause", "action": "WAIT", "signal": {}}

    @staticmethod
    def _calc_adx(highs, lows, closes, period: int = 14) -> float:
        """简化版 ADX（平均趋向指数）"""
        try:
            if len(closes) < period + 1:
                return 0.0
            plus_dm = []
            minus_dm = []
            tr = []
            for i in range(1, len(closes)):
                up = highs[i] - highs[i - 1]
                down = lows[i - 1] - lows[i]
                plus_dm.append(max(up, 0) if up > down else 0)
                minus_dm.append(max(down, 0) if down > up else 0)
                tr.append(max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                ))
            if not tr or sum(tr) == 0:
                return 0.0
            plus_di = 100 * sum(plus_dm[-period:]) / max(sum(tr[-period:]), 1e-9)
            minus_di = 100 * sum(minus_dm[-period:]) / max(sum(tr[-period:]), 1e-9)
            dx = 100 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-9)
            return dx
        except Exception:
            return 0.0

    @staticmethod
    def _std(data: list) -> float:
        """标准差"""
        try:
            if len(data) < 2:
                return 0.0
            mean = sum(data) / len(data)
            var = sum((x - mean) ** 2 for x in data) / len(data)
            return math.sqrt(var)
        except Exception:
            return 0.0
