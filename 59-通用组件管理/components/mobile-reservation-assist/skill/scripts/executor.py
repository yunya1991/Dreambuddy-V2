"""执行器：作业 → 手机指令，状态机 + 安全门禁（不代付、不锁座、一次性）。"""

from __future__ import annotations

import security
from phone_adapters import CommandError, get_adapter


class GateDenied(Exception):
    """门禁拒绝：不满足下发条件。"""


# 手机回执状态 → 作业状态
RESULT_STATE_MAP = {
    "ok": "done",
    "success": "done",
    "needs_human": "unknown",
    "captcha": "cooldown",
    "risk": "cooldown",
    "blocked": "cooldown",
    "rejected": "failed",
    "error": "failed",
}


def _generic_command(job: dict) -> dict:
    return {
        "job_id": job.get("_id"),
        "adapter": job.get("adapter", ""),
        "app": "",
        "target": job.get("target") or {},
        "max_price": job.get("max_price"),
        "steps": [
            {"action": "open_official_app", "adapter": job.get("adapter", "")},
            {"action": "goto_order_page"},
            {"action": "stop", "reason": "await_human_confirm"},
        ],
        "stop_before": "payment",
    }


def build_command(job: dict) -> dict:
    """把作业翻译为手机指令；未登记平台走通用占位（仍强制停在支付前）。"""
    try:
        adapter = get_adapter(job.get("adapter", ""))
    except KeyError:
        return _generic_command(job)
    try:
        return adapter.describe(job)
    except CommandError as exc:
        raise GateDenied("bad_command: {}".format(exc)) from None


def ensure_executable(job: dict, store, env=None, paused: bool = False) -> None:
    """下发前三道门禁：暂停 / 执行开关 / 一次性。"""
    if paused:
        raise GateDenied("paused")
    if not security.env_allows_execute(env) or security.is_container():
        raise GateDenied("env")
    if store.has_terminal(job.get("task_id", ""), job.get("fingerprint", "")):
        raise GateDenied("already_terminal")


def normalize_result_state(raw: str) -> str:
    return RESULT_STATE_MAP.get((raw or "").strip().lower(), "unknown")


def apply_result(
    store, job_id: int, device_id: str, raw_state: str, detail: dict | None = None
) -> dict:
    """落库手机回执：更新作业状态、写结果与事件。"""
    state = normalize_result_state(raw_state)
    store.set_job_state(job_id, state, device_id)
    store.add_result(job_id, device_id, state, detail)
    level = "info" if state == "done" else "warn"
    store.add_event(
        level, "result_{}".format(state), None, {"job_id": job_id, "device_id": device_id}
    )
    return {"job_id": job_id, "state": state}
