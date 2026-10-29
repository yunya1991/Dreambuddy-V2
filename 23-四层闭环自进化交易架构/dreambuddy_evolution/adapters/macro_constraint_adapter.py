"""40-周期神经网络系统 宏观约束只读适配器（路2 上下文注入）。

SPEC 路径2：40 主链路产出 cycle_state.json → 23 自进化系统宏观约束层上下文。
原则：单向依赖不回写——本模块只读取 40 产出物，绝不写回；
fail-open：40 产出物缺失/损坏/过期时返回空 dict，不影响 23 主链路。

用法（data_pipeline 注入点）：
    from dreambuddy_evolution.adapters.macro_constraint_adapter import load_macro_constraint
    kline_data["macro_constraint"] = load_macro_constraint()
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("dc.macro_constraint")

_CYCLE_STATE_PATH = "/home/luke/dreambuddy/40-周期神经网络系统/cycle_state.json"
_MAX_AGE_HOURS = 72  # 超过 72h 视为过期，返回空（fail-open）


def _parse_ts(ts):
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def load_macro_constraint(path: str = _CYCLE_STATE_PATH) -> dict:
    """只读加载 40 系统 cycle_state 宏观约束上下文。

    返回精简约束视图（不含 40 系统内部细节）：
      {available, stale, quadrant, quadrant_confidence, real_cycle_state,
       technical_anchor_btc_above, transmission_state, note}
    任何异常返回 {available: False}（fail-open）。
    """
    try:
        if not os.path.exists(path):
            return {"available": False, "note": "cycle_state 不存在（fail-open）"}
        with open(path, encoding="utf-8") as f:
            cs = json.load(f)
        gen = _parse_ts(cs.get("generated_at"))
        stale = True
        age_h = None
        if gen is not None:
            age_h = (datetime.now(timezone.utc) - gen).total_seconds() / 3600.0
            stale = age_h > _MAX_AGE_HOURS
        if stale:
            return {"available": False, "stale": True, "age_hours": age_h,
                    "note": "cycle_state 过期（fail-open）"}
        # 精简约束视图（只暴露 23 系统需要的宏观约束字段）
        ta = (cs.get("technical_anchor") or {}).get("assets", {}).get("BTC/USDT", {})
        return {
            "available": True,
            "stale": False,
            "age_hours": round(age_h, 1) if age_h is not None else None,
            "real_cycle_state": (cs.get("real_cycle") or {}).get("state"),
            "technical_anchor_btc_above": ta.get("above"),
            "transmission_state": (cs.get("sector_transmission") or {}).get("state"),
            "source": "40-周期神经网络系统/cycle_state.json",
            "note": "宏观约束上下文（只读，单向依赖不回写）；只产建议不产交易信号",
        }
    except Exception as e:
        logger.warning("[macro_constraint] 加载失败（fail-open）: %s", e)
        return {"available": False, "note": f"加载异常（fail-open）: {e}"}


if __name__ == "__main__":
    print(json.dumps(load_macro_constraint(), ensure_ascii=False, indent=2))
