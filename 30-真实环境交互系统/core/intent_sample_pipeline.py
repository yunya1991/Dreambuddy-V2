"""IntentSample 数据结构 + Pipeline（落盘 + 分桶 + 触发训练）

对齐 SPEC-20261004 §3.2 / §3.3 + SPEC-20260929 §2.1 IntentSample 格式。
HC-1a：本模块在 30 系统内，不修改 dreamos/。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class IntentSample:
    """意图识别训练样本

    字段（对齐 spec §3.2）：
    - sample_id: UUID
    - input: {user_query, scenario_id, market_features, data_freshness?}
    - gold: {gold_chain, gold_intent}  # gold_chain: C|F|A 三大思维链
    - recognizer_output: {predicted_intent, confidence, level}
    - human_label: {confirmed, corrected_intent?}
    - dataset_split: train | eval
    - created_at: ISO8601
    """
    sample_id: str
    input: Dict[str, Any]
    gold: Dict[str, str]
    recognizer_output: Dict[str, Any]
    human_label: Dict[str, Any]
    dataset_split: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentSample":
        return cls(**data)


class IntentSamplePipeline:
    """IntentSample 落盘 + 分桶统计 + 触发训练

    对齐 spec §3.3。构造参数化以便测试注入（storage_path/bucket_threshold/trigger_fn）。
    """

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        bucket_threshold: int = 30,
        distill_accuracy_target: float = 0.85,
        trigger_fn: Optional[Callable] = None,
    ):
        self.STORAGE_PATH = Path(storage_path) if storage_path else Path("30-真实环境交互系统/training/intent_samples/")
        self.BUCKET_THRESHOLD = bucket_threshold
        self.DISTILL_ACCURACY_TARGET = distill_accuracy_target
        self._trigger_fn = trigger_fn
        self._bucket_counter: Dict[Tuple[str, str], int] = defaultdict(int)
        self.STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    @property
    def bucket_counter(self) -> Dict[Tuple[str, str], int]:
        return self._bucket_counter

    def ingest(self, sample: IntentSample) -> None:
        """实时落盘 + 分桶统计（仅 train）+ 触发训练"""
        self._persist(sample)
        if sample.dataset_split != "train":
            return
        bucket_key = (sample.gold["gold_intent"], sample.input["scenario_id"])
        self._bucket_counter[bucket_key] += 1
        if self._bucket_counter[bucket_key] >= self.BUCKET_THRESHOLD:
            self._trigger_training(bucket_key)
            self._bucket_counter[bucket_key] = 0  # 触发后清零，避免重复

    def _persist(self, sample: IntentSample) -> None:
        bucket_dir = self.STORAGE_PATH / f"{sample.gold['gold_intent']}_{sample.input['scenario_id']}"
        bucket_dir.mkdir(parents=True, exist_ok=True)
        with open(bucket_dir / f"{sample.sample_id}.json", "w", encoding="utf-8") as f:
            json.dump(sample.to_dict(), f, ensure_ascii=False, indent=2)

    def _trigger_training(self, bucket_key: Tuple[str, str]) -> None:
        samples = self._load_bucket(bucket_key)
        accuracy = self._compute_accuracy(samples)
        if self._trigger_fn:
            self._trigger_fn(bucket_key, samples)
            return
        # 默认调用 IntentTrainer（Task 3 实现，懒导入避免循环依赖）
        from core.intent_trainer import IntentTrainer
        trainer = IntentTrainer()
        trainer.update_weights(bucket_key, samples)
        if accuracy >= self.DISTILL_ACCURACY_TARGET and len(samples) >= self.BUCKET_THRESHOLD:
            trainer.distill_to_rules(bucket_key, samples)
            trainer.refine_orchestration(bucket_key, samples)

    def load_split(self, split: str) -> List[IntentSample]:
        """加载指定 split 的所有样本（供 eval 回归门）"""
        results: List[IntentSample] = []
        if not self.STORAGE_PATH.exists():
            return results
        for bucket_dir in self.STORAGE_PATH.iterdir():
            if not bucket_dir.is_dir():
                continue
            for f in bucket_dir.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    if data.get("dataset_split") == split:
                        results.append(IntentSample.from_dict(data))
                except Exception:
                    continue
        return results

    def _load_bucket(self, bucket_key: Tuple[str, str]) -> List[IntentSample]:
        bucket_dir = self.STORAGE_PATH / f"{bucket_key[0]}_{bucket_key[1]}"
        if not bucket_dir.exists():
            return []
        results: List[IntentSample] = []
        for f in bucket_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    results.append(IntentSample.from_dict(json.load(fp)))
            except Exception:
                continue
        return results

    @staticmethod
    def _compute_accuracy(samples: List[IntentSample]) -> float:
        if not samples:
            return 0.0
        correct = sum(1 for s in samples if s.human_label.get("confirmed"))
        return correct / len(samples)
