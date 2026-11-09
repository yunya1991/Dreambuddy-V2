"""M4-2/M4-4: 反射弧触发门（SPEC-M3 §2.1/§2.3）。

- M4-2 龙头监控门：|F_macro(BTC)| ≥ 0.4 → 提交 P0 龙头任务
- M4-4 salience 门：微观信号置信度 ≥ 0.6 → 提交 P1 任务（受每源配额限制）

依赖 42 task_dispatcher。fail-open：dispatcher 不可用 / F_macro 缺失时静默跳过。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 跨模块导入 42 task_dispatcher（fail-open）
try:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    _42_PATH = str(_REPO_ROOT / "42-神经网络交易协调层")
    if _42_PATH not in sys.path:
        sys.path.insert(0, _42_PATH)
    from task_dispatcher import TaskDispatcher  # type: ignore

    _HAS_DISPATCHER = True
except Exception:  # noqa: BLE001
    TaskDispatcher = None  # type: ignore
    _HAS_DISPATCHER = False

from core.macro_force import MacroForce  # noqa: E402

# M4-2 龙头门阈值
MACRO_LED_THRESHOLD = 0.4
# M4-4 salience 阈值
SALIENCE_CONFIDENCE_THRESHOLD = 0.6


def _get_dispatcher() -> TaskDispatcher | None:
    if not _HAS_DISPATCHER:
        return None
    try:
        return TaskDispatcher()
    except Exception:  # noqa: BLE001
        return None


# ══════════════════════════════════════════════════════════════════
# M4-2: 龙头监控门
# ══════════════════════════════════════════════════════════════════


def check_macro_led_gate(macro_forces: dict[str, MacroForce]) -> dict[str, Any]:
    """检查龙头（BTC）宏观力是否越过阈值，越过则提交 P0 任务。

    返回 {"triggered": bool, "f_macro_btc": float, "task_id": str|None}。
    """
    btc = macro_forces.get("BTC")
    f_macro = btc.d1_trend if btc else 0.0
    result = {"triggered": False, "f_macro_btc": f_macro, "task_id": None}

    if abs(f_macro) < MACRO_LED_THRESHOLD:
        return result

    dispatcher = _get_dispatcher()
    if dispatcher is None:
        return result

    try:
        task = dispatcher.submit(
            symbol="BTC/USDT",
            trigger="macro_led",
            priority="P0",
            requester="50-macro-force",
            reason=f"F_macro(BTC)={f_macro:+.3f} crossed threshold {MACRO_LED_THRESHOLD}",
            targets=["11-bcrm-tactical", "11-bdsm", "11-washout"],
        )
        if task is not None:
            result["triggered"] = True
            result["task_id"] = task.task_id
    except Exception:  # noqa: BLE001
        pass
    return result


# ══════════════════════════════════════════════════════════════════
# M4-4: salience 门
# ══════════════════════════════════════════════════════════════════


def check_salience_gate(evidences: list[dict[str, Any]]) -> dict[str, Any]:
    """微观显著信号门：置信度 ≥ 0.6 的信号提交 P1 任务（受每源配额限制）。

    返回 {"triggered": list of {source, confidence, task_id}}。
    """
    triggered: list[dict[str, Any]] = []
    dispatcher = _get_dispatcher()
    if dispatcher is None:
        return {"triggered": triggered}

    seen_sources: set[str] = set()
    for ev in evidences:
        conf = float(ev.get("confidence") or 0.0)
        if conf < SALIENCE_CONFIDENCE_THRESHOLD:
            continue
        source = str(ev.get("source") or "unknown")
        if source in seen_sources:
            continue  # 同源只提一次
        seen_sources.add(source)

        try:
            task = dispatcher.submit(
                symbol=str(ev.get("symbol") or "MULTI"),
                trigger="micro_led",
                priority="P1",
                requester="50-salience",
                reason=f"micro signal {source} confidence={conf:.3f} >= {SALIENCE_CONFIDENCE_THRESHOLD}",
                targets=[source],
                salience_source=source,
            )
            if task is not None:
                triggered.append({"source": source, "confidence": conf, "task_id": task.task_id})
        except Exception:  # noqa: BLE001
            pass
    return {"triggered": triggered}
