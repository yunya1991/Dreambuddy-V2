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
    "long_threshold_multiplier": 1.0,   # 分支多头开仓阈值系数（1.0-2.0）
    "position_size_factor": 1.0,        # 分支仓位系数（0.3-1.0）
    "long_short_ratio_cap": None,        # 多空比上限（各系统默认，只收紧不放宽）
    "weight_adjust_limit": 0.05,        # 单次权重调整限幅 ±5%（固定）
    "cooldown_period_hours": 24,         # 权重调整冷却期（≥12h）
    "risk_budget_ratio": {},             # 各分支风险预算占比（按初始分配，只收紧不放大）
}

# 参数调节范围（§4.1，校验用）
_PARAM_RANGES = {
    "long_threshold_multiplier": (1.0, 2.0),
    "position_size_factor": (0.3, 1.0),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_active() -> dict:
    """只读加载当前生效参数集（fail-open 返回默认值）。"""
    try:
        with open(PARAMS_ACTIVE_PATH, encoding="utf-8") as f:
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


def write_active(doc: dict) -> None:
    """原子写入 params_active.json（写临时文件 + rename）。"""
    os.makedirs(os.path.dirname(PARAMS_ACTIVE_PATH), exist_ok=True)
    tmp = PARAMS_ACTIVE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PARAMS_ACTIVE_PATH)


def append_history(entry: dict) -> None:
    """追加变更历史（params_history.jsonl）。"""
    os.makedirs(os.path.dirname(PARAMS_HISTORY_PATH), exist_ok=True)
    with open(PARAMS_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def init_params(reason: str = "P2 阶段初始下发：全部默认值（v1.0 冻结）") -> dict:
    """生成初始参数集并落盘（幂等：已存在则跳过，除非 force）。"""
    if os.path.exists(PARAMS_ACTIVE_PATH):
        try:
            existing = load_active()
            return {"status": "exists", "doc": existing}
        except Exception:
            pass
    doc = _default_doc()
    write_active(doc)
    append_history({
        "ts": doc["generated_at"],
        "action": "init",
        "version": doc["version"],
        "reason": reason,
        "params": doc["params"],
    })
    return {"status": "created", "doc": doc}


def main() -> int:
    result = init_params()
    doc = result["doc"]
    print(json.dumps({
        "status": result["status"],
        "version": doc.get("version"),
        "generated_at": doc.get("generated_at"),
        "params": doc.get("params"),
        "path": PARAMS_ACTIVE_PATH,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
