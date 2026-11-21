"""执行器：作业 → 手机指令，状态机 + 安全门禁（不代付、不锁座、一次性）。

P0 变化：
- 状态机区分「等人工 / 人工接管 / 订单未知」，不再把三者混成 unknown。
- 回执结构化：trace_id / stage / screenshot / page_text / order_id。
- 下单阶段响应不确定 → order_unknown，禁止自动重试（须对账收敛）。
"""

from __future__ import annotations

import time

import security
from phone_adapters import CommandError, get_adapter
from phone_tools import build_step

PAGE_TEXT_LIMIT = 2000

# 触发「订单未知」的阶段：这些阶段之后响应不确定，可能已产生订单
ORDER_STAGES = ("accept", "order_confirm", "submit", "cashier", "payment_pause", "pay")

RECEIPT_SCHEMA = "mra.receipt.v1"
RECEIPT_REQUIRED = ("trace_id", "stage", "screenshot", "page_text", "order_id")


class GateDenied(Exception):
    """门禁拒绝：不满足下发条件。"""


# 手机回执状态 → 作业状态
RESULT_STATE_MAP = {
    "ok": "done",
    "success": "done",
    "done": "done",
    "needs_human": "pending_human",
    "pending_human": "pending_human",
    "takeover": "takeover",
    "needs_login": "takeover",
    "login": "takeover",
    "order_unknown": "order_unknown",
    "captcha": "cooldown",
    "risk": "cooldown",
    "blocked": "cooldown",
    "rejected": "failed",
    "error": "failed",
    "failed": "failed",
}


def _generic_command(job: dict) -> dict:
    return {
        "job_id": job.get("_id"),
        "adapter": job.get("adapter", ""),
        "app": "",
        "target": job.get("target") or {},
        "max_price": job.get("max_price"),
        "steps": [
            build_step("goto_order_page"),
            build_step("stop", reason="await_human_confirm"),
        ],
        "stop_before": "payment",
    }


def build_command(job: dict) -> dict:
    """把作业翻译为手机指令；未登记平台走通用占位（仍强制停在支付前）。"""
    try:
        adapter = get_adapter(job.get("adapter", ""))
    except KeyError:
        command = _generic_command(job)
    else:
        try:
            command = adapter.describe(job)
        except CommandError as exc:
            raise GateDenied("bad_command: {}".format(exc)) from None
    command["trace_id"] = str(job.get("_trace_id") or "") or _new_trace_id(job)
    command["receipt"] = {"schema": RECEIPT_SCHEMA, "required": list(RECEIPT_REQUIRED)}
    return command


def _new_trace_id(job: dict) -> str:
    return "{}-{}-{}".format(
        job.get("_id"), str(job.get("fingerprint") or "")[:8], int(time.time() * 1000)
    )


def ensure_executable(job: dict, store, env=None, paused: bool = False) -> None:
    """下发前三道门禁：暂停 / 执行开关 / 一次性。"""
    if paused:
        raise GateDenied("paused")
    if not security.env_allows_execute(env) or security.is_container():
        raise GateDenied("env")
    if store.blocks_reenqueue(job.get("task_id", ""), job.get("fingerprint", "")):
        raise GateDenied("already_terminal")


def normalize_receipt(detail: dict | None, trace_id: str = "") -> dict:
    """结构化回执：补齐五个必备字段，其余证据原样保留；page_text 截断防爆库。"""
    source = dict(detail or {})
    normalized = {
        "trace_id": str(source.get("trace_id") or trace_id or ""),
        "stage": str(source.get("stage") or ""),
        "screenshot": str(source.get("screenshot") or ""),
        "page_text": str(source.get("page_text") or "")[:PAGE_TEXT_LIMIT],
        "order_id": str(source.get("order_id") or ""),
    }
    for key, value in source.items():
        if key not in normalized:
            normalized[key] = value
    return normalized


def _in_order_stage(detail: dict | None) -> bool:
    return str((detail or {}).get("stage") or "") in ORDER_STAGES


def normalize_result_state(raw: str, detail: dict | None = None) -> str:
    """回执状态归一；下单阶段报错视为结果不确定 → order_unknown（不得自动重试）。"""
    state = RESULT_STATE_MAP.get((raw or "").strip().lower(), "unknown")
    if state == "failed" and _in_order_stage(detail):
        return "order_unknown"
    return state


def apply_result(store, job_id: int, device_id: str, raw_state: str, detail: dict | None = None) -> dict:
    """落库手机回执：更新作业状态、写结构化结果与事件。

    幂等：同一 trace_id + 同一归一状态重复回传时只记一次，避免设备重试导致状态翻转。
    """
    receipt = normalize_receipt(detail)
    state = normalize_result_state(raw_state, receipt)
    latest = store.latest_result(job_id)
    if (
        latest
        and receipt["trace_id"]
        and latest.get("trace_id") == receipt["trace_id"]
        and latest.get("state") == state
    ):
        return {"job_id": job_id, "state": state, "trace_id": receipt["trace_id"], "duplicate": True}
    store.set_job_state(job_id, state, device_id)
    store.add_result(
        job_id,
        device_id,
        state,
        receipt,
        trace_id=receipt["trace_id"],
        stage=receipt["stage"],
        screenshot=receipt["screenshot"],
        order_id=receipt["order_id"],
    )
    level = "info" if state == "done" else "warn"
    store.add_event(
        level,
        "result_{}".format(state),
        None,
        {"job_id": job_id, "device_id": device_id, "trace_id": receipt["trace_id"], "stage": receipt["stage"]},
    )
    if state == "order_unknown":
        store.add_event(
            "warn",
            "order_unknown_pending_reconcile",
            None,
            {"job_id": job_id, "trace_id": receipt["trace_id"], "order_id": receipt["order_id"]},
        )
    return {"job_id": job_id, "state": state, "trace_id": receipt["trace_id"]}
