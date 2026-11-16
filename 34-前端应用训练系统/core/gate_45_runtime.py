# -*- coding: utf-8 -*-
"""45 门禁生产注入点（GAP-14 / T-L2 P0）。

职责边界
--------
- 只做「开关解析 + transport 组合」，**不定义业务 payload**：
  45 受理要求 category / object_type / object_ref / submitter / purpose /
  spec_id / env_manifest，其中 spec_id 与 env_manifest 属业务口径，
  必须由调用侧通过 ``register_payload_builder`` 注入，禁止在此硬编码默认值。
- 未开启（``DREAM_GATE_45_MODE`` 未设置）、模式非法、未注册 builder、
  或组合异常 → 一律返回 ``None``。此时 ``settle`` 行为与接线前完全一致（H2 字节等价）。

环境变量
--------
- ``DREAM_GATE_45_MODE``：``shadow`` | ``hard``；未设置 = 关闭（默认）。
- ``DREAM_GATE_45_BASE_URL``：45 服务地址，默认 ``http://127.0.0.1:8790``。
- ``DREAM_GATE_45_TIMEOUT_S``：HTTP 超时秒数，默认 5。

mode=hard 仍受 ``gate_45_adapter.GATE_45_HARD_SWITCH``（``enable_gate_45_hard``，
默认 False）约束：未打开该开关时按 shadow 放行。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable, Dict, Mapping, Optional
from urllib.request import Request, urlopen

try:  # 以项目根入 sys.path（data_query_executor 模式）
    from core.gate_45_adapter import GateFn, build_gate_45
except ImportError:  # 以 34/core 直接入 sys.path（settle_case_cli 模式）
    from gate_45_adapter import GateFn, build_gate_45

MODE_ENV = "DREAM_GATE_45_MODE"
BASE_URL_ENV = "DREAM_GATE_45_BASE_URL"
TIMEOUT_ENV = "DREAM_GATE_45_TIMEOUT_S"
DEFAULT_BASE_URL = "http://127.0.0.1:8790"
VALID_MODES = ("shadow", "hard")

PayloadBuilder = Callable[[Dict[str, Any]], Dict[str, Any]]
_payload_builder: Optional[PayloadBuilder] = None


def register_payload_builder(fn: PayloadBuilder) -> None:
    """注册业务 payload 构造器：context -> 45 /submit 请求体。"""
    global _payload_builder
    if not callable(fn):
        raise TypeError("payload_builder 必须可调用")
    _payload_builder = fn


def reset_payload_builder() -> None:
    """清空构造器（测试/热重载用）。"""
    global _payload_builder
    _payload_builder = None


def _idempotency_key(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return "settle-" + hashlib.sha256(blob).hexdigest()[:32]


def _http_submit(base_url: str, timeout: float) -> Callable[[Dict[str, Any]], Optional[str]]:
    def submit(context: Dict[str, Any]) -> Optional[str]:
        payload = _payload_builder(context) if _payload_builder else None
        if not isinstance(payload, dict):
            return None
        req = Request(
            f"{base_url}/api/v1/eval/submit",
            data=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": _idempotency_key(payload),
            },
            method="POST",
        )
        # 内网固定地址，S310 不适用
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8") or "{}")
        return body.get("eval_id")

    return submit


def _http_poll(base_url: str, timeout: float) -> Callable[[str], Dict[str, Any]]:
    def poll(eval_id: str) -> Dict[str, Any]:
        with urlopen(f"{base_url}/api/v1/eval/{eval_id}", timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8") or "{}")

    return poll


def resolve_settle_gate(
    flags: Optional[Dict[str, Any]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[GateFn]:
    """解析 settle 门禁；默认返回 None（关闭，字节等价）。"""
    try:
        env = os.environ if environ is None else environ
        mode = str(env.get(MODE_ENV, "")).strip().lower()
        if mode not in VALID_MODES:
            return None
        if _payload_builder is None:  # 无业务 payload 构造器 → 不伪造请求
            return None
        base_url = str(env.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
        try:
            timeout = float(env.get(TIMEOUT_ENV, "5"))
        except (TypeError, ValueError):
            timeout = 5.0
        config = {
            "mode": mode,
            "submit_fn": _http_submit(base_url, timeout),
            "poll_fn": _http_poll(base_url, timeout),
        }
        return build_gate_45(config, flags)
    except Exception:  # FAIL-OPEN：解析失败退回无门禁
        return None
