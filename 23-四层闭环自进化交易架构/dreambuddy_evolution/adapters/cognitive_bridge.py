"""
CognitiveBridge — 桥接认知记忆系统（CognitiveLoopEntry）
SPEC §2.6 + §7

Phase 3 预留接口（≥2000 交易样本后解冻 L3/L4）。
当前提供 recall/record/verify/record_ripple 能力，FAIL-OPEN 降级。

对接点:
  §0.7  涟漪原型写入   → record_ripple()     (RI≥0.75 持续 24h)
  §1.6.3 CBR 先验       → recall_similar()    (开仓前)
  §1.6.3 反思后验证     → verify_prediction()  (平仓后 CS 计算)
  §1.10 自动标注        → record_trade()      (交易结算)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# CBR 中性降级值
_CBR_NEUTRAL = {"cbr_sim": 0.5, "cbr_top1_outcome": "NEUTRAL", "cbr_top1_id": ""}


class CognitiveBridge:
    """认知系统桥接器（Phase 3 预留）"""

    def __init__(self, db_path: str | None = None, enabled: bool = True) -> None:
        self._db_path = db_path
        self._enabled = enabled
        self._entry: Any = None  # CognitiveLoopEntry 实例（懒加载）

    # ---------------------------------------------------------- CBR 检索
    def recall_similar(self, r_vector: dict[str, Any], action: str) -> dict[str, Any]:
        """
        从认知记忆库检索相似案例 → CBR 先验。

        Args:
            r_vector: R 向量 dict
            action: 方向 "long"/"short"

        Returns:
            {cbr_sim: float, cbr_top1_outcome: str, cbr_top1_id: str}
            FAIL-OPEN: 返回中性值
        """
        if not self._enabled:
            return dict(_CBR_NEUTRAL)

        try:
            entry = self._get_entry()
            if entry is None:
                return dict(_CBR_NEUTRAL)

            r_up = r_vector.get("R_up", 0.5)
            r_down = r_vector.get("R_down", 0.5)
            context = (
                f"R_up={r_up}, R_down={r_down}, action={action}"
            )
            results = entry.recall(context, top_k=3, min_quality="C")

            if not results:
                return dict(_CBR_NEUTRAL)

            top1 = results[0]
            return {
                "cbr_sim": float(top1.get("score", 0.5)),
                "cbr_top1_outcome": self._extract_outcome(top1),
                "cbr_top1_id": top1.get("id", ""),
            }

        except Exception as e:
            logger.debug("[FO] cognitive recall crash: %s", e)
            return dict(_CBR_NEUTRAL)

    # ---------------------------------------------------------- 记录交易
    def record_trade(self, snapshot: dict[str, Any], outcome: dict[str, Any]) -> str | None:
        """
        交易结算后记录经验到认知系统。

        Args:
            snapshot: 开仓快照
            outcome: 结算结果 {real_outcome, cs, memory_id?}

        Returns:
            memory_id 或 None（FAIL-OPEN）
        """
        if not self._enabled:
            return None

        try:
            entry = self._get_entry()
            if entry is None:
                return None

            symbol = snapshot.get("symbol", "?")
            d_star = snapshot.get("level0_dstar", "?")
            real_outcome = outcome.get("real_outcome", "?")
            cs = outcome.get("cs", 0.0)
            pnl_pct = outcome.get("pnl_pct", 0.0)

            content = (
                f"[trade] symbol={symbol} d*={d_star} "
                f"outcome={real_outcome} CS={cs:.4f} pnl={pnl_pct:.4f}"
            )
            memory_id = entry.record(
                content=content,
                quality_level="B",
                confidence=0.4,
                tags=["trade", "evolution", "l1-reflection"],
                source="evolution-trade",
            )
            logger.info("[COG] record_trade → %s", memory_id)
            return memory_id

        except Exception as e:
            logger.debug("[FO] record_trade crash: %s", e)
            return None

    # ---------------------------------------------------------- 验证预测
    def verify_prediction(self, memory_id: str, success: bool) -> dict[str, Any] | None:
        """
        验证预测准确性 → 贝叶斯置信度更新。

        Args:
            memory_id: 认知记忆 ID
            success: 预测是否正确

        Returns:
            verify 结果 dict 或 None
        """
        if not self._enabled or not memory_id:
            return None

        try:
            entry = self._get_entry()
            if entry is None:
                return None
            result = entry.verify(memory_id=memory_id, success=success)
            logger.info("[COG] verify_prediction %s success=%s", memory_id, success)
            return result
        except Exception as e:
            logger.debug("[FO] verify_prediction crash: %s", e)
            return None

    # ---------------------------------------------------------- 涟漪原型
    def record_ripple(self, snapshot: dict[str, Any]) -> str | None:
        """
        RI≥0.75 持续 24h → 写入「市场结构簇中心」。

        Args:
            snapshot: 涟漪快照 {symbol, r_vector, ri, duration_hours}

        Returns:
            memory_id 或 None
        """
        if not self._enabled:
            return None

        try:
            entry = self._get_entry()
            if entry is None:
                return None

            symbol = snapshot.get("symbol", "?")
            ri = snapshot.get("ri", 0.0)
            r_vec = snapshot.get("r_vector", {})
            content = (
                f"[ripple] symbol={symbol} RI={ri:.4f} "
                f"R_up={r_vec.get('R_up', '?')} R_down={r_vec.get('R_down', '?')} "
                f"持续={snapshot.get('duration_hours', 0)}h"
            )
            memory_id = entry.record(
                content=content,
                quality_level="B",
                confidence=0.5,
                tags=["ripple", "market-structure", "evolution"],
                source="evolution-ripple",
            )
            logger.info("[COG] record_ripple → %s", memory_id)
            return memory_id

        except Exception as e:
            logger.debug("[FO] record_ripple crash: %s", e)
            return None

    # ---------------------------------------------------------- 内部
    def _get_entry(self) -> Any:
        """懒加载 CognitiveLoopEntry"""
        if self._entry is not None:
            return self._entry

        try:
            import sys as _sys
            from pathlib import Path

            # 4-MEMORY/9-工具与接口 加入 path
            _tools_dir = None
            if self._db_path:
                _tools_dir = str(Path(self._db_path).parents[1] / "9-工具与接口")
            if not _tools_dir or not Path(_tools_dir).exists():
                # 从项目根推导
                _root = Path(__file__).resolve().parents[4]  # dreambuddy-v2/
                _tools_dir = str(_root / "4-MEMORY" / "9-工具与接口")

            if _tools_dir not in _sys.path:
                _sys.path.insert(0, _tools_dir)

            from cognitive_loop_entry import CognitiveLoopEntry  # type: ignore

            if self._db_path:
                self._entry = CognitiveLoopEntry(storage_path=self._db_path)
            else:
                self._entry = CognitiveLoopEntry()
            return self._entry

        except Exception as e:
            logger.warning("[FO] CognitiveLoopEntry load fail: %s", e)
            self._entry = None
            return None

    @staticmethod
    def _extract_outcome(memory: dict) -> str:
        """从记忆 content 中提取交易结果标签"""
        try:
            content = str(memory.get("content", ""))
            if "TP" in content or "profit" in content.lower():
                return "TP"
            if "SL" in content or "loss" in content.lower():
                return "SL"
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"
