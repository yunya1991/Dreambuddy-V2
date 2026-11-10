"""ASIL D3 Adapter — 接入 DreamOS IntentEngine 真实调用（规则基线）。

Phase 2：从 Phase 1 mock 升级为真实 IntentEngine.recognize() 调用。
use_llm_based=False → 零 Token、零 API key、纯规则基线。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

# 路径设置（和 d3_intent_engine_loader.py 一致）
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_ARCH_DIR = _REPO_ROOT / "1-ARCHITECTURE"
if str(_ARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ARCH_DIR))
# 48-涌现架构
_ASIL_ROOT = Path(__file__).resolve().parent.parent
if str(_ASIL_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASIL_ROOT))


@dataclass
class D3IntentResult:
    """D3 意图识别结果（ASIL 侧规范化 schema）。"""

    intent_type: str = ""
    confidence: float = 0.0
    recommended_chain: list = None
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_type": self.intent_type,
            "confidence": self.confidence,
            "recommended_chain": self.recommended_chain or [],
            "rationale": self.rationale,
        }


class D3Adapter:
    """D3 IntentEngine 适配器 — 真实调用 + 降级 fallback。"""

    def __init__(self, use_llm_based: bool = False):
        self.use_llm_based = use_llm_based
        self._engine = None
        self._engine_available = False
        self._init_engine()

    def _init_engine(self) -> None:
        """惰性初始化 IntentEngine，失败不阻塞 ASIL。"""
        try:
            from baselines.d3_intent_engine_loader import load_intent_engine

            self._engine = load_intent_engine(use_llm_based=self.use_llm_based)
            self._engine_available = True
        except Exception:
            self._engine_available = False

    def is_available(self) -> bool:
        return self._engine_available

    def recognize(
        self,
        user_message: str,
        market: Optional[Dict[str, Any]] = None,
    ) -> D3IntentResult:
        """调用 IntentEngine.recognize()，失败返回 fallback。"""
        if not self._engine_available or self._engine is None:
            return self._fallback(user_message)

        market = market or {}
        try:
            result = self._engine.recognize(user_message=user_message, market=market)
            return D3IntentResult(
                intent_type=getattr(result, "intent_type", "unknown"),
                confidence=getattr(result, "confidence", 0.0),
                recommended_chain=getattr(result, "recommended_chain", []),
                rationale=getattr(result, "rationale", ""),
            )
        except Exception:
            return self._fallback(user_message)

    def _fallback(self, user_message: str) -> D3IntentResult:
        """引擎不可用时的启发式 fallback（规则关键词匹配）。"""
        msg = user_message.lower()
        if any(k in msg for k in ("trend", "趋势", "follow", "方向")):
            intent = "TREND_FOLLOWING"
        elif any(k in msg for k in ("mean", "回归", "revert")):
            intent = "MEAN_REVERSION"
        elif any(k in msg for k in ("breakout", "突破", "range")):
            intent = "BREAKOUT"
        else:
            intent = "GENERAL_ANALYSIS"
        return D3IntentResult(intent_type=intent, confidence=0.25)

    # ------------------------------------------------------------------
    # SPEC §3.2 R5 process_reward 启发式子目标检查
    # ------------------------------------------------------------------
    def check_r5_subgoal(self, recall_count: int) -> float:
        """Query step 子目标：recall 命中数 ≥ 5 → 通过。"""
        return 1.0 if recall_count >= 5 else 0.0
