"""ReverseCognitiveBridge — 逆向推导认知记忆集成。

P3 §6: 逆向推导输出 ReverseDeriveResult 复用 33-REA Evidence 结构，
统一入库认知记忆系统。

Evidence 结构:
  level: "derivation"（从观察推导）
  provenance: {snapshot_id, outcome_id, dimensions_checked}
  confidence: 0.0-1.0
  known_gaps: [...]
  root_cause / wrong_dimensions / root_cause_type
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class ReverseCognitiveBridge:
    """逆向推导 → 认知记忆桥接器.

    将 ReverseDeriveResult 转为 33-REA Evidence 结构并入库认知记忆。
    FAIL-OPEN: 认知入口不可用时返回 None，不阻塞交易流程。
    """

    def __init__(self, db_path: str | None = None, enabled: bool = True) -> None:
        self._db_path = db_path
        self._enabled = enabled
        self._entry: Any = None  # CognitiveLoopEntry（懒加载）

    # ------------------------------------------------------------------
    # Evidence 结构转换
    # ------------------------------------------------------------------
    def to_evidence(self, derive_result: Any, snapshot: dict[str, Any],
                    outcome: dict[str, Any]) -> dict[str, Any]:
        """将 ReverseDeriveResult 转为 33-REA Evidence 结构."""
        per_dim = getattr(derive_result, "per_dimension_correctness", {}) or {}
        return {
            "level": "derivation",
            "provenance": {
                "snapshot_id": snapshot.get("snapshot_id") or str(uuid.uuid4()),
                "outcome_id": outcome.get("outcome_id") or str(uuid.uuid4()),
                "dimensions_checked": list(per_dim.keys()),
            },
            "confidence": float(getattr(derive_result, "confidence", 0.0)),
            "known_gaps": list(getattr(derive_result, "known_gaps", []) or []),
            "root_cause": getattr(derive_result, "root_cause", ""),
            "root_cause_type": getattr(derive_result, "root_cause_type", "unknown"),
            "wrong_dimensions": list(getattr(derive_result, "wrong_dimensions", []) or []),
            "optimization_action": getattr(derive_result, "optimization_action", ""),
            "symbol": snapshot.get("symbol", ""),
            "real_outcome": outcome.get("real_outcome", ""),
        }

    # ------------------------------------------------------------------
    # 认知记忆入库
    # ------------------------------------------------------------------
    def record_evidence(self, derive_result: Any, snapshot: dict[str, Any],
                        outcome: dict[str, Any]) -> str | None:
        """将逆向推导 Evidence 入库认知记忆.

        Returns:
            memory_id 或 None（FAIL-OPEN）
        """
        if not self._enabled:
            return None
        try:
            entry = self._get_entry()
            if entry is None:
                return None

            evidence = self.to_evidence(derive_result, snapshot, outcome)
            wrong_dims = evidence["wrong_dimensions"]
            content = (
                f"[reverse-derive] symbol={evidence['symbol']} "
                f"wrong_dims={wrong_dims} "
                f"root_cause_type={evidence['root_cause_type']} "
                f"confidence={evidence['confidence']:.2f} "
                f"action={evidence['optimization_action']}"
            )
            tags = ["reverse-derive", "方向3", evidence["root_cause_type"]]
            if wrong_dims:
                tags.extend(f"dim:{d}" for d in wrong_dims)

            memory_id = entry.record(
                content=content,
                quality_level="B",
                confidence=evidence["confidence"],
                tags=tags,
                source="reverse-derive",
            )
            logger.info("[ReverseCog] record_evidence → %s", memory_id)
            return memory_id
        except Exception as e:
            logger.debug("[FO] record_evidence crash: %s", e)
            return None

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _get_entry(self) -> Any:
        """懒加载 CognitiveLoopEntry（复用 cognitive_bridge 模式）。"""
        if self._entry is not None:
            return self._entry
        try:
            import sys as _sys
            from pathlib import Path

            _root = Path(__file__).resolve().parents[4]  # dreambuddy-v2/
            _tools_dir = str(_root / "4-MEMORY" / "9-工具与接口")
            if _tools_dir not in _sys.path:
                _sys.path.insert(0, _tools_dir)

            from cognitive_loop_entry import CognitiveLoopEntry  # type: ignore

            self._entry = (
                CognitiveLoopEntry(storage_path=self._db_path)
                if self._db_path
                else CognitiveLoopEntry()
            )
            return self._entry
        except Exception as e:
            logger.warning("[FO] CognitiveLoopEntry load fail: %s", e)
            self._entry = None
            return None
