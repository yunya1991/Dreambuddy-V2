"""ReverseCaseStore — 逆向推导错误案例库。

P2 §5.2: 错误案例入库，标注 {wrong_dim, root_cause}，
下次类似场景（相同 wrong_dim 模式）降权或避开。

案例结构:
  case_id, timestamp, symbol, action, wrong_dimensions,
  root_cause, root_cause_type, confidence, outcome, snapshot_summary

设计原则:
  1. 仅入库有错误维度的案例（正确案例不污染错误案例库）
  2. JSON 持久化，支持跨实例加载
  3. 按 wrong_dim / 维度模式检索
  4. 维度错误频次统计（供 ParameterReverseOptimizer 使用）
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class ReverseCaseStore:
    """逆向推导错误案例库（JSON 持久化）。"""

    def __init__(self, storage_path: str | None = None) -> None:
        self._storage_path = storage_path or self._default_path()
        self._cases: list[dict[str, Any]] = []
        self._load()

    @staticmethod
    def _default_path() -> str:
        base = os.environ.get("DREAMBUDDY_DATA", ".")
        return os.path.join(base, "reverse_case_library.json")

    def _load(self) -> None:
        try:
            if os.path.exists(self._storage_path):
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    self._cases = json.load(f)
        except Exception as e:
            logger.warning("[ReverseCaseStore] load fail: %s", e)
            self._cases = []

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._storage_path) or ".", exist_ok=True)
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(self._cases, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("[ReverseCaseStore] save fail: %s", e)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def add_case(self, derive_result: Any, snapshot: dict[str, Any],
                 outcome: dict[str, Any]) -> str | None:
        """入库一个错误案例。

        Args:
            derive_result: ReverseDeriveResult（须含 wrong_dimensions）
            snapshot: 开仓快照
            outcome: 交易结果

        Returns:
            case_id（无错误维度时返回 None，不入库）
        """
        wrong_dims = list(getattr(derive_result, "wrong_dimensions", []) or [])
        if not wrong_dims:
            return None  # 正确案例不入库

        case = {
            "case_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": snapshot.get("symbol", ""),
            "action": snapshot.get("action", ""),
            "wrong_dimensions": wrong_dims,
            "root_cause": getattr(derive_result, "root_cause", ""),
            "root_cause_type": getattr(derive_result, "root_cause_type", "unknown"),
            "confidence": float(getattr(derive_result, "confidence", 0.0)),
            "optimization_action": getattr(derive_result, "optimization_action", ""),
            "real_outcome": outcome.get("real_outcome", ""),
            "real_direction": outcome.get("real_direction", ""),
            "snapshot_summary": {
                "level0_dstar": snapshot.get("level0_dstar", ""),
                "ess_dir": snapshot.get("ess_dir", ""),
                "cluster_id": snapshot.get("cluster_id", ""),
            },
        }
        self._cases.append(case)
        self._save()
        logger.info("[ReverseCaseStore] added case %s wrong_dims=%s",
                    case["case_id"][:8], wrong_dims)
        return case["case_id"]

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def query_by_wrong_dim(self, dim: str) -> list[dict[str, Any]]:
        """按错误维度检索案例。"""
        return [c for c in self._cases if dim in c.get("wrong_dimensions", [])]

    def query_similar(self, wrong_dims: list[str]) -> list[dict[str, Any]]:
        """相似案例检索：wrong_dims 有交集的案例（按交集大小倒序）。"""
        target = set(wrong_dims)
        scored = []
        for c in self._cases:
            overlap = len(target & set(c.get("wrong_dimensions", [])))
            if overlap > 0:
                scored.append((overlap, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored]

    def stats(self) -> dict[str, Any]:
        """案例统计：各维度错误频次 + 根因类型分布。"""
        dim_counts: dict[str, int] = {}
        cause_type_counts: dict[str, int] = {}
        for c in self._cases:
            for d in c.get("wrong_dimensions", []):
                dim_counts[d] = dim_counts.get(d, 0) + 1
            ct = c.get("root_cause_type", "unknown")
            cause_type_counts[ct] = cause_type_counts.get(ct, 0) + 1
        return {
            "total_cases": len(self._cases),
            "dim_error_counts": dim_counts,
            "root_cause_type_counts": cause_type_counts,
        }

    def count(self) -> int:
        return len(self._cases)

    def all_cases(self) -> list[dict[str, Any]]:
        return list(self._cases)
