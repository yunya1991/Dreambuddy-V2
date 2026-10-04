# SPEC-20261004 — DreamOS S 层意图识别训练闭环（30 真实环境交互系统接入）

**版本**: v1.0
**日期**: 2026-10-04
**作者**: Trae + User
**状态**: Draft（待用户审阅 → 转入 implementation）
**方法论**: brainstorming skill（设计审批前不写代码）
**关联文档**:
- [SPEC-20260929-DREAMOS-渐进式能力演进路线.md](./SPEC-20260929-DREAMOS-渐进式能力演进路线.md) v3.0（两大训练核心 + P0-P5 路线）
- [SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md](./dream-harness-bridge/SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md) v0.1（三层分工：算法驱动 / Harness 评审训练 / Agent 接管）
- [INTENT_ROUTER.md](../3.1-FRONTEND/dream-universal-gateway/docs/INTENT_ROUTER.md) v3.0（35 型正典 + 4 级管线）
- [intent-taxonomy.md](./intent-recognition-spec/intent-taxonomy.md) v1.1（6×30 对话意图规范）
- [30-真实环境交互系统/SKILL.md](../30-真实环境交互系统/SKILL.md) v2.2（四引擎架构 + 协同 skill）

---

## 0. Executive Summary

**核心命题**：调用 30-真实环境交互系统跑真实用户交互场景，产出 IntentSample 训练素材，驱动 DreamOS S 层意图识别能力训练（第一重点），补全 SPEC-20260929 §2.1 的训练数据 pipeline 缺口。

**与 SPEC-20260929 的关系**：本 SPEC 是 SPEC-20260929 v3.0 §2.1「训练核心一：S 层意图识别」的**实施细化**——补全"IntentSample 如何从 30 系统产出"这一未明确定义的环节。不修改 SPEC-20260929 的训练动作设计（贝叶斯更新 + 规则蒸馏 + OrchestrationMemory 精确化），只补全数据流入口。

**范围边界**：
- ✓ S 层意图识别训练闭环（30 系统 → IntentSample → DynamicRecognizer 训练）
- ✗ C-Drive-Agent 四步循环训练（第二重点，后续单独做）
- ✗ 9 个 subagent 接入（P2-P4 范围）
- ✗ Bull/Bear 辩论 / LLM 内容汇总（P3-P4 范围）

---

## 1. 设计决策汇总（用户已确认）

| 编号 | 决策点 | 选择 | 理由 |
|---|---|---|---|
| D1 | 训练数据链路 | **IntentSample 直接入库** | 完全对齐 SPEC-20260929 IntentSample 设计，路径最短，不依赖 evolution-case-ingest |
| D2 | 标注来源 | **YAML 预设 gold_intent** | 30 系统跑场景时 DreamOS intent_engine 产出 recognizer_output，自动对照 gold_intent 生成 human_label；符合「代码驱动+算层为主」偏好 |
| D3 | 30 引擎选择 | **线1 脚本引擎（YAML+Playwright）为主** | 批量产出可控多样化问法，成本低、可复现；产出 train 集 |
| D4 | 训练触发节奏 | **实时入库 + 分桶触发训练** | IntentSample 实时落盘，某桶 ≥30 时自动触发 DynamicRecognizer 权重更新 |
| D5 | eval 集来源 | **YAML 预留 eval 场景** | YAML 标记 `split: train\|eval`，预留 20% 场景作 eval，可复现 |

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  YAML 场景文件（train/eval 预设）                              │
│  - gold_intent: 35型正典  - scenario_id: 36场景              │
│  - split: train|eval    - user_query: 真实问法                │
│  - market_features: 上下文                                   │
└──────────────────┬──────────────────────────────────────────┘
                   │ 线1 脚本引擎批量执行
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  30 系统 scenario_runner.py（扩展）                            │
│  - 跑 YAML 场景 → 调用 DreamOS /intent/route                  │
│  - 产出 recognizer_output（predicted_intent + confidence）    │
│  - 自动对照 gold_intent 生成 human_label                      │
│  - 产出 IntentSample（input + gold + recognizer_output +     │
│    human_label + dataset_split）                              │
└──────────────────┬──────────────────────────────────────────┘
                   │ IntentSample 实时落盘
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  intent_sample_pipeline.py（新建）                             │
│  - 落盘路径：30-真实环境交互系统/training/intent_samples/      │
│  - 分桶：意图×scenario_id 维度统计样本数                       │
│  - 触发：某桶 ≥N（P1 阶段 N=30）时触发 DynamicRecognizer 训练  │
└──────────────────┬──────────────────────────────────────────┘
                   │ 分桶触发
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  DynamicRecognizer 训练动作（方案 C：贝叶斯更新+规则蒸馏）      │
│  - Step 1：按桶统计先验分布，新样本做贝叶斯后验更新            │
│            （复用 dreamos/core/memory/bayesian_memory_updater.py）
│  - Step 2：高频且一致的桶（同桶 ≥N 且准确率 ≥85%）             │
│            → 蒸馏为零 Token 规则（RuleBasedRecognizer）        │
│  - Step 3：OrchestrationMemory 场景→链路映射精确化（L3→L0）    │
│  - 产出：updated weights + distilled rules + 训练报告         │
└──────────────────┬──────────────────────────────────────────┘
                   │ 训练完成
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  eval 回归门 + 认知闭环                                        │
│  - 跑 eval 集：意图识别准确率、零 Token 占比、路由命中率        │
│  - 准确率波动 <3% 才允许上线（P5 标准）                        │
│  - record 训练经验进认知库，verify 升级                        │
└─────────────────────────────────────────────────────────────┘
```

**核心组件清单**：
1. YAML 场景格式扩展（现有 e2e_market_query.yaml 加 4 字段）
2. scenario_runner.py 扩展（现有 30 系统组件，加 IntentSample 产出钩子）
3. intent_sample_pipeline.py（新建）：落盘 + 分桶 + 触发训练
4. DynamicRecognizer 训练动作扩展（扩展现有 `dreamos/core/sense/recognizers/dynamic.py`）
5. eval 回归门（新建 `30-真实环境交互系统/training/eval_gate.py`）

---

## 3. 组件设计

### 3.1 YAML 场景格式扩展

基于现有 `30-真实环境交互系统/scenarios/examples/e2e_market_query.yaml` 结构，新增 4 个训练字段：

```yaml
name: "P1-TREND-001-趋势跟随问法"
description: "TREND_FOLLOWING 意图 × 趋势上升场景"
timeout: 180
retry: 1

# === 新增训练字段 ===
intent_training:
  gold_intent: "trend_following"        # 35型正典（P1 阶段聚焦 TREND_FOLLOWING/MEAN_REVERSION/BREAKOUT 三类）
  scenario_id: "TREND_UP"               # 36 场景之一（来自 dreamos/core/sense/scenario_classifier.py）
  split: "train"                        # train | eval
  market_features:                       # 上下文快照
    regime: "trending"
    volatility: "medium"
    data_freshness: "realtime"

steps:
  - name: "打开聊天页面"
    action: navigate
    url: "http://localhost:3001/chat"
  - name: "输入趋势问法"
    action: type
    text: "BTC 现在是上升趋势吗，要不要顺势加仓"
    human: true
  # ... 其余步骤同现有格式
```

#### P1 阶段场景矩阵

**36 场景说明**：`dreamos/core/sense/scenario_classifier.py` 定义 36 场景（6 市场状态 × 6 子状态组合）。P1 阶段聚焦其中 6 个最相关场景作为 MVP 子集，P2-P5 逐步扩展到全 36 场景。

| 意图 × 场景 | TREND_UP | TREND_DOWN | RANGE | VOLATILE | BREAKOUT_UP | BREAKOUT_DOWN |
|---|---|---|---|---|---|---|
| TREND_FOLLOWING | ✓ train×5 | ✓ train×5 | ✗ | ✓ eval×3 | ✓ train×5 | ✓ train×5 |
| MEAN_REVERSION | ✗ | ✗ | ✓ train×5 | ✓ eval×3 | ✗ | ✗ |
| BREAKOUT | ✓ eval×3 | ✗ | ✗ | ✓ train×5 | ✓ train×5 | ✓ train×5 |

**目标样本数**（P1 末）：
- train ≥ 90（3 意图 × 5 问法 × 6 场景 = 90，扣除 ✗ 项）
- eval ≥ 30（预留 20%）
- 总计 ≥ 120 IntentSample

#### 35 型正典与 P1 三类意图的映射

根据 `INTENT_ROUTER.md` v3.0 的 35 型正典 + `canon_intent_bridge.py` 的双向映射：
- P1 训练用 7 型策略意图的子集（TREND_FOLLOWING / MEAN_REVERSION / BREAKOUT）
- 通过 `dreamOSToCanon()` 转换为 35 型正典存储（gold_intent 字段）
- eval 准确率统计在 35 型粒度（最细粒度，可向上映射到 7 型/6×25）

---

### 3.2 scenario_runner.py 扩展

**文件路径**：`30-真实环境交互系统/core/scenario_runner.py`（现有文件扩展）

**新增接口**：

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class IntentSample:
    sample_id: str               # UUID
    input: dict                  # {user_query, scenario_id, market_features, data_freshness}
    gold: dict                   # {gold_chain, gold_intent}
    recognizer_output: dict      # {predicted_intent, confidence, level}
    human_label: dict            # {confirmed, corrected_intent?, corrected_chain?}
    dataset_split: str           # train | eval
    created_at: str              # ISO8601


class ScenarioRunner:
    """现有 ScenarioRunner 扩展（不破坏现有 run_scenario 接口）"""

    def run_scenario(self, yaml_path: str) -> "ScenarioResult":
        scenario = self._load_yaml(yaml_path)
        result = self._execute_steps(scenario.steps)

        # === 新增：训练钩子 ===
        if scenario.get("intent_training"):
            intent_sample = self._build_intent_sample(scenario, result)
            # 调用 DreamOS /intent/route 获取 recognizer_output
            recognizer_output = self._call_dreamos_intent_route(result.user_input)
            intent_sample.recognizer_output = recognizer_output
            intent_sample.human_label = self._auto_label(
                recognizer_output, scenario.intent_training.gold_intent
            )
            # 实时落盘到 pipeline
            self.pipeline.ingest(intent_sample)

        return result

    def _build_intent_sample(self, scenario, result) -> IntentSample:
        """从 YAML 场景 + 执行结果构建 IntentSample"""
        ...

    def _call_dreamos_intent_route(self, user_input: str) -> dict:
        """调用 DreamOS /intent/route 端点（HC-7 FAIL-OPEN）"""
        ...

    def _auto_label(self, recognizer_output, gold_intent) -> dict:
        """自动对照 gold_intent 生成 human_label"""
        confirmed = recognizer_output.get("predicted_intent") == gold_intent
        return {
            "confirmed": confirmed,
            "corrected_intent": None if confirmed else gold_intent
        }
```

**FAIL-OPEN 边界守护**（HC-7）：
- DreamOS `/intent/route` 不可用时：recognizer_output 留空 `{"predicted_intent": None, "confidence": 0.0, "level": "failopen"}`，human_label.confirmed=False
- IntentSample 仍落盘（用于后续人工补标）
- 6 层堆栈日志记录降级路径

**与现有 scenario_runner.py 的兼容性**：
- 不修改现有 `run_scenario()` 的返回值 `ScenarioResult`
- 新增的 `_build_intent_sample / _call_dreamos_intent_route / _auto_label` 是私有方法
- 现有测试 `test_scenario_runner.py` 不破坏

---

### 3.3 intent_sample_pipeline.py（新建）

**文件路径**：`30-真实环境交互系统/core/intent_sample_pipeline.py`

```python
import json
import uuid
from pathlib import Path
from collections import defaultdict
from typing import Optional

class IntentSamplePipeline:
    """IntentSample 落盘 + 分桶统计 + 触发训练"""

    STORAGE_PATH = Path("30-真实环境交互系统/training/intent_samples/")
    BUCKET_THRESHOLD = 30          # P1 阶段触发训练的样本数阈值
    DISTILL_ACCURACY_TARGET = 0.85  # 规则蒸馏的准确率阈值

    def __init__(self):
        self._bucket_counter: dict[tuple[str, str], int] = defaultdict(int)
        self.STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    def ingest(self, sample: IntentSample) -> None:
        """实时落盘 + 分桶统计 + 触发训练"""
        self._persist(sample)
        bucket_key = (sample.gold["gold_intent"], sample.input["scenario_id"])
        self._bucket_counter[bucket_key] += 1
        if self._bucket_counter[bucket_key] >= self.BUCKET_THRESHOLD:
            self._trigger_training(bucket_key)

    def _persist(self, sample: IntentSample) -> None:
        """落盘到 STORAGE_PATH/{bucket_key}/{sample_id}.json"""
        bucket_dir = self.STORAGE_PATH / f"{sample.gold['gold_intent']}_{sample.input['scenario_id']}"
        bucket_dir.mkdir(parents=True, exist_ok=True)
        with open(bucket_dir / f"{sample.sample_id}.json", "w") as f:
            json.dump(sample.__dict__, f, indent=2, ensure_ascii=False)

    def _trigger_training(self, bucket_key: tuple[str, str]) -> None:
        """触发 DynamicRecognizer 贝叶斯更新 + 规则蒸馏"""
        samples = self._load_bucket(bucket_key)
        accuracy = self._compute_accuracy(samples)

        # 调用 dreamos/core/sense/recognizers/dynamic.py 训练接口
        from dreamos.core.sense.recognizers.dynamic import DynamicRecognizer
        DynamicRecognizer.update_weights(bucket_key, samples)

        if accuracy >= self.DISTILL_ACCURACY_TARGET and len(samples) >= self.BUCKET_THRESHOLD:
            DynamicRecognizer.distill_to_rules(bucket_key, samples)
            DynamicRecognizer.refine_orchestration(bucket_key, samples)

        # 记录认知经验（对齐 CLAUDE.md 硬约束）
        # record(content=f"意图训练桶 {bucket_key} 完成 accuracy={accuracy}", ...)

    def load_split(self, split: str) -> list[IntentSample]:
        """加载 train 或 eval 集样本（供 eval 回归门使用）"""
        ...

    def _load_bucket(self, bucket_key) -> list[IntentSample]:
        ...

    def _compute_accuracy(self, samples) -> float:
        """计算分桶准确率"""
        if not samples:
            return 0.0
        correct = sum(1 for s in samples if s.human_label["confirmed"])
        return correct / len(samples)
```

**触发训练后桶计数清零**：避免重复触发，需等下一批样本累积。

---

### 3.4 DynamicRecognizer 训练动作扩展

**文件路径**：`dreamos/core/sense/recognizers/dynamic.py`（现有文件扩展）

**3 步训练动作**（对齐 SPEC-20260929 §2.1）：

```python
class DynamicRecognizer:
    """现有 DynamicRecognizer 扩展训练类方法"""

    @classmethod
    def update_weights(cls, bucket_key: tuple[str, str], samples: list) -> None:
        """Step 1: 贝叶斯后验更新（复用 bayesian_memory_updater.py）"""
        from dreamos.core.memory.bayesian_memory_updater import BayesianMemoryUpdater
        prior = cls._load_prior(bucket_key)
        posterior = BayesianMemoryUpdater.update(prior, samples)
        cls._save_posterior(bucket_key, posterior)

    @classmethod
    def distill_to_rules(cls, bucket_key: tuple[str, str], samples: list) -> None:
        """Step 2: 高频模式蒸馏为零 Token 规则（→ RuleBasedRecognizer）"""
        from dreamos.core.sense.recognizers.rule_based import RuleBasedRecognizer
        common_features = cls._extract_common_features(samples)
        RuleBasedRecognizer.add_rule(bucket_key, common_features)

    @classmethod
    def refine_orchestration(cls, bucket_key: tuple[str, str], samples: list) -> None:
        """Step 3: OrchestrationMemory 场景→链路映射精确化（L3→L0）"""
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory
        OrchestrationMemory.update_mapping(bucket_key, samples)

    # 私有辅助方法
    @classmethod
    def _load_prior(cls, bucket_key) -> dict: ...
    @classmethod
    def _save_posterior(cls, bucket_key, posterior) -> None: ...
    @classmethod
    def _extract_common_features(cls, samples) -> dict: ...
```

**蒸馏触发条件**（硬约束）：
- 同桶样本数 ≥ 30（BUCKET_THRESHOLD）
- 分桶准确率 ≥ 85%（DISTILL_ACCURACY_TARGET）
- 两个条件同时满足才蒸馏，避免低质量规则污染 RuleBasedRecognizer

**与现有 dynamic.py 的兼容性**：
- 现有 `recognize()` 方法不变
- 新增 3 个 classmethod：`update_weights / distill_to_rules / refine_orchestration`
- 新增私有辅助方法

---

### 3.5 eval 回归门

**文件路径**：`30-真实环境交互系统/training/eval_gate.py`（新建）

```python
from dataclasses import dataclass

@dataclass
class EvalReport:
    accuracy: float
    drift: float
    passed: bool
    zero_token_ratio: float          # 零 Token 识别占比
    route_hit_ratio: float           # 路由命中率
    details: list[dict]


class IntentEvalGate:
    """eval 集回归门：训练后跑 eval 集验证准确率"""

    ACCURACY_TARGET = 0.75           # P3 末目标（SPEC §4）
    ACCURACY_DRIFT_LIMIT = 0.03      # P5 连续波动 <3%
    ZERO_TOKEN_TARGET = 0.50         # P3 末零 Token 占比 ≥50%

    def __init__(self, pipeline: IntentSamplePipeline):
        self.pipeline = pipeline
        self._last_accuracy: float | None = None

    def run_eval(self) -> EvalReport:
        """跑 eval 集，返回 EvalReport"""
        eval_samples = self.pipeline.load_split("eval")
        results = []
        zero_token_count = 0
        route_hit_count = 0

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

        accuracy = sum(results) / len(results) if results else 0.0
        drift = abs(accuracy - self._last_accuracy) if self._last_accuracy else 0.0

        passed = (
            accuracy >= self.ACCURACY_TARGET
            and drift < self.ACCURACY_DRIFT_LIMIT
        )

        report = EvalReport(
            accuracy=accuracy,
            drift=drift,
            passed=passed,
            zero_token_ratio=zero_token_count / len(eval_samples) if eval_samples else 0.0,
            route_hit_ratio=route_hit_count / len(eval_samples) if eval_samples else 0.0,
            details=[],
        )
        self._last_accuracy = accuracy
        return report

    def _call_dreamos_intent_route(self, user_input: str) -> dict:
        """调用 DreamOS /intent/route（HC-7 FAIL-OPEN）"""
        ...
```

---

## 4. 数据流细节

### 4.1 完整训练闭环时序

```
1. 用户编写 YAML 场景文件（含 gold_intent + scenario_id + split）
2. 30 系统 scenario_runner.py 加载 YAML
3. 执行 steps：navigate → type "BTC 现在是上升趋势吗" → click → wait → verify
4. 收集 user_input + 页面响应
5. 调用 DreamOS /intent/route {text: user_input}
   → 返回 {predicted_intent, confidence, level, canon_intent}
6. 构建 IntentSample:
   - input = {user_query, scenario_id, market_features, data_freshness}
   - gold = {gold_chain: "C", gold_intent: yaml.gold_intent}
   - recognizer_output = step 5 返回值
   - human_label = {confirmed: (predicted == gold), corrected_intent: ...}
   - dataset_split = yaml.split
7. pipeline.ingest(intent_sample)
   → 落盘到 STORAGE_PATH/{bucket_key}/{sample_id}.json
   → 分桶计数 +1
   → 若 ≥30 触发训练
8. DynamicRecognizer.update_weights(bucket_key, samples)
   → 贝叶斯后验更新
9. 若 accuracy ≥85% 且 ≥30：
   → DynamicRecognizer.distill_to_rules()（→ RuleBasedRecognizer）
   → DynamicRecognizer.refine_orchestration()（→ OrchestrationMemory）
10. 训练完成 → IntentEvalGate.run_eval()
    → 跑 eval 集验证准确率
    → 若 accuracy ≥75% 且 drift <3% → 上线
    → record 认知经验 → verify 升级
```

### 4.2 IntentSample 存储布局

```
30-真实环境交互系统/training/intent_samples/
├── trend_following_TREND_UP/
│   ├── {uuid1}.json
│   ├── {uuid2}.json
│   └── ... (≥30 个 → 触发训练)
├── trend_following_TREND_DOWN/
├── mean_reversion_RANGE/
├── breakout_VOLATILE/
└── ...
```

每个 JSON 文件格式：
```json
{
  "sample_id": "uuid",
  "input": {"user_query": "...", "scenario_id": "TREND_UP", "market_features": {...}, "data_freshness": "realtime"},
  "gold": {"gold_chain": "C", "gold_intent": "trend_following"},
  "recognizer_output": {"predicted_intent": "trend_following", "confidence": 0.82, "level": "rule"},
  "human_label": {"confirmed": true, "corrected_intent": null},
  "dataset_split": "train",
  "created_at": "2026-10-04T16:00:00Z"
}
```

**gold_chain 字段说明**：对齐 SPEC-20260929 §2.1 IntentSample 格式，取值为 `C | F | A` 三大思维链：
- `C` = C 链（技术面：扫描→识别→匹配→回测→参数）—— TREND_FOLLOWING / MEAN_REVERSION / BREAKOUT 均走 C 链
- `F` = F 链（基本面：新闻→资金→情绪→链上→宏观）—— P2 阶段 FUNDAMENTAL_PLAY 走 F 链
- `A` = A 链（执行环：矛盾→调研→原理→沙盘→验证→执行→离场）

---

## 5. TDD 范围

### 5.1 RED 测试列表（17 个，按依赖顺序）

```python
# 测试文件位置：30-真实环境交互系统/tests/

# 1. 数据契约层（先测数据结构）
test_intent_sample_contract.py
  - test_intent_sample_dataclass_fields         # 5 字段齐全
  - test_intent_sample_serialization            # JSON 往返
  - test_yaml_intent_training_field_parse       # YAML 4 字段解析

# 2. Pipeline 层（核心训练闭环）
test_intent_sample_pipeline.py
  - test_ingest_persists_sample                 # 落盘成功
  - test_bucket_counter_increments              # 分桶计数
  - test_trigger_training_at_threshold          # ≥30 触发训练
  - test_no_trigger_below_threshold             # <30 不触发
  - test_eval_samples_not_count_train           # split 隔离

# 3. ScenarioRunner 扩展层
test_scenario_runner_intent_hook.py
  - test_build_intent_sample_from_yaml          # YAML → IntentSample
  - test_call_dreamos_intent_route              # 调用 /intent/route
  - test_human_label_auto_compare               # 自动对照 gold_intent
  - test_failopen_when_dreamos_unavailable      # DreamOS 不可用降级

# 4. DynamicRecognizer 训练动作层
test_dynamic_recognizer_training.py
  - test_update_weights_bayesian                # 贝叶斯后验更新
  - test_distill_to_rules_at_threshold          # ≥85% 准确率蒸馏
  - test_no_distill_below_accuracy              # <85% 不蒸馏
  - test_refine_orchestration_mapping            # 场景→链路映射

# 5. Eval 回归门层
test_intent_eval_gate.py
  - test_run_eval_returns_report                # 返回 EvalReport
  - test_accuracy_below_target_fails            # <75% 不通过
  - test_drift_exceeds_limit_fails              # 波动 ≥3% 不通过
```

**RED 测试断言**：
- 新建模块：`ModuleNotFoundError`（intent_sample_pipeline / eval_gate）
- 扩展方法：`AttributeError`（DynamicRecognizer.update_weights / ScenarioRunner._build_intent_sample）

### 5.2 GREEN 实现顺序（最简实现）

```
1. IntentSample dataclass          → test_intent_sample_contract
2. YAML intent_training field 解析  → test_yaml_intent_training_field_parse
3. IntentSamplePipeline.ingest     → test_intent_sample_pipeline (4 个)
4. ScenarioRunner 扩展钩子         → test_scenario_runner_intent_hook (4 个)
5. DynamicRecognizer 训练动作      → test_dynamic_recognizer_training (4 个)
6. IntentEvalGate                  → test_intent_eval_gate (3 个)
```

### 5.3 REFACTOR 检查点

- 全套 17 测试无回归
- DreamOS 现有 `intent_engine.py` 测试不破坏（HC-1a：不修改 dreamos/ 核心代码，只 import）
- 30 系统现有 `test_scenario_runner.py` 不破坏（扩展私有方法，不改 run_scenario 接口）

---

## 6. 与 SPEC-20260929 P1 验收对齐

| P1 验收标准（SPEC §3.1） | 本设计如何满足 |
|---|---|
| ① 单问题"分析 BTC 技术面"→ 报告五要素齐全 | 30 系统跑 e2e_market_query.yaml + 断言响应含 BTC |
| ② C-Drive recall+反思在 50ms 内完成 | **不在本次范围**（C 层训练是第二重点，本次只做 S 层） |
| ③ 10 个 IntentSample 有人工标签 | YAML 预设 gold_intent 即人工标签，P1 末产出 ≥90 train + 30 eval |
| **额外**：S 层意图识别准确率 ≥75%（P3 末） | eval 回归门 ACCURACY_TARGET=0.75 |
| **额外**：零 Token 识别占比 ≥50%（P3 末） | 规则蒸馏后 RuleBasedRecognizer 占比统计（eval 回归门 zero_token_ratio） |
| **额外**：路由命中率 ≥70%（P3 末） | eval 回归门 route_hit_ratio |

---

## 7. 风险与边界守护

| 风险 | 缓解 |
|---|---|
| DreamOS `/intent/route` 不可用 | HC-7 FAIL-OPEN：recognizer_output 留空，IntentSample 仍落盘供后续补标 |
| 训练数据污染（YAML gold_intent 标错） | YAML 评审门禁 + eval 集交叉验证（train 误标会拉低 eval 准确率） |
| 规则蒸馏过早（低质量规则污染 RuleBasedRecognizer） | 双阈值硬约束：样本 ≥30 且准确率 ≥85% 才蒸馏 |
| DreamOS 核心代码被改（HC-1a 违反） | 训练逻辑在 30 系统内，`dreamos/` 只 import 不修改 |
| 训练桶样本不平衡 | P1 场景矩阵保证每意图×场景 ≥5 train 样本；不平衡时记录 warning |
| mcp_cognitive 不可用 | record 调用 FAIL-OPEN（认知闭环降级，不影响训练主流程） |

**硬约束对齐**：
- HC-1a：不修改 dreamos/ 核心代码（只 import 调用）
- HC-5：reward 不参与（意图识别训练无 reward，只用准确率）
- HC-7：跨语言/跨进程 FAIL-OPEN（DreamOS /intent/route 调用失败降级）
- HC-9：Plugin 只透传不决策（30 系统 → DreamOS 调用是数据透传，决策在 DreamOS 内部）

---

## 8. 实施路线（待用户审阅后启动）

| 阶段 | 任务 | 验收 |
|---|---|---|
| Phase 1 | 写 17 个 RED 测试 | 全部失败（ModuleNotFoundError/AttributeError） |
| Phase 2 | GREEN 实现 IntentSample dataclass | test_intent_sample_contract 通过 |
| Phase 3 | GREEN 实现 IntentSamplePipeline | test_intent_sample_pipeline 通过 |
| Phase 4 | GREEN 实现 ScenarioRunner 扩展 | test_scenario_runner_intent_hook 通过 |
| Phase 5 | GREEN 实现 DynamicRecognizer 训练动作 | test_dynamic_recognizer_training 通过 |
| Phase 6 | GREEN 实现 IntentEvalGate | test_intent_eval_gate 通过 |
| Phase 7 | 编写 P1 场景矩阵 YAML（≥120 场景） | YAML lint 通过 |
| Phase 8 | 端到端跑通：30 系统 → IntentSample → 训练 → eval | EvalReport.passed = True |
| Phase 9 | record 认知经验 + verify 升级 | 认知库更新 |

---

## 9. 待用户确认项

1. **场景矩阵规模**：P1 末 ≥120 场景（90 train + 30 eval），是否接受？还是先做 MVP（每意图 10 train + 5 eval = 45 场景）？
2. **触发训练阈值**：BUCKET_THRESHOLD=30 是否合适？还是先设 10 跑通快速验证？
3. **蒸馏准确率阈值**：DISTILL_ACCURACY_TARGET=0.85 是否合适？还是先设 0.70 鼓励早期蒸馏？
4. **spec 文档路径**：当前放在 `1-ARCHITECTURE/SPEC-20261004-INTENT-TRAINING-LOOP-30-SYSTEM.md`，是否接受？还是改放 `30-真实环境交互系统/docs/`？

---

## 附录 A：相关记忆库记录

- VM-1789693592908 (B级)：意图识别文档对齐代码实现完成（35 型正典 + 4 级管线）
- VM-1789628054845 (A级)：PROP-20260917 实施完成（35型映射函数 + TDD + Bug 修复）
- VM-1790698674859 (B级)：DreamOS 训练路线 v3 硬约束（S 层意图识别是第一重点）
- VM-1789627473439 (B级)：意图识别前后端一致性方案 4 项决策（35型↔7型 + 35型↔6×25 双向映射）
