#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""42 层弹性约束参数下发通道 ParamGovernor（SPEC §四，最小实现）。

职责（42 层 SPEC §4.4 下发方式）：
- params_active.json：当前生效参数集（子系统适配器只读该文件）
- params_history.jsonl：变更历史（每次变更追加，可审计可回滚）
- 初始版本：全部默认值（v1.0 冻结，§4.1 预注册参数集）
- fail-open：文件缺失/损坏/超期 → 子系统使用本地默认值（子系统侧负责）

安全红线（§4.3）：
1. 参数只做收紧方向的弹性约束，不做放大方向
2. 单次变更不超过 weight_adjust_limit（±5%），冷却期内不重复调整
3. 参数集版本化，每次变更记录变更原因，可审计可回滚
4. 13 系统门禁优先：任何参数不得放宽或绕过 13-通用风控模块门禁

用法：python3 param_governor.py（生成/刷新 params_active.json）
"""

import json
import os
import sys
from datetime import datetime, timezone

_42_ROOT = os.path.dirname(os.path.abspath(__file__))
PARAMS_ACTIVE_PATH = os.path.join(_42_ROOT, "runtime", "params_active.json")
PARAMS_HISTORY_PATH = os.path.join(_42_ROOT, "runtime", "params_history.jsonl")

# §4.1 预注册参数集（v1.0 冻结，禁止调整）
DEFAULT_PARAMS = {
    "long_threshold_multiplier": 1.0,  # 分支多头开仓阈值系数（1.0-2.0）
    "position_size_factor": 1.0,  # 分支仓位系数（0.3-1.0）
    "long_short_ratio_cap": None,  # 多空比上限（各系统默认，只收紧不放宽）
    "weight_adjust_limit": 0.05,  # 单次权重调整限幅 ±5%（固定）
    "cooldown_period_hours": 24,  # 权重调整冷却期（≥12h）
    "risk_budget_ratio": {},  # 各分支风险预算占比（按初始分配，只收紧不放大）
}

# 参数调节范围（§4.1，校验用）
_PARAM_RANGES = {
    "long_threshold_multiplier": (1.0, 2.0),
    "position_size_factor": (0.3, 1.0),
}

# §4.3 红线1：收紧方向（+1=上调为收紧，-1=下调为收紧）
_TIGHTEN_DIRECTION = {
    "long_threshold_multiplier": 1,
    "position_size_factor": -1,
}

# P1-06：订阅分发主题（registry subscribe 声明中含其一即为参数订阅者）
_PARAM_TOPICS = ("elastic_params", "risk_budget")

# P1-06：分发产物路径
PARAM_DISPATCH_DIR = os.path.join(_42_ROOT, "runtime", "param_dispatch")
PARAM_DISPATCH_LOG = os.path.join(_42_ROOT, "runtime", "param_dispatch_log.jsonl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_active(active_path: str = None) -> dict:
    """只读加载当前生效参数集（fail-open 返回默认值）。"""
    try:
        with open(active_path or PARAMS_ACTIVE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "params" in data:
            return data
    except Exception:
        pass
    return _default_doc("fail-open：params_active.json 缺失/损坏，返回默认参数集")


def _default_doc(note: str = "初始版本") -> dict:
    return {
        "version": "v1.0",
        "generated_at": _now_iso(),
        "params": dict(DEFAULT_PARAMS),
        "note": "42 层 ParamGovernor 参数集（SPEC §4.1 预注册默认值）；{}".format(note),
    }


def write_active(doc: dict, active_path: str = None) -> None:
    """原子写入 params_active.json（写临时文件 + rename）。"""
    path = active_path or PARAMS_ACTIVE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_history(entry: dict, history_path: str = None) -> None:
    """追加变更历史（params_history.jsonl）。"""
    path = history_path or PARAMS_HISTORY_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def init_params(
    reason: str = "P2 阶段初始下发：全部默认值（v1.0 冻结）",
    active_path: str = None,
    history_path: str = None,
) -> dict:
    """生成初始参数集并落盘（幂等：已存在则跳过，除非 force）。"""
    path = active_path or PARAMS_ACTIVE_PATH
    if os.path.exists(path):
        try:
            existing = load_active(path)
            return {"status": "exists", "doc": existing}
        except Exception:
            pass
    doc = _default_doc()
    write_active(doc, path)
    append_history(
        {
            "ts": doc["generated_at"],
            "action": "init",
            "version": doc["version"],
            "reason": reason,
            "params": doc["params"],
        },
        history_path,
    )
    return {"status": "created", "doc": doc}


# ── P1-06：发布（非默认参数）+ 订阅分发 stub ──


def dispatch_enabled() -> bool:
    """P1-06 开关：ENABLE_PARAM_DISPATCH=1 才允许发布/分发（默认关=回滚路径）。"""
    return os.environ.get("ENABLE_PARAM_DISPATCH") == "1"


def _version_bump(version: str) -> str:
    """v1.0 → v1.1（次版本递增；非法版本回退 v1.1）。"""
    try:
        major, minor = str(version).lstrip("v").split(".")[:2]
        return "v{}.{}".format(int(major), int(minor) + 1)
    except Exception:
        return "v1.1"


def _last_adjust_ts(history_path: str):
    """历史中最近一次 adjust 时间（无则 None）。"""
    path = history_path or PARAMS_HISTORY_PATH
    try:
        last = None
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("action") == "adjust":
                    last = entry.get("ts")
        if last:
            ts = datetime.fromisoformat(last)
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        pass
    return None


def adjust_params(
    updates: dict,
    reason: str,
    active_path: str = None,
    history_path: str = None,
) -> dict:
    """发布非默认参数（P1-06）。红线：只收紧不放大；单次 ≤ weight_adjust_limit；冷却期内拒绝。"""
    if not dispatch_enabled():
        return {"status": "disabled", "reason": "ENABLE_PARAM_DISPATCH 未设置为 1（回滚路径）"}
    if not isinstance(updates, dict) or not updates:
        return {"status": "rejected", "reason": "updates 为空"}

    doc = load_active(active_path)
    params = doc["params"]
    limit = float(params.get("weight_adjust_limit") or 0.05)

    for key, value in updates.items():
        if key not in _PARAM_RANGES:
            return {"status": "rejected", "reason": "参数 {} 不支持调整（§4.1 冻结）".format(key)}
        try:
            new_val = float(value)
        except (TypeError, ValueError):
            return {"status": "rejected", "reason": "参数 {} 取值非法: {}".format(key, value)}
        lo, hi = _PARAM_RANGES[key]
        if not (lo <= new_val <= hi):
            return {"status": "rejected", "reason": "参数 {} 超出范围 [{}, {}]".format(key, lo, hi)}
        old_val = float(params.get(key))
        delta = new_val - old_val
        if abs(delta) > limit + 1e-12:
            return {
                "status": "rejected",
                "reason": "参数 {} 单次变更 |{}| 超过限幅 {}".format(key, round(delta, 6), limit),
            }
        # 红线1：只收紧不放大
        if delta * _TIGHTEN_DIRECTION[key] < 0:
            return {
                "status": "rejected",
                "reason": "参数 {} 变更为放大方向（红线：只收紧不放大）".format(key),
            }

    # 红线2：冷却期
    cooldown_hours = float(params.get("cooldown_period_hours") or 24)
    last_ts = _last_adjust_ts(history_path)
    if last_ts is not None:
        elapsed = (datetime.now(timezone.utc) - last_ts).total_seconds() / 3600.0
        if elapsed < cooldown_hours:
            return {
                "status": "rejected",
                "reason": "冷却期内（距上次调整 {:.1f}h < {}h）".format(elapsed, cooldown_hours),
            }

    new_params = dict(params)
    new_params.update({k: float(v) for k, v in updates.items()})
    new_doc = {
        "version": _version_bump(doc.get("version", "v1.0")),
        "generated_at": _now_iso(),
        "params": new_params,
        "note": "42 层 ParamGovernor 参数集；P1-06 非默认发布：{}".format(reason),
    }
    write_active(new_doc, active_path)
    append_history(
        {
            "ts": new_doc["generated_at"],
            "action": "adjust",
            "version": new_doc["version"],
            "reason": reason,
            "updates": {k: float(v) for k, v in updates.items()},
            "params": new_params,
        },
        history_path,
    )
    return {"status": "adjusted", "version": new_doc["version"], "params": new_params}


def load_subscribers(registry_path: str = None) -> list:
    """registry.yaml 中声明订阅参数主题的子系统 [(name, topics)]。"""
    import yaml  # 延迟导入：仅分发时需要

    path = registry_path or os.path.join(_42_ROOT, "registry.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            reg = yaml.safe_load(f)
        subscribers = []
        for sub in (reg or {}).get("subsystems") or []:
            if not isinstance(sub, dict) or not sub.get("enabled", True):
                continue
            topics = [t for t in (sub.get("subscribe") or []) if t in _PARAM_TOPICS]
            if topics:
                subscribers.append((sub.get("name"), topics))
        return subscribers
    except Exception:  # noqa: BLE001  fail-open：registry 异常不分发
        return []


def dispatch(
    active_path: str = None,
    registry_path: str = None,
    dispatch_dir: str = None,
    log_path: str = None,
) -> dict:
    """订阅分发 stub（P1-06）：按 registry 订阅声明写各订阅者参数视图 + 分发日志。"""
    if not dispatch_enabled():
        return {"status": "disabled", "reason": "ENABLE_PARAM_DISPATCH 未设置为 1（回滚路径）"}
    out_dir = dispatch_dir or PARAM_DISPATCH_DIR
    log = log_path or PARAM_DISPATCH_LOG
    doc = load_active(active_path)
    subscribers = load_subscribers(registry_path)
    if not subscribers:
        return {"status": "unavailable", "reason": "registry 无参数订阅者（fail-open）"}

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    ts = _now_iso()
    names = []
    for name, topics in subscribers:
        view = {
            "subscriber": name,
            "topics": topics,
            "version": doc.get("version"),
            "generated_at": ts,
            "params": doc.get("params"),
            "note": "P1-06 订阅分发 stub：子系统只读本视图；未消费不影响裁决",
        }
        view_path = os.path.join(out_dir, "{}.json".format(name))
        tmp = view_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(view, f, ensure_ascii=False, indent=2)
        os.replace(tmp, view_path)
        with open(log, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": ts,
                        "subscriber": name,
                        "topics": topics,
                        "version": doc.get("version"),
                        "path": view_path,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        names.append(name)
    return {"status": "dispatched", "version": doc.get("version"), "subscribers": names}


def main() -> int:
    result = init_params()
    doc = result["doc"]
    print(
        json.dumps(
            {
                "status": result["status"],
                "version": doc.get("version"),
                "generated_at": doc.get("generated_at"),
                "params": doc.get("params"),
                "path": PARAMS_ACTIVE_PATH,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
