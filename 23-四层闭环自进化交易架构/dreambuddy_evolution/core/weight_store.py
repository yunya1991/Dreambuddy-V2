"""WeightStore — 权重持久化组件

从 evolution_pipeline.py _load_weight_factors/_save_weight_factors/_get_wf_for_dim 抽出。
按维度独立的矛盾权重字典 + JSON 持久化。
FAIL-OPEN: 文件不存在或解析失败 → 空 dict；写入失败不阻断。
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class WeightStore:
    """按维度独立的矛盾权重持久化。

    职责：
    - load(): 从 JSON 加载矛盾权重
    - save(): 持久化矛盾权重到 JSON
    - get(dim): 获取指定维度的权重因子
    - atomic_update(dim, value): 原子更新单个维度权重
    """

    DEFAULT_PERSIST_PATH = REPO_ROOT / "dreambuddy_evolution" / "data" / "weight_factors.json"

    def __init__(self, gene_root: Path | str | None = None, persist_path: Path | None = None):
        if persist_path is not None:
            self._persist_path = persist_path
        elif gene_root is not None:
            self._persist_path = Path(gene_root) / "data" / "weight_factors.json"
        else:
            self._persist_path = self.DEFAULT_PERSIST_PATH
        self._weight_factors: dict[str, float] = {}

    def load(self) -> dict[str, float]:
        """从 JSON 加载按维度独立的矛盾权重。FAIL-OPEN: 文件不存在或解析失败 → 空 dict。"""
        try:
            if self._persist_path.exists():
                data = json.loads(self._persist_path.read_text(encoding="utf-8"))
                self._weight_factors = {
                    str(k): max(0.3, min(1.5, float(v)))
                    for k, v in data.items()
                }
                logger.debug("[WF] 加载 %d 个维度权重: %s",
                             len(self._weight_factors),
                             list(self._weight_factors.keys()))
            else:
                self._weight_factors = {}
        except Exception as e:
            logger.debug("[FO] WeightStore.load crash: %s", e)
            self._weight_factors = {}
        return self._weight_factors

    def save(self) -> None:
        """持久化矛盾权重到 JSON。FAIL-OPEN: 写入失败不阻断。"""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps(self._weight_factors, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("[FO] WeightStore.save crash: %s", e)

    def get(self, dim: str) -> float:
        """获取指定维度的权重因子，默认 1.0。"""
        return self._weight_factors.get(dim, 1.0)

    def atomic_update(self, dim: str, value: float) -> float:
        """原子更新单个维度权重（更新 + 持久化）。"""
        clamped = max(0.3, min(1.5, float(value)))
        self._weight_factors[dim] = clamped
        self.save()
        return clamped

    @property
    def weight_factors(self) -> dict[str, float]:
        """只读访问权重字典"""
        return dict(self._weight_factors)
