"""
CBR → BCRM 2.0 适配层

将 CBR 引擎的输出整合到 BCRM 2.0 决策流程中：
- 在 BCRM 生成信号后，调用 CBR 检索相似历史案例
- 用 CBR 的策略修正结果增强 BCRM 原始信号
- 输出融合后的最终交易决策
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from scripts.memory_l4.cbr_engine import CBRCase, CBREngine, CBRQuery, CBRCycleResult


@dataclass
class BCRMSignal:
    """BCRM 2.0 原始信号。"""
    inst_id: str
    direction: str              # long / short / flat
    confidence: float           # 0-1
    regime: Optional[str] = None
    volatility: float = 0.0
    current_price: float = 0.0
    suggested_leverage: float = 3.0
    suggested_position_pct: float = 0.1
    sl_atr: float = 2.0
    tp_atr: float = 3.0
    max_hold_bars: int = 60
    hexagram: Optional[str] = None
    evidence_chain: Dict[str, List[Dict]] = field(default_factory=dict)


@dataclass
class EnhancedSignal:
    """CBR 增强后的信号。"""
    inst_id: str
    direction: str
    confidence: float
    leverage: float
    position_pct: float
    sl_atr: float
    tp_atr: float
    max_hold_bars: int
    regime: Optional[str] = None
    # CBR 元数据
    cbr_similarity_top1: float = 0.0
    cbr_historical_win_rate: float = 0.0
    cbr_avg_pnl: float = 0.0
    cbr_risk_notes: List[str] = field(default_factory=list)
    cbr_revision_notes: List[str] = field(default_factory=list)
    # 融合标记
    fusion_method: str = "cbr_override"  # cbr_override / cbr_blend / bcrm_only


class CBRSignalEnhancer:
    """CBR 信号增强器：将 CBR 结果融入 BCRM 信号。"""

    def __init__(self, cbr_engine: Optional[CBREngine] = None):
        self.cbr = cbr_engine or CBREngine(use_sharded=True)

    def load(self) -> "CBRSignalEnhancer":
        self.cbr.load(use_index=True)
        return self

    def enhance(self, signal: BCRMSignal) -> EnhancedSignal:
        """用 CBR 增强 BCRM 信号。

        融合策略：
        1. 如果 CBR 历史胜率 > 60% 且 Top-1 相似度 > 0.5：信任 CBR，使用 cbr_override
        2. 如果 CBR 历史胜率 40-60%：混合 BCRM 和 CBR 参数（cbr_blend）
        3. 如果 CBR 历史胜率 < 40% 或无相似案例：降级为 BCRM 原始信号（bcrm_only）
        """
        query = CBRQuery(
            inst_id=signal.inst_id,
            regime=signal.regime,
            decision=signal.direction,
            confidence=signal.confidence,
            volatility=signal.volatility,
            entry_price=signal.current_price,
            evidence_chain=signal.evidence_chain,
        )

        result = self.cbr.cycle(query)

        # 判定融合策略
        win_rate = result.reuse.profit_rate
        top_sim = result.retrieved[0].similarity if result.retrieved else 0.0

        if win_rate > 0.6 and top_sim > 0.5:
            method = "cbr_override"
            final = self._cbr_override(signal, result)
        elif win_rate >= 0.4 or (not result.retrieved):
            method = "cbr_blend"
            final = self._cbr_blend(signal, result)
        else:
            method = "bcrm_only"
            final = self._bcrm_only(signal, result)

        return EnhancedSignal(
            inst_id=signal.inst_id,
            direction=signal.direction,
            confidence=final["confidence"],
            leverage=final["leverage"],
            position_pct=final["position_pct"],
            sl_atr=final["sl_atr"],
            tp_atr=final["tp_atr"],
            max_hold_bars=final["max_hold_bars"],
            regime=signal.regime,
            cbr_similarity_top1=round(top_sim, 3),
            cbr_historical_win_rate=round(win_rate, 3),
            cbr_avg_pnl=round(result.reuse.avg_pnl, 4),
            cbr_risk_notes=result.reuse.risk_notes,
            cbr_revision_notes=result.revise.revision_notes,
            fusion_method=method,
        )

    @staticmethod
    def _cbr_override(signal: BCRMSignal, result: CBRCycleResult) -> Dict[str, Any]:
        """CBR 完全覆盖：历史证据充分，信任 CBR 修正结果。"""
        r = result.revise
        return {
            "confidence": r.final_confidence,
            "leverage": r.final_leverage,
            "position_pct": r.final_position_pct,
            "sl_atr": r.final_sl_atr,
            "tp_atr": r.final_tp_atr,
            "max_hold_bars": r.final_hold_bars,
        }

    @staticmethod
    def _cbr_blend(signal: BCRMSignal, result: CBRCycleResult) -> Dict[str, Any]:
        """混合模式：BCRM 和 CBR 参数加权平均。
        权重按 CBR 历史胜率调整：胜率越高，CBR 权重越大。"""
        w = result.reuse.profit_rate  # 0.4 ~ 0.6
        # CBR 权重 = w, BCRM 权重 = 1 - w
        r = result.revise
        return {
            "confidence": round(signal.confidence * (1 - w) + r.final_confidence * w, 4),
            "leverage": round(signal.suggested_leverage * (1 - w) + r.final_leverage * w, 1),
            "position_pct": round(signal.suggested_position_pct * (1 - w) + r.final_position_pct * w, 4),
            "sl_atr": round(signal.sl_atr * (1 - w) + r.final_sl_atr * w, 2),
            "tp_atr": round(signal.tp_atr * (1 - w) + r.final_tp_atr * w, 2),
            "max_hold_bars": int(signal.max_hold_bars * (1 - w) + r.final_hold_bars * w),
        }

    @staticmethod
    def _bcrm_only(signal: BCRMSignal, result: CBRCycleResult) -> Dict[str, Any]:
        """BCRM 优先：历史证据不足或历史胜率低，使用原始信号。
        但置信度轻微下调（因为 CBR 给出了负面历史信号）。"""
        return {
            "confidence": round(signal.confidence * 0.95, 4),
            "leverage": signal.suggested_leverage,
            "position_pct": signal.suggested_position_pct,
            "sl_atr": signal.sl_atr,
            "tp_atr": signal.tp_atr,
            "max_hold_bars": signal.max_hold_bars,
        }


class CBRToBCRMBridge:
    """CBR 与 BCRM 2.0 的桥接器。

    集成点：
    1. BCRM2Adapter.predict() 后调用 enhance()
    2. PollingTrader 在下单前检查 CBR 增强结果
    3. 监控面板展示 CBR 历史对照
    """

    def __init__(self):
        self.enhancer: Optional[CBRSignalEnhancer] = None

    def initialize(self) -> "CBRToBCRMBridge":
        self.enhancer = CBRSignalEnhancer()
        self.enhancer.load()
        return self

    def enhance_bcrm_signal(self, bcrm_output: Dict[str, Any]) -> Dict[str, Any]:
        """将 BCRM 字典输出增强为包含 CBR 建议的字典。"""
        if self.enhancer is None:
            self.initialize()

        signal = BCRMSignal(
            inst_id=bcrm_output.get("inst_id", "UNKNOWN"),
            direction=bcrm_output.get("direction", "flat"),
            confidence=bcrm_output.get("confidence", 0.0),
            regime=bcrm_output.get("regime"),
            volatility=bcrm_output.get("volatility", 0.0),
            current_price=bcrm_output.get("current_price", 0.0),
            suggested_leverage=bcrm_output.get("suggested_leverage", 3.0),
            suggested_position_pct=bcrm_output.get("suggested_position_pct", 0.1),
            sl_atr=bcrm_output.get("sl_atr", 2.0),
            tp_atr=bcrm_output.get("tp_atr", 3.0),
            max_hold_bars=bcrm_output.get("max_hold_bars", 60),
            hexagram=bcrm_output.get("hexagram"),
            evidence_chain=bcrm_output.get("evidence_chain", {}),
        )

        enhanced = self.enhancer.enhance(signal)

        return {
            # BCRM 原始信号
            "bcrm_direction": enhanced.direction,
            "bcrm_confidence": signal.confidence,
            # CBR 增强后信号
            "direction": enhanced.direction,
            "confidence": enhanced.confidence,
            "leverage": enhanced.leverage,
            "position_pct": enhanced.position_pct,
            "sl_atr": enhanced.sl_atr,
            "tp_atr": enhanced.tp_atr,
            "max_hold_bars": enhanced.max_hold_bars,
            # CBR 元数据
            "cbr_similarity_top1": enhanced.cbr_similarity_top1,
            "cbr_historical_win_rate": enhanced.cbr_historical_win_rate,
            "cbr_avg_pnl": enhanced.cbr_avg_pnl,
            "cbr_risk_notes": enhanced.cbr_risk_notes,
            "cbr_revision_notes": enhanced.cbr_revision_notes,
            "cbr_fusion_method": enhanced.fusion_method,
        }
