"""dream-harness-bridge P0-5 训练数据质量门禁

Layer 训练闭环 — 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-5
对应风险: TR-6 训练数据污染（质量门禁 + 异常数据隔离）

设计原则:
    - FAIL-OPEN: 任何异常返回中性兜底（valid=False / quality_score=0），不阻塞调用方
    - HC-9: 只校验数据元数据，不做交易判断（不出现 direction/action/rsi/pnl/reward 等）
    - 纯校验模块，不写入文件，不修改数据

API:
    validate_sample(sample)       → 检查单条样本质量
    validate_dataset(dataset)     → 检查数据集整体质量（标签分布平衡性）
"""

from __future__ import annotations

import traceback
from typing import Any

# 复用 server.py 的 _send_stderr（结构化日志）
try:
    from server import _send_stderr
except ImportError:
    # 独立运行时 fallback
    import sys
    _send_stderr = lambda level, msg: sys.stderr.write(  # noqa: E731
        f"[{level}] {msg}\n"
    )

# 单条样本必需字段（HC-3 数据主权：训练样本必须可追溯）
_REQUIRED_FIELDS = ("id", "user_message", "algorithm_result")

# 标签分布平衡性阈值（最大占比不超过此值视为平衡）
_LABEL_BALANCE_MAX_RATIO = 0.80

# 数据集最小样本数（低于此值 quality_score 打折）
_MIN_DATASET_SIZE = 10


def validate_sample(sample: dict) -> dict:
    """检查单条样本质量

    校验项:
        1. 必需字段存在（id, user_message, algorithm_result）
        2. 字段类型合法（id 非空 str，user_message 非空 str，algorithm_result 为 dict）
        3. 标签一致性（若 label 非空，label_source 必须非空）

    输入:
        sample: dict — 单条训练样本

    输出:
        {valid: bool, errors: list[str]}

    FAIL-OPEN: 异常返回 valid=False
    """
    errors: list[str] = []
    try:
        if not isinstance(sample, dict):
            return {"valid": False, "errors": ["sample must be a dict"]}

        # 1. 必需字段存在性
        for field in _REQUIRED_FIELDS:
            if field not in sample:
                errors.append(f"missing required field: {field}")
            elif sample[field] is None:
                errors.append(f"null required field: {field}")

        # 2. 字段类型校验（仅在字段存在时校验，避免重复报错）
        if "id" in sample and sample["id"] is not None:
            if not isinstance(sample["id"], str) or not sample["id"].strip():
                errors.append("field 'id' must be non-empty string")
        if "user_message" in sample and sample["user_message"] is not None:
            if not isinstance(sample["user_message"], str) or not sample["user_message"].strip():
                errors.append("field 'user_message' must be non-empty string")
        if "algorithm_result" in sample and sample["algorithm_result"] is not None:
            if not isinstance(sample["algorithm_result"], dict):
                errors.append("field 'algorithm_result' must be dict")

        # 3. 标签一致性：有 label 必须有 label_source
        label = sample.get("label")
        label_source = sample.get("label_source")
        if label is not None and label != "":
            if not label_source:
                errors.append("field 'label_source' required when 'label' is set")

        return {"valid": len(errors) == 0, "errors": errors}
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"validate_sample 异常，FAIL-OPEN: {e}\n{stack}")
        return {
            "valid": False,
            "errors": [f"validate_exception: {type(e).__name__}: {e}"],
        }


def validate_dataset(dataset: list) -> dict:
    """检查数据集整体质量

    校验项:
        1. 数据集非空且为 list
        2. 每条样本通过 validate_sample
        3. 标签分布平衡性（单一标签占比不超过 _LABEL_BALANCE_MAX_RATIO）
        4. 数据集规模（低于 _MIN_DATASET_SIZE 时 quality_score 打折）

    输入:
        dataset: list[dict] — 训练数据集

    输出:
        {valid: bool, quality_score: float, issues: list[str]}

    FAIL-OPEN: 异常返回 valid=False, quality_score=0.0
    """
    issues: list[str] = []
    try:
        if not isinstance(dataset, list):
            return {
                "valid": False,
                "quality_score": 0.0,
                "issues": ["dataset must be a list"],
            }

        if len(dataset) == 0:
            return {
                "valid": False,
                "quality_score": 0.0,
                "issues": ["empty dataset"],
            }

        # 1. 逐条校验
        invalid_count = 0
        label_counts: dict[str, int] = {}
        labeled_count = 0
        for idx, sample in enumerate(dataset):
            result = validate_sample(sample if isinstance(sample, dict) else {})
            if not result["valid"]:
                invalid_count += 1
                # 只记录前 3 条错误，避免日志膨胀
                if len(issues) < 3:
                    issues.append(
                        f"sample#{idx} invalid: {'; '.join(result['errors'][:2])}"
                    )
            # 统计标签分布（仅已标注样本）
            if isinstance(sample, dict):
                label = sample.get("label")
                if label is not None and label != "":
                    labeled_count += 1
                    label_key = str(label)
                    label_counts[label_key] = label_counts.get(label_key, 0) + 1

        # 2. 标签分布平衡性
        max_ratio = 0.0
        if labeled_count > 0:
            max_count = max(label_counts.values())
            max_ratio = max_count / labeled_count
            if max_ratio > _LABEL_BALANCE_MAX_RATIO:
                dominant_label = max(label_counts, key=label_counts.get)
                issues.append(
                    f"label imbalance: '{dominant_label}' occupies "
                    f"{max_ratio:.1%} (threshold {_LABEL_BALANCE_MAX_RATIO:.0%})"
                )

        # 3. 数据集规模
        size_penalty = 0.0
        if len(dataset) < _MIN_DATASET_SIZE:
            size_penalty = 0.2
            issues.append(
                f"dataset too small: {len(dataset)} < {_MIN_DATASET_SIZE}"
            )

        # 4. quality_score 计算
        #    基础分 1.0 - 无效样本比例 - 标签不平衡惩罚 - 规模惩罚
        invalid_ratio = invalid_count / len(dataset) if dataset else 1.0
        imbalance_penalty = max(0.0, (max_ratio - _LABEL_BALANCE_MAX_RATIO)) if labeled_count > 0 else 0.0
        quality_score = max(
            0.0,
            1.0 - invalid_ratio - imbalance_penalty - size_penalty,
        )

        # 整体 valid：无无效样本 + 无标签不平衡
        valid = invalid_count == 0 and (
            labeled_count == 0 or max_ratio <= _LABEL_BALANCE_MAX_RATIO
        )

        return {
            "valid": valid,
            "quality_score": round(quality_score, 4),
            "issues": issues,
        }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"validate_dataset 异常，FAIL-OPEN: {e}\n{stack}")
        return {
            "valid": False,
            "quality_score": 0.0,
            "issues": [f"validate_exception: {type(e).__name__}: {e}"],
        }
