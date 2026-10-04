"""PumpDumpReversalCaseLibrary — 拉高出货做空案例库 (CBR/KNN).

阶段2 新增 (纯新增):
  - 复用 WashoutCase 结构
  - actual_label: reversal_short_success / reversal_short_fail
  - 独立于 WashoutReversalCaseLibrary (标签语义不同)
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .washout_case_library import WashoutCase

__all__ = ["PumpDumpReversalCaseLibrary"]

logger = logging.getLogger(__name__)

# 默认案例库目录: {project_root}/4-MEMORY/data/evolution_cases/
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent.parent
_DEFAULT_CASES_DIR = str(_PROJECT_ROOT / "4-MEMORY" / "data" / "evolution_cases")

_MIN_CASES = 30


class PumpDumpReversalCaseLibrary:
    """拉高出货做空案例库 (镜像 WashoutReversalCaseLibrary)."""

    def __init__(
        self,
        min_cases: int = _MIN_CASES,
        persist_path: Optional[str] = None,
        use_env_path: bool = False,
        library_name: str = "pump_dump_reversal",
    ):
        self._cases: List[WashoutCase] = []
        self._index: Dict[str, WashoutCase] = {}
        self.min_cases = max(1, int(min_cases))

        if use_env_path:
            cases_dir = os.environ.get("EVOLUTION_CASES_DIR", _DEFAULT_CASES_DIR)
            persist_path = str(Path(cases_dir) / f"{library_name}.json")

        self.persist_path = persist_path
        if self.persist_path:
            self.load(self.persist_path)

    def add(self, case: WashoutCase) -> None:
        """案例入库. 自动 save 如果 persist_path 设置."""
        if not isinstance(case, WashoutCase):
            logger.warning("PumpDumpReversalCaseLibrary.add: 非 WashoutCase, 忽略")
            return
        if case.case_id in self._index:
            try:
                self._cases.remove(self._index[case.case_id])
            except ValueError:
                pass
        self._cases.append(case)
        self._index[case.case_id] = case

        if self.persist_path:
            self.save()

    # ============================================================
    # JSON 持久化 (阶段1: 打破冷启动死锁)
    # ============================================================
    def save(self, path: Optional[str] = None) -> None:
        """保存案例库到 JSON. FAIL-OPEN: 异常 → 仅日志, 不抛错."""
        target = path or self.persist_path
        if not target:
            return
        try:
            p = Path(target)
            p.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(c) for c in self._cases]
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("PumpDumpReversalCaseLibrary.save FAIL-OPEN: %s", e)

    def load(self, path: str) -> None:
        """从 JSON 加载案例库. FAIL-OPEN: 文件不存在/损坏 → 空库."""
        try:
            p = Path(path)
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            for item in data:
                case = WashoutCase(**item)
                if case.case_id in self._index:
                    try:
                        self._cases.remove(self._index[case.case_id])
                    except ValueError:
                        pass
                self._cases.append(case)
                self._index[case.case_id] = case
        except Exception as e:
            logger.warning("PumpDumpReversalCaseLibrary.load FAIL-OPEN: %s", e)

    def get(self, case_id: str) -> Optional[WashoutCase]:
        return self._index.get(case_id)

    def all(self) -> List[WashoutCase]:
        return list(self._cases)

    def __len__(self) -> int:
        return len(self._cases)

    def __contains__(self, case_id: str) -> bool:
        return case_id in self._index

    def knn_search(self, query: Dict[str, float], k: int = 5
                   ) -> List[Tuple[float, WashoutCase]]:
        try:
            if not self._cases or k <= 0:
                return []
            distances = [(self._euclidean_distance(query, c.features_snapshot), c)
                         for c in self._cases]
            distances.sort(key=lambda x: x[0])
            return distances[:k]
        except Exception as e:
            logger.debug("PumpDumpReversalCaseLibrary.knn_search FAIL-OPEN: %s", e)
            return []

    @staticmethod
    def _euclidean_distance(a: Dict[str, float], b: Dict[str, float]) -> float:
        if not a and not b:
            return 0.0
        keys = set(a.keys()) | set(b.keys())
        sum_sq = 0.0
        for key in keys:
            d = float(a.get(key, 0.0)) - float(b.get(key, 0.0))
            sum_sq += d * d
        return math.sqrt(sum_sq)

    def count_by_label(self, label: str) -> int:
        return sum(1 for c in self._cases if c.actual_label == label.lower())

    def is_ready_for_knn(self) -> bool:
        return len(self._cases) >= self.min_cases
