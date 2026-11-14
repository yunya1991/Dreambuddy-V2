# -*- coding: utf-8 -*-
"""L1 意图 golden set 采集器 — 人工标注集接入训练链路。

数据源: 34-前端应用训练系统/l1_intent_golden.jsonl
  311 条人工标注（12 个 L1 意图 + unknown），字段 {message, intent, variant}。
  与 tests/test_l1_intent_golden.py 共用同一份数据：
    - 测试侧做回归门禁（准确率不退化）
    - 训练侧经本 Provider 进入 TDR（意图分类的训练语料）

设计:
  - 只读现有文件，不生成新样本（标注质量高于运行时日志推导）
  - FAIL-OPEN: 文件缺失/单行损坏均跳过，不阻塞 ActiveTrainingCollector
  - 增量: since 与文件 mtime 比较，文件未更新则返回空列表
"""

import json
import os
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)

from interfaces.training_data_provider import TrainingCase, TrainingDataProvider  # noqa: E402

GOLDEN_PATH = os.path.join(_34_DIR, "l1_intent_golden.jsonl")


class IntentGoldenCollector(TrainingDataProvider):
    """把人工标注的 L1 意图 golden set 转为 TrainingCase。"""

    def get_source_name(self) -> str:
        return "intent_golden"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        if not os.path.exists(GOLDEN_PATH):
            return []
        try:
            mtime_ms = str(int(os.path.getmtime(GOLDEN_PATH) * 1000))
        except OSError:
            return []
        # 增量: 文件未更新则无新案例（since 为上次采集时间戳，毫秒）
        if since and mtime_ms <= since:
            return []

        cases: List[TrainingCase] = []
        try:
            with open(GOLDEN_PATH, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return []

        for line in lines:
            if len(cases) >= limit:
                break
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                message = (row.get("message") or "").strip()
                intent = (row.get("intent") or "").strip()
            except Exception:
                continue
            if not message or not intent:
                continue
            variant = row.get("variant") or "unknown"
            cases.append(
                TrainingCase(
                    intent=intent,
                    actions=["l1:intent_detect"],
                    outcome_text=message,
                    learned=[f"标注意图={intent}（措辞={variant}）"],
                    layer_tags=["L1"],
                    quality="A",
                    confidence=0.8,
                    source="intent_golden",
                    metadata={
                        "expected_intent": intent,
                        "variant": variant,
                        "negative_sample": intent == "unknown",
                        "dataset": "l1_intent_golden",
                    },
                )
            )
        return cases
