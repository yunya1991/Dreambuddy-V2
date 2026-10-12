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

    def __init__(self, db_path: str | None = None, enabled: bool = True,
                 mask_override_path: str | None = None) -> None:
        self._db_path = db_path
        self._enabled = enabled
        self._entry: Any = None  # CognitiveLoopEntry（懒加载）
        # P2-1b: factor_head_mask 微调 override 持久化路径（None → 默认 gene_data）
        if mask_override_path:
            self._mask_override_path = mask_override_path
        else:
            from pathlib import Path as _Path
            self._mask_override_path = str(
                _Path(__file__).resolve().parents[1] / "gene_data"
                / "factor_head_mask_override.json"
            )

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
        # P2-1b: mask override 更新独立于认知库可用性（wrong_dims 来自 derive_result）
        _wrong_dims_early = list(getattr(derive_result, "wrong_dimensions", []) or [])
        if _wrong_dims_early:
            self._update_mask_override(_wrong_dims_early)
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
    # factor_head_mask 微调（P2-1b 接线）
    # ------------------------------------------------------------------
    def _update_mask_override(self, wrong_dims: list[str]) -> None:
        """逆向推导判定错误维度 → FactorHeadMaskFineTuner 降权 → 持久化 override.

        override JSON 结构: {dimension: multiplier}，multiplier ∈ [0.1, 1.0]。
        应用方: core/exogenous_data_bridge.build_factor_head_mask 构建时把
        wrong_dim head 行允许值 0.0 → log(multiplier)（additive attention bias 抑制）。
        FAIL-OPEN: 任何异常只记 debug，不阻塞认知入库主流程。
        """
        try:
            import json as _json
            from pathlib import Path as _Path

            from dreambuddy_evolution.engines.factor_head_mask_fine_tuner import (
                FactorHeadMaskFineTuner,
            )

            path = _Path(self._mask_override_path)
            current: dict = {}
            if path.exists():
                try:
                    current = _json.loads(path.read_text())
                    if not isinstance(current, dict):
                        current = {}
                except Exception:
                    current = {}  # 损坏 → 重建
            # 首次出现的维度初始化 1.0，再交给 tuner 统一降权
            for dim in wrong_dims:
                current.setdefault(str(dim), 1.0)

            adjusted = FactorHeadMaskFineTuner().adjust(current, list(wrong_dims))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_json.dumps(adjusted, ensure_ascii=False, indent=2))
            logger.info(
                "[ReverseCog] mask_override updated: wrong_dims=%s → %s",
                wrong_dims, {d: adjusted.get(d) for d in wrong_dims},
            )
        except Exception as e:
            logger.debug("[FO] _update_mask_override fail: %s", e)

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
