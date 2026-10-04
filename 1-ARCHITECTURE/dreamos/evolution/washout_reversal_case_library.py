"""WashoutReversalCaseLibrary — 洗盘反转做多案例库 (CBR/KNN 检索).

Spec: docs/superpowers/specs/2026-09-22-washout-reversal-genome-design.md §3.2

阶段1 新增 (纯新增, 零回归):
  - 复用 WashoutCase 结构 (case_id/coin/entry/exit/features/label/pnl/reward/timestamp)
  - actual_label: reversal_long_success / reversal_long_fail
  - KNN: 欧氏距离 + key 并集缺失填 0.0 + 稳定排序
  - 降级规则: 案例库 < min_cases=30 → 走规则化 EndingDetector

设计原则 (硬约束):
  - HC-G4: 案例库 <30 时走规则化 EndingDetector
  - reward = tanh(pnl_pct/0.02) 归一化 [-1, 1] (复用 WashoutCase.compute_reward)
  - FAIL-OPEN: knn_search 异常 → 返回空列表, 不抛错
  - 禁用 LLM, 纯数值计算
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

__all__ = ["WashoutReversalCaseLibrary"]

logger = logging.getLogger(__name__)

# 默认案例库目录: {project_root}/4-MEMORY/data/evolution_cases/
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent.parent
_DEFAULT_CASES_DIR = str(_PROJECT_ROOT / "4-MEMORY" / "data" / "evolution_cases")

_MIN_CASES = 30  # 案例库 < 30 → 降级规则化


class WashoutReversalCaseLibrary:
    """洗盘反转做多案例库 (CBR/KNN 检索).

    复用 WashoutCase 结构, actual_label 使用:
      - reversal_long_success: 反转做多成功
      - reversal_long_fail: 反转做多失败

    用法:
        lib = WashoutReversalCaseLibrary()
        lib.add(case)
        neighbors = lib.knn_search(query_features, k=5)
        if len(lib) >= lib.min_cases:
            # KNN 路径
        else:
            # 降级规则化
    """

    def __init__(
        self,
        min_cases: int = _MIN_CASES,
        persist_path: Optional[str] = None,
        use_env_path: bool = False,
        library_name: str = "washout_reversal",
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
        """案例入库. case_id 重复时覆盖旧案例. 自动 save 如果 persist_path 设置."""
        if not isinstance(case, WashoutCase):
            logger.warning("WashoutReversalCaseLibrary.add: 非 WashoutCase 类型, 忽略")
            return
        if case.case_id in self._index:
            old = self._index[case.case_id]
            try:
                self._cases.remove(old)
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
            logger.warning("WashoutReversalCaseLibrary.save FAIL-OPEN: %s", e)

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
                    old = self._index[case.case_id]
                    try:
                        self._cases.remove(old)
                    except ValueError:
                        pass
                self._cases.append(case)
                self._index[case.case_id] = case
        except Exception as e:
            logger.warning("WashoutReversalCaseLibrary.load FAIL-OPEN: %s", e)

    def get(self, case_id: str) -> Optional[WashoutCase]:
        """通过 case_id 检索案例. 不存在返回 None."""
        return self._index.get(case_id)

    def all(self) -> List[WashoutCase]:
        """返回所有案例 (按入库顺序)."""
        return list(self._cases)

    def __len__(self) -> int:
        return len(self._cases)

    def __contains__(self, case_id: str) -> bool:
        return case_id in self._index

    # ============================================================
    # KNN 检索 (欧氏距离)
    # ============================================================
    def knn_search(
        self,
        query: Dict[str, float],
        k: int = 5,
    ) -> List[Tuple[float, WashoutCase]]:
        """KNN 检索 top-k 相似案例.

        Args:
            query: 查询特征快照 (Dict[str, float])
            k: 返回的最近邻数量

        Returns:
            List[(distance, WashoutCase)] 按距离升序排列.
            库为空或 k<=0 → 返回空列表.

        FAIL-OPEN:
            异常 → 返回空列表, 不抛错.
        """
        try:
            if not self._cases or k <= 0:
                return []

            distances: List[Tuple[float, WashoutCase]] = []
            for case in self._cases:
                d = self._euclidean_distance(query, case.features_snapshot)
                distances.append((d, case))

            distances.sort(key=lambda x: x[0])
            return distances[:k]
        except Exception as e:
            logger.debug("WashoutReversalCaseLibrary.knn_search FAIL-OPEN: %s", e)
            return []

    @staticmethod
    def _euclidean_distance(
        a: Dict[str, float],
        b: Dict[str, float],
    ) -> float:
        """计算两个特征 dict 的欧氏距离.

        使用 key 并集, 缺失 key 填 0.0.
        空特征 → 距离 0.0.
        """
        if not a and not b:
            return 0.0
        keys = set(a.keys()) | set(b.keys())
        sum_sq = 0.0
        for key in keys:
            av = float(a.get(key, 0.0))
            bv = float(b.get(key, 0.0))
            diff = av - bv
            sum_sq += diff * diff
        return math.sqrt(sum_sq)

    # ============================================================
    # 统计辅助 (自进化用)
    # ============================================================
    def count_by_label(self, label: str) -> int:
        """统计指定 actual_label 的案例数."""
        return sum(1 for c in self._cases if c.actual_label == label.lower())

    def is_ready_for_knn(self) -> bool:
        """案例库是否足够走 KNN 路径 (≥ min_cases)."""
        return len(self._cases) >= self.min_cases
