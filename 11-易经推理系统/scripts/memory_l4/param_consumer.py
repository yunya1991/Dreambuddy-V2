#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""11 层参数消费者（WP-R1 N5，SPEC-M1 M11）。

对齐 23/43 param_consumer 契约，但**真实应用**参数到 11 的阈值/仓位系数：
- 读取 42 层 ParamGovernor 订阅分发视图
  （42-神经网络交易协调层/runtime/param_dispatch/11-bcrm.json）
- 提取 long_threshold_multiplier / position_size_factor，校验范围
- 原子写入 11/runtime/param_governor_override.json（polling_trader 启动时加载覆盖）

FAIL-OPEN：
- 视图缺失/损坏/格式非法 → 返回 unavailable，**不改动**已有 override（避免抖动回滚）
- 参数越界 → 拒绝该参数，保留上一次有效值

用法：python3 param_consumer.py
"""

import json
import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
_11_ROOT = os.path.dirname(os.path.dirname(_ROOT))  # 11-易经推理系统
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(_11_ROOT)

CONSUMER_NAME = "11-bcrm"

# 42 分发视图路径
_DEFAULT_VIEW = os.path.join(
    _DREAMBUDDY_ROOT,
    "42-神经网络交易协调层",
    "runtime",
    "param_dispatch",
    "{}.json".format(CONSUMER_NAME),
)

# 11 侧 override 落盘路径（polling_trader 读此文件覆盖阈值/仓位）
_DEFAULT_OVERRIDE = os.path.join(_11_ROOT, "runtime", "param_governor_override.json")
_DEFAULT_LOG = os.path.join(_11_ROOT, "runtime", "param_consumption_log.jsonl")

# 42 param_governor 定义的参数范围（§4.1）
_PARAM_RANGES = {
    "long_threshold_multiplier": (1.0, 2.0),
    "position_size_factor": (0.3, 1.0),
}


def load_override(override_path: str = None) -> dict:
    """加载当前生效的 governor override（缺失返回空 dict）。

    polling_trader 启动时调用：若返回非空，则用其中的
    long_threshold_multiplier / position_size_factor 覆盖内部默认值。
    """
    path = override_path or _DEFAULT_OVERRIDE
    try:
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def consume(view_path: str = None, override_path: str = None, log_path: str = None) -> dict:
    """消费 42 分发视图，校验并写入 override（FAIL-OPEN）。

    返回 {status, consumer, version, ...}：
      applied     — 视图合法，override 已更新
      unavailable — 视图缺失/损坏/格式非法（override 保持不变）
    """
    view_path = view_path or _DEFAULT_VIEW
    override_path = override_path or _DEFAULT_OVERRIDE
    log_path = log_path or _DEFAULT_LOG

    # ── 读取视图（FAIL-OPEN）──
    try:
        with open(view_path, encoding="utf-8") as f:
            view = json.load(f)
        if not isinstance(view, dict) or "params" not in view:
            return _log_and_return(
                {"status": "unavailable", "reason": "视图格式非法（fail-open）"},
                log_path,
            )
    except Exception as exc:  # noqa: BLE001
        return _log_and_return(
            {"status": "unavailable", "reason": "视图缺失/损坏（fail-open）: {}".format(exc)},
            log_path,
        )

    params = view.get("params") or {}
    if not isinstance(params, dict):
        return _log_and_return(
            {"status": "unavailable", "reason": "params 字段非法（fail-open）"},
            log_path,
        )

    # ── 校验参数范围 ──
    applied = {}
    for key, (lo, hi) in _PARAM_RANGES.items():
        val = params.get(key)
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if lo <= val <= hi:
            applied[key] = val
        # 越界 → 跳过该参数（保留上一次 override 中的值）

    # ── 合并：新值覆盖旧值，未提供/越界的保留旧值 ──
    existing = load_override(override_path)
    merged = dict(existing)
    merged.update(applied)
    merged["version"] = view.get("version")
    merged["applied_at"] = datetime.now(timezone.utc).isoformat()
    merged["source"] = "42-param_governor"

    # ── 原子写入 override ──
    try:
        os.makedirs(os.path.dirname(override_path), exist_ok=True)
        tmp = override_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        os.replace(tmp, override_path)
    except Exception as exc:  # noqa: BLE001
        return _log_and_return(
            {"status": "fail-open", "reason": "override 写入失败: {}".format(exc)},
            log_path,
        )

    return _log_and_return(
        {
            "status": "applied",
            "consumer": CONSUMER_NAME,
            "version": view.get("version"),
            "applied_params": applied,
        },
        log_path,
    )


def _log_and_return(result: dict, log_path: str) -> dict:
    """追加消费日志后返回 result（日志失败不影响返回）。"""
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "consumer": CONSUMER_NAME,
            **result,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
    return result


if __name__ == "__main__":
    print(json.dumps(consume(), ensure_ascii=False, indent=2))
    sys.exit(0)
