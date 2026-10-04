"""WashoutCaseLibrary — 洗盘/真弱势闭环案例库 (CBR/KNN 检索).

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §5.3

W4 阶段落地 (纯新增, 零回归):
  - WashoutCase dataclass: 闭环案例 (入场/出场快照 + 盈亏分类)
  - WashoutCaseLibrary: 案例入库 + KNN 欧氏距离检索

设计原则 (硬约束):
  - HC-2: KNN/CBR + 贝叶斯闭环 (禁用 LLM, 本文件纯数值计算无 LLM 依赖)
  - reward = tanh(pnl_pct / 0.02) 归一化 [-1, 1] (自进化硬约束)
  - FAIL-OPEN: knn_search 异常 → 返回空列表, 不抛错

双时间点案例闭合 (用户偏好):
  - entry_time + exit_time 双快照
  - actual_label 闭环后真实标签 ("washout" / "weakness")
  - features_snapshot 12+1 维特征 (F1-F13)
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

__all__ = ["WashoutCase", "WashoutCaseLibrary"]

logger = logging.getLogger(__name__)

# 默认案例库目录: {project_root}/4-MEMORY/data/evolution_cases/
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent.parent
_DEFAULT_CASES_DIR = str(_PROJECT_ROOT / "4-MEMORY" / "data" / "evolution_cases")


# ============================================================
# WashoutCase 数据结构 (§5.3)
# ============================================================
@dataclass
class WashoutCase:
    """洗盘/真弱势闭环案例.

    Attributes:
        case_id: 案例唯一 ID
        coin: 币种符号
        entry_time: 入场时间 (ISO 8601 UTC)
        exit_time: 出场时间 (闭环时间, ISO 8601 UTC)
        features_snapshot: 12+1 维特征快照 (F1-F13)
        actual_label: 闭环后真实标签 ("washout" / "weakness")
        pnl_pct: 闭环盈亏百分比 (如 0.05 = +5%, -0.03 = -3%)
        reward: tanh(pnl_pct / 0.02) 归一化 [-1, 1]
        timestamp: 案例入库时间 (ISO 8601 UTC)
    """
    case_id: str
    coin: str
    entry_time: str
    exit_time: str
    features_snapshot: Dict[str, float]
    actual_label: str  # "washout" / "weakness"
    pnl_pct: float
    reward: float
    timestamp: str

    def __post_init__(self):
        # features_snapshot 深拷贝避免外部 mutation
        object.__setattr__(self, "features_snapshot", dict(self.features_snapshot))
        # actual_label 标准化为小写
        object.__setattr__(self, "actual_label", str(self.actual_label).lower())
        # reward 边界裁剪 [-1, 1]
        r = float(self.reward)
        if r < -1.0:
            r = -1.0
        elif r > 1.0:
            r = 1.0
        object.__setattr__(self, "reward", r)

    @staticmethod
    def compute_reward(pnl_pct: float) -> float:
        """reward = tanh(pnl_pct / 0.02) 归一化到 [-1, 1].

        硬约束: 自进化系统矛盾反馈用真实 PnL 作为 reward 信号.
        """
        return math.tanh(float(pnl_pct) / 0.02)


# ============================================================
# WashoutCaseLibrary 案例库
# ============================================================
class WashoutCaseLibrary:
    """洗盘/真弱势案例库 (CBR/KNN 检索).

    用法:
        lib = WashoutCaseLibrary()
        lib.add(case)
        neighbors = lib.knn_search(query_features, k=5)
    """

    def __init__(
        self,
        persist_path: Optional[str] = None,
        use_env_path: bool = False,
        library_name: str = "washout",
    ):
        self._cases: List[WashoutCase] = []
        self._index: Dict[str, WashoutCase] = {}  # case_id → case

        if use_env_path:
            cases_dir = os.environ.get("EVOLUTION_CASES_DIR", _DEFAULT_CASES_DIR)
            persist_path = str(Path(cases_dir) / f"{library_name}.json")

        self.persist_path = persist_path
        if self.persist_path:
            self.load(self.persist_path)

    def add(self, case: WashoutCase) -> None:
        """案例入库. case_id 重复时覆盖旧案例. 自动 save 如果 persist_path 设置."""
        if not isinstance(case, WashoutCase):
            logger.warning("WashoutCaseLibrary.add: 非 WashoutCase 类型, 忽略")
            return
        # 移除旧 case (如果 case_id 已存在)
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
            logger.warning("WashoutCaseLibrary.save FAIL-OPEN: %s", e)

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
            logger.warning("WashoutCaseLibrary.load FAIL-OPEN: %s", e)

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
            k > 库大小 → 返回全部案例.

        距离计算:
            欧氏距离 = sqrt(sum((q[key] - c[key])^2))
            使用 query 和 case.features_snapshot 的 key 并集,
            缺失的 key 填 0.0.

        FAIL-OPEN:
            异常 → 返回空列表, 不抛错.
        """
        try:
            if not self._cases or k <= 0:
                return []

            # 计算 query 与每个 case 的欧氏距离
            distances: List[Tuple[float, WashoutCase]] = []
            for case in self._cases:
                d = self._euclidean_distance(query, case.features_snapshot)
                distances.append((d, case))

            # 按距离升序稳定排序 (相同距离保持入库顺序)
            distances.sort(key=lambda x: x[0])

            # 返回前 k 个 (k > 库大小则返回全部)
            return distances[:k]
        except Exception as e:
            logger.debug("WashoutCaseLibrary.knn_search FAIL-OPEN: %s", e)
            return []

    @staticmethod
    def _euclidean_distance(
        a: Dict[str, float],
        b: Dict[str, float],
    ) -> float:
        """计算两个特征 dict 的欧氏距离.

        使用 key 并集, 缺失 key 填 0.0.
        空特征 → 距离 0.0 (视为完全相似).
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
