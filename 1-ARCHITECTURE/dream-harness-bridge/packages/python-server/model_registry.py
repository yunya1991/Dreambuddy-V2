"""dream-harness-bridge P0-5 模型版本注册表

Layer 训练闭环 — 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-5
对应事件: model.update（model_id/version/rollout_strategy）

设计原则:
    - FAIL-OPEN: 任何异常返回 degraded=True，不阻塞调用方
    - HC-3: 模型注册表主权归 DreamOS，统一写入 ~/.workbuddy/model_registry/
    - HC-9: 只记录模型元数据，不做交易判断
    - 版本化 + 可回滚：每条记录含 model_id / version / trained_at / metrics / dataset_size / training_params

IPC handler:
    handle_publish_model_update(params) → 注册新模型版本到 registry.jsonl

数据目录: ~/.workbuddy/model_registry/
    registry.jsonl — 模型版本注册表（每行一个 JSON 记录，追加写入）
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
try:
    from server import _send_stderr
except ImportError:
    # 独立运行时 fallback
    import sys
    _send_stderr = lambda level, msg: sys.stderr.write(  # noqa: E731
        f"[{level}] {msg}\n"
    )

# 模型注册表目录（HC-3 单一真相源：DreamOS 拥有模型主权）
_MODEL_REGISTRY_DIR = Path.home() / ".workbuddy" / "model_registry"
_REGISTRY_FILE = _MODEL_REGISTRY_DIR / "registry.jsonl"


def _ensure_dir() -> None:
    """确保模型注册表目录存在（FAIL-OPEN：失败仅记日志）"""
    try:
        _MODEL_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        _send_stderr("WARN", f"model_registry 创建目录失败: {e}")


def handle_publish_model_update(params: dict) -> dict:
    """注册新模型版本到 registry.jsonl

    输入 params:
        model_id: str          — 模型唯一标识（如 "intent_classifier_v1"）
        version: str           — 版本号（如 "1.0.0"）
        metrics: dict          — 训练指标（如 {"accuracy": 0.85, "f1": 0.82}）
        dataset_size: int      — 训练数据集大小
        training_params: dict — 训练超参（如 {"epochs": 10, "lr": 1e-4}）
        （可选）trained_at: str     — 训练时间（未提供则用当前时间）
        （可选）rollout_strategy: str — 灰度发布策略

    输出:
        {registered, model_id, version, record_id, degraded, reason?}

    数据格式（每行一条 JSONL）:
        {model_id, version, trained_at, metrics, dataset_size, training_params,
         rollout_strategy, record_id, registered_at}

    FAIL-OPEN: 任何异常返回 degraded=True，不阻塞调用方
    """
    try:
        _ensure_dir()

        model_id = params.get("model_id") or f"unknown_{uuid.uuid4().hex[:8]}"
        version = params.get("version") or "0.0.0"
        metrics = params.get("metrics") or {}
        dataset_size = params.get("dataset_size", 0)
        training_params = params.get("training_params") or {}
        trained_at = params.get("trained_at") or time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        rollout_strategy = params.get("rollout_strategy", "canary_10pct")
        record_id = str(uuid.uuid4())
        registered_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record = {
            "model_id": model_id,
            "version": version,
            "trained_at": trained_at,
            "metrics": metrics,
            "dataset_size": dataset_size,
            "training_params": training_params,
            "rollout_strategy": rollout_strategy,
            "record_id": record_id,
            "registered_at": registered_at,
        }

        try:
            with open(_REGISTRY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            _send_stderr("WARN", f"model_registry 写入 registry.jsonl 失败: {e}")
            return {
                "registered": False,
                "model_id": model_id,
                "version": version,
                "record_id": record_id,
                "degraded": True,
                "reason": f"{type(e).__name__}: {e}",
            }

        return {
            "registered": True,
            "model_id": model_id,
            "version": version,
            "record_id": record_id,
            "degraded": False,
        }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"publish_model_update 失败，FAIL-OPEN: {e}\n{stack}")
        return {
            "registered": False,
            "model_id": params.get("model_id"),
            "version": params.get("version"),
            "record_id": None,
            "degraded": True,
            "reason": f"{type(e).__name__}: {e}",
        }
