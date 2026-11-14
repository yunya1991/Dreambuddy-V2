# -*- coding: utf-8 -*-
"""L1 意图识别 golden set 回归（人工标注，覆盖注册表 12 意图 + unknown）。

数据源: 34-前端应用训练系统/l1_intent_golden.jsonl
  每行 {"message", "intent", "variant"}，variant 标注措辞类型
  （formal/terse/colloquial/slang/mixed/multi_entity/oos），用于定位退化来源。

被测对象: 3.1-FRONTEND/scripts/l1_route_signal.py::detect_intent
  —— 它与 3.1-FRONTEND/src/lib/l1-intent-registry.ts 的 fallbackPattern 逐条对齐，
  因此本集同时约束前后端两套规则，避免只改一侧。

门禁:
  1. 逐条精确匹配
  2. 总体准确率 >= 0.90，且每个意图 >= 0.75（unknown 只计入总体，
     因为过度拒识会掩盖意图覆盖退化）
"""

import json
import os
import sys
from collections import Counter

import pytest

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "3.1-FRONTEND",
    "scripts",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import l1_route_signal as lrs  # noqa: E402

_GOLDEN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "l1_intent_golden.jsonl"
)

_TOTAL_ACC_MIN = 0.90
_PER_INTENT_ACC_MIN = 0.75


def _load_cases():
    with open(_GOLDEN_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


CASES = _load_cases()


def _predict(message: str) -> str:
    return lrs.detect_intent(message) or "unknown"


@pytest.mark.parametrize("case", CASES, ids=[c["message"] for c in CASES])
def test_intent_golden_case(case):
    got = _predict(case["message"])
    assert (
        got == case["intent"]
    ), f"{case['message']} → {got}（标注 {case['intent']}，variant={case.get('variant')}）"


def test_intent_golden_accuracy_gate():
    hit = Counter()
    total = Counter()
    for case in CASES:
        total[case["intent"]] += 1
        if _predict(case["message"]) == case["intent"]:
            hit[case["intent"]] += 1

    acc = sum(hit.values()) / len(CASES)
    assert acc >= _TOTAL_ACC_MIN, f"总体准确率 {acc:.3f} < {_TOTAL_ACC_MIN}"

    weak = {
        intent: f"{hit[intent]}/{n}"
        for intent, n in total.items()
        if n and intent != "unknown" and hit[intent] / n < _PER_INTENT_ACC_MIN
    }
    assert not weak, f"以下意图准确率低于 {_PER_INTENT_ACC_MIN}: {weak}"
