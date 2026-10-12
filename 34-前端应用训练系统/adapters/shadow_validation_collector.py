"""ShadowValidation 采集器 — DSH 层 P4 进化链数据源.

从 shadow_validation/ 目录的 _samples.jsonl 文件提取 Shadow-RL 决策节点,
构造 DSH 层训练数据。

设计 (SPEC-DSH-训练数据源 v0.4 §6):
  - 扫描 shadow_validation/ 目录下 *_samples.jsonl 文件
  - 每条样本含 gene_id/direction/win/pnl_pct/hold_bars
  - 构造 node_sequence: sample_load → entry → hold → exit → pnl → outcome → validate
  - FAIL-OPEN: 损坏的 JSON 行跳过,目录不存在返回空

预期: 20-40 条 (每个基因文件采样2-3条)
"""
import json
import os
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

for _p in [_THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# 默认 shadow_validation 目录
_DEFAULT_SAMPLES_DIR = os.path.join(
    _PROJECT_ROOT,
    "23-四层闭环自进化交易架构",
    "dreambuddy_evolution",
    "gene_data",
    "shadow_validation",
)


class ShadowValidationCollector(TrainingDataProvider):
    """ShadowValidation 采集器 — DSH 层 P4 数据源。"""

    def __init__(self, samples_dir: Optional[str] = None):
        self.samples_dir = samples_dir or _DEFAULT_SAMPLES_DIR

    def get_source_name(self) -> str:
        return "shadow_validation"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从 shadow_validation 样本文件采集训练案例。

        每个基因文件采样前2-3条样本(避免单一基因过多)。

        Returns:
            训练案例列表 (FAIL-OPEN)
        """
        cases: List[TrainingCase] = []

        if not os.path.isdir(self.samples_dir):
            return cases

        try:
            sample_files = sorted([
                os.path.join(self.samples_dir, f)
                for f in os.listdir(self.samples_dir)
                if f.endswith("_samples.jsonl")
            ])
        except Exception:
            return cases

        for file_path in sample_files:
            if len(cases) >= limit:
                break
            file_cases = self._parse_samples_file(file_path, max_per_file=3)
            cases.extend(file_cases)

        return cases[:limit]

    def _parse_samples_file(
        self, file_path: str, max_per_file: int = 3
    ) -> List[TrainingCase]:
        """解析单个 _samples.jsonl 文件。

        每文件取前 max_per_file 条样本(覆盖不同基因)。

        FAIL-OPEN: 损坏的 JSON 行跳过。
        """
        cases: List[TrainingCase] = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if len(cases) >= max_per_file:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sample = json.loads(line)
                    except Exception:
                        continue  # FAIL-OPEN: 跳过损坏行

                    case = self._build_case(sample, file_path)
                    if case:
                        cases.append(case)
        except Exception:
            pass

        return cases

    def _build_case(self, sample: dict, file_path: str) -> Optional[TrainingCase]:
        """从样本构建 TrainingCase。"""
        gene_id = sample.get("gene_id", "unknown")
        direction = sample.get("direction", "unknown")
        win = sample.get("win", False)
        pnl_pct = sample.get("pnl_pct", 0.0)
        entry_price = sample.get("entry_price", 0)
        exit_price = sample.get("exit_price", 0)
        hold_bars = sample.get("hold_bars", 0)

        # 构造 node_sequence
        node_seq = [
            f"sample_load(gene={gene_id})",
            f"entry(direction={direction},price={entry_price})",
            f"hold(bars={hold_bars})",
            f"exit(price={exit_price})",
            f"pnl_compute(pct={pnl_pct:.4f})",
            f"outcome({'win' if win else 'loss'})",
            "validate",
        ]

        outcome = "success" if win else "failure"

        return TrainingCase(
            intent=f"shadow.{gene_id}",
            actions=node_seq,
            outcome_text=outcome,
            learned=[
                f"gene_id={gene_id}",
                f"direction={direction}",
                f"pnl={pnl_pct:.4f}",
                f"hold_bars={hold_bars}",
            ],
            layer_tags=["DSH"],
            quality="B",
            confidence=0.5 if win else 0.3,
            source=f"shadow_validation:{os.path.basename(file_path)}",
            metadata={
                "outcome": outcome,  # win→success, loss→failure (ground truth)
                "gene_id": gene_id,
                "direction": direction,
                "win": win,
                "pnl_pct": pnl_pct,
                "hold_bars": hold_bars,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "node_count": len(node_seq),
            },
        )
