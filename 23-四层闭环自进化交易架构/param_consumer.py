#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""23 层参数消费者 stub（P1-06，SPEC-49 §13.5）。

只读 42 层 ParamGovernor 订阅分发视图
（42-神经网络交易协调层/runtime/param_dispatch/23-contradiction.json），
追加本地消费日志（runtime/param_consumption_log.jsonl）。

- FAIL-OPEN：视图缺失/损坏 → 返回 unavailable，不抛异常，不影响裁决
- stub 语义：仅证明"消费可观测"，不将参数接入任何裁决逻辑（默认不改变裁决）

用法：python3 param_consumer.py
"""

import json
import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(_ROOT)

CONSUMER_NAME = "23-contradiction"
_DEFAULT_VIEW = os.path.join(
    _DREAMBUDDY_ROOT,
    "42-神经网络交易协调层",
    "runtime",
    "param_dispatch",
    "{}.json".format(CONSUMER_NAME),
)
_DEFAULT_LOG = os.path.join(_ROOT, "runtime", "param_consumption_log.jsonl")


def consume(view_path: str = None, log_path: str = None) -> dict:
    """只读参数视图并追加消费日志（FAIL-OPEN）。返回 {status, ...}。"""
    view_path = view_path or _DEFAULT_VIEW
    log_path = log_path or _DEFAULT_LOG
    try:
        with open(view_path, encoding="utf-8") as f:
            view = json.load(f)
        if not isinstance(view, dict) or "params" not in view:
            return {"status": "unavailable", "reason": "视图格式非法（fail-open）"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "reason": "视图缺失/损坏（fail-open）: {}".format(exc)}

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "consumer": CONSUMER_NAME,
        "version": view.get("version"),
        "topics": view.get("topics"),
        "view_path": view_path,
        "note": "P1-06 stub：仅观测记录，参数未接入裁决",
    }
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail-open", "reason": "消费日志写入失败: {}".format(exc)}
    return {"status": "consumed", "consumer": CONSUMER_NAME, "version": view.get("version")}


if __name__ == "__main__":
    print(json.dumps(consume(), ensure_ascii=False, indent=2))
    sys.exit(0)
