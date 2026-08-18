#!/usr/bin/env python3
"""
双通道运行器 (Dual-Channel Runner)

P2-8 spec §4.2 执行层：在同一市场数据上并行运行左右脑通道，
通过胼胝体整合器输出最终决策。

左脑通道（分析型）：复用 chain_router 的 A0→A1→A2→A3 节点链
右脑通道（直觉型）：易经卦象 + 做梦部潜意识分析

依赖：
  - experiments/ab-trading/core/nodes/oneirology.py（做梦部，已内置）
  - 11-易经推理系统/scripts/memory_l4/bcrm/yijing_engine.py（易经，通过 bridge 注入）
"""
from __future__ import annotations
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any

from .corpus_callosum import CorpusCallosum, ChannelResult, IntegrationResult


# ── Yijing Bridge：注入 11-易经推理系统 路径 ──────────────────────
_YIJING_PATH = (
    Path(__file__).resolve().parents[4]
    / "11-易经推理系统" / "scripts"
)
if str(_YIJING_PATH) not in sys.path:
    sys.path.insert(0, str(_YIJING_PATH))

_YIJING_AVAILABLE = False
try:
    from memory_l4.bcrm.yijing_engine import YijingEngine as _YijingEngine
    _YIJING_AVAILABLE = True
except Exception:
    _YijingEngine = None


@dataclass
class DualChannelDecision:
    """双通道决策完整结果"""
    integration: IntegrationResult
    left_brain: ChannelResult
    right_brain: Optional[ChannelResult]
    yijing_raw: Optional[dict] = None
    oneirology_raw: Optional[dict] = None
    timestamp: str = ""

    @property
    def direction(self) -> str:
        return self.integration.direction

    @property
    def confidence(self) -> float:
        return self.integration.confidence

    @property
    def gate_passed(self) -> bool:
        return self.integration.gate_passed

    def to_dict(self) -> dict:
        return {
            "integration": self.integration.to_dict(),
            "left_brain": {
                "direction": self.left_brain.direction,
                "confidence": round(self.left_brain.confidence, 4),
                "source": self.left_brain.source,
            },
            "right_brain": {
                "direction": self.right_brain.direction if self.right_brain else None,
                "confidence": round(self.right_brain.confidence, 4) if self.right_brain else None,
                "source": self.right_brain.source if self.right_brain else None,
            } if self.right_brain else None,
            "yijing_hexagram": self.yijing_raw.get("hexagram_name_cn", "") if self.yijing_raw else "",
            "divergence_flag": self.integration.divergence_flag,
            "timestamp": self.timestamp,
        }


class DualChannelRunner:
    """
    双通道并行决策运行器

    用法：
        runner = DualChannelRunner()
        decision = runner.run(mkt_data, memory, left_brain_result)
    """

    def __init__(
        self,
        corpus_callosum: Optional[CorpusCallosum] = None,
        right_channel_enabled: bool = True,
    ):
        self.cc = corpus_callosum or CorpusCallosum()
        self.right_channel_enabled = right_channel_enabled
        self._yijing_engine: Optional[Any] = None
        if right_channel_enabled and _YIJING_AVAILABLE:
            try:
                self._yijing_engine = _YijingEngine()
            except Exception:
                self._yijing_engine = None

    # ── 主入口 ────────────────────────────────────────────────────

    def run(
        self,
        mkt: Dict,
        memory: Dict,
        left_result: ChannelResult,
        a0_direction: str = "HOLD",
    ) -> DualChannelDecision:
        """
        在同一市场数据上运行双通道并整合。

        Args:
            mkt: 市场数据（price, rsi14, change_24h, funding_rate, ...）
            memory: 记忆数据（recent_decisions, loss_streaks, ...）
            left_result: 左脑通道结果（由 chain_router A0-A3 链产出）
            a0_direction: A0 矛盾分析主导方向

        Returns:
            DualChannelDecision
        """
        from datetime import datetime, timezone

        right = None
        yijing_raw = None
        oneirology_raw = None

        if self.right_channel_enabled:
            # ── 右脑通道：易经 + 做梦部 ──────────────────────────
            yijing_ch = self._run_yijing_channel(mkt)
            dream_ch = self._run_oneirology_channel(mkt, memory)

            # 合并右脑两个子通道：取置信度更高的
            if yijing_ch and dream_ch:
                right = yijing_ch if yijing_ch.confidence >= dream_ch.confidence else dream_ch
                yijing_raw = yijing_ch.metadata
            elif yijing_ch:
                right = yijing_ch
                yijing_raw = yijing_ch.metadata
            elif dream_ch:
                right = dream_ch
                oneirology_raw = dream_ch.metadata

            # 如果做梦部有数据，保存它
            if dream_ch and dream_ch.metadata:
                oneirology_raw = dream_ch.metadata

        # ── 胼胝体整合 ────────────────────────────────────────────
        integration = self.cc.integrate(left_result, right, a0_direction)

        return DualChannelDecision(
            integration=integration,
            left_brain=left_result,
            right_brain=right,
            yijing_raw=yijing_raw,
            oneirology_raw=oneirology_raw,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ── 右脑子通道 ────────────────────────────────────────────────

    def _run_yijing_channel(self, mkt: Dict) -> Optional[ChannelResult]:
        """易经卦象通道：四维评分 → 卦象 → 方向 + 置信度"""
        if not self._yijing_engine:
            return None

        try:
            # 从市场数据提取四维评分
            supply_demand = self._score_supply_demand(mkt)
            technical = self._score_technical(mkt)
            capital_flow = self._score_capital_flow(mkt)
            sentiment = self._score_sentiment(mkt)

            result = self._yijing_engine.infer(
                supply_demand_score=supply_demand,
                technical_score=technical,
                capital_flow_score=capital_flow,
                sentiment_score=sentiment,
                trend_strength=mkt.get("trend_strength", 0.5),
                volatility=mkt.get("volatility", 0.5),
                volume_ratio=mkt.get("vol_ratio", 1.0),
                price_position=mkt.get("price_position", 0.5),
            )

            # 映射 direction_hint → LONG/SHORT/HOLD
            dir_map = {"UP": "LONG", "DOWN": "SHORT", "FLAT": "HOLD",
                       "TRANSITIONING": "HOLD", "UNKNOWN": "HOLD"}
            direction = dir_map.get(result.direction_hint, "HOLD")
            confidence = result.confidence

            return ChannelResult(
                direction=direction,
                confidence=confidence,
                source="yijing",
                reasoning=[
                    f"易经: {result.hexagram_name_cn} ({result.hexagram_name})",
                    f"方向: {result.direction_hint} → {direction}",
                    f"置信度: {confidence:.0%}",
                    f"风险等级: {result.risk_level}",
                ],
                metadata=result.to_dict(),
            )
        except Exception as e:
            return ChannelResult(
                direction="HOLD", confidence=0.0, source="yijing_error",
                reasoning=[f"易经引擎异常: {e}"],
            )

    def _run_oneirology_channel(self, mkt: Dict, memory: Dict) -> Optional[ChannelResult]:
        """做梦部通道：强迫性重复检测 + 反事实推演"""
        try:
            # 导入 ab-trading 内置的做梦部节点
            ab_core = Path(__file__).resolve().parents[1]
            if str(ab_core) not in sys.path:
                sys.path.insert(0, str(ab_core))
            from nodes.oneirology import execute as oneirology_execute

            result = oneirology_execute(mkt, memory, {})
            direction = result.get("direction", "HOLD")
            confidence = result.get("confidence", 0.5)
            hold_streak = result.get("hold_streak", 0)

            # 做梦部只在检测到强迫性重复时才有信号价值
            if hold_streak < 3:
                return ChannelResult(
                    direction="HOLD", confidence=0.4, source="oneirology",
                    reasoning=["做梦部: 无强迫性重复，无信号"],
                    metadata=result.get("pattern", {}),
                )

            return ChannelResult(
                direction=direction,
                confidence=confidence,
                source="oneirology",
                reasoning=result.get("rationale", [])[:5],
                metadata=result.get("pattern", {}),
            )
        except Exception as e:
            return ChannelResult(
                direction="HOLD", confidence=0.0, source="oneirology_error",
                reasoning=[f"做梦部异常: {e}"],
            )

    # ── 四维评分辅助（从市场数据推导）──────────────────────────────

    def _score_supply_demand(self, mkt: Dict) -> float:
        """供需评分：价格变动 + 成交量"""
        ch24 = mkt.get("change_24h", 0)
        vol_ratio = mkt.get("vol_ratio", 1.0)
        score = 0.5 + ch24 * 0.1 + (vol_ratio - 1.0) * 0.2
        return max(0.0, min(1.0, score))

    def _score_technical(self, mkt: Dict) -> float:
        """技术面评分：RSI + EMA 排列"""
        rsi = mkt.get("rsi14", 50)
        price = mkt.get("price", 0)
        ema20 = mkt.get("ema20", price)
        ema50 = mkt.get("ema50", price)

        score = 0.5
        if price > ema20 > ema50:
            score += 0.2
        elif price < ema20 < ema50:
            score -= 0.2
        score += (rsi - 50) * 0.005
        return max(0.0, min(1.0, score))

    def _score_capital_flow(self, mkt: Dict) -> float:
        """资金流评分：资金费率"""
        funding = mkt.get("funding_rate", 0)
        score = 0.5 - funding * 500  # 正费率=多头拥挤=降分
        return max(0.0, min(1.0, score))

    def _score_sentiment(self, mkt: Dict) -> float:
        """情绪面评分：RSI 极端 + 涨跌幅"""
        rsi = mkt.get("rsi14", 50)
        ch24 = mkt.get("change_24h", 0)
        score = 0.5 + (rsi - 50) * 0.008 + ch24 * 0.05
        return max(0.0, min(1.0, score))

    # ── 状态查询 ──────────────────────────────────────────────────

    def status(self) -> dict:
        """返回运行器状态（用于环境就绪度检查）"""
        return {
            "right_channel_enabled": self.right_channel_enabled,
            "yijing_available": _YIJING_AVAILABLE,
            "yijing_engine_active": self._yijing_engine is not None,
            "corpus_callosum": {
                "gate_threshold": self.cc.gate_threshold,
                "consensus_bonus": self.cc.consensus_bonus,
                "divergence_penalty": self.cc.divergence_penalty,
                "lr_consensus_penalty": self.cc.lr_consensus_penalty,
            },
        }
