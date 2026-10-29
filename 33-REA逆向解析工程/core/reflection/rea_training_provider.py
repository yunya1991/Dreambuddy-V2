"""REA 训练案例 Provider — 输出训练闭环接线（SPEC §6.3）。

将反思层训练案例库（training_cases）对接 34 系统主动训练采集器
的 TrainingDataProvider 协议：
- 历史项目案例冷启动：系统已开发项目案例作为初始训练语料
- 增量采集：按 created_at 时间戳增量，新增案例走增量训练
- 质量门控：无证据引用不入库（TrainingCaseRecord.passes_gate）
- 负样本 100% 入库（不静默丢弃）
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
for _p in (_PROJECT_ROOT,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.reflection.training_cases import TrainingCaseRecord, TrainingCaseStore

# 默认训练案例库路径（工程内）
DEFAULT_CASE_STORE = os.path.join(
    _PROJECT_ROOT, "reflection_data", "training_cases.jsonl"
)


class REATrainingCaseProvider:
    """REA 训练案例 Provider（对齐 TrainingDataProvider 协议）。

    协议方法以鸭子类型实现（避免硬依赖 34 系统导入路径），
    采集器通过 get_source_name/fetch_cases/get_quality_threshold 调用。
    """

    def __init__(self, store_path: str = DEFAULT_CASE_STORE):
        self.store = TrainingCaseStore(store_path)

    def get_source_name(self) -> str:
        return "rea_output_scenarios"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> list:
        """增量采集训练案例：since 之后的案例优先返回。

        返回 TrainingCaseRecord 列表（采集器侧再做质量门控与 TDR 映射）。
        """
        cases = self.store.load_all()
        if since:
            cases = [c for c in cases if c.created_at > since]
        # 质量门控前置过滤（无证据引用不入库）
        cases = [c for c in cases if c.passes_gate()]
        return cases[-limit:] if limit else cases

    def get_quality_threshold(self) -> str:
        return "B"

    def to_training_case(self, record: TrainingCaseRecord):
        """TrainingCaseRecord → 34 系统 TrainingCase 映射（TDR 字段对齐）。

        映射（SPEC §6.2）：
        - intent → intent
        - payload 动作序列 → actions
        - 执行结果 → outcome_text
        - label/poe_score → quality/confidence
        - case_type → layer_tags
        """
        quality = "A" if record.label == "positive" else "B"
        confidence = max(0.1, min(1.0, record.poe_score))
        actions = [
            f"{record.case_type}",
            f"label={record.label}",
        ]
        outcome = (
            f"poe_score={record.poe_score:.2f}, "
            f"evidence_refs={len(record.evidence_refs)}"
        )
        learned = [
            f"case_type={record.case_type}",
            f"label={record.label}",
        ]
        return {
            "intent": record.intent,
            "actions": actions,
            "outcome_text": outcome,
            "learned": learned,
            "layer_tags": [f"rea_{record.case_type}"],
            "quality": quality,
            "confidence": confidence,
            "source": self.get_source_name(),
            "metadata": {
                "case_type": record.case_type,
                "label": record.label,
                "poe_score": record.poe_score,
                "evidence_refs": record.evidence_refs,
                "created_at": record.created_at,
            },
        }
