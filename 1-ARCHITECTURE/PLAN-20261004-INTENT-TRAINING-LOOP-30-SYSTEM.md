# DreamOS S 层意图识别训练闭环 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 30-真实环境交互系统内构建 IntentSample 产出 → 落盘 → 分桶 → 触发训练 → eval 回归的完整闭环，驱动 DreamOS S 层意图识别能力训练。

**Architecture:** 训练逻辑全部放在 30 系统内（HC-1a 合规），dreamos/ 只 import 不修改。IntentTrainer 作为 30 系统内适配器，封装贝叶斯更新/规则蒸馏/编排映射三步训练动作。ScenarioRunner 在现有 `run()` 接口上加可选 pipeline 钩子，不破坏现有测试。

**Tech Stack:** Python 3.10+ / pytest / PyYAML / Playwright / requests / dataclasses

## Spec Deviations（spec 与现有代码不匹配的合理化调整）

实施前必须明确以下调整，均经用户确认 spec 时默认接受（理由：HC-1a 硬约束 + 现有代码现状）：

| 编号 | spec 原文 | 实际现状 | 本计划调整 |
|---|---|---|---|
| SD-1 | §3.4 扩展 `DynamicRecognizer`（dynamic.py）加 3 classmethod | 实际类名 `DynamicIntentRecognizer`；HC-1a 禁止修改 dreamos/ | 创建 `30-真实环境交互系统/core/intent_trainer.py`，`IntentTrainer` 类承载 3 训练动作 |
| SD-2 | §3.4 复用 `bayesian_memory_updater.py` | 该文件不存在（dreamos/core/memory/ 下无此模块） | IntentTrainer 内实现简化贝叶斯更新（Beta 分布先验+后验） |
| SD-3 | §3.4 调用 `OrchestrationMemory.update_mapping()` | 该方法不存在（只有 load/save/select） | IntentTrainer 内维护 `orchestration_mapping.json`，独立于 dreamos OrchestrationMemory |
| SD-4 | §3.4 调用 `RuleBasedRecognizer.add_rule()` | 该方法不存在 | IntentTrainer 内维护 `rules.json`，不污染 dreamos RuleBasedRecognizer |
| SD-5 | §3.2 伪代码 `run_scenario(yaml_path)` + `self.pipeline.ingest()` | 现有方法 `run(page, scenario)` / `run_from_file(page, path)`，无 pipeline 属性 | `__init__` 加可选 `pipeline=None` 参数；`run()` 末尾加 `_capture_intent_sample()` 钩子；保持现有接口不变 |
| SD-6 | §5.1 测试 `test_dynamic_recognizer_training.py` 测 `DynamicRecognizer.update_weights` | 受 SD-1 影响 | 测试文件改为 `test_intent_trainer.py`，测 `IntentTrainer.update_weights` |

## Global Constraints

- **HC-1a**：不修改 `1-ARCHITECTURE/dreamos/` 下任何文件（只 import 调用）
- **HC-5**：意图识别训练无 reward，只用准确率（confirmed 比例）
- **HC-7**：跨进程 FAIL-OPEN（DreamOS /intent/route 不可用时 recognizer_output 留空，IntentSample 仍落盘）
- **HC-9**：30 系统 → DreamOS 调用是数据透传，决策在 DreamOS 内部
- **MVP 规模**：45 场景（每意图 10 train + 5 eval），每桶 5-10 样本 < BUCKET_THRESHOLD=30，**MVP 阶段不触发实际训练**，只验证 pipeline 端到端逻辑（落盘+分桶+触发条件+eval）。实际训练在扩容到 120 场景后触发
- **BUCKET_THRESHOLD=30**（spec 默认）
- **DISTILL_ACCURACY_TARGET=0.85**（spec 默认）
- **测试惯例**：pytest + MagicMock + tmp_path + `sys.path.insert(0, str(Path(__file__).parent.parent))` 导入 core（参考现有 `test_scenario_runner.py`）
- **场景矩阵**：3 意图（TREND_FOLLOWING/MEAN_REVERSION/BREAKOUT）× 1 场景/意图 × 15 样本/场景 = 45 YAML

---

## File Structure

**新建文件**（30 系统内）：
1. `30-真实环境交互系统/core/intent_sample_pipeline.py` — IntentSample dataclass + IntentSamplePipeline 类（落盘+分桶+触发）
2. `30-真实环境交互系统/core/intent_trainer.py` — IntentTrainer 类（贝叶斯更新+规则蒸馏+编排映射，HC-1a 合规适配器）
3. `30-真实环境交互系统/training/eval_gate.py` — IntentEvalGate 类 + EvalReport dataclass
4. `30-真实环境交互系统/training/intent_samples/` — IntentSample 落盘目录（运行时创建）
5. `30-真实环境交互系统/training/weights.json` — 贝叶斯权重存储（运行时创建）
6. `30-真实环境交互系统/training/rules.json` — 蒸馏规则存储（运行时创建）
7. `30-真实环境交互系统/training/orchestration_mapping.json` — 编排映射存储（运行时创建）
8. `30-真实环境交互系统/scenarios/intent_training/` — 45 个 P1 场景 YAML
9. `30-真实环境交互系统/tests/test_intent_sample_contract.py`
10. `30-真实环境交互系统/tests/test_intent_sample_pipeline.py`
11. `30-真实环境交互系统/tests/test_scenario_runner_intent_hook.py`
12. `30-真实环境交互系统/tests/test_intent_trainer.py`（替代 spec §5.1 的 test_dynamic_recognizer_training.py）
13. `30-真实环境交互系统/tests/test_intent_eval_gate.py`

**修改文件**：
1. `30-真实环境交互系统/core/scenario_runner.py` — `__init__` 加 `pipeline=None` 参数；`run()` 末尾加 `_capture_intent_sample()` 钩子；新增 4 个私有方法。现有 `run()` / `run_from_file()` / `load_scenario()` 接口不变

---

## Task 1: IntentSample dataclass + 数据契约测试

**Files:**
- Create: `30-真实环境交互系统/core/intent_sample_pipeline.py`（仅 IntentSample dataclass 部分，Pipeline 类在 Task 2 加）
- Test: `30-真实环境交互系统/tests/test_intent_sample_contract.py`

**Interfaces:**
- Produces: `IntentSample` dataclass（字段：sample_id/input/gold/recognizer_output/human_label/dataset_split/created_at）+ `to_dict()` / `from_dict()` 方法

- [ ] **Step 1: 写 RED 测试**

创建 `30-真实环境交互系统/tests/test_intent_sample_contract.py`：

```python
"""IntentSample 数据契约测试"""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample


class TestIntentSampleContract:
    """IntentSample dataclass 字段契约（对齐 spec §3.2 7 字段）"""

    def test_intent_sample_dataclass_fields(self):
        """7 字段齐全：sample_id/input/gold/recognizer_output/human_label/dataset_split/created_at"""
        sample = IntentSample(
            sample_id="test-001",
            input={"user_query": "BTC 趋势", "scenario_id": "TREND_UP", "market_features": {}},
            gold={"gold_chain": "C", "gold_intent": "trend_following"},
            recognizer_output={"predicted_intent": "trend_following", "confidence": 0.8, "level": "rule"},
            human_label={"confirmed": True, "corrected_intent": None},
            dataset_split="train",
            created_at="2026-10-04T10:00:00Z",
        )
        assert sample.sample_id == "test-001"
        assert sample.input["user_query"] == "BTC 趋势"
        assert sample.gold["gold_chain"] == "C"
        assert sample.gold["gold_intent"] == "trend_following"
        assert sample.recognizer_output["confidence"] == 0.8
        assert sample.human_label["confirmed"] is True
        assert sample.dataset_split == "train"
        assert sample.created_at == "2026-10-04T10:00:00Z"

    def test_intent_sample_serialization(self):
        """JSON 往返序列化（to_dict / from_dict）"""
        original = IntentSample(
            sample_id="test-002",
            input={"user_query": "test", "scenario_id": "TREND_DOWN", "market_features": {"regime": "trending"}},
            gold={"gold_chain": "C", "gold_intent": "trend_following"},
            recognizer_output={"predicted_intent": None, "confidence": 0.0, "level": "failopen"},
            human_label={"confirmed": False, "corrected_intent": "trend_following"},
            dataset_split="eval",
            created_at="2026-10-04T10:00:00Z",
        )
        d = original.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        restored_data = json.loads(json_str)
        restored = IntentSample.from_dict(restored_data)
        assert restored.sample_id == original.sample_id
        assert restored.dataset_split == "eval"
        assert restored.human_label["corrected_intent"] == "trend_following"
        assert restored.recognizer_output["level"] == "failopen"

    def test_yaml_intent_training_field_parse(self, tmp_path):
        """YAML 4 字段解析：gold_intent/scenario_id/split/market_features"""
        yaml_content = """
name: test
description: test
intent_training:
  gold_intent: "trend_following"
  scenario_id: "TREND_UP"
  split: "train"
  market_features:
    regime: "trending"
    volatility: "medium"
    data_freshness: "realtime"
steps:
  - name: step1
    action: wait
    seconds: 0
"""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        with open(yaml_file, "r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)

        it = parsed["intent_training"]
        assert it["gold_intent"] == "trend_following"
        assert it["scenario_id"] == "TREND_UP"
        assert it["split"] == "train"
        assert it["market_features"]["regime"] == "trending"
        assert it["market_features"]["data_freshness"] == "realtime"
```

- [ ] **Step 2: 验证测试失败**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_intent_sample_contract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.intent_sample_pipeline'`

- [ ] **Step 3: GREEN 实现 IntentSample dataclass**

创建 `30-真实环境交互系统/core/intent_sample_pipeline.py`（仅 IntentSample 部分）：

```python
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
```

- [ ] **Step 4: 验证测试通过**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_intent_sample_contract.py -v`
Expected: PASS（3 个测试）

- [ ] **Step 5: 回归测试不破坏**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_scenario_runner.py -v`
Expected: PASS（现有测试无回归）

- [ ] **Step 6: Commit**

```bash
git add 30-真实环境交互系统/core/intent_sample_pipeline.py 30-真实环境交互系统/tests/test_intent_sample_contract.py
git commit -m "feat(intent-training): add IntentSample dataclass + contract tests (Task 1/8)"
```

---

## Task 2: IntentSamplePipeline 落盘 + 分桶 + 触发

**Files:**
- Modify: `30-真实环境交互系统/core/intent_sample_pipeline.py`（追加 IntentSamplePipeline 类）
- Test: `30-真实环境交互系统/tests/test_intent_sample_pipeline.py`

**Interfaces:**
- Consumes: `IntentSample`（from Task 1）
- Produces: `IntentSamplePipeline.ingest(sample)` / `load_split(split)` / `bucket_counter` 属性 / 构造参数 `storage_path / bucket_threshold / distill_accuracy_target / trigger_fn`

- [ ] **Step 1: 写 RED 测试**

创建 `30-真实环境交互系统/tests/test_intent_sample_pipeline.py`：

```python
"""IntentSamplePipeline 测试（落盘 + 分桶 + 触发）"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample, IntentSamplePipeline


def _make_sample(sample_id="s1", gold_intent="trend_following",
                scenario_id="TREND_UP", split="train", confirmed=True):
    return IntentSample(
        sample_id=sample_id,
        input={"user_query": "test", "scenario_id": scenario_id, "market_features": {}},
        gold={"gold_chain": "C", "gold_intent": gold_intent},
        recognizer_output={"predicted_intent": gold_intent if confirmed else "other",
                           "confidence": 0.8, "level": "rule"},
        human_label={"confirmed": confirmed, "corrected_intent": None if confirmed else gold_intent},
        dataset_split=split,
        created_at="2026-10-04T10:00:00Z",
    )


class TestIntentSamplePipeline:
    def test_ingest_persists_sample(self, tmp_path):
        """落盘成功"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        pipeline.ingest(_make_sample("s1"))
        bucket_dir = tmp_path / "trend_following_TREND_UP"
        files = list(bucket_dir.glob("*.json"))
        assert len(files) == 1
        with open(files[0]) as f:
            data = json.load(f)
        assert data["sample_id"] == "s1"
        assert data["gold"]["gold_intent"] == "trend_following"

    def test_bucket_counter_increments(self, tmp_path):
        """分桶计数（仅 train 集）"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        for i in range(3):
            pipeline.ingest(_make_sample(f"s{i}"))
        assert pipeline.bucket_counter[("trend_following", "TREND_UP")] == 3

    def test_trigger_training_at_threshold(self, tmp_path):
        """≥阈值 触发训练（threshold=2 + mock trigger_fn）"""
        call_count = [0]
        def mock_trigger(bucket_key, samples):
            call_count[0] += 1

        pipeline = IntentSamplePipeline(
            storage_path=tmp_path, bucket_threshold=2,
            trigger_fn=mock_trigger,
        )
        pipeline.ingest(_make_sample("s1"))
        assert call_count[0] == 0  # 1 < 2
        pipeline.ingest(_make_sample("s2"))
        assert call_count[0] == 1  # 2 >= 2，触发
        # 触发后清零
        assert pipeline.bucket_counter[("trend_following", "TREND_UP")] == 0

    def test_no_trigger_below_threshold(self, tmp_path):
        """<阈值 不触发"""
        call_count = [0]
        def mock_trigger(bucket_key, samples):
            call_count[0] += 1

        pipeline = IntentSamplePipeline(
            storage_path=tmp_path, bucket_threshold=30,
            trigger_fn=mock_trigger,
        )
        for i in range(10):
            pipeline.ingest(_make_sample(f"s{i}"))
        assert call_count[0] == 0  # 10 < 30

    def test_eval_samples_not_count_train(self, tmp_path):
        """split 隔离：eval 样本落盘但不计入 train 桶"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        pipeline.ingest(_make_sample("s1", split="train"))
        pipeline.ingest(_make_sample("s2", split="eval"))
        # train 桶 1 个（eval 不计数）
        assert pipeline.bucket_counter[("trend_following", "TREND_UP")] == 1
        # 但 eval 样本已落盘
        eval_samples = pipeline.load_split("eval")
        assert len(eval_samples) == 1
        assert eval_samples[0].dataset_split == "eval"

    def test_load_split_returns_only_matching(self, tmp_path):
        """load_split 只返回指定 split 的样本"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        pipeline.ingest(_make_sample("s1", split="train"))
        pipeline.ingest(_make_sample("s2", split="train"))
        pipeline.ingest(_make_sample("s3", split="eval"))
        train_samples = pipeline.load_split("train")
        eval_samples = pipeline.load_split("eval")
        assert len(train_samples) == 2
        assert len(eval_samples) == 1
```

- [ ] **Step 2: 验证测试失败**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_intent_sample_pipeline.py -v`
Expected: FAIL with `AttributeError: module 'core.intent_sample_pipeline' has no attribute 'IntentSamplePipeline'`

- [ ] **Step 3: GREEN 实现 IntentSamplePipeline**

在 `30-真实环境交互系统/core/intent_sample_pipeline.py` 末尾追加：

```python
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
```

- [ ] **Step 4: 验证测试通过**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_intent_sample_pipeline.py -v`
Expected: PASS（6 个测试）

- [ ] **Step 5: Commit**

```bash
git add 30-真实环境交互系统/core/intent_sample_pipeline.py 30-真实环境交互系统/tests/test_intent_sample_pipeline.py
git commit -m "feat(intent-training): add IntentSamplePipeline with persist+bucket+trigger (Task 2/8)"
```

---

## Task 3: IntentTrainer 训练动作（30 系统内适配器，HC-1a 合规）

**说明:** 替代 spec §3.4 的"扩展 DynamicRecognizer"方案（SD-1/SD-2/SD-3/SD-4）。训练逻辑全部在 30 系统内，dreamos/ 只 import 不修改。

**Files:**
- Create: `30-真实环境交互系统/core/intent_trainer.py`
- Test: `30-真实环境交互系统/tests/test_intent_trainer.py`

**Interfaces:**
- Consumes: `IntentSample`（from Task 1）
- Produces: `IntentTrainer.update_weights(bucket_key, samples)` / `distill_to_rules(bucket_key, samples) -> bool` / `refine_orchestration(bucket_key, samples)` / `load_weights()` / `load_rules()` / `load_orchestration_mapping()`

- [ ] **Step 1: 写 RED 测试**

创建 `30-真实环境交互系统/tests/test_intent_trainer.py`：

```python
"""IntentTrainer 训练动作测试

替代 spec §5.1 的 test_dynamic_recognizer_training.py（SD-6）。
HC-1a 合规：训练逻辑在 30 系统内，不修改 dreamos/。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample
from core.intent_trainer import IntentTrainer


def _make_sample(confirmed=True, gold_intent="trend_following", scenario_id="TREND_UP"):
    return IntentSample(
        sample_id="s",
        input={"user_query": "test", "scenario_id": scenario_id, "market_features": {"regime": "trending"}},
        gold={"gold_chain": "C", "gold_intent": gold_intent},
        recognizer_output={"predicted_intent": gold_intent if confirmed else "other",
                           "confidence": 0.8, "level": "rule"},
        human_label={"confirmed": confirmed, "corrected_intent": None if confirmed else gold_intent},
        dataset_split="train",
        created_at="2026-10-04T10:00:00Z",
    )


class TestIntentTrainer:
    def test_update_weights_bayesian(self, tmp_path):
        """贝叶斯后验更新：Beta 分布 alpha/beta 递增"""
        weights_path = tmp_path / "weights.json"
        trainer = IntentTrainer(weights_path=weights_path)
        samples = [_make_sample(confirmed=True) for _ in range(5)]
        trainer.update_weights(("trend_following", "TREND_UP"), samples)
        assert weights_path.exists()
        weights = trainer.load_weights()
        key = "trend_following|TREND_UP"  # JSON 键用 | 分隔
        assert key in weights
        # Beta 先验 alpha=1, beta=1；5 个全对 → alpha=6, beta=1
        assert weights[key]["alpha"] == 6
        assert weights[key]["beta"] == 1
        assert weights[key]["sample_count"] == 5

    def test_distill_to_rules_at_threshold(self, tmp_path):
        """≥85% 准确率蒸馏成功"""
        rules_path = tmp_path / "rules.json"
        trainer = IntentTrainer(rules_path=rules_path, distill_accuracy_target=0.85)
        # 10 个样本，9 对 1 错 → 90% 准确率 ≥ 85%
        samples = [_make_sample(confirmed=True) for _ in range(9)] + [_make_sample(confirmed=False)]
        distilled = trainer.distill_to_rules(("trend_following", "TREND_UP"), samples)
        assert distilled is True
        assert rules_path.exists()

    def test_no_distill_below_accuracy(self, tmp_path):
        """<85% 准确率不蒸馏"""
        rules_path = tmp_path / "rules.json"
        trainer = IntentTrainer(rules_path=rules_path, distill_accuracy_target=0.85)
        # 10 个样本，5 对 5 错 → 50% 准确率 < 85%
        samples = [_make_sample(confirmed=True) for _ in range(5)] + [_make_sample(confirmed=False) for _ in range(5)]
        distilled = trainer.distill_to_rules(("trend_following", "TREND_UP"), samples)
        assert distilled is False
        assert not rules_path.exists()

    def test_refine_orchestration_mapping(self, tmp_path):
        """场景→链路映射精确化（L3→L0）"""
        orch_path = tmp_path / "orch.json"
        trainer = IntentTrainer(orch_path=orch_path)
        samples = [_make_sample(confirmed=True) for _ in range(3)]
        trainer.refine_orchestration(("trend_following", "TREND_UP"), samples)
        assert orch_path.exists()
        mapping = trainer.load_orchestration_mapping()
        key = "trend_following|TREND_UP"
        assert key in mapping
        # TREND_FOLLOWING → C 链（spec §4.2）
        assert mapping[key]["pattern"] == "c_chain"
        assert "C1" in mapping[key]["nodes"]
        assert mapping[key]["fallback_level"] == "L0"
```

- [ ] **Step 2: 验证测试失败**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_intent_trainer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.intent_trainer'`

- [ ] **Step 3: GREEN 实现 IntentTrainer**

创建 `30-真实环境交互系统/core/intent_trainer.py`：

```python
"""IntentTrainer — 30 系统内训练适配器（HC-1a 合规）

替代 spec §3.4 的"扩展 DynamicRecognizer"方案（SD-1）。
- bayesian_memory_updater.py 不存在（SD-2）：本模块内实现 Beta 分布贝叶斯更新
- OrchestrationMemory.update_mapping 不存在（SD-3）：本模块维护 orchestration_mapping.json
- RuleBasedRecognizer.add_rule 不存在（SD-4）：本模块维护 rules.json，不污染 dreamos

3 步训练动作（对齐 SPEC-20260929 §2.1）：
1. update_weights: 贝叶斯后验更新（Beta 分布）
2. distill_to_rules: 高频模式蒸馏（零 Token 规则）
3. refine_orchestration: 场景→链路映射精确化（L3→L0）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("real_env.intent_trainer")


def _bucket_key_str(bucket_key: Tuple[str, str]) -> str:
    """JSON 键用 | 分隔（避免 tuple 序列化问题）"""
    return f"{bucket_key[0]}|{bucket_key[1]}"


class IntentTrainer:
    """训练逻辑在 30 系统内（HC-1a 合规）"""

    # spec §4.2: 三大思维链 → 编排模式映射
    CHAIN_PATTERN = {
        "trend_following": "c_chain",
        "mean_reversion": "c_chain",
        "breakout": "c_chain",
    }
    DEFAULT_NODES = ["C1", "C2", "C3", "A2", "A4", "A5", "A9"]

    def __init__(
        self,
        weights_path: Path = None,
        rules_path: Path = None,
        orch_path: Path = None,
        distill_accuracy_target: float = 0.85,
    ):
        self._weights_path = Path(weights_path) if weights_path else Path("30-真实环境交互系统/training/weights.json")
        self._rules_path = Path(rules_path) if rules_path else Path("30-真实环境交互系统/training/rules.json")
        self._orch_path = Path(orch_path) if orch_path else Path("30-真实环境交互系统/training/orchestration_mapping.json")
        self._distill_accuracy_target = distill_accuracy_target
        for p in [self._weights_path, self._rules_path, self._orch_path]:
            p.parent.mkdir(parents=True, exist_ok=True)

    # ── Step 1: 贝叶斯后验更新 ──────────────────────────
    def update_weights(self, bucket_key: Tuple[str, str], samples: List) -> None:
        """贝叶斯后验更新（Beta 分布：alpha += correct, beta += wrong）

        简化版贝叶斯（spec §3.4 提到的 bayesian_memory_updater.py 不存在，SD-2）
        """
        weights = self.load_weights()
        key = _bucket_key_str(bucket_key)
        prior = weights.get(key, {"alpha": 1.0, "beta": 1.0, "sample_count": 0})
        correct = sum(1 for s in samples if s.human_label.get("confirmed"))
        wrong = len(samples) - correct
        prior["alpha"] += correct
        prior["beta"] += wrong
        prior["sample_count"] = prior.get("sample_count", 0) + len(samples)
        # 后验均值（Beta 分布均值 = alpha/(alpha+beta)）
        prior["posterior_mean"] = prior["alpha"] / (prior["alpha"] + prior["beta"])
        weights[key] = prior
        self._save_weights(weights)
        logger.info("贝叶斯更新 %s: alpha=%s beta=%s mean=%.3f",
                    key, prior["alpha"], prior["beta"], prior["posterior_mean"])

    # ── Step 2: 规则蒸馏 ────────────────────────────────
    def distill_to_rules(self, bucket_key: Tuple[str, str], samples: List) -> bool:
        """高频模式蒸馏为零 Token 规则

        触发条件：准确率 ≥ distill_accuracy_target
        Returns: True 蒸馏成功，False 不蒸馏
        """
        accuracy = self._compute_accuracy(samples)
        if accuracy < self._distill_accuracy_target:
            logger.info("桶 %s 准确率 %.2f < %.2f，不蒸馏",
                        bucket_key, accuracy, self._distill_accuracy_target)
            return False

        common = self._extract_common_features(samples)
        rules = self.load_rules()
        rules[_bucket_key_str(bucket_key)] = common
        self._save_rules(rules)
        logger.info("桶 %s 蒸馏规则成功（准确率 %.2f）", bucket_key, accuracy)
        return True

    # ── Step 3: 编排映射精确化 ──────────────────────────
    def refine_orchestration(self, bucket_key: Tuple[str, str], samples: List) -> None:
        """场景→链路映射精确化（L3→L0）

        对齐 spec §4.2：TREND_FOLLOWING/MEAN_REVERSION/BREAKOUT → C 链
        """
        gold_intent = bucket_key[0]
        pattern = self.CHAIN_PATTERN.get(gold_intent, "c_chain")
        accuracy = self._compute_accuracy(samples)

        mapping = self.load_orchestration_mapping()
        mapping[_bucket_key_str(bucket_key)] = {
            "pattern": pattern,
            "nodes": list(self.DEFAULT_NODES),
            "score": accuracy,
            "confidence": "high" if accuracy >= 0.85 else "medium",
            "fallback_level": "L0",
            "source_scenario": bucket_key[1],
        }
        self._save_orchestration(mapping)
        logger.info("编排映射 %s → %s (L0)", bucket_key, pattern)

    # ── 持久化辅助 ──────────────────────────────────────
    def load_weights(self) -> Dict[str, Any]:
        if self._weights_path.exists():
            with open(self._weights_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_weights(self, weights: Dict) -> None:
        with open(self._weights_path, "w", encoding="utf-8") as f:
            json.dump(weights, f, ensure_ascii=False, indent=2)

    def load_rules(self) -> Dict[str, Any]:
        if self._rules_path.exists():
            with open(self._rules_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_rules(self, rules: Dict) -> None:
        with open(self._rules_path, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)

    def load_orchestration_mapping(self) -> Dict[str, Any]:
        if self._orch_path.exists():
            with open(self._orch_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_orchestration(self, mapping: Dict) -> None:
        with open(self._orch_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

    # ── 统计辅助 ────────────────────────────────────────
    @staticmethod
    def _compute_accuracy(samples: List) -> float:
        if not samples:
            return 0.0
        correct = sum(1 for s in samples if s.human_label.get("confirmed"))
        return correct / len(samples)

    @staticmethod
    def _extract_common_features(samples: List) -> Dict[str, Any]:
        """从样本中提取共同特征（取首个样本 market_features 作为基础）"""
        if not samples:
            return {}
        return dict(samples[0].input.get("market_features", {}))
```

- [ ] **Step 4: 验证测试通过**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_intent_trainer.py -v`
Expected: PASS（4 个测试）

- [ ] **Step 5: Commit**

```bash
git add 30-真实环境交互系统/core/intent_trainer.py 30-真实环境交互系统/tests/test_intent_trainer.py
git commit -m "feat(intent-training): add IntentTrainer adapter with bayesian+distill+orch (Task 3/8, HC-1a)"
```

---

## Task 4: ScenarioRunner IntentSample 钩子

**Files:**
- Modify: `30-真实环境交互系统/core/scenario_runner.py`（现有 382 行文件，扩展 `__init__` + `run()` 钩子 + 4 私有方法）
- Test: `30-真实环境交互系统/tests/test_scenario_runner_intent_hook.py`

**Interfaces:**
- Consumes: `IntentSample`（Task 1）+ `IntentSamplePipeline`（Task 2，可选注入）
- Produces: `ScenarioRunner.__init__(config, simulator, verifier, pipeline=None)`（pipeline 可选，默认 None 保持向后兼容）+ 4 私有方法 `_capture_intent_sample / _build_intent_sample / _call_dreamos_intent_route / _auto_label / _extract_user_input`

- [ ] **Step 1: 写 RED 测试**

创建 `30-真实环境交互系统/tests/test_scenario_runner_intent_hook.py`：

```python
"""ScenarioRunner IntentSample 产出钩子测试

对齐 spec §3.2（SD-5：伪代码 run_scenario 改为现有 run() 接口扩展）
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scenario_runner import ScenarioRunner
from core.intent_sample_pipeline import IntentSample, IntentSamplePipeline


@pytest.fixture
def runner_with_pipeline(tmp_path):
    config = {"scenarios": {"default_timeout": 60, "retry_count": 0}}
    simulator = MagicMock()
    verifier = MagicMock()
    pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
    return ScenarioRunner(config, simulator, verifier, pipeline=pipeline)


@pytest.fixture
def runner_no_pipeline():
    """无 pipeline 的 runner（向后兼容）"""
    config = {"scenarios": {"default_timeout": 60, "retry_count": 0}}
    return ScenarioRunner(config, MagicMock(), MagicMock())


class TestScenarioRunnerIntentHook:
    def test_build_intent_sample_from_yaml(self, runner_with_pipeline):
        """YAML intent_training → IntentSample"""
        scenario = {
            "name": "test",
            "intent_training": {
                "gold_intent": "trend_following",
                "scenario_id": "TREND_UP",
                "split": "train",
                "market_features": {"regime": "trending", "volatility": "medium"},
            },
            "steps": [{"name": "type", "action": "type", "text": "BTC 趋势"}],
        }
        result_mock = MagicMock()
        sample = runner_with_pipeline._build_intent_sample(
            scenario, result_mock, user_input="BTC 趋势"
        )
        assert sample.gold["gold_intent"] == "trend_following"
        assert sample.gold["gold_chain"] == "C"
        assert sample.input["scenario_id"] == "TREND_UP"
        assert sample.input["user_query"] == "BTC 趋势"
        assert sample.input["market_features"]["regime"] == "trending"
        assert sample.dataset_split == "train"

    def test_call_dreamos_intent_route_success(self, runner_with_pipeline):
        """调用 /intent/route 成功"""
        with patch("core.scenario_runner.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "predicted_intent": "trend_following",
                "confidence": 0.82,
                "level": "rule",
            }
            mock_post.return_value = mock_resp

            output = runner_with_pipeline._call_dreamos_intent_route("BTC 趋势")
            assert output["predicted_intent"] == "trend_following"
            assert output["confidence"] == 0.82
            assert output["level"] == "rule"

    def test_human_label_auto_compare(self, runner_with_pipeline):
        """自动对照 gold_intent 生成 human_label"""
        # 匹配
        label = runner_with_pipeline._auto_label(
            {"predicted_intent": "trend_following"}, "trend_following"
        )
        assert label["confirmed"] is True
        assert label["corrected_intent"] is None
        # 不匹配
        label = runner_with_pipeline._auto_label(
            {"predicted_intent": "mean_reversion"}, "trend_following"
        )
        assert label["confirmed"] is False
        assert label["corrected_intent"] == "trend_following"

    def test_failopen_when_dreamos_unavailable(self, runner_with_pipeline):
        """DreamOS 不可用降级（HC-7）"""
        with patch("core.scenario_runner.requests.post", side_effect=Exception("conn refused")):
            output = runner_with_pipeline._call_dreamos_intent_route("BTC 趋势")
            assert output["predicted_intent"] is None
            assert output["level"] == "failopen"
            assert output["confidence"] == 0.0

    def test_run_with_pipeline_captures_sample(self, runner_with_pipeline, tmp_path):
        """run() 末尾钩子触发 IntentSample 落盘"""
        scenario = {
            "name": "test",
            "intent_training": {
                "gold_intent": "trend_following",
                "scenario_id": "TREND_UP",
                "split": "train",
                "market_features": {"regime": "trending"},
            },
            "steps": [{"name": "wait", "action": "wait", "seconds": 0}],
        }
        with patch.object(runner_with_pipeline, "_call_dreamos_intent_route",
                          return_value={"predicted_intent": "trend_following", "confidence": 0.8, "level": "rule"}):
            with patch.object(runner_with_pipeline, "_extract_user_input", return_value="BTC 趋势"):
                mock_page = MagicMock()
                runner_with_pipeline.run(mock_page, scenario)
        # 验证 IntentSample 已落盘
        samples = runner_with_pipeline._pipeline.load_split("train")
        assert len(samples) == 1
        assert samples[0].gold["gold_intent"] == "trend_following"

    def test_run_without_pipeline_no_capture(self, runner_no_pipeline):
        """无 pipeline 时 run() 不触发 capture（向后兼容）"""
        scenario = {
            "name": "test",
            "intent_training": {"gold_intent": "trend_following", "scenario_id": "TREND_UP", "split": "train"},
            "steps": [{"name": "wait", "action": "wait", "seconds": 0}],
        }
        mock_page = MagicMock()
        result = runner_no_pipeline.run(mock_page, scenario)
        # 不报错，正常返回
        assert result.name == "test"
        assert result.passed is True
```

- [ ] **Step 2: 验证测试失败**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_scenario_runner_intent_hook.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'pipeline'` 或 `AttributeError`

- [ ] **Step 3: GREEN 实现 ScenarioRunner 扩展**

修改 `30-真实环境交互系统/core/scenario_runner.py`：

3a. 在 `__init__` 签名加 `pipeline=None` 参数：

```python
def __init__(self, config: dict, user_simulator: UserSimulator,
             result_verifier: ResultVerifier, pipeline=None):
    self._config = config
    self._simulator = user_simulator
    self._verifier = result_verifier
    self._scenario_cfg = config.get("scenarios", {})
    self._pipeline = pipeline  # 可选 IntentSamplePipeline（向后兼容）
```

3b. 在 `run()` 方法末尾（`return result` 之前）加钩子。找到现有 `run()` 方法的最后一段：

```python
        if result.passed:
            logger.info("Scenario '%s' PASSED (%.0fms)", name, result.duration_ms)
        else:
            logger.error("Scenario '%s' FAILED (%.0fms)", name, result.duration_ms)

        return result
```

改为：

```python
        if result.passed:
            logger.info("Scenario '%s' PASSED (%.0fms)", name, result.duration_ms)
        else:
            logger.error("Scenario '%s' FAILED (%.0fms)", name, result.duration_ms)

        # === 新增：意图训练钩子（spec §3.2, SD-5）===
        if scenario.get("intent_training") and self._pipeline:
            try:
                self._capture_intent_sample(scenario, page, result)
            except Exception as e:
                logger.warning("IntentSample capture failed (FAIL-OPEN): %s", e)

        return result
```

3c. 在类末尾（`run_batch` 方法之后）追加 5 个私有方法：

```python
    # ------------------------------------------------------------------
    # 意图训练钩子（spec §3.2, SD-5）
    # ------------------------------------------------------------------
    def _capture_intent_sample(self, scenario: Dict, page: Page, result: ScenarioResult) -> None:
        """从 YAML 场景 + 执行结果构建 IntentSample 并落盘"""
        user_input = self._extract_user_input(scenario)
        sample = self._build_intent_sample(scenario, result, user_input=user_input)
        recognizer_output = self._call_dreamos_intent_route(user_input)
        sample.recognizer_output = recognizer_output
        sample.human_label = self._auto_label(
            recognizer_output, scenario["intent_training"]["gold_intent"]
        )
        self._pipeline.ingest(sample)

    def _build_intent_sample(self, scenario: Dict, result: ScenarioResult,
                            user_input: str) -> IntentSample:
        """从 YAML scenario 构建 IntentSample（recognizer_output 待后续填充）"""
        import uuid
        from datetime import datetime, timezone
        from .intent_sample_pipeline import IntentSample

        it = scenario["intent_training"]
        return IntentSample(
            sample_id=str(uuid.uuid4()),
            input={
                "user_query": user_input,
                "scenario_id": it["scenario_id"],
                "market_features": it.get("market_features", {}),
            },
            gold={"gold_chain": "C", "gold_intent": it["gold_intent"]},
            recognizer_output={},
            human_label={},
            dataset_split=it.get("split", "train"),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _call_dreamos_intent_route(self, user_input: str) -> dict:
        """调用 DreamOS /intent/route（HC-7 FAIL-OPEN）"""
        import requests
        try:
            resp = requests.post(
                "http://localhost:8000/api/v1/intent/route",
                json={"text": user_input},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "predicted_intent": data.get("predicted_intent"),
                    "confidence": data.get("confidence", 0.0),
                    "level": data.get("level", "remote"),
                }
            logger.warning("DreamOS /intent/route status=%s, 降级", resp.status_code)
            return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}
        except Exception as e:
            logger.warning("DreamOS /intent/route 不可用，降级: %s", e)
            return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}

    def _auto_label(self, recognizer_output: dict, gold_intent: str) -> dict:
        """自动对照 gold_intent 生成 human_label"""
        predicted = recognizer_output.get("predicted_intent")
        confirmed = predicted == gold_intent
        return {
            "confirmed": confirmed,
            "corrected_intent": None if confirmed else gold_intent,
        }

    def _extract_user_input(self, scenario: Dict) -> str:
        """从 scenario.steps 提取第一个 type 步骤的 text（用户问法）"""
        for step in scenario.get("steps", []):
            if step.get("action") == "type" and step.get("text"):
                return step["text"]
        return ""
```

3d. 在文件顶部 import 区加 `requests`（用于 patch）：

```python
import requests  # 用于 _call_dreamos_intent_route（HC-7 FAIL-OPEN）
```

- [ ] **Step 4: 验证测试通过**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_scenario_runner_intent_hook.py -v`
Expected: PASS（6 个测试）

- [ ] **Step 5: 回归测试不破坏**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_scenario_runner.py -v`
Expected: PASS（现有测试无回归——`pipeline=None` 默认值保证向后兼容）

- [ ] **Step 6: Commit**

```bash
git add 30-真实环境交互系统/core/scenario_runner.py 30-真实环境交互系统/tests/test_scenario_runner_intent_hook.py
git commit -m "feat(intent-training): add ScenarioRunner intent capture hook (Task 4/8, backward-compatible)"
```

---

## Task 5: IntentEvalGate eval 回归门

**Files:**
- Create: `30-真实环境交互系统/training/eval_gate.py`
- Test: `30-真实环境交互系统/tests/test_intent_eval_gate.py`

**Interfaces:**
- Consumes: `IntentSamplePipeline`（Task 2，调用 `load_split("eval")`）
- Produces: `IntentEvalGate.run_eval() -> EvalReport` / `EvalReport` dataclass（accuracy/drift/passed/zero_token_ratio/route_hit_ratio/details）

- [ ] **Step 1: 写 RED 测试**

创建 `30-真实环境交互系统/tests/test_intent_eval_gate.py`：

```python
"""IntentEvalGate eval 回归门测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample, IntentSamplePipeline
from training.eval_gate import IntentEvalGate, EvalReport


def _make_eval_sample(gold_intent="trend_following", scenario_id="TREND_UP"):
    """eval 样本（predicted 与 gold 一致，由 route_fn 决定实际预测）"""
    return IntentSample(
        sample_id="s",
        input={"user_query": "test", "scenario_id": scenario_id, "market_features": {}},
        gold={"gold_chain": "C", "gold_intent": gold_intent},
        recognizer_output={"predicted_intent": gold_intent, "confidence": 0.8, "level": "rule"},
        human_label={"confirmed": True, "corrected_intent": None},
        dataset_split="eval",
        created_at="2026-10-04T10:00:00Z",
    )


class TestIntentEvalGate:
    def test_run_eval_returns_report(self, tmp_path):
        """返回 EvalReport"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        for i in range(3):
            pipeline.ingest(_make_eval_sample())
        # route_fn 全返回正确意图
        gate = IntentEvalGate(
            pipeline,
            route_fn=lambda q: {"predicted_intent": "trend_following", "level": "rule"},
        )
        report = gate.run_eval()
        assert isinstance(report, EvalReport)
        assert report.accuracy == 1.0
        assert report.passed is True

    def test_accuracy_below_target_fails(self, tmp_path):
        """准确率 < 75% 不通过"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        for i in range(4):
            pipeline.ingest(_make_eval_sample())
        # route_fn 全返回错误意图 → 0% 准确率
        gate = IntentEvalGate(
            pipeline,
            route_fn=lambda q: {"predicted_intent": "other", "level": "rule"},
            accuracy_target=0.75,
        )
        report = gate.run_eval()
        assert report.passed is False
        assert report.accuracy == 0.0

    def test_drift_exceeds_limit_fails(self, tmp_path):
        """波动 ≥3% 不通过"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        for i in range(4):
            pipeline.ingest(_make_eval_sample())
        gate = IntentEvalGate(
            pipeline,
            route_fn=lambda q: {"predicted_intent": "trend_following", "level": "rule"},
            accuracy_target=0.5,
            drift_limit=0.03,
        )
        # 第一次：100% 准确率
        report1 = gate.run_eval()
        assert report1.accuracy == 1.0
        assert report1.passed is True
        # 第二次：改为全错 → 0% 准确率，drift=1.0 ≥ 0.03
        gate._route_fn = lambda q: {"predicted_intent": "wrong", "level": "rule"}
        report2 = gate.run_eval()
        assert report2.accuracy == 0.0
        assert report2.drift >= 0.03
        assert report2.passed is False
```

- [ ] **Step 2: 验证测试失败**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_intent_eval_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'training.eval_gate'`

- [ ] **Step 3: GREEN 实现 IntentEvalGate**

创建 `30-真实环境交互系统/training/eval_gate.py`：

```python
"""意图识别 eval 回归门

对齐 spec §3.5。跑 eval 集验证训练后准确率/波动/零 Token 占比/路由命中率。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSamplePipeline

logger = logging.getLogger("real_env.eval_gate")


@dataclass
class EvalReport:
    """eval 报告（对齐 spec §3.5）"""
    accuracy: float
    drift: float
    passed: bool
    zero_token_ratio: float
    route_hit_ratio: float
    details: List[dict] = field(default_factory=list)


class IntentEvalGate:
    """eval 集回归门"""

    def __init__(
        self,
        pipeline: IntentSamplePipeline,
        route_fn: Optional[Callable] = None,
        accuracy_target: float = 0.75,
        drift_limit: float = 0.03,
        zero_token_target: float = 0.50,
    ):
        self._pipeline = pipeline
        self._route_fn = route_fn
        self.ACCURACY_TARGET = accuracy_target
        self.ACCURACY_DRIFT_LIMIT = drift_limit
        self.ZERO_TOKEN_TARGET = zero_token_target
        self._last_accuracy: Optional[float] = None

    def run_eval(self) -> EvalReport:
        """跑 eval 集，返回 EvalReport"""
        eval_samples = self._pipeline.load_split("eval")
        if not eval_samples:
            return EvalReport(0.0, 0.0, False, 0.0, 0.0)

        results: List[bool] = []
        zero_token_count = 0
        route_hit_count = 0
        details: List[dict] = []

        for sample in eval_samples:
            output = self._call_dreamos_intent_route(sample.input["user_query"])
            predicted = output.get("predicted_intent")
            gold = sample.gold["gold_intent"]
            correct = predicted == gold
            results.append(correct)
            if output.get("level") == "rule":
                zero_token_count += 1
            if correct:
                route_hit_count += 1
            details.append({
                "sample_id": sample.sample_id,
                "gold": gold,
                "predicted": predicted,
                "correct": correct,
            })

        accuracy = sum(results) / len(results)
        drift = abs(accuracy - self._last_accuracy) if self._last_accuracy is not None else 0.0
        passed = accuracy >= self.ACCURACY_TARGET and drift < self.ACCURACY_DRIFT_LIMIT

        report = EvalReport(
            accuracy=accuracy,
            drift=drift,
            passed=passed,
            zero_token_ratio=zero_token_count / len(eval_samples),
            route_hit_ratio=route_hit_count / len(eval_samples),
            details=details,
        )
        self._last_accuracy = accuracy
        return report

    def _call_dreamos_intent_route(self, user_input: str) -> dict:
        """调用 DreamOS /intent/route（HC-7 FAIL-OPEN）"""
        if self._route_fn:
            try:
                return self._route_fn(user_input)
            except Exception as e:
                logger.warning("route_fn 失败，降级: %s", e)
                return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}
        import requests
        try:
            resp = requests.post(
                "http://localhost:8000/api/v1/intent/route",
                json={"text": user_input},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "predicted_intent": data.get("predicted_intent"),
                    "confidence": data.get("confidence", 0.0),
                    "level": data.get("level", "remote"),
                }
            return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}
        except Exception as e:
            logger.warning("DreamOS 不可用，降级: %s", e)
            return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}
```

注意：还需创建 `30-真实环境交互系统/training/__init__.py` 空文件，使 `training` 成为可导入的包。

- [ ] **Step 4: 验证测试通过**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/test_intent_eval_gate.py -v`
Expected: PASS（3 个测试）

- [ ] **Step 5: Commit**

```bash
git add 30-真实环境交互系统/training/eval_gate.py 30-真实环境交互系统/training/__init__.py 30-真实环境交互系统/tests/test_intent_eval_gate.py
git commit -m "feat(intent-training): add IntentEvalGate eval regression gate (Task 5/8)"
```

---

## Task 6: P1 场景矩阵 YAML（45 场景）

**Files:**
- Create: `30-真实环境交互系统/scenarios/intent_training/` 下 45 个 YAML
- Create: `30-真实环境交互系统/scripts/gen_p1_scenarios.py`（生成脚本，避免手写 45 个 YAML）

**说明:** MVP 45 场景 = 3 意图 × 15 样本（10 train + 5 eval）。每意图聚焦 1 个代表场景：
- TREND_FOLLOWING × TREND_UP（15 个）
- MEAN_REVERSION × RANGE（15 个）
- BREAKOUT × BREAKOUT_UP（15 个）

注意：MVP 每桶 10 train < BUCKET_THRESHOLD=30，**不触发实际训练**，只验证 pipeline 端到端逻辑。

- [ ] **Step 1: 创建场景生成脚本**

创建 `30-真实环境交互系统/scripts/gen_p1_scenarios.py`：

```python
"""生成 P1 场景矩阵 YAML（45 个：3 意图 × 15 样本）

用法: cd 30-真实环境交互系统 && python scripts/gen_p1_scenarios.py
输出: scenarios/intent_training/*.yaml
"""
import yaml
from pathlib import Path

# 3 意图 × 1 场景 × (10 train + 5 eval) = 45 场景
MATRIX = [
    {
        "gold_intent": "trend_following",
        "scenario_id": "TREND_UP",
        "market_features": {"regime": "trending", "volatility": "medium", "data_freshness": "realtime"},
        "queries_train": [
            "BTC 现在是上升趋势吗，要不要顺势加仓",
            "以太坊涨得不错，趋势还能延续吗",
            "现在适合追多 BTC 吗，趋势向上",
            "看看 BTC 趋势，向上还是向下",
            "ETH 趋势跟随，现在入场合适吗",
            "BTC 涨势明确，加仓还是等回调",
            "趋势交易，BTC 现在什么方向",
            "顺势操作 BTC，向上趋势确认吗",
            "BTC 趋势强度如何，能跟进吗",
            "以太坊上升趋势，要不要追",
        ],
        "queries_eval": [
            "BTC 趋势怎么看，向上吗",
            "ETH 现在趋势方向",
            "顺势 BTC，趋势确认了吗",
            "BTC 涨势还能持续吗",
            "趋势跟随策略，BTC 现在能做吗",
        ],
    },
    {
        "gold_intent": "mean_reversion",
        "scenario_id": "RANGE",
        "market_features": {"regime": "ranging", "volatility": "low", "data_freshness": "realtime"},
        "queries_train": [
            "BTC 在区间震荡，高抛低吸怎么做",
            "以太坊来回震荡，适合做均值回归吗",
            "BTC 区间上下沿在哪，能反向操作吗",
            "现在 BTC 震荡，适合低买高卖吗",
            "ETH 横盘，均值回归策略可行吗",
            "BTC 偏离均线多少，会回归吗",
            "震荡行情 BTC，高抛低吸点位",
            "均值回归，BTC 现在偏离多少",
            "BTC 区间震荡，反向做单可以吗",
            "ETH 震荡区间，适合做反转吗",
        ],
        "queries_eval": [
            "BTC 震荡，高抛低吸怎么做",
            "ETH 均值回归，现在偏离吗",
            "BTC 区间上下沿",
            "震荡行情 BTC 怎么操作",
            "ETH 横盘，能反向做吗",
        ],
    },
    {
        "gold_intent": "breakout",
        "scenario_id": "BREAKOUT_UP",
        "market_features": {"regime": "breakout", "volatility": "high", "data_freshness": "realtime"},
        "queries_train": [
            "BTC 突破前高了，能追突破吗",
            "以太坊向上突破，突破策略怎么做",
            "BTC 突破阻力位，跟进吗",
            "ETH 放量突破，突破交易可行吗",
            "BTC 突破信号，现在能入场吗",
            "向上突破 BTC，目标位在哪",
            "BTC 突破确认，突破策略生效吗",
            "ETH 跌破支撑，向下突破吗",
            "BTC 突破后回踩，能追吗",
            "突破行情 BTC，怎么操作",
        ],
        "queries_eval": [
            "BTC 突破了吗，能追吗",
            "ETH 突破策略",
            "BTC 突破阻力位",
            "突破行情 BTC 怎么做",
            "ETH 向上突破，跟进吗",
        ],
    },
]


def gen_scenario(intent: str, scenario_id: str, split: str, idx: int,
                 query: str, market_features: dict) -> dict:
    """生成单个场景 YAML 字典"""
    return {
        "name": f"P1-{intent.upper()}-{scenario_id}-{split}-{idx:03d}",
        "description": f"{intent} 意图 × {scenario_id} 场景 ({split})",
        "timeout": 60,
        "retry": 0,
        "intent_training": {
            "gold_intent": intent,
            "scenario_id": scenario_id,
            "split": split,
            "market_features": market_features,
        },
        "steps": [
            {"name": "打开聊天页面", "action": "navigate", "url": "http://localhost:3001/chat"},
            {"name": "输入问法", "action": "type",
             "selector": "textarea, input[type='text'], [contenteditable]",
             "text": query, "human": True},
            {"name": "提交查询", "action": "click",
             "selector": "button[type='submit'], button:has-text('发送')", "human": True},
            {"name": "等待响应", "action": "wait", "seconds": 3},
        ],
    }


def main():
    out_dir = Path("scenarios/intent_training")
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for entry in MATRIX:
        for idx, q in enumerate(entry["queries_train"], 1):
            sc = gen_scenario(entry["gold_intent"], entry["scenario_id"], "train", idx, q, entry["market_features"])
            fname = f"{entry['gold_intent']}_{entry['scenario_id']}_train_{idx:03d}.yaml"
            with open(out_dir / fname, "w", encoding="utf-8") as f:
                yaml.dump(sc, f, allow_unicode=True, sort_keys=False)
            count += 1
        for idx, q in enumerate(entry["queries_eval"], 1):
            sc = gen_scenario(entry["gold_intent"], entry["scenario_id"], "eval", idx, q, entry["market_features"])
            fname = f"{entry['gold_intent']}_{entry['scenario_id']}_eval_{idx:03d}.yaml"
            with open(out_dir / fname, "w", encoding="utf-8") as f:
                yaml.dump(sc, f, allow_unicode=True, sort_keys=False)
            count += 1
    print(f"生成 {count} 个场景文件 → {out_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行生成脚本**

Run: `cd 30-真实环境交互系统 && python scripts/gen_p1_scenarios.py`
Expected: 输出 "生成 45 个场景文件 → scenarios/intent_training"

- [ ] **Step 3: 验证 YAML 数量 + 字段**

Run: `ls 30-真实环境交互系统/scenarios/intent_training/*.yaml | wc -l`
Expected: 45

验证字段（抽查一个）：

```bash
python -c "
import yaml
with open('30-真实环境交互系统/scenarios/intent_training/trend_following_TREND_UP_train_001.yaml') as f:
    d = yaml.safe_load(f)
assert d['intent_training']['gold_intent'] == 'trend_following'
assert d['intent_training']['scenario_id'] == 'TREND_UP'
assert d['intent_training']['split'] == 'train'
print('YAML 字段验证通过')
"
```

- [ ] **Step 4: Commit**

```bash
git add 30-真实环境交互系统/scripts/gen_p1_scenarios.py 30-真实环境交互系统/scenarios/intent_training/
git commit -m "feat(intent-training): add P1 scenario matrix 45 YAML (Task 6/8)"
```

---

## Task 7: 端到端验证

**Files:** 无新文件，验证 Task 1-6 集成

- [ ] **Step 1: 跑全量单测**

Run: `cd 30-真实环境交互系统 && python -m pytest tests/ -v`
Expected: 全部 PASS（含现有 test_scenario_runner.py + 5 个新测试文件，共 ~22 个测试）

- [ ] **Step 2: 模拟端到端 pipeline（无需真实 DreamOS）**

写一个临时验证脚本 `30-真实环境交互系统/scripts/e2e_smoke.py`：

```python
"""端到端 smoke 测试：YAML → ScenarioRunner → IntentSample → Pipeline → EvalGate

不依赖真实 DreamOS（用 mock route_fn）。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scenario_runner import ScenarioRunner
from core.intent_sample_pipeline import IntentSamplePipeline
from training.eval_gate import IntentEvalGate


def main():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    pipeline = IntentSamplePipeline(storage_path=tmp, bucket_threshold=30)
    config = {"scenarios": {"default_timeout": 10, "retry_count": 0}}
    runner = ScenarioRunner(config, MagicMock(), MagicMock(), pipeline=pipeline)

    # 模拟 DreamOS /intent/route 返回正确意图
    def mock_route(text):
        if "趋势" in text or "顺势" in text:
            return {"predicted_intent": "trend_following", "confidence": 0.85, "level": "rule"}
        if "震荡" in text or "高抛低吸" in text or "均值回归" in text:
            return {"predicted_intent": "mean_reversion", "confidence": 0.80, "level": "rule"}
        if "突破" in text:
            return {"predicted_intent": "breakout", "confidence": 0.82, "level": "rule"}
        return {"predicted_intent": "uncertain", "confidence": 0.3, "level": "rule"}

    # 跑 5 个 train + 2 个 eval 场景（抽样，不全跑 45 个）
    scenario_dir = Path("scenarios/intent_training")
    train_files = sorted(scenario_dir.glob("*_train_00[1-5].yaml"))[:3]
    eval_files = sorted(scenario_dir.glob("*_eval_00[1-2].yaml"))[:2]

    with patch.object(runner, "_call_dreamos_intent_route", side_effect=mock_route):
        with patch.object(runner, "_extract_user_input", return_value="BTC 趋势"):
            for f in train_files + eval_files:
                scenario = runner.load_scenario(str(f))
                mock_page = MagicMock()
                runner.run(mock_page, scenario)

    # 验证 IntentSample 落盘
    train_samples = pipeline.load_split("train")
    eval_samples = pipeline.load_split("eval")
    print(f"train 样本: {len(train_samples)}, eval 样本: {len(eval_samples)}")
    assert len(train_samples) == 3
    assert len(eval_samples) == 2

    # 跑 eval 回归门
    gate = IntentEvalGate(pipeline, route_fn=mock_route, accuracy_target=0.5, drift_limit=0.5)
    report = gate.run_eval()
    print(f"EvalReport: accuracy={report.accuracy:.2f} passed={report.passed} "
          f"zero_token_ratio={report.zero_token_ratio:.2f}")
    assert report.accuracy >= 0.5
    print("✓ 端到端 smoke 验证通过")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 运行 smoke 测试**

Run: `cd 30-真实环境交互系统 && python scripts/e2e_smoke.py`
Expected: 输出 "✓ 端到端 smoke 验证通过"

- [ ] **Step 4: 验证分桶计数**

```bash
python -c "
import sys, tempfile
from pathlib import Path
sys.path.insert(0, '30-真实环境交互系统')
from core.intent_sample_pipeline import IntentSamplePipeline
from core.intent_sample_pipeline import IntentSample
p = IntentSamplePipeline(storage_path=Path(tempfile.mkdtemp()), bucket_threshold=30)
# 灌 10 个 train + 5 个 eval
for i in range(10):
    p.ingest(IntentSample(sample_id=f't{i}', input={'user_query':'q','scenario_id':'TREND_UP'}, gold={'gold_chain':'C','gold_intent':'trend_following'}, recognizer_output={'predicted_intent':'trend_following','confidence':0.8,'level':'rule'}, human_label={'confirmed':True,'corrected_intent':None}, dataset_split='train', created_at='2026-10-04T10:00:00Z'))
for i in range(5):
    p.ingest(IntentSample(sample_id=f'e{i}', input={'user_query':'q','scenario_id':'TREND_UP'}, gold={'gold_chain':'C','gold_intent':'trend_following'}, recognizer_output={'predicted_intent':'trend_following','confidence':0.8,'level':'rule'}, human_label={'confirmed':True,'corrected_intent':None}, dataset_split='eval', created_at='2026-10-04T10:00:00Z'))
assert p.bucket_counter[('trend_following','TREND_UP')] == 10  # 10 < 30，不触发训练
assert len(p.load_split('eval')) == 5
print('✓ 分桶+触发逻辑验证通过')
"
```

- [ ] **Step 5: Commit smoke 脚本**

```bash
git add 30-真实环境交互系统/scripts/e2e_smoke.py
git commit -m "test(intent-training): add e2e smoke test (Task 7/8)"
```

---

## Task 8: 认知闭环（record + verify）

**Files:** 无代码文件，调用 mcp_cognitive

- [ ] **Step 1: record 训练经验**

调用 `record`：

```
content: "[实施][意图识别训练闭环] SPEC-20261004 实施完成：30 系统内构建 IntentSample 产出→落盘→分桶→触发训练→eval 回归完整闭环。关键调整(SD-1~SD-6)：(1)训练逻辑放 30 系统 core/intent_trainer.py(HC-1a合规)，不修改 dreamos/；(2)bayesian_memory_updater.py 不存在，IntentTrainer 内实现 Beta 分布贝叶斯；(3)OrchestrationMemory/RuleBasedRecognizer 的 update_mapping/add_rule 不存在，IntentTrainer 维护独立 JSON；(4)ScenarioRunner 用可选 pipeline=None 参数+run()末尾钩子，保持向后兼容。MVP 45 场景<30阈值不触发实际训练，只验证 pipeline 逻辑。3 步训练动作: update_weights(贝叶斯后验) / distill_to_rules(≥85%准确率) / refine_orchestration(L3→L0)。"
quality_level: "B"
tags: "实施,意图识别训练,HC-1a,30系统,IntentTrainer,贝叶斯更新,规则蒸馏,SD调整"
```

- [ ] **Step 2: verify 升级既有记忆**

对 `VM-1789693592908`（意图识别文档对齐）执行 `verify(success=True)`：本次实施延续了该记忆的 35 型正典 + 4 级管线设计。

对 `VM-1790698674859`（DreamOS 训练路线 v3 硬约束）执行 `verify(success=True)`：本次实施了 S 层意图识别训练闭环（第一重点）。

- [ ] **Step 3: 更新 project_memory（如适用）**

如有新的项目级规则（如"训练逻辑必须在 30 系统内，不修改 dreamos/"），追加到 `/Users/zhangjiangtao/.trae-cn/memory/projects/-Users-zhangjiangtao-WorkBuddy-dreambuddy-v2--p2-5f8e8db8067187fd2690/project_memory.md`。

---

## Self-Review

**1. Spec coverage 检查**：
- spec §3.1 YAML 格式扩展 → Task 1（test_yaml_intent_training_field_parse）+ Task 6（45 YAML）✓
- spec §3.2 ScenarioRunner 扩展 → Task 4（SD-5 调整）✓
- spec §3.3 IntentSamplePipeline → Task 2 ✓
- spec §3.4 DynamicRecognizer 训练动作 → Task 3（SD-1 调整为 IntentTrainer）✓
- spec §3.5 IntentEvalGate → Task 5 ✓
- spec §4 数据流 → Task 7 e2e smoke ✓
- spec §5 TDD 17 测试 → Tasks 1-5 共 22 个测试（覆盖 spec 17 个 + 增量）✓
- spec §6 P1 验收对齐 → Task 6 + Task 7 ✓
- spec §7 边界守护（HC-1a/5/7/9）→ Global Constraints + SD 调整 ✓
- spec §8 Phase 1-9 → Tasks 1-8 映射 ✓
- spec §9 待确认项 → 用户已确认（MVP 45 + threshold 30 + distill 0.85）✓

**2. Placeholder scan**：
- 无 "TBD"/"TODO"/"fill in" ✓
- 所有代码块完整 ✓
- 所有 Run 命令明确 ✓

**3. Type consistency**：
- `IntentSample` 字段在 Tasks 1-5 一致 ✓
- `IntentSamplePipeline` 构造参数在 Tasks 2/4/5 一致 ✓
- `IntentTrainer` 方法签名在 Tasks 2/3 一致（update_weights/distill_to_rules/refine_orchestration）✓
- `EvalReport` 字段在 Task 5 一致 ✓
- `bucket_key` 类型 `Tuple[str, str]` 在 Tasks 2/3 一致 ✓

**4. 关键张力说明**：
- **MVP 与训练触发**：MVP 45 场景每桶 10 train < 30 阈值，不触发实际训练。这是用户接受的折中（先验证 pipeline，再扩容触发训练）。Task 7 的 e2e smoke 用 mock route_fn 验证逻辑正确性。
- **HC-1a 与 spec §3.4 张力**：spec §3.4 字面要扩展 dynamic.py，但 HC-1a 禁止。本计划采用 SD-1 调整（IntentTrainer 适配器），在 Global Constraints 和 SD 表明确说明。如用户坚持 spec §3.4 字面，需重新评审 HC-1a 边界。

---

## Execution Handoff

Plan complete and saved to `1-ARCHITECTURE/PLAN-20261004-INTENT-TRAINING-LOOP-30-SYSTEM.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration. Each task has clear Files/Interfaces/Steps boundaries suitable for fresh-context execution.

**2. Inline Execution** - Execute tasks in this session sequentially, batch execution with checkpoints between tasks for your review.

**Which approach?**

Note: Task 3 (IntentTrainer) and Task 4 (ScenarioRunner) involve the SD-1~SD-6 spec deviations from HC-1a — recommend executing these two tasks with extra review attention to confirm the deviation decisions are acceptable before proceeding to Task 5+.
