"""dream-harness-bridge P0-5 训练数据集管理

Layer 训练闭环 — 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-5

设计原则:
    - FAIL-OPEN: 任何异常返回中性兜底（degraded=True），不阻塞交易热路径
    - HC-3: 训练数据集主权归 DreamOS，统一写入 ~/.workbuddy/training_datasets/
    - HC-9: 只产出标注元数据，不做任何交易判断（不出现 direction/action/rsi/pnl/reward 等）
    - 数据格式: JSONL（每行一个 JSON 样本）

IPC handler:
    handle_request_label(params)         → 接收难例样本，写入 pending.jsonl
    handle_fetch_training_dataset(params) → 读取 labeled.jsonl 已标注数据集

数据目录: ~/.workbuddy/training_datasets/
    pending.jsonl   — 待标注难例（confidence < ACTIVE_LEARNING_DIFFICULTY_THRESHOLD）
    labeled.jsonl   — 已标注样本（供训练拉取）
"""

from __future__ import annotations

import json
import os
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

# 复用 server.py 的 _send_stderr（结构化日志）
# 同目录 import，运行时由 server.py 的 sys.path 保证可导入
try:
    from server import _send_stderr
except ImportError:
    # 独立运行时 fallback
    import sys
    _send_stderr = lambda level, msg: sys.stderr.write(  # noqa: E731
        f"[{level}] {msg}\n"
    )

# 训练数据集目录（HC-3 单一真相源：DreamOS 拥有数据主权）
_TRAINING_DATASETS_DIR = Path.home() / ".workbuddy" / "training_datasets"
_PENDING_FILE = _TRAINING_DATASETS_DIR / "pending.jsonl"
_LABELED_FILE = _TRAINING_DATASETS_DIR / "labeled.jsonl"

# 难例阈值（与 server.py 的 _ACTIVE_LEARNING_DIFFICULTY_THRESHOLD 对齐）
# confidence < 此阈值的样本送 Harness 标注
_ACTIVE_LEARNING_DIFFICULTY_THRESHOLD = 0.55


def _ensure_dir() -> None:
    """确保训练数据目录存在（FAIL-OPEN：失败仅记日志）"""
    try:
        _TRAINING_DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        _send_stderr("WARN", f"training_dataset 创建目录失败: {e}")


def handle_request_label(params: dict) -> dict:
    """接收难例样本（confidence < 0.55），写入 pending.jsonl

    输入 params:
        algorithm_result: dict  — 算法识别结果（含 user_message, intent_type, confidence, tier, ...）
        （可选）label: str          — 若附带标注则直接写入 labeled.jsonl
        （可选）label_source: str   — 标注来源（shadow_review / human / agent）
        （可选）user_message: str   — 用户原始消息（若不在 algorithm_result 中）

    输出:
        {status, sample_id, written, degraded, reason?}

    数据格式（每行一条 JSONL）:
        {id, user_message, algorithm_result, label, label_source, timestamp}

    FAIL-OPEN: 任何异常返回 degraded=True，不阻塞调用方
    """
    try:
        _ensure_dir()

        algorithm_result = params.get("algorithm_result", {}) or {}
        user_message = (
            params.get("user_message")
            or algorithm_result.get("user_message")
            or ""
        )
        label = params.get("label")
        label_source = params.get("label_source", "shadow_review")
        sample_id = str(uuid.uuid4())
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        sample = {
            "id": sample_id,
            "user_message": user_message,
            "algorithm_result": algorithm_result,
            "label": label,
            "label_source": label_source,
            "timestamp": timestamp,
        }

        # 若已附带 label → 直接写入 labeled.jsonl；否则写入 pending.jsonl 待标注
        target_file = _LABELED_FILE if label else _PENDING_FILE

        try:
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        except Exception as e:
            _send_stderr("WARN", f"training_dataset 写入 {target_file.name} 失败: {e}")
            return {
                "status": "degraded",
                "sample_id": sample_id,
                "written": False,
                "degraded": True,
                "reason": f"{type(e).__name__}: {e}",
            }

        return {
            "status": "ok",
            "sample_id": sample_id,
            "written": True,
            "degraded": False,
            "target": target_file.name,
        }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"request_label 失败，FAIL-OPEN: {e}\n{stack}")
        return {
            "status": "degraded",
            "sample_id": None,
            "written": False,
            "degraded": True,
            "reason": f"{type(e).__name__}: {e}",
        }


def handle_fetch_training_dataset(params: dict) -> dict:
    """返回已标注数据集（从 labeled.jsonl 读取）

    输入 params:
        limit: int  — 最大返回样本数（默认 100）

    输出:
        {dataset, count, degraded, reason?}

    FAIL-OPEN: 文件不存在/读取异常返回空数据集 + degraded=True
    """
    try:
        limit = int(params.get("limit", 100))
        if limit <= 0:
            limit = 100

        if not _LABELED_FILE.exists():
            # 文件不存在视为空数据集（非错误，可能尚无标注样本）
            return {
                "dataset": [],
                "count": 0,
                "degraded": False,
                "reason": "labeled.jsonl not_found",
            }

        dataset: list[dict[str, Any]] = []
        try:
            with open(_LABELED_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        dataset.append(json.loads(line))
                    except json.JSONDecodeError:
                        # 跳过损坏行（FAIL-OPEN）
                        continue
                    if len(dataset) >= limit:
                        break
        except Exception as e:
            _send_stderr("WARN", f"training_dataset 读取 labeled.jsonl 失败: {e}")
            return {
                "dataset": [],
                "count": 0,
                "degraded": True,
                "reason": f"{type(e).__name__}: {e}",
            }

        return {
            "dataset": dataset,
            "count": len(dataset),
            "degraded": False,
        }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"fetch_training_dataset 失败，FAIL-OPEN: {e}\n{stack}")
        return {
            "dataset": [],
            "count": 0,
            "degraded": True,
            "reason": f"{type(e).__name__}: {e}",
        }
