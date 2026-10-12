"""P1 修复: outcome 信号 + prompt_pattern 归一化派生器
=====================================================
修复 LLM 层 success_count=0 + 权重衰减到 1e-12 的根因:

根因 1 (outcome 信号缺失):
  数据 collectors 不设 metadata["outcome"]，默认 "unknown" → "partial"。
  LLM 层从未收到 "success" 反馈 → success_count 恒为 0。

根因 2 (prompt_pattern 唯一):
  prompt_pattern = case.outcome_text (完整唯一内容)，每个模板只出现一次。
  EWMA λ=0.9 → 单次增长 0.45 后持续 ×0.1 衰减 → 12 步后 ~4.5e-13。

修复:
  1. derive_outcome(case): 从 quality/confidence 派生 outcome
     - quality S/A 或 confidence>=0.7 → success
     - quality B 或 0.4<=conf<0.7 → partial
     - quality C/D 或 conf<0.4 → failure
     - metadata.outcome 显式设置时优先
  2. normalize_prompt_pattern(case): 用 intent 或 outcome_text[:80] 归一化
     - 相似 case 共享 pattern → 模板可聚类 → 权重可积累

关联:
  - LLM 层: 3.1-FRONTEND/src/lib/llm-prompt-training-loop.ts
  - 转换层: ts_http_training_executor.py + run_continual_training.py
"""
from typing import Tuple


# outcome 派生阈值
CONF_SUCCESS = 0.7   # confidence >= 0.7 → success
CONF_PARTIAL = 0.4   # 0.4 <= conf < 0.7 → partial

# prompt_pattern 截断长度
PATTERN_MAX_LEN = 80
DEFAULT_PATTERN = "unknown_pattern"


def derive_outcome(case) -> str:
    """从 case 派生 outcome 信号。

    优先级:
      1. metadata.outcome 显式设置 (success/failure/partial) → 直接使用
      2. quality 等级 (S/A→success, B→partial, C/D→failure)
      3. confidence 兜底 (>=0.7 success, >=0.4 partial, <0.4 failure)

    Returns:
        "success" | "partial" | "failure"
    """
    metadata = getattr(case, "metadata", {}) or {}
    explicit = metadata.get("outcome")
    if explicit in ("success", "failure", "partial"):
        return explicit

    quality = getattr(case, "quality", "") or ""
    confidence = float(getattr(case, "confidence", 0.0) or 0.0)

    # quality 映射
    if quality in ("S", "A"):
        return "success"
    if quality == "B":
        return "partial"
    if quality in ("C", "D"):
        return "failure"

    # confidence 兜底
    if confidence >= CONF_SUCCESS:
        return "success"
    if confidence >= CONF_PARTIAL:
        return "partial"
    return "failure"


def normalize_prompt_pattern(case) -> str:
    """归一化 prompt_pattern，使相似 case 可聚类。

    优先级:
      1. case.intent (非空) — 同 intent 的 case 共享 pattern
      2. case.outcome_text[:PATTERN_MAX_LEN] — 截断避免唯一长文本
      3. DEFAULT_PATTERN — 兜底

    Returns:
        稳定的 pattern 字符串 (长度 <= PATTERN_MAX_LEN)
    """
    intent = getattr(case, "intent", "") or ""
    if intent:
        return intent[:PATTERN_MAX_LEN]

    outcome_text = getattr(case, "outcome_text", "") or ""
    if outcome_text:
        return outcome_text[:PATTERN_MAX_LEN]

    return DEFAULT_PATTERN


def derive_outcome_and_pattern(case) -> Tuple[str, str]:
    """一次性派生 (outcome, prompt_pattern)。

    供 ts_http_training_executor.py 和 run_continual_training.py 调用。
    """
    return derive_outcome(case), normalize_prompt_pattern(case)
